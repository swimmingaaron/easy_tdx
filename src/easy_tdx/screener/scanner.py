"""Full Market Strategy Screener Scanner for easy_tdx with Real TDX Historical & Live Data."""
from __future__ import annotations
import logging
from typing import Any
import pandas as pd
from easy_tdx.strategies.registry import get_strategy
from easy_tdx.stock_lookup import get_stock_name, COMMON_STOCKS
from easy_tdx.market_data import fetch_security_kline

logger = logging.getLogger(__name__)

# Active scanning universe covering key liquid sectors across A-Shares
DEFAULT_SCAN_UNIVERSE = [
    "600660", "300223", "000001", "600123", "002345", "300142", "601216", 
    "002415", "300750", "600519", "000002", "000063", "000333", "000651", 
    "000725", "000858", "002230", "002475", "002594", "300059", "300760", 
    "600000", "600028", "600030", "600036", "600887", "601318", "601857", 
    "601888", "601899", "603259", "688981", "301151", "300413", "600227"
]

def scan_market_strategy(
    strategy_name: str, 
    symbols: list[str] | None = None,
    lookback_bars: int = 20
) -> list[dict[str, Any]]:
    """Scan market universe against strategy using real TDX historical bars and return matched stocks."""
    st = get_strategy(strategy_name)
    if not symbols:
        symbols = DEFAULT_SCAN_UNIVERSE
        
    matched: list[dict[str, Any]] = []
    
    for sym in symbols:
        try:
            df = fetch_security_kline(sym, period="DAY", count=140)
            if df is None or len(df) < 20:
                continue
                
            sig_df = st.generate_signals(df)
            if sig_df is None or "buy_signal" not in sig_df.columns:
                continue
                
            # Check if buy_signal occurred in the recent trading window
            window_size = min(lookback_bars, len(sig_df))
            recent_df = sig_df.iloc[-window_size:]
            buy_mask = recent_df["buy_signal"].astype(bool)
            
            if buy_mask.any():
                # Locate the most recent buy signal bar
                trigger_idx = buy_mask[buy_mask].index[-1]
                trigger_bar = sig_df.loc[trigger_idx]
                trigger_loc = sig_df.index.get_loc(trigger_idx)
                last_bar = sig_df.iloc[-1]
                
                stock_name = get_stock_name(sym)
                close_price = round(float(last_bar["close"]), 2)
                trigger_price = round(float(trigger_bar["close"]), 2)
                vol = int(last_bar["volume"])
                amt_wan = round(float(last_bar.get("amount", 0.0)) / 10000.0, 1)

                # Calculate change_pct on signal_date (trigger_bar close vs its prior bar close)
                if trigger_loc > 0:
                    trigger_prev_close = float(sig_df.iloc[trigger_loc - 1]["close"])
                    signal_change_pct = round((trigger_price - trigger_prev_close) / trigger_prev_close * 100.0, 2) if trigger_prev_close > 0 else 0.0
                elif "change_pct" in trigger_bar and pd.notna(trigger_bar["change_pct"]):
                    signal_change_pct = round(float(trigger_bar["change_pct"]), 2)
                else:
                    signal_change_pct = 0.0

                # Return since signal
                since_signal_pct = round((close_price - trigger_price) / trigger_price * 100.0, 2) if trigger_price > 0 else 0.0

                # Latest day change
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
                    "days_ago": days_ago,
                    "trigger_days_ago": days_ago,
                    "status_label": status_label,
                    "signal_date": signal_date or "最新交易日",
                    "trigger_date": signal_date or "最新交易日",
                })
        except Exception as e:
            logger.debug(f"Strategy {strategy_name} scan error on {sym}: {e}")
            continue

    # Sort matches: most recent signals first (days_ago ascending), then by volume descending
    matched.sort(key=lambda x: (x.get("days_ago", 999), -x.get("volume", 0)))
    return matched
