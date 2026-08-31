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

logger = logging.getLogger(__name__)

# Global thread-safe client instance
_CLIENT_LOCK = threading.Lock()
_TDX_CLIENT: TdxClient | None = None
_CACHE: dict[str, tuple[float, pd.DataFrame]] = {}
CACHE_TTL_SEC = 30.0

PRIMARY_HOSTS = ["180.153.18.170", "119.147.212.81", "115.238.56.198", "124.71.187.122"]

def _get_market(symbol: str) -> Market:
    sym = symbol.strip().upper().replace("SH", "").replace("SZ", "").replace("BJ", "").replace(".", "")
    if sym.startswith(("60", "68", "99")):
        return Market.SH
    elif sym.startswith(("00", "30", "399")):
        return Market.SZ
    elif sym.startswith(("4", "83", "87", "88", "92")):
        return Market.BJ
    elif sym.startswith("8"):
        return Market.BJ
    return Market.SZ

def _is_board_symbol(clean_sym: str) -> bool:
    """Detect if symbol is an industry/concept board index (e.g. 881376, 880472, 880xxx, 881xxx)."""
    if clean_sym.startswith("88") and len(clean_sym) == 6:
        return True
    if clean_sym.startswith(("BK", "HY")):
        return True
    return False

def _is_index_symbol(clean_sym: str, market: Market) -> bool:
    """Detect if symbol is a standard index (e.g. 999999, 399001, 399006, 000300)."""
    if clean_sym in ("999999", "000300", "000016", "000010", "000688") or clean_sym.startswith("99"):
        return True
    if clean_sym.startswith("399") or clean_sym in ("399001", "399006", "399300", "399005", "899050"):
        return True
    return False

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

# Thread-safe MAC client singleton
_MAC_CLIENT = None
_MAC_LOCK = threading.Lock()

def _get_or_create_mac_client():
    """Get or create singleton MacClient for board index K-lines."""
    global _MAC_CLIENT
    with _MAC_LOCK:
        if _MAC_CLIENT is not None:
            return _MAC_CLIENT
        from easy_tdx.mac.client import MacClient
        try:
            _MAC_CLIENT = MacClient.from_best_host()
            _MAC_CLIENT.connect()
            logger.info("MacClient connected for board K-lines")
        except Exception as e:
            logger.warning(f"Failed to connect MacClient.from_best_host(): {e}")
            _MAC_CLIENT = MacClient()
            try:
                _MAC_CLIENT.connect()
            except Exception:
                pass
        return _MAC_CLIENT

