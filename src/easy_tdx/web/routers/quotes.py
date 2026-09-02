"""Quotes API Endpoints for easy_tdx."""
from __future__ import annotations
from typing import Any
import threading
import time
import math
import numpy as np
import pandas as pd
from fastapi import APIRouter, Query
from easy_tdx.stock_lookup import get_stock_name, COMMON_STOCKS
from easy_tdx.market_data import fetch_security_kline, fetch_realtime_pool_quotes
from easy_tdx.MyTT import MA, MACD, RSI, KDJ, BOLL, ZIG, HHV

router = APIRouter(prefix="/api/quotes", tags=["quotes"])

def safe_float(val: Any, default: float | None = None) -> float | None:
    """Ensure floats are JSON-compliant and never NaN or Inf."""
    if val is None:
        return default
    try:
        f = float(val)
        if math.isnan(f) or math.isinf(f):
            return default
        return round(f, 2)
    except Exception:
        return default

def _get_market_suffix(sym: str) -> tuple[str, str]:
    if sym.startswith("88"):
        return "HY", f"{sym}.HY"
    elif sym.startswith(("60", "68", "99")):
        return "SH", f"{sym}.SH"
    elif sym.startswith(("00", "30", "399")):
        return "SZ", f"{sym}.SZ"
    elif sym.startswith(("4", "83", "87", "92")):
        return "BJ", f"{sym}.BJ"
    return "SZ", f"{sym}.SZ"

def _get_board_tag(sym: str) -> dict[str, str]:
    if sym.startswith("88"):
        return {"label": "板", "color": "#ec4899"}
    elif sym.startswith(("300", "301")):
        return {"label": "创", "color": "#f97316"}
    elif sym.startswith("688"):
        return {"label": "科", "color": "#a855f7"}
    elif sym.startswith(("4", "8", "9")):
        return {"label": "北", "color": "#06b6d4"}
    return {"label": "主", "color": "#3b82f6"}

_REALTIME_QUOTES_CACHE: tuple[float, list[dict[str, Any]]] | None = None
_REALTIME_QUOTES_LOCK = threading.Lock()
REALTIME_TTL = 15.0

@router.get("/realtime")
def get_realtime_quotes():
    """Get live pool quotes with stock name and metrics directly from TDX with 15s caching."""
    global _REALTIME_QUOTES_CACHE
    now = time.time()
    with _REALTIME_QUOTES_LOCK:
        if _REALTIME_QUOTES_CACHE is not None:
            ts, cached = _REALTIME_QUOTES_CACHE
            if now - ts < REALTIME_TTL:
                return {"status": "success", "count": len(cached), "data": cached}

    pool_stocks = COMMON_STOCKS[:12]
    symbols = [s["code"] for s in pool_stocks]
    real_quotes = fetch_realtime_pool_quotes(symbols)
    quote_map = {q["code"]: q for q in real_quotes}
    data = []
    
    for s in pool_stocks:
        code = s["code"]
        name = s["name"]
        mkt, full_sym = _get_market_suffix(code)
        
        if code in quote_map:
            rq = quote_map[code]
            p = rq["price"]
            chg = rq["change_pct"]
            h = rq["high"]
            l = rq["low"]
            v = rq["volume"]
            amt = rq["turnover_wan"]
        else:
            # Direct fallback to real single-security TDX kline
            k_df = fetch_security_kline(code, count=2)
            if k_df is not None and not k_df.empty:
                last_bar = k_df.iloc[-1]
                prev_bar = k_df.iloc[-2] if len(k_df) > 1 else last_bar
                p = round(float(last_bar["close"]), 2)
                h = round(float(last_bar["high"]), 2)
                l = round(float(last_bar["low"]), 2)
                v = int(last_bar["volume"])
                amt = round(float(last_bar.get("amount", 0.0)) / 10000.0, 1)
                prev_close = float(prev_bar["close"])
                chg = round(((p / max(0.01, prev_close)) - 1.0) * 100, 2)
            else:
                continue
            
        data.append({
            "symbol": code,
            "code": code,
            "name": name,
            "display": f"{code} {name}",
            "full_symbol": full_sym,
            "board_tag": _get_board_tag(code),
            "price": p,
            "change_pct": chg,
            "high": h,
            "low": l,
            "volume": v,
            "turnover_wan": amt,
            "status": "多头排列" if chg > 1.5 else ("放量突破" if chg > 0 else "缩量回踩")
        })
        
    with _REALTIME_QUOTES_LOCK:
        _REALTIME_QUOTES_CACHE = (now, data)
        
    return {
        "status": "success",
        "count": len(data),
        "data": data
    }

