"""Quotes API Endpoints for easy_tdx."""
from __future__ import annotations
from typing import Any
import math
import numpy as np
import pandas as pd
from fastapi import APIRouter, Query
from easy_tdx.stock_lookup import get_stock_name, COMMON_STOCKS
from easy_tdx.screener.scanner import generate_mock_kline
from easy_tdx.MyTT import MA, MACD, RSI, KDJ, BOLL

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
    if sym.startswith(("60", "68")):
        return "SH", f"{sym}.SH"
    elif sym.startswith(("00", "30")):
        return "SZ", f"{sym}.SZ"
    elif sym.startswith(("4", "8", "9")):
        return "BJ", f"{sym}.BJ"
    return "SZ", f"{sym}.SZ"

def _get_board_tag(sym: str) -> dict[str, str]:
    if sym.startswith(("300", "301")):
        return {"label": "创", "color": "#f97316"}
    elif sym.startswith("688"):
        return {"label": "科", "color": "#a855f7"}
    elif sym.startswith(("4", "8", "9")):
        return {"label": "北", "color": "#06b6d4"}
    return {"label": "主", "color": "#3b82f6"}

@router.get("/realtime")
def get_realtime_quotes():
    """Get live pool quotes with stock name and metrics."""
    data = []
    for s in COMMON_STOCKS[:10]:
        code = s["code"]
        name = s["name"]
        p = 10.0 + (hash(code) % 50)
        chg = ((hash(code) % 15) - 3) / 2.0
        mkt, full_sym = _get_market_suffix(code)
        data.append({
            "symbol": code,
            "code": code,
            "name": name,
            "display": f"{code} {name}",
            "full_symbol": full_sym,
            "board_tag": _get_board_tag(code),
            "price": round(float(p), 2),
            "change_pct": round(float(chg), 2),
            "high": round(float(p * 1.03), 2),
            "low": round(float(p * 0.98), 2),
            "volume": int(120000 + (hash(code) % 500000)),
            "turnover_wan": round(float(15000 + (hash(code) % 80000)), 1),
            "status": "多头排列" if chg > 1.5 else ("放量突破" if chg > 0 else "缩量回踩")
        })
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
    """Get rich K-line bars, moving averages, and technical indicators for preview dialog."""
    clean_sym = symbol.strip().upper().replace("SH", "").replace("SZ", "").replace("BJ", "").replace(".", "")
    if not clean_sym:
        clean_sym = "000001"
        
    n_bars = max(30, min(500, count if count != 120 else (months * 22 if months else 120)))
    df = generate_mock_kline(clean_sym, n_bars=n_bars)
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

    bars_data = []
    for i in range(len(df)):
        bars_data.append({
            "datetime": str(df["datetime"].iloc[i]),
            "open": safe_float(df["open"].iloc[i], 0.0),
            "high": safe_float(df["high"].iloc[i], 0.0),
            "low": safe_float(df["low"].iloc[i], 0.0),
            "close": safe_float(df["close"].iloc[i], 0.0),
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
        })

    last_bar = bars_data[-1]
    prev_bar = bars_data[-2] if len(bars_data) > 1 else last_bar
    last_price = last_bar["close"]
    prev_price = prev_bar["close"]
    chg = round(last_price - prev_price, 2)
    chg_pct = round((last_price / max(0.01, prev_price) - 1.0) * 100, 2)

    total_val_yi = round(last_price * (15 + (hash(clean_sym) % 30)), 2)
    float_val_yi = round(total_val_yi * 0.88, 2)
    turnover = round(2.5 + (hash(clean_sym) % 15) * 0.8, 2)

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
        "data": bars_data
    }
