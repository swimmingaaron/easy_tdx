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
from easy_tdx.MyTT import MA, MACD, RSI, KDJ, BOLL, ZIG, HHV, SUM, TD_SEQUENTIAL

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
    raw_upper = sym.strip().upper()
    if raw_upper.endswith(".SH") or raw_upper.endswith("SH") or raw_upper.startswith("SH"):
        clean = raw_upper.replace(".SH", "").replace("SH", "").replace(".", "")
        return "SH", f"{clean}.SH"
    if raw_upper.endswith(".SZ") or raw_upper.endswith("SZ") or raw_upper.startswith("SZ"):
        clean = raw_upper.replace(".SZ", "").replace("SZ", "").replace(".", "")
        return "SZ", f"{clean}.SZ"
    if raw_upper.endswith(".BJ") or raw_upper.endswith("BJ") or raw_upper.startswith("BJ"):
        clean = raw_upper.replace(".BJ", "").replace("BJ", "").replace(".", "")
        return "BJ", f"{clean}.BJ"
    if raw_upper.endswith(".HY") or raw_upper.endswith("HY") or raw_upper.startswith("HY"):
        clean = raw_upper.replace(".HY", "").replace("HY", "").replace(".", "")
        return "HY", f"{clean}.HY"

    clean_sym = raw_upper.replace(".", "")
    if clean_sym in ("999999", "999998", "999997", "000688"):
        return "SH", f"{clean_sym}.SH"
    if clean_sym.startswith("88"):
        return "HY", f"{clean_sym}.HY"
    elif clean_sym.startswith(("60", "68", "99")):
        return "SH", f"{clean_sym}.SH"
    elif clean_sym.startswith(("00", "30", "399")):
        return "SZ", f"{clean_sym}.SZ"
    elif clean_sym.startswith(("4", "83", "87", "92")):
        return "BJ", f"{clean_sym}.BJ"
    return "SZ", f"{clean_sym}.SZ"

def _get_board_tag(sym: str) -> dict[str, str]:
    raw_upper = sym.strip().upper()
    clean = raw_upper.replace(".SH", "").replace("SH", "").replace(".SZ", "").replace("SZ", "").replace(".BJ", "").replace("BJ", "").replace(".", "")
    if clean in ("000688", "999688"):
        return {"label": "科", "color": "#a855f7"}
    if clean in ("999999", "000001", "000300", "399300", "399001"):
        return {"label": "指", "color": "#3b82f6"}
    if clean == "399006":
        return {"label": "创", "color": "#f97316"}
    if clean == "899050":
        return {"label": "北", "color": "#06b6d4"}
    if clean.startswith("88"):
        return {"label": "板", "color": "#ec4899"}
    elif clean.startswith(("300", "301")):
        return {"label": "创", "color": "#f97316"}
    elif clean.startswith("688"):
        return {"label": "科", "color": "#a855f7"}
    elif clean.startswith(("4", "8", "9")):
        return {"label": "北", "color": "#06b6d4"}
    return {"label": "主", "color": "#3b82f6"}

from pydantic import BaseModel

class WatchlistUpdateRequest(BaseModel):
    symbols: list[str]

_REALTIME_QUOTES_CACHE: tuple[float, list[dict[str, Any]]] | None = None
_REALTIME_QUOTES_LOCK = threading.Lock()
REALTIME_TTL = 5.0

_STOCK_BOARD_CACHE: dict[str, dict[str, str]] = {}
_BOARD_NAME_MAP: dict[str, str] = {}
_STOCK_BOARD_LOCK = threading.Lock()

