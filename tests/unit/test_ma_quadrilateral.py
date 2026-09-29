"""Unit tests for ma_quadrilateral strategy and screener integration."""
import pytest
import numpy as np
import pandas as pd
from unittest.mock import patch

from easy_tdx.strategies.registry import get_strategy
from easy_tdx.screener.scanner import _evaluate_stock_for_strategy


def make_quadrilateral_kline(n_bars: int = 95, trigger_quad: bool = True) -> pd.DataFrame:
    """Generate mock K-line sequence simulating moving average quadrilateral cross."""
    dates = pd.date_range("2026-05-01", periods=n_bars, freq="B").strftime("%Y-%m-%d")
    
    if not trigger_quad:
        # Pure flat sequence without moving average cross
        closes = np.full(n_bars, 10.0)
    else:
        # Construct a sequence where MA5, MA10 sequentially cross MA20, MA60 with stable MA60 > MA20 base:
        # Phase 1 (0-70): Downtrend / consolidation around 8.5 where MA60 > MA20 is stably maintained
        # Phase 2 (70-82): Violent rally from 8.5 to 14.5 triggering P1, P2, P3, P4
        # Phase 3 (82+): Air refueling consolidation above MA60
        closes = np.zeros(n_bars)
        closes[:70] = np.linspace(12.0, 8.5, 70)
        closes[70:82] = np.linspace(8.5, 14.5, 12)
        closes[82:] = np.linspace(14.5, 15.5, n_bars - 82)
        
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
    assert "pullback_window" in st.params_schema
    assert st.params_schema["pullback_window"] == 12


def test_ma_quadrilateral_signals():
    st = get_strategy("ma_quadrilateral", window=10)
    
    # 1. Test on quadrilateral breakout dataset
    df = make_quadrilateral_kline(n_bars=95, trigger_quad=True)
    sig_df = st.generate_signals(df)
    
    assert "xg" in sig_df.columns
    assert "buy_signal" in sig_df.columns
    assert "ma5" in sig_df.columns
    assert "ma60" in sig_df.columns
    assert "band_mm" in sig_df.columns
    assert "band_kk" in sig_df.columns
    assert "quad_regularity" in sig_df.columns
    assert "quad_buy_type" in sig_df.columns
    assert "quad_bottom_price" in sig_df.columns
    
    # Must have triggered quadrilateral xg and buy signals
    assert sig_df["xg"].any(), "Should detect quadrilateral condition XG"
    assert sig_df["buy_signal"].any(), "Should generate buy signal on quadrilateral formation"
    
    # Check regularity score and bottom price are positive on triggered bar
    triggered_bars = sig_df[sig_df["buy_signal"]]
    assert len(triggered_bars) > 0
    assert (triggered_bars["quad_regularity"] > 0).any()
    assert (triggered_bars["quad_bottom_price"] > 0).any()
    assert (triggered_bars["quad_buy_type"] != "").any()
    
    # 2. Test flat dataset without MA cross
    flat_df = make_quadrilateral_kline(n_bars=95, trigger_quad=False)
    flat_sig = st.generate_signals(flat_df)
    assert not flat_sig["buy_signal"].any(), "Flat data should have no buy signals"


def test_ma_quadrilateral_same_day_rejection():
    """Verify that if golden crosses happen on the same day (D1 == D2), XG is rejected."""
    st = get_strategy("ma_quadrilateral", window=10)
    
    n = 80
    dates = pd.date_range("2026-06-01", periods=n, freq="B").strftime("%Y-%m-%d")
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


def test_ma_quadrilateral_pullback_entry():
    """Test pullback entry (e.g. 回踩10日线抢筹 / 空中加油二次起爆 / 回踩20日线)."""
    st = get_strategy("ma_quadrilateral", window=12, pullback_window=10)
    df = make_quadrilateral_kline(n_bars=95, trigger_quad=True)
    
    sig_df = st.generate_signals(df)
    buy_types = set(sig_df[sig_df["buy_signal"]]["quad_buy_type"].values)
    valid_types = {
        "闭合加速", "沿5日线强攻", "回踩10日线", "回踩10日线抢筹",
        "空中加油二次起爆", "回踩20日线", "回踩60日线"
    }
    assert any(bt in valid_types for bt in buy_types)


def test_ma_quadrilateral_screener_evaluation():
    st = get_strategy("ma_quadrilateral", take_profit_pct=0.0)
    df = make_quadrilateral_kline(n_bars=95, trigger_quad=True)
    
    with patch("easy_tdx.screener.scanner._get_or_fetch_daily_kline", return_value=df):
        res = _evaluate_stock_for_strategy("600000", "ma_quadrilateral", st, 20)
        assert res is not None
        assert res["strategy_id"] == "ma_quadrilateral"
        assert "四边形" in res["status_label"]
        assert any("四边形" in p for p in res["patterns"])


def test_ma_quadrilateral_rejects_unstable_base():
    """Verify that when MA20 and MA60 dead-cross right before P1 (like 600233), it is rejected."""
    st = get_strategy("ma_quadrilateral", window=10)
    
    # Construct a dataset like 600233 where MA20 was ABOVE MA60 right before the rally
    n = 100
    dates = pd.date_range("2026-05-01", periods=n, freq="B").strftime("%Y-%m-%d")
    closes = np.full(n, 15.0)
    closes[:50] = 15.0
    closes[50:70] = 20.0  # Uptrend causing MA20 > MA60
    closes[70:78] = np.linspace(20.0, 16.0, 8)  # Sharp plunge causing MA20 to dive and cross MA60
    closes[78:88] = np.linspace(16.0, 19.0, 10)  # Quick rebound
    closes[88:] = 19.0
    
    df = pd.DataFrame({
        "datetime": dates,
        "open": closes,
        "high": closes * 1.01,
        "low": closes * 0.99,
        "close": closes,
        "volume": np.full(n, 1000.0),
        "amount": np.full(n, 10000.0)
    })
    sig_df = st.generate_signals(df)
    assert not sig_df["xg"].any(), "Should reject pattern where MA20 dead-crossed MA60 right before P1 (like 600233)"
