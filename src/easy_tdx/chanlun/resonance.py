"""缠论多周期立体共振买卖点计算引擎与数据格式化模块。

支持周期：
    月线 (MONTH) | 周线 (WEEK) | 日线 (DAY) | 120F (120分钟) |
    60F (60分钟) | 30F (30分钟) | 15F (15分钟) | 5F (5分钟) | 1F (1分钟)

核心能力：
1. 三周期立体共振买卖点识别引擎 (ThreePeriodResonanceEngine)；
2. 大/中级别分型、笔、中枢向基准小级别的坐标精确对齐映射；
3. 支持历史截断回溯 (Backtracking / Replay)；
4. 格式化生成 ECharts / Web 前端图表所需的统一立体结构及各周期独立分屏结构。
"""

from __future__ import annotations

import bisect
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from concurrent.futures import ThreadPoolExecutor
import numpy as np
import pandas as pd

from easy_tdx.chanlun.analyser import ChanlunAnalyser, ChanlunResult
from easy_tdx.chanlun.types import BI, FX, MMD, ZS, Direction, FXType, MMDType
from easy_tdx.chanlun.resample import convert_kline_frequency, can_resample_from
from easy_tdx.chanlun.kline_cache import get_global_kline_disk_cache
from easy_tdx.market_data import fetch_security_kline
from easy_tdx.stock_lookup import get_stock_name
from easy_tdx.MyTT import RSI, KDJ, EXPMA, MA, MACD


def safe_float(val: Any, default: float | None = None) -> float | None:
    if val is None or pd.isna(val) or np.isnan(val) or np.isinf(val):
        return default
    return round(float(val), 2)


def calculate_inflow_data(
    df: pd.DataFrame,
    clean_code: str | None = None,
    is_backtracking: bool = False,
    is_daily: bool = True,
) -> dict[str, list[float | None]]:
    """参考 K 线弹窗 (quotes.py) 算法计算逐根 K 线主力资金净流入及移动平均线，并在日线实时态用 Level-2 官方主力净流入校准。"""
    if df.empty or len(df) == 0:
        return {"net_inflow": [], "ma3": [], "ma5": [], "ma10": []}

    c = df["close"].values.astype(float)
    o = df["open"].values.astype(float)
    h = df["high"].values.astype(float)
    l = df["low"].values.astype(float)
    v = df["volume"].values.astype(float) if "volume" in df.columns else np.zeros(len(df), dtype=float)

    if "amount" in df.columns:
        amt_vals = df["amount"].values.astype(float)
        mask = np.isnan(amt_vals) | (amt_vals <= 0)
        amt_vals[mask] = (c * v)[mask]
    else:
        amt_vals = (c * v).astype(float)

    n_len = len(df)
    net_inflows = np.zeros(n_len, dtype=float)
    for idx in range(n_len):
        c_i = float(c[idx])
        o_i = float(o[idx])
        h_i = float(h[idx])
        l_i = float(l[idx])
        amt_i = float(amt_vals[idx])
        pre_c_i = float(c[idx - 1]) if idx > 0 else o_i
        hl_diff = max(0.001, h_i - l_i)
        body_r = (c_i - o_i) / hl_diff
        pos_r = (c_i - l_i) / hl_diff - 0.5
        chg_r = ((c_i / max(0.01, pre_c_i)) - 1.0) * 10.0
        # Realistic net capital inflow ratio in A-share market is bounded in [-0.20, 0.20]
        flow_r = max(-0.20, min(0.20, body_r * 0.08 + pos_r * 0.06 + chg_r * 0.10))
        net_inflows[idx] = round(amt_i * flow_r, 2)

    # 仅在非历史回溯且日线模式下，使用通达信 Level-2 官方主力净流入进行权威校准（与 quotes.py 弹窗逻辑完全保持一致）
    if not is_backtracking and is_daily and clean_code and n_len > 0:
        m1_real = 0.0
        m3_real = 0.0
        m5_real = 0.0
        try:
            from easy_tdx.web.routers.quotes import _STOCK_MAC_CACHE, _STOCK_MAC_LOCK
            now_q = time.time()
            with _STOCK_MAC_LOCK:
                if clean_code in _STOCK_MAC_CACHE:
                    ts_q, c_val = _STOCK_MAC_CACHE[clean_code]
                    if now_q - ts_q < 3600.0:
                        m1_real = float(c_val.get("main_net_amount") or 0.0)
                        m3_real = float(c_val.get("main_net_3d_amount") or 0.0)
                        m5_real = float(c_val.get("main_net_5d_amount") or 0.0)
        except Exception:
            pass

        if m1_real == 0.0 and m3_real == 0.0 and m5_real == 0.0:
            try:
                from easy_tdx.market_data import _get_or_create_mac_client
                from easy_tdx.codec.bitmap import FieldBit, PresetField
                mac = _get_or_create_mac_client()
                fields = (
                    PresetField.BASIC
                    + FieldBit.AMOUNT
                    + FieldBit.MAIN_NET_AMOUNT
                    + FieldBit.MAIN_NET_3D_AMOUNT
                    + FieldBit.MAIN_NET_5D_AMOUNT
                )
                mac_mkt = 1 if (clean_code.startswith(("6", "9")) or clean_code.startswith("sh")) else 0
                df_q = mac.get_stock_quotes([(mac_mkt, clean_code)], fields=fields)
                if df_q is not None and not df_q.empty:
                    row_q = df_q.iloc[0]
                    m1_real = float(row_q.get("main_net_amount") or 0.0)
                    m3_real = float(row_q.get("main_net_3d_amount") or 0.0)
                    m5_real = float(row_q.get("main_net_5d_amount") or 0.0)
                    try:
                        from easy_tdx.web.routers.quotes import _STOCK_MAC_CACHE, _STOCK_MAC_LOCK
                        with _STOCK_MAC_LOCK:
                            _STOCK_MAC_CACHE[clean_code] = (
                                time.time(),
                                {
                                    "main_net_amount": m1_real,
                                    "main_net_3d_amount": m3_real,
                                    "main_net_5d_amount": m5_real,
                                },
                            )
                    except Exception:
                        pass
            except Exception as e_calib:
                logging.getLogger("chanlun.resonance").debug("Level-2 inflow calib fetch failed: %s", e_calib)

        if m1_real != 0.0 or m3_real != 0.0 or m5_real != 0.0:
            net_inflows[-1] = round(m1_real, 2)

            # Calibrate 3-day window
            if n_len >= 3 and m3_real != 0.0:
                diff_3 = m3_real - m1_real
                w3_idx = [-2, -3]
                tot_a_3 = max(1.0, float(amt_vals[w3_idx[0]]) + float(amt_vals[w3_idx[1]]))
                sum_r_3 = float(net_inflows[w3_idx[0]]) + float(net_inflows[w3_idx[1]])
                for i in w3_idx:
                    w = float(amt_vals[i]) / tot_a_3
                    net_inflows[i] = round(w * diff_3 + (net_inflows[i] - w * sum_r_3), 2)

            # Calibrate 5-day window
            if n_len >= 5 and m5_real != 0.0:
                diff_5 = m5_real - (m3_real if m3_real != 0.0 else (m1_real * 3.0))
                w5_idx = [-4, -5]
                tot_a_5 = max(1.0, float(amt_vals[w5_idx[0]]) + float(amt_vals[w5_idx[1]]))
                sum_r_5 = float(net_inflows[w5_idx[0]]) + float(net_inflows[w5_idx[1]])
                for i in w5_idx:
                    w = float(amt_vals[i]) / tot_a_5
                    net_inflows[i] = round(w * diff_5 + (net_inflows[i] - w * sum_r_5), 2)

    inflow_ma3 = MA(net_inflows, 3)
    inflow_ma5 = MA(net_inflows, 5)
    inflow_ma10 = MA(net_inflows, 10)

    return {
        "net_inflow": [round(float(v_val), 2) for v_val in net_inflows],
        "ma3": [safe_float(v_val) for v_val in inflow_ma3],
        "ma5": [safe_float(v_val) for v_val in inflow_ma5],
        "ma10": [safe_float(v_val) for v_val in inflow_ma10],
    }