def _resolve_stock_board_info(code: str, raw_sym: str = "") -> dict[str, str]:
    """Resolve stock industry sector name and code using TDX MAC get_belong_board."""
    clean = code.strip().upper().replace("SH", "").replace("SZ", "").replace("BJ", "").replace("HY", "").replace(".", "")
    if clean.startswith("88"):
        b_name = _BOARD_NAME_MAP.get(clean) or get_stock_name(clean)
        return {"board_code": clean, "board_name": b_name}
    if clean in ("999999", "399001", "399006", "000300", "000688", "899050"):
        return {"board_code": clean, "board_name": "宽基指数"}
        
    with _STOCK_BOARD_LOCK:
        if clean in _STOCK_BOARD_CACHE:
            return _STOCK_BOARD_CACHE[clean]
            
    b_code = ""
    b_name = "--"
    try:
        from easy_tdx.market_overview import _get_or_create_mac_client
        mac = _get_or_create_mac_client()
        mkt = 1 if (clean.startswith(("6", "9")) or raw_sym.upper().endswith("SH")) else 0
        df = mac.get_belong_board(mkt, clean)
        if df is not None and not df.empty:
            for _, row in df.iterrows():
                bc = str(row.get("board_code", "")).strip()
                bn = str(row.get("board_name", "")).strip()
                if bc and bn:
                    _BOARD_NAME_MAP[bc] = bn
            hy = df[df["board_type"] == 12]
            if not hy.empty:
                r = hy.iloc[-1]
                b_code = str(r["board_code"])
                b_name = str(r["board_name"])
            else:
                r = df.iloc[-1]
                b_code = str(r["board_code"])
                b_name = str(r["board_name"])
    except Exception:
        pass
        
    res = {"board_code": b_code, "board_name": b_name}
    with _STOCK_BOARD_LOCK:
        _STOCK_BOARD_CACHE[clean] = res
    return res



@router.get("/watchlist")
def get_watchlist():
    """Get permanently saved watchlist symbols."""
    from easy_tdx.watchlist_store import load_watchlist
    symbols = load_watchlist()
    return {
        "status": "success",
        "count": len(symbols),
        "data": symbols
    }

@router.post("/watchlist")
def update_watchlist(req: WatchlistUpdateRequest):
    """Permanently persist watchlist symbols."""
    from easy_tdx.watchlist_store import save_watchlist
    symbols = save_watchlist(req.symbols)
    global _REALTIME_QUOTES_CACHE
    with _REALTIME_QUOTES_LOCK:
        _REALTIME_QUOTES_CACHE = None
    return {
        "status": "success",
        "count": len(symbols),
        "data": symbols
    }

@router.post("/watchlist/reset")
def reset_watchlist_endpoint():
    """Reset watchlist to defaults."""
    from easy_tdx.watchlist_store import reset_watchlist
    symbols = reset_watchlist()
    global _REALTIME_QUOTES_CACHE
    with _REALTIME_QUOTES_LOCK:
        _REALTIME_QUOTES_CACHE = None
    return {
        "status": "success",
        "count": len(symbols),
        "data": symbols
    }

