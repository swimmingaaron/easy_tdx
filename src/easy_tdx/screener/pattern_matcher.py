"""形态匹配选股 (Pattern Matching Screener) 核心算法引擎。

参考通达信形态匹配选股功能：
1. 输入：用户在 K 线图上拖拉框选的收盘价序列 (长度 M 根)；
2. 目标：在指定股票池 (core/hs300/zz500/zz1000/all 或自定义股票列表) 中，
   计算各股票与模板形态的皮尔逊相关系数 (Pearson Correlation r) 及形态相似度；
3. 支持当前即时形态匹配 (最新 M 根比对) 与滑动窗口历史最佳匹配；
4. 输出：按匹配度 (相似度百分比) 降序排列的 Top N 股票，附带现价、最新涨幅、匹配区间、
   以及归一化走势点位供前端绘制迷你重叠拟合图。
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
import numpy as np
import pandas as pd

from easy_tdx.stock_lookup import get_stock_name
from easy_tdx.market_data import fetch_security_kline
from easy_tdx.screener.universe import get_universe_symbols, CORE_UNIVERSE

logger = logging.getLogger(__name__)


def normalize_min_max(arr: np.ndarray) -> list[float]:
    """将数值序列归一化到 0~100 范围，便于图表绘制对比。"""
    if len(arr) == 0:
        return []
    min_v = float(np.min(arr))
    max_v = float(np.max(arr))
    diff = max_v - min_v
    if diff <= 1e-8:
        return [50.0] * len(arr)
    return [round(float((v - min_v) / diff * 100), 1) for v in arr]


def calc_pearson_correlation(x: np.ndarray, y: np.ndarray) -> float:
    """计算两组等长序列的皮尔逊相关系数。"""
    if len(x) != len(y) or len(x) < 3:
        return 0.0
    x_std = np.std(x)
    y_std = np.std(y)
    if x_std <= 1e-8 or y_std <= 1e-8:
        return 0.0
    x_norm = (x - np.mean(x)) / x_std
    y_norm = (y - np.mean(y)) / y_std
    corr = float(np.mean(x_norm * y_norm))
    return max(-1.0, min(1.0, corr))


def match_single_stock(
    symbol: str,
    target_pattern: np.ndarray,
    period: str = "DAY",
    lookback_window: int = 0,
) -> dict[str, Any] | None:
    """比对单个标的与模板形态的匹配度。"""
    clean_sym = symbol.strip().upper().replace("SH", "").replace("SZ", "").replace("BJ", "").replace(".", "")
    m_len = len(target_pattern)
    req_bars = max(m_len + 15, (lookback_window if lookback_window > 0 else m_len) + 10)

    try:
        df = fetch_security_kline(clean_sym, period=period, count=req_bars, adjust="qfq")
        if df is None or df.empty or len(df) < m_len:
            return None

        closes = df["close"].to_numpy(dtype=float)
        dates = df["datetime"].astype(str).tolist() if "datetime" in df.columns else []

        best_corr = -1.0
        best_slice: np.ndarray | None = None
        best_start_idx = -1
        best_end_idx = -1

        if lookback_window <= 0 or lookback_window <= m_len:
            # 仅匹配最新 m_len 根 K 线（即时形态匹配）
            sub = closes[-m_len:]
            corr = calc_pearson_correlation(target_pattern, sub)
            best_corr = corr
            best_slice = sub
            best_start_idx = len(closes) - m_len
            best_end_idx = len(closes) - 1
        else:
            # 滑动窗口：在最后 lookback_window 范围内滑动寻找最大相关度
            window_len = min(len(closes), lookback_window)
            start_search = len(closes) - window_len
            for i in range(start_search, len(closes) - m_len + 1):
                sub = closes[i : i + m_len]
                corr = calc_pearson_correlation(target_pattern, sub)
                if corr > best_corr:
                    best_corr = corr
                    best_slice = sub
                    best_start_idx = i
                    best_end_idx = i + m_len - 1

        if best_corr <= 0.1 or best_slice is None:
            return None

        # 相似度计算：皮尔逊系数 r > 0 时映射为百分比，例如 r=0.92 -> 92.0%
        similarity = round(best_corr * 100, 1)

        # 最新现价与涨跌幅
        latest_close = float(closes[-1])
        prev_close = float(closes[-2]) if len(closes) >= 2 else latest_close
        pct_chg = round((latest_close - prev_close) / prev_close * 100, 2) if prev_close > 0 else 0.0

        start_date = dates[best_start_idx] if 0 <= best_start_idx < len(dates) else ""
        end_date = dates[best_end_idx] if 0 <= best_end_idx < len(dates) else ""

        # 归一化点位供前端绘制对比 Sparkline
        cand_norm = normalize_min_max(best_slice)

        name = get_stock_name(clean_sym)

        return {
            "code": clean_sym,
            "name": name,
            "similarity": similarity,
            "correlation": round(best_corr, 4),
            "latest_price": latest_close,
            "pct_change": pct_chg,
            "start_date": start_date,
            "end_date": end_date,
            "matched_bars": m_len,
            "cand_points": cand_norm,
        }
    except Exception as e:
        logger.debug(f"Failed pattern match for {clean_sym}: {e}")
        return None


def search_pattern_matches(
    target_prices: list[float],
    target_symbol: str = "",
    universe: str = "core",
    symbols: list[str] | None = None,
    period: str = "DAY",
    top_n: int = 30,
    lookback_window: int = 0,
    max_workers: int = 16,
) -> dict[str, Any]:
    """批量对股票池进行形态匹配检索。"""
    t0 = time.time()
    clean_target = target_symbol.strip().upper().replace("SH", "").replace("SZ", "").replace("BJ", "").replace(".", "")

    target_arr = np.array(target_prices, dtype=float)
    if len(target_arr) < 3:
        return {
            "status": "error",
            "message": "选取的K线根数过少（至少需要3根K线）",
            "matches": [],
            "total_scanned": 0,
            "cost_seconds": 0.0,
        }

    # 确定股票池标的列表
    if symbols and len(symbols) > 0:
        cand_symbols = symbols
    else:
        cand_symbols = get_universe_symbols(universe)

    # 排除模板自身
    cand_symbols = [s for s in cand_symbols if s.strip().upper().replace("SH", "").replace("SZ", "").replace("BJ", "").replace(".", "") != clean_target]

    target_norm = normalize_min_max(target_arr)

    matches: list[dict[str, Any]] = []
    total_scanned = 0

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_sym = {
            executor.submit(
                match_single_stock,
                sym,
                target_arr,
                period=period,
                lookback_window=lookback_window,
            ): sym
            for sym in cand_symbols
        }

        for future in as_completed(future_to_sym):
            total_scanned += 1
            res = future.result()
            if res is not None:
                matches.append(res)

    # 按相似度降序排序
    matches.sort(key=lambda m: m["similarity"], reverse=True)
    top_matches = matches[:top_n]

    cost = round(time.time() - t0, 2)

    return {
        "status": "success",
        "target_symbol": clean_target,
        "target_len": len(target_arr),
        "target_points": target_norm,
        "universe": universe,
        "period": period,
        "total_scanned": total_scanned,
        "matched_count": len(matches),
        "matches": top_matches,
        "cost_seconds": cost,
    }
