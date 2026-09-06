"""Quantitative Dynamic Pattern Recognition Engine for A-shares.

Scans historical K-line bars, moving averages, volume ratios, and indicators,
dynamically recognizing all satisfied technical patterns, breakout structures,
and multi-indicator resonance signals.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any

import numpy as np
import pandas as pd

from easy_tdx.MyTT import (
    BOLL,
    KDJ,
    MACD,
    MA,
    TD_SEQUENTIAL,
)

logger = logging.getLogger(__name__)

# In-memory thread-safe pattern cache: clean_symbol -> (timestamp, list[str])
_PATTERN_CACHE: dict[str, tuple[float, list[str]]] = {}
_PATTERN_LOCK = threading.Lock()
PATTERN_CACHE_TTL = 15.0  # 15s cache TTL for real-time responsiveness


def detect_patterns(df: pd.DataFrame) -> list[str]:
    """Detect all quantitative patterns satisfied by the current K-line sequence.

    Returns a list of all matched pattern names in order of priority/significance.
    """
    if df is None or df.empty or len(df) < 5:
        return ["震荡整理"]

    c = np.asarray(df["close"].values, dtype=float)
    o = np.asarray(df["open"].values, dtype=float)
    h = np.asarray(df["high"].values, dtype=float)
    l = np.asarray(df["low"].values, dtype=float)
    v = np.asarray(df["volume"].values, dtype=float)
    n = len(c)

    patterns: list[str] = []

    # Price change & volume ratios
    cur_c = float(c[-1])
    prev_c = float(c[-2]) if n >= 2 else cur_c
    cur_chg_pct = ((cur_c / max(0.01, prev_c)) - 1.0) * 100.0

    ma_v5 = np.asarray(MA(v, min(5, n)), dtype=float)
    vol_ratio = (float(v[-1]) / float(ma_v5[-1])) if float(ma_v5[-1]) > 0 else 1.0

    # Moving averages
    ma5 = np.asarray(MA(c, min(5, n)), dtype=float)
    ma10 = np.asarray(MA(c, min(10, n)), dtype=float)
    ma20 = np.asarray(MA(c, min(20, n)), dtype=float)

    # --- Pattern 1: 放量突破 (Volume Breakout) ---
    # Breakout of 20-bar high with volume >= 1.5x 5-day average volume and positive gain >= 1.5%
    lookback = min(20, n - 1)
    if lookback >= 5:
        prev_highs = h[-(lookback + 1):-1]
        prev_max_h = float(np.max(prev_highs))
        prev_closes = c[-(lookback + 1):-1]
        prev_max_c = float(np.max(prev_closes))
        if (cur_c >= prev_max_h or cur_c >= prev_max_c) and vol_ratio >= 1.45 and cur_chg_pct >= 1.5:
            patterns.append("放量突破")

    # --- Pattern 2: 出水芙蓉 (Hibiscus Out of Water) ---
    # Strong bullish candle (>= 2.5%) cutting across MA5, MA10, and MA20 simultaneously from below with volume expansion
    if n >= 20:
        min_mas = min(float(ma5[-1]), float(ma10[-1]), float(ma20[-1]))
        max_mas = max(float(ma5[-1]), float(ma10[-1]), float(ma20[-1]))
        if cur_chg_pct >= 2.5 and float(l[-1]) <= min_mas and cur_c >= max_mas and vol_ratio >= 1.3:
            patterns.append("出水芙蓉")

    # --- Pattern 3: 均线多头 (Bullish MA Alignment) ---
    # C >= MA5 >= MA10 >= MA20 and MA slopes are upward
    if n >= 20:
        if (
            cur_c >= float(ma5[-1]) >= float(ma10[-1]) >= float(ma20[-1])
            and float(ma5[-1]) >= float(ma5[-2])
            and float(ma10[-1]) >= float(ma10[-2])
        ):
            patterns.append("均线多头")

    # --- Pattern 4: 缩量回踩 (Low-Volume Pullback) ---
    # In an uptrend (MA20 slope >= 0), price pulls back to near MA10/MA20 with low volume (< 0.85x)
    if n >= 20:
        ma20_slope_up = float(ma20[-1]) >= float(ma20[-3])
        dist_ma10 = abs(cur_c - float(ma10[-1])) / max(0.01, float(ma10[-1]))
        dist_ma20 = abs(cur_c - float(ma20[-1])) / max(0.01, float(ma20[-1]))
        is_near_support = (dist_ma10 <= 0.018 or dist_ma20 <= 0.022) and cur_c >= min(float(ma10[-1]), float(ma20[-1])) * 0.985
        if ma20_slope_up and is_near_support and vol_ratio <= 0.85 and cur_chg_pct <= 1.0:
            patterns.append("缩量回踩")

    # --- Pattern 5: 均线空头 (Bearish MA Alignment) ---
    if n >= 20:
        if (
            cur_c <= float(ma5[-1]) <= float(ma10[-1]) <= float(ma20[-1])
            and float(ma5[-1]) <= float(ma5[-2])
            and float(ma10[-1]) <= float(ma10[-2])
        ):
            patterns.append("均线空头")

    # --- Pattern 6: 底分型确立 (Bottom Fractal Reversal) ---
    # Low of 2 bars ago is the minimum of 5 bars, and today's close breaks above its high
    if n >= 5:
        if float(l[-2]) == float(np.min(l[-5:])) and cur_c > float(h[-2]) and cur_c > float(o[-1]):
            patterns.append("底分型")

    # --- Pattern 7: 顶分型衰竭 (Top Fractal Warning) ---
    if n >= 5:
        if float(h[-2]) == float(np.max(h[-5:])) and cur_c < float(l[-2]) and cur_c < float(o[-1]):
            patterns.append("顶分型")

    # --- Pattern 8: TD9见底 / TD9见顶 (TD Sequential 9 Reversals) ---
    try:
        td_h, td_l = TD_SEQUENTIAL(c, 9)
        td_l_arr = np.asarray(td_l)
        td_h_arr = np.asarray(td_h)
        if len(td_l_arr) > 0 and (int(td_l_arr[-1]) >= 9 or (n >= 2 and int(td_l_arr[-2]) >= 9 and cur_c > float(o[-1]))):
            patterns.append("TD9见底")
        elif len(td_h_arr) > 0 and (int(td_h_arr[-1]) >= 9 or (n >= 2 and int(td_h_arr[-2]) >= 9 and cur_c < float(o[-1]))):
            patterns.append("TD9见顶")
    except Exception:
        pass

    # --- Pattern 9: MACD金叉 / 死叉 (MACD Golden / Death Cross) ---
    try:
        dif, dea, _ = MACD(c)
        dif_a = np.asarray(dif)
        dea_a = np.asarray(dea)
        if len(dif_a) >= 2:
            if float(dif_a[-1]) > float(dea_a[-1]) and float(dif_a[-2]) <= float(dea_a[-2]):
                patterns.append("MACD金叉")
            elif len(dif_a) >= 3 and float(dif_a[-1]) > float(dea_a[-1]) > 0 and float(dif_a[-3]) <= float(dea_a[-3]):
                patterns.append("零上金叉")
            elif float(dif_a[-1]) < float(dea_a[-1]) and float(dif_a[-2]) >= float(dea_a[-2]):
                patterns.append("MACD死叉")
    except Exception:
        pass

    # --- Pattern 10: KDJ超卖金叉 / 超买 (KDJ Signals) ---
    try:
        k_val, d_val, _ = KDJ(c, h, l)
        k_a = np.asarray(k_val)
        d_a = np.asarray(d_val)
        if len(k_a) >= 2:
            if float(k_a[-1]) > float(d_a[-1]) and float(k_a[-2]) <= float(d_a[-2]) and float(k_a[-1]) <= 40:
                patterns.append("KDJ低位金叉")
            elif float(k_a[-1]) > 80 and float(d_a[-1]) > 80:
                patterns.append("KDJ超买")
    except Exception:
        pass

    # --- Pattern 11: 红三兵 (Three Red Soldiers) ---
    if n >= 3:
        if (
            float(c[-1]) > float(c[-2]) > float(c[-3])
            and float(c[-1]) > float(o[-1])
            and float(c[-2]) > float(o[-2])
            and float(c[-3]) > float(o[-3])
            and cur_chg_pct > 0.3
        ):
            patterns.append("红三兵")

    # --- Pattern 12: 阳包阴 (Bullish Engulfing) ---
    if n >= 2:
        if (
            float(c[-2]) < float(o[-2])
            and float(c[-1]) > float(o[-1])
            and float(o[-1]) <= float(c[-2])
            and float(c[-1]) >= float(o[-2])
        ):
            patterns.append("阳包阴")

    # --- Pattern 13: 布林突破 / 收口 (BOLL Signals) ---
    try:
        b_up, b_mid, b_low = BOLL(c, 20, 2)
        up_a = np.asarray(b_up)
        mid_a = np.asarray(b_mid)
        low_a = np.asarray(b_low)
        if len(up_a) >= 5 and float(mid_a[-1]) > 0:
            bandwidth = (float(up_a[-1]) - float(low_a[-1])) / float(mid_a[-1])
            if cur_c >= float(up_a[-1]) and bandwidth > (float(up_a[-2]) - float(low_a[-2])) / float(mid_a[-2]):
                patterns.append("布林突破")
            elif bandwidth < 0.09:
                patterns.append("布林收口")
    except Exception:
        pass

    # Fallback if no specific trigger fired
    if not patterns:
        if n >= 20 and len(ma20) > 0:
            if cur_c >= float(ma20[-1]):
                patterns.append("震荡蓄势")
            else:
                patterns.append("弱势整理")
        else:
            patterns.append("震荡整理")

    return patterns


def detect_stock_patterns(symbol: str, count: int = 60) -> list[str]:
    """Fetch historical K-line bars for symbol and dynamically recognize all satisfied patterns.

    Results are cached with a 15-second TTL.
    """
    clean_sym = (
        symbol.strip()
        .upper()
        .replace("SH", "")
        .replace("SZ", "")
        .replace("BJ", "")
        .replace("HY", "")
        .replace("BK", "")
        .replace(".", "")
    )
    if not clean_sym:
        clean_sym = "000001"

    now = time.time()
    with _PATTERN_LOCK:
        if clean_sym in _PATTERN_CACHE:
            ts, cached_patterns = _PATTERN_CACHE[clean_sym]
            if now - ts < PATTERN_CACHE_TTL:
                return list(cached_patterns)

    try:
        from easy_tdx.market_data import fetch_security_kline
        df = fetch_security_kline(clean_sym, count=count)
        patterns = detect_patterns(df)
    except Exception as e:
        logger.debug(f"Failed to detect patterns for {clean_sym}: {e}")
        patterns = ["震荡整理"]

    with _PATTERN_LOCK:
        _PATTERN_CACHE[clean_sym] = (now, patterns)

    return list(patterns)
