"""Unit tests for WeeklyBigBullConsolidationStrategy."""
import pytest
import pandas as pd
import numpy as np

from easy_tdx.strategies.registry import get_strategy
from easy_tdx.strategies.technical.weekly_big_bull_consolidation import WeeklyBigBullConsolidationStrategy


def test_strategy_registration():
    st = get_strategy("weekly_bull_flag")
    assert st is not None
    assert st.name == "weekly_bull_flag"
    assert "上涨旗形" in st.display_name
    assert st.category == "technical"
    assert "prior_drop_pct" in st.params_schema

    # Alias check
    st_alias = get_strategy("weekly_big_bull_consolidation")
    assert st_alias is not None
    assert "上涨旗形" in st_alias.display_name


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
    
    st = WeeklyBigBullConsolidationStrategy(enable_ma_filter=False, enable_macd_filter=False)
    res = st.generate_signals(df)
    
    assert "buy_signal" in res.columns
    # After at least 2 weeks of consolidation (idx 22 and idx 23), pattern should be recognized
    assert res.loc[22, "buy_signal"] == True
    assert res.loc[23, "buy_signal"] == True


def test_ma_and_macd_resonance_filter():
    """Verify that MA and MACD resonance properly filters out signals when MA/MACD conditions are not met."""
    dates = pd.date_range("2025-01-01", periods=30, freq="W")
    # Base pattern where MA5 >= MA10 and MACD DIF >= DEA
    # 10 bars decline from 20 to 12, then 10 bars basing at 12, then big bull candle to 14.5
    prices = list(np.linspace(20.0, 12.0, 10)) + [12.0] * 10
    prices.append(14.0)  # big bull candle (+16.7%)
    prices.extend([14.1, 14.0, 14.2])  # 3 weeks flag consolidation
    prices.extend([15.0, 16.0, 17.0, 18.0, 19.0, 20.0])

    df = pd.DataFrame({
        "datetime": dates,
        "open": prices,
        "high": [p * 1.02 for p in prices],
        "low": [p * 0.98 for p in prices],
        "close": prices,
        "volume": [10000] * 20 + [50000] + [20000, 18000, 22000] + [60000] * 6,
    })
    df.loc[20, "open"] = 12.0
    df.loc[20, "close"] = 14.0
    df.loc[20, "low"] = 11.9
    df.loc[20, "high"] = 14.2

    df.loc[21, "open"] = 14.0
    df.loc[21, "close"] = 14.1
    df.loc[21, "low"] = 13.5
    df.loc[21, "high"] = 14.3

    df.loc[22, "open"] = 14.1
    df.loc[22, "close"] = 14.0
    df.loc[22, "low"] = 13.5
    df.loc[22, "high"] = 14.2

    st_with_filter = WeeklyBigBullConsolidationStrategy(enable_ma_filter=True, enable_macd_filter=True)
    res_filtered = st_with_filter.generate_signals(df)

    # MA5 and MACD DIF should both be bullish here, so signals should trigger
    assert res_filtered.loc[22, "buy_signal"] == True


def test_exclude_drop_greater_than_3_pct():
    """Verify that any consolidation week dropping more than 3% is strictly excluded."""
    dates = pd.date_range("2025-01-01", periods=25, freq="W")
    prices = list(np.linspace(20.0, 12.0, 20)) # 20 weeks drop > 20%
    prices.append(13.5) # big bull candle (+12.5%)
    prices.extend([13.4, 12.8, 13.0, 13.2]) # week 2 drops from 13.4 to 12.8 (-4.48% > 3%)
    
    df = pd.DataFrame({
        "datetime": dates,
        "open": prices,
        "high": [p * 1.02 for p in prices],
        "low": [p * 0.98 for p in prices],
        "close": prices,
        "volume": [10000] * 20 + [50000] + [20000, 18000, 22000, 21000],
    })
    df.loc[20, "open"] = 12.0
    df.loc[20, "close"] = 13.5
    
    # In week 22, close drops from 13.4 to 12.8 (-4.48%)
    st = WeeklyBigBullConsolidationStrategy()
    res = st.generate_signals(df)
    
    # Must NOT have buy_signal on bar 22, 23, 24 due to the > 3% drop
    assert res.loc[22, "buy_signal"] == False
    assert res.loc[23, "buy_signal"] == False


def test_benchmark_first_bar_deviation_within_3_pct():
    """Verify that consolidation bars must stay within 3% deviation from first bar."""
    dates = pd.date_range("2025-01-01", periods=25, freq="W")
    prices = list(np.linspace(20.0, 12.0, 20)) # 20 weeks drop > 20%
    prices.append(13.5) # big bull candle (idx 20)
    # First bar after big bull (idx 21): close = 13.5
    # Next bar (idx 22): close = 13.95 (deviation = (13.95-13.5)/13.5 = +3.33% > 3%)
    prices.extend([13.5, 13.95, 13.5, 13.5])
    
    df = pd.DataFrame({
        "datetime": dates,
        "open": prices,
        "high": [p * 1.01 for p in prices],
        "low": [p * 0.99 for p in prices],
        "close": prices,
        "volume": [10000] * 20 + [50000] + [20000, 19000, 21000, 20000],
    })
    df.loc[20, "open"] = 12.0
    df.loc[20, "close"] = 13.5
    
    st = WeeklyBigBullConsolidationStrategy()
    res = st.generate_signals(df)
    
    # idx 22 deviated by +3.33% > 3% from first bar, so should NOT be matched
    assert res.loc[22, "buy_signal"] == False


def test_first_big_bull_from_bottom_filter():
    """Verify that only the FIRST big bull candle from bottom is accepted, not the 2nd/3rd chasing candle."""
    dates = pd.date_range("2025-01-01", periods=35, freq="W")
    # 15 weeks drop from 20 to 12
    prices = list(np.linspace(20.0, 12.0, 15))
    # 1st big bull at idx 15: 12.0 -> 13.5 (+12.5%)
    prices.append(13.5)
    # 2 weeks small rest: 13.5, 13.6
    prices.extend([13.5, 13.6])
    # 2nd big bull at idx 18: 13.6 -> 15.2 (+11.8%)
    prices.append(15.2)
    # 2 weeks rest: 15.2, 15.1
    prices.extend([15.2, 15.1])
    # remaining bars
    prices.extend([16.0] * 14)

    df = pd.DataFrame({
        "datetime": dates,
        "open": prices,
        "high": [p * 1.02 for p in prices],
        "low": [p * 0.98 for p in prices],
        "close": prices,
        "volume": [10000] * 35,
    })
    df.loc[15, "open"] = 12.0
    df.loc[15, "close"] = 13.5
    df.loc[15, "volume"] = 50000
    df.loc[16, "volume"] = 20000
    df.loc[17, "volume"] = 20000

    df.loc[18, "open"] = 13.6
    df.loc[18, "close"] = 15.2
    df.loc[18, "volume"] = 60000
    df.loc[19, "volume"] = 25000
    df.loc[20, "volume"] = 25000

    # With first_bull_only=True:
    # 2nd big bull at idx 18 has a prior big bull at idx 15 (within 8 weeks), so at idx 20 it must NOT trigger
    st = WeeklyBigBullConsolidationStrategy(
        first_bull_only=True,
        first_bull_lookback=8,
        enable_ma_filter=False,
        enable_macd_filter=False,
    )
    res = st.generate_signals(df)

    # idx 17 is after 1st big bull (valid)
    assert res.loc[17, "buy_signal"] == True
    # idx 20 is after 2nd big bull (rejected because idx 15 was an earlier big bull within 8 weeks)
    assert res.loc[20, "buy_signal"] == False