def build_merged_chart_data(
    low_res: ChanlunResult,
    base_df: pd.DataFrame,
    dates: list[str],
    high_bis: list[dict],
    high_zss: list[dict],
    mid_bis: list[dict],
    mid_zss: list[dict],
    mmd_marks: list[dict],
    res_marks: list[dict],
    clean_code: str | None = None,
    is_backtracking: bool = False,
    is_daily: bool = True,
    fractal_marks: list[dict] | None = None,
) -> dict[str, Any]:
    """严格按照缠论标准包含关系，构建合并后的 K 线图及关联的笔、中枢、买卖点、指标数据。"""
    cklines = getattr(low_res, "cklines", []) or []
    n_ck = len(cklines)
    n_base = len(base_df)

    if n_ck == 0 or n_base == 0:
        return {
            "dates": [],
            "candles": [],
            "volumes": [],
            "amounts": [],
            "high_bis": [],
            "high_zss": [],
            "mid_bis": [],
            "mid_zss": [],
            "low_bis": [],
            "low_zss": [],
            "fractal_marks": [],
            "mmd_marks": [],
            "res_marks": [],
            "macd": {"hist": [], "dif": [], "dea": [], "marks": []},
            "macd_marks": [],
            "macd_div_lines": [],
            "rsi": {"rsi6": [], "rsi12": [], "rsi24": []},
            "kdj": {"k": [], "d": [], "j": []},
            "expma": {"exp12": [], "exp50": []},
            "inflow": {"net_inflow": [], "ma3": [], "ma5": [], "ma10": []},
        }

    raw_to_ck_idx: dict[int, int] = {}
    date_to_ck_idx: dict[str, int] = {}
    ck_dates: list[str] = []
    ck_candles: list[list[float]] = []
    ck_volumes: list[list[Any]] = []
    ck_amounts: list[list[Any]] = []

    base_vols = base_df["volume"].values if "volume" in base_df.columns else np.zeros(n_base)
    base_amts = base_df["amount"].values if "amount" in base_df.columns else None
    base_closes = base_df["close"].values if "close" in base_df.columns else np.zeros(n_base)

    for ck_i, ck in enumerate(cklines):
        # 记录每根 raw kline 所属的 ck_i
        for k in ck.klines:
            raw_to_ck_idx[k.index] = ck_i
            if 0 <= k.index < len(dates):
                date_to_ck_idx[dates[k.index]] = ck_i

        # 确定该根合并 K 线的坐标日期 (取末根原始 K 线日期)
        last_k_idx = ck.klines[-1].index if ck.klines else ck.k_index
        if 0 <= last_k_idx < len(dates):
            d_str = dates[last_k_idx]
        else:
            d_str = low_res._fmt_dt(ck.date)
        ck_dates.append(d_str)

        # 按照缠论理论合并：基于缠论的 K 线只有最高和最低，没有上下影线
        # 向上实体：open=low, close=high（从最低填满到最高，上影线=0，下影线=0）
        # 向下实体：open=high, close=low（从最高填满到最低，上影线=0，下影线=0）
        c_low = round(float(ck.low), 2)
        c_high = round(float(ck.high), 2)
        is_up = (ck.direction == "up") if ck.direction else (ck.close >= ck.open)

        if is_up:
            ck_candles.append([c_low, c_high, c_low, c_high])
        else:
            ck_candles.append([c_high, c_low, c_low, c_high])

        # 成交量与成交额累加
        v_sum = sum(float(base_vols[k.index]) for k in ck.klines if k.index < len(base_vols))
        if base_amts is not None:
            a_sum = sum(
                float(base_amts[k.index])
                if pd.notna(base_amts[k.index]) and float(base_amts[k.index]) > 0
                else float(base_vols[k.index] * base_closes[k.index])
                for k in ck.klines
                if k.index < len(base_amts)
            )
        else:
            a_sum = v_sum * float(ck.close)

        is_up = 1 if ck.close >= ck.open else -1
        ck_volumes.append([ck_i, round(v_sum, 2), is_up])
        ck_amounts.append([ck_i, round(a_sum, 2), is_up])

    # 1. 当前基准级别的笔与中枢（严格依据包含合并后的 cklines 索引）
    ck_low_bis = [
        {
            "start": [ck_dates[bi.start.k.index], round(bi.start.val, 2)],
            "end": [ck_dates[bi.end.k.index], round(bi.end.val, 2)],
            "direction": bi.direction.value,
            "done": bi.is_done(),
        }
        for bi in low_res.bis
        if 0 <= bi.start.k.index < n_ck and 0 <= bi.end.k.index < n_ck
    ]

    ck_low_zss = [
        {
            "start_date": ck_dates[zs.start.k.index],
            "end_date": ck_dates[zs.end.k.index],
            "zg": round(zs.zg, 2),
            "zd": round(zs.zd, 2),
            "gg": round(zs.gg, 2),
            "dd": round(zs.dd, 2),
        }
        for zs in low_res.zss
        if zs.start and zs.end
        and 0 <= zs.start.k.index < n_ck
        and 0 <= zs.end.k.index < n_ck
    ]

    # 日期映射辅助函数：将 raw 日期映射为最匹配的 ck_date
    def map_raw_date_to_ck_date(d_val: str) -> str:
        if not ck_dates or not d_val:
            return d_val
        if d_val in date_to_ck_idx:
            return ck_dates[date_to_ck_idx[d_val]]
        idx = bisect.bisect_right(ck_dates, d_val) - 1
        idx = max(0, min(n_ck - 1, idx))
        return ck_dates[idx]

    # 2. 映射大级别与中级别笔到合并 K 线坐标系
    ck_high_bis = []
    for b in high_bis:
        s_date = map_raw_date_to_ck_date(b["start"][0])
        e_date = map_raw_date_to_ck_date(b["end"][0])
        ck_high_bis.append({
            "start": [s_date, b["start"][1]],
            "end": [e_date, b["end"][1]],
            "direction": b.get("direction", ""),
            "done": b.get("done", True),
        })

    ck_mid_bis = []
    for b in mid_bis:
        s_date = map_raw_date_to_ck_date(b["start"][0])
        e_date = map_raw_date_to_ck_date(b["end"][0])
        ck_mid_bis.append({
            "start": [s_date, b["start"][1]],
            "end": [e_date, b["end"][1]],
            "direction": b.get("direction", ""),
            "done": b.get("done", True),
        })

    # 3. 映射大级别与中级别中枢
    ck_high_zss = [
        {
            **zs,
            "start_date": map_raw_date_to_ck_date(zs["start_date"]),
            "end_date": map_raw_date_to_ck_date(zs["end_date"]),
        }
        for zs in high_zss
    ]

    ck_mid_zss = [
        {
            **zs,
            "start_date": map_raw_date_to_ck_date(zs["start_date"]),
            "end_date": map_raw_date_to_ck_date(zs["end_date"]),
        }
        for zs in mid_zss
    ]

    # 4. 买卖点与共振标记映射
    ck_mmd_marks = []
    for m in mmd_marks:
        raw_d = m.get("date") or (m.get("coord")[0] if m.get("coord") else "")
        ck_d = map_raw_date_to_ck_date(raw_d)
        m_copy = dict(m)
        m_copy["date"] = ck_d
        if "coord" in m_copy and len(m_copy["coord"]) == 2:
            m_copy["coord"] = [ck_d, m_copy["coord"][1]]
        ck_mmd_marks.append(m_copy)

    ck_res_marks = []
    for r in res_marks:
        raw_d = r.get("date") or (r.get("coord")[0] if r.get("coord") else "")
        ck_d = map_raw_date_to_ck_date(raw_d)
        r_copy = dict(r)
        r_copy["date"] = ck_d
        if "coord" in r_copy and len(r_copy["coord"]) == 2:
            r_copy["coord"] = [ck_d, r_copy["coord"][1]]
        ck_res_marks.append(r_copy)

    ck_fractal_marks = []
    if fractal_marks:
        for f in fractal_marks:
            raw_d = f.get("date") or (f.get("coord")[0] if f.get("coord") else "")
            ck_d = map_raw_date_to_ck_date(raw_d)
            f_copy = dict(f)
            f_copy["date"] = ck_d
            if "coord" in f_copy and len(f_copy["coord"]) == 2:
                f_copy["coord"] = [ck_d, f_copy["coord"][1]]
            ck_fractal_marks.append(f_copy)

    # 5. 副图技术指标重算（严格基于 cklines 数据序列）
    ck_c = np.array([ck.close for ck in cklines], dtype=float)
    ck_h = np.array([ck.high for ck in cklines], dtype=float)
    ck_l = np.array([ck.low for ck in cklines], dtype=float)

    dif_s, dea_s, hist_s = MACD(ck_c, 12, 26, 9)
    ck_macd_dif = [round(float(v), 3) if pd.notna(v) else 0.0 for v in dif_s]
    ck_macd_dea = [round(float(v), 3) if pd.notna(v) else 0.0 for v in dea_s]
    ck_macd_hist = [round(float(v), 3) for v in hist_s]

    r6 = RSI(ck_c, 6)
    r12 = RSI(ck_c, 12)
    r24 = RSI(ck_c, 24)
    ck_rsi = {
        "rsi6": [safe_float(v) for v in r6],
        "rsi12": [safe_float(v) for v in r12],
        "rsi24": [safe_float(v) for v in r24],
    }

    kv, dv, jv = KDJ(ck_c, ck_h, ck_l, 9, 3, 3)
    ck_kdj = {
        "k": [safe_float(v) for v in kv],
        "d": [safe_float(v) for v in dv],
        "j": [safe_float(v) for v in jv],
    }

    e12, e50 = EXPMA(ck_c, 12, 50)
    ck_expma = {
        "exp12": [safe_float(v) for v in e12],
        "exp50": [safe_float(v) for v in e50],
    }

    ck_df = pd.DataFrame({
        "close": ck_c,
        "open": [ck.open for ck in cklines],
        "high": ck_h,
        "low": ck_l,
        "volume": [v[1] for v in ck_volumes],
        "amount": [a[1] for a in ck_amounts],
    })
    ck_inflow = calculate_inflow_data(
        ck_df,
        clean_code=clean_code,
        is_backtracking=is_backtracking,
        is_daily=is_daily,
    )

    return {
        "dates": ck_dates,
        "candles": ck_candles,
        "volumes": ck_volumes,
        "amounts": ck_amounts,
        "high_bis": ck_high_bis,
        "high_zss": ck_high_zss,
        "mid_bis": ck_mid_bis,
        "mid_zss": ck_mid_zss,
        "low_bis": ck_low_bis,
        "low_zss": ck_low_zss,
        "mmd_marks": ck_mmd_marks,
        "fractal_marks": ck_fractal_marks,
        "res_marks": ck_res_marks,
        "macd": {
            "hist": ck_macd_hist,
            "dif": ck_macd_dif,
            "dea": ck_macd_dea,
            "marks": [],
        },
        "macd_marks": [],
        "macd_div_lines": [],
        "rsi": ck_rsi,
        "kdj": ck_kdj,
        "expma": ck_expma,
        "inflow": ck_inflow,
    }


logger = logging.getLogger("chanlun.resonance")

# 全量母数据集内存缓存池，供历史回溯与切片极速复用（彻底消除回溯时的网络请求）
# key: (clean_code, period) -> (cached_at: float, df: pd.DataFrame)
_RESONANCE_RAW_KLINE_CACHE: dict[tuple[str, str], tuple[float, pd.DataFrame]] = {}
# 回溯态分析结果全量缓存池，相同股票、周期与截断时点 100% 内存瞬时返回，免除重复缠论管道计算
# key: (clean_code, tuple(p_list), cutoff_str) -> result_dict
_RESONANCE_BACKTRACK_ANALYSIS_CACHE: dict[tuple[str, tuple[str, ...], str], dict[str, Any]] = {}
# 实时态分析结果智能缓存池，相同标的、周期、最新K线时点与收盘价时 0ms 瞬间返回
# key: (clean_code, tuple(p_list), latest_bar_time, latest_bar_close) -> (cached_at: float, result_dict: dict)
_RESONANCE_REALTIME_ANALYSIS_CACHE: dict[tuple[str, tuple[str, ...], str, float], tuple[float, dict[str, Any]]] = {}
_RESONANCE_CACHE_LOCK = threading.Lock()
BACKTRACK_CACHE_TTL = 3600.0  # 回溯态母数据缓存有效期（1小时），确保沉浸式复盘期间 100% 内存切片
REALTIME_CACHE_TTL = 20.0     # 实时态短期缓存（20秒）


def clear_resonance_kline_cache(code: str | None = None) -> None:
    """清理缠论多周期母数据缓存及回溯与实时结果缓存。"""
    with _RESONANCE_CACHE_LOCK:
        if code:
            clean = str(code).strip().upper().replace("SZ", "").replace("SH", "").replace("BJ", "")
            keys_to_del = [k for k in _RESONANCE_RAW_KLINE_CACHE if k[0] == clean]
            for k in keys_to_del:
                _RESONANCE_RAW_KLINE_CACHE.pop(k, None)
            ana_keys_to_del = [k for k in _RESONANCE_BACKTRACK_ANALYSIS_CACHE if k[0] == clean]
            for k in ana_keys_to_del:
                _RESONANCE_BACKTRACK_ANALYSIS_CACHE.pop(k, None)
            rt_keys_to_del = [k for k in _RESONANCE_REALTIME_ANALYSIS_CACHE if k[0] == clean]
            for k in rt_keys_to_del:
                _RESONANCE_REALTIME_ANALYSIS_CACHE.pop(k, None)
        else:
            _RESONANCE_RAW_KLINE_CACHE.clear()
            _RESONANCE_BACKTRACK_ANALYSIS_CACHE.clear()
            _RESONANCE_REALTIME_ANALYSIS_CACHE.clear()


# ==============================================================================
# 1. 周期规范与定义
# ==============================================================================

PERIOD_SPECS: dict[str, dict[str, Any]] = {
    "MONTH": {
        "aliases": ["MONTH", "MONTHLY", "月线", "月", "M"],
        "weight": 90,
        "market_cat": "MONTH",
        "chan_freq": "monthly",
        "label": "月线 (MONTH)",
        "short_name": "月线",
        "date_fmt": "%Y-%m",
    },
    "WEEK": {
        "aliases": ["WEEK", "WEEKLY", "周线", "周", "W"],
        "weight": 80,
        "market_cat": "WEEK",
        "chan_freq": "weekly",
        "label": "周线 (WEEK)",
        "short_name": "周线",
        "date_fmt": "%Y-%m-%d",
    },
    "DAY": {
        "aliases": ["DAY", "DAILY", "日线", "日", "D"],
        "weight": 70,
        "market_cat": "DAY",
        "chan_freq": "daily",
        "label": "日线 (DAY)",
        "short_name": "日线",
        "date_fmt": "%Y-%m-%d",
    },
    "120F": {
        "aliases": ["120F", "120M", "120MIN", "120", "120分钟", "2H"],
        "weight": 60,
        "market_cat": "120M",
        "chan_freq": "120min",
        "label": "120分钟 (120F)",
        "short_name": "120F",
        "date_fmt": "%m-%d %H:%M",
    },
    "60F": {
        "aliases": ["60F", "60M", "60MIN", "60", "60分钟", "1H"],
        "weight": 50,
        "market_cat": "60M",
        "chan_freq": "60min",
        "label": "60分钟 (60F)",
        "short_name": "60F",
        "date_fmt": "%m-%d %H:%M",
    },
    "30F": {
        "aliases": ["30F", "30M", "30MIN", "30", "30分钟"],
        "weight": 40,
        "market_cat": "30M",
        "chan_freq": "30min",
        "label": "30分钟 (30F)",
        "short_name": "30F",
        "date_fmt": "%m-%d %H:%M",
    },
    "15F": {
        "aliases": ["15F", "15M", "15MIN", "15", "15分钟"],
        "weight": 30,
        "market_cat": "15M",
        "chan_freq": "15min",
        "label": "15分钟 (15F)",
        "short_name": "15F",
        "date_fmt": "%m-%d %H:%M",
    },
    "5F": {
        "aliases": ["5F", "5M", "5MIN", "5", "5分钟"],
        "weight": 20,
        "market_cat": "5M",
        "chan_freq": "5min",
        "label": "5分钟 (5F)",
        "short_name": "5F",
        "date_fmt": "%m-%d %H:%M",
    },
    "1F": {
        "aliases": ["1F", "1M", "1MIN", "1", "1分钟"],
        "weight": 10,
        "market_cat": "1M",
        "chan_freq": "1min",
        "label": "1分钟 (1F)",
        "short_name": "1F",
        "date_fmt": "%m-%d %H:%M",
    },
}


def normalize_period(user_input: str) -> str:
    """将用户输入的任意周期名（如 '周线', '30M', '30F'）规范化为标准键名。"""
    raw = str(user_input).strip().upper()
    for key, spec in PERIOD_SPECS.items():
        if raw in [a.upper() for a in spec["aliases"]]:
            return key
    raise ValueError(
        f"未知周期 '{user_input}'，可选周期包括: "
        f"{', '.join(PERIOD_SPECS.keys())}"
    )


