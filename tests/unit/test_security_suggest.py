"""测试股票代码/拼音/名称搜索联想端点。"""

from __future__ import annotations

import pytest
from easy_tdx.web.routers.market import _fetch_stock_suggest_sync


class TestStockSuggest:
    """测试股票搜索联想。"""

    def test_suggest_pinyin_jzgf(self) -> None:
        """测试拼音声母 jzgf 能够匹配君正股份/金证股份等。"""
        results = _fetch_stock_suggest_sync("jzgf")
        assert len(results) > 0
        names = [r["name"] for r in results]
        codes = [r["code"] for r in results]
        # 应包含君正股份(300223)或金证股份(600446)
        assert any("君正" in n or "金证" in n for n in names)
        assert any(c in ("300223", "600446") for c in codes)
        for r in results:
            assert r["market"] in ("SH", "SZ", "BJ")
            assert len(r["code"]) == 6
            assert r["symbol"] == f"{r['market']}:{r['code']}"

    def test_suggest_code_601216(self) -> None:
        """测试 6 位代码 601216 匹配君正集团。"""
        results = _fetch_stock_suggest_sync("601216")
        assert len(results) > 0
        assert results[0]["code"] == "601216"
        assert "君正" in results[0]["name"]
        assert results[0]["market"] == "SH"

    def test_suggest_chinese_name(self) -> None:
        """测试中文名称搜索。"""
        results = _fetch_stock_suggest_sync("君正")
        assert len(results) > 0
        assert any("君正" in r["name"] for r in results)

    def test_suggest_empty_query(self) -> None:
        """测试空查询返回空列表。"""
        assert _fetch_stock_suggest_sync("") == []
        assert _fetch_stock_suggest_sync("   ") == []

    def test_000688_distinguishes_guocheng_vs_kechuang50(self) -> None:
        """测试 000688 深圳股票国城矿业 与 000688.SH/999688 上证科创50指数的精确区分。"""
        from easy_tdx.market_data import _get_market
        from easy_tdx.stock_lookup import get_stock_name, search_stocks
        from easy_tdx.web.routers.quotes import _get_market_suffix, _get_board_tag, _resolve_stock_board_info
        from easy_tdx.models.enums import Market

        assert _get_market("000688") == Market.SZ
        assert _get_market("000688.SZ") == Market.SZ
        assert _get_market("000688.SH") == Market.SH
        assert _get_market("999688") == Market.SH

        assert _get_market_suffix("000688") == ("SZ", "000688.SZ")
        assert _get_market_suffix("000688.SH") == ("SH", "000688.SH")

        assert get_stock_name("000688") == "国城矿业"
        assert get_stock_name("000688.SZ") == "国城矿业"
        assert get_stock_name("000688.SH") == "科创50"
        assert get_stock_name("999688") == "科创50"

        assert _get_board_tag("000688")["label"] == "主"
        assert _get_board_tag("000688.SH")["label"] == "科"

        b_info_sz = _resolve_stock_board_info("000688")
        assert b_info_sz["board_name"] != "宽基指数"

        b_info_sh = _resolve_stock_board_info("000688.SH")
        assert b_info_sh["board_name"] == "宽基指数"

        gcky_matches = search_stocks("GCKY")
        assert any(r["code"] == "000688" and "国城矿业" in r["name"] for r in gcky_matches)

        kc50_matches = search_stocks("KC50")
        assert any("科创50" in r["name"] for r in kc50_matches)

