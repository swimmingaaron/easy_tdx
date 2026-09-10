"""Trading System Quant Engine (复刻 trading_system.cgi / cross_conditions.py)

基于 easy_tdx 原生行情与 K 线体系：
1. 18 项买入打分模型 (buy_score) 与 9 项卖出预警打分模型 (sell_score)
2. 5 大实战选股指标 (r1: 均线多头, r2: 量价回踩, r3: 拒绝僵尸, r4: MACD吸筹, r5: 布林护盘)
3. 7 大战法形态识别 (is_macd, is_peach, is_duck_head, is_cup_tea, is_cross3line, is_d_volume, is_quad)
4. 红星/绿星量价共振与爆量滞涨模型标记
5. 近 8 期财报指标抓取与深度基本面智能诊断
6. 单股历史变迁回溯 (30~60 天买卖打分时序)
"""
from __future__ import annotations

import logging
import os
import json
import time
import gzip
import urllib.request
import urllib.parse
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd

from easy_tdx.market_data import fetch_security_kline, fetch_realtime_pool_quotes, _TDX_POOL, _get_market
from easy_tdx.sina import SinaClient
from easy_tdx.stock_lookup import get_stock_name, COMMON_STOCKS
from easy_tdx.screener.universe import get_universe_symbols, CORE_UNIVERSE
from easy_tdx.pattern_recognition import detect_patterns

logger = logging.getLogger(__name__)

# pattern_recognition 全量 75 种形态多空分类体系
BULLISH_PATTERNS = {
    # 均线 & 突破
    "放量突破", "蛟龙出海", "出水芙蓉", "均线多头", "缩量回踩", "金蜘蛛", "价托",
    # 看涨 K 线
    "启明星", "曙光初现", "旭日东升", "阳包阴", "锤子线", "倒锤子线", "多方炮", "红三兵", "上升三法",
    # 指标金叉 & 背离
    "零上金叉", "零轴下金叉", "MACD金叉", "MACD底背离",
    "KDJ低位金叉", "KDJ超卖",
    "RSI超卖", "RSI底背离",
    "CCI突破", "CCI超卖",
    "OBV创新高",
    # 量价
    "价涨量增", "地量",
    # 布林
    "布林突破", "布林下轨支撑",
    # 缠论与 TD
    "底分型", "TD9见底", "TD13见底",
    # 缺口
    "向上跳空缺口",
}

BEARISH_PATTERNS = {
    # 均线 & 破位
    "均线空头", "空头排列", "死蜘蛛", "价压",
    # 看跌 K 线
    "三只乌鸦", "乌云盖顶", "倾盆大雨", "阴包阳", "黄昏之星", "下降三法", "射击之星", "吊颈线", "空方炮",
    # 指标死叉 & 背离
    "MACD死叉", "MACD顶背离",
    "KDJ高位死叉", "KDJ超买",
    "RSI超买", "RSI顶背离",
    "OBV顶背离",
    # 量价
    "放量滞涨", "放量下跌", "量价背离",
    # 布林
    "布林跌破", "布林上轨压力",
    # 缠论与 TD
    "顶分型", "TD9见顶", "TD13见顶",
    # 缺口
    "向下跳空缺口",
}

NEUTRAL_PATTERNS = {
    "布林收口", "布林开口",
    "低位十字星", "长上影十字", "长下影十字", "十字星",
    "十字孕线", "孕线",
    "震荡蓄势", "弱势整理", "震荡整理",
}

_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Encoding": "gzip, deflate",
    "Referer": "https://emweb.securities.eastmoney.com/",
}

# 缓存配置
_CACHE_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "trading_system_cache")
os.makedirs(_CACHE_DIR, exist_ok=True)
_MEM_CACHE: Dict[str, Tuple[float, Any]] = {}
_FINA_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_HOLDERS_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_EVAL_PROGRESS: Dict[str, Dict[str, Any]] = {}


def get_universe_eval_progress(universe_type: str = "core") -> Dict[str, Any]:
    """获取指定股票池的实时计算进度。"""
    return _EVAL_PROGRESS.get(universe_type, {
        "status": "idle",
        "total": 0,
        "completed": 0,
        "pct": 100.0,
        "stock": "",
    })


def _get_market_prefix(code: str) -> str:
    c = code.strip().upper().replace("SH", "").replace("SZ", "").replace("BJ", "")
    if c.startswith("6") or c.startswith("9"):
        return "SH"
    elif c.startswith("8") or c.startswith("4"):
        return "BJ"
    return "SZ"


def fetch_stock_holders(code: str) -> Dict[str, Any]:
    """
    获取股东人数及前十大股东集中度。
    第一获取接口：从 easy_tdx 原生 TDX 接口获取最新股东人数；
    若失败或需要历史变动及集中度，再从外部接口（东方财富等）补充/兜底抓取。
    """
    clean_code = code.strip().upper().replace("SH", "").replace("SZ", "").replace("BJ", "")
    pfx = _get_market_prefix(clean_code)
    now = time.time()
    if clean_code in _HOLDERS_CACHE:
        ts, data = _HOLDERS_CACHE[clean_code]
        if now - ts < 86400:
            return data

    res = {
        "holders_num": 0,
        "holders_str": "--",
        "holder_ratio": 0.0,
        "holder_focus": "--",
        "holders_changes": [],
        "holders_history": [],
    }

    # 1. 第一获取接口：easy_tdx 原生 TDX get_finance_info
    easy_tdx_ok = False
    try:
        cli = _TDX_POOL.acquire()
        try:
            mkt = _get_market(clean_code)
            df = cli.get_finance_info(mkt, clean_code)
            _TDX_POOL.release(cli, success=True)
            if df is not None and not df.empty:
                row = df.iloc[0]
                num = int(row.get("gudong_renshu") or 0)
                if num > 0:
                    res["holders_num"] = num
                    res["holders_str"] = f"{num / 10000:.2f}万" if num >= 10000 else str(num)
                    easy_tdx_ok = True
        except Exception as e:
            _TDX_POOL.release(cli, success=False)
            logger.debug(f"easy_tdx get_finance_info failed for {clean_code}: {e}")
    except Exception as e:
        logger.debug(f"easy_tdx acquire failed for {clean_code}: {e}")

    # 2. 第二获取接口/补充接口：抓取股东集中度与完整历史变动明细（若第一接口失败则作为完整兜底）
    try:
        url = f"https://emweb.securities.eastmoney.com/PC_HSF10/ShareholderResearch/PageAjax?code={pfx}{clean_code}"
        req = urllib.request.Request(url, headers=_DEFAULT_HEADERS)
        with urllib.request.urlopen(req, timeout=2.5) as resp:
            raw_bytes = resp.read()
            if raw_bytes[:2] == b"\x1f\x8b":
                raw = gzip.decompress(raw_bytes).decode("utf-8", errors="replace")
            else:
                raw = raw_bytes.decode("utf-8", errors="replace")
            data_json = json.loads(raw)
            if "gdrs" in data_json and data_json["gdrs"]:
                gdrs = data_json["gdrs"]
                latest = gdrs[0]
                em_num = int(latest.get("HOLDER_TOTAL_NUM") or 0)
                # 股东人数格式化 (优先采用东财精确总人数)
                if em_num > 0:
                    res["holders_num"] = em_num
                    res["holders_str"] = f"{em_num / 10000:.2f}万" if em_num >= 10000 else str(em_num)

                ratio = float(latest.get("HOLD_RATIO_TOTAL") or latest.get("FREEHOLD_RATIO_TOTAL") or 0.0)
                focus = str(latest.get("HOLD_FOCUS") or "")

                changes = []
                for item in gdrs[:3]:
                    chg_r = item.get("TOTAL_NUM_RATIO")
                    edate = str(item.get("END_DATE") or "")[:10]
                    if chg_r is not None:
                        changes.append({
                            "date": edate,
                            "ratio": round(float(chg_r), 2),
                            "num": int(item.get("HOLDER_TOTAL_NUM") or 0)
                        })

                # 完整历史变动明细 (对齐变动日期、股东总人数、较上期变动)
                history = []
                for item in gdrs:
                    edate = str(item.get("END_DATE") or "")[:10]
                    h_num = int(item.get("HOLDER_TOTAL_NUM") or 0)
                    h_num_str = f"{h_num / 10000:.2f}万" if h_num >= 10000 else str(h_num)
                    chg_r = item.get("TOTAL_NUM_RATIO")
                    ratio_val = round(float(chg_r), 2) if chg_r is not None else None
                    ratio_str = f"{ratio_val:+.2f}%" if ratio_val is not None else ""
                    history.append({
                        "date": edate,
                        "num": h_num,
                        "num_str": h_num_str,
                        "ratio": ratio_val,
                        "ratio_str": ratio_str,
                        "hold_ratio": round(float(item.get("HOLD_RATIO_TOTAL") or item.get("FREEHOLD_RATIO_TOTAL") or 0.0), 2),
                        "focus": str(item.get("HOLD_FOCUS") or ""),
                    })

                res["holder_ratio"] = round(ratio, 2)
                res["holder_focus"] = focus
                res["holders_changes"] = changes
                res["holders_history"] = history
    except Exception as e:
        logger.debug(f"Eastmoney shareholder fetch failed for {clean_code}: {e}")

    _HOLDERS_CACHE[clean_code] = (now, res)
    return res


