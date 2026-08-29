"""Verification script for ZigBreakoutStrategy."""
import numpy as np
import pandas as pd

from easy_tdx.backtest.engine import BacktestEngine
from easy_tdx.backtest.strategies.builtin import ZigBreakoutStrategy

np.random.seed(42)
n = 200
dates = pd.date_range("2025-01-01", periods=n, freq="B")
close = np.cumprod(1 + np.random.normal(0.001, 0.025, n)) * 100
df = pd.DataFrame(
    {
        "datetime": dates,
        "open": close * 0.995,
        "high": close * 1.025,
        "low": close * 0.975,
        "close": close,
        "vol": np.random.uniform(5000, 20000, n),
        "amount": np.random.uniform(5e5, 2e6, n),
    }
)

result = BacktestEngine(ZigBreakoutStrategy, cash=100000).run(df)
perf = result.performance
print("=== ZigBreakoutStrategy (Plan 1) Verification ===")
print(f"Total return  : {perf['total_return']*100:.2f}%")
print(f"Total trades  : {perf['total_trades']}")
print(f"Win rate      : {perf.get('win_rate', 0)*100:.1f}%")
print()
print("Trade records:")
print(result.trades[["datetime", "direction", "size", "price", "pnl"]].to_string(index=False))

assert perf["total_trades"] > 0, "No trades generated"
print()
print("PASS: ZigBreakoutStrategy verified successfully.")
