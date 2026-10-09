"""Unit tests for monitor_watchlist_quadrilateral script."""
from pathlib import Path
from unittest.mock import patch
import pandas as pd
import numpy as np

from monitor_watchlist_quadrilateral import (
    format_quadrilateral_message,
    generate_quadrilateral_snapshot,
    check_single_stock_quadrilateral,
    scan_watchlist_quadrilateral,
)
from tests.unit.test_ma_quadrilateral import make_quadrilateral_kline


def test_format_quadrilateral_message():
    mock_results = {
        "buy_signals": [
            {
                "code": "600592",
                "name": "龙溪股份",
                "close": 15.43,
                "chg_pct": 2.5,
                "amount": 250000000.0,
                "bar_time": "2026-10-09",
                "buy_info": {
                    "days_ago": 0,
                    "buy_type": "回踩10日线抢筹",
                    "regularity": 94.0,
                    "bottom_price": 12.69,
                    "trigger_time": "2026-10-09",
                },
            }
        ],
        "closure_signals": [
            {
                "code": "603116",
                "name": "红蜻蜓",
                "close": 7.21,
                "chg_pct": 0.84,
                "bar_time": "2026-10-09",
            }
        ],
        "sell_signals": [],
    }

    title, md = format_quadrilateral_message(mock_results, "DAY", "盘中14:30")
    assert "均线四边形预警" in title
    assert "盘中14:30" in title
    assert "600592 龙溪股份" in md
    assert "回踩10日线抢筹" in md
    assert "603116 红蜻蜓" in md


def test_generate_quadrilateral_snapshot():
    df = make_quadrilateral_kline(n_bars=90, trigger_quad=True)
    df["ma5"] = df["close"].rolling(5).mean()
    df["ma10"] = df["close"].rolling(10).mean()
    df["ma20"] = df["close"].rolling(20).mean()
    df["ma30"] = df["close"].rolling(30).mean()
    df["buy_signal"] = False
    df.loc[df.index[-1], "buy_signal"] = True
    df["quad_buy_type"] = "闭合加速"
    df["quad_regularity"] = 92.0

    img_bytes = generate_quadrilateral_snapshot(
        code="600072",
        name="中船科技",
        sig_df=df,
        buy_type="闭合加速",
        regularity=92.0,
        bottom_price=10.0,
        change_pct=1.5,
        period="DAY",
    )
    assert isinstance(img_bytes, bytes)
    assert len(img_bytes) > 1000
    assert img_bytes[:8] == b"\x89PNG\r\n\x1a\n"


def test_check_single_stock_quadrilateral():
    df = make_quadrilateral_kline(n_bars=95, trigger_quad=True)
    with patch("monitor_watchlist_quadrilateral.fetch_security_kline", return_value=df):
        res = check_single_stock_quadrilateral(
            item={"code": "600592", "name": "龙溪股份"},
            period="DAY",
            lookback_bars=10,
        )
        assert res is not None
        assert res["code"] == "600592"
        assert res["status"] in ("BUY", "CLOSURE")


def test_scan_watchlist_quadrilateral():
    df = make_quadrilateral_kline(n_bars=95, trigger_quad=True)
    mock_stocks = [{"code": "600592", "name": "龙溪股份"}]
    with patch("monitor_watchlist_quadrilateral.fetch_security_kline", return_value=df), \
         patch("monitor_watchlist_quadrilateral.fetch_realtime_snapshot_quotes", return_value={}):
        res = scan_watchlist_quadrilateral(
            stocks=mock_stocks,
            period="DAY",
            lookback_bars=10,
            max_workers=1,
        )
        assert len(res["buy_signals"]) + len(res["closure_signals"]) >= 1


def test_export_results_to_csv(tmp_path):
    from monitor_watchlist_quadrilateral import export_results_to_csv
    mock_results = {
        "buy_signals": [
            {
                "code": "601088",
                "name": "中国神华",
                "close": 48.25,
                "chg_pct": 1.6,
                "amount": 416000000.0,
                "bar_time": "2026-10-09",
                "buy_info": {
                    "days_ago": 0,
                    "buy_type": "回踩10日线抢筹",
                    "regularity": 94.0,
                    "bottom_price": 45.76,
                    "trigger_time": "2026-10-09",
                },
            }
        ],
        "closure_signals": [],
        "sell_signals": [],
    }
    out_file = tmp_path / "test_quad_export.csv"
    p = export_results_to_csv(mock_results, out_file)
    assert Path(p).is_file()
    df_read = pd.read_csv(p, encoding="utf-8-sig")
    assert len(df_read) == 1
    assert df_read.iloc[0]["代码"] == 601088 or str(df_read.iloc[0]["代码"]).zfill(6) == "601088"
    assert df_read.iloc[0]["名称"] == "中国神华"
    assert df_read.iloc[0]["买点类型"] == "回踩10日线抢筹"


