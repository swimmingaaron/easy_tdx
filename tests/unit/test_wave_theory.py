"""Unit tests for wave_theory_impulse strategy and screener integration."""
import pytest
import numpy as np
import pandas as pd
from unittest.mock import patch

from easy_tdx.strategies.registry import get_strategy
from easy_tdx.screener.scanner import _evaluate_stock_for_strategy


def make_wave_kline(n_bars: int = 80, simulate_wave: bool = True) -> pd.DataFrame:
    """Generate mock K-line sequence simulating Elliott Wave 1 -> 2 -> 3."""
    dates = pd.date_range("2026-06-01", periods=n_bars, freq="B").strftime("%Y-%m-%d")
    
    if not simulate_wave:
        # Flat oscillation without wave impulse
        closes = np.full(n_bars, 10.0) + np.random.normal(0, 0.1, n_bars)
        highs = closes + 0.1
        lows = closes - 0.1
        opens = closes
        volumes = np.full(n_bars, 100000.0)
    else:
        # Build 1 wave, 2 wave, and 3 wave
        # Bars 0-30: base consolidation around 10.0
        # Bars 31-45: Wave 1 rally from 10.0 to 13.0 (+30%)
        # Bars 46-55: Wave 2 pullback from 13.0 to 11.5 (retrace 50%)
        # Bars 56-65: Wave 3 breakout from 11.5 to 14.5
        closes = np.zeros(n_bars)
        closes[:30] = np.linspace(9.8, 10.0, 30)
        closes[30:45] = np.linspace(10.0, 13.0, 15)
        closes[45:55] = np.linspace(13.0, 11.5, 10)
        closes[55:65] = np.linspace(11.5, 14.2, 10)
        closes[65:] = np.linspace(14.2, 14.8, n_bars - 65)
        
        highs = closes * 1.015
        lows = closes * 0.985
        opens = (closes + lows) / 2.0
        
        volumes = np.full(n_bars, 100000.0)
        volumes[30:45] = 200000.0  # Wave 1 volume expansion
        volumes[45:55] = 80000.0   # Wave 2 volume contraction
        volumes[55:65] = 250000.0  # Wave 3 volume explosion
        
    df = pd.DataFrame({
        "datetime": dates,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
        "amount": volumes * closes,
    })
    return df


def test_wave_theory_strategy_metadata():
    st = get_strategy("wave_theory_impulse")
    assert st is not None
    assert st.name == "wave_theory_impulse"
    assert "波浪理论主升3浪" in st.display_name
    assert st.category == "daily_analysis"


def test_wave_theory_signal_generation():
    st = get_strategy("wave_theory_impulse")
    df = make_wave_kline(n_bars=80, simulate_wave=True)
    sig_df = st.generate_signals(df)
    
    assert "buy_signal" in sig_df.columns
    assert "sell_signal" in sig_df.columns
    assert "wave_type" in sig_df.columns
    assert "wave1_rise" in sig_df.columns
    assert "wave2_retrace" in sig_df.columns
    
    # Must have triggered buy signals in Wave 3 zone (bars 56+)
    buys = sig_df["buy_signal"].astype(bool)
    assert buys.any(), "Should detect Wave 3 impulse on simulated wave data"
    
    # Flat data without wave structure should not trigger
    flat_df = make_wave_kline(n_bars=80, simulate_wave=False)
    flat_sig = st.generate_signals(flat_df)
    assert not flat_sig["buy_signal"].any(), "Flat data should have zero buy signals"


def test_wave_theory_screener_evaluation():
    st = get_strategy("wave_theory_impulse")
    wave_df = make_wave_kline(n_bars=70, simulate_wave=True)
    
    with patch("easy_tdx.screener.scanner._get_or_fetch_daily_kline", return_value=wave_df):
        res = _evaluate_stock_for_strategy("600000", "wave_theory_impulse", st, 20)
        assert res is not None
        assert res["strategy_id"] == "wave_theory_impulse"
        assert "3浪" in res["status_label"]
        assert any("3浪" in p for p in res["patterns"])


def test_wave_theory_hongqingting_benchmark():
    """Verify 603116 (Hongqingting) matches Wave 3 impulse breakout."""
    from easy_tdx.market_data import fetch_security_kline
    st = get_strategy("wave_theory_impulse")
    df = fetch_security_kline("603116", period="DAY", count=120)
    assert df is not None and len(df) >= 60
    
    sig_df = st.generate_signals(df)
    assert sig_df["buy_signal"].any(), "603116 must trigger 3浪突破过顶"
    
    # Verify the wave type is strictly breakout over Wave 1 high
    breakouts = sig_df[sig_df["buy_signal"]]
    assert (breakouts["wave_type"] == "3浪突破过顶").all(), "All wave types must strictly be '3浪突破过顶'"