def parse_three_periods(periods_input: list[str] | str | None) -> list[str]:
    """解析并校验周期。支持单周期 (返回 [P, P, P]) 或三周期 (按大到小排序返回)。"""
    if periods_input is None:
        return ["DAY", "30F", "5F"]

    if isinstance(periods_input, str):
        parts = [p.strip() for p in periods_input.replace("，", ",").split(",") if p.strip()]
    else:
        parts = [str(p).strip() for p in periods_input if str(p).strip()]

    if len(parts) == 1:
        p = normalize_period(parts[0])
        return [p, p, p]
    elif len(parts) == 3:
        normalized = [normalize_period(p) for p in parts]
        if len(set(normalized)) != 3:
            raise ValueError(f"选择的 3 个周期不能重复: {normalized}")
        return sorted(normalized, key=lambda k: PERIOD_SPECS[k]["weight"], reverse=True)
    else:
        raise ValueError(f"周期数必须为 1（单周期）或 3（三级联），当前输入了 {len(parts)} 个: {periods_input}")


def _to_dt(val: Any) -> datetime:
    """安全极速将任意时间格式 (str, pd.Timestamp, datetime) 转为 Python datetime。"""
    if isinstance(val, datetime):
        return val
    if isinstance(val, pd.Timestamp):
        return val.to_pydatetime()
    s = str(val).strip()
    n = len(s)
    if n >= 10 and s[4] == '-' and s[7] == '-':
        try:
            year = int(s[0:4])
            month = int(s[5:7])
            day = int(s[8:10])
            hour = int(s[11:13]) if n >= 13 and s[10] in (' ', 'T') else 0
            minute = int(s[14:16]) if n >= 16 and s[13] == ':' else 0
            second = int(s[17:19]) if n >= 19 and s[16] == ':' else 0
            return datetime(year, month, day, hour, minute, second)
        except Exception:
            pass
    try:
        return pd.to_datetime(s).to_pydatetime()
    except Exception:
        return datetime.now()


def _fmt_dt(val: Any, is_intraday: bool = False) -> str:
    """安全快速格式化日期。"""
    if isinstance(val, str):
        s = val.strip()
        if len(s) >= 10 and s[4] == '-' and s[7] == '-':
            return s[:16] if is_intraday else s[:10]
    dt = _to_dt(val)
    return dt.strftime("%Y-%m-%d %H:%M") if is_intraday else dt.strftime("%Y-%m-%d")


# ==============================================================================
# 2. 三周期立体共振买卖点引擎
# ==============================================================================


@dataclass
class PeriodState:
    """某一周期在特定时间戳下的走势状态。"""

    period: str
    bar_index: int
    bar_date: str
    price: float
    current_bi_direction: str  # "up" / "down" / "none"
    current_bi_start_val: float = 0.0
    current_bi_end_val: float = 0.0
    recent_mmd_type: str = ""
    recent_mmd_date: str = ""
    recent_mmd_bars_ago: int = 999
    is_bullish: bool = False
    is_bearish: bool = False
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "period": self.period,
            "period_label": PERIOD_SPECS.get(self.period, {}).get("short_name", self.period),
            "bar_index": self.bar_index,
            "bar_date": self.bar_date,
            "price": round(self.price, 2),
            "bi_direction": self.current_bi_direction,
            "recent_mmd": self.recent_mmd_type.upper() if self.recent_mmd_type else "",
            "recent_mmd_bars_ago": self.recent_mmd_bars_ago,
            "is_bullish": self.is_bullish,
            "is_bearish": self.is_bearish,
            "detail": self.detail,
        }


@dataclass
class ResonanceSignal:
    """三周期共振买卖点事件。"""

    timestamp: str  # 小级别触发时间
    price: float  # 小级别触发价格
    direction: str  # "BUY" 或 "SELL"
    grade: str  # "AAA" / "AA" / "A"
    pattern_name: str  # 共振形态名称
    high_period: str
    mid_period: str
    low_period: str
    high_state: PeriodState
    mid_state: PeriodState
    low_state: PeriodState
    low_bar_idx: int  # 小级别图上的 K 线索引
    mid_bar_idx: int
    high_bar_idx: int
    description: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "price": round(self.price, 2),
            "direction": self.direction,
            "grade": self.grade,
            "pattern_name": self.pattern_name,
            "high_period": self.high_period,
            "mid_period": self.mid_period,
            "low_period": self.low_period,
            "low_bar_idx": self.low_bar_idx,
            "high_state": self.high_state.to_dict(),
            "mid_state": self.mid_state.to_dict(),
            "low_state": self.low_state.to_dict(),
            "description": self.description,
        }


# 各周期有效买卖点回溯窗口（根数），根据 K 线时间粒度动态配置
# 原则：覆盖约 1~2 周的交易时间
_PERIOD_MMD_WINDOW: dict[str, int] = {
    "MONTH": 3,    # 月线：3根 ≈ 一个季度
    "WEEK":  6,    # 周线：6根 ≈ 1.5个月
    "DAY":  20,    # 日线：20根 ≈ 1个月
    "120F": 40,   # 120分钟：40根 ≈ 1周
    "60F":  60,   # 60分钟：60根 ≈ 1.5周
    "30F": 80,    # 30分钟：80根 ≈ 2周
    "15F": 100,   # 15分钟：100根
    "5F":  150,   # 5分钟：150根 ≈ 3天
    "1F":  300,   # 1分钟：300根
}


class ThreePeriodResonanceEngine:
    """三周期缠论共振买卖点识别引擎。"""

    def __init__(
        self,
        high_period: str,
        mid_period: str,
        low_period: str,
        results: dict[str, ChanlunResult],
    ):
        self.p_high = high_period
        self.p_mid = mid_period
        self.p_low = low_period
        self.res_high = results[high_period]
        self.res_mid = results[mid_period]
        self.res_low = results[low_period]

        # 预先构建各周期时间戳索引与买卖点时间轴，加速状态检索到 O(log N)
        self._period_cache: dict[str, dict[str, Any]] = {}
        for p in (high_period, mid_period, low_period):
            res = results.get(p)
            if not res or not res.klines:
                self._period_cache[p] = {
                    "klines": [],
                    "k_dts": [],
                    "bis": [],
                    "bi_starts": [],
                    "mmd_entries": [],
                    "mmd_dts": [],
                    "is_intra": "min" in p.lower() or "f" in p.lower() or "m" in p.lower(),
                    "mmd_window": _PERIOD_MMD_WINDOW.get(p, 20),
                }
                continue

            k_dts = [_to_dt(k.date) for k in res.klines]
            bis = res.bis or []
            bi_starts = [bi.start.k.k_index for bi in bis]

            mmd_entries = []
            for mmd in (res.mmds or []):
                if mmd.bi:
                    mmd_entries.append((_to_dt(mmd.bi.end.k.date), mmd))
            mmd_entries.sort(key=lambda x: x[0])
            mmd_dts = [x[0] for x in mmd_entries]

            self._period_cache[p] = {
                "klines": res.klines,
                "k_dts": k_dts,
                "bis": bis,
                "bi_starts": bi_starts,
                "mmd_entries": mmd_entries,
                "mmd_dts": mmd_dts,
                "is_intra": "min" in p.lower() or "f" in p.lower() or "m" in p.lower(),
                "mmd_window": _PERIOD_MMD_WINDOW.get(p, 20),
            }

    def get_period_state_at(self, period: str, target_dt: Any) -> PeriodState:
        """评估指定周期在某一时间戳 target_dt 的多空状态。"""
        target_obj = _to_dt(target_dt)
        cache = self._period_cache.get(period)
        if not cache or not cache["klines"]:
            return PeriodState(period, -1, "", 0.0, "none")

        klines = cache["klines"]
        k_dts = cache["k_dts"]

        # 二分查找 target_obj 对应的最大 bar_idx (k_dts[i] <= target_obj)
        pos = bisect.bisect_right(k_dts, target_obj) - 1
        if pos < 0:
            bar_idx = 0
        else:
            bar_idx = min(pos, len(klines) - 1)

        cur_k = klines[bar_idx]
        is_intra = cache["is_intra"]
        cur_date_str = _fmt_dt(cur_k.date, is_intraday=is_intra)

        # 二分查找当前活跃笔 (bi.start.k.k_index <= bar_idx)
        active_bi = None
        bi_starts = cache["bi_starts"]
        if bi_starts:
            bi_pos = bisect.bisect_right(bi_starts, bar_idx) - 1
            if bi_pos >= 0:
                active_bi = cache["bis"][bi_pos]

        bi_dir = active_bi.direction.value if active_bi else "none"
        bi_s_val = active_bi.start.val if active_bi else 0.0
        bi_e_val = active_bi.end.val if active_bi else 0.0

        # 二分查找 target_obj 之前的最近买卖点
        mmd_dts = cache["mmd_dts"]
        last_mmd = None
        if mmd_dts:
            mmd_pos = bisect.bisect_right(mmd_dts, target_obj) - 1
            if mmd_pos >= 0:
                last_mmd = cache["mmd_entries"][mmd_pos][1]

        mmd_type = last_mmd.mmd_type.value if last_mmd else ""
        mmd_dt = (
            _fmt_dt(last_mmd.bi.end.k.date, is_intraday=is_intra)
            if last_mmd and last_mmd.bi
            else ""
        )
        bars_ago = (
            (bar_idx - last_mmd.bi.end.k.k_index)
            if last_mmd and last_mmd.bi
            else 999
        )

        # 动态有效买卖点回溯窗口（根据周期K线粒度自适应）
        mmd_window: int = cache.get("mmd_window", 20)

        is_bullish = False
        is_bearish = False
        detail_msg = []

        # 判断逻辑（优先级从高到低）：
        # 1. 近期有买点信号（在有效窗口内）→ 多头
        # 2. 近期有卖点信号（在有效窗口内）→ 空头
        # 3. 当前活跃笔方向（兜底）→ 仅作辅助参考
        #
        # 注意：买卖点信号优先于笔方向判断，
        # 因为笔方向只反映最近一笔走势，可能在大趋势下的回调中显示反向笔
        if mmd_type in ("1buy", "2buy", "3buy") and bars_ago <= mmd_window:
            is_bullish = True
            detail_msg.append(f"{mmd_type.upper()}确立({bars_ago}根前)")

        if mmd_type in ("1sell", "2sell", "3sell") and bars_ago <= mmd_window:
            is_bearish = True
            detail_msg.append(f"{mmd_type.upper()}确立({bars_ago}根前)")

        # 买卖点过期或无买卖点时，用笔方向兜底
        if not is_bullish and not is_bearish:
            if bi_dir == "up":
                is_bullish = True
                detail_msg.append("向上笔运行中（无近期信号）")
            elif bi_dir == "down":
                is_bearish = True
                detail_msg.append("向下笔运行中（无近期信号）")

        # 冲突时：买卖点信号优先于笔方向
        if is_bullish and is_bearish:
            # 优先取更近的买卖点；若距离相同则笔方向决定
            if mmd_type in ("1buy", "2buy", "3buy"):
                is_bearish = False
            elif mmd_type in ("1sell", "2sell", "3sell"):
                is_bullish = False
            elif bi_dir == "up":
                is_bearish = False
            else:
                is_bullish = False

        return PeriodState(
            period=period,
            bar_index=bar_idx,
            bar_date=cur_date_str,
            price=cur_k.close,
            current_bi_direction=bi_dir,
            current_bi_start_val=bi_s_val,
            current_bi_end_val=bi_e_val,
            recent_mmd_type=mmd_type,
            recent_mmd_date=mmd_dt,
            recent_mmd_bars_ago=bars_ago,
            is_bullish=is_bullish,
            is_bearish=is_bearish,
            detail="; ".join(detail_msg) if detail_msg else "无明显单边倾向",
        )

    def scan_resonances(self) -> list[ResonanceSignal]:
        """扫描在小级别上触发的三周期共振买卖点，并去重。

        去重规则：同一 K 线位置（bar_idx）同方向（BUY/SELL）只保留等级最高的信号。
        等级顺序：AAA > AA > A
        """
        raw_resonances: list[ResonanceSignal] = []
        low_res = self.res_low

        trigger_events = []
        for mmd in low_res.mmds:
            if not mmd.bi:
                continue
            trigger_events.append({
                "type": mmd.mmd_type.value,
                "dt": mmd.bi.end.k.date,
                "price": mmd.bi.end.val,
                "bar_idx": mmd.bi.end.k.k_index,
                "is_buy": "buy" in mmd.mmd_type.value,
                "msg": mmd.msg,
            })

        trigger_events = sorted(trigger_events, key=lambda x: _to_dt(x["dt"]))

        is_intra = (
            "min" in self.p_low.lower()
            or "f" in self.p_low.lower()
            or "m" in self.p_low.lower()
        )

        for ev in trigger_events:
            target_dt = ev["dt"]
            is_buy = ev["is_buy"]

            low_state = self.get_period_state_at(self.p_low, target_dt)
            mid_state = self.get_period_state_at(self.p_mid, target_dt)
            high_state = self.get_period_state_at(self.p_high, target_dt)

            if is_buy:
                if mid_state.is_bullish and high_state.is_bullish:
                    grade, name = self._classify_resonance(
                        "BUY", high_state, mid_state, ev["type"]
                    )
                    desc = (
                        f"【{name}】\n"
                        f"- {PERIOD_SPECS[self.p_high]['short_name']}(大): {high_state.detail}\n"
                        f"- {PERIOD_SPECS[self.p_mid]['short_name']}(中): {mid_state.detail}\n"
                        f"- {PERIOD_SPECS[self.p_low]['short_name']}(小): 触发 {ev['type'].upper()} ({ev['price']:.2f})"
                    )
                    raw_resonances.append(
                        ResonanceSignal(
                            timestamp=_fmt_dt(target_dt, is_intraday=is_intra),
                            price=ev["price"],
                            direction="BUY",
                            grade=grade,
                            pattern_name=name,
                            high_period=self.p_high,
                            mid_period=self.p_mid,
                            low_period=self.p_low,
                            high_state=high_state,
                            mid_state=mid_state,
                            low_state=low_state,
                            low_bar_idx=ev["bar_idx"],
                            mid_bar_idx=mid_state.bar_index,
                            high_bar_idx=high_state.bar_index,
                            description=desc,
                        )
                    )
            else:
                if mid_state.is_bearish and high_state.is_bearish:
                    grade, name = self._classify_resonance(
                        "SELL", high_state, mid_state, ev["type"]
                    )
                    desc = (
                        f"【{name}】\n"
                        f"- {PERIOD_SPECS[self.p_high]['short_name']}(大): {high_state.detail}\n"
                        f"- {PERIOD_SPECS[self.p_mid]['short_name']}(中): {mid_state.detail}\n"
                        f"- {PERIOD_SPECS[self.p_low]['short_name']}(小): 触发 {ev['type'].upper()} ({ev['price']:.2f})"
                    )
                    raw_resonances.append(
                        ResonanceSignal(
                            timestamp=_fmt_dt(target_dt, is_intraday=is_intra),
                            price=ev["price"],
                            direction="SELL",
                            grade=grade,
                            pattern_name=name,
                            high_period=self.p_high,
                            mid_period=self.p_mid,
                            low_period=self.p_low,
                            high_state=high_state,
                            mid_state=mid_state,
                            low_state=low_state,
                            low_bar_idx=ev["bar_idx"],
                            mid_bar_idx=mid_state.bar_index,
                            high_bar_idx=high_state.bar_index,
                            description=desc,
                        )
                    )

        # 去重：同 bar_idx + 同方向只保留等级最高的信号
        return _dedup_resonances(raw_resonances)

    def _classify_resonance(
        self,
        direction: str,
        high: PeriodState,
        mid: PeriodState,
        low_mmd: str,
    ) -> tuple[str, str]:
        p_names = f"{PERIOD_SPECS[self.p_high]['short_name']}·{PERIOD_SPECS[self.p_mid]['short_name']}·{PERIOD_SPECS[self.p_low]['short_name']}"

        if direction == "BUY":
            h_type = high.recent_mmd_type
            m_type = mid.recent_mmd_type
            if "1buy" in h_type and "1buy" in m_type and "1buy" in low_mmd:
                return "AAA", f"★ [{p_names}] 区间套·极值底背驰全共振"
            if "2buy" in h_type and "2buy" in m_type and "2buy" in low_mmd:
                return "AAA", f"★ [{p_names}] 全二买稳健主升共振"
            if "3buy" in h_type and "3buy" in m_type and "3buy" in low_mmd:
                return "AAA", f"★ [{p_names}] 全三买主升浪爆发共振"

            # 核心区间套模型：大/次级别处于底区，次级别/小级别2买二次确认 (稳健起涨)
            if "1buy" in h_type and "2buy" in low_mmd:
                return "AAA", f"★ [{p_names}] 区间套·次级别稳健二买确认"
            if "1buy" in m_type and "2buy" in low_mmd:
                return "AAA", f"★ [{p_names}] 区间套·次一买小二买共振"
            if ("1buy" in h_type or "1buy" in m_type) and "1buy" in low_mmd:
                return "AAA", f"★ [{p_names}] 区间套·极值底背驰共振点"

            if "3buy" in low_mmd:
                return "AA", f"★ [{p_names}] 三类买点中枢突破起爆"
            if "2buy" in low_mmd:
                return "AA", f"★ [{p_names}] 次级别稳健二买起跑"
            if "1buy" in low_mmd:
                return "AA", f"★ [{p_names}] 区间套极值底背驰拐点"

            return "A", f"★ [{p_names}] 多周期多头趋势共振买点"
        else:
            h_type = high.recent_mmd_type
            m_type = mid.recent_mmd_type
            if "1sell" in h_type and "1sell" in m_type and "1sell" in low_mmd:
                return "AAA", f"▼ [{p_names}] 区间套·极高顶背驰全共振"
            if "2sell" in h_type and "2sell" in m_type and "2sell" in low_mmd:
                return "AAA", f"▼ [{p_names}] 全二卖破位共振"
            if "3sell" in h_type and "3sell" in m_type and "3sell" in low_mmd:
                return "AAA", f"▼ [{p_names}] 全三卖破位下杀共振"

            # 核心区间套卖点：大级别1卖出顶，次级别/小级别2卖破位确认
            if "1sell" in h_type and "2sell" in low_mmd:
                return "AAA", f"▼ [{p_names}] 区间套·次级别清仓二卖破位"
            if "1sell" in m_type and "2sell" in low_mmd:
                return "AAA", f"▼ [{p_names}] 区间套·次一卖小二卖破位点"
            if ("1sell" in h_type or "1sell" in m_type) and "1sell" in low_mmd:
                return "AAA", f"▼ [{p_names}] 区间套·极高顶背驰共振点"

            if "1sell" in low_mmd:
                return "AA", f"▼ [{p_names}] 区间套极高顶背驰拐点"
            if "2sell" in low_mmd:
                return "AA", f"▼ [{p_names}] 次级别清仓二卖反弹不过"
            if "3sell" in low_mmd:
                return "AA", f"▼ [{p_names}] 三类卖点破位下杀共振"

            return "A", f"▼ [{p_names}] 多周期空头破位共振卖点"


