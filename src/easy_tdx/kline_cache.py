"""全局 K 线本地磁盘持久化缓存与增量更新管理器。

参考 chanlun-pro 的 FileCacheDB 核心架构：
1. 磁盘持久化保存每只标的、周期、复权类型的历史 K 线数据；
2. 增量更新机制：已有历史数据时，仅向行情服务器请求最新微量增量（少量条数），
   在本地高效拼接去重，极大减轻网络包传输负担并缩减网络往返延迟；
3. 休市/非交易时间智能拦截：若本地数据已覆盖最新交易收盘时间，0 网络请求瞬时返回。
"""

from __future__ import annotations

import datetime
import logging
import pathlib
import threading
import zoneinfo
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

_CACHE_LOCK = threading.Lock()
_SH_TZ = zoneinfo.ZoneInfo("Asia/Shanghai")


def is_trade_session() -> bool:
    """判断当前是否处于 A 股交易时段。"""
    now = datetime.datetime.now(_SH_TZ)
    if now.weekday() >= 5:  # 周六、周日
        return False
    t = now.time()
    morning = datetime.time(9, 15) <= t <= datetime.time(11, 35)
    afternoon = datetime.time(12, 55) <= t <= datetime.time(15, 5)
    return morning or afternoon


def get_expected_last_trading_day(now: datetime.datetime | None = None) -> datetime.date:
    """获取当前时刻理论上应该已经完全收盘的最近交易日日期（扣除周末，支持自定义 now）。"""
    if now is None:
        now = datetime.datetime.now(_SH_TZ)
    d = now.date()
    t = now.time()

    # 周一到周五
    if now.weekday() < 5:
        if t >= datetime.time(15, 5):
            # 今天 15:05 之后，今天已正式收盘
            return d
        else:
            # 今天尚未收盘（盘前或盘中），上一个已收盘交易日是昨天
            d -= datetime.timedelta(days=1)
    elif now.weekday() == 5:  # 周六
        d -= datetime.timedelta(days=1)
    elif now.weekday() == 6:  # 周日
        d -= datetime.timedelta(days=2)

    # 往前跳过周末
    while d.weekday() in (5, 6):
        d -= datetime.timedelta(days=1)
    return d


