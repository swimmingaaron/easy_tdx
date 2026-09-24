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