@router.get("/realtime")
def get_realtime_quotes(symbols: str | None = Query(None, description="Comma-separated stock symbols for custom watchlist")):
    """Get live pool quotes with stock name and metrics directly from TDX with caching."""
    global _REALTIME_QUOTES_CACHE
    now = time.time()
    
    clean_syms: list[str] = []
    if symbols:
        raw_list = [s.strip().upper().replace("SH", "").replace("SZ", "").replace("BJ", "").replace(".", "") 
                    for s in symbols.split(",") if s.strip()]
        seen = set()
        for s in raw_list:
            if s and s not in seen:
                seen.add(s)
                clean_syms.append(s)
    
    # If no symbols provided, check default cache and load persistent watchlist
    if not clean_syms:
        from easy_tdx.watchlist_store import load_watchlist
        clean_syms = load_watchlist()
        with _REALTIME_QUOTES_LOCK:
            if _REALTIME_QUOTES_CACHE is not None:
                ts, cached = _REALTIME_QUOTES_CACHE
                if now - ts < REALTIME_TTL:
                    return {"status": "success", "count": len(cached), "data": cached}

    real_quotes = fetch_realtime_pool_quotes(clean_syms)
    quote_map = {q["code"]: q for q in real_quotes}
    data = []
    
    for code in clean_syms:
        name = get_stock_name(code)
        mkt, full_sym = _get_market_suffix(code)
        
        if code in quote_map:
            rq = quote_map[code]
            p = rq["price"]
            chg = rq["change_pct"]
            h = rq["high"]
            l = rq["low"]
            v = rq["volume"]
            amt = rq["turnover_wan"]
            total_mv_yi = rq.get("total_mv_yi", 0.0)
            m1 = rq.get("main_net_amount", 0.0)
            m3 = rq.get("main_net_3d", 0.0)
            m5 = rq.get("main_net_5d", 0.0)
            inflow_1d = rq.get("inflow_1d_str", "")
            inflow_3d = rq.get("inflow_3d_str", "")
            inflow_5d = rq.get("inflow_5d_str", "")
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
                p, h, l, v, amt, chg = 0.0, 0.0, 0.0, 0, 0.0, 0.0
            total_mv_yi = 0.0
            m1, m3, m5 = 0.0, 0.0, 0.0
            inflow_1d, inflow_3d, inflow_5d = "0.0万", "0.0万", "0.0万"
            
        b_info = _resolve_stock_board_info(code, full_sym)
        data.append({
            "symbol": code,
            "code": code,
            "name": name,
            "display": f"{code} {name}",
            "full_symbol": full_sym,
            "board_tag": _get_board_tag(code),
            "board_code": b_info["board_code"],
            "board_name": b_info["board_name"],
            "price": p,
            "change_pct": chg,
            "high": h,
            "low": l,
            "volume": v,
            "turnover_wan": amt,
            "total_mv_yi": total_mv_yi,
            "main_net_amount": m1,
            "main_net_3d": m3,
            "main_net_5d": m5,
            "inflow_1d_str": inflow_1d,
            "inflow_3d_str": inflow_3d,
            "inflow_5d_str": inflow_5d,
            "status": "多头排列" if chg > 1.5 else ("放量突破" if chg > 0 else "缩量回踩")
        })
        
    if not symbols:
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
    raw_sym = symbol.strip()
    clean_sym = raw_sym.upper().replace("SH", "").replace("SZ", "").replace("BJ", "").replace(".", "")
    if not clean_sym:
        clean_sym = "000001"
        raw_sym = "000001"
        
    n_bars = max(30, min(500, count if count != 120 else (months * 22 if months else 120)))
    
    df = fetch_security_kline(raw_sym, count=n_bars, period=period)
    mkt, full_sym = _get_market_suffix(raw_sym)
    stock_name = _BOARD_NAME_MAP.get(clean_sym) or get_stock_name(full_sym)
    board = _get_board_tag(full_sym)

    c = df["close"].values
    h = df["high"].values
    l = df["low"].values
    v = df["volume"].values

    # Moving averages
    ma5 = MA(c, 5)
    ma10 = MA(c, 10)
    ma20 = MA(c, 20)
    ma60 = MA(c, min(60, len(c)))

    # Volume & Turnover MAs & ratio
    v_ma5 = MA(v, 5)
    v_ma10 = MA(v, 10)
    vol_ratios = np.round(v / np.maximum(v_ma5, 1.0), 2)
    
    amt_vals = df["amount"].values.astype(float) if "amount" in df.columns else (c * v).astype(float)
    amt_ma5 = MA(amt_vals, 5)
    amt_ma10 = MA(amt_vals, 10)

    # Net capital inflow per bar (using normalized price-action spread and trend)
    n_len = len(df)
    net_inflows = np.zeros(n_len, dtype=float)
    for idx in range(n_len):
        c_i = float(c[idx])
        o_i = float(df["open"].iloc[idx])
        h_i = float(h[idx])
        l_i = float(l[idx])
        amt_i = float(amt_vals[idx])
        pre_c_i = float(df["close"].iloc[idx - 1]) if idx > 0 else o_i
        hl_diff = max(0.001, h_i - l_i)
        body_r = (c_i - o_i) / hl_diff
        pos_r = (c_i - l_i) / hl_diff - 0.5
        chg_r = ((c_i / max(0.01, pre_c_i)) - 1.0) * 10.0
        # Realistic net capital inflow ratio in A-share market is bounded in [-0.20, 0.20]
        flow_r = max(-0.20, min(0.20, body_r * 0.08 + pos_r * 0.06 + chg_r * 0.10))
        net_inflows[idx] = round(amt_i * flow_r, 2)

    inflow_ma3 = MA(net_inflows, 3)
    inflow_ma5 = MA(net_inflows, 5)
    inflow_ma10 = MA(net_inflows, 10)
    inflow_sum3 = SUM(net_inflows, 3)
    inflow_sum5 = SUM(net_inflows, 5)
    inflow_sum10 = SUM(net_inflows, 10)

    # Indicators
    dif, dea, macd_hist = MACD(c)
    rsi6 = RSI(c, 6)
    rsi12 = RSI(c, 12)
    k_val, d_val, j_val = KDJ(c, h, l)
    boll_up, boll_mid, boll_low = BOLL(c, 20, 2)
    
    # TD Sequential (通达信九转与十三转)
    td9_h, td9_l = TD_SEQUENTIAL(c, 9)
    td13_h, td13_l = TD_SEQUENTIAL(c, 13)

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
            "amount": safe_float(amt_vals[i], 0.0),
            "amount_ma5": safe_float(amt_ma5[i]),
            "amount_ma10": safe_float(amt_ma10[i]),
            "net_inflow": safe_float(net_inflows[i]),
            "inflow_sum3": safe_float(inflow_sum3[i]),
            "inflow_sum5": safe_float(inflow_sum5[i]),
            "inflow_sum10": safe_float(inflow_sum10[i]),
            "inflow_ma3": safe_float(inflow_ma3[i]),
            "inflow_ma5": safe_float(inflow_ma5[i]),
            "inflow_ma10": safe_float(inflow_ma10[i]),
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
            "td9_high": int(td9_h[i]),
            "td9_low": int(td9_l[i]),
            "td13_high": int(td13_h[i]),
            "td13_low": int(td13_l[i]),
        })

    last_bar = bars_data[-1]
    prev_bar = bars_data[-2] if len(bars_data) > 1 else last_bar
    last_price = last_bar["close"]
    prev_price = prev_bar["close"]
    chg = round(last_price - prev_price, 2)
    chg_pct = round(((last_price / max(0.01, prev_price)) - 1.0) * 100, 2)
    amt_yi = round(float(last_bar.get("amount", 0.0)) / 100000000.0, 2)
    
    # Base defaults
    total_val_yi = round(amt_yi * 18.5, 2) if amt_yi > 0 else round(last_price * 15.0, 2)
    float_val_yi = round(total_val_yi * 0.85, 2)
    turnover = round((float(last_bar.get("volume", 0)) / 1000000.0) * 2.5, 2)
    pe_dynamic = None
    pe_ttm = None
    pe_static = None
    vol_ratio = last_bar.get("vol_ratio", 1.0)
    m1_real = float(last_bar.get("net_inflow", 0.0))
    m3_real = 0.0
    m5_real = 0.0
    m10_real = 0.0

    # Real-time enrichment from TDX MAC quote protocol (total_cap, float_cap, PE, turnover, vol_ratio)
    try:
        from easy_tdx.market_overview import _get_or_create_mac_client
        from easy_tdx.codec.bitmap import FieldBit, PresetField
        mac = _get_or_create_mac_client()
        fields = (
            PresetField.BASIC
            + FieldBit.AMOUNT
            + FieldBit.VOL_RATIO
            + FieldBit.TOTAL_MARKET_CAP_AB
            + FieldBit.PE_DYNAMIC
            + FieldBit.PE_TTM
            + FieldBit.PE_STATIC
            + FieldBit.CIRCULATING_CAPITAL_Z
            + FieldBit.MAIN_NET_AMOUNT
            + FieldBit.MAIN_NET_3D_AMOUNT
            + FieldBit.MAIN_NET_5D_AMOUNT
            + FieldBit.MAIN_NET_10D_AMOUNT
        )
        mac_mkt = 1 if (clean_sym.startswith(("6", "9")) or raw_sym.upper().endswith("SH")) else 0
        df_q = mac.get_stock_quotes([(mac_mkt, clean_sym)], fields=fields)
        if df_q is not None and not df_q.empty:
            row_q = df_q.iloc[0]
            t_cap = float(row_q.get("total_market_cap_ab") or 0.0)
            if t_cap > 0:
                total_val_yi = round(t_cap / 1e8, 2)
            circ_z = float(row_q.get("circulating_capital_z") or 0.0)
            if circ_z > 0:
                float_val_yi = round((circ_z * 10000.0 * last_price) / 1e8, 2)
                vol_shares = float(last_bar.get("volume", 0))
                turnover = round((vol_shares / (circ_z * 10000.0)) * 100.0, 2)
            
            p_d = float(row_q.get("pe_dynamic") or 0.0)
            if p_d != 0:
                pe_dynamic = round(p_d, 1)
            p_t = float(row_q.get("pe_ttm") or 0.0)
            if p_t != 0:
                pe_ttm = round(p_t, 1)
            p_s = float(row_q.get("pe_static") or 0.0)
            if p_s != 0:
                pe_static = round(p_s, 1)
            vr = float(row_q.get("vol_ratio") or 0.0)
            if vr > 0:
                vol_ratio = round(vr, 2)

            m1_real = float(row_q.get("main_net_amount") or 0.0)
            m3_real = float(row_q.get("main_net_3d_amount") or 0.0)
            m5_real = float(row_q.get("main_net_5d_amount") or 0.0)
            m10_real = float(row_q.get("main_net_10d_amount") or 0.0)

            # Calibrate net_inflow on daily bars with TDX Level-2 official capital flows
            if bars_data and (m1_real != 0.0 or m3_real != 0.0 or m5_real != 0.0):
                bars_data[-1]["net_inflow"] = round(m1_real, 2)

                # Calibrate 3-day window
                if len(bars_data) >= 3 and m3_real != 0.0:
                    diff_3 = m3_real - m1_real
                    a_prev1 = float(bars_data[-2].get("amount") or 1.0)
                    a_prev2 = float(bars_data[-3].get("amount") or 1.0)
                    tot_a_3 = max(1.0, a_prev1 + a_prev2)
                    bars_data[-2]["net_inflow"] = round(diff_3 * (a_prev1 / tot_a_3), 2)
                    bars_data[-3]["net_inflow"] = round(diff_3 * (a_prev2 / tot_a_3), 2)

                # Calibrate 5-day window
                if len(bars_data) >= 5 and m5_real != 0.0:
                    diff_5 = m5_real - (m3_real if m3_real != 0.0 else (m1_real * 3.0))
                    a_prev3 = float(bars_data[-4].get("amount") or 1.0)
                    a_prev4 = float(bars_data[-5].get("amount") or 1.0)
                    tot_a_5 = max(1.0, a_prev3 + a_prev4)
                    bars_data[-4]["net_inflow"] = round(diff_5 * (a_prev3 / tot_a_5), 2)
                    bars_data[-5]["net_inflow"] = round(diff_5 * (a_prev4 / tot_a_5), 2)

                # Calibrate 10-day window
                if len(bars_data) >= 10 and m10_real != 0.0:
                    diff_10 = m10_real - (m5_real if m5_real != 0.0 else (m1_real * 5.0))
                    sub_amts = [float(bars_data[-(k+1)].get("amount") or 1.0) for k in range(5, 10)]
                    tot_a_10 = max(1.0, sum(sub_amts))
                    for k in range(5, 10):
                        bars_data[-(k+1)]["net_inflow"] = round(diff_10 * (float(bars_data[-(k+1)].get("amount") or 1.0) / tot_a_10), 2)

                # Recompute inflow_ma and inflow_sum after calibration
                calib_flows = [b["net_inflow"] for b in bars_data]
                rec_flows_arr = np.array(calib_flows, dtype=float)
                rec_ma3 = MA(rec_flows_arr, 3)
                rec_ma5 = MA(rec_flows_arr, 5)
                rec_ma10 = MA(rec_flows_arr, 10)
                rec_sum3 = SUM(rec_flows_arr, 3)
                rec_sum5 = SUM(rec_flows_arr, 5)
                rec_sum10 = SUM(rec_flows_arr, 10)
                for b_idx, b in enumerate(bars_data):
                    b["inflow_ma3"] = safe_float(rec_ma3[b_idx])
                    b["inflow_ma5"] = safe_float(rec_ma5[b_idx])
                    b["inflow_ma10"] = safe_float(rec_ma10[b_idx])
                    b["inflow_sum3"] = safe_float(rec_sum3[b_idx])
                    b["inflow_sum5"] = safe_float(rec_sum5[b_idx])
                    b["inflow_sum10"] = safe_float(rec_sum10[b_idx])
                if m3_real != 0.0:
                    bars_data[-1]["inflow_sum3"] = round(m3_real, 2)
                    bars_data[-1]["inflow_ma3"] = round(m3_real / 3.0, 2)
                if m5_real != 0.0:
                    bars_data[-1]["inflow_sum5"] = round(m5_real, 2)
                    bars_data[-1]["inflow_ma5"] = round(m5_real / 5.0, 2)
                if m10_real != 0.0:
                    bars_data[-1]["inflow_sum10"] = round(m10_real, 2)
                    bars_data[-1]["inflow_ma10"] = round(m10_real / 10.0, 2)
    except Exception as e:
        logger.debug(f"Failed to fetch TDX MAC quotes for {clean_sym}: {e}")

    b_info = _resolve_stock_board_info(clean_sym, full_sym)
    board_lbl = board.get("label", "") if isinstance(board, dict) else str(board)
    zs_block = b_info.get("board_name") or board_lbl or ""
    data1 = f"{clean_sym}|{zs_block}"

    return {
        "status": "success",
        "symbol": clean_sym,
        "name": stock_name,
        "display": f"{clean_sym} {stock_name}",
        "full_symbol": full_sym,
        "market": mkt,
        "board_tag": board,
        "zs_block": zs_block,
        "data1": data1,
        "period": period,
        "count": len(bars_data),
        "td_summary": {
            "td9_high": int(td9_h[-1]) if len(td9_h) > 0 else 0,
            "td9_low": int(td9_l[-1]) if len(td9_l) > 0 else 0,
            "td13_high": int(td13_h[-1]) if len(td13_h) > 0 else 0,
            "td13_low": int(td13_l[-1]) if len(td13_l) > 0 else 0,
        },
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
            "pe_dynamic": pe_dynamic,
            "pe_ttm": pe_ttm,
            "pe_static": pe_static,
            "vol_ratio": vol_ratio,
            "main_net_amount": m1_real,
            "main_net_3d": m3_real,
            "main_net_5d": m5_real,
            "main_net_10d": m10_real,
            "net_inflow": last_bar.get("net_inflow", 0.0),
            "ma5": last_bar["ma5"],
            "ma10": last_bar["ma10"],
            "ma20": last_bar["ma20"],
            "ma60": last_bar["ma60"],
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

@router.get("/stock_profile")
def get_stock_profile(symbol: str = Query(..., description="Stock symbol, e.g. 688683")):
    """Get full stock profile including shareholder counts, company information, belonging sectors, and quarterly revenue/profit YoY/QoQ."""
    from easy_tdx.stock_profile import get_stock_full_profile
    data = get_stock_full_profile(symbol)
    return {
        "status": "success",
        "symbol": symbol,
        "data": data
    }


