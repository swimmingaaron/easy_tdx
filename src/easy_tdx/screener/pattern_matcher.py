"""形态匹配选股 (Pattern Matching Screener) 核心多维复合算法与深度选股引擎。

参考通达信形态匹配选股功能及量化形态识别最佳实践：
1. 输入：用户在 K 线图上拖拉框选的收盘价序列 (长度 M 根)；
2. 多维复合相似度算法：
   - 趋势方向相关度 (Pearson Correlation r, 权重 40%)
   - 几何形态轮廓契合度 (Normalized Euclidean Distance / RMSE, 权重 30%)
   - 涨跌幅与振幅匹配度 (Return & Amplitude Ratio, 权重 20%)
   - 极值拐点位置吻合度 (Peak/Valley Timing Alignment, 权重 10%)
3. 双重匹配模式：
   - 即时形态匹配：寻找当前最新 M 根 K 线走势与模板形态高度吻合的候选股（当期买点触发）
   - 历史滑动寻优：在最近 lookback 窗口中滑动匹配最佳形态，并输出该形态确立后未来 5/10/20 根 K 线的实际历史收益率
4. 模板后续验证推演：
   - 当用户框选的是历史形态区间时，自动提取模板后续走势及涨跌幅，为候选股对标提供明确参考
5. 丰富的股票池与行业赛道过滤：
   - 核心龙头 (core)、沪深300 (hs300)、中证500 (zz500)、中证1000 (zz1000)、全市场 (all)、细分行业赛道
   - 排除 ST/*ST、排除科创板/创业板/北交所
6. 性能与缓存：
   - 深度集成 screener 内存日K缓存与多线程并发，毫秒级比对。
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
from easy_tdx.screener.industry import load_industry_universe
from easy_tdx.screener.scanner import _get_or_fetch_kline

logger = logging.getLogger(__name__)


def normalize_min_max(arr: np.ndarray | list[float]) -> list[float]:
    """将数值序列归一化到 0~100 范围，便于前端图表双线拟合对比。"""
    if len(arr) == 0:
        return []
    np_arr = np.array(arr, dtype=float)
    min_v = float(np.min(np_arr))
    max_v = float(np.max(np_arr))
    diff = max_v - min_v
    if diff <= 1e-8:
        return [50.0] * len(np_arr)
    return [round(float((v - min_v) / diff * 100), 1) for v in np_arr]


def calc_pearson_correlation(x: np.ndarray, y: np.ndarray) -> float:
    """计算两组等长序列的皮尔逊相关系数。"""
    if len(x) != len(y) or len(x) < 3:
        return 0.0
    x_std = float(np.std(x))
    y_std = float(np.std(y))
    if x_std <= 1e-8 or y_std <= 1e-8:
        return 0.0
    x_norm = (x - np.mean(x)) / x_std
    y_norm = (y - np.mean(y)) / y_std
    corr = float(np.mean(x_norm * y_norm))
    return max(-1.0, min(1.0, corr))


def calc_composite_similarity(
    x: np.ndarray, 
    y: np.ndarray
) -> tuple[float, dict[str, float]]:
    """计算多维复合形态相似度得分 (0.0 ~ 100.0) 及各分项维度。
    
    维度构成：
    1. 趋势相关度 (s_corr): 衡量涨跌趋势方向的协方差；
    2. 几何形态契合度 (s_geom): 归一化后的 RMSE，衡量波动曲线的形状契合度；
    3. 涨跌与振幅匹配度 (s_scale): 衡量幅度力度比率，防止死水微澜股被误判为高相似；
    4. 极值拐点位置吻合度 (s_turning): 衡量最高点与最低点出现时刻的同步性。
    """
    n = len(x)
    if n != len(y) or n < 3:
        return 0.0, {"corr": 0.0, "geom": 0.0, "scale": 0.0, "turning": 0.0}

    # 1. 趋势方向相关度 (Pearson Correlation)
    x_std = float(np.std(x))
    y_std = float(np.std(y))
    if x_std <= 1e-8 or y_std <= 1e-8:
        r = 0.0
    else:
        x_norm = (x - np.mean(x)) / x_std
        y_norm = (y - np.mean(y)) / y_std
        r = float(np.mean(x_norm * y_norm))
        r = max(-1.0, min(1.0, r))

    # 若相关系数为负或极微弱正相关，直接判定形态不匹配
    if r <= 0.15:
        return 0.0, {"corr": round(max(0.0, r) * 100, 1), "geom": 0.0, "scale": 0.0, "turning": 0.0}

    s_corr = r * 100.0

    # 2. 几何形态轮廓契合度 (Min-Max 归一化后的 RMSE)
    x_min, x_max = float(np.min(x)), float(np.max(x))
    y_min, y_max = float(np.min(y)), float(np.max(y))
    x_diff = x_max - x_min
    y_diff = y_max - y_min

    if x_diff <= 1e-8 or y_diff <= 1e-8:
        s_geom = 50.0
    else:
        xn = (x - x_min) / x_diff
        yn = (y - y_min) / y_diff
        rmse = float(np.sqrt(np.mean((xn - yn) ** 2)))
        s_geom = max(0.0, min(100.0, (1.0 - rmse * 1.414) * 100.0))

    # 3. 幅度与收益率比率匹配度 (Scale & Return Matching)
    ret_x = (x[-1] - x[0]) / (x[0] + 1e-8)
    ret_y = (y[-1] - y[0]) / (y[0] + 1e-8)

    # 方向反向惩罚 (例如模板涨超 2% 而候选跌超 2%)
    if (ret_x > 0.02 and ret_y < -0.02) or (ret_x < -0.02 and ret_y > 0.02):
        s_scale = 0.0
    else:
        ret_ratio = min(abs(ret_x) + 0.01, abs(ret_y) + 0.01) / (max(abs(ret_x), abs(ret_y)) + 0.01)
        amp_x = (x_max - x_min) / (x_min + 1e-8)
        amp_y = (y_max - y_min) / (y_min + 1e-8)
        amp_ratio = min(amp_x + 0.01, amp_y + 0.01) / (max(amp_x, amp_y) + 0.01)
        s_scale = float((ret_ratio * 0.5 + amp_ratio * 0.5) * 100.0)

    # 4. 转折极值点位置吻合度 (Peak/Valley Timing Alignment)
    x_max_idx = int(np.argmax(x))
    y_max_idx = int(np.argmax(y))
    x_min_idx = int(np.argmin(x))
    y_min_idx = int(np.argmin(y))
    max_diff_pct = abs(x_max_idx - y_max_idx) / (n - 1)
    min_diff_pct = abs(x_min_idx - y_min_idx) / (n - 1)
    s_turning = max(0.0, min(100.0, (1.0 - (max_diff_pct + min_diff_pct) * 0.5) * 100.0))

    composite = (
        s_corr * 0.40 +
        s_geom * 0.30 +
        s_scale * 0.20 +
        s_turning * 0.10
    )
    # 若波动幅度或收益率极度不匹配 (s_scale < 25)，施加缩放惩罚
    if s_scale < 25.0:
        composite *= (s_scale / 25.0)

    composite = max(0.0, min(100.0, composite))

    details = {
        "corr": round(s_corr, 1),
        "geom": round(s_geom, 1),
        "scale": round(s_scale, 1),
        "turning": round(s_turning, 1),
    }
    return round(composite, 1), details


def match_single_stock(
    symbol: str,
    target_pattern: np.ndarray,
    period: str = "DAY",
    lookback_window: int = 0,
    min_similarity: float = 65.0,
    industry_map: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """比对单个标的与模板形态的匹配度。"""
    clean_sym = symbol.strip().upper().replace("SH", "").replace("SZ", "").replace("BJ", "").replace(".", "")
    m_len = len(target_pattern)
    req_bars = max(m_len + 15, (lookback_window if lookback_window > 0 else m_len) + 15)

    try:
        # 优先使用 scanner 内存日K缓存加速
        df = _get_or_fetch_kline(clean_sym, period=period)
        if df is None or len(df) < m_len:
            df = fetch_security_kline(clean_sym, period=period, count=req_bars, adjust="qfq")

        if df is None or df.empty or len(df) < m_len:
            return None

        closes = df["close"].to_numpy(dtype=float)
        dates = df["datetime"].astype(str).tolist() if "datetime" in df.columns else []

        best_score = -1.0
        best_details: dict[str, float] = {}
        best_slice: np.ndarray | None = None
        best_start_idx = -1
        best_end_idx = -1

        if lookback_window <= 0 or lookback_window <= m_len:
            # 仅匹配最新 m_len 根 K 线（即时形态匹配）
            sub = closes[-m_len:]
            score, details = calc_composite_similarity(target_pattern, sub)
            best_score = score
            best_details = details
            best_slice = sub
            best_start_idx = len(closes) - m_len
            best_end_idx = len(closes) - 1
        else:
            # 滑动窗口查找：在最近 lookback_window 内寻找最佳匹配
            window_len = min(len(closes), lookback_window)
            start_search = len(closes) - window_len
            for i in range(start_search, len(closes) - m_len + 1):
                sub = closes[i : i + m_len]
                score, details = calc_composite_similarity(target_pattern, sub)
                if score > best_score:
                    best_score = score
                    best_details = details
                    best_slice = sub
                    best_start_idx = i
                    best_end_idx = i + m_len - 1

        if best_score < min_similarity or best_slice is None:
            return None

        # 候选形态区间涨跌幅与振幅
        slice_ret = round((best_slice[-1] - best_slice[0]) / (best_slice[0] + 1e-8) * 100, 2)
        slice_amp = round((float(np.max(best_slice)) - float(np.min(best_slice))) / (best_slice[0] + 1e-8) * 100, 2)

        # 最新现价与最新单日涨跌幅
        latest_close = float(closes[-1])
        prev_close = float(closes[-2]) if len(closes) >= 2 else latest_close
        pct_chg = round((latest_close - prev_close) / prev_close * 100, 2) if prev_close > 0 else 0.0

        start_date = dates[best_start_idx] if 0 <= best_start_idx < len(dates) else ""
        end_date = dates[best_end_idx] if 0 <= best_end_idx < len(dates) else ""

        # 历史滑动匹配模式下的后续收益验证 (未来 5/10/20 根 K 线表现)
        forward_bars = len(closes) - 1 - best_end_idx
        forward_returns = None
        if forward_bars > 0:
            f5 = round((closes[min(len(closes) - 1, best_end_idx + 5)] - closes[best_end_idx]) / (closes[best_end_idx] + 1e-8) * 100, 2) if forward_bars >= 5 else None
            f10 = round((closes[min(len(closes) - 1, best_end_idx + 10)] - closes[best_end_idx]) / (closes[best_end_idx] + 1e-8) * 100, 2) if forward_bars >= 10 else None
            f20 = round((closes[min(len(closes) - 1, best_end_idx + 20)] - closes[best_end_idx]) / (closes[best_end_idx] + 1e-8) * 100, 2) if forward_bars >= 20 else None
            forward_returns = {
                "forward_bars": forward_bars,
                "f5": f5,
                "f10": f10,
                "f20": f20
            }

        # 归一化点位供前端绘制对比 Sparkline
        cand_norm = normalize_min_max(best_slice)

        # 股票名称与行业归属
        name = get_stock_name(clean_sym)
        ind_info = industry_map.get(clean_sym, {}) if industry_map else {}
        ind_name = ind_info.get("name", "其它")
        ind_cat = ind_info.get("category", "")

        return {
            "code": clean_sym,
            "name": name,
            "similarity": round(best_score, 1),
            "correlation": round(best_details.get("corr", 0.0) / 100.0, 4),
            "details": best_details,
            "latest_price": latest_close,
            "pct_change": pct_chg,
            "range_chg": slice_ret,
            "range_amp": slice_amp,
            "start_date": start_date,
            "end_date": end_date,
            "matched_bars": m_len,
            "cand_points": cand_norm,
            "industry": ind_name,
            "category": ind_cat,
            "forward_returns": forward_returns,
            "is_realtime": (best_end_idx == len(closes) - 1),
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
    min_similarity: float = 65.0,
    exclude_st: bool = True,
    exclude_gem_star: bool = False,
    target_future_prices: list[float] | None = None,
    max_workers: int = 24,
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

    # 加载行业板块内存字典
    try:
        uni = load_industry_universe()
        industry_map = uni.get("stock_to_industry", {})
    except Exception:
        industry_map = {}

    # 确定股票池标的列表
    if symbols and len(symbols) > 0:
        cand_symbols = symbols
    else:
        cand_symbols = get_universe_symbols(universe)

    # 排除模板自身
    cand_symbols = [
        s for s in cand_symbols 
        if s.strip().upper().replace("SH", "").replace("SZ", "").replace("BJ", "").replace(".", "") != clean_target
    ]

    # 排除 ST/*ST 股
    if exclude_st:
        cand_symbols = [
            s for s in cand_symbols 
            if "ST" not in get_stock_name(s).upper()
        ]

    # 排除创业板(300/301)、科创板(688)、北交所(8/4/920)
    if exclude_gem_star:
        cand_symbols = [
            s for s in cand_symbols 
            if not s.strip().upper().replace("SH", "").replace("SZ", "").replace("BJ", "").replace(".", "").startswith(("300", "301", "688", "8", "4", "920"))
        ]

    target_norm = normalize_min_max(target_arr)

    # 计算模板本身的统计指标
    target_ret = round((float(target_arr[-1]) - float(target_arr[0])) / (float(target_arr[0]) + 1e-8) * 100, 2)
    target_amp = round((float(np.max(target_arr)) - float(np.min(target_arr))) / (float(target_arr[0]) + 1e-8) * 100, 2)
    target_stats = {
        "target_len": len(target_arr),
        "target_ret": target_ret,
        "target_amp": target_amp,
        "start_price": round(float(target_arr[0]), 2),
        "end_price": round(float(target_arr[-1]), 2),
        "high_price": round(float(np.max(target_arr)), 2),
        "low_price": round(float(np.min(target_arr)), 2),
    }

    # 计算模板后续走势表现验证（若存在后续 K 线）
    target_future_stats = None
    if target_future_prices and len(target_future_prices) > 0:
        base_p = float(target_arr[-1])
        f_arr = np.array(target_future_prices, dtype=float)
        f_last = float(f_arr[-1])
        f_max = float(np.max(f_arr))
        f_min = float(np.min(f_arr))
        target_future_stats = {
            "future_bars": len(f_arr),
            "future_ret": round((f_last - base_p) / (base_p + 1e-8) * 100, 2),
            "future_max_gain": round((f_max - base_p) / (base_p + 1e-8) * 100, 2),
            "future_max_drawdown": round((f_min - base_p) / (base_p + 1e-8) * 100, 2),
            "future_points": normalize_min_max(np.concatenate([target_arr[-1:], f_arr]))
        }

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
                min_similarity=min_similarity,
                industry_map=industry_map,
            ): sym
            for sym in cand_symbols
        }

        for future in as_completed(future_to_sym):
            total_scanned += 1
            res = future.result()
            if res is not None:
                matches.append(res)

    # 按复合相似度降序排序
    matches.sort(key=lambda m: m["similarity"], reverse=True)
    top_matches = matches[:top_n]

    cost = round(time.time() - t0, 2)

    return {
        "status": "success",
        "target_symbol": clean_target,
        "target_name": get_stock_name(clean_target),
        "target_len": len(target_arr),
        "target_points": target_norm,
        "target_stats": target_stats,
        "target_future_stats": target_future_stats,
        "universe": universe,
        "period": period,
        "lookback_window": lookback_window,
        "min_similarity": min_similarity,
        "total_scanned": total_scanned,
        "matched_count": len(matches),
        "matches": top_matches,
        "cost_seconds": cost,
    }
