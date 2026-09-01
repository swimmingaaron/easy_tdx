"""Full Market Strategy Screener Scanner for easy_tdx with Real TDX Historical & Live Data.

Supports:
- Multi-tier universes: core (35), hs300 (300), zz500 (500), zz1000 (1000), all (5200+)
- Daily disk caching for fast re-entry
- Progress callbacks for background async task tracking
- Graceful cancellation via stop_event
"""
from __future__ import annotations
import logging
import os
import json
import time
from datetime import date
from pathlib import Path
from typing import Any, Callable
import pandas as pd
import threading

from easy_tdx.strategies.registry import get_strategy
from easy_tdx.stock_lookup import get_stock_name, COMMON_STOCKS
from easy_tdx.market_data import fetch_security_kline
from easy_tdx.screener.universe import get_universe_symbols, CORE_UNIVERSE

logger = logging.getLogger(__name__)

DEFAULT_SCAN_UNIVERSE = CORE_UNIVERSE

def _get_cache_dir() -> Path:
    base = Path(__file__).resolve().parent.parent.parent.parent / "data" / "screener_cache"
    base.mkdir(parents=True, exist_ok=True)
    return base

def _get_cache_file(strategy_name: str, universe: str) -> Path:
    today_str = date.today().strftime("%Y%m%d")
    return _get_cache_dir() / f"{strategy_name}_{universe}_{today_str}.json"

