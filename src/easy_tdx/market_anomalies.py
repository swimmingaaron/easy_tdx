"""Real-Time Market Anomaly Radar (异动雷达) Engine for A-Shares.

Powered 100% natively by easy_tdx:
1. 集合竞价高开抢筹与弱转强雷达 (Auction Anomalies & Weak-to-Strong)
2. 盘中放量急涨与主力大单雷达 (Intraday Surges & Main Capital Inflow)
3. 交易所异动偏离值合规红线监控 (Exchange Deviation Redline Monitor)
"""
from __future__ import annotations
import logging
import time
import datetime
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from easy_tdx.market_data import fetch_security_kline, fetch_realtime_pool_quotes
from easy_tdx.stock_lookup import get_stock_name
from easy_tdx.screener.universe import CORE_UNIVERSE

logger = logging.getLogger(__name__)

_ANOMALIES_CACHE: tuple[float, dict[str, list[dict[str, Any]]]] | None = None
CACHE_TTL_SEC = 15.0

# 核心监控候选池：行业领袖 + 活跃核心标的 + 高辨识度个股
HOT_RADAR_SEEDS = [
    "605577", "600108", "002403", "600865", "603162", "605580", "605398", 
    "000428", "002702", "000735", "000592", "003040", "601579", "002827", 
    "603123", "001366", "000560", "301151", "300413", "600227", "603269", 
    "003018", "002475", "600519", "300750", "601888", "002415", "600036",
    "000001", "300059", "601318", "000858", "600900", "601138", "300274"
]

def _calc_stock_deviation(code: str) -> dict[str, Any] | None:
    """Calculate exact 3-day exchange deviation limit usage from native daily K-lines."""
    try:
        df = fetch_security_kline(code, period="DAY", count=5)
        if df is not None and len(df) >= 3:
            c_now = float(df.iloc[-1]["close"])
            c_3d = float(df.iloc[-3]["close"])
            if c_3d > 0:
                cum_3d = round((c_now / c_3d - 1.0) * 100.0, 1)
                if code.startswith(("30", "68")):
                    threshold = 30.0
                    board_str = "创业板/科创板 (3日 30%)"
                elif code.startswith(("92", "8", "4")):
                    threshold = 40.0
                    board_str = "北交所 (3日 40%)"
                else:
                    threshold = 20.0
                    board_str = "主板 (3日 20%)"
                
                dev_pct = round((cum_3d / threshold) * 100.0, 1)
                is_warning = dev_pct >= 80.0
                name = get_stock_name(code)
                
                status_note = (
                    "【严重预警】已突破异动监管红线，谨防停牌核查与特停风险。"
                    if dev_pct >= 100.0
                    else (
                        "【临界预警】接近异动红线，谨防高位监管压单与主力分歧。"
                        if is_warning
                        else "距异动红线尚有一定合规缓冲空间。"
                    )
                )
                
                return {
                    "sym": code,
                    "code": code,
                    "name": name,
                    "price": f"{c_now:.2f}",
                    "chg": f"{cum_3d:+.2f}%",
                    "board": board_str,
                    "threshold": f"{threshold:.0f}%",
                    "cum_gain": f"3日涨幅 {cum_3d:+.1f}%",
                    "dev_ratio": f"偏离度 {dev_pct:.1f}%",
                    "dev_val": dev_pct,
                    "is_warning": is_warning,
                    "desc": f"3日累计涨幅 {cum_3d:+.1f}%，已达 {threshold:.0f}% 异动监管红线的 {dev_pct:.1f}%。{status_note}点击查看K线。"
                }
    except Exception as e:
        logger.debug(f"Failed to calculate deviation for {code}: {e}")
    return None

def _calc_intraday_speed(code: str) -> dict[str, Any]:
    """Calculate 5-minute price surge speed from native 1-minute K-lines."""
    try:
        df = fetch_security_kline(code, period="1M", count=25)
        if df is not None and len(df) >= 5:
            c_now = float(df.iloc[-1]["close"])
            c_5m = float(df.iloc[-5]["close"])
            if c_5m > 0:
                speed_pct = round((c_now / c_5m - 1.0) * 100.0, 2)
                dt_str = str(df.iloc[-1]["datetime"])
                t_str = dt_str.split(" ")[-1]
                if len(t_str) == 5:
                    t_str += ":00"
                return {"speed_pct": speed_pct, "time": t_str}
    except Exception as e:
        logger.debug(f"Failed to calculate intraday speed for {code}: {e}")
    return {"speed_pct": 0.0, "time": datetime.datetime.now().strftime("%H:%M:%S")}

