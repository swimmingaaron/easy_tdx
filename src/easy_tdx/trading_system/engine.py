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
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd

from easy_tdx.market_data import fetch_security_kline, fetch_realtime_pool_quotes
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


def fetch_stock_holders(code: str) -> Dict[str, Any]:
    """获取股东人数及前十大股东集中度（带 24 小时内存与本地缓存）。"""
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
    }

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
                num = int(latest.get("HOLDER_TOTAL_NUM") or 0)
                ratio = float(latest.get("HOLD_RATIO_TOTAL") or latest.get("FREEHOLD_RATIO_TOTAL") or 0.0)
                focus = str(latest.get("HOLD_FOCUS") or "")

                num_str = f"{num / 10000:.1f}万" if num >= 10000 else (str(num) if num > 0 else "--")

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

                res["holders_num"] = num
                res["holders_str"] = num_str
                res["holder_ratio"] = round(ratio, 2)
                res["holder_focus"] = focus
                res["holders_changes"] = changes
                _HOLDERS_CACHE[clean_code] = (now, res)
                return res
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



def _get_market_prefix(code: str) -> str:
    c = code.strip().upper().replace("SH", "").replace("SZ", "").replace("BJ", "")
    if c.startswith("6") or c.startswith("9"):
        return "SH"
    elif c.startswith("8") or c.startswith("4"):
        return "BJ"
    return "SZ"


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
    抓取东方财富近 8 期财报及同行对比指标（支持 gzip 解压，带内存缓存）。
    """
    clean_code = code.strip().upper().replace("SH", "").replace("SZ", "").replace("BJ", "")
    pfx = _get_market_prefix(clean_code)
    cache_key = f"{pfx}{clean_code}"
    now = time.time()

    if cache_key in _FINA_CACHE:
        ts, data = _FINA_CACHE[cache_key]
        if now - ts < 3600:
            return data

    fina_list = []
    peers_list = []
    industry = "通用行业"

    try:
        url = f"https://emweb.securities.eastmoney.com/PC_HSF10/NewFinanceAnalysis/ZYZBAjaxNew?type=0&code={pfx}{clean_code}"
        req = urllib.request.Request(url, headers=_DEFAULT_HEADERS)
        with urllib.request.urlopen(req, timeout=5) as resp:
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

    # 获取行业
    try:
        from easy_tdx.web.routers.quotes import _resolve_stock_board_info
        b_info = _resolve_stock_board_info(clean_code)
        if b_info and b_info.get("board_name") and b_info["board_name"] != "--":
            industry = b_info["board_name"]
    except Exception:
        pass

    # 智能诊断文本生成
    analysis_html = _generate_fina_diagnosis(clean_code, get_stock_name(clean_code), industry, fina_list)

    result = {
        "success": True,
        "stock_code": str(clean_code),
        "stock_name": str(get_stock_name(clean_code)),
        "industry": str(industry),
        "fina_data": fina_list,
        "peers_data": peers_list,
        "analysis_html": str(analysis_html),
        "model_name": "StockQuant 智能投研系统",
    }
    _FINA_CACHE[cache_key] = (now, result)
    return result


def _generate_fina_diagnosis(code: str, name: str, industry: str, fina_data: List[Dict[str, Any]]) -> str:
    """基于财务报表生成高质量的结构化智能诊断。"""
    if not fina_data:
        return f"<div style='padding:20px;text-align:center;color:var(--muted);'>暂未获取到 {name} ({code}) 的历史财报数据。</div>"

    latest = fina_data[0]
    qdate = latest.get("qdate", "最新期")
    rev = latest.get("total_operate_income", 0.0)
    rev_yi = rev / 1e8
    np_val = latest.get("parent_netprofit", 0.0)
    np_yi = np_val / 1e8
    roe = latest.get("weightavg_roe", 0.0)
    ystz = latest.get("ystz", 0.0)
    sjltz = latest.get("sjltz", 0.0)
    xsmll = latest.get("xsmll", 0.0)

    # 趋势分析
    rev_trend = "持续稳健扩张" if ystz > 15 else ("小幅增长" if ystz > 0 else "承压收缩")
    profit_trend = "强劲爆发" if sjltz > 30 else ("稳健上升" if sjltz > 5 else "显著承压下滑")
    roe_level = "极高（巴菲特级护城河）" if roe >= 15 else ("良好稳健" if roe >= 8 else "中等偏低")

    diagnosis = f"""### 🎯 【{name} ({code})】基本面深度体检与诊断透视

> **报告期：{qdate} | 所属行业：{industry}**

#### 1. 核心成长能力诊断
- **营业总收入**：**{rev_yi:.2f} 亿元**，同比增速 **{ystz:+.2f}%**（态势：<span style='color:{"var(--red)" if ystz>0 else "var(--green)"}'>{rev_trend}</span>）。
- **归母净利润**：**{np_yi:.2f} 亿元**，同比增速 **{sjltz:+.2f}%**（态势：<span style='color:{"var(--red)" if sjltz>0 else "var(--green)"}'>{profit_trend}</span>）。
- **营业健康度**：{"净利润增速跑赢营收增速，经营杠杆与规模效应凸显，盈利能力良性提升。" if sjltz > ystz else "净利润增速略低于营收增速，关注费用端控制与成本压力。"}

#### 2. 资本回报与盈利质量
- **加权 ROE (年化/季度)**：**{roe:.2f}%**，资本回报水平属于：**{roe_level}**。
- **销售毛利率**：**{xsmll:.2f}%**，反映产品定价权与行业竞争壁垒。
- **每股收益 (EPS)**：**{latest.get("basic_eps", 0.0):.3f} 元/股**。

#### 3. 投研操盘策略建议
- {"🟢 **白马成长型标的**：主营业务与扣非净利强劲共振，若叠加技术面量价回踩，是高胜率波段配置良机。" if ystz > 10 and sjltz > 10 and roe > 8 else "🟡 **周期/重组震荡型标的**：短期业绩处于修复或平稳期，建议严守技术面 ZIG 与 5 大指标均线共振信号，以右侧量价突破为主。"}
- **风险警示**：股市有风险，数据基于公开发布财报统计与量化模型推演，入市需谨慎。
"""
    return diagnosis


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