def _calculate_consecutive_flow(df: pd.DataFrame, realtime_quote: Optional[Dict[str, Any]] = None) -> Tuple[int, float]:
    """
    计算连续净流入天数与累计净流入金额。
    正数表示连续流入天数，负数表示连续流出天数。
    """
    if df is None or df.empty:
        return 0, 0.0

    c = df["close"].values
    h = df["high"].values
    l = df["low"].values
    amt = df["amount"].values if "amount" in df.columns else c * df["volume"].values
    n = len(c)
    if n == 0:
        return 0, 0.0

    denom = np.maximum(0.01, h - l)
    mfm = ((c - l) - (h - c)) / denom
    k_flows = mfm * amt

    m1 = float(realtime_quote.get("main_net_amount", 0.0)) if realtime_quote else 0.0
    m3 = float(realtime_quote.get("main_net_3d", 0.0)) if realtime_quote else 0.0
    m5 = float(realtime_quote.get("main_net_5d", 0.0)) if realtime_quote else 0.0

    if abs(m1) > 0:
        k_flows[-1] = m1

    cur_sign = 1 if k_flows[-1] > 0 else (-1 if k_flows[-1] < 0 else 0)
    if cur_sign == 0:
        return 0, 0.0

    consec_days = 0
    consec_amount = 0.0
    for i in range(n - 1, -1, -1):
        flow_i = k_flows[i]
        if (cur_sign > 0 and flow_i > 0) or (cur_sign < 0 and flow_i < 0):
            consec_days += 1
            consec_amount += flow_i
        else:
            break

    if realtime_quote:
        if cur_sign > 0 and m1 > 0:
            if m3 > m1 and consec_days < 3:
                consec_days = 3
                consec_amount = max(consec_amount, m3)
            if m5 > m3 and consec_days >= 3 and consec_days < 5:
                consec_days = 5
                consec_amount = max(consec_amount, m5)
        elif cur_sign < 0 and m1 < 0:
            if m3 < m1 and consec_days < 3:
                consec_days = 3
                consec_amount = min(consec_amount, m3)
            if m5 < m3 and consec_days >= 3 and consec_days < 5:
                consec_days = 5
                consec_amount = min(consec_amount, m5)

    sign_days = consec_days if cur_sign > 0 else -consec_days
    return int(sign_days), float(consec_amount)




def calculate_zig(close: np.ndarray, change_pct: float = 0.05) -> Tuple[np.ndarray, int]:
    """
    计算经典 ZIG 转向序列与当前转向状态天数。
    返回值:
      zig_series: 沿极值点连线的序列
      current_days: 当前向上为正天数(反转首日为1)，向下为负天数(反转首日为-1)
    """
    n = len(close)
    if n < 5:
        return np.copy(close), 0

    pivots: List[Tuple[int, float, int]] = []  # (idx, price, type: +1 for peak, -1 for trough)
    
    trend = 0  # 1 for up, -1 for down
    last_pivot_idx = 0
    last_pivot_price = close[0]

    for i in range(1, n):
        cur_p = close[i]
        if last_pivot_price <= 0:
            last_pivot_price = cur_p
            continue
            
        ratio = (cur_p - last_pivot_price) / last_pivot_price
        
        if trend == 0:
            if ratio >= change_pct:
                trend = 1
                pivots.append((last_pivot_idx, last_pivot_price, -1))
                last_pivot_idx = i
                last_pivot_price = cur_p
            elif ratio <= -change_pct:
                trend = -1
                pivots.append((last_pivot_idx, last_pivot_price, 1))
                last_pivot_idx = i
                last_pivot_price = cur_p
        elif trend == 1:
            if cur_p > last_pivot_price:
                last_pivot_idx = i
                last_pivot_price = cur_p
            elif (last_pivot_price - cur_p) / last_pivot_price >= change_pct:
                pivots.append((last_pivot_idx, last_pivot_price, 1))
                trend = -1
                last_pivot_idx = i
                last_pivot_price = cur_p
        elif trend == -1:
            if cur_p < last_pivot_price:
                last_pivot_idx = i
                last_pivot_price = cur_p
            elif (cur_p - last_pivot_price) / last_pivot_price >= change_pct:
                pivots.append((last_pivot_idx, last_pivot_price, -1))
                trend = 1
                last_pivot_idx = i
                last_pivot_price = cur_p

    if not pivots:
        return np.copy(close), 1 if close[-1] >= close[0] else -1

    last_p = pivots[-1]
    days_since_pivot = n - 1 - last_p[0]
    
    if last_p[2] == -1:
        current_zig_day = max(1, days_since_pivot + 1)
    else:
        current_zig_day = -max(1, days_since_pivot + 1)

    return close, int(current_zig_day)