# ==============================================================================
# 3. 跨级别笔与中枢向基准周期的对齐映射
# ==============================================================================


def _dedup_resonances(resonances: list[ResonanceSignal]) -> list[ResonanceSignal]:
    """去重共振信号：同 bar_idx + 同方向只保留等级最高的信号。

    等级顺序：AAA > AA > A
    """
    _grade_order = {"AAA": 3, "AA": 2, "A": 1}
    best: dict[tuple[int, str], ResonanceSignal] = {}
    for r in resonances:
        key = (r.low_bar_idx, r.direction)
        existing = best.get(key)
        if existing is None or _grade_order.get(r.grade, 0) > _grade_order.get(existing.grade, 0):
            best[key] = r
    return sorted(best.values(), key=lambda r: r.low_bar_idx)


def map_pivot_to_base(
    dt_val: Any,
    val: float,
    is_high: bool,
    period_key: str,
    base_df: pd.DataFrame,
    base_dts: pd.Series,
    base_dts_list: list[datetime] | None = None,
    fx_obj: Any = None,
) -> int:
    """将较高级别的笔分型端点精确映射到基准小周期的某根 K 线索引。
    
    对于同波段或包含处理合并后的极端高低点，智能定位到在基准周期上实际触及该极值价格的 K 线，
    使大级别、次级别、小级别的顶点或底点在视觉与数学坐标上精准落在同一根 K 线周期上。
    """
    p_dt = _to_dt(dt_val)
    n_bars = len(base_df)
    if n_bars == 0:
        return 0
    if p_dt < base_dts.iloc[0]:
        return -1
    if p_dt > base_dts.iloc[-1]:
        return n_bars - 1

    # 1. 如果提供了分型对象且其合并 K 线包含多根原始 K 线，优先定位到实际达到极值价格的原始 K 线时间
    anchor_dt = p_dt
    if fx_obj is not None and hasattr(fx_obj, "k") and hasattr(fx_obj.k, "klines") and fx_obj.k.klines:
        for raw_k in fx_obj.k.klines:
            raw_target = raw_k.high if is_high else raw_k.low
            if abs(raw_target - val) < 1e-4:
                anchor_dt = _to_dt(raw_k.date)
                break

    # 2. 根据周期类型确定基准周期的候选搜索时间窗口
    p_upper = period_key.upper()
    if p_upper in ("MONTH", "M"):
        mask = (base_dts.dt.year == anchor_dt.year) & (base_dts.dt.month == anchor_dt.month)
    elif p_upper in ("WEEK", "W"):
        w_start = (anchor_dt - pd.Timedelta(days=6)).date()
        w_end = (anchor_dt + pd.Timedelta(days=1)).date()
        mask = (base_dts.dt.date >= w_start) & (base_dts.dt.date <= w_end)
    elif p_upper in ("DAY", "D"):
        mask = base_dts.dt.date == anchor_dt.date()
    else:
        # 分钟周期 (如 120F, 60F, 30F, 15F, 5F, 1F)
        delta_m = 30
        if "120" in p_upper:
            delta_m = 120
        elif "60" in p_upper:
            delta_m = 60
        elif "30" in p_upper:
            delta_m = 30
        elif "15" in p_upper:
            delta_m = 15
        elif "5" in p_upper:
            delta_m = 5
        elif "1" in p_upper:
            delta_m = 1

        t_min = anchor_dt - pd.Timedelta(minutes=delta_m)
        t_max = anchor_dt + pd.Timedelta(seconds=59)
        mask = (base_dts >= t_min) & (base_dts <= t_max)

    if mask is not None:
        idxs = np.where(mask)[0]
        if len(idxs) > 0:
            target_col = "high" if is_high else "low"
            sub_vals = base_df[target_col].iloc[idxs].values
            diffs = np.abs(sub_vals - val)
            # 优先精确匹配极值价格（浮点容差 1e-3）
            if np.min(diffs) < 1e-3:
                match_positions = np.where(diffs < 1e-3)[0]
                return int(idxs[match_positions[0]])
            elif is_high:
                return int(idxs[np.argmax(sub_vals)])
            else:
                return int(idxs[np.argmin(sub_vals)])

    # 高速二分查找最邻近索引 (O(log N)) 作为保底
    if base_dts_list is not None and len(base_dts_list) == n_bars:
        pos = bisect.bisect_left(base_dts_list, anchor_dt)
        if pos == 0:
            return 0
        if pos >= n_bars:
            return n_bars - 1
        diff1 = abs((base_dts_list[pos - 1] - anchor_dt).total_seconds())
        diff2 = abs((base_dts_list[pos] - anchor_dt).total_seconds())
        return pos - 1 if diff1 <= diff2 else pos

    diffs = np.abs((base_dts - anchor_dt).dt.total_seconds().values)
    return int(np.argmin(diffs))




# ==============================================================================
# 4. 核心主函数：多周期立体分析与数据结构组织
# ==============================================================================