class KlineDiskCache:
    """参考 chanlun-pro FileCacheDB 实现的全局高性能 K 线磁盘缓存管理器。"""

    def __init__(self, cache_dir: pathlib.Path | str | None = None) -> None:
        if cache_dir is None:
            home = pathlib.Path.home()
            self.base_dir = home / ".easy_tdx" / "cache" / "klines"
        else:
            self.base_dir = pathlib.Path(cache_dir)

        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _get_file_path(self, symbol: str, period: Any, adjust: Any = "QFQ") -> pathlib.Path:
        s_upper = str(symbol).strip().upper()
        pfx = "SH_" if (("SH" in s_upper or s_upper.startswith("SH_")) and s_upper.replace("SH_", "").replace("SH", "").replace(".", "").startswith("00")) else ""
        clean_sym = s_upper.replace("SH_", "").replace("SH", "").replace("SZ", "").replace("BJ", "").replace(".", "")
        clean_p = str(period).strip().upper().replace("MIN_", "").replace("MIN", "M").replace("F", "M")
        clean_adj = str(adjust).strip().upper()
        return self.base_dir / f"{pfx}{clean_sym}_{clean_p}_{clean_adj}.pkl"

    def _get_meta_path(self, symbol: str, period: Any, adjust: Any = "QFQ") -> pathlib.Path:
        fp = self._get_file_path(symbol, period, adjust)
        return fp.with_suffix(".meta.json")

    def read_cached(self, symbol: str, period: str, adjust: str = "QFQ") -> pd.DataFrame | None:
        """从本地磁盘读取 K 线缓存（含新股全量历史状态）。"""
        fp = self._get_file_path(symbol, period, adjust)
        if not fp.is_file():
            return None
        try:
            with open(fp, "rb") as f:
                df = pd.read_pickle(f)
            if isinstance(df, pd.DataFrame) and not df.empty and ("datetime" in df.columns or "date" in df.columns):
                # 尝试读取元数据文件辅助恢复 full_history（防止 pickle 跨环境丢失 attrs）
                meta_fp = self._get_meta_path(symbol, period, adjust)
                if meta_fp.is_file():
                    try:
                        import json
                        with open(meta_fp, "r", encoding="utf-8") as mf:
                            meta = json.load(mf)
                        if meta.get("full_history"):
                            df.attrs["full_history"] = True
                    except Exception:
                        pass
                return df
        except Exception as e:
            logger.debug("读取本地 K 线缓存异常 %s %s: %s", symbol, period, e)
            try:
                fp.unlink(missing_ok=True)
            except Exception:
                pass
        return None

    def write_cached(
        self,
        symbol: str,
        period: str,
        df: pd.DataFrame,
        adjust: str = "QFQ",
        full_history: bool | None = None,
    ) -> None:
        """写入/更新本地磁盘 K 线缓存（针对 5F 保留最多 16000 根，支持新股全历史标记）。"""
        if df is None or df.empty or len(df) == 0:
            return
        fp = self._get_file_path(symbol, period, adjust)
        meta_fp = self._get_meta_path(symbol, period, adjust)
        try:
            p_upper = str(period).strip().upper()
            if any(k in p_upper for k in ("5F", "5M")):
                max_keep = 16000  # 保证 12000 根 5F 分钟线完整持久化并留有充裕余量
            elif any(k in p_upper for k in ("1F", "1M", "15F", "15M", "30F", "30M")):
                max_keep = 6000
            else:
                max_keep = 5000

            save_df = df.iloc[-max_keep:].copy().reset_index(drop=True)

            # 保留或设置新股全量历史属性
            is_full = (
                full_history
                if full_history is not None
                else bool(getattr(df, "attrs", {}).get("full_history", False))
            )
            save_df.attrs["full_history"] = is_full

            with open(fp, "wb") as f:
                save_df.to_pickle(f)

            # 同步写轻量元数据文件供快速读取
            try:
                import json
                meta_data = {
                    "symbol": symbol,
                    "period": period,
                    "adjust": adjust,
                    "count": len(save_df),
                    "full_history": is_full,
                }
                with open(meta_fp, "w", encoding="utf-8") as mf:
                    json.dump(meta_data, mf)
            except Exception:
                pass
        except Exception as e:
            logger.debug("写入本地 K 线缓存异常 %s %s: %s", symbol, period, e)

    def merge_and_update(
        self,
        symbol: str,
        period: str,
        existing_df: pd.DataFrame | None,
        new_df: pd.DataFrame | None,
        adjust: str = "QFQ",
    ) -> pd.DataFrame:
        """增量合并已有数据与新数据，去重排序并持久化（自动继承新股 full_history 标记）。"""
        if existing_df is None or existing_df.empty:
            if new_df is not None and not new_df.empty:
                self.write_cached(symbol, period, new_df, adjust)
                return new_df
            return pd.DataFrame(columns=["datetime", "open", "high", "low", "close", "vol", "amount"])

        if new_df is None or new_df.empty:
            return existing_df

        # 识别时间列名（date 或 datetime）
        dt_col = "date" if "date" in existing_df.columns else "datetime"
        if dt_col not in new_df.columns:
            other_dt = "datetime" if dt_col == "date" else "date"
            if other_dt in new_df.columns:
                new_df = new_df.rename(columns={other_dt: dt_col})

        # 拼接并以时间列为唯一键去重，保留最新更新（keep='last' 保证最后一根未完结 bar 能被最新行情覆盖）
        combined = pd.concat([existing_df, new_df], ignore_index=True)
        if dt_col in combined.columns:
            combined.drop_duplicates(subset=[dt_col], keep="last", inplace=True)
            combined.sort_values(by=dt_col, inplace=True)
            combined.reset_index(drop=True, inplace=True)

        # 继承新股全历史标记
        is_full = bool(
            getattr(existing_df, "attrs", {}).get("full_history", False)
            or getattr(new_df, "attrs", {}).get("full_history", False)
        )
        combined.attrs["full_history"] = is_full

        self.write_cached(symbol, period, combined, adjust, full_history=is_full)
        return combined

    def is_up_to_date(self, df: pd.DataFrame, period: str) -> bool:
        """判断缓存中的数据是否已经是最新的（例如非交易时间且已包含最后收盘 bar）。"""
        if df is None or df.empty or len(df) == 0:
            return False

        now = datetime.datetime.now(_SH_TZ)
        dt_col = "date" if "date" in df.columns else "datetime"
        if dt_col not in df.columns:
            return False
        latest_str = str(df[dt_col].iloc[-1]).strip()
        latest_date_str = latest_str.split()[0].split("T")[0]

        expected_closed_date = get_expected_last_trading_day(now)
        expected_closed_str = expected_closed_date.strftime("%Y-%m-%d")

        p_upper = str(period).strip().upper()

        # 0. 季线 (SEASON)
        if any(x in p_upper for x in ("SEASON", "QUARTER", "Q")):
            try:
                latest_d = datetime.date.fromisoformat(latest_date_str)
                cur_yq = (latest_d.year, (latest_d.month - 1) // 3)
                exp_yq = (expected_closed_date.year, (expected_closed_date.month - 1) // 3)
                if cur_yq < exp_yq:
                    return False
                return not is_trade_session()
            except Exception:
                return False

        # 1. 周线 (WEEK)
        if "WEEK" in p_upper or p_upper == "W":
            try:
                latest_d = datetime.date.fromisoformat(latest_date_str)
                latest_year, latest_week, _ = latest_d.isocalendar()
                exp_year, exp_week, _ = expected_closed_date.isocalendar()
                if (latest_year, latest_week) < (exp_year, exp_week):
                    return False
                # 若正处于交易时段且当周尚未最终收盘，周线仍在跳动，非最终状态
                return not is_trade_session()
            except Exception:
                return False

        # 2. 月线 (MONTH)
        if "MONTH" in p_upper or p_upper == "M":
            try:
                latest_d = datetime.date.fromisoformat(latest_date_str)
                cur_ym = (latest_d.year, latest_d.month)
                exp_ym = (expected_closed_date.year, expected_closed_date.month)
                if cur_ym < exp_ym:
                    return False
                return not is_trade_session()
            except Exception:
                return False

        # 3. 日线及分钟线核心核验：
        # 如果缓存中最新一条日期落后于理论已收盘交易日，直接判定未更新！
        if latest_date_str < expected_closed_str:
            return False

        # 4. 如果当前在交易时段（盘中），行情在实时跳动，磁盘历史缓存不能代替实时盘中数据
        if is_trade_session():
            return False

        # 5. 非交易时段（盘后、中午休市、盘前或周末）：
        t = now.time()
        today_str = now.strftime("%Y-%m-%d")
        is_today = (latest_date_str == today_str)

        is_min_bar = any(m in p_upper for m in ["1F", "5F", "15F", "30F", "60F", "120F", "MIN"])

        # 5.1 工作日收盘后 (15:05 之后)
        if now.weekday() < 5 and t >= datetime.time(15, 5):
            if not is_today:
                return False
            if is_min_bar:
                # 分钟线收盘时必须覆盖到 15:00 附近
                return ("15:00" in latest_str) or ("14:55" in latest_str)
            return True

        # 5.2 工作日中午休市 (11:35 - 12:55)
        if now.weekday() < 5 and datetime.time(11, 35) <= t <= datetime.time(12, 55):
            if not is_today:
                return False
            if is_min_bar:
                return ("11:30" in latest_str) or ("11:25" in latest_str)
            return True

        # 5.3 周末或盘前
        # 只要最新日期已经达到预期收盘交易日且分钟线已经收在 15:00
        if is_min_bar:
            return ("15:00" in latest_str) or ("14:55" in latest_str)
        return True


_GLOBAL_DISK_CACHE: KlineDiskCache | None = None


def get_global_kline_disk_cache() -> KlineDiskCache:
    """获取全局 K 线磁盘缓存单例。"""
    global _GLOBAL_DISK_CACHE
    if _GLOBAL_DISK_CACHE is None:
        with _CACHE_LOCK:
            if _GLOBAL_DISK_CACHE is None:
                _GLOBAL_DISK_CACHE = KlineDiskCache()
    return _GLOBAL_DISK_CACHE
