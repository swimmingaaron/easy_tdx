"""K线 / 分时 / 逐笔成交路由。"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, Query

from easy_tdx._df import _category_to_minutes
from easy_tdx.web.convert import (
    adjust_from_str,
    category_from_str,
    market_from_str,
    market_value_from_str,
    period_times_from_category,
)
from easy_tdx.web.deps import get_client, get_mac_client_optional
from easy_tdx.web.schemas import DataFrameResponse

_logger = logging.getLogger(__name__)

router = APIRouter(tags=["bars"])

# 规整后保持的列顺序（匹配旧 SecurityBar 输出契约）
_NORMAL_COLS = ["open", "close", "high", "low", "vol", "amount"]


def _df_resp(df: Any) -> DataFrameResponse:
    return DataFrameResponse.from_dataframe(df)


def _is_daily_plus(cat: Any) -> bool:
    """判断 KlineCategory 是否日线及以上周期（datetime 应归一为 date）。

    KlineCategory 的枚举值不按周期长短排序（MIN_1=7、MIN_3=8 均大于 DAY=4），
    不能用整数大小判断"日线及以上"；与 client.py 的 get_security_bars 路径保持
    同一判定源：_CATEGORY_MINUTES 查得到=分钟级，查不到=日线及以上。
    """
    return _category_to_minutes(int(cat)) is None


def _normalize_mac_df(df: pd.DataFrame, daily_plus: bool) -> pd.DataFrame:
    """规整 MacClient.get_stock_kline 的输出以匹配旧 /bars 契约。

    MacClient 返回 ``datetime`` 列（含时分秒）+ ``float_shares`` 列，OHLC 顺序为
    open/high/low/close。旧 /bars（SecurityBar 路径）日线返回 ``date`` 列（仅日期）、
    分钟线返回 ``datetime`` 列，无 float_shares，OHLC 顺序为 open/close/high/low。
    本函数做对齐，保证迁移后调用方输出契约不变。

    Args:
        df: MacClient 返回的 DataFrame（可能为空）。
        daily_plus: True=日线及以上周期（datetime→date），False=分钟线（保留 datetime）。
    """
    if df.empty:
        return df
    out = df.copy()
    if "float_shares" in out.columns:
        out = out.drop(columns=["float_shares"])
    time_col = "date" if daily_plus else "datetime"
    if "datetime" in out.columns:
        if daily_plus:
            # 截断为仅日期（00:00:00），与旧 _merge_bar_datetime 的 date 列语义一致
            out["datetime"] = pd.to_datetime(out["datetime"]).dt.normalize()
        out = out.rename(columns={"datetime": time_col})
    # 重排列顺序：时间列在前，OHLC 顺序 open/close/high/low，再 vol/amount
    cols = [c for c in [time_col, *_NORMAL_COLS] if c in out.columns]
    # 兜底：保留未列出的列（理论上不应有），追加到末尾
    cols += [c for c in out.columns if c not in cols]
    return out[cols]


from easy_tdx.kline_cache import get_global_kline_disk_cache


async def _fetch_raw_tdx_bars(
    mac_client: Any,
    client: Any,
    market: str,
    code: str,
    cat: Any,
    start: int,
    count: int,
    bar_time: str,
    adjust: str,
) -> pd.DataFrame:
    """从底层的 TDX / MAC 客户端拉取单次 K 线并规整化。"""
    if mac_client is not None:
        period, times = period_times_from_category(cat)
        df = await mac_client.get_stock_kline(
            market_value_from_str(market),
            code,
            period,
            start,
            count,
            times,
            adjust=adjust_from_str(adjust),
            bar_time=bar_time,
        )
        return _normalize_mac_df(df, daily_plus=_is_daily_plus(cat))
    else:
        _logger.info(
            "/bars MAC 客户端未连接，回退标准 TdxClient（adjust=%s）",
            adjust,
        )
        return await client.get_security_bars(
            market_from_str(market),
            code,
            cat,
            start,
            count,
            bar_time=bar_time,
            adjust=adjust_from_str(adjust),
        )


@router.get("/bars", response_model=DataFrameResponse)
async def security_bars(
    market: str = Query(..., description="市场: SZ, SH, BJ"),
    code: str = Query(..., min_length=6, max_length=6),
    category: str = Query(
        "DAY",
        description="K线周期: MIN_1, MIN_5, MIN_15, MIN_30, MIN_60, DAY, WEEK, MONTH, YEAR",
    ),
    start: int = Query(0, ge=0),
    count: int = Query(800, ge=1, le=800),
    bar_time: str = Query(
        "start", description="时间戳: start=bar开始时间(默认) / end=bar结束时间(对齐Tushare)"
    ),
    adjust: str = Query(
        "QFQ", description="复权: NONE=不复权 / QFQ=前复权(默认) / HFQ=后复权（需 MAC 客户端）"
    ),
    mac_client: Any = Depends(get_mac_client_optional),
    client: Any = Depends(get_client),
) -> DataFrameResponse:
    """获取股票K线数据（支持缠论同款磁盘持久化与最新微量增量策略）。

    1. 若本地磁盘已有有效缓存且当前非交易时间/最新bar已收盘，0网络请求瞬时返回；
    2. 若需最新行情，仅向 TDX 发送微量增量（60根以内），本地增量合并并异步持久化；
    3. start > 0 翻页时，若本地历史深度覆盖则直接本地切片返回，避免慢速网络往返。
    """
    cat = category_from_str(category)
    disk_cache = get_global_kline_disk_cache()
    symbol_key = f"{market}:{code}"

    # 1. 尝试从本地持久化缓存加载
    cached_df = disk_cache.read_cached(symbol_key, category, adjust)

    if start == 0:
        # 客户端请求最新数据段
        if cached_df is not None and not cached_df.empty:
            # 检查是否已是最新（闭市/最新bar闭合）且条数充足
            if disk_cache.is_up_to_date(cached_df, category) and len(cached_df) >= count:
                return _df_resp(cached_df.iloc[-count:])

            # 交易时段或需更新：仅请求微量增量（60 根）
            try:
                delta_n = min(count, 60)
                delta_df = await _fetch_raw_tdx_bars(
                    mac_client, client, market, code, cat, 0, delta_n, bar_time, adjust
                )
                if delta_df is not None and not delta_df.empty:
                    merged = disk_cache.merge_and_update(symbol_key, category, cached_df, delta_df, adjust)
                    return _df_resp(merged.iloc[-count:])
            except Exception as e:
                _logger.warning("获取微量增量异常，回退本地缓存: %s", e)
            return _df_resp(cached_df.iloc[-count:])

        # 本地无缓存：首次全量拉取（至少 800 根以充实本地库）
        fetch_n = max(count, 800)
        df = await _fetch_raw_tdx_bars(
            mac_client, client, market, code, cat, 0, fetch_n, bar_time, adjust
        )
        if df is not None and not df.empty:
            disk_cache.write_cached(symbol_key, category, df, adjust)
            return _df_resp(df.iloc[-count:])
        return _df_resp(df)

    else:
        # 客户端请求历史分页 (start > 0)
        if cached_df is not None and len(cached_df) >= start + count:
            # 本地历史深度充足，直接从本地切片（按时间倒数切片）
            start_idx = len(cached_df) - start - count
            end_idx = len(cached_df) - start
            return _df_resp(cached_df.iloc[start_idx:end_idx])

        # 本地历史深度不足，向 TDX 补拉该页
        page_df = await _fetch_raw_tdx_bars(
            mac_client, client, market, code, cat, start, count, bar_time, adjust
        )
        if page_df is not None and not page_df.empty:
            # 增量合并扩充本地库
            disk_cache.merge_and_update(symbol_key, category, cached_df, page_df, adjust)
        return _df_resp(page_df)


@router.get("/bars/index", response_model=DataFrameResponse)
async def index_bars(
    market: str = Query(..., description="市场: SZ, SH"),
    code: str = Query(..., min_length=6, max_length=6),
    category: str = Query("DAY", description="K线周期"),
    start: int = Query(0, ge=0),
    count: int = Query(800, ge=1, le=800),
    bar_time: str = Query(
        "start", description="时间戳: start=bar开始时间(默认) / end=bar结束时间(对齐Tushare)"
    ),
    client: Any = Depends(get_client),
) -> DataFrameResponse:
    """获取指数K线数据。"""
    df = await client.get_index_bars(
        market_from_str(market), code, category_from_str(category), start, count, bar_time=bar_time
    )
    return _df_resp(df)


@router.get("/minute", response_model=DataFrameResponse)
async def minute_time(
    market: str = Query(..., description="市场: SZ, SH"),
    code: str = Query(..., min_length=6, max_length=6),
    client: Any = Depends(get_client),
) -> DataFrameResponse:
    """获取今日分时数据。"""
    df = await client.get_minute_time_data(market_from_str(market), code)
    return _df_resp(df)


@router.get("/minute/history", response_model=DataFrameResponse)
async def history_minute_time(
    market: str = Query(..., description="市场: SZ, SH"),
    code: str = Query(..., min_length=6, max_length=6),
    date: int = Query(..., description="日期 YYYYMMDD"),
    client: Any = Depends(get_client),
) -> DataFrameResponse:
    """获取历史某日分时数据。"""
    df = await client.get_history_minute_time_data(market_from_str(market), code, date)
    return _df_resp(df)


@router.get("/transaction", response_model=DataFrameResponse)
async def transaction_data(
    market: str = Query(..., description="市场: SZ, SH"),
    code: str = Query(..., min_length=6, max_length=6),
    start: int = Query(0, ge=0),
    count: int = Query(800, ge=1, le=800),
    client: Any = Depends(get_client),
) -> DataFrameResponse:
    """获取当日逐笔成交。"""
    df = await client.get_transaction_data(market_from_str(market), code, start, count)
    return _df_resp(df)


@router.get("/transaction/history", response_model=DataFrameResponse)
async def history_transaction_data(
    market: str = Query(..., description="市场: SZ, SH"),
    code: str = Query(..., min_length=6, max_length=6),
    date: int = Query(..., description="日期 YYYYMMDD"),
    start: int = Query(0, ge=0),
    count: int = Query(800, ge=1, le=800),
    client: Any = Depends(get_client),
) -> DataFrameResponse:
    """获取历史逐笔成交。"""
    df = await client.get_history_transaction_data(
        market_from_str(market), code, date, start, count
    )
    return _df_resp(df)