def fetch_realtime_anomalies() -> dict[str, list[dict[str, Any]]]:
    """Fetch real-time market anomalies powered 100% by easy_tdx native socket & K-line data."""
    global _ANOMALIES_CACHE
    now = time.time()
    if _ANOMALIES_CACHE is not None:
        ts, cached_data = _ANOMALIES_CACHE
        if now - ts < CACHE_TTL_SEC:
            return cached_data

    auction_list: list[dict[str, Any]] = []
    intraday_list: list[dict[str, Any]] = []
    deviation_list: list[dict[str, Any]] = []

    # 1. Assemble comprehensive monitoring pool
    all_codes = list(dict.fromkeys(HOT_RADAR_SEEDS + CORE_UNIVERSE[:35]))

    # 2. Fetch real-time snapshot quotes via easy_tdx native protocol
    try:
        quotes = fetch_realtime_pool_quotes(all_codes)
    except Exception as e:
        logger.error(f"easy_tdx failed to fetch pool quotes for anomalies: {e}")
        quotes = []

    now_time_str = datetime.datetime.now().strftime("%H:%M:%S")

    # 3. Process Auction Anomalies (集合竞价高开抢筹 / 弱转强)
    for q in quotes:
        price = float(q.get("price") or 0.0)
        pre_close = float(q.get("pre_close") or price)
        open_p = float(q.get("open") or price)
        chg = float(q.get("change_pct") or 0.0)
        amt_yi = round(float(q.get("turnover_wan") or 0.0) / 10000.0, 2)
        code = str(q.get("code", "")).upper()
        name = get_stock_name(code)

        if price <= 0 or pre_close <= 0:
            continue

        open_gap = round(((open_p / pre_close) - 1.0) * 100.0, 2)

        # 集合竞价高开抢筹 / 弱转强判定
        if open_gap >= 1.5:
            if open_gap >= 5.0:
                tag = f"+{chg:.1f}% 竞价强开"
                desc = f"集合竞价顶格大幅高开 +{open_gap:.2f}%，开盘抢筹成交 {amt_yi:.2f} 亿元。点击查看实时K线。"
            elif open_gap >= 3.0:
                tag = f"+{chg:.1f}% 竞价抢筹"
                desc = f"早盘集合竞价主力抢筹高开 +{open_gap:.2f}%，开盘成交 {amt_yi:.2f} 亿元。点击查看实时K线。"
            else:
                tag = f"+{chg:.1f}% 弱转强"
                desc = f"超预期小幅高开 +{open_gap:.2f}% 弱转强，多头攻击意愿明确，成交 {amt_yi:.2f} 亿元。点击查看实时K线。"

            auction_list.append({
                "sym": code,
                "code": code,
                "name": name,
                "price": f"{price:.2f}",
                "chg": f"{chg:+.2f}%",
                "open_gap_val": open_gap,
                "open_gap": f"高开 +{open_gap:.2f}%",
                "tag": tag,
                "desc": desc
            })

    auction_list.sort(key=lambda x: x["open_gap_val"], reverse=True)

    # 4. Process Intraday Surges (盘中急涨放量 / 主力大单)
    surge_candidates = [
        q for q in quotes 
        if float(q.get("change_pct") or 0.0) >= 2.0 and float(q.get("turnover_wan") or 0.0) >= 3000
    ]
    # Sort primarily by main net inflow or price change
    surge_candidates.sort(
        key=lambda x: (float(x.get("main_net_amount") or 0.0), float(x.get("change_pct") or 0.0)), 
        reverse=True
    )

    top_surges = surge_candidates[:8]
    for q in top_surges:
        code = str(q.get("code", "")).upper()
        name = get_stock_name(code)
        price = float(q.get("price") or 0.0)
        chg = float(q.get("change_pct") or 0.0)
        amt_yi = round(float(q.get("turnover_wan") or 0.0) / 10000.0, 2)
        inflow_str = str(q.get("inflow_1d_str") or "0元")
        
        # Calculate real 5-min speed via 1M K-line
        speed_info = _calc_intraday_speed(code)
        s_pct = speed_info["speed_pct"]
        t_str = speed_info["time"]

        intraday_list.append({
            "sym": code,
            "code": code,
            "name": name,
            "price": f"{price:.2f}",
            "chg": f"{chg:+.2f}%",
            "time": t_str,
            "desc": f"主力资金净流入 {inflow_str}，5分钟急涨 +{s_pct:.1f}%，日内成交 {amt_yi:.2f} 亿元，多头买盘活跃。点击查看K线。"
        })

    # 5. Process Deviation Redline Monitors (交易所异动偏离值合规红线)
    # Select stocks with high positive momentum to evaluate deviation
    dev_candidates = [
        q["code"] for q in sorted(quotes, key=lambda x: float(x.get("change_pct") or 0.0), reverse=True)[:18]
    ]
    with ThreadPoolExecutor(max_workers=8) as executor:
        dev_results = list(executor.map(_calc_stock_deviation, dev_candidates))

    for d in dev_results:
        if d is not None and d["dev_val"] > 0:
            deviation_list.append(d)

    deviation_list.sort(key=lambda x: x["dev_val"], reverse=True)

    result = {
        "auction": auction_list[:6],
        "intraday": intraday_list[:6],
        "deviation": deviation_list[:6]
    }
    _ANOMALIES_CACHE = (now, result)
    return result
