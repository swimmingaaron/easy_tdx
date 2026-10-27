"""Unit tests for Industry Universe definitions and Sector Index based screening."""

import pytest
from easy_tdx.screener.industry import (
    load_industry_universe,
    list_all_industries,
    list_all_industry_indices,
    get_all_industry_index_codes,
    get_industry_index_symbols,
    find_industry,
    get_industry_symbols,
    get_stock_industry,
    is_industry_scope,
)
from easy_tdx.screener.universe import get_universe_symbols, get_universe_options
from easy_tdx.screener.scanner import scan_market_strategy


class TestIndustryUniverseDefinition:
    """测试通达信行业板块的定义与元数据加载"""

    def test_load_all_128_industries(self):
        universe = load_industry_universe()
        assert universe is not None
        assert "industries" in universe
        assert "stock_to_industry" in universe
        assert len(universe["industries"]) == 128
        assert len(universe["stock_to_industry"]) >= 5000

    def test_list_all_industry_indices(self):
        all_indices = list_all_industry_indices()
        assert len(all_indices) == 128
        names = [ind["name"] for ind in all_indices]
        for expected in ["半导体", "通信设备", "软件服务", "电池", "酿酒"]:
            assert expected in names, f"预期行业板块 {expected} 应该存在于行业列表中"
        for ind in all_indices:
            assert ind["code"].startswith("88"), "行业指数代码应以 88 开头"

    def test_find_industry_by_code_and_name(self):
        semiconductor = find_industry("881319")
        assert semiconductor is not None
        assert semiconductor["name"] == "半导体"

        wine = find_industry("酿酒")
        assert wine is not None
        assert wine["code"] == "881130"

        chip = find_industry("芯片")
        assert chip is not None
        assert chip["name"] == "半导体"

    def test_get_stock_industry_reverse_lookup(self):
        # 针对股票: 600519 贵州茅台 -> 酿酒
        maotai_ind = get_stock_industry("600519")
        assert maotai_ind is not None
        assert maotai_ind["name"] == "酿酒"

        # 针对行业指数代码本身: 881319 -> 半导体
        idx_ind = get_stock_industry("881319")
        assert idx_ind is not None
        assert idx_ind["name"] == "半导体"
        assert idx_ind.get("is_index") is True

    def test_is_industry_scope(self):
        assert is_industry_scope("industry_index") is True
        assert is_industry_scope("industry_index:tmt") is True
        assert is_industry_scope("industry:半导体") is True
        assert is_industry_scope("半导体") is True
        assert is_industry_scope("881319") is True
        assert is_industry_scope("core") is False
        assert is_industry_scope("all") is False


class TestSectorIndexUniverse:
    """测试 Universe 模块对【行业板块指数自身】择时选股的支持（非成分股）"""

    def test_get_all_industry_indices(self):
        # 全部行业板块指数
        codes = get_universe_symbols("industry_index")
        assert len(codes) == 128
        assert "881319" in codes  # 半导体指数
        assert "881130" in codes  # 酿酒指数

    def test_get_category_industry_indices(self):
        # TMT 科技大类行业指数
        tmt_codes = get_universe_symbols("industry_index:tmt")
        assert 10 <= len(tmt_codes) <= 25
        assert "881319" in tmt_codes  # 半导体属于 TMT
        assert "881130" not in tmt_codes  # 酿酒属于消费

    def test_single_industry_resolves_to_sector_index_code(self):
        # 单行业直接映射为该行业指数代码本身，而不是成分股
        codes1 = get_universe_symbols("industry:半导体")
        assert codes1 == ["881319"]

        codes2 = get_universe_symbols("半导体")
        assert codes2 == ["881319"]

        codes3 = get_universe_symbols("881319")
        assert codes3 == ["881319"]

    def test_get_universe_options_includes_sector_indices(self):
        opts = get_universe_options()
        opt_ids = [opt["id"] for opt in opts]
        assert "core" in opt_ids
        assert "industry_index" in opt_ids
        assert "industry_index:tmt" in opt_ids
        assert "industry_index:manufacturing" in opt_ids


class TestScreenerIndustryIndexExecution:
    """测试对行业板块指数自身执行选股策略"""

    def test_scan_sector_indices_directly(self):
        # 对 881344 (电信服务指数) 和 881319 (半导体指数) 进行选股测试
        test_indices = ["881344", "881319", "881130"]
        results = scan_market_strategy(
            strategy_name="bull_trend",
            symbols=test_indices,
            universe="industry_index",
            period="DAY",
            lookback_bars=22,
            max_workers=2,
            force_refresh=True,
        )
        assert isinstance(results, list)
        for r in results:
            # 验证结果为行业指数自身
            assert str(r["code"]).startswith("88")
            assert r.get("is_index") is True
            assert r["name"] in ["电信服务", "半导体", "酿酒", "光伏设备"]
            assert float(r["price"]) > 0
