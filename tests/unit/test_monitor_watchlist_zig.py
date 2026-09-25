"""Unit tests for monitor_watchlist_zig.py."""
import sys
from datetime import datetime
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from monitor_watchlist_zig import (
    CHECK_SLOTS,
    is_trading_day,
    get_current_check_slot,
    format_zig_message,
    WeChatNotifier,
)


def test_check_slots_definition():
    """Verify that all 8 half-hour -5min slots in A-share trading are covered."""
    assert len(CHECK_SLOTS) == 8
    expected = [
        (9, 55),
        (10, 25),
        (10, 55),
        (11, 25),
        (13, 25),
        (13, 55),
        (14, 25),
        (14, 55),
    ]
    assert CHECK_SLOTS == expected


def test_is_trading_day():
    """Verify weekday / weekend detection."""
    # 2026-09-25 is Friday -> True
    fri = datetime(2026, 9, 25, 10, 0, 0)
    assert is_trading_day(fri) is True

    # 2026-09-26 is Saturday -> False
    sat = datetime(2026, 9, 26, 10, 0, 0)
    assert is_trading_day(sat) is False

    # 2026-09-27 is Sunday -> False
    sun = datetime(2026, 9, 27, 10, 0, 0)
    assert is_trading_day(sun) is False


def test_get_current_check_slot():
    """Verify slot hit matching."""
    hit_dt = datetime(2026, 9, 25, 9, 55, 30)
    assert get_current_check_slot(hit_dt) == (9, 55)

    hit_dt2 = datetime(2026, 9, 25, 14, 25, 10)
    assert get_current_check_slot(hit_dt2) == (14, 25)

    miss_dt = datetime(2026, 9, 25, 9, 50, 0)
    assert get_current_check_slot(miss_dt) is None


def test_format_zig_message():
    """Verify markdown output formatting for WeChat notification."""
    scan_res = {
        "buy_signals": [
            {
                "code": "000002",
                "name": "万科A",
                "zig": 1,
                "close": 3.76,
                "chg_pct": 1.25,
                "amount": 220000000.0,
                "bar_time": "2026-09-25 10:00",
            }
        ],
        "sell_signals": [
            {
                "code": "600519",
                "name": "贵州茅台",
                "zig": -1,
                "close": 1500.0,
                "chg_pct": -0.85,
                "amount": 1500000000.0,
                "bar_time": "2026-09-25 10:00",
            }
        ],
    }

    title, content = format_zig_message(scan_res, "09:55", 0.05)
    assert "09:55" in title
    assert "向上反转" in content
    assert "000002 万科A" in content
    assert "向下见顶" in content
    assert "600519 贵州茅台" in content


def test_is_in_trading_hours():
    """Verify trading hours detection for morning and afternoon sessions."""
    from monitor_watchlist_zig import is_in_trading_hours
    # Friday 10:00 -> True
    assert is_in_trading_hours(datetime(2026, 9, 25, 10, 0, 0)) is True
    # Friday 11:35 (lunch break) -> False
    assert is_in_trading_hours(datetime(2026, 9, 25, 11, 35, 0)) is False
    # Friday 14:00 -> True
    assert is_in_trading_hours(datetime(2026, 9, 25, 14, 0, 0)) is True
    # Friday 15:30 (after market) -> False
    assert is_in_trading_hours(datetime(2026, 9, 25, 15, 30, 0)) is False
    # Saturday 10:00 -> False
    assert is_in_trading_hours(datetime(2026, 9, 26, 10, 0, 0)) is False


def test_ensure_realtime_30m_kline():
    """Verify realtime kline calibration during trading hours and preservation off-hours."""
    import pandas as pd
    from monitor_watchlist_zig import ensure_realtime_30m_kline

    sample_df = pd.DataFrame({
        "datetime": ["2026-09-24 14:30", "2026-09-24 15:00"],
        "open": [10.0, 10.2],
        "high": [10.5, 10.4],
        "low": [9.9, 10.1],
        "close": [10.2, 10.3],
        "volume": [1000, 2000],
        "amount": [10000.0, 20000.0],
    })

    # Case 1: Weekend or off-hours -> historical df must NOT be modified
    sat_dt = datetime(2026, 9, 26, 10, 0, 0)
    df_off = ensure_realtime_30m_kline(sample_df, {"price": 15.0}, now=sat_dt)
    assert len(df_off) == 2
    assert df_off.iloc[-1]["close"] == 10.3  # Unchanged!

    # Case 2: During trading hours with new bar window -> appends ongoing bar
    fri_dt = datetime(2026, 9, 25, 10, 25, 0)
    df_on = ensure_realtime_30m_kline(sample_df, {"price": 10.8}, now=fri_dt)
    assert len(df_on) == 3
    assert df_on.iloc[-1]["datetime"] == "2026-09-25 10:30"
    assert df_on.iloc[-1]["close"] == 10.8
    assert df_on.iloc[-2]["close"] == 10.3  # Historical bar intact!
