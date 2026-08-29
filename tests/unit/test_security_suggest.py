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
