import json
import unittest
from unittest.mock import patch, MagicMock
from easy_tdx.models import Market
from easy_tdx.stock_profile import (
    _resolve_quarter_end_date,
    _format_period_title,
    _fetch_shareholder_history,
)

class TestStockProfileShareholders(unittest.TestCase):
    def test_resolve_quarter_end_date(self):
        self.assertEqual(_resolve_quarter_end_date("2026-06-30"), "2026-06-30")
        self.assertEqual(_resolve_quarter_end_date("2026-08-15"), "2026-06-30")
        self.assertEqual(_resolve_quarter_end_date("2026-10-28"), "2026-09-30")
        self.assertEqual(_resolve_quarter_end_date("2026-04-20"), "2025-12-31")

    def test_format_period_title(self):
        self.assertEqual(_format_period_title("2026-03-31"), "2026一季报")
        self.assertEqual(_format_period_title("2026-06-30"), "2026中报")
        self.assertEqual(_format_period_title("2026-09-30"), "2026三季报")
        self.assertEqual(_format_period_title("2026-12-31"), "2026年报")
        self.assertEqual(_format_period_title("2026-08-15"), "2026中报")

    def test_tier1_tdx_first_choice_and_merge(self):
        # EastMoney returns 4 historical quarters
        mock_eastmoney = [
            {"period": "2026-06-30", "period_title": "2026中报", "holder_count": 290000, "avg_shares": 4000, "focus": "分散"},
            {"period": "2026-03-31", "period_title": "2026一季报", "holder_count": 240000, "avg_shares": 5000, "focus": "分散"},
            {"period": "2025-12-31", "period_title": "2025年报", "holder_count": 250000, "avg_shares": 4800, "focus": "分散"},
        ]
        # TDX has local latest data (different/newer count: 296404)
        tdx_data = {
            "holder_count": 296404,
            "avg_shares_per_holder": 4217.5,
            "updated_date": "2026-08-15",
        }

        with patch("easy_tdx.stock_profile._fetch_shareholder_history_datacenter", return_value=mock_eastmoney):
            records = _fetch_shareholder_history("600519", "SH", tdx_data=tdx_data)

            self.assertEqual(len(records), 3)
            # Latest record must be overridden by Tier 1 TDX
            self.assertEqual(records[0]["source"], "easy_tdx")
            self.assertEqual(records[0]["holder_count"], 296404)
            self.assertEqual(records[0]["avg_shares"], 4217.5)
            # Retains supplementary fields
            self.assertEqual(records[0]["focus"], "分散")
            # Recalculated QoQ against previous quarter (296404 vs 240000 -> +23.5%)
            expected_qoq = round(((296404 - 240000) / 240000) * 100, 2)
            self.assertEqual(records[0]["holder_qoq"], expected_qoq)

    def test_tier1_tdx_prepend_when_newer(self):
        # EastMoney only has up to 2026-03-31
        mock_eastmoney = [
            {"period": "2026-03-31", "period_title": "2026一季报", "holder_count": 240000, "avg_shares": 5000},
            {"period": "2025-12-31", "period_title": "2025年报", "holder_count": 250000, "avg_shares": 4800},
        ]
        # TDX already has 2026中报 (2026-06-30)
        tdx_data = {
            "holder_count": 296404,
            "avg_shares_per_holder": 4217.5,
            "updated_date": "2026-08-15",
        }

        with patch("easy_tdx.stock_profile._fetch_shareholder_history_datacenter", return_value=mock_eastmoney):
            records = _fetch_shareholder_history("600519", "SH", tdx_data=tdx_data)

            self.assertEqual(len(records), 3)
            self.assertEqual(records[0]["period"], "2026-06-30")
            self.assertEqual(records[0]["source"], "easy_tdx")
            self.assertEqual(records[0]["holder_count"], 296404)
            self.assertEqual(records[1]["period"], "2026-03-31")

    def test_disaster_recovery_external_outage(self):
        # Both EastMoney and THS fail
        tdx_data = {
            "holder_count": 296404,
            "avg_shares_per_holder": 4217.5,
            "updated_date": "2026-08-15",
        }
        with patch("easy_tdx.stock_profile._fetch_shareholder_history_datacenter", side_effect=Exception("DC fail")), \
             patch("easy_tdx.stock_profile._fetch_shareholder_history_pageajax", side_effect=Exception("PA fail")), \
             patch("easy_tdx.stock_profile._fetch_shareholder_history_ths", side_effect=Exception("THS fail")):
            records = _fetch_shareholder_history("600519", "SH", tdx_data=tdx_data)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["source"], "easy_tdx")
            self.assertEqual(records[0]["holder_count"], 296404)

    def test_disaster_recovery_tdx_outage(self):
        mock_eastmoney = [
            {"period": "2026-06-30", "period_title": "2026中报", "holder_count": 296404, "avg_shares": 4217},
            {"period": "2026-03-31", "period_title": "2026一季报", "holder_count": 243159, "avg_shares": 5150},
        ]
        with patch("easy_tdx.stock_profile._fetch_shareholder_history_tdx", return_value=None), \
             patch("easy_tdx.stock_profile._fetch_shareholder_history_datacenter", return_value=mock_eastmoney):
            records = _fetch_shareholder_history("600519", "SH", tdx_data=None)
            self.assertEqual(len(records), 2)
            self.assertEqual(records[0]["holder_count"], 296404)

    def test_company_info_fallback(self):
        from easy_tdx.stock_profile import _fetch_company_info
        mock_data = json.dumps({"jbzl": [{"gsmc": "兴森快捷", "sshy": "电子元件", "frdb": "邱醒亚", "gsjj": "主营印制电路板"}]}).encode("utf-8")
        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_data
        mock_resp.headers = {}
        mock_resp.__enter__.return_value = mock_resp
        with patch("urllib.request.urlopen", return_value=mock_resp):
            info = _fetch_company_info("002436", "SZ", Market.SZ)
            self.assertEqual(info["org_name"], "兴森快捷")
            self.assertEqual(info["industry"], "电子元件")
            self.assertEqual(info["legal_person"], "邱醒亚")
            self.assertIn("印制电路板", info["main_business"])

    def test_stock_sectors_fallback(self):
        from easy_tdx.stock_profile import _fetch_stock_sectors
        mock_data = json.dumps({"result": {"data": [{"BOARD_NAME": "半导体", "BOARD_TYPE": "行业"}, {"BOARD_NAME": "芯片", "BOARD_TYPE": "概念"}]}}).encode("utf-8")
        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_data
        mock_resp.headers = {}
        mock_resp.__enter__.return_value = mock_resp
        with patch("urllib.request.urlopen", return_value=mock_resp):
            sectors = _fetch_stock_sectors("002436", "SZ", Market.SZ, company_info={"industry": "电子元件"})
            names = [s["name"] for s in sectors]
            self.assertIn("电子元件", names)
            self.assertIn("半导体", names)
            self.assertIn("芯片", names)


    def test_financials_sina_fallback(self):
        import pandas as pd
        from easy_tdx.stock_profile import _fetch_stock_financials
        df_lrb = pd.DataFrame([
            {"报告期": "2026-06-30", "营业总收入": 4038000000.0, "归属于母公司所有者的净利润": 111000000.0, "营业总收入_同比": 0.178, "归属于母公司所有者的净利润_同比": 2.83},
            {"报告期": "2026-03-31", "营业总收入": 1818000000.0, "归属于母公司所有者的净利润": 18740000.0, "营业总收入_同比": 0.151, "归属于母公司所有者的净利润_同比": 1.00},
        ])
        with patch("urllib.request.urlopen", side_effect=Exception("EM fail")), \
             patch("easy_tdx.stock_profile.SinaClient.get_financial_report", return_value=df_lrb):
            fins = _fetch_stock_financials("002436", "SZ", Market.SZ)
            self.assertEqual(len(fins), 2)
            self.assertEqual(fins[0]["revenue_yi"], 40.38)
            self.assertEqual(fins[0]["revenue_yoy"], 17.8)
            self.assertEqual(fins[0]["net_profit_yi"], 1.11)


if __name__ == "__main__":
    unittest.main()