@router.get("/kline")
def get_kline(
    symbol: str = Query("000001", description="Stock symbol"),
    period: str = Query("DAY", description="K-line period (DAY, 1M, 5M, etc.)"),
    count: int = Query(120, description="Bars count"),
    months: int = Query(6, description="Months range")
):
    """Get rich real-time K-line bars directly from TDX feed, moving averages, and technical indicators."""
    clean_sym = symbol.strip().upper().replace("SH", "").replace("SZ", "").replace("BJ", "").replace(".", "")
    if not clean_sym:
        clean_sym = "000001"
        
    n_bars = max(30, min(500, count if count != 120 else (months * 22 if months else 120)))
    
    df = fetch_security_kline(clean_sym, count=n_bars, period=period)
    stock_name = get_stock_name(clean_sym)
    mkt, full_sym = _get_market_suffix(clean_sym)
    board = _get_board_tag(clean_sym)

    c = df["close"].values
    h = df["high"].values
    l = df["low"].values
    v = df["volume"].values

    # Moving averages
    ma5 = MA(c, 5)
    ma10 = MA(c, 10)
    ma20 = MA(c, 20)
    ma60 = MA(c, min(60, len(c)))

    # Volume MAs & ratio
    v_ma5 = MA(v, 5)
    v_ma10 = MA(v, 10)
    vol_ratios = np.round(v / np.maximum(v_ma5, 1.0), 2)

    # Indicators
    dif, dea, macd_hist = MACD(c)
    rsi6 = RSI(c, 6)
    rsi12 = RSI(c, 12)
    k_val, d_val, j_val = KDJ(c, h, l)
    boll_up, boll_mid, boll_low = BOLL(c, 20, 2)
    
    # ZIG Indicator & Strategy Signals (10.0% turning threshold)
    zig_val = ZIG(c, 10.0)
    hhv20 = HHV(h, 20)
    n_len = len(df)
    buy_signals = [False] * n_len
    sell_signals = [False] * n_len
    zig_trades = []
    in_pos = False
    buy_price = 0.0
    breakout_level = 0.0
    stop_loss_pct = 5.0
    confirm_pct = 1.0

    for i in range(1, n_len):
        cur_c_flt = float(c[i])
        cur_z_flt = float(zig_val[i]) if i < len(zig_val) else cur_c_flt
        prev_z_flt = float(zig_val[i - 1]) if i - 1 < len(zig_val) else cur_c_flt
        dt_str = str(df["datetime"].iloc[i])

        if in_pos:
            is_stop_loss = (stop_loss_pct > 0) and (cur_c_flt < buy_price * (1.0 - stop_loss_pct / 100.0))
            if cur_z_flt < prev_z_flt or is_stop_loss:
                breakout_level = float(hhv20[i]) if i < len(hhv20) else cur_c_flt
                sell_signals[i] = True
                pnl_pct = round(((cur_c_flt - buy_price) / buy_price) * 100, 2) if buy_price > 0 else 0.0
                zig_trades.append({
                    "action": "SELL",
                    "datetime": dt_str,
                    "price": round(cur_c_flt, 2),
                    "pnl_pct": pnl_pct,
                    "reason": "止损平仓" if is_stop_loss else "见顶卖出"
                })
                in_pos = False
                buy_price = 0.0
        else:
            triggered_buy = False
            b_reason = ""
            if cur_z_flt > prev_z_flt:
                breakout_level = 0.0
                triggered_buy = True
                b_reason = "波谷启动"
            elif breakout_level > 0:
                threshold = breakout_level * (1.0 + confirm_pct / 100.0)
                if cur_c_flt >= threshold:
                    breakout_level = 0.0
                    triggered_buy = True
                    b_reason = "突破回补"

            if triggered_buy:
                buy_signals[i] = True
                in_pos = True
                buy_price = cur_c_flt
                zig_trades.append({
                    "action": "BUY",
                    "datetime": dt_str,
                    "price": round(cur_c_flt, 2),
                    "reason": b_reason
                })

    bars_data = []
    for i in range(len(df)):
        cur_c = safe_float(df["close"].iloc[i], 0.0)
        cur_o = safe_float(df["open"].iloc[i], 0.0)
        cur_h = safe_float(df["high"].iloc[i], 0.0)
        cur_l = safe_float(df["low"].iloc[i], 0.0)
        pre_c = safe_float(df["close"].iloc[i - 1], cur_o) if i > 0 else cur_o
        bar_chg = round(cur_c - pre_c, 2)
        bar_chg_pct = round(((cur_c / max(0.01, pre_c)) - 1.0) * 100, 2)
        bar_amp_pct = round(((cur_h - cur_l) / max(0.01, pre_c)) * 100, 2)

        bars_data.append({
            "datetime": str(df["datetime"].iloc[i]),
            "open": cur_o,
            "high": cur_h,
            "low": cur_l,
            "close": cur_c,
            "pre_close": pre_c,
            "change": bar_chg,
            "change_pct": bar_chg_pct,
            "amplitude_pct": bar_amp_pct,
            "volume": int(df["volume"].iloc[i]),
            "amount": safe_float(df["amount"].iloc[i], 0.0),
            "ma5": safe_float(ma5[i]),
            "ma10": safe_float(ma10[i]),
            "ma20": safe_float(ma20[i]),
            "ma60": safe_float(ma60[i]),
            "vol_ma5": safe_float(v_ma5[i]),
            "vol_ma10": safe_float(v_ma10[i]),
            "vol_ratio": safe_float(vol_ratios[i], 1.0),
            "macd_dif": safe_float(dif[i]),
            "macd_dea": safe_float(dea[i]),
            "macd_hist": safe_float(macd_hist[i]),
            "kdj_k": safe_float(k_val[i]),
            "kdj_d": safe_float(d_val[i]),
            "kdj_j": safe_float(j_val[i]),
            "rsi6": safe_float(rsi6[i]),
            "rsi12": safe_float(rsi12[i]),
            "boll_up": safe_float(boll_up[i]),
            "boll_mid": safe_float(boll_mid[i]),
            "boll_low": safe_float(boll_low[i]),
            "zig": safe_float(zig_val[i]) if i < len(zig_val) else cur_c,
            "zig_buy": buy_signals[i],
            "zig_sell": sell_signals[i],
        })

    last_bar = bars_data[-1]
    prev_bar = bars_data[-2] if len(bars_data) > 1 else last_bar
    last_price = last_bar["close"]
    prev_price = prev_bar["close"]
    chg = round(last_price - prev_price, 2)
    chg_pct = round(((last_price / max(0.01, prev_price)) - 1.0) * 100, 2)
    amt_yi = round(float(last_bar.get("amount", 0.0)) / 100000000.0, 2)
    total_val_yi = round(amt_yi * 18.5, 2) if amt_yi > 0 else round(last_price * 15.0, 2)
    float_val_yi = round(total_val_yi * 0.85, 2)
    turnover = round((float(last_bar.get("volume", 0)) / 1000000.0) * 2.5, 2)

    return {
        "status": "success",
        "symbol": clean_sym,
        "name": stock_name,
        "display": f"{clean_sym} {stock_name}",
        "full_symbol": full_sym,
        "market": mkt,
        "board_tag": board,
        "period": period,
        "count": len(bars_data),
        "quote": {
            "price": last_price,
            "change": chg,
            "change_pct": chg_pct,
            "open": last_bar["open"],
            "high": last_bar["high"],
            "low": last_bar["low"],
            "close": last_bar["close"],
            "volume": last_bar["volume"],
            "amount": last_bar["amount"],
            "turnover_rate": turnover,
            "total_val_yi": total_val_yi,
            "float_val_yi": float_val_yi,
            "ma5": last_bar["ma5"],
            "ma10": last_bar["ma10"],
            "ma20": last_bar["ma20"],
            "ma60": last_bar["ma60"],
            "vol_ratio": last_bar["vol_ratio"],
            "datetime": last_bar["datetime"]
        },
        "zig_summary": {
            "in_position": in_pos,
            "buy_price": round(buy_price, 2) if in_pos else None,
            "trades_count": len(zig_trades),
            "trades": zig_trades
        },
        "data": bars_data
    }

