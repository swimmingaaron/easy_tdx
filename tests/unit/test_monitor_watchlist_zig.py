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

    # Case 3: Quote timestamp belongs to previous day -> do NOT append fake ongoing bar
    prev_quote = {"price": 10.8, "time": "20260924161412"}
    df_prev = ensure_realtime_30m_kline(sample_df, prev_quote, now=fri_dt)
    assert len(df_prev) == 2
    assert df_prev.iloc[-1]["datetime"] == "2026-09-24 15:00"
    assert df_prev.iloc[-1]["close"] == 10.3


def test_generate_kline_snapshot_and_send_image(monkeypatch):
    """Verify 30M K-line snapshot generation and image sending logic."""
    import pandas as pd
    from monitor_watchlist_zig import generate_kline_snapshot, WeChatNotifier

    # Build dummy K-lines
    rows = []
    base_price = 10.0
    for i in range(20):
        c = base_price + (i * 0.1 if i < 15 else (15 * 0.1 - (i - 15) * 0.2))
        rows.append({
            "datetime": f"2026-09-25 {10 + i // 2:02d}:{(i % 2) * 30:02d}",
            "open": c - 0.05,
            "high": c + 0.1,
            "low": c - 0.1,
            "close": c,
            "volume": 1000 + i * 50,
            "amount": 10000.0,
            "zig": 1 if i == 19 else (i - 18 if i >= 15 else -(i + 1)),
        })
    df = pd.DataFrame(rows)

    # 1. Test generate_kline_snapshot
    img_bytes = generate_kline_snapshot(
        code="002436",
        name="兴森科技",
        df=df,
        zig_val=1,
        change_pct=2.5,
        delta_pct=0.05,
    )
    assert isinstance(img_bytes, bytes)
    assert len(img_bytes) > 1000  # Valid PNG data generated
    assert img_bytes[:8] == b"\x89PNG\r\n\x1a\n"  # PNG magic header

    # 2. Test WeChatNotifier.send_image mock
    notifier = WeChatNotifier(wecom_webhook="https://qyapi.weixin.qq.com/mock")
    sent_payload = []

    def mock_post_json(url, data, timeout=8):
        sent_payload.append(data)
        return {"errcode": 0, "errmsg": "ok"}

    monkeypatch.setattr(notifier, "_post_json", mock_post_json)
    success = notifier.send_image(img_bytes)
    assert success is True
    assert len(sent_payload) == 1
    assert sent_payload[0]["msgtype"] == "image"
    assert "base64" in sent_payload[0]["image"]
    assert "md5" in sent_payload[0]["image"]