def analyze_multi_period_resonance(
    code: str = "000001",
    periods: list[str] | str | None = None,
    count: int = 300,
    cutoff_date: str | None = None,
    force_refresh: bool = False,
    screener_mode: bool = False,
) -> dict[str, Any]:
    """执行三周期缠论立体共振分析，支持历史回溯与实时计算。

    Args:
        code: 证券代码（如 000001, 600519）
        periods: 3 个周期组合（如 ["DAY", "30F", "5F"] 或 "DAY,30F,5F"，默认 "DAY,30F,5F"）
        count: 基准最小周期 K 线根数（默认 300）
        cutoff_date: 回溯截止日期时间（若提供则只计算 <= 该时间的数据，模拟历史当下）
        force_refresh: 是否强制穿透缓存获取最新实时行情
        screener_mode: 选股极速模式（跳过图表与技术指标组装，专注于中枢与买卖点判定）
    """
    clean_code = (
        str(code)
        .strip()
        .upper()
        .replace("SZ", "")
        .replace("SH", "")
        .replace("BJ", "")
    )
    if not clean_code:
        clean_code = "000001"

    p_list = parse_three_periods(periods)
    high_p, mid_p, low_p = p_list[0], p_list[1], p_list[2]
    stock_name = get_stock_name(clean_code) or "标的资产"

    is_backtracking = bool(cutoff_date and str(cutoff_date).strip())
    cutoff_str = str(cutoff_date).strip() if is_backtracking else ""
    if is_backtracking:
        parsed_dt = _to_dt(cutoff_str)
        # 若只提供了日期部分 (例如 '2026-09-11' 或长度 <= 10，不包含具体时分秒)，
        # 表示回溯至该交易日全天（收盘态）。需将截断时点扩展至当天 23:59:59，
        # 避免分钟级子周期 (30F, 5F, 1F 等) 因 00:00:00 早于 09:30 开盘时间而被全部错误过滤。
        if len(cutoff_str) <= 10 or (" " not in cutoff_str and "T" not in cutoff_str):
            cutoff_dt = parsed_dt.replace(hour=23, minute=59, second=59)
        else:
            cutoff_dt = parsed_dt
    else:
        cutoff_dt = None
    now_ts = time.time()

    # 历史回溯极速缓存：相同标的、周期组合、截断点 100% 内存瞬时返回，彻底避免重复向行情服务器与缠论管道计算
    if is_backtracking:
        backtrack_cache_key = (clean_code, tuple(p_list), cutoff_str)
        with _RESONANCE_CACHE_LOCK:
            if backtrack_cache_key in _RESONANCE_BACKTRACK_ANALYSIS_CACHE:
                logger.debug(
                    "回溯直接命中内存分析结果缓存: code=%s periods=%s cutoff=%s",
                    clean_code, p_list, cutoff_str
                )
                return _RESONANCE_BACKTRACK_ANALYSIS_CACHE[backtrack_cache_key]

    # 4.1 请求 K 线基准根数（严格对齐周期特性深度规划）:
    # 月线 (MONTH): 最大安全拉取 120 根（覆盖 10 年，既完全满足缠论大中枢构建，又彻底避开 2002 年远古减法负价区）；
    # 周线 (WEEK): 最大安全拉取 250 根（覆盖约 5 年）；
    # 日线 : 维持 500~800 根；
    # 30M 5F 1F 分钟线 : 维持 3000 根
    if screener_mode:
        req_counts = {
            high_p: 120 if high_p == "MONTH" else (250 if high_p == "WEEK" else 500),
            mid_p: 250 if mid_p == "WEEK" else 500,
            low_p: 500,
        }
    else:
        req_counts = {
            high_p: 120 if high_p == "MONTH" else (250 if high_p == "WEEK" else 800),
            mid_p: 250 if mid_p == "WEEK" else 800,
            low_p: 800,
        }
    # 30M / 5F / 1F 分钟线：统一维持 3000 根
    for p in p_list:
        if p in ("30F", "30M", "15F", "15M", "5F", "5M", "1F", "1M"):
            req_counts[p] = 3000

    # 回溯模式下强制禁用 force_refresh，彻底阻断向行情服务器重复更新 K 线
    effective_force_refresh = False if is_backtracking else force_refresh

    is_single_period = (high_p == mid_p == low_p)

    # 4.2 规划多周期加载（借鉴 chanlun-pro 低到高合成与并发拉取策略）：
    # 判断 mid_p / high_p 是否可由 low_p 重采样合成，避免冗余远程网络 I/O
    resample_plan: dict[str, str] = {}
    needed_fetch_periods: list[str] = [low_p]

    if not is_single_period:
        for p in (mid_p, high_p):
            if low_p in ("1F", "1M") and p in ("30F", "30M", "60F", "60M", "120F", "120M", "DAY"):
                if p not in needed_fetch_periods:
                    needed_fetch_periods.append(p)
            elif can_resample_from(low_p, p):
                resample_plan[p] = low_p
            elif p not in needed_fetch_periods:
                needed_fetch_periods.append(p)

    def _fetch_one_period(p_name: str) -> tuple[str, pd.DataFrame]:
        spec_item = PERIOD_SPECS[p_name]
        needed_cnt = req_counts[p_name]
        if p_name == "MONTH":
            target_cnt = 120  # 最大安全拉取 120 根
        elif p_name == "WEEK":
            target_cnt = 250  # 最大安全拉取 250 根
        elif p_name in ("DAY", "120M", "60M"):
            target_cnt = 500 if screener_mode else 800  # 日线维持 500~800 根
        elif p_name in ("30F", "30M", "15F", "15M", "5F", "5M", "1F", "1M"):
            target_cnt = 3000  # 30M 5F 1F 分钟线维持 3000 根
        else:
            target_cnt = max(needed_cnt, 800)

        # 1. 检查内存缓存
        if not effective_force_refresh:
            with _RESONANCE_CACHE_LOCK:
                if (clean_code, p_name) in _RESONANCE_RAW_KLINE_CACHE:
                    c_time, c_df = _RESONANCE_RAW_KLINE_CACHE[(clean_code, p_name)]
                    if c_df is not None and not c_df.empty:
                        if is_backtracking or (now_ts - c_time < REALTIME_CACHE_TTL):
                            return p_name, c_df

        # 2. 检查本地磁盘持久化缓存（借鉴 chanlun-pro FileCacheDB）
        disk_cache = get_global_kline_disk_cache()
        cached_df = disk_cache.read_cached(clean_code, p_name)
        if cached_df is not None and not cached_df.empty and len(cached_df) >= target_cnt and not effective_force_refresh:
            # 严格检查磁盘缓存是否已到达最新理论收盘状态
            if disk_cache.is_up_to_date(cached_df, p_name):
                with _RESONANCE_CACHE_LOCK:
                    _RESONANCE_RAW_KLINE_CACHE[(clean_code, p_name)] = (now_ts, cached_df)
                return p_name, cached_df

            try:
                # 缓存存在但非最新（如盘中需要实时更新，或盘后首次访问时缓存仍停留在旧交易日）
                # 估算落后自然日天数，动态分配足够安全的增量条数，彻底防止分钟线断层
                dt_col = "date" if "date" in cached_df.columns else "datetime"
                last_dt_str = str(cached_df[dt_col].iloc[-1]).strip() if dt_col in cached_df.columns else ""
                lag_days = 1
                try:
                    last_d = datetime.date.fromisoformat(last_dt_str.split()[0].split("T")[0])
                    cur_d = datetime.datetime.now(_SH_TZ).date()
                    lag_days = max(1, (cur_d - last_d).days)
                except Exception:
                    pass

                p_upper = p_name.upper()
                if "1F" in p_upper:
                    delta_cnt = lag_days * 240 + 60
                elif "5F" in p_upper:
                    delta_cnt = lag_days * 48 + 48
                elif "15F" in p_upper:
                    delta_cnt = lag_days * 16 + 20
                elif "30F" in p_upper:
                    delta_cnt = lag_days * 8 + 16
                elif "60F" in p_upper:
                    delta_cnt = lag_days * 4 + 8
                else:
                    # 日线、周线、月线
                    delta_cnt = lag_days + 10

                delta_cnt = max(delta_cnt, 80)
                delta_cnt = min(delta_cnt, target_cnt)

                delta_df = fetch_security_kline(
                    clean_code,
                    category=spec_item["market_cat"],
                    count=delta_cnt,
                    force_refresh=True,
                )
                if delta_df is not None and not delta_df.empty:
                    merged = disk_cache.merge_and_update(clean_code, p_name, cached_df, delta_df)
                    with _RESONANCE_CACHE_LOCK:
                        _RESONANCE_RAW_KLINE_CACHE[(clean_code, p_name)] = (now_ts, merged)
                    return p_name, merged
                return p_name, cached_df
            except Exception as e:
                logger.debug("增量同步更新异常 %s %s: %s", clean_code, p_name, e)
                return p_name, cached_df

        # 3. 磁盘无缓存或数量不足，或 force_refresh：向 TDX 全量拉取
        df_fetched = fetch_security_kline(
            clean_code,
            category=spec_item["market_cat"],
            count=target_cnt,
            force_refresh=effective_force_refresh,
        )
        if df_fetched is None or df_fetched.empty:
            df_fetched = pd.DataFrame(columns=["datetime", "open", "high", "low", "close", "volume", "amount"])
        else:
            disk_cache.write_cached(clean_code, p_name, df_fetched)
            with _RESONANCE_CACHE_LOCK:
                _RESONANCE_RAW_KLINE_CACHE[(clean_code, p_name)] = (now_ts, df_fetched)

        return p_name, df_fetched

    # 4.3 并发拉取独立周期数据
    raw_dfs: dict[str, pd.DataFrame] = {}
    if len(needed_fetch_periods) == 1:
        p_name, df_res = _fetch_one_period(needed_fetch_periods[0])
        raw_dfs[p_name] = df_res
    else:
        with ThreadPoolExecutor(max_workers=min(len(needed_fetch_periods), 4)) as pool:
            futs = [pool.submit(_fetch_one_period, p_name) for p_name in needed_fetch_periods]
            for f in futs:
                p_name, df_res = f.result()
                raw_dfs[p_name] = df_res

    # 4.4 针对匹配周期执行毫秒级重采样合成（免去重复远程请求）
    for p_target, p_src in resample_plan.items():
        src_df = raw_dfs.get(p_src)
        spec_target = PERIOD_SPECS[p_target]
        if src_df is not None and not src_df.empty:
            raw_dfs[p_target] = convert_kline_frequency(src_df, spec_target["market_cat"])
        else:
            raw_dfs[p_target] = pd.DataFrame(columns=["datetime", "open", "high", "low", "close", "volume", "amount"])

    # 获取完整可用时间跨度（由母数据全量序列提供，供前端滑块稳定自由导航）
    base_full_df = raw_dfs[low_p]
    available_dates = (
        base_full_df["datetime"].astype(str).tolist()
        if not base_full_df.empty
        else []
    )
    min_date = available_dates[0] if available_dates else ""
    max_date = available_dates[-1] if available_dates else ""

    # 实时态瞬时分析结果缓存命中检查：如果标的最新一根 K 线的时点与收盘价未改变，直接复用完整分析结果
    if not is_backtracking and not base_full_df.empty and not effective_force_refresh:
        latest_dt_check = str(base_full_df["datetime"].iloc[-1])
        latest_close_check = round(float(base_full_df["close"].iloc[-1]), 2)
        rt_cache_key = (clean_code, tuple(p_list), latest_dt_check, latest_close_check)
        with _RESONANCE_CACHE_LOCK:
            if rt_cache_key in _RESONANCE_REALTIME_ANALYSIS_CACHE:
                cached_at, cached_res = _RESONANCE_REALTIME_ANALYSIS_CACHE[rt_cache_key]
                if now_ts - cached_at < REALTIME_CACHE_TTL:
                    logger.debug("实时行情未变，直接命中分析结果缓存: %s", rt_cache_key)
                    return cached_res

    # 如果指定了 cutoff_date，进行历史无未来切除回溯
    dfs: dict[str, pd.DataFrame] = {}
    if is_backtracking and cutoff_dt is not None and not base_full_df.empty:
        for p in p_list:
            df_cur = raw_dfs[p]
            if not df_cur.empty and "datetime" in df_cur.columns:
                # 严格切除 > cutoff_dt 的未来数据，保证无未来函数
                dts = pd.to_datetime(df_cur["datetime"].astype(str))
                mask = dts <= cutoff_dt
                sub_df = df_cur[mask].copy().reset_index(drop=True)
                # 至少保留 15 根 K 线供缠论计算，避免历史过早导致全空
                if len(sub_df) < 15:
                    sub_df = df_cur.iloc[:min(len(df_cur), 30)].copy().reset_index(drop=True)
                dfs[p] = sub_df
            else:
                dfs[p] = df_cur.copy()
    else:
        dfs = {k: v.copy() for k, v in raw_dfs.items()}

    # 运行缠论分析管道
    results: dict[str, ChanlunResult] = {}
    if is_single_period:
        ana_res = ChanlunAnalyser(code=clean_code, frequency=PERIOD_SPECS[low_p]["chan_freq"]).process_klines(dfs[low_p])
        for p in p_list:
            results[p] = ana_res
    else:
        with ThreadPoolExecutor(max_workers=3) as pool:
            ana_futs = {
                p: pool.submit(
                    ChanlunAnalyser(code=clean_code, frequency=PERIOD_SPECS[p]["chan_freq"]).process_klines,
                    dfs[p]
                )
                for p in p_list
            }
            for p, f in ana_futs.items():
                results[p] = f.result()

    # 运行共振引擎（单周期无需共振识别）
    engine = ThreePeriodResonanceEngine(high_p, mid_p, low_p, results)
    resonances = [] if is_single_period else engine.scan_resonances()

    # 获取当前最新时点的多空态势
    base_df = dfs[low_p]
    latest_dt = base_df["datetime"].iloc[-1] if not base_df.empty else ""
    current_high_state = engine.get_period_state_at(high_p, latest_dt)
    current_mid_state = engine.get_period_state_at(mid_p, latest_dt)
    current_low_state = engine.get_period_state_at(low_p, latest_dt)

    # 组装基准 K 线坐标轴与图表序列
    n_base = len(base_df)
    dates = base_df["datetime"].astype(str).tolist() if not base_df.empty else []
    candles = (
        base_df[["open", "close", "low", "high"]].values.tolist()
        if not base_df.empty
        else []
    )
    if not base_df.empty:
        vols = base_df["volume"].values
        closes_arr = base_df["close"].values
        opens_arr = base_df["open"].values
        volumes = [
            [i, float(vols[i]), 1 if closes_arr[i] >= opens_arr[i] else -1]
            for i in range(n_base)
        ]
        amts = base_df["amount"].values if "amount" in base_df.columns else None
        amounts = [
            [
                i,
                float(amts[i]) if (amts is not None and pd.notna(amts[i]) and float(amts[i]) > 0) else float(vols[i] * closes_arr[i]),
                1 if closes_arr[i] >= opens_arr[i] else -1,
            ]
            for i in range(n_base)
        ]
        base_dts = pd.to_datetime(base_df["datetime"].astype(str))
        base_dts_list = [t.to_pydatetime() for t in base_dts]
    else:
        volumes = []
        amounts = []
        base_dts = pd.Series(dtype="datetime64[ns]")
        base_dts_list = []

    # 1. 映射大级别笔与中枢 (单周期模式下跳过，稍后由单周期线段填充)
    high_bis = []
    high_zss = []
    if not is_single_period:
        high_res = results[high_p]
        prev_high_end_coord = None
        prev_high_end_idx = None
        for bi in high_res.bis:
            s_is_high = bi.start.fx_type == FXType.DING
            e_is_high = bi.end.fx_type == FXType.DING
            s_i = map_pivot_to_base(bi.start.k.date, bi.start.val, s_is_high, high_p, base_df, base_dts, base_dts_list, fx_obj=bi.start)
            e_i = map_pivot_to_base(bi.end.k.date, bi.end.val, e_is_high, high_p, base_df, base_dts, base_dts_list, fx_obj=bi.end)
            if s_i < 0 and e_i < 0:
                continue
            s_clamp = max(0, min(n_base - 1, s_i))
            e_clamp = max(0, min(n_base - 1, e_i))
            start_coord = prev_high_end_coord if prev_high_end_coord is not None else [dates[s_clamp], bi.start.val]
            start_idx = prev_high_end_idx if prev_high_end_idx is not None else s_clamp
            if e_clamp <= start_idx and start_idx < n_base - 1:
                e_clamp = start_idx + 1
            end_coord = [dates[e_clamp], bi.end.val]
            high_bis.append({
                "start": start_coord,
                "end": end_coord,
                "start_idx": start_idx,
                "end_idx": e_clamp,
                "direction": bi.direction.value,
            })
            prev_high_end_coord = end_coord
            prev_high_end_idx = e_clamp

        for zs in results[high_p].zss:
            if not zs.start or not zs.end:
                continue
            s_i = map_pivot_to_base(zs.start.k.date, zs.zd, False, high_p, base_df, base_dts, base_dts_list)
            e_i = map_pivot_to_base(zs.end.k.date, zs.zg, True, high_p, base_df, base_dts, base_dts_list)
            if e_i < 0 or s_i >= n_base:
                continue
            s_clamp = max(0, min(n_base - 1, s_i))
            e_clamp = max(0, min(n_base - 1, e_i))
            high_zss.append({
                "start_date": dates[s_clamp],
                "end_date": dates[e_clamp],
                "start_idx": s_clamp,
                "end_idx": e_clamp,
                "zg": round(zs.zg, 2),
                "zd": round(zs.zd, 2),
                "gg": round(zs.gg, 2),
                "dd": round(zs.dd, 2),
            })

    # 2. 映射中级别笔与中枢
    mid_bis = []
    mid_zss = []
    if not is_single_period:
        mid_res = results[mid_p]
        prev_mid_end_coord = None
        prev_mid_end_idx = None
        for bi in mid_res.bis:
            s_is_high = bi.start.fx_type == FXType.DING
            e_is_high = bi.end.fx_type == FXType.DING
            s_i = map_pivot_to_base(bi.start.k.date, bi.start.val, s_is_high, mid_p, base_df, base_dts, base_dts_list, fx_obj=bi.start)
            e_i = map_pivot_to_base(bi.end.k.date, bi.end.val, e_is_high, mid_p, base_df, base_dts, base_dts_list, fx_obj=bi.end)
            if s_i < 0 and e_i < 0:
                continue
            s_clamp = max(0, min(n_base - 1, s_i))
            e_clamp = max(0, min(n_base - 1, e_i))
            start_coord = prev_mid_end_coord if prev_mid_end_coord is not None else [dates[s_clamp], bi.start.val]
            start_idx = prev_mid_end_idx if prev_mid_end_idx is not None else s_clamp
            if e_clamp <= start_idx and start_idx < n_base - 1:
                e_clamp = start_idx + 1
            end_coord = [dates[e_clamp], bi.end.val]
            mid_bis.append({
                "start": start_coord,
                "end": end_coord,
                "start_idx": start_idx,
                "end_idx": e_clamp,
                "direction": bi.direction.value,
            })
            prev_mid_end_coord = end_coord
            prev_mid_end_idx = e_clamp

        for zs in results[mid_p].zss:
            if not zs.start or not zs.end:
                continue
            s_i = map_pivot_to_base(zs.start.k.date, zs.zd, False, mid_p, base_df, base_dts, base_dts_list)
            e_i = map_pivot_to_base(zs.end.k.date, zs.zg, True, mid_p, base_df, base_dts, base_dts_list)
            if e_i < 0 or s_i >= n_base:
                continue
            s_clamp = max(0, min(n_base - 1, s_i))
            e_clamp = max(0, min(n_base - 1, e_i))
            mid_zss.append({
                "start_date": dates[s_clamp],
                "end_date": dates[e_clamp],
                "start_idx": s_clamp,
                "end_idx": e_clamp,
                "zg": round(zs.zg, 2),
                "zd": round(zs.zd, 2),
                "gg": round(zs.gg, 2),
                "dd": round(zs.dd, 2),
            })

    # 3. 小级别（基准）笔与中枢
    low_res = results[low_p]
    low_bis = []
    prev_low_end_coord = None
    prev_low_end_idx = None
    for bi in low_res.bis:
        s_i = bi.start.k.k_index
        if hasattr(bi.start.k, "klines") and bi.start.k.klines:
            is_start_high = (bi.start.fx_type == FXType.DING)
            for raw_k in bi.start.k.klines:
                raw_target = raw_k.high if is_start_high else raw_k.low
                if abs(raw_target - bi.start.val) < 1e-4:
                    s_i = raw_k.index
                    break

        e_i = bi.end.k.k_index
        if hasattr(bi.end.k, "klines") and bi.end.k.klines:
            is_end_high = (bi.end.fx_type == FXType.DING)
            for raw_k in bi.end.k.klines:
                raw_target = raw_k.high if is_end_high else raw_k.low
                if abs(raw_target - bi.end.val) < 1e-4:
                    e_i = raw_k.index
                    break

        s_i = max(0, min(n_base - 1, s_i))
        e_i = max(0, min(n_base - 1, e_i))
        start_coord = prev_low_end_coord if prev_low_end_coord is not None else [dates[s_i], bi.start.val]
        start_idx = prev_low_end_idx if prev_low_end_idx is not None else s_i
        end_coord = [dates[e_i], bi.end.val]
        low_bis.append({
            "start": start_coord,
            "end": end_coord,
            "start_idx": start_idx,
            "end_idx": e_i,
            "direction": bi.direction.value,
        })
        prev_low_end_coord = end_coord
        prev_low_end_idx = e_i


    low_zss = []
    for zs in low_res.zss:
        if not zs.start or not zs.end:
            continue
        s_i = max(0, min(n_base - 1, zs.start.k.k_index))
        e_i = max(0, min(n_base - 1, zs.end.k.k_index))
        if e_i < s_i:
            continue
        low_zss.append({
            "start_date": dates[s_i],
            "end_date": dates[e_i],
            "start_idx": s_i,
            "end_idx": e_i,
            "zg": round(zs.zg, 2),
            "zd": round(zs.zd, 2),
            "gg": round(zs.gg, 2),
            "dd": round(zs.dd, 2),
        })

    # 4. 买卖点标记点 (多级别同图融合与区间套专业标识，攻克大周期买卖点滞后)
    mmd_marks = []
    low_short_name = PERIOD_SPECS.get(low_p, {}).get("short_name", low_p)
    mid_short_name = PERIOD_SPECS.get(mid_p, {}).get("short_name", mid_p)
    high_short_name = PERIOD_SPECS.get(high_p, {}).get("short_name", high_p)

    # 4.1 小级别/当前底图级别买卖点 (抓极值影线拐点与稳健二买确认，解决滞后核心)
    for mmd in low_res.mmds:
        if mmd.bi:
            k_idx = mmd.bi.end.k.k_index
            if hasattr(mmd.bi.end.k, "klines") and mmd.bi.end.k.klines:
                is_end_high = (mmd.bi.end.fx_type == FXType.DING)
                for raw_k in mmd.bi.end.k.klines:
                    raw_target = raw_k.high if is_end_high else raw_k.low
                    if abs(raw_target - mmd.bi.end.val) < 1e-4:
                        k_idx = raw_k.index
                        break
            k_idx = max(0, min(n_base - 1, k_idx))
            is_buy = "buy" in mmd.mmd_type.value
            m_type = mmd.mmd_type.value.lower()

            if "1buy" in m_type:
                label_txt = f"[{low_short_name}]1买(极低)"
                short_label = f"[{low_short_name}]1买"
                category = "nested_1buy"
                trade_msg = f"【{low_short_name}区间套极值买点】底背驰极值拐点，抓相对最低价。严格以跌破分型底设止损（极小止损博高盈亏比）。"
            elif "2buy" in m_type:
                label_txt = f"[{low_short_name}]2买(稳健)"
                short_label = f"[{low_short_name}]2买"
                category = "steady_2buy"
                trade_msg = f"【{low_short_name}稳健买点】回踩不破前低起涨确认，避开大级别确认滞后，高胜率相对低吸点。"
            elif "3buy" in m_type:
                label_txt = f"[{low_short_name}]3买(主升起爆)"
                short_label = f"[{low_short_name}]3买"
                category = "breakout_3buy"
                trade_msg = f"【{low_short_name}中枢突破3买】突破中枢回抽不破中枢上沿，主升浪起爆点，动能强劲。"
            elif "1sell" in m_type:
                label_txt = f"[{low_short_name}]1卖(极高)"
                short_label = f"[{low_short_name}]1卖"
                category = "nested_1sell"
                trade_msg = f"【{low_short_name}区间套极值卖点】顶背驰极高点逃顶，大级别涨势衰竭，抓最高影线分批锁定利润。"
            elif "2sell" in m_type:
                label_txt = f"[{low_short_name}]2卖(清仓)"
                short_label = f"[{low_short_name}]2卖"
                category = "defense_2sell"
                trade_msg = f"【{low_short_name}清仓卖点】冲高回落反弹不创新高，多头动能枯竭，清仓或破位防守。"
            elif "3sell" in m_type:
                label_txt = f"[{low_short_name}]3卖(破位下杀)"
                short_label = f"[{low_short_name}]3卖"
                category = "breakdown_3sell"
                trade_msg = f"【{low_short_name}中枢破位3卖】跌破中枢反抽不入中枢，加速下杀风险，坚决空仓规避。"
            else:
                label_txt = f"[{low_short_name}]{mmd.mmd_type.value.upper()}"
                short_label = label_txt
                category = "other"
                trade_msg = mmd.msg

            mmd_marks.append({
                "coord": [dates[k_idx], mmd.bi.end.val],
                "date": dates[k_idx],
                "price": round(mmd.bi.end.val, 2),
                "type": mmd.mmd_type.value.upper(),
                "level": "low",
                "label": label_txt,
                "short_label": short_label,
                "category": category,
                "is_buy": is_buy,
                "msg": trade_msg,
            })

    # 4.2 中级别买卖点向底图映射 (次级别波段拐点与稳健确认)
    if not is_single_period:
        for mmd in mid_res.mmds:
            if mmd.bi:
                end_val = mmd.bi.end.val
                is_high = mmd.bi.end.fx_type == FXType.DING
                b_idx = map_pivot_to_base(mmd.bi.end.k.date, end_val, is_high, mid_p, base_df, base_dts, base_dts_list, fx_obj=mmd.bi.end)
                if 0 <= b_idx < n_base:
                    is_buy = "buy" in mmd.mmd_type.value
                    m_type = mmd.mmd_type.value.lower()
                    if "1buy" in m_type:
                        label_txt = f"[{mid_short_name}]区间套1买"
                        short_label = f"[{mid_short_name}]极低1买"
                        category = "mid_1buy"
                        trade_msg = f"【{mid_short_name}区间套1买】次级别底背驰极值拐点，博取中周期波段底部。"
                    elif "2buy" in m_type:
                        label_txt = f"[{mid_short_name}]稳健2买"
                        short_label = f"[{mid_short_name}]稳健2买"
                        category = "mid_2buy"
                        trade_msg = f"【{mid_short_name}稳健2买】次级别回踩不破前低，中周期起涨确认点。"
                    elif "3buy" in m_type:
                        label_txt = f"[{mid_short_name}]主升3买"
                        short_label = f"[{mid_short_name}]主升3买"
                        category = "mid_3buy"
                        trade_msg = f"【{mid_short_name}主升3买】次级别突破中枢回抽确认，主升起跑。"
                    elif "1sell" in m_type:
                        label_txt = f"[{mid_short_name}]极高1卖"
                        short_label = f"[{mid_short_name}]极高1卖"
                        category = "mid_1sell"
                        trade_msg = f"【{mid_short_name}极高1卖】次级别顶背驰，波段极高点分批锁定利润。"
                    elif "2sell" in m_type:
                        label_txt = f"[{mid_short_name}]清仓2卖"
                        short_label = f"[{mid_short_name}]清仓2卖"
                        category = "mid_2sell"
                        trade_msg = f"【{mid_short_name}清仓2卖】次级别反弹不破前高，波段清仓防守。"
                    elif "3sell" in m_type:
                        label_txt = f"[{mid_short_name}]破位3卖"
                        short_label = f"[{mid_short_name}]破位3卖"
                        category = "mid_3sell"
                        trade_msg = f"【{mid_short_name}破位3卖】跌破次级别中枢反抽不入，离场避险。"
                    else:
                        label_txt = f"[{mid_short_name}]{mmd.mmd_type.value.upper()}"
                        short_label = label_txt
                        category = "mid_other"
                        trade_msg = f"{PERIOD_SPECS[mid_p]['label']}: {mmd.msg}"

                    mmd_marks.append({
                        "coord": [dates[b_idx], end_val],
                        "date": dates[b_idx],
                        "price": round(end_val, 2),
                        "type": mmd.mmd_type.value.upper(),
                        "level": "mid",
                        "label": label_txt,
                        "short_label": short_label,
                        "category": category,
                        "is_buy": is_buy,
                        "msg": trade_msg,
                    })

    # 4.3 大级别买卖点向底图映射 (明确大级别趋势反转确认，阐明滞后原因与大趋势跟踪)
    if not is_single_period:
        for mmd in high_res.mmds:
            if mmd.bi:
                end_val = mmd.bi.end.val
                is_high = mmd.bi.end.fx_type == FXType.DING
                b_idx = map_pivot_to_base(mmd.bi.end.k.date, end_val, is_high, high_p, base_df, base_dts, base_dts_list, fx_obj=mmd.bi.end)
                if 0 <= b_idx < n_base:
                    is_buy = "buy" in mmd.mmd_type.value
                    m_type = mmd.mmd_type.value.lower()
                    if "1buy" in m_type:
                        label_txt = f"[{high_short_name}]大级别1买(趋势确认)"
                        short_label = f"[{high_short_name}]大1买"
                        category = "high_1buy"
                        trade_msg = f"【{high_short_name}大级别1买】趋势转折确认区（大级别笔确认存在滞后，适于长线趋势跟踪；更优相对低点请参考次级别区间套1买/2买）。"
                    elif "2buy" in m_type:
                        label_txt = f"[{high_short_name}]大级别2买"
                        short_label = f"[{high_short_name}]大2买"
                        category = "high_2buy"
                        trade_msg = f"【{high_short_name}大级别2买】大级别右侧回踩不破底，中长线安全边际最高。"
                    elif "3buy" in m_type:
                        label_txt = f"[{high_short_name}]大级别3买"
                        short_label = f"[{high_short_name}]大3买"
                        category = "high_3buy"
                        trade_msg = f"【{high_short_name}大级别3买】突破大级别中枢，超大级别主升浪起爆点。"
                    elif "1sell" in m_type:
                        label_txt = f"[{high_short_name}]大级别1卖(趋势确认)"
                        short_label = f"[{high_short_name}]大1卖"
                        category = "high_1sell"
                        trade_msg = f"【{high_short_name}大级别1卖】大级别顶背驰确认区（确认存在滞后，极高逃顶请参考次级别区间套1卖/2卖）。"
                    elif "2sell" in m_type:
                        label_txt = f"[{high_short_name}]大级别2卖"
                        short_label = f"[{high_short_name}]大2卖"
                        category = "high_2sell"
                        trade_msg = f"【{high_short_name}大级别2卖】反弹不过大级别前高，大周期趋势转熊防御。"
                    elif "3sell" in m_type:
                        label_txt = f"[{high_short_name}]大级别3卖"
                        short_label = f"[{high_short_name}]大3卖"
                        category = "high_3sell"
                        trade_msg = f"【{high_short_name}大级别3卖】跌破大级别中枢，进入大周期下行熊途。"
                    else:
                        label_txt = f"[{high_short_name}]大级别{mmd.mmd_type.value.upper()}"
                        short_label = label_txt
                        category = "high_other"
                        trade_msg = f"{PERIOD_SPECS[high_p]['label']}: {mmd.msg}"

                    mmd_marks.append({
                        "coord": [dates[b_idx], end_val],
                        "date": dates[b_idx],
                        "price": round(end_val, 2),
                        "type": mmd.mmd_type.value.upper(),
                        "level": "high",
                        "label": label_txt,
                        "short_label": short_label,
                        "category": category,
                        "is_buy": is_buy,
                        "msg": trade_msg,
                    })

    # 5. 共振买卖点标记 (三周期立体共振)
    res_marks = []
    for r in resonances:
        if 0 <= r.low_bar_idx < n_base:
            is_buy = r.direction == "BUY"
            res_marks.append({
                "coord": [dates[r.low_bar_idx], r.price],
                "date": dates[r.low_bar_idx],
                "price": round(r.price, 2),
                "direction": r.direction,
                "grade": r.grade,
                "pattern_name": r.pattern_name,
                "label": f"★{r.grade}买" if is_buy else f"▼{r.grade}卖",
                "short_label": f"★{r.grade}买" if is_buy else f"▼{r.grade}卖",
                "desc": r.description,
            })

    # 5.1 顶底分型标记 (单周期及缠论走势结构关键要素)
    fractal_marks = []
    for fx in getattr(low_res, "fractals", []):
        k_idx = fx.k.k_index
        if hasattr(fx.k, "klines") and fx.k.klines:
            is_ding = (fx.fx_type == FXType.DING)
            for raw_k in fx.k.klines:
                raw_target = raw_k.high if is_ding else raw_k.low
                if abs(raw_target - fx.val) < 1e-4:
                    k_idx = raw_k.index
                    break
        k_idx = max(0, min(n_base - 1, k_idx))
        is_ding = (fx.fx_type == FXType.DING)
        fractal_marks.append({
            "coord": [dates[k_idx], round(fx.val, 2)],
            "date": dates[k_idx],
            "price": round(fx.val, 2),
            "type": "ding" if is_ding else "di",
            "label": "顶分型" if is_ding else "底分型",
            "short_label": "▲顶" if is_ding else "▼底",
        })

    # 5.2 线段映射 (低级别笔向上构建的高一级走势段)
    xds = []
    prev_xd_end_coord = None
    prev_xd_end_idx = None
    for xd in getattr(low_res, "xds", []):
        s_i = xd.start.k.k_index
        if hasattr(xd.start.k, "klines") and xd.start.k.klines:
            is_start_high = (xd.start.fx_type == FXType.DING)
            for raw_k in xd.start.k.klines:
                raw_target = raw_k.high if is_start_high else raw_k.low
                if abs(raw_target - xd.start.val) < 1e-4:
                    s_i = raw_k.index
                    break
        e_i = xd.end.k.k_index
        if hasattr(xd.end.k, "klines") and xd.end.k.klines:
            is_end_high = (xd.end.fx_type == FXType.DING)
            for raw_k in xd.end.k.klines:
                raw_target = raw_k.high if is_end_high else raw_k.low
                if abs(raw_target - xd.end.val) < 1e-4:
                    e_i = raw_k.index
                    break
        s_i = max(0, min(n_base - 1, s_i))
        e_i = max(0, min(n_base - 1, e_i))
        start_coord = prev_xd_end_coord if prev_xd_end_coord is not None else [dates[s_i], xd.start.val]
        start_idx = prev_xd_end_idx if prev_xd_end_idx is not None else s_i
        end_coord = [dates[e_i], xd.end.val]
        xds.append({
            "start": start_coord,
            "end": end_coord,
            "start_idx": start_idx,
            "end_idx": e_i,
            "direction": xd.direction.value,
        })
        prev_xd_end_coord = end_coord
        prev_xd_end_idx = e_i

    # 单周期模式下：线段直接作为 high_bis（紫色粗折线）在图表中高光呈现！
    if is_single_period:
        high_bis = xds

    # 6. MACD 数据及背离（底背离 / 顶背离）识别
    macd_data = low_res.macd or {}
    macd_hist = [round(h * 2, 3) for h in (macd_data.get("hist") or [])]
    macd_dif = [round(d, 3) for d in (macd_data.get("dif") or [])]
    macd_dea = [round(d, 3) for d in (macd_data.get("dea") or [])]

    macd_marks = []
    macd_div_lines = []
    seen_macd_bars = set()

    # 6.1 结合缠论背驰点 (笔背驰 / 盘整背驰 / 趋势背驰)
    for bc in getattr(low_res, "bcs", []):
        if not bc.curr or not getattr(bc, "bc", False):
            continue
        bar_idx = getattr(bc.curr.end.k, "k_index", -1)
        if 0 <= bar_idx < n_base and bar_idx not in seen_macd_bars:
            seen_macd_bars.add(bar_idx)
            is_bottom = getattr(bc.curr.direction, "value", "") == "down"
            m_dif = macd_dif[bar_idx] if bar_idx < len(macd_dif) else 0.0
            m_hist = macd_hist[bar_idx] if bar_idx < len(macd_hist) else 0.0
            macd_marks.append({
                "date": dates[bar_idx],
                "bar_idx": bar_idx,
                "type": "bottom" if is_bottom else "top",
                "label": "▲底背离" if is_bottom else "▼顶背离",
                "dif": m_dif,
                "hist": m_hist,
                "price": round(float(base_df["close"].iloc[bar_idx]), 2),
                "msg": bc.msg or ("缠论底背驰(MACD绿柱动能衰竭)" if is_bottom else "缠论顶背驰(MACD红柱动能衰竭)"),
            })
            if hasattr(bc, "prev") and bc.prev and hasattr(bc.prev.end, "k"):
                p_idx = getattr(bc.prev.end.k, "k_index", -1)
                if 0 <= p_idx < bar_idx:
                    macd_div_lines.append({
                        "start": [dates[p_idx], macd_dif[p_idx]],
                        "end": [dates[bar_idx], m_dif],
                        "type": "bottom" if is_bottom else "top",
                        "color": "#ef4444" if is_bottom else "#10b981",
                        "label": "缠论底背驰连线" if is_bottom else "缠论顶背驰连线",
                    })

    # 6.2 结合缠论一类买卖点 (天然对应标准走势终结底背离/顶背离)
    for mmd in low_res.mmds:
        if not mmd.bi:
            continue
        bar_idx = getattr(mmd.bi.end.k, "k_index", -1)
        if 0 <= bar_idx < n_base and bar_idx not in seen_macd_bars:
            m_type = mmd.mmd_type.value.lower()
            if "1buy" in m_type:
                seen_macd_bars.add(bar_idx)
                m_dif = macd_dif[bar_idx] if bar_idx < len(macd_dif) else 0.0
                m_hist = macd_hist[bar_idx] if bar_idx < len(macd_hist) else 0.0
                macd_marks.append({
                    "date": dates[bar_idx],
                    "bar_idx": bar_idx,
                    "type": "bottom",
                    "label": "▲底背离",
                    "dif": m_dif,
                    "hist": m_hist,
                    "price": round(float(base_df["close"].iloc[bar_idx]), 2),
                    "msg": "一买底背驰: 价格见底且MACD动能底背离",
                })
            elif "1sell" in m_type:
                seen_macd_bars.add(bar_idx)
                m_dif = macd_dif[bar_idx] if bar_idx < len(macd_dif) else 0.0
                m_hist = macd_hist[bar_idx] if bar_idx < len(macd_hist) else 0.0
                macd_marks.append({
                    "date": dates[bar_idx],
                    "bar_idx": bar_idx,
                    "type": "top",
                    "label": "▼顶背离",
                    "dif": m_dif,
                    "hist": m_hist,
                    "price": round(float(base_df["close"].iloc[bar_idx]), 2),
                    "msg": "一卖顶背驰: 价格冲顶且MACD动能顶背离",
                })

    # 6.3 经典技术指标 MACD 峰谷背离检测 (价格创极值但 DIF 未创新极值)
    if len(macd_dif) >= 20 and not base_df.empty:
        closes = base_df["close"].values
        for i in range(10, len(macd_dif) - 5):
            if i in seen_macd_bars:
                continue
            # 谷底底背离候选 (DIF < 0 且局部低谷)
            if macd_dif[i] < macd_dif[i - 1] and macd_dif[i] < macd_dif[i + 1] and macd_dif[i] < 0:
                prev_valley = None
                for j in range(i - 8, max(0, i - 80), -1):
                    if macd_dif[j] < macd_dif[j - 1] and macd_dif[j] < macd_dif[j + 1] and macd_dif[j] < 0:
                        prev_valley = j
                        break
                if prev_valley is not None:
                    if closes[i] <= closes[prev_valley] * 0.998 and macd_dif[i] > macd_dif[prev_valley]:
                        seen_macd_bars.add(i)
                        macd_marks.append({
                            "date": dates[i],
                            "bar_idx": i,
                            "type": "bottom",
                            "label": "▲底背离",
                            "dif": macd_dif[i],
                            "hist": macd_hist[i],
                            "price": round(float(closes[i]), 2),
                            "msg": f"MACD底背离: 现价 ¥{closes[i]:.2f} 低于前低 ¥{closes[prev_valley]:.2f}，但DIF明显抬高",
                        })
                        macd_div_lines.append({
                            "start": [dates[prev_valley], macd_dif[prev_valley]],
                            "end": [dates[i], macd_dif[i]],
                            "type": "bottom",
                            "color": "#ef4444",
                            "label": "MACD底背离连线",
                        })
            # 峰顶顶背离候选 (DIF > 0 且局部高峰)
            elif macd_dif[i] > macd_dif[i - 1] and macd_dif[i] > macd_dif[i + 1] and macd_dif[i] > 0:
                prev_peak = None
                for j in range(i - 8, max(0, i - 80), -1):
                    if macd_dif[j] > macd_dif[j - 1] and macd_dif[j] > macd_dif[j + 1] and macd_dif[j] > 0:
                        prev_peak = j
                        break
                if prev_peak is not None:
                    if closes[i] >= closes[prev_peak] * 1.002 and macd_dif[i] < macd_dif[prev_peak]:
                        seen_macd_bars.add(i)
                        macd_marks.append({
                            "date": dates[i],
                            "bar_idx": i,
                            "type": "top",
                            "label": "▼顶背离",
                            "dif": macd_dif[i],
                            "hist": macd_hist[i],
                            "price": round(float(closes[i]), 2),
                            "msg": f"MACD顶背离: 现价 ¥{closes[i]:.2f} 高于前高 ¥{closes[prev_peak]:.2f}，但DIF明显衰退",
                        })
                        macd_div_lines.append({
                            "start": [dates[prev_peak], macd_dif[prev_peak]],
                            "end": [dates[i], macd_dif[i]],
                            "type": "top",
                            "color": "#10b981",
                            "label": "MACD顶背离连线",
                        })

    macd_marks.sort(key=lambda x: x["bar_idx"])

    # 6.3 辅助副图技术指标计算 (RSI, KDJ, EXPMA)
    c_arr = base_df["close"].values if not base_df.empty else np.array([])
    h_arr = base_df["high"].values if not base_df.empty else np.array([])
    l_arr = base_df["low"].values if not base_df.empty else np.array([])

    rsi_data: dict[str, list[float | None]] = {"rsi6": [], "rsi12": [], "rsi24": []}
    kdj_data: dict[str, list[float | None]] = {"k": [], "d": [], "j": []}
    expma_data: dict[str, list[float | None]] = {"exp12": [], "exp50": []}

    if len(c_arr) > 0:
        r6 = RSI(c_arr, 6)
        r12 = RSI(c_arr, 12)
        r24 = RSI(c_arr, 24)
        rsi_data = {
            "rsi6": [safe_float(v) for v in r6],
            "rsi12": [safe_float(v) for v in r12],
            "rsi24": [safe_float(v) for v in r24],
        }

        kv, dv, jv = KDJ(c_arr, h_arr, l_arr, 9, 3, 3)
        kdj_data = {
            "k": [safe_float(v) for v in kv],
            "d": [safe_float(v) for v in dv],
            "j": [safe_float(v) for v in jv],
        }

        e12, e50 = EXPMA(c_arr, 12, 50)
        expma_data = {
            "exp12": [safe_float(v) for v in e12],
            "exp50": [safe_float(v) for v in e50],
        }

    # 7. 各周期独立分屏数据（用于切换分屏联动视图或单独看某个周期）
    levels_data = {}
    for p in p_list:
        p_res = results[p]
        p_df = dfs[p]
        p_dates = p_df["datetime"].astype(str).tolist() if not p_df.empty else []
        p_candles = p_df[["open", "close", "low", "high"]].values.tolist() if not p_df.empty else []
        p_bis = [
            [[p_dates[bi.start.k.k_index], bi.start.val], [p_dates[bi.end.k.k_index], bi.end.val]]
            for bi in p_res.bis
            if 0 <= bi.start.k.k_index < len(p_dates) and 0 <= bi.end.k.k_index < len(p_dates)
        ]
        p_zss = [
            {
                "start_date": p_dates[zs.start.k.k_index],
                "end_date": p_dates[zs.end.k.k_index],
                "zg": round(zs.zg, 2),
                "zd": round(zs.zd, 2),
            }
            for zs in p_res.zss
            if zs.start and zs.end
            and 0 <= zs.start.k.k_index < len(p_dates)
            and 0 <= zs.end.k.k_index < len(p_dates)
        ]
        p_macd = p_res.macd or {}

        p_c = p_df["close"].values if not p_df.empty else np.array([])
        p_h = p_df["high"].values if not p_df.empty else np.array([])
        p_l = p_df["low"].values if not p_df.empty else np.array([])
        p_rsi: dict[str, list[float | None]] = {"rsi6": [], "rsi12": [], "rsi24": []}
        p_kdj: dict[str, list[float | None]] = {"k": [], "d": [], "j": []}
        p_expma: dict[str, list[float | None]] = {"exp12": [], "exp50": []}
        if len(p_c) > 0:
            p_rsi = {
                "rsi6": [safe_float(v) for v in RSI(p_c, 6)],
                "rsi12": [safe_float(v) for v in RSI(p_c, 12)],
                "rsi24": [safe_float(v) for v in RSI(p_c, 24)],
            }
            p_kv, p_dv, p_jv = KDJ(p_c, p_h, p_l, 9, 3, 3)
            p_kdj = {
                "k": [safe_float(v) for v in p_kv],
                "d": [safe_float(v) for v in p_dv],
                "j": [safe_float(v) for v in p_jv],
            }
            p_e12, p_e50 = EXPMA(p_c, 12, 50)
            p_expma = {
                "exp12": [safe_float(v) for v in p_e12],
                "exp50": [safe_float(v) for v in p_e50],
            }

        levels_data[p] = {
            "period": p,
            "label": PERIOD_SPECS[p]["label"],
            "short_name": PERIOD_SPECS[p]["short_name"],
            "dates": p_dates,
            "candles": p_candles,
            "bis": p_bis,
            "zss": p_zss,
            "macd": {
                "hist": [round(h * 2, 3) for h in (p_macd.get("hist") or [])],
                "dif": [round(d, 3) for d in (p_macd.get("dif") or [])],
                "dea": [round(d, 3) for d in (p_macd.get("dea") or [])],
            },
            "rsi": p_rsi,
            "kdj": p_kdj,
            "expma": p_expma,
            "inflow": calculate_inflow_data(
                p_df,
                clean_code=clean_code,
                is_backtracking=is_backtracking,
                is_daily=(p == "DAY"),
            ),
            "merged_chart": build_merged_chart_data(
                low_res=p_res,
                base_df=p_df,
                dates=p_dates,
                high_bis=[],
                high_zss=[],
                mid_bis=[],
                mid_zss=[],
                mmd_marks=[],
                res_marks=[],
                clean_code=clean_code,
                is_backtracking=is_backtracking,
                is_daily=(p == "DAY"),
            ),
        }

    # 最新价格与涨跌
    latest_close = base_df["close"].iloc[-1] if not base_df.empty else 0.0
    prev_close = base_df["close"].iloc[-2] if len(base_df) >= 2 else latest_close
    chg_pct = round((latest_close - prev_close) / prev_close * 100, 2) if prev_close else 0.0

    result_data = {
        "code": clean_code,
        "name": stock_name,
        "periods": {
            "high": {"key": high_p, "label": PERIOD_SPECS[high_p]["label"], "name": PERIOD_SPECS[high_p]["short_name"]},
            "mid": {"key": mid_p, "label": PERIOD_SPECS[mid_p]["label"], "name": PERIOD_SPECS[mid_p]["short_name"]},
            "low": {"key": low_p, "label": PERIOD_SPECS[low_p]["label"], "name": PERIOD_SPECS[low_p]["short_name"]},
        },
        "base_period": low_p,
        "summary": {
            "latest_price": round(latest_close, 2),
            "change_pct": chg_pct,
            "latest_date": latest_dt,
            "high_state": current_high_state.to_dict(),
            "mid_state": current_mid_state.to_dict(),
            "low_state": current_low_state.to_dict(),
            "resonance_count": len(resonances),
            "is_backtracking": is_backtracking,
            "cutoff_date": cutoff_date if is_backtracking else None,
            "is_single_period": is_single_period,
            "period": low_p,
            "period_name": PERIOD_SPECS[low_p]["short_name"],
            "latest_bi_dir": current_low_state.current_bi_direction,
            "latest_fx": fractal_marks[-1] if fractal_marks else None,
            "latest_xd_dir": xds[-1]["direction"] if xds else "",
            "latest_zs_range": [low_zss[-1]["zd"], low_zss[-1]["zg"]] if low_zss else None,
            "latest_mmd": current_low_state.recent_mmd_type,
        },
        "resonances": [r.to_dict() for r in resonances],
        "unified_chart": {
            "dates": dates,
            "candles": candles,
            "volumes": volumes,
            "amounts": amounts,
            "high_bis": high_bis,
            "high_zss": high_zss,
            "mid_bis": mid_bis,
            "mid_zss": mid_zss,
            "low_bis": low_bis,
            "low_zss": low_zss,
            "xds": xds,
            "fractal_marks": fractal_marks,
            "mmd_marks": mmd_marks,
            "res_marks": res_marks,
            "macd": {
                "hist": macd_hist,
                "dif": macd_dif,
                "dea": macd_dea,
                "marks": macd_marks,
            },
            "macd_marks": macd_marks,
            "macd_div_lines": macd_div_lines,
            "rsi": rsi_data,
            "kdj": kdj_data,
            "expma": expma_data,
            "inflow": calculate_inflow_data(
                base_df,
                clean_code=clean_code,
                is_backtracking=is_backtracking,
                is_daily=(low_p == "DAY"),
            ),
        },
        "merged_chart": build_merged_chart_data(
            low_res=low_res,
            base_df=base_df,
            dates=dates,
            high_bis=high_bis,
            high_zss=high_zss,
            mid_bis=mid_bis,
            mid_zss=mid_zss,
            mmd_marks=mmd_marks,
            res_marks=res_marks,
            clean_code=clean_code,
            is_backtracking=is_backtracking,
            is_daily=(low_p == "DAY"),
            fractal_marks=fractal_marks,
        ),
        "levels_data": levels_data,
        "backtrack_timeline": {
            "min_date": min_date,
            "max_date": max_date,
            "available_dates": available_dates,
            "current_date": latest_dt,
            "total_bars": len(available_dates),
            "current_bar_index": len(base_df) - 1 if not base_df.empty else 0,
        },
    }

    if is_backtracking:
        with _RESONANCE_CACHE_LOCK:
            if len(_RESONANCE_BACKTRACK_ANALYSIS_CACHE) > 500:
                for k in list(_RESONANCE_BACKTRACK_ANALYSIS_CACHE.keys())[:200]:
                    _RESONANCE_BACKTRACK_ANALYSIS_CACHE.pop(k, None)
            _RESONANCE_BACKTRACK_ANALYSIS_CACHE[(clean_code, tuple(p_list), cutoff_str)] = result_data
    else:
        with _RESONANCE_CACHE_LOCK:
            if len(_RESONANCE_REALTIME_ANALYSIS_CACHE) > 500:
                for k in list(_RESONANCE_REALTIME_ANALYSIS_CACHE.keys())[:200]:
                    _RESONANCE_REALTIME_ANALYSIS_CACHE.pop(k, None)
            rt_cache_key = (clean_code, tuple(p_list), str(latest_dt), round(float(latest_close), 2))
            _RESONANCE_REALTIME_ANALYSIS_CACHE[rt_cache_key] = (now_ts, result_data)

    return result_data