def fetch_security_kline(
    symbol: str, 
    category: KlineCategory | str = KlineCategory.DAY, 
    count: int = 240,
    period: str | None = None
) -> pd.DataFrame:
    """Fetch historical K-line bars via TDX binary socket connection, with caching."""
    if period is not None:
        category = period
        
    clean_sym = symbol.strip().upper().replace("SH", "").replace("SZ", "").replace("BJ", "").replace(".", "")
    if not clean_sym:
        clean_sym = "000001"
        
    is_120m = False
    if isinstance(category, str):
        c_upper = category.upper()
        if c_upper in ("120M", "MIN_120", "120MIN", "120"):
            is_120m = True
            category = KlineCategory.MIN_60
        else:
            cat_map = {
                "DAY": KlineCategory.DAY,
                "WEEK": KlineCategory.WEEK,
                "MONTH": KlineCategory.MONTH,
                "SEASON": KlineCategory.SEASON,
                "QUARTER": KlineCategory.SEASON,
                "YEAR": KlineCategory.YEAR,
                "60M": KlineCategory.MIN_60,
                "MIN_60": KlineCategory.MIN_60,
                "30M": KlineCategory.MIN_30,
                "MIN_30": KlineCategory.MIN_30,
                "15M": KlineCategory.MIN_15,
                "MIN_15": KlineCategory.MIN_15,
                "5M": KlineCategory.MIN_5,
                "MIN_5": KlineCategory.MIN_5,
                "1M": KlineCategory.MIN_1,
                "MIN_1": KlineCategory.MIN_1,
            }
            category = cat_map.get(c_upper, KlineCategory.DAY)

    cache_suffix = "120M" if is_120m else (category.value if hasattr(category, 'value') else category)
    cache_key = f"{clean_sym}_{cache_suffix}_{count}"
    now = time.time()
    
    # Check cache
    if cache_key in _CACHE:
        ts, cached_df = _CACHE[cache_key]
        if now - ts < CACHE_TTL_SEC:
            return cached_df.copy()

    from easy_tdx.mac.enums import Period as MacPeriod

    # 1. Check if 120M requested: MacClient supports native 120M (times=120)
    if is_120m:
        try:
            mac = _get_or_create_mac_client()
            mkt_id = 1 if (clean_sym.startswith("6") or clean_sym.startswith("88")) else 0
            bdf = mac.get_stock_kline(mkt_id, clean_sym, MacPeriod.MINS, times=120, count=count)
            if bdf is not None and not bdf.empty and len(bdf) > 0:
                res_df = pd.DataFrame()
                res_df["datetime"] = bdf["datetime"].astype(str).str.slice(0, 16)
                res_df["open"] = pd.to_numeric(bdf["open"], errors="coerce").fillna(0.0).round(2)
                res_df["high"] = pd.to_numeric(bdf["high"], errors="coerce").fillna(0.0).round(2)
                res_df["low"] = pd.to_numeric(bdf["low"], errors="coerce").fillna(0.0).round(2)
                res_df["close"] = pd.to_numeric(bdf["close"], errors="coerce").fillna(0.0).round(2)
                res_df["volume"] = pd.to_numeric(bdf["vol"] if "vol" in bdf.columns else bdf.get("volume", 0), errors="coerce").fillna(0).astype(int)
                res_df["amount"] = pd.to_numeric(bdf["amount"], errors="coerce").fillna(0.0).round(2)
                res_df = res_df.sort_values(by="datetime").reset_index(drop=True)
                _CACHE[cache_key] = (now, res_df)
                return res_df.copy()
        except Exception as e:
            logger.warning(f"Failed to fetch native 120M via MacClient: {e}")

    # 2. Check if this is an industry/concept board index (e.g. 881376, 881422, etc.)
    if _is_board_symbol(clean_sym):
        try:
            mac_period_map = {
                KlineCategory.DAY: MacPeriod.DAILY,
                KlineCategory.WEEK: MacPeriod.WEEKLY,
                KlineCategory.MONTH: MacPeriod.MONTHLY,
                KlineCategory.SEASON: MacPeriod.QUARTERLY,
                KlineCategory.YEAR: MacPeriod.YEARLY,
                KlineCategory.MIN_60: MacPeriod.MIN_60,
                KlineCategory.MIN_30: MacPeriod.MIN_30,
                KlineCategory.MIN_15: MacPeriod.MIN_15,
                KlineCategory.MIN_5: MacPeriod.MIN_5,
                KlineCategory.MIN_1: MacPeriod.MIN_1,
            }
            mac_p = mac_period_map.get(category, MacPeriod.DAILY)
            mac = _get_or_create_mac_client()
            bdf = mac.get_stock_kline(1, clean_sym, mac_p, count=count)
            if bdf is not None and not bdf.empty and len(bdf) > 0:
                res_df = pd.DataFrame()
                if "datetime" in bdf.columns:
                    # Daily/weekly/monthly/season/year is YYYY-MM-DD; intraday contains HH:MM
                    if mac_p in (MacPeriod.DAILY, MacPeriod.WEEKLY, MacPeriod.MONTHLY, MacPeriod.QUARTERLY, MacPeriod.YEARLY):
                        res_df["datetime"] = bdf["datetime"].astype(str).str.slice(0, 10)
                    else:
                        res_df["datetime"] = bdf["datetime"].astype(str).str.slice(0, 16)
                else:
                    res_df["datetime"] = [d.strftime("%Y-%m-%d") for d in pd.date_range(end=pd.Timestamp.now(), periods=len(bdf), freq="B")]
                    
                res_df["open"] = pd.to_numeric(bdf["open"], errors="coerce").fillna(0.0).round(2)
                res_df["high"] = pd.to_numeric(bdf["high"], errors="coerce").fillna(0.0).round(2)
                res_df["low"] = pd.to_numeric(bdf["low"], errors="coerce").fillna(0.0).round(2)
                res_df["close"] = pd.to_numeric(bdf["close"], errors="coerce").fillna(0.0).round(2)
                res_df["volume"] = pd.to_numeric(bdf["vol"] if "vol" in bdf.columns else bdf.get("volume", 0), errors="coerce").fillna(0).astype(int)
                res_df["amount"] = pd.to_numeric(bdf["amount"], errors="coerce").fillna(0.0).round(2)
                res_df = res_df.sort_values(by="datetime").reset_index(drop=True)
                
                _CACHE[cache_key] = (now, res_df)
                return res_df.copy()
        except Exception as e:
            logger.warning(f"Failed to fetch MAC board K-line for {clean_sym}: {e}")
            
    # 3. Try fetching real data from standard TDX client
    try:
        client = _get_or_create_client()
        market = _get_market(clean_sym)
        fetch_cnt = count * 2 if is_120m else count
        if _is_index_symbol(clean_sym, market):
            df = client.get_index_bars(market, clean_sym, category, 0, fetch_cnt)
        else:
            df = client.get_security_bars(market, clean_sym, category, 0, fetch_cnt)
        
        if df is not None and not df.empty and len(df) > 0:
            res_df = pd.DataFrame()
            is_intraday = category in (KlineCategory.MIN_1, KlineCategory.MIN_5, KlineCategory.MIN_15, KlineCategory.MIN_30, KlineCategory.MIN_60)
            date_col = "date" if "date" in df.columns else ("datetime" if "datetime" in df.columns else None)
            if date_col:
                slice_len = 16 if is_intraday else 10
                res_df["datetime"] = df[date_col].astype(str).str.slice(0, slice_len)
            else:
                res_df["datetime"] = [d.strftime("%Y-%m-%d") for d in pd.date_range(end=pd.Timestamp.now(), periods=len(df), freq="B")]
                
            res_df["open"] = pd.to_numeric(df["open"], errors="coerce").fillna(0.0).round(2)
            res_df["high"] = pd.to_numeric(df["high"], errors="coerce").fillna(0.0).round(2)
            res_df["low"] = pd.to_numeric(df["low"], errors="coerce").fillna(0.0).round(2)
            res_df["close"] = pd.to_numeric(df["close"], errors="coerce").fillna(0.0).round(2)
            res_df["volume"] = pd.to_numeric(df["vol"] if "vol" in df.columns else df["volume"], errors="coerce").fillna(0).astype(int)
            res_df["amount"] = pd.to_numeric(df["amount"] if "amount" in df.columns else (res_df["volume"] * res_df["close"]), errors="coerce").fillna(0.0).round(2)
            
            # If 120M was requested but MacClient wasn't used, resample pairs of 60M bars
            if is_120m and len(res_df) >= 2:
                # Group every 2 bars
                groups = np.arange(len(res_df)) // 2
                res_df = res_df.groupby(groups).agg({
                    "datetime": "last",
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum",
                    "amount": "sum"
                }).reset_index(drop=True)
                if len(res_df) > count:
                    res_df = res_df.tail(count).reset_index(drop=True)

            res_df = res_df.sort_values(by="datetime").reset_index(drop=True)
            _CACHE[cache_key] = (now, res_df)
            return res_df.copy()
    except Exception as e:
        logger.warning(f"Failed to fetch live TDX bars for {clean_sym}: {e}, falling back to generator.")
        
    # Fallback to realistic bars if TDX connection fails
    return _generate_fallback_bars(clean_sym, n_bars=count)