def _load_cache(strategy_name: str, universe: str) -> list[dict[str, Any]] | None:
    cache_f = _get_cache_file(strategy_name, universe)
    if cache_f.exists():
        try:
            # Valid if created within the last 12 hours
            mtime = os.path.getmtime(cache_f)
            if time.time() - mtime < 43200:
                with open(cache_f, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        logger.info(f"Loaded {len(data)} cached screener results from {cache_f.name}")
                        return data
        except Exception as e:
            logger.warning(f"Failed to read cache {cache_f}: {e}")
    return None

def _save_cache(strategy_name: str, universe: str, matches: list[dict[str, Any]]) -> None:
    try:
        cache_f = _get_cache_file(strategy_name, universe)
        with open(cache_f, "w", encoding="utf-8") as f:
            json.dump(matches, f, ensure_ascii=False, indent=2)
        logger.info(f"Saved {len(matches)} screener matches to cache {cache_f.name}")
    except Exception as e:
        logger.warning(f"Failed to save screener cache: {e}")

def scan_market_strategy(
    strategy_name: str, 
    symbols: list[str] | None = None,
    universe: str = "core",
    lookback_bars: int = 20,
    use_cache: bool = True,
    progress_callback: Callable[[int, int, int, float], None] | None = None,
    stop_event: threading.Event | None = None
) -> list[dict[str, Any]]:
    """Scan market universe against strategy using real TDX historical bars and return matched stocks.
    
    Args:
        strategy_name: Identifier for strategy in registry
        symbols: Optional custom list of symbols. If None, loaded based on universe.
        universe: Universe tier: 'core' (35), 'hs300' (300), 'zz500' (500), 'zz1000' (1000), 'all' (5200+)
        lookback_bars: Signal trigger lookback window
        use_cache: If True, check disk cache for today's completed scan
        progress_callback: Optional callable(processed, total, matches_count, percent)
        stop_event: Optional threading.Event to abort early
    """
    st = get_strategy(strategy_name)
    
    # 1. Check disk cache if symbols is not custom
    if not symbols and use_cache:
        cached = _load_cache(strategy_name, universe)
        if cached is not None:
            if progress_callback:
                progress_callback(len(cached), len(cached), len(cached), 100.0)
            return cached

    if not symbols:
        symbols = get_universe_symbols(universe)
        
    total_count = len(symbols)
    matched: list[dict[str, Any]] = []
    
    for idx, sym in enumerate(symbols, 1):
        if stop_event is not None and stop_event.is_set():
            logger.info(f"Scan aborted by stop_event at {idx}/{total_count}")
            break

        try:
            df = fetch_security_kline(sym, period="DAY", count=140)
            if df is None or len(df) < 20:
                pass
            else:
                sig_df = st.generate_signals(df)
                if sig_df is not None and "buy_signal" in sig_df.columns:
                    window_size = min(lookback_bars, len(sig_df))
                    recent_df = sig_df.iloc[-window_size:]
                    buy_mask = recent_df["buy_signal"].astype(bool)
                    
                    if buy_mask.any():
                        trigger_idx = buy_mask[buy_mask].index[-1]
                        trigger_bar = sig_df.loc[trigger_idx]
                        trigger_loc = sig_df.index.get_loc(trigger_idx)
                        last_bar = sig_df.iloc[-1]
                        
                        stock_name = get_stock_name(sym)
                        close_price = round(float(last_bar["close"]), 2)
                        trigger_price = round(float(trigger_bar["close"]), 2)
                        vol = int(last_bar["volume"])
                        amt_wan = round(float(last_bar.get("amount", 0.0)) / 10000.0, 1)

                        if trigger_loc > 0:
                            trigger_prev_close = float(sig_df.iloc[trigger_loc - 1]["close"])
                            signal_change_pct = round((trigger_price - trigger_prev_close) / trigger_prev_close * 100.0, 2) if trigger_prev_close > 0 else 0.0
                        elif "change_pct" in trigger_bar and pd.notna(trigger_bar["change_pct"]):
                            signal_change_pct = round(float(trigger_bar["change_pct"]), 2)
                        else:
                            signal_change_pct = 0.0

                        since_signal_pct = round((close_price - trigger_price) / trigger_price * 100.0, 2) if trigger_price > 0 else 0.0

                        if len(sig_df) >= 2:
                            last_prev_close = float(sig_df.iloc[-2]["close"])
                            latest_change_pct = round((close_price - last_prev_close) / last_prev_close * 100.0, 2) if last_prev_close > 0 else 0.0
                        else:
                            latest_change_pct = 0.0
                        
                        signal_date = str(trigger_bar.get("datetime", ""))
                        if " " in signal_date:
                            signal_date = signal_date.split(" ")[0]
                        elif len(signal_date) == 8 and signal_date.isdigit():
                            signal_date = f"{signal_date[:4]}-{signal_date[4:6]}-{signal_date[6:]}"
                            
                        days_ago = len(sig_df) - 1 - sig_df.index.get_loc(trigger_idx)
                        status_label = "今日触发" if days_ago == 0 else f"{days_ago}日前触发"

                        matched.append({
                            "symbol": sym,
                            "code": sym,
                            "name": stock_name,
                            "display": f"{sym} {stock_name}",
                            "strategy": st.display_name,
                            "strategy_id": strategy_name,
                            "price": close_price,
                            "change_pct": signal_change_pct,
                            "signal_change_pct": signal_change_pct,
                            "since_signal_pct": since_signal_pct,
                            "latest_change_pct": latest_change_pct,
                            "trigger_price": trigger_price,
                            "volume": vol,
                            "amount_wan": amt_wan,
                            "days_ago": days_ago,
                            "trigger_days_ago": days_ago,
                            "status_label": status_label,
                            "signal_date": signal_date or "最新交易日",
                            "trigger_date": signal_date or "最新交易日",
                        })
        except Exception as e:
            logger.debug(f"Strategy {strategy_name} scan error on {sym}: {e}")
            
        # Report progress every 3 stocks or on completion
        if progress_callback and (idx % 3 == 0 or idx == total_count):
            pct = round((idx / total_count) * 100.0, 1)
            progress_callback(idx, total_count, len(matched), pct)

    # Sort matches: most recent signals first (days_ago ascending), then by volume descending
    matched.sort(key=lambda x: (x.get("days_ago", 999), -x.get("volume", 0)))
    
    # Save to disk cache if full universe scan completed without abortion
    if (stop_event is None or not stop_event.is_set()) and not symbols:
        _save_cache(strategy_name, universe, matched)

    return matched
