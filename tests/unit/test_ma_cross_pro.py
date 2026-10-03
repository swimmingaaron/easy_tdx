import pytest
import pandas as pd
import numpy as np
from easy_tdx.backtest.strategies import get_registry
from easy_tdx.backtest.engine import BacktestEngine

def test_ma_cross_pro_registration():
    reg = get_registry()
    assert "ma_cross_pro" in reg.names()
    entry = reg.get("ma_cross_pro")
    assert entry.label == "双均线优化战法"
    schema = entry.to_schema()
    assert "fast" in [p["name"] for p in schema["params"]]
    assert "slow" in [p["name"] for p in schema["params"]]

def test_ma_cross_pro_backtest_run():
    reg = get_registry()
    entry = reg.get("ma_cross_pro")
    strat_cls = entry.strategy_cls

    # 构造含金叉与回踩的测试行情
    dates = pd.date_range("2024-01-01", periods=60)
    prices = [10.0] * 20 + [10.0 + i * 0.5 for i in range(20)] + [20.0 - i * 0.2 for i in range(20)]
    df = pd.DataFrame({
        "datetime": dates,
        "open": prices,
        "high": [p + 0.5 for p in prices],
        "low": [p - 0.5 for p in prices],
        "close": prices,
        "vol": [10000] * 60,
        "amount": [p * 10000 for p in prices],
    })

    engine = BacktestEngine(strat_cls, cash=100000)
    result = engine.run(df)
    assert result is not None
    assert result.equity_curve is not None
    assert result.performance is not None


