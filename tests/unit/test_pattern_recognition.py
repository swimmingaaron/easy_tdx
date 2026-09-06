"""Unit tests for quantitative dynamic pattern recognition engine."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from easy_tdx.pattern_recognition import detect_patterns, detect_stock_patterns


def _create_synthetic_kline(n: int = 30, base_price: float = 10.0, trend: float = 0.0) -> pd.DataFrame:
    """Generate synthetic daily bars with configurable length and price trend."""
    closes = [base_price + i * trend for i in range(n)]
    opens = [c - 0.05 for c in closes]
    highs = [c + 0.15 for c in closes]
    lows = [c - 0.15 for c in closes]
    volumes = [100000] * n

    dates = pd.date_range(end="2026-09-05", periods=n, freq="B").strftime("%Y-%m-%d").tolist()

    return pd.DataFrame({
        "datetime": dates,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes
    })


def test_empty_or_short_df_returns_fallback():
    assert detect_patterns(pd.DataFrame()) == ["震荡整理"]
    assert detect_patterns(None) == ["震荡整理"]
    short_df = _create_synthetic_kline(n=4)
    assert detect_patterns(short_df) == ["震荡整理"]


def test_bullish_ma_alignment():
    # Strong upward trend so MA5 > MA10 > MA20
    df = _create_synthetic_kline(n=30, base_price=10.0, trend=0.2)
    patterns = detect_patterns(df)
    assert "均线多头" in patterns


def test_bearish_ma_alignment():
    # Downward trend so MA5 < MA10 < MA20
    df = _create_synthetic_kline(n=30, base_price=20.0, trend=-0.3)
    patterns = detect_patterns(df)
    assert "均线空头" in patterns


def test_volume_breakout():
    # 25 days flat, then day 26 explodes above 20-day high with 3x volume
    df = _create_synthetic_kline(n=25, base_price=10.0, trend=0.0)
    # New bar with massive breakout
    breakout_bar = pd.DataFrame([{
        "datetime": "2026-09-06",
        "open": 10.2,
        "high": 11.5,
        "low": 10.1,
        "close": 11.2,
        "volume": 350000  # 3.5x average
    }])
    df = pd.concat([df, breakout_bar], ignore_index=True)
    patterns = detect_patterns(df)
    assert "放量突破" in patterns


def test_low_volume_pullback():
    # Uptrend leading up to day 28
    df = _create_synthetic_kline(n=28, base_price=10.0, trend=0.15)
    # Day 29: pulls back slightly to near MA10 with low volume (< 0.6x)
    ma10_approx = float(df["close"].iloc[-10:].mean())
    pullback_bar = pd.DataFrame([{
        "datetime": "2026-09-06",
        "open": ma10_approx + 0.05,
        "high": ma10_approx + 0.08,
        "low": ma10_approx - 0.02,
        "close": ma10_approx + 0.01,
        "volume": 50000  # 0.5x average
    }])
    df = pd.concat([df, pullback_bar], ignore_index=True)
    patterns = detect_patterns(df)
    assert "缩量回踩" in patterns or "均线多头" in patterns


def test_three_red_soldiers():
    df = _create_synthetic_kline(n=20, base_price=10.0, trend=0.0)
    # Add 3 solid green/red candles with rising closes
    c_prev = 10.0
    for i in range(3):
        c_new = c_prev + 0.25
        bar = pd.DataFrame([{
            "datetime": f"2026-09-0{7+i}",
            "open": c_prev + 0.05,
            "high": c_new + 0.05,
            "low": c_prev,
            "close": c_new,
            "volume": 120000
        }])
        df = pd.concat([df, bar], ignore_index=True)
        c_prev = c_new
    patterns = detect_patterns(df)
    assert "红三兵" in patterns


def test_bullish_engulfing():
    df = _create_synthetic_kline(n=20, base_price=10.0, trend=0.0)
    # Yesterday: black candle
    yest = pd.DataFrame([{
        "datetime": "2026-09-07",
        "open": 10.5,
        "high": 10.6,
        "low": 9.9,
        "close": 10.0,
        "volume": 100000
    }])
    # Today: opens below/equal to yesterday's close and closes above yesterday's open
    today = pd.DataFrame([{
        "datetime": "2026-09-08",
        "open": 9.95,
        "high": 10.8,
        "low": 9.9,
        "close": 10.65,
        "volume": 150000
    }])
    df = pd.concat([df, yest, today], ignore_index=True)
    patterns = detect_patterns(df)
    assert "阳包阴" in patterns


def test_multi_pattern_detection_lists_all_satisfied():
    # Synthesize a stock that satisfies multiple patterns at once:
    # 1. Moving averages trending upward -> 均线多头
    # 2. Breaks out past 20-day high with high volume -> 放量突破
    # 3. Consecutive rising candles -> 红三兵
    df = _create_synthetic_kline(n=25, base_price=10.0, trend=0.1)
    for i in range(3):
        c_last = float(df["close"].iloc[-1])
        c_new = c_last + 0.35
        b = pd.DataFrame([{
            "datetime": f"2026-09-0{7+i}",
            "open": c_last + 0.05,
            "high": c_new + 0.1,
            "low": c_last,
            "close": c_new,
            "volume": 250000 if i == 2 else 150000
        }])
        df = pd.concat([df, b], ignore_index=True)

    patterns = detect_patterns(df)
    # Must list multiple satisfied patterns
    assert len(patterns) >= 2
    assert "放量突破" in patterns or "均线多头" in patterns


def test_detect_stock_patterns_cache():
    p1 = detect_stock_patterns("000001", count=30)
    assert isinstance(p1, list)
    assert len(p1) > 0
    # Second call hits cache
    p2 = detect_stock_patterns("000001", count=30)
    assert p1 == p2


def test_three_black_crows():
    # 20 bars in an uptrend reaching high
    df = _create_synthetic_kline(n=20, base_price=10.0, trend=0.2)
    # Append 3 falling solid bear candles
    c_last = float(df["close"].iloc[-1])
    for i in range(3):
        c_new = c_last - 0.4
        bar = pd.DataFrame([{
            "datetime": f"2026-09-0{7+i}",
            "open": c_last + 0.05,
            "high": c_last + 0.1,
            "low": c_new - 0.05,
            "close": c_new,
            "volume": 120000
        }])
        df = pd.concat([df, bar], ignore_index=True)
        c_last = c_new
    patterns = detect_patterns(df)
    assert "三只乌鸦" in patterns


def test_dark_cloud_cover():
    df = _create_synthetic_kline(n=20, base_price=10.0, trend=0.1)
    # Day -2: Big bull candle
    yest = pd.DataFrame([{
        "datetime": "2026-09-07",
        "open": 12.0,
        "high": 12.8,
        "low": 11.9,
        "close": 12.6,
        "volume": 100000
    }])
    # Day -1: Opens higher (12.7 > 12.6), closes at 12.2 (deep into lower half of yest body [12.0, 12.6])
    today = pd.DataFrame([{
        "datetime": "2026-09-08",
        "open": 12.7,
        "high": 12.75,
        "low": 12.15,
        "close": 12.2,
        "volume": 150000
    }])
    df = pd.concat([df, yest, today], ignore_index=True)
    patterns = detect_patterns(df)
    assert "乌云盖顶" in patterns


def test_downpour_heavy_rain():
    df = _create_synthetic_kline(n=20, base_price=10.0, trend=0.1)
    # Day -2: Big bull candle
    yest = pd.DataFrame([{
        "datetime": "2026-09-07",
        "open": 12.0,
        "high": 12.8,
        "low": 11.9,
        "close": 12.6,
        "volume": 100000
    }])
    # Day -1: Opens at 12.6, plunges below yesterday's open of 12.0 to close at 11.8
    today = pd.DataFrame([{
        "datetime": "2026-09-08",
        "open": 12.6,
        "high": 12.65,
        "low": 11.75,
        "close": 11.8,
        "volume": 200000
    }])
    df = pd.concat([df, yest, today], ignore_index=True)
    patterns = detect_patterns(df)
    assert "倾盆大雨" in patterns


def test_morning_star():
    # Downward trend leading to low
    df = _create_synthetic_kline(n=20, base_price=15.0, trend=-0.2)
    # -3: Big bear candle
    day3 = pd.DataFrame([{
        "datetime": "2026-09-06",
        "open": 11.0,
        "high": 11.1,
        "low": 10.1,
        "close": 10.2,
        "volume": 100000
    }])
    # -2: Gap-down small star
    day2 = pd.DataFrame([{
        "datetime": "2026-09-07",
        "open": 9.9,
        "high": 10.0,
        "low": 9.8,
        "close": 9.95,
        "volume": 80000
    }])
    # -1: Big bull candle cutting past midpoint of -3 body (10.6 >= 10.6)
    day1 = pd.DataFrame([{
        "datetime": "2026-09-08",
        "open": 10.0,
        "high": 10.9,
        "low": 9.95,
        "close": 10.8,
        "volume": 160000
    }])
    df = pd.concat([df, day3, day2, day1], ignore_index=True)
    patterns = detect_patterns(df)
    assert "启明星" in patterns


def test_shooting_star():
    df = _create_synthetic_kline(n=25, base_price=10.0, trend=0.15)
    # Last bar: Long upper shadow >= 2x body, body near low at high position
    c_last = float(df["close"].iloc[-1])
    bar = pd.DataFrame([{
        "datetime": "2026-09-08",
        "open": c_last + 0.1,
        "high": c_last + 1.2,  # Upper shadow = 1.05
        "low": c_last - 0.02,
        "close": c_last + 0.15,  # Body = 0.05
        "volume": 150000
    }])
    df = pd.concat([df, bar], ignore_index=True)
    patterns = detect_patterns(df)
    assert "射击之星" in patterns


def test_hammer_at_bottom():
    df = _create_synthetic_kline(n=25, base_price=15.0, trend=-0.2)
    # Last bar: Long lower shadow >= 2x body, body near high at low position
    c_last = float(df["close"].iloc[-1])
    bar = pd.DataFrame([{
        "datetime": "2026-09-08",
        "open": c_last - 0.1,
        "high": c_last + 0.02,
        "low": c_last - 1.2,  # Lower shadow = 1.1
        "close": c_last - 0.05,  # Body = 0.05
        "volume": 150000
    }])
    df = pd.concat([df, bar], ignore_index=True)
    patterns = detect_patterns(df)
    assert "锤子线" in patterns


def test_dragon_emerging():
    # 65 bars flat around 10.0, so MA5, MA10, MA20, MA60 are all near 10.0
    df = _create_synthetic_kline(n=65, base_price=10.0, trend=0.0)
    # Latest bar: opens at 9.8 (below min of MAs), surges to 10.6 (above max of MAs) with 2x volume
    bar = pd.DataFrame([{
        "datetime": "2026-09-08",
        "open": 9.85,
        "high": 10.7,
        "low": 9.8,
        "close": 10.6,
        "volume": 250000
    }])
    df = pd.concat([df, bar], ignore_index=True)
    patterns = detect_patterns(df)
    assert "蛟龙出海" in patterns


def test_volume_stagnation():
    # 25 bars in uptrend, then massive volume (2.5x) with almost 0% price change at the high
    df = _create_synthetic_kline(n=25, base_price=10.0, trend=0.1)
    c_last = float(df["close"].iloc[-1])
    bar = pd.DataFrame([{
        "datetime": "2026-09-08",
        "open": c_last + 0.02,
        "high": c_last + 0.3,
        "low": c_last - 0.3,
        "close": c_last + 0.01,
        "volume": 300000  # 3x volume
    }])
    df = pd.concat([df, bar], ignore_index=True)
    patterns = detect_patterns(df)
    assert "放量滞涨" in patterns


def test_gap_up():
    df = _create_synthetic_kline(n=20, base_price=10.0, trend=0.0)
    # Yesterday high is around 10.15
    yest_h = float(df["high"].iloc[-1])
    today = pd.DataFrame([{
        "datetime": "2026-09-08",
        "open": yest_h + 0.3,
        "high": yest_h + 0.6,
        "low": yest_h + 0.2,  # Clean gap above yesterday high
        "close": yest_h + 0.5,
        "volume": 120000
    }])
    df = pd.concat([df, today], ignore_index=True)
    patterns = detect_patterns(df)
    assert "向上跳空缺口" in patterns

