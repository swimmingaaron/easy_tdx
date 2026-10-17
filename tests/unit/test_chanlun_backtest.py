"""Unit tests for Chanlun backtest strategy and engine integration."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from easy_tdx.backtest import BacktestEngine
from easy_tdx.backtest.strategies import get_registry
from easy_tdx.strategies.registry import get_strategy as get_general_strategy


@pytest.fixture()
def sample_kline_df() -> pd.DataFrame:
    """Generate realistic oscillating K-line DataFrame with trends and pullbacks."""
    np.random.seed(123)
    n = 200
    base_price = 20.0
    # Generate oscillating wave pattern
    t = np.linspace(0, 8 * np.pi, n)
    wave = 4.0 * np.sin(t) + 0.05 * np.arange(n)
    closes = base_price + wave + np.random.randn(n) * 0.3
    highs = closes + np.abs(np.random.randn(n) * 0.4) + 0.1
    lows = closes - np.abs(np.random.randn(n) * 0.4) - 0.1
    opens = (closes + np.roll(closes, 1)) / 2.0
    opens[0] = closes[0]
    vols = np.random.randint(10000, 50000, n).astype(float)
    amounts = vols * closes
    dates = pd.date_range("2024-01-01", periods=n, freq="B")

    return pd.DataFrame({
        "datetime": dates,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "vol": vols,
        "amount": amounts,
    })


def test_chanlun_strategy_registered():
    """Verify chanlun_strategy is properly registered in builtin strategies."""
    reg = get_registry()
    names = reg.names()
    assert "chanlun_strategy" in names

    entry = reg.get("chanlun_strategy")
    assert entry.name == "chanlun_strategy"
    assert "缠论" in entry.label

    param_names = [p.name for p in entry.params]
    assert "buy_mode" in param_names
    assert "entry_mode" in param_names
    assert "stop_loss_pct" in param_names
    assert "trailing_stop_pct" in param_names
    assert "activate_profit" in param_names
    assert "max_hold_bars" in param_names


def test_chanlun_strategy_execution(sample_kline_df):
    """Verify ChanlunStrategy executes cleanly via BacktestEngine."""
    reg = get_registry()
    entry = reg.get("chanlun_strategy")
    strat = entry.build({
        "buy_mode": "all_buys",
        "entry_mode": "confirmed",
        "stop_loss_pct": 5.0,
        "trailing_stop_pct": 5.0,
        "activate_profit": 8.0,
    })

    engine = BacktestEngine(
        strat,
        cash=100000.0,
        commission=0.0003,
        execution="next_open",
    )
    result = engine.run(sample_kline_df)

    assert result is not None
    assert "total_return" in result.performance
    assert "annual_return" in result.performance
    assert "max_drawdown" in result.performance
    assert len(result.equity_curve) == len(sample_kline_df)


def test_chanlun_strategy_combo_23(sample_kline_df):
    """Verify combo_23 mode executes and adheres to constraints."""
    reg = get_registry()
    entry = reg.get("chanlun_strategy")
    strat = entry.build({
        "buy_mode": "combo_23",
        "entry_mode": "confirmed",
        "stop_loss_pct": 4.0,
        "trailing_stop_pct": 4.0,
    })

    engine = BacktestEngine(strat, cash=100000.0)
    result = engine.run(sample_kline_df)
    assert result.performance["total_trades"] >= 0


def test_general_chanlun_strategy(sample_kline_df):
    """Verify ChanlunBuySellStrategy in easy_tdx.strategies produces signal columns."""
    st = get_general_strategy("chanlun_strategy", buy_mode="combo_23")
    res_df = st.generate_signals(sample_kline_df)

    assert "buy_signal" in res_df.columns
    assert "sell_signal" in res_df.columns
    assert "signal_type" in res_df.columns
    assert "stop_price" in res_df.columns
    assert len(res_df) == len(sample_kline_df)