def test_universe_symbols_integration():
    from easy_tdx.screener.universe import get_universe_symbols
    core = get_universe_symbols("core")
    assert len(core) >= 30
    assert "601088" in core or "600519" in core


def test_long_message_byte_budget_and_split():
    """Verify that scanning 396+ items strictly produces messages within WeCom 4096-byte limit."""
    from monitor_watchlist_quadrilateral import WeChatNotifier

    # Generate 400 mock signals
    mock_buys = []
    for i in range(400):
        mock_buys.append({
            "code": f"{600000+i:06d}",
            "name": f"股票{i}",
            "close": 15.0 + i * 0.1,
            "chg_pct": 2.5,
            "amount": 250000000.0,
            "bar_time": "2026-10-09",
            "buy_info": {
                "days_ago": 0,
                "buy_type": "回踩10日线抢筹",
                "regularity": 94.0,
                "bottom_price": 12.0,
                "trigger_time": "2026-10-09",
            },
        })

    mock_results = {
        "buy_signals": mock_buys,
        "closure_signals": [{"code": "600001", "name": "平银", "close": 10.0, "chg_pct": 0.5, "bar_time": "2026-10-09"}] * 30,
        "sell_signals": [{"code": "600002", "name": "万科", "close": 8.0, "chg_pct": -1.5, "bar_time": "2026-10-09"}] * 20,
    }

    title, md = format_quadrilateral_message(
        mock_results, "DAY", "即时扫描", pool_name="全市场 A 股 (5222只)", output_path="output/quad_all.csv"
    )

    full_payload = f"### {title}\n\n{md}"
    # Must strictly be <= 4096 bytes
    assert len(full_payload.encode("utf-8")) <= 4000
    assert "quad_all.csv" in md

    # Also test _split_markdown_chunks on an artificially huge 10KB message
    huge_msg = ("这是一行很长的测试消息标的内容文本，包含了股票代码与买入预警形态\n" * 200)
    chunks = WeChatNotifier._split_markdown_chunks(huge_msg, max_bytes=3800)
    assert len(chunks) > 1
    for chk in chunks:
        assert len(chk.encode("utf-8")) <= 3800


def test_max_images_support():
    from unittest.mock import MagicMock
    from monitor_watchlist_quadrilateral import run_single_scan_and_notify

    mock_notifier = MagicMock()
    mock_notifier.is_configured.return_value = True
    mock_notifier.send_image.return_value = True

    # 10 mock buy signals with dummy sig_df
    df = pd.DataFrame({"close": [10.0, 11.0], "datetime": ["2026-10-08", "2026-10-09"]})
    mock_buys = [
        {"code": f"{600000+i:06d}", "name": f"股{i}", "close": 10.5, "sig_df": df, "buy_info": {}, "chg_pct": 2.0}
        for i in range(10)
    ]

    with patch("monitor_watchlist_quadrilateral.scan_watchlist_quadrilateral", return_value={"buy_signals": mock_buys, "closure_signals": [], "sell_signals": []}), \
         patch("monitor_watchlist_quadrilateral.generate_quadrilateral_snapshot", return_value=b"fake_png"), \
         patch("time.sleep"):
        # Test max_images=3
        run_single_scan_and_notify(
            notifier=mock_notifier,
            stocks=[],
            max_images=3,
        )
        assert mock_notifier.send_image.call_count == 3

        mock_notifier.send_image.reset_mock()
        # Test default max_images (10 signals <= 50, so all 10 sent)
        run_single_scan_and_notify(
            notifier=mock_notifier,
            stocks=[],
            max_images=50,
        )
        assert mock_notifier.send_image.call_count == 10


def test_wecom_rate_limit_and_retry():
    from unittest.mock import MagicMock
    from monitor_watchlist_quadrilateral import WeChatNotifier

    notifier = WeChatNotifier(wecom_webhook="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=dummy")

    with patch("time.sleep") as mock_sleep, \
         patch.object(notifier, "_post_json") as mock_post:
        # Case 1: normal send
        mock_post.return_value = {"errcode": 0, "errmsg": "ok"}
        for i in range(20):
            res = notifier._send_wecom_with_rate_limit({"msgtype": "text"})
            assert res.get("errcode") == 0

        # After 20 sends, the 21st send must wait 60 seconds
        mock_sleep.reset_mock()
        notifier._send_wecom_with_rate_limit({"msgtype": "text"})
        mock_sleep.assert_called_with(60)

        # Case 2: 45009 error triggers 60s wait and retry
        mock_sleep.reset_mock()
        mock_post.side_effect = [
            {"errcode": 45009, "errmsg": "Too many requests"},
            {"errcode": 0, "errmsg": "ok"},
        ]
        res = notifier._send_wecom_with_rate_limit({"msgtype": "text"})
        assert res.get("errcode") == 0
        mock_sleep.assert_called_with(60)




