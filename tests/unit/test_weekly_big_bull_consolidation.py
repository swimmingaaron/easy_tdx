"""Unit tests for WeeklyBigBullConsolidationStrategy."""
import pytest
import pandas as pd
import numpy as np

from easy_tdx.strategies.registry import get_strategy
from easy_tdx.strategies.technical.weekly_big_bull_consolidation import WeeklyBigBullConsolidationStrategy


def test_strategy_registration():
    st = get_strategy("weekly_big_bull_consolidation")
    assert st is not None
    assert st.name == "weekly_big_bull_consolidation"
    assert "大阳横盘调整" in st.display_name
    assert st.category == "technical"
    assert "prior_drop_pct" in st.params_schema


def test_synthetic_weekly_pattern():
    # Build synthetic weekly dataframe:
    # 1. 20 weeks drop from 20.0 to 12.0 (> 30% drop)
    # 2. 1 week big bull candle: 12.0 -> 13.5 (+12.5%)
    # 3. 3 weeks sideways consolidation: 13.5, 13.4, 13.6 with volume shrinking
    # 4. Breakout
    
    dates = pd.date_range("2025-01-01", periods=30, freq="W")
    
    # 20 weeks decline:
    prices = list(np.linspace(20.0, 12.0, 20))
    # 1 week big bull:
    prices.append(13.5)
    # 3 weeks consolidation:
    prices.extend([13.4, 13.3, 13.6])
    # 6 weeks subsequent:
    prices.extend([15.0, 17.0, 19.0, 21.0, 22.0, 20.0])
    
    df = pd.DataFrame({
        "datetime": dates,
        "open": prices,
        "high": [p * 1.02 for p in prices],
        "low": [p * 0.98 for p in prices],
        "close": prices,
        "volume": [10000] * 20 + [50000] + [20000, 18000, 22000] + [60000] * 6,
    })
    
    # Adjust big bull candle:
    # idx 20: open 12.0, close 13.5 (+12.5%), low 11.9, high 13.8
    df.loc[20, "open"] = 12.0
    df.loc[20, "close"] = 13.5
    df.loc[20, "low"] = 11.9
    df.loc[20, "high"] = 13.8
    
    # Cons bars (21, 22, 23):
    df.loc[21, "open"] = 13.5
    df.loc[21, "close"] = 13.4
    df.loc[21, "low"] = 13.0
    df.loc[21, "high"] = 13.7
    
    df.loc[22, "open"] = 13.4
    df.loc[22, "close"] = 13.3
    df.loc[22, "low"] = 12.9
    df.loc[22, "high"] = 13.6
    
    df.loc[23, "open"] = 13.3
    df.loc[23, "close"] = 13.6
    df.loc[23, "low"] = 13.1
    df.loc[23, "high"] = 13.8
    
    st = WeeklyBigBullConsolidationStrategy()
    res = st.generate_signals(df)
    
    assert "buy_signal" in res.columns
    # After at least 2 weeks of consolidation (idx 22 and idx 23), pattern should be recognized
    assert res.loc[22, "buy_signal"] == True
    assert res.loc[23, "buy_signal"] == True