def evaluate_kline_strategy(code: str, df: pd.DataFrame, realtime_quote: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    对单只股票完整评估打分与形态指标（全部转为原生 Python 类型以保证 JSON 序列化无误）。
    """
    if df is None or len(df) < 30:
        return {}

    close = df["close"].values.astype(float)
    high = df["high"].values.astype(float)
    low = df["low"].values.astype(float)
    open_p = df["open"].values.astype(float)
    vol = df["volume"].values.astype(float)
    dates = df["datetime"].astype(str).tolist()

    n = len(df)

    # 1. 基础价格、涨幅、量比、换手
    cur_close = float(close[-1])
    pre_close = float(close[-2]) if n >= 2 else cur_close
    cur_pct = round(((cur_close / max(0.01, pre_close)) - 1.0) * 100, 2)
    cur_open = float(open_p[-1])
    cur_high = float(high[-1])
    cur_low = float(low[-1])
    cur_vol = float(vol[-1])
    rec_date = str(dates[-1])[:10]

    # 实时行情补充
    dde_net = 0.0
    dde_all = 0.0
    mkt_capt = 0.0
    amount = float(df["amount"].values[-1]) if "amount" in df.columns else float(cur_vol * cur_close)

    if realtime_quote:
        if "price" in realtime_quote and realtime_quote["price"] > 0:
            cur_close = float(realtime_quote["price"])
            cur_pct = float(realtime_quote.get("change_pct", cur_pct))
        if "volume" in realtime_quote and realtime_quote["volume"] > 0:
            cur_vol = float(realtime_quote["volume"])
        if "main_net_amount" in realtime_quote:
            dde_net = float(realtime_quote["main_net_amount"])
        if "turnover_wan" in realtime_quote:
            amount = float(realtime_quote["turnover_wan"]) * 10000.0
        if "total_mv_yi" in realtime_quote:
            mkt_capt = float(realtime_quote["total_mv_yi"]) * 1e8
        dde_all = float(realtime_quote.get("main_net_5d", 0.0))

    # 量比 (当前成交量 / 过去5日平均量)
    v5 = float(np.mean(vol[-6:-1])) if n >= 6 else (cur_vol if cur_vol > 0 else 1.0)
    v_rate = round(float(cur_vol / max(1.0, v5)), 2)

    # 换手率估算
    if mkt_capt > 0 and amount > 0:
        t_rate = round(float((amount / mkt_capt) * 100.0), 2)
    else:
        t_rate = round(float(min(25.0, max(0.5, (cur_vol / max(100000.0, v5 * 30.0)) * 10.0))), 2)

    # 2. 均线与指标系统
    s_close = pd.Series(close)
    ma5 = s_close.rolling(5).mean().values
    ma10 = s_close.rolling(10).mean().values
    ma20 = s_close.rolling(20).mean().values
    ma30 = s_close.rolling(30).mean().values
    ma60 = s_close.rolling(60).mean().values if n >= 60 else ma30

    ema10 = s_close.ewm(span=10, adjust=False).mean().values
    ema20 = s_close.ewm(span=20, adjust=False).mean().values
    ema30 = s_close.ewm(span=30, adjust=False).mean().values
    ema12 = s_close.ewm(span=12, adjust=False).mean().values
    ema26 = s_close.ewm(span=26, adjust=False).mean().values
    dif = ema12 - ema26
    dea = pd.Series(dif).ewm(span=9, adjust=False).mean().values
    macd = (dif - dea) * 2

    # BOLL 布林带
    boll_mid = ma20
    boll_std = s_close.rolling(20).std().values
    boll_std = np.nan_to_num(boll_std, nan=0.01)
    boll_up = boll_mid + 2.0 * boll_std
    boll_low = boll_mid - 2.0 * boll_std
    boll_bandwidth = (boll_up - boll_low) / np.maximum(0.01, boll_mid)

    # 连涨天数 (days)
    days = 0
    if cur_close > pre_close:
        for i in range(n - 1, -1, -1):
            if i > 0 and close[i] > close[i - 1]:
                days += 1
            else:
                break
    elif cur_close < pre_close:
        for i in range(n - 1, -1, -1):
            if i > 0 and close[i] < close[i - 1]:
                days -= 1
            else:
                break

    # ZIG 计算
    _, zig_days = calculate_zig(close)

    # 连续净流入 (consec_days, consec_amount)
    consec_days, consec_amount = _calculate_consecutive_flow(df, realtime_quote)

    # PE 近 3 年历史百分比 (若不足 750 日则基于全量已知历史)
    pe_percentile = round(float(np.mean(close < cur_close) * 100.0), 1)

    # 3. 5 大实战选股指标规则判定 (r1 ~ r5)
    r1 = 0
    if (
        ema10[-1] > ema20[-1] > ema30[-1]
        and ema10[-1] > ema10[-2]
        and ema20[-1] > ema20[-2]
        and ema30[-1] > ema30[-2]
    ):
        r1 = 1

    r2 = 0
    lookback_15 = min(15, n - 2)
    if lookback_15 >= 5:
        sub_c = close[-lookback_15 - 1 : -1]
        sub_o = open_p[-lookback_15 - 1 : -1]
        sub_l = low[-lookback_15 - 1 : -1]
        sub_v = vol[-lookback_15 - 1 : -1]
        
        found_breakout = False
        breakout_low = 0.0
        breakout_vol = 1.0

        for k in range(len(sub_c)):
            p_chg = (sub_c[k] / max(0.01, sub_o[k]) - 1.0) * 100.0
            avg_5v = np.mean(vol[max(0, n - 15 + k - 5) : max(1, n - 15 + k)])
            if p_chg >= 3.8 and sub_v[k] >= 1.6 * avg_5v:
                found_breakout = True
                breakout_low = float(sub_l[k])
                breakout_vol = float(sub_v[k])
                break

        if (
            found_breakout
            and cur_low >= breakout_low * 0.985
            and cur_vol < breakout_vol * 0.75
            and -3.5 <= cur_pct <= 2.5
        ):
            r2 = 1

    r3 = 0
    lookback_60 = min(60, n)
    amplitudes = (high[-lookback_60:] - low[-lookback_60:]) / np.maximum(0.01, close[-lookback_60:]) * 100.0
    avg_amp = float(np.mean(amplitudes))
    if avg_amp >= 1.8 or t_rate >= 0.8:
        r3 = 1

    r4 = 0
    if dif[-1] < 0.15 and dea[-1] < 0.15:
        lookback_12 = min(12, n)
        recent_c = close[-lookback_12:]
        recent_o = open_p[-lookback_12:]
        pos_candles = sum(1 for c, o in zip(recent_c, recent_o) if c >= o)
        cum_gain = float((recent_c[-1] / max(0.01, recent_c[0]) - 1.0) * 100.0)
        if pos_candles >= 6 and 0.0 <= cum_gain <= 15.0:
            r4 = 1

    r5 = 0
    cur_bw = float(boll_bandwidth[-1])
    lookback_12 = min(12, n)
    above_mid_days = sum(1 for i in range(n - lookback_12, n) if close[i] >= boll_mid[i])
    if (cur_bw < 0.15 or cur_bw <= float(np.min(boll_bandwidth[-min(60, n):])) * 1.35) and above_mid_days >= 8:
        r5 = 1

    matched_count = int(r1 + r2 + r3 + r4 + r5)

    # 4. 基于 pattern_recognition.py 的全量量化形态特征识别
    patterns_raw = detect_patterns(df)

    # 分类与打分 (上涨 +1, 下跌 -1, 中性 0)
    patterns_list = []
    for p_name in patterns_raw:
        if p_name in BULLISH_PATTERNS:
            patterns_list.append({"name": p_name, "score": 1, "type": "up"})
        elif p_name in BEARISH_PATTERNS:
            patterns_list.append({"name": p_name, "score": -1, "type": "down"})
        else:
            patterns_list.append({"name": p_name, "score": 0, "type": "neutral"})

    # 若已有具体战法形态，过滤纯兜底无特征提示词
    meaningful = [p for p in patterns_list if p["name"] not in {"震荡整理", "弱势整理", "震荡蓄势"}]
    if meaningful:
        patterns_list = meaningful

    pattern_score = int(sum(p["score"] for p in patterns_list))

    # 5. 评分模型计算 (buy_score & sell_score)
    buy_score = 0
    sell_score = 0

    # 买入加分
    if 5.0 <= t_rate <= 10.0 and 3.0 <= v_rate <= 5.0:
        buy_score += 3
    elif t_rate > 5.0 and 2.0 <= v_rate <= 3.0:
        buy_score += 2
    elif t_rate > 10.0 and v_rate > 5.0 and days <= 1:
        buy_score += 1
    elif v_rate > 1.5 and 1.0 <= t_rate <= 5.0:
        buy_score += 1

    if cur_pct > 2.0: buy_score += 1
    if dde_net > 0: buy_score += 1
    if days > 0: buy_score += 1

    if zig_days == 1:
        buy_score += 2
    elif zig_days > 1:
        buy_score += 1

    # 形态上涨信号纳入买入评分 (+1分)
    bull_cnt = sum(1 for p in patterns_list if p["score"] > 0)
    buy_score += bull_cnt

    # 形态下跌信号纳入卖出评分 (扣分/预警)
    bear_cnt = sum(1 for p in patterns_list if p["score"] < 0)
    sell_score += bear_cnt

    has_macd_bull = any(p["name"] in {"MACD金叉", "零上金叉", "零轴下金叉"} for p in patterns_list)
    is_super = bool(5.0 <= t_rate <= 10.0 and 2.0 <= v_rate <= 3.0 and cur_pct > 4.0 and has_macd_bull)
    is_pullback = bool(v_rate < 0.8 and t_rate < 3.0 and -3.0 <= cur_pct <= 0.0 and zig_days == 1)
    is_holding = bool(v_rate < 1.0 and t_rate < 5.0 and days >= 3 and cur_pct > 1.0)
    is_golden = bool(5.0 <= t_rate <= 10.0 and 3.0 <= v_rate <= 5.0)
    is_startup = bool(t_rate > 5.0 and 2.0 <= v_rate <= 3.0)

    if is_super: buy_score += 2
    if is_pullback: buy_score += 2
    if is_holding: buy_score += 2

    star_buy = bool(is_super or is_pullback or is_holding or is_golden or is_startup)

    # 卖出加分
    is_climax = bool(v_rate > 4.0 and t_rate > 15.0 and cur_pct < 1.0)
    if is_climax: sell_score += 3

    is_escape = bool(t_rate > 10.0 and v_rate < 1.0)
    if is_escape: sell_score += 3

    is_distribute = bool(t_rate > 10.0 and v_rate > 5.0 and days > 2)
    if is_distribute: sell_score += 2

    if t_rate > 20.0:
        sell_score += 2
    elif t_rate > 15.0:
        sell_score += 1

    if v_rate > 3.0 and cur_pct < 1.0:
        sell_score += 2
    elif v_rate > 2.0 and cur_pct < -1.0:
        sell_score += 1

    if v_rate < 0.5 and t_rate < 0.5:
        sell_score += 1

    if dde_net < 0: sell_score += 1
    if days < 0: sell_score += 1

    if zig_days == -1:
        sell_score += 2
    elif zig_days < -1:
        sell_score += 1

    star_sell = bool(is_climax or is_escape or is_distribute)

    return {
        "record_date": str(rec_date),
        "stock_code": str(code),
        "stock_name": str(get_stock_name(code)),
        "close": float(cur_close),
        "pct": float(cur_pct),
        "open": float(cur_open),
        "high": float(cur_high),
        "low": float(cur_low),
        "amplitude": round(float((cur_high - cur_low) / max(0.01, pre_close) * 100.0), 2),
        "v_rate": float(v_rate),
        "t_rate": float(t_rate),
        "dde_net": float(dde_net),
        "dde_all": float(dde_all),
        "amount": float(amount),
        "days": int(days),
        "zig": int(zig_days),
        "buy_score": int(buy_score),
        "sell_score": int(sell_score),
        "star_buy": bool(star_buy),
        "star_sell": bool(star_sell),
        "r1": int(r1),
        "r2": int(r2),
        "r3": int(r3),
        "r4": int(r4),
        "r5": int(r5),
        "matched_count": int(matched_count),
        "patterns": patterns_list,
        "pattern_names": [p["name"] for p in patterns_list],
        "pattern_score": int(pattern_score),
        "mkt_capt": float(mkt_capt),
        "consec_days": int(consec_days),
        "consec_amount": float(consec_amount),
        "pe_percentile": float(pe_percentile),
        "board_code": "",
        "industry": "--",
        "ystz": 0.0,
        "sjltz": 0.0,
        "holders_num": 0,
        "holders_str": "--",
        "holder_ratio": 0.0,
        "holder_focus": "--",
        "holders_changes": [],
    }


def fetch_stock_financials(code: str) -> Dict[str, Any]:
    """
    获取近 8 期财报及诊断指标。
    第一获取接口：从 easy_tdx 原生接口（SinaClient 8期报表 + TDX 每股净资产）获取；
    若获取失败或数据为空，再从外部接口（东方财富等）回退抓取。
    """
    clean_code = code.strip().upper().replace("SH", "").replace("SZ", "").replace("BJ", "")
    pfx = _get_market_prefix(clean_code)
    cache_key = f"{pfx}{clean_code}"
    now = time.time()

    if cache_key in _FINA_CACHE:
        ts, data = _FINA_CACHE[cache_key]
        if (now - ts < 3600) and data.get("peers_data") and len(data["peers_data"]) > 0 and data.get("holders_data"):
            return data

    fina_list = []
    peers_list = []
    industry = "通用行业"

    # 1. 第一获取接口：easy_tdx 内置 SinaClient 8 期财报
    try:
        sc = SinaClient(timeout=3.0)
        df_sina = sc.get_financial_report(clean_code, report_type="lrb", num=8)

        # 从 easy_tdx 原生 TDX 获取每股净资产以计算 ROE
        nav = 0.0
        try:
            cli = _TDX_POOL.acquire()
            df_tdx = cli.get_finance_info(_get_market(clean_code), clean_code)
            _TDX_POOL.release(cli, success=True)
            if df_tdx is not None and not df_tdx.empty:
                nav = float(df_tdx.iloc[0].get("meigujing_zichan") or 0.0)
        except Exception:
            pass

        if df_sina is not None and not df_sina.empty:
            for _, r in df_sina.iterrows():
                rep_date = str(r.get("报告期") or "")[:10]
                qdate = rep_date
                rev = float(r.get("营业总收入") or r.get("营业收入") or 0.0)
                np_val = float(r.get("归属于母公司所有者的净利润") or r.get("净利润") or 0.0)
                ystz = float(r.get("营业总收入_同比") or r.get("营业收入_同比") or 0.0) * 100.0
                sjltz = float(r.get("归属于母公司所有者的净利润_同比") or r.get("净利润_同比") or 0.0) * 100.0
                eps = float(r.get("基本每股收益") or 0.0)
                roe = round((eps / nav) * 100.0, 2) if nav > 0 and eps != 0 else 0.0

                fina_list.append({
                    "record_date": str(rep_date),
                    "qdate": str(qdate),
                    "total_operate_income": float(rev),
                    "parent_netprofit": float(np_val),
                    "weightavg_roe": float(roe),
                    "ystz": float(round(ystz, 2)),
                    "sjltz": float(round(sjltz, 2)),
                    "xsmll": 0.0,
                    "basic_eps": float(round(eps, 3)),
                })
    except Exception as e:
        logger.debug(f"easy_tdx financial interface failed for {clean_code}: {e}")

    # 2. 第二获取接口：若 easy_tdx 接口获取失败或为空，回退到东方财富抓取
    if not fina_list:
        try:
            url = f"https://emweb.securities.eastmoney.com/PC_HSF10/NewFinanceAnalysis/ZYZBAjaxNew?type=0&code={pfx}{clean_code}"
            req = urllib.request.Request(url, headers=_DEFAULT_HEADERS)
            with urllib.request.urlopen(req, timeout=4) as resp:
                raw_bytes = resp.read()
                if raw_bytes[:2] == b"\x1f\x8b":
                    raw = gzip.decompress(raw_bytes).decode("utf-8", errors="replace")
                else:
                    raw = raw_bytes.decode("utf-8", errors="replace")
                data_json = json.loads(raw).get("data", [])
                for item in data_json[:8]:
                    rep_date = str(item.get("REPORT_DATE", ""))[:10]
                    qdate = str(item.get("REPORT_DATE_NAME") or rep_date)
                    rev = float(item.get("TOTALOPERATEREVE") or 0.0)
                    np_val = float(item.get("PARENTNETPROFIT") or 0.0)
                    roe = float(item.get("ROEJQ") or 0.0)
                    ystz = float(item.get("TOTALOPERATEREVETZ") or 0.0)
                    sjltz = float(item.get("PARENTNETPROFITTZ") or 0.0)
                    xsmll = float(item.get("XSMLL") or 0.0) if item.get("XSMLL") is not None else 0.0
                    eps = float(item.get("EPSJB") or 0.0)

                    fina_list.append({
                        "record_date": str(rep_date),
                        "qdate": str(qdate),
                        "total_operate_income": float(rev),
                        "parent_netprofit": float(np_val),
                        "weightavg_roe": float(round(roe, 2)),
                        "ystz": float(round(ystz, 2)),
                        "sjltz": float(round(sjltz, 2)),
                        "xsmll": float(round(xsmll, 2)),
                        "basic_eps": float(round(eps, 3)),
                    })
        except Exception as e:
            logger.debug(f"Failed to fetch EastMoney fina for {clean_code}: {e}")

    # 获取股东人数及历史集中度变动
    holders_info = fetch_stock_holders(clean_code)

    # 获取同行业横向对比与所属行业
    industry, peers_list = fetch_stock_peers_data(clean_code, fallback_industry=industry)

    # 智能诊断文本生成 (传入 holders_info 以在顶部报告条显示股东人数)
    analysis_html = _generate_fina_diagnosis(clean_code, get_stock_name(clean_code), industry, fina_list, holders_info=holders_info)

    result = {
        "success": True,
        "stock_code": str(clean_code),
        "stock_name": str(get_stock_name(clean_code)),
        "industry": str(industry),
        "fina_data": fina_list,
        "peers_data": peers_list,
        "holders_data": holders_info,
        "analysis_html": str(analysis_html),
        "model_name": "StockQuant 智能投研系统",
    }
    _FINA_CACHE[cache_key] = (now, result)
    return result


_PE_PERCENTILE_CACHE: Tuple[float, Dict[str, float]] = (0.0, {})


def _get_universe_pe_map() -> Dict[str, float]:
    """获取全市场最近的 PE(3年分位) 映射表 (基于 universe 缓存)。"""
    global _PE_PERCENTILE_CACHE
    now = time.time()
    if _PE_PERCENTILE_CACHE[1] and (now - _PE_PERCENTILE_CACHE[0] < 600):
        return _PE_PERCENTILE_CACHE[1]

    import glob
    pe_map: Dict[str, float] = {}
    cache_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "data", "trading_system_cache"))
    pattern = os.path.join(cache_dir, "universe_all_*.json")
    files = sorted(glob.glob(pattern))
    if not files:
        pattern2 = os.path.join(cache_dir, "universe_*.json")
        files = sorted(glob.glob(pattern2))

    if files:
        latest_file = files[-1]
        try:
            with open(latest_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                for item in data:
                    c = str(item.get("stock_code", "")).strip()
                    p = item.get("pe_percentile")
                    if c and p is not None:
                        pe_map[c] = float(p)
            _PE_PERCENTILE_CACHE = (now, pe_map)
        except Exception as e:
            logger.debug(f"Failed to load universe pe map from {latest_file}: {e}")

    return pe_map


def fetch_stock_peers_data(clean_code: str, fallback_industry: str = "通用行业") -> Tuple[str, List[Dict[str, Any]]]:
    """
    获取目标个股所属行业及同行业同报告期龙头横向对比数据。
    基于东方财富权威行业与财报数据中心（RPT_LICO_FN_CPD）。
    包含历史 3 年 PE 百分位（PE(3年分位)）。
    """
    peers_list: List[Dict[str, Any]] = []
    industry = fallback_industry

    # 尝试读取本地股票的板块名称作为基础
    try:
        from easy_tdx.web.routers.quotes import _resolve_stock_board_info
        b_info = _resolve_stock_board_info(clean_code)
        if b_info and b_info.get("board_name") and b_info["board_name"] != "--":
            industry = str(b_info["board_name"])
    except Exception:
        pass

    pe_map = _get_universe_pe_map()
    target_pe = pe_map.get(clean_code)
    if target_pe is None:
        try:
            df_t = fetch_security_kline(clean_code, count=750)
            if df_t is not None and len(df_t) >= 30:
                c_v = df_t["close"].values.astype(float)
                target_pe = round(float(np.mean(c_v < float(c_v[-1])) * 100.0), 1)
        except Exception:
            pass

    try:
        url_t = (
            f"https://datacenter-web.eastmoney.com/api/data/v1/get?"
            f"reportName=RPT_LICO_FN_CPD&columns=ALL"
            f"&filter=(SECURITY_CODE%3D%22{clean_code}%22)"
            f"&sortTypes=-1&sortColumns=REPORTDATE&pageSize=1"
        )
        req = urllib.request.Request(url_t, headers=_DEFAULT_HEADERS)
        with urllib.request.urlopen(req, timeout=4.5) as resp:
            raw = resp.read()
            if raw[:2] == b"\x1f\x8b":
                raw = gzip.decompress(raw)
            d = json.loads(raw.decode("utf-8", errors="ignore"))
            items = d.get("result", {}).get("data", [])
            if not items:
                return industry, []
            target = items[0]

        b_code = target.get("BOARD_CODE")
        em_bname = target.get("BOARD_NAME") or target.get("PUBLISHNAME")
        rep_date = target.get("REPORTDATE")
        target_name = target.get("SECURITY_NAME_ABBR") or get_stock_name(clean_code)

        # 行业名称判定：优先保留用户熟知的本地细分行业（如 PCB），若无则采用东财行业名
        if industry == "通用行业" and em_bname:
            industry = str(em_bname)

        if not b_code or not rep_date:
            return industry, []

        filter_str = f'(BOARD_CODE="{b_code}")(REPORTDATE=\'{rep_date}\')'
        url_p = (
            f"https://datacenter-web.eastmoney.com/api/data/v1/get?"
            f"reportName=RPT_LICO_FN_CPD&columns=ALL"
            f"&filter={urllib.parse.quote(filter_str)}"
            f"&sortTypes=-1&sortColumns=TOTAL_OPERATE_INCOME"
            f"&pageNumber=1&pageSize=500"
        )
        req2 = urllib.request.Request(url_p, headers=_DEFAULT_HEADERS)
        with urllib.request.urlopen(req2, timeout=5.0) as resp2:
            raw2 = resp2.read()
            if raw2[:2] == b"\x1f\x8b":
                raw2 = gzip.decompress(raw2)
            d2 = json.loads(raw2.decode("utf-8", errors="ignore"))
            peer_items = d2.get("result", {}).get("data", [])

        # 全量包含同一行业的所有股票（不进行截断，让用户可纵览全行业排位）
        has_target = False

        for it in peer_items:
            c = str(it.get("SECURITY_CODE", ""))
            is_tgt = (c == clean_code)
            if is_tgt:
                has_target = True
            pe_val = target_pe if is_tgt else pe_map.get(c)
            peers_list.append({
                "code": c,
                "name": str(it.get("SECURITY_NAME_ABBR") or get_stock_name(c)),
                "qdate": str(it.get("QDATE") or target.get("QDATE") or "--"),
                "total_operate_income": float(it.get("TOTAL_OPERATE_INCOME") or 0.0),
                "ystz": round(float(it["YSTZ"]), 2) if it.get("YSTZ") is not None else None,
                "parent_netprofit": float(it.get("PARENT_NETPROFIT") or 0.0),
                "sjltz": round(float(it["SJLTZ"]), 2) if it.get("SJLTZ") is not None else None,
                "weightavg_roe": round(float(it["WEIGHTAVG_ROE"]), 2) if it.get("WEIGHTAVG_ROE") is not None else None,
                "xsmll": round(float(it["XSMLL"]), 2) if it.get("XSMLL") is not None else None,
                "pe_percentile": pe_val,
                "is_target": is_tgt,
            })

        # 若目标股票不在同行业已披露名单中，把目标股票自身补充在末尾
        if not has_target:
            peers_list.append({
                "code": clean_code,
                "name": str(target.get("SECURITY_NAME_ABBR") or target_name),
                "qdate": str(target.get("QDATE") or "--"),
                "total_operate_income": float(target.get("TOTAL_OPERATE_INCOME") or 0.0),
                "ystz": round(float(target["YSTZ"]), 2) if target.get("YSTZ") is not None else None,
                "parent_netprofit": float(target.get("PARENT_NETPROFIT") or 0.0),
                "sjltz": round(float(target["SJLTZ"]), 2) if target.get("SJLTZ") is not None else None,
                "weightavg_roe": round(float(target["WEIGHTAVG_ROE"]), 2) if target.get("WEIGHTAVG_ROE") is not None else None,
                "xsmll": round(float(target["XSMLL"]), 2) if target.get("XSMLL") is not None else None,
                "pe_percentile": target_pe,
                "is_target": True,
            })

    except Exception as e:
        logger.debug(f"Failed to fetch stock peers for {clean_code}: {e}")

    return industry, peers_list


def _generate_fina_diagnosis(
    code: str,
    name: str,
    industry: str,
    fina_data: List[Dict[str, Any]],
    holders_info: Optional[Dict[str, Any]] = None,
) -> str:
    """基于财务报表与核心基本面指标的多维度量化智能诊断算法（4大维度：成长动力、资本回报、持续性、策略映射）。"""
    if not fina_data:
        return f"""
        <div class="py-12 text-center text-slate-500 dark:text-slate-400 space-y-2">
            <div class="text-2xl">📋</div>
            <div class="text-sm font-medium">暂未获取到 {name} ({code}) 的历史财报数据</div>
            <div class="text-xs text-slate-400 dark:text-slate-500">建议在交易日盘后或更新季报后重新诊断</div>
        </div>
        """

    latest = fina_data[0]
    qdate = latest.get("qdate", latest.get("record_date", "最新报告期"))
    rev = latest.get("total_operate_income", 0.0) or 0.0
    rev_yi = rev / 1e8
    np_val = latest.get("parent_netprofit", 0.0) or 0.0
    np_yi = np_val / 1e8
    roe = float(latest.get("weightavg_roe") or 0.0)
    ystz = float(latest.get("ystz") or 0.0)
    sjltz = float(latest.get("sjltz") or 0.0)
    xsmll = float(latest.get("xsmll") or 0.0)
    eps = float(latest.get("basic_eps") or 0.0)

    # 1. 维度一：成长动力与经营杠杆评级 (Growth Dimension, 0 ~ 35分)
    growth_score = 15  # 基准分
    if ystz > 25: growth_score += 10
    elif ystz > 10: growth_score += 7
    elif ystz > 0: growth_score += 3
    elif ystz > -10: growth_score -= 5
    else: growth_score -= 10

    if sjltz > 35: growth_score += 10
    elif sjltz > 15: growth_score += 7
    elif sjltz > 0: growth_score += 3
    elif sjltz > -15: growth_score -= 5
    else: growth_score -= 10

    # 营收净利剪刀差 (经营杠杆)
    leverage = sjltz - ystz
    if leverage > 5:
        leverage_desc = "净利润增速显著超越营收增速，经营杠杆与规模效应凸显，盈利空间良性释放。"
        growth_score += 5
    elif leverage >= -5:
        leverage_desc = "营收与净利润保持同频扩张，处于健康扩张稳态区间。"
    else:
        leverage_desc = "净利润增速滞后于营收增速（增收不增利），提示需留意期间费用、成本上升或资产减值侵蚀。"
        growth_score -= 5

    # 2. 维度二：资本回报与护城河壁垒 (Quality Dimension, 0 ~ 30分)
    quality_score = 15
    if roe >= 15:
        quality_score += 10
        roe_desc = "巴菲特级顶级护城河 (≥15%)"
    elif roe >= 8:
        quality_score += 6
        roe_desc = "良性稳健回报 (8%~15%)"
    elif roe >= 3:
        quality_score += 2
        roe_desc = "中等平稳回报 (3%~8%)"
    elif roe > 0:
        quality_score -= 3
        roe_desc = "回报偏低 (0%~3%)"
    else:
        quality_score -= 8
        roe_desc = "资本回报为负 (亏损)"

    if xsmll >= 35: quality_score += 5
    elif xsmll >= 15: quality_score += 2
    elif xsmll > 0 and xsmll < 10: quality_score -= 2

    # 3. 维度三：多期时序持续性检验 (Consistency Dimension, 0 ~ 20分)
    consistency_score = 10
    pos_streak = 0
    recent_4 = fina_data[:4]
    for p in recent_4:
        p_sjltz = float(p.get("sjltz") or 0.0)
        if p_sjltz > 0:
            pos_streak += 1
    if pos_streak >= 4:
        consistency_score += 10
        streak_desc = f"近 4 期财报净利润保持连续正增长 ({pos_streak}/4 期)，盈利持续性卓越。"
    elif pos_streak >= 2:
        consistency_score += 5
        streak_desc = f"近 4 期财报中有 {pos_streak} 期净利正增长，中短期盈利处于上升修复期。"
    else:
        consistency_score -= 5
        streak_desc = f"近 4 期财报仅有 {pos_streak} 期正增长，业绩波动较大或处于周期承压期。"

    # 综合体检总分 (0 ~ 100)
    total_score = max(10, min(98, 15 + growth_score + quality_score + consistency_score))

    # 4. 维度四：评级与量化策略映射 (Strategy Mapping)
    if total_score >= 85:
        level_tag = "🌟 五星卓越 · 核心白马"
        tag_class = "bg-rose-50 dark:bg-rose-950/50 text-rose-600 dark:text-rose-400 border border-rose-200 dark:border-rose-800"
        strategy_desc = "🟢 <strong>高景气白马成长标的</strong>：主营业务扩张与净利润释放高度共振，资本回报处于顶级梯队。若叠加技术面量价回踩均线或 ZIG 翻红，为胜率极高的波段底仓配置首选。"
    elif total_score >= 70:
        level_tag = "📈 四星优良 · 景气扩张"
        tag_class = "bg-amber-50 dark:bg-amber-950/50 text-amber-700 dark:text-amber-400 border border-amber-200 dark:border-amber-800"
        strategy_desc = "🔵 <strong>稳健扩张型优质标的</strong>：整体财务态势良性，盈利能力处于健康扩张通道。适合逢技术面均线多头回踩均线或成交量地量缩量企稳时分批低吸。"
    elif total_score >= 55:
        level_tag = "⚖️ 三星中性 · 周期平衡"
        tag_class = "bg-blue-50 dark:bg-blue-950/50 text-blue-700 dark:text-blue-400 border border-blue-200 dark:border-blue-800"
        strategy_desc = "🟡 <strong>震荡/修复型周期标的</strong>：短期业绩处于修复或平稳期，建议严守技术面 ZIG 与 5 大指标均线共振信号，以右侧量价突破操盘为主，不宜盲目左侧重仓。"
    else:
        level_tag = "⚠️ 警示关注 · 承压收缩"
        tag_class = "bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 border border-slate-300 dark:border-slate-600"
        strategy_desc = "🔴 <strong>业绩承压收缩标的</strong>：受行业周期调整或成本费用侵蚀，净利润出现较大幅度下滑。建议保持观望，防范业绩雷与估值双杀，等待单季度拐点明确。"

    rev_trend = "强劲扩张" if ystz > 20 else ("稳健增长" if ystz > 0 else "收缩承压")
    profit_trend = "强劲爆发" if sjltz > 30 else ("良性上升" if sjltz > 0 else "显著承压下滑")
    ystz_color = "text-rose-600 dark:text-rose-400" if ystz > 0 else "text-emerald-600 dark:text-emerald-400"
    sjltz_color = "text-rose-600 dark:text-rose-400" if sjltz > 0 else "text-emerald-600 dark:text-emerald-400"

    # 生成眼部舒适、明暗自适应的高质感卡片布局
    holders_badge = ""
    if holders_info and holders_info.get("holders_str") and holders_info["holders_str"] != "--":
        h_str = holders_info["holders_str"]
        h_changes = holders_info.get("holders_changes") or []
        chg_text = ""
        if h_changes:
            r = h_changes[0].get("ratio")
            if r is not None:
                if r < 0:
                    chg_text = f'<span class="text-emerald-600 dark:text-emerald-400 font-semibold">{r:.2f}%</span>'
                elif r > 0:
                    chg_text = f'<span class="text-rose-600 dark:text-rose-400 font-semibold">+{r:.2f}%</span>'
        chg_span = f' (较上期 {chg_text})' if chg_text else ''
        holders_badge = f'<span class="text-xs text-slate-600 dark:text-slate-400 border-l border-slate-300 dark:border-slate-700 pl-2.5">股东人数: <strong class="text-slate-900 dark:text-slate-100 font-semibold font-mono">{h_str}</strong>{chg_span}</span>'

    html = f"""
    <div class="space-y-3.5 text-xs text-slate-700 dark:text-slate-300 font-sans">
        <!-- 顶部信息摘要胶囊 (温和护眼蓝灰色调) -->
        <div class="flex flex-wrap items-center justify-between gap-2 p-3.5 rounded-xl bg-slate-100/90 dark:bg-slate-800/80 border border-slate-200/90 dark:border-slate-700/80 text-slate-800 dark:text-slate-200 shadow-xs">
            <div class="flex flex-wrap items-center gap-2.5">
                <span class="px-2.5 py-1 rounded-lg text-xs font-bold bg-indigo-600 text-white dark:bg-cyan-500 dark:text-slate-950 shadow-xs">报告期: {qdate}</span>
                <span class="text-xs text-slate-600 dark:text-slate-400">所属行业: <strong class="text-slate-900 dark:text-slate-100 font-semibold">{industry}</strong></span>
                {holders_badge}
            </div>
            <div class="flex items-center space-x-2">
                <span class="text-xs text-slate-500 dark:text-slate-400">量化体检得分:</span>
                <span class="text-base font-extrabold text-indigo-600 dark:text-cyan-400 font-mono">{total_score} 分</span>
                <span class="px-2.5 py-0.5 rounded-full text-xs font-bold {tag_class}">{level_tag}</span>
            </div>
        </div>

        <!-- 卡片 1: 核心成长能力与经营杠杆 -->
        <div class="p-4 rounded-xl bg-white dark:bg-slate-800/90 border border-slate-200 dark:border-slate-700/80 shadow-xs space-y-2.5">
            <div class="flex items-center justify-between border-b border-slate-100 dark:border-slate-700/60 pb-2">
                <div class="flex items-center space-x-2 text-xs font-bold text-slate-900 dark:text-slate-100">
                    <span class="w-2 h-2 rounded-full bg-indigo-500 dark:bg-cyan-400"></span>
                    <span>1. 核心成长能力与经营杠杆 (Growth Dimension)</span>
                </div>
                <span class="text-[11px] font-mono text-slate-500 dark:text-slate-400">维度评级: {growth_score}/35分</span>
            </div>
            <ul class="space-y-1.5 pl-1 leading-relaxed">
                <li class="flex items-center justify-between">
                    <span class="text-slate-600 dark:text-slate-400">• 营业总收入：<strong class="text-slate-900 dark:text-slate-100">{rev_yi:.2f} 亿元</strong></span>
                    <span>同比增速 <strong class="{ystz_color} font-mono">{ystz:+.2f}%</strong>（态势: {rev_trend}）</span>
                </li>
                <li class="flex items-center justify-between">
                    <span class="text-slate-600 dark:text-slate-400">• 归母净利润：<strong class="text-slate-900 dark:text-slate-100">{np_yi:.2f} 亿元</strong></span>
                    <span>同比增速 <strong class="{sjltz_color} font-mono">{sjltz:+.2f}%</strong>（态势: {profit_trend}）</span>
                </li>
                <li class="pt-1 text-slate-600 dark:text-slate-400 border-t border-dashed border-slate-100 dark:border-slate-700/50">
                    • 经营杠杆剪刀差 (净利增速 - 营收增速 = <strong class="font-mono text-slate-800 dark:text-slate-200">{leverage:+.2f}%</strong>)：{leverage_desc}
                </li>
            </ul>
        </div>

        <!-- 卡片 2: 资本回报与护城河壁垒 -->
        <div class="p-4 rounded-xl bg-white dark:bg-slate-800/90 border border-slate-200 dark:border-slate-700/80 shadow-xs space-y-2.5">
            <div class="flex items-center justify-between border-b border-slate-100 dark:border-slate-700/60 pb-2">
                <div class="flex items-center space-x-2 text-xs font-bold text-slate-900 dark:text-slate-100">
                    <span class="w-2 h-2 rounded-full bg-emerald-500"></span>
                    <span>2. 资本回报与盈利质量 (Quality Dimension)</span>
                </div>
                <span class="text-[11px] font-mono text-slate-500 dark:text-slate-400">维度评级: {quality_score}/30分</span>
            </div>
            <ul class="space-y-1.5 pl-1 leading-relaxed">
                <li class="flex items-center justify-between">
                    <span class="text-slate-600 dark:text-slate-400">• 加权 ROE (最新期/年化)：<strong class="text-slate-900 dark:text-slate-100 font-mono">{roe:.2f}%</strong></span>
                    <span class="text-slate-500 dark:text-slate-400">资本回报率: <strong class="text-indigo-600 dark:text-cyan-400 font-medium">{roe_desc}</strong></span>
                </li>
                <li class="flex items-center justify-between">
                    <span class="text-slate-600 dark:text-slate-400">• 基本每股收益 (EPS)：<strong class="text-slate-900 dark:text-slate-100 font-mono">{eps:.3f} 元/股</strong></span>
                    <span class="text-slate-500 dark:text-slate-400">销售毛利率: <strong class="text-slate-900 dark:text-slate-100 font-mono">{xsmll:.2f}%</strong></span>
                </li>
            </ul>
        </div>

        <!-- 卡片 3: 连续季度趋势持续性 -->
        <div class="p-4 rounded-xl bg-white dark:bg-slate-800/90 border border-slate-200 dark:border-slate-700/80 shadow-xs space-y-2">
            <div class="flex items-center justify-between border-b border-slate-100 dark:border-slate-700/60 pb-2">
                <div class="flex items-center space-x-2 text-xs font-bold text-slate-900 dark:text-slate-100">
                    <span class="w-2 h-2 rounded-full bg-cyan-500"></span>
                    <span>3. 连续季度趋势持续性 (Consistency Dimension)</span>
                </div>
                <span class="text-[11px] font-mono text-slate-500 dark:text-slate-400">维度评级: {consistency_score}/20分</span>
            </div>
            <div class="text-slate-600 dark:text-slate-400 leading-relaxed">
                • {streak_desc}
            </div>
        </div>

        <!-- 卡片 4: 投研操盘策略建议 -->
        <div class="p-4 rounded-xl bg-white dark:bg-slate-800/90 border border-slate-200 dark:border-slate-700/80 shadow-xs space-y-2">
            <div class="flex items-center space-x-2 text-xs font-bold text-slate-900 dark:text-slate-100 border-b border-slate-100 dark:border-slate-700/60 pb-2">
                <span class="w-2 h-2 rounded-full bg-amber-500"></span>
                <span>4. 投研操盘策略指引 (Strategy Guidance)</span>
            </div>
            <div class="leading-relaxed text-slate-700 dark:text-slate-300">
                {strategy_desc}
            </div>
            <div class="pt-2 text-[11px] text-slate-500 dark:text-slate-400 border-t border-slate-100 dark:border-slate-700/50">
                ⚖️ <strong>量化风控提示</strong>：本模型基于已公开权威财报数据与多因子量化推演，股市有风险，入市需谨慎。
            </div>
        </div>
    </div>
    """
    return html


def evaluate_universe(
    symbols: Optional[List[str]] = None,
    max_workers: int = 24,
    universe_type: str = "core",
    force_refresh: bool = False,
) -> List[Dict[str, Any]]:
    """
    全市场或指定代码池的高速多线程批量量化评估（支持内存与磁盘双重高速缓存）。
    """
    is_custom_symbols = symbols is not None
    today_str = date.today().strftime("%Y%m%d")
    cache_f = os.path.join(_CACHE_DIR, f"universe_{universe_type}_{today_str}.json")
    mem_key = f"univ_{universe_type}"

    # 自选/自定义股票池启用30秒轻量缓存与秒级实时快照刷新
    if is_custom_symbols and not force_refresh and symbols:
        mem_key = f"univ_custom_{','.join(sorted(symbols))}"
        now = time.time()
        if mem_key in _MEM_CACHE:
            ts, cached_list = _MEM_CACHE[mem_key]
            if now - ts < 30.0:
                try:
                    quotes = fetch_realtime_pool_quotes(symbols)
                    q_map = {q["code"]: q for q in quotes}
                    updated_list = []
                    for item in cached_list:
                        s_copy = dict(item)
                        sc = s_copy.get("stock_code")
                        if sc in q_map:
                            q = q_map[sc]
                            s_copy["close"] = float(q.get("price") or q.get("close") or s_copy.get("close", 0))
                            s_copy["pct"] = float(q.get("change_pct") or s_copy.get("pct", 0))
                            s_copy["high"] = float(q.get("high") or s_copy.get("high", 0))
                            s_copy["low"] = float(q.get("low") or s_copy.get("low", 0))
                            pre_c = float(q.get("pre_close") or s_copy.get("close") or 1.0)
                            s_copy["amplitude"] = round(float((s_copy["high"] - s_copy["low"]) / max(0.01, pre_c) * 100.0), 2)
                            s_copy["amount"] = float(q.get("amount") or s_copy.get("amount", 0))
                            if "main_net_amount" in q:
                                s_copy["dde_net"] = float(q["main_net_amount"])
                            if "total_val_yi" in q and q["total_val_yi"]:
                                s_copy["mkt_capt"] = float(q["total_val_yi"]) * 1e8
                        updated_list.append(s_copy)
                    return updated_list
                except Exception:
                    return [dict(x) for x in cached_list]

    # 仅对标准股票池启用缓存
    if not is_custom_symbols and not force_refresh:
        now = time.time()
        # 1. 内存缓存 (优先极速命中)
        if mem_key in _MEM_CACHE:
            ts, cached_list = _MEM_CACHE[mem_key]
            if now - ts < 600.0:  # 10分钟内存缓存
                return [dict(x) for x in cached_list]
        # 2. 磁盘缓存 (当日有效，用户未勾选“从服务器获取最新数据”时优先秒级复用)
        if os.path.exists(cache_f):
            try:
                with open(cache_f, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list) and len(data) > 0:
                        _MEM_CACHE[mem_key] = (now, data)
                        logger.info(f"Loaded {len(data)} stocks from today cache: {cache_f}")
                        return data
            except Exception as e:
                logger.warning(f"Failed to read cache {cache_f}: {e}")


    if not symbols:
        symbols = get_universe_symbols(universe_type)
        if not symbols:
            symbols = CORE_UNIVERSE

    # 批量获取快照与资金流
    quotes = fetch_realtime_pool_quotes(symbols)
    q_map = {q["code"]: q for q in quotes}

    results: List[Dict[str, Any]] = []

    def _worker(s: str):
        try:
            df = fetch_security_kline(s, count=750)
            if df is not None and not df.empty and len(df) >= 20:
                res = evaluate_kline_strategy(s, df, q_map.get(s))
                if res:
                    # 1. 板块代码与行业名称
                    try:
                        from easy_tdx.web.routers.quotes import _resolve_stock_board_info
                        b_info = _resolve_stock_board_info(s)
                        if b_info and b_info.get("board_name") and b_info["board_name"] != "--":
                            res["board_code"] = str(b_info.get("board_code") or "")
                            res["industry"] = str(b_info["board_name"])
                        else:
                            res["board_code"] = ""
                            res["industry"] = str(q_map.get(s, {}).get("board_name") or "--")
                    except Exception:
                        res["board_code"] = ""
                        res["industry"] = str(q_map.get(s, {}).get("board_name") or "--")

                    # 2. 财务营收/净利同比 (近一期)
                    try:
                        fina = fetch_stock_financials(s)
                        latest_f = fina.get("fina_data", [{}])[0] if fina.get("fina_data") else {}
                        res["ystz"] = float(latest_f.get("ystz", 0.0))
                        res["sjltz"] = float(latest_f.get("sjltz", 0.0))
                    except Exception:
                        res["ystz"] = 0.0
                        res["sjltz"] = 0.0

                    # 3. 股东户数与集中度
                    try:
                        h_info = fetch_stock_holders(s)
                        res["holders_num"] = int(h_info.get("holders_num", 0))
                        res["holders_str"] = str(h_info.get("holders_str", "--"))
                        res["holder_ratio"] = float(h_info.get("holder_ratio", 0.0))
                        res["holder_focus"] = str(h_info.get("holder_focus", "--"))
                        res["holders_changes"] = list(h_info.get("holders_changes", []))
                    except Exception:
                        res["holders_num"] = 0
                        res["holders_str"] = "--"
                        res["holder_ratio"] = 0.0
                        res["holder_focus"] = "--"
                        res["holders_changes"] = []

                    return res
        except Exception as e:
            logger.debug(f"Worker failed for {s}: {e}")
        return None

    total_syms = len(symbols)
    _EVAL_PROGRESS[universe_type] = {
        "status": "running",
        "total": total_syms,
        "completed": 0,
        "pct": 0.0,
        "stock": "正在初始化扫描...",
    }

    done_cnt = 0
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_worker, s) for s in symbols]
        for f in as_completed(futures):
            r = f.result()
            if r:
                results.append(r)
            done_cnt += 1
            s_name = r.get("stock_name", "") if r else ""
            _EVAL_PROGRESS[universe_type] = {
                "status": "running",
                "total": total_syms,
                "completed": done_cnt,
                "pct": round(done_cnt / max(1, total_syms) * 100, 1),
                "stock": s_name,
            }

    _EVAL_PROGRESS[universe_type] = {
        "status": "done",
        "total": total_syms,
        "completed": total_syms,
        "pct": 100.0,
        "stock": "计算完成",
    }

    # 写入缓存
    if not is_custom_symbols and results:
        try:
            _MEM_CACHE[mem_key] = (time.time(), results)
            with open(cache_f, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save universe cache: {e}")
    elif is_custom_symbols and results and symbols:
        mem_key = f"univ_custom_{','.join(sorted(symbols))}"
        _MEM_CACHE[mem_key] = (time.time(), results)

    return results


def evaluate_stock_history(code: str, days_count: int = 60) -> List[Dict[str, Any]]:
    """
    单只股票历史多日信号与打分变迁回溯。
    """
    clean_code = code.strip().upper().replace("SH", "").replace("SZ", "").replace("BJ", "")
    df = fetch_security_kline(clean_code, count=days_count + 60)
    if df is None or len(df) < 30:
        return []

    history = []
    start_idx = max(30, len(df) - days_count)
    for end_idx in range(len(df), start_idx, -1):
        sub_df = df.iloc[:end_idx].copy().reset_index(drop=True)
        rec = evaluate_kline_strategy(clean_code, sub_df)
        if rec:
            history.append(rec)

    return history
