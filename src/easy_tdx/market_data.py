"""Real-Time & Historical Market Data Provider using easy_tdx TDX Socket Client."""
from __future__ import annotations
import logging
import time
import threading
from typing import Any
import pandas as pd
import numpy as np
from easy_tdx.client import TdxClient
from easy_tdx.models import Market, KlineCategory
from easy_tdx.screener.scanner import generate_mock_kline

logger = logging.getLogger(__name__)

# Global thread-safe client instance
_CLIENT_LOCK = threading.Lock()
_TDX_CLIENT: TdxClient | None = None
_CACHE: dict[str, tuple[float, pd.DataFrame]] = {}
CACHE_TTL_SEC = 30.0

PRIMARY_HOSTS = ["180.153.18.170", "119.147.212.81", "115.238.56.198", "124.71.187.122"]

def _get_market(symbol: str) -> Market:
    sym = symbol.strip().upper()
    if sym.startswith(("60", "68")):
        return Market.SH
    elif sym.startswith(("00", "30")):
        return Market.SZ
    elif sym.startswith(("4", "8", "9")):
        return Market.BJ
    return Market.SZ

def _get_or_create_client() -> TdxClient:
    global _TDX_CLIENT
    with _CLIENT_LOCK:
        if _TDX_CLIENT is not None:
            return _TDX_CLIENT
            
        for host in PRIMARY_HOSTS:
            try:
                cli = TdxClient(host=host, port=7709, timeout=2.5)
                cli.connect()
                _TDX_CLIENT = cli
                logger.info(f"TDX client connected successfully to {host}:7709")
                return _TDX_CLIENT
            except Exception as e:
                logger.warning(f"Failed to connect to TDX host {host}: {e}")
                
        # Default fallback
        _TDX_CLIENT = TdxClient(host="180.153.18.170", port=7709, timeout=2.5)
        try:
            _TDX_CLIENT.connect()
        except Exception:
            pass
        return _TDX_CLIENT

def fetch_security_kline(symbol: str, count: int = 120, category: KlineCategory = KlineCategory.DAY) -> pd.DataFrame:
    """Fetch real market K-line bars for symbol from TDX server with fallback to realistic mock."""
    clean_sym = symbol.strip().upper().replace("SH", "").replace("SZ", "").replace("BJ", "").replace(".", "")
    if not clean_sym:
        clean_sym = "000001"
        
    cache_key = f"{clean_sym}_{category.value if hasattr(category, 'value') else category}_{count}"
    now = time.time()
    
    # Check cache
    if cache_key in _CACHE:
        ts, cached_df = _CACHE[cache_key]
        if now - ts < CACHE_TTL_SEC:
            return cached_df.copy()
            
    # Try fetching real data from TDX
    try:
        client = _get_or_create_client()
        market = _get_market(clean_sym)
        df = client.get_security_bars(market, clean_sym, category, 0, count)
        
        if df is not None and not df.empty and len(df) > 0:
            res_df = pd.DataFrame()
            if "date" in df.columns:
                # Format date string: "2026-08-31 00:00:00" -> "2026-08-31"
                res_df["datetime"] = df["date"].astype(str).str.slice(0, 10)
            elif "datetime" in df.columns:
                res_df["datetime"] = df["datetime"].astype(str).str.slice(0, 10)
            else:
                res_df["datetime"] = [d.strftime("%Y-%m-%d") for d in pd.date_range(end=pd.Timestamp.now(), periods=len(df), freq="B")]
                
            res_df["open"] = pd.to_numeric(df["open"], errors="coerce").fillna(0.0).round(2)
            res_df["high"] = pd.to_numeric(df["high"], errors="coerce").fillna(0.0).round(2)
            res_df["low"] = pd.to_numeric(df["low"], errors="coerce").fillna(0.0).round(2)
            res_df["close"] = pd.to_numeric(df["close"], errors="coerce").fillna(0.0).round(2)
            res_df["volume"] = pd.to_numeric(df["vol"] if "vol" in df.columns else df["volume"], errors="coerce").fillna(0).astype(int)
            res_df["amount"] = pd.to_numeric(df["amount"] if "amount" in df.columns else (res_df["volume"] * res_df["close"]), errors="coerce").fillna(0.0).round(2)
            
            # Sort by datetime ascending
            res_df = res_df.sort_values(by="datetime").reset_index(drop=True)
            
            _CACHE[cache_key] = (now, res_df)
            return res_df.copy()
    except Exception as e:
        logger.warning(f"Failed to fetch live TDX bars for {clean_sym}: {e}, falling back to generator.")
        
    # Fallback to realistic mock if TDX is offline
    fallback_df = generate_mock_kline(clean_sym, n_bars=count)
    return fallback_df

def fetch_realtime_pool_quotes(symbols: list[str] | None = None) -> list[dict[str, Any]]:
    """Fetch real-time snapshot quotes from TDX server."""
    if not symbols:
        symbols = ["600660", "300223", "000001", "600123", "002345", "300142", "601216", "002415", "300750", "600519"]
        
    pairs = [(_get_market(s), s) for s in symbols]
    quotes_list = []
    
    try:
        client = _get_or_create_client()
        raw_quotes = client.get_security_quotes(pairs)
        if raw_quotes is not None and not raw_quotes.empty:
            for _, row in raw_quotes.iterrows():
                code = str(row.get("code", ""))
                price = float(row.get("price") or 0.0)
                pre_close = float(row.get("pre_close") or price)
                chg_pct = round(((price / max(0.01, pre_close)) - 1.0) * 100, 2) if pre_close > 0 else 0.0
                
                quotes_list.append({
                    "symbol": code,
                    "code": code,
                    "price": round(price, 2),
                    "pre_close": round(pre_close, 2),
                    "open": round(float(row.get("open") or price), 2),
                    "high": round(float(row.get("high") or price), 2),
                    "low": round(float(row.get("low") or price), 2),
                    "volume": int(row.get("vol") or 0),
                    "turnover_wan": round(float(row.get("amount") or 0.0) / 10000.0, 1),
                    "change_pct": chg_pct,
                })
    except Exception as e:
        logger.warning(f"Failed to fetch realtime quotes from TDX: {e}")
        
    return quotes_list
