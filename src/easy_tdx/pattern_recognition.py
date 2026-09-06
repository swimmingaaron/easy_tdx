"""Quantitative Dynamic Pattern Recognition Engine for A-shares.

Scans historical K-line bars, moving averages, volume ratios, and indicators,
dynamically recognizing all satisfied technical patterns, breakout structures,
candlestick reversals, and multi-indicator resonance signals.
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
    CCI,
    KDJ,
    MACD,
    MA,
    OBV,
    RSI,
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

    # Basic dimensions of the latest bar
    cur_c = float(c[-1])
    cur_o = float(o[-1])
    cur_h = float(h[-1])
    cur_l = float(l[-1])
    cur_v = float(v[-1])
    prev_c = float(c[-2]) if n >= 2 else cur_c
    prev_o = float(o[-2]) if n >= 2 else cur_o
    prev_h = float(h[-2]) if n >= 2 else cur_h
    prev_l = float(l[-2]) if n >= 2 else cur_l

    cur_chg_pct = ((cur_c / max(0.01, prev_c)) - 1.0) * 100.0
    cur_body = abs(cur_c - cur_o)
    cur_range = max(0.001, cur_h - cur_l)

    # 5-day volume moving average & volume ratio
    ma_v5 = np.asarray(MA(v, min(5, n)), dtype=float)
    vol_ratio = (cur_v / float(ma_v5[-1])) if float(ma_v5[-1]) > 0 else 1.0

    # Moving averages
    ma5 = np.asarray(MA(c, min(5, n)), dtype=float)
    ma10 = np.asarray(MA(c, min(10, n)), dtype=float)
    ma20 = np.asarray(MA(c, min(20, n)), dtype=float)
    ma60 = np.asarray(MA(c, min(60, n)), dtype=float) if n >= 60 else None

    # =========================================================================
    # 一、均线 & 突破类形态
    # =========================================================================

    # 1. 放量突破 (破20日高点 + 量比 >= 1.45 + 阳线 + 涨幅 >= 1.5%)
    lookback = min(20, n - 1)
    if lookback >= 5:
        prev_highs = h[-(lookback + 1):-1]
        prev_max_h = float(np.max(prev_highs))
        prev_closes = c[-(lookback + 1):-1]
        prev_max_c = float(np.max(prev_closes))
        if (cur_c >= prev_max_h or cur_c >= prev_max_c) and vol_ratio >= 1.45 and cur_chg_pct >= 1.5 and cur_c > cur_o:
            patterns.append("放量突破")

    # 2. 蛟龙出海 (大阳线一举站上 MA5/10/20/60 四均线，放量突破)
    if n >= 60 and ma60 is not None:
        min_4mas = min(float(ma5[-1]), float(ma10[-1]), float(ma20[-1]), float(ma60[-1]))
        max_4mas = max(float(ma5[-1]), float(ma10[-1]), float(ma20[-1]), float(ma60[-1]))
        if cur_chg_pct >= 1.8 and cur_l <= min_4mas and cur_c >= max_4mas and cur_c > cur_o and vol_ratio >= 1.3:
            patterns.append("蛟龙出海")
    # 3. 出水芙蓉 (大阳线一举站上 MA5/10/20 三均线)
    elif n >= 20:
        min_3mas = min(float(ma5[-1]), float(ma10[-1]), float(ma20[-1]))
        max_3mas = max(float(ma5[-1]), float(ma10[-1]), float(ma20[-1]))
        if cur_chg_pct >= 2.0 and cur_l <= min_3mas and cur_c >= max_3mas and cur_c > cur_o and vol_ratio >= 1.3:
            patterns.append("出水芙蓉")

    # 4. 均线多头 (C >= MA5 >= MA10 >= MA20，发散向上)
    if n >= 20:
        if (
            cur_c >= float(ma5[-1]) >= float(ma10[-1]) >= float(ma20[-1])
            and float(ma5[-1]) >= float(ma5[-2])
            and float(ma10[-1]) >= float(ma10[-2])
        ):
            patterns.append("均线多头")

    # 5. 缩量回踩 (上升通道回踩 MA10/MA20 支撑位，量比 <= 0.85)
    if n >= 20:
        ma20_slope_up = float(ma20[-1]) >= float(ma20[-3])
        dist_ma10 = abs(cur_c - float(ma10[-1])) / max(0.01, float(ma10[-1]))
        dist_ma20 = abs(cur_c - float(ma20[-1])) / max(0.01, float(ma20[-1]))
        is_near_support = (dist_ma10 <= 0.022 or dist_ma20 <= 0.025) and cur_c >= min(float(ma10[-1]), float(ma20[-1])) * 0.985
        if ma20_slope_up and is_near_support and vol_ratio <= 0.85 and cur_chg_pct <= 1.0:
            patterns.append("缩量回踩")

    # 6. 均线空头 / 空头排列
    if n >= 20:
        if (
            cur_c <= float(ma5[-1]) <= float(ma10[-1]) <= float(ma20[-1])
            and float(ma5[-1]) <= float(ma5[-2])
            and float(ma10[-1]) <= float(ma10[-2])
        ):
            if n >= 60 and ma60 is not None and float(ma20[-1]) <= float(ma60[-1]):
                patterns.append("空头排列")
            else:
                patterns.append("均线空头")

    # 7. 金蜘蛛 (低位 MA5 上穿 MA10/20，均线黏合后多头发散)
    if n >= 10:
        recent_cross = (float(ma5[-1]) > float(ma10[-1]) and float(ma5[-1]) > float(ma20[-1])) and (
            float(ma5[-3]) <= min(float(ma10[-3]), float(ma20[-3])) or float(ma5[-2]) <= min(float(ma10[-2]), float(ma20[-2]))
        )
        ma_spread = abs(float(ma10[-1]) - float(ma20[-1])) / max(0.01, float(ma20[-1]))
        if recent_cross and ma_spread <= 0.035 and float(ma5[-1]) >= float(ma5[-2]):
            patterns.append("金蜘蛛")

    # 8. 死蜘蛛 (高位 MA5 下穿 MA10/20，均线黏合后空头发散)
    if n >= 10:
        recent_dead_cross = (float(ma5[-1]) < float(ma10[-1]) and float(ma5[-1]) < float(ma20[-1])) and (
            float(ma5[-3]) >= max(float(ma10[-3]), float(ma20[-3])) or float(ma5[-2]) >= max(float(ma10[-2]), float(ma20[-2]))
        )
        if recent_dead_cross and float(ma5[-1]) <= float(ma5[-2]):
            patterns.append("死蜘蛛")

    # 9. 价托 (低位三角均线支撑: MA5上穿MA10/20，MA10上穿MA20形成三角形)
    if n >= 25:
        if float(ma5[-1]) >= float(ma10[-1]) >= float(ma20[-1]):
            had_5_10 = any(float(ma5[-k]) > float(ma10[-k]) and float(ma5[-k - 1]) <= float(ma10[-k - 1]) for k in range(1, min(10, n - 1)))
            had_10_20 = any(float(ma10[-k]) > float(ma20[-k]) and float(ma10[-k - 1]) <= float(ma20[-k - 1]) for k in range(1, min(10, n - 1)))
            if had_5_10 and had_10_20 and cur_c >= float(ma5[-1]):
                patterns.append("价托")

    # 10. 价压 (高位三角均线压制: MA5下穿MA10/20，MA10下穿MA20形成三角形)
    if n >= 25:
        if float(ma5[-1]) <= float(ma10[-1]) <= float(ma20[-1]):
            had_dead_5_10 = any(float(ma5[-k]) < float(ma10[-k]) and float(ma5[-k - 1]) >= float(ma10[-k - 1]) for k in range(1, min(10, n - 1)))
            had_dead_10_20 = any(float(ma10[-k]) < float(ma20[-k]) and float(ma10[-k - 1]) >= float(ma20[-k - 1]) for k in range(1, min(10, n - 1)))
            if had_dead_5_10 and had_dead_10_20 and cur_c <= float(ma5[-1]):
                patterns.append("价压")

    # =========================================================================
    # 二、经典看跌 K 线形态
    # =========================================================================

    # 1. 三只乌鸦 (连续三根实体阴线，收盘逐根降低，高位走弱)
    if n >= 3:
        three_crows = (
            cur_c < cur_o and float(c[-2]) < float(o[-2]) and float(c[-3]) < float(o[-3])
            and cur_c < float(c[-2]) < float(c[-3])
            and (cur_body / max(0.01, cur_o)) >= 0.006
            and (abs(float(c[-2]) - float(o[-2])) / max(0.01, float(o[-2]))) >= 0.006
            and float(c[-3]) >= np.mean(c[-min(20, n):])
        )
        if three_crows:
            patterns.append("三只乌鸦")

    # 2. 乌云盖顶 (前大阳线，当日高开收阴，深入前阳实体内部一半以上)
    if n >= 2:
        prev_is_big_bull = prev_c > prev_o and ((prev_c - prev_o) / max(0.01, prev_o)) >= 0.015
        cur_is_bear = cur_c < cur_o
        mid_prev = (prev_o + prev_c) / 2.0
        if prev_is_big_bull and cur_o > prev_c and cur_is_bear and cur_c < mid_prev and cur_c > prev_o:
            patterns.append("乌云盖顶")

    # 3. 倾盆大雨 (前大阳线，当日高开或平开收阴，收盘价直接跌破前阳开盘价)
    if n >= 2:
        prev_is_big_bull = prev_c > prev_o and ((prev_c - prev_o) / max(0.01, prev_o)) >= 0.015
        if prev_is_big_bull and cur_o >= prev_c * 0.995 and cur_c < cur_o and cur_c < prev_o:
            patterns.append("倾盆大雨")

    # 4. 穿头破脚（阴包阳 / 看跌吞没）
    if n >= 2:
        if prev_c > prev_o and cur_c < cur_o and cur_o >= prev_c and cur_c <= prev_o and prev_c >= np.mean(c[-min(20, n):]):
            patterns.append("阴包阳")

    # 5. 黄昏之星 (大阳线 -> 跳空小星线 -> 深入大阴线)
    if n >= 3:
        day3_bull = float(c[-3]) > float(o[-3]) and ((float(c[-3]) - float(o[-3])) / max(0.01, float(o[-3]))) >= 0.015
        day2_star = min(float(o[-2]), float(c[-2])) >= float(c[-3]) * 0.998 and (abs(float(c[-2]) - float(o[-2])) / max(0.01, float(o[-2]))) <= 0.012
        day1_bear = cur_c < cur_o and cur_c <= (float(o[-3]) + float(c[-3])) / 2.0
        if day3_bull and day2_star and day1_bear:
            patterns.append("黄昏之星")

    # 6. 下降三法 (大阴线后小阳线反弹中继，再来大阴线破新低)
    if n >= 5:
        day5_big_bear = float(c[-5]) < float(o[-5]) and ((float(o[-5]) - float(c[-5])) / max(0.01, float(o[-5]))) >= 0.018
        inter_inside = max(float(h[-4]), float(h[-3]), float(h[-2])) <= float(h[-5])
        day1_break_low = cur_c < cur_o and cur_c < float(c[-5])
        if day5_big_bear and inter_inside and day1_break_low:
            patterns.append("下降三法")

    # 7. 射击之星（流星线: 高位长上影小实体，实体靠近最低价）
    upper_shadow = cur_h - max(cur_c, cur_o)
    lower_shadow = min(cur_c, cur_o) - cur_l
    if cur_range >= 0.01 * cur_c:
        is_high_pos = (cur_h == float(np.max(h[-min(10, n):])) or cur_c >= float(np.mean(c[-min(20, n):])))
        if upper_shadow >= 2.0 * cur_body and (upper_shadow / cur_range) >= 0.5 and (lower_shadow / cur_range) <= 0.15 and is_high_pos:
            patterns.append("射击之星")

    # 8. 吊颈线 (高位长下影小实体，实体靠近最高价)
    if cur_range >= 0.01 * cur_c:
        is_high_pos = cur_c >= float(np.mean(c[-min(15, n):]))
        if lower_shadow >= 2.0 * cur_body and (lower_shadow / cur_range) >= 0.5 and (upper_shadow / cur_range) <= 0.15 and is_high_pos:
            patterns.append("吊颈线")

    # 9. 空方炮 (两阴夹一阳看跌形态)
    if n >= 3:
        day3_bear = float(c[-3]) < float(o[-3]) and ((float(o[-3]) - float(c[-3])) / max(0.01, float(o[-3]))) >= 0.012
        day2_bull = float(c[-2]) > float(o[-2]) and float(c[-2]) <= float(o[-3])
        day1_bear = cur_c < cur_o and cur_c < float(c[-3])
        if day3_bear and day2_bull and day1_bear:
            patterns.append("空方炮")

    # =========================================================================
    # 三、经典看涨 K 线形态
    # =========================================================================

    # 1. 启明星 (早晨之星: 大阴线 -> 跳空小星线 -> 大阳线反包)
    if n >= 3:
        day3_bear = float(c[-3]) < float(o[-3]) and ((float(o[-3]) - float(c[-3])) / max(0.01, float(o[-3]))) >= 0.015
        day2_star = max(float(o[-2]), float(c[-2])) <= float(c[-3]) * 1.002 and (abs(float(c[-2]) - float(o[-2])) / max(0.01, float(o[-2]))) <= 0.012
        day1_bull = cur_c > cur_o and cur_c >= (float(o[-3]) + float(c[-3])) / 2.0
        if day3_bear and day2_star and day1_bull:
            patterns.append("启明星")

    # 2. 曙光初现 (低开高走，收盘价回升至前大阴实体一半以上但未反超开盘价)
    if n >= 2:
        prev_is_big_bear = prev_c < prev_o and ((prev_o - prev_c) / max(0.01, prev_o)) >= 0.015
        mid_prev = (prev_o + prev_c) / 2.0
        if prev_is_big_bear and cur_o < prev_c and cur_c > cur_o and cur_c >= mid_prev and cur_c <= prev_o:
            patterns.append("曙光初现")

    # 3. 旭日东升 (低开或平开大阳线反转，收盘价直接超过前一日开盘价)
    if n >= 2:
        prev_is_big_bear = prev_c < prev_o and ((prev_o - prev_c) / max(0.01, prev_o)) >= 0.015
        if prev_is_big_bear and cur_c > cur_o and cur_c > prev_o:
            patterns.append("旭日东升")

    # 4. 阳包阴 (看涨吞没: 阳线实体完全包裹前阴线实体)
    if n >= 2:
        if prev_c < prev_o and cur_c > cur_o and cur_o <= prev_c and cur_c >= prev_o:
            patterns.append("阳包阴")

    # 5. 锤子线 (下跌末端长下影小实体，下影线 >= 2*实体，多头止跌企稳)
    if cur_range >= 0.01 * cur_c:
        is_low_pos = cur_c <= float(np.mean(c[-min(15, n):]))
        if lower_shadow >= 2.0 * cur_body and (lower_shadow / cur_range) >= 0.5 and (upper_shadow / cur_range) <= 0.15 and is_low_pos:
            patterns.append("锤子线")

    # 6. 倒锤子线 (低位长上影小实体，实体靠近最低价，试盘探底)
    if cur_range >= 0.01 * cur_c:
        is_low_pos = cur_c <= float(np.mean(c[-min(15, n):]))
        if upper_shadow >= 2.0 * cur_body and (upper_shadow / cur_range) >= 0.5 and (lower_shadow / cur_range) <= 0.15 and is_low_pos:
            patterns.append("倒锤子线")

    # 7. 多方炮 (两阳夹一阴看涨攻击形态)
    if n >= 3:
        day3_bull = float(c[-3]) > float(o[-3]) and ((float(c[-3]) - float(o[-3])) / max(0.01, float(o[-3]))) >= 0.012
        day2_bear = float(c[-2]) < float(o[-2]) and float(c[-2]) >= float(o[-3])
        day1_bull = cur_c > cur_o and cur_c > float(c[-3])
        if day3_bull and day2_bear and day1_bull:
            patterns.append("多方炮")

    # 8. 红三兵 (连续三根温和阳线，收盘逐根抬高)
    if n >= 3:
        if (
            cur_c > float(c[-2]) > float(c[-3])
            and cur_c > cur_o
            and float(c[-2]) > float(o[-2])
            and float(c[-3]) > float(o[-3])
            and cur_chg_pct > 0.3
        ):
            patterns.append("红三兵")

    # 9. 上升三法 (大阳线后小回调中继，放量大阳线再创新高)
    if n >= 5:
        day5_big_bull = float(c[-5]) > float(o[-5]) and ((float(c[-5]) - float(o[-5])) / max(0.01, float(o[-5]))) >= 0.018
        inter_hold = min(float(l[-4]), float(l[-3]), float(l[-2])) >= float(l[-5])
        day1_new_high = cur_c > cur_o and cur_c > float(h[-5])
        if day5_big_bull and inter_hold and day1_new_high:
            patterns.append("上升三法")

    # =========================================================================
    # 四、震荡 / 转折类（十字星、孕线、缺口）
    # =========================================================================

    is_doji = (cur_body / max(0.01, cur_o)) <= 0.0035 and (cur_range / max(0.01, cur_o)) >= 0.008
    if is_doji:
        is_low_star = cur_c <= float(np.min(c[-min(15, n):])) * 1.03 or cur_c < float(ma20[-1])
        if is_low_star:
            patterns.append("低位十字星")
        elif upper_shadow >= 2.0 * max(0.001, lower_shadow):
            patterns.append("长上影十字")
        elif lower_shadow >= 2.0 * max(0.001, upper_shadow):
            patterns.append("长下影十字")
        else:
            patterns.append("十字星")

    # 孕线（身怀六甲） / 十字孕线
    if n >= 2:
        prev_body_large = (abs(prev_c - prev_o) / max(0.01, prev_o)) >= 0.015
        is_inside = max(cur_c, cur_o) <= max(prev_c, prev_o) and min(cur_c, cur_o) >= min(prev_c, prev_o)
        if prev_body_large and is_inside:
            if is_doji:
                patterns.append("十字孕线")
            else:
                patterns.append("孕线")

    # 跳空缺口
    if n >= 2:
        if cur_l > prev_h * 1.001:
            patterns.append("向上跳空缺口")
        elif cur_h < prev_l * 0.999:
            patterns.append("向下跳空缺口")

    # =========================================================================
    # 五、辅助指标信号（MACD, KDJ, RSI, CCI, OBV）
    # =========================================================================

    # 1. MACD 金叉 / 死叉 / 零轴下金叉 / 背离
    try:
        dif, dea, _ = MACD(c)
        dif_a = np.asarray(dif, dtype=float)
        dea_a = np.asarray(dea, dtype=float)
        if len(dif_a) >= 2:
            if dif_a[-1] > dea_a[-1] and dif_a[-2] <= dea_a[-2]:
                if dea_a[-1] > 0:
                    patterns.append("零上金叉")
                elif dea_a[-1] < 0:
                    patterns.append("零轴下金叉")
                else:
                    patterns.append("MACD金叉")
            elif dif_a[-1] < dea_a[-1] and dif_a[-2] >= dea_a[-2]:
                patterns.append("MACD死叉")

            # MACD 顶底背离判定 (近20日)
            if n >= 25:
                if cur_c >= float(np.max(c[-20:])) and dif_a[-1] < float(np.max(dif_a[-20:])) * 0.85:
                    patterns.append("MACD顶背离")
                elif cur_c <= float(np.min(c[-20:])) and dif_a[-1] > float(np.min(dif_a[-20:])) + 0.05:
                    patterns.append("MACD底背离")
    except Exception:
        pass

    # 2. KDJ 低位金叉 / 高位死叉 / 超买 / 超卖
    try:
        k_val, d_val, _ = KDJ(c, h, l)
        k_a = np.asarray(k_val, dtype=float)
        d_a = np.asarray(d_val, dtype=float)
        if len(k_a) >= 2:
            if k_a[-1] > d_a[-1] and k_a[-2] <= d_a[-2] and k_a[-1] <= 40:
                patterns.append("KDJ低位金叉")
            elif k_a[-1] < d_a[-1] and k_a[-2] >= d_a[-2] and k_a[-1] >= 65:
                patterns.append("KDJ高位死叉")
            elif k_a[-1] >= 80 and d_a[-1] >= 80:
                patterns.append("KDJ超买")
            elif k_a[-1] <= 20 and d_a[-1] <= 20:
                patterns.append("KDJ超卖")
    except Exception:
        pass

    # 3. RSI 超买 / 超卖 / 背离
    try:
        rsi_vals = np.asarray(RSI(c, 14), dtype=float)
        if len(rsi_vals) >= 2:
            if rsi_vals[-1] >= 75:
                patterns.append("RSI超买")
            elif rsi_vals[-1] <= 25:
                patterns.append("RSI超卖")
            if n >= 25:
                if cur_c >= float(np.max(c[-20:])) and rsi_vals[-1] < float(np.max(rsi_vals[-20:])) - 5.0:
                    patterns.append("RSI顶背离")
                elif cur_c <= float(np.min(c[-20:])) and rsi_vals[-1] > float(np.min(rsi_vals[-20:])) + 5.0:
                    patterns.append("RSI底背离")
    except Exception:
        pass

    # 4. CCI 顺势指标突破 / 超卖
    try:
        cci_vals = np.asarray(CCI(c, h, l, 14), dtype=float)
        if len(cci_vals) >= 2:
            if cci_vals[-1] > 100 and cci_vals[-2] <= 100:
                patterns.append("CCI突破")
            elif cci_vals[-1] < -100:
                patterns.append("CCI超卖")
    except Exception:
        pass

    # 5. OBV 能量潮创新高 / 顶背离
    try:
        obv_vals = np.asarray(OBV(c, v), dtype=float)
        if len(obv_vals) >= 20:
            if obv_vals[-1] >= float(np.max(obv_vals[-20:])) and vol_ratio >= 1.2:
                patterns.append("OBV创新高")
            elif cur_c >= float(np.max(c[-20:])) and obv_vals[-1] < float(np.max(obv_vals[-20:])) * 0.9:
                patterns.append("OBV顶背离")
    except Exception:
        pass

    # =========================================================================
    # 六、量价形态
    # =========================================================================

    # 1. 放量滞涨 (高位巨量但涨幅停滞)
    if cur_c >= float(np.mean(c[-min(20, n):])) and vol_ratio >= 1.7 and abs(cur_chg_pct) <= 0.8:
        patterns.append("放量滞涨")

    # 2. 放量下跌 (巨量下砸，抛压沉重)
    if cur_chg_pct <= -2.5 and vol_ratio >= 1.5:
        patterns.append("放量下跌")

    # 3. 地量 (近20日极度缩量，变盘临界点)
    if n >= 20 and cur_v <= float(np.min(v[-20:])) * 1.05 and vol_ratio <= 0.65:
        patterns.append("地量")

    # 4. 价涨量增 (健康上涨，价量齐飞)
    if cur_chg_pct >= 1.5 and vol_ratio >= 1.25:
        patterns.append("价涨量增")

    # 5. 价涨量缩 (量价背离，警惕无量空涨诱多)
    if cur_chg_pct >= 1.5 and vol_ratio <= 0.75:
        patterns.append("量价背离")

    # =========================================================================
    # 七、布林带形态
    # =========================================================================
    try:
        b_up, b_mid, b_low = BOLL(c, 20, 2)
        up_a = np.asarray(b_up, dtype=float)
        mid_a = np.asarray(b_mid, dtype=float)
        low_a = np.asarray(b_low, dtype=float)
        if len(up_a) >= 5 and mid_a[-1] > 0:
            bandwidth = (up_a[-1] - low_a[-1]) / mid_a[-1]
            prev_bandwidth = (up_a[-2] - low_a[-2]) / mid_a[-2]
            if cur_c >= up_a[-1] and bandwidth > prev_bandwidth:
                patterns.append("布林突破")
            elif cur_c <= low_a[-1]:
                patterns.append("布林跌破")
            elif cur_h >= up_a[-1] * 0.995 and cur_c < up_a[-1]:
                patterns.append("布林上轨压力")
            elif cur_l <= low_a[-1] * 1.005 and cur_c > low_a[-1]:
                patterns.append("布林下轨支撑")

            if bandwidth < 0.09:
                patterns.append("布林收口")
            elif bandwidth > (up_a[-3] - low_a[-3]) / mid_a[-3] * 1.35 and bandwidth > 0.16:
                patterns.append("布林开口")
    except Exception:
        pass

    # =========================================================================
    # 八、缠论分型与 TD 序列
    # =========================================================================

    # 底分型确立
    if n >= 5:
        if float(l[-2]) == float(np.min(l[-5:])) and cur_c > float(h[-2]) and cur_c > cur_o:
            patterns.append("底分型")

    # 顶分型衰竭
    if n >= 5:
        if float(h[-2]) == float(np.max(h[-5:])) and cur_c < float(l[-2]) and cur_c < cur_o:
            patterns.append("顶分型")

    # TD9 见底 / TD9 见顶
    try:
        td9_h, td9_l = TD_SEQUENTIAL(c, 9)
        td9_l_arr = np.asarray(td9_l, dtype=int)
        td9_h_arr = np.asarray(td9_h, dtype=int)
        if len(td9_l_arr) > 0 and (td9_l_arr[-1] >= 9 or (n >= 2 and td9_l_arr[-2] >= 9 and cur_c > cur_o)):
            patterns.append("TD9见底")
        elif len(td9_h_arr) > 0 and (td9_h_arr[-1] >= 9 or (n >= 2 and td9_h_arr[-2] >= 9 and cur_c < cur_o)):
            patterns.append("TD9见顶")
    except Exception:
        pass

    # TD13 极致计数反转
    try:
        td13_h, td13_l = TD_SEQUENTIAL(c, 13)
        td13_l_arr = np.asarray(td13_l, dtype=int)
        td13_h_arr = np.asarray(td13_h, dtype=int)
        if len(td13_l_arr) > 0 and td13_l_arr[-1] >= 13:
            patterns.append("TD13见底")
        elif len(td13_h_arr) > 0 and td13_h_arr[-1] >= 13:
            patterns.append("TD13见顶")
    except Exception:
        pass

    # Deduplicate while preserving order
    seen = set()
    unique_patterns = []
    for p in patterns:
        if p not in seen:
            seen.add(p)
            unique_patterns.append(p)

    # Fallback if no specific trigger fired
    if not unique_patterns:
        if n >= 20 and len(ma20) > 0:
            if cur_c >= float(ma20[-1]):
                unique_patterns.append("震荡蓄势")
            else:
                unique_patterns.append("弱势整理")
        else:
            unique_patterns.append("震荡整理")

    return unique_patterns


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