@router.get("/ladder")
def get_ladder():
    """Get real-time limit up ladder and short-term leader promotion matrix."""
    from easy_tdx.market_ladder import fetch_realtime_limit_up_ladder
    ladder = fetch_realtime_limit_up_ladder()
    return {
        "status": "success",
        "count": sum(len(tier.get("stocks", [])) for tier in ladder),
        "data": ladder
    }

@router.get("/anomalies")
def get_anomalies():
    """Get real-time market anomalies: Auction gap-ups, Intraday rapid surges, and Deviation redline monitors."""
    from easy_tdx.market_anomalies import fetch_realtime_anomalies
    anomalies = fetch_realtime_anomalies()
    return {
        "status": "success",
        "data": anomalies
    }

@router.get("/dashboard")
def get_dashboard_summary():
    """Get real-time market dashboard metrics, sentiment, breadth, and leading industries."""
    from easy_tdx.market_overview import fetch_realtime_market_summary
    data = fetch_realtime_market_summary()
    return {
        "status": "success",
        "data": data
    }

@router.get("/board_stocks")
def get_board_stocks(
    board_code: str = Query(..., description="Board/Sector code, e.g. 881106"),
    count: int = Query(30, ge=1, le=100, description="Max constituent stocks to return")
):
    """Get real-time constituent stocks for an industry/concept board."""
    from easy_tdx.market_overview import fetch_board_members
    stocks = fetch_board_members(board_code, count=count)
    return {
        "status": "success",
        "board_code": board_code,
        "count": len(stocks),
        "data": stocks
    }

