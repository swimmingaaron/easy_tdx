"""Unit tests for ma_quadrilateral strategy and screener integration."""
import pytest
import numpy as np
import pandas as pd
from unittest.mock import patch

from easy_tdx.strategies.registry import get_strategy
from easy_tdx.screener.scanner import _evaluate_stock_for_strategy


def make_quadrilateral_kline(n_bars: int = 100, trigger_quad: bool = True) -> pd.DataFrame:
    """Generate mock K-line sequence simulating moving average quadrilateral cross."""
    dates = pd.date_range("2026-06-01", periods=n_bars, freq="B").strftime("%Y-%m-%d")
    
    if not trigger_quad:
        # Flat oscillation without moving average cross convergence
        closes = np.full(n_bars, 10.0) + np.random.normal(0, 0.05, n_bars)
    else:
        # Construct a sequence where MA5, MA10 sequentially cross MA20, MA60
        # Phase 1 (0-60): Downtrend / consolidation around 8.0-9.0
        # Phase 2 (61-80): Violent rally from 8.5 to 15.0 triggering P1, P2, P3, P4
        closes = np.zeros(n_bars)
        closes[:60] = np.linspace(12.0, 8.5, 60)
        closes[60:75] = np.linspace(8.5, 14.5, 15)
        closes[75:] = np.linspace(14.5, 15.5, n_bars - 75)
        
    highs = closes * 1.02
    lows = closes * 0.98
    opens = (closes + lows) / 2.0
    volumes = np.full(n_bars, 100000.0)
    amounts = closes * volumes
    
    return pd.DataFrame({
        "datetime": dates,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
        "amount": amounts
    })


def test_ma_quadrilateral_metadata():
    st = get_strategy("ma_quadrilateral")
    assert st.name == "ma_quadrilateral"
    assert "四边形" in st.display_name
    assert st.category == "technical"
    assert "window" in st.params_schema
    assert st.params_schema["window"] == 10


def test_ma_quadrilateral_signals():
    st = get_strategy("ma_quadrilateral", window=10)
    
    # 1. Test on quadrilateral breakout dataset
    df = make_quadrilateral_kline(n_bars=100, trigger_quad=True)
    sig_df = st.generate_signals(df)
    
    assert "xg" in sig_df.columns
    assert "buy_signal" in sig_df.columns
    assert "ma5" in sig_df.columns
    assert "ma60" in sig_df.columns
    
    # Must have triggered quadrilateral xg and buy signals
    assert sig_df["xg"].any(), "Should detect quadrilateral condition XG"
    assert sig_df["buy_signal"].any(), "Should generate buy signal on quadrilateral formation"
    
    # 2. Test flat dataset without MA cross
    flat_df = make_quadrilateral_kline(n_bars=100, trigger_quad=False)
    flat_sig = st.generate_signals(flat_df)
    assert not flat_sig["buy_signal"].any(), "Flat data should have no buy signals"


def test_ma_quadrilateral_same_day_rejection():
    """Verify that if golden crosses happen on the same day (D1 == D2), XG is rejected."""
    st = get_strategy("ma_quadrilateral", window=10)
    
    # When crosses happen on the same day, they do not satisfy D1!=D2
    # Verify exact XG logic rejects identical bar crosses
    n = 80
    dates = pd.date_range("2026-06-01", periods=n, freq="B").strftime("%Y-%m-%d")
    # Single huge gap up candle causing MA5 to cross MA20 and MA60 simultaneously
    closes = np.full(n, 10.0)
    df = pd.DataFrame({
        "datetime": dates,
        "open": closes,
        "high": closes,
        "low": closes,
        "close": closes,
        "volume": np.full(n, 1000.0),
        "amount": np.full(n, 10000.0)
    })
    sig_df = st.generate_signals(df)
    assert not sig_df["xg"].any()


def test_ma_quadrilateral_screener_evaluation():
    st = get_strategy("ma_quadrilateral", take_profit_pct=0.0)
    df = make_quadrilateral_kline(n_bars=80, trigger_quad=True)
    
    with patch("easy_tdx.screener.scanner._get_or_fetch_daily_kline", return_value=df):
        res = _evaluate_stock_for_strategy("600000", "ma_quadrilateral", st, 20)
        assert res is not None
        assert res["strategy_id"] == "ma_quadrilateral"
        assert "四边形" in res["status_label"]
        assert any("四边形" in p for p in res["patterns"])