def _generate_fallback_bars(symbol: str, n_bars: int = 120) -> pd.DataFrame:
    """Deterministic fallback bars generator without circular dependencies."""
    import hashlib
    dates = pd.date_range(end=pd.Timestamp.now(), periods=n_bars, freq="B")
    seed = int(hashlib.md5(symbol.encode()).hexdigest(), 16) % (2**32)
    rng = np.random.RandomState(seed)
    base_price = 15.0 + (int(symbol[-2:]) if symbol.isdigit() else 10)
    daily_returns = rng.normal(0.0008, 0.022, size=n_bars)
    close_prices = [base_price]
    for r in daily_returns[:-1]:
        close_prices.append(max(2.0, close_prices[-1] * (1.0 + r)))
    
    opens = [round(max(2.0, close_prices[i] * (1.0 + rng.normal(0, 0.008))), 2) for i in range(n_bars)]
    highs = [round(max(opens[i], close_prices[i]) + abs(rng.exponential(0.012) * max(opens[i], close_prices[i])), 2) for i in range(n_bars)]
    lows = [round(max(1.0, min(opens[i], close_prices[i]) - abs(rng.exponential(0.012) * min(opens[i], close_prices[i]))), 2) for i in range(n_bars)]
    volumes = [rng.randint(30000, 350000) for _ in range(n_bars)]
    
    return pd.DataFrame({
        "datetime": [d.strftime("%Y-%m-%d") for d in dates],
        "open": opens,
        "high": highs,
        "low": lows,
        "close": [round(x, 2) for x in close_prices],
        "volume": volumes,
        "amount": [round(volumes[i] * close_prices[i], 2) for i in range(n_bars)]
    })

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
