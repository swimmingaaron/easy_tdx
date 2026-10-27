"""Unit tests for Industry Universe definitions and Sector-based stock screening."""

import pytest
from easy_tdx.screener.industry import (
    load_industry_universe,
    list_all_industries,
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
        # 验证至少包含 120 个以上细分行业（标准为 128 个）
        assert len(universe["industries"]) >= 120
        # 验证覆盖 5000 只以上 A 股
        assert len(universe["stock_to_industry"]) >= 5000

    def test_list_all_industries(self):
        all_inds = list_all_industries()
        assert len(all_inds) >= 120
        # 检查是否包含核心赛道
        names = [ind["name"] for ind in all_inds]
        for expected in ["半导体", "通信设备", "软件服务", "电池", "酿酒"]:
            assert expected in names, f"预期行业板块 {expected} 应该存在于行业列表中"

    def test_find_industry_by_code_and_name(self):
        # 按代码查找
        semiconductor = find_industry("881319")
        assert semiconductor is not None
        assert semiconductor["name"] == "半导体"
        assert len(semiconductor["symbols"]) > 50

        # 按名称查找
        wine = find_industry("酿酒")
        assert wine is not None
        assert wine["code"] == "881130"

        # 按别名/模糊查找
        chip = find_industry("芯片")
        assert chip is not None
        assert chip["name"] == "半导体"

        baijiu = find_industry("白酒")
        assert baijiu is not None
        assert baijiu["name"] == "酿酒"

    def test_get_industry_symbols(self):
        symbols = get_industry_symbols("半导体")
        assert len(symbols) >= 100
        # 检查知名半导体个股是否在内 (如 688981 中芯国际, 603986 兆易创新)
        assert any(s in symbols for s in ["688981", "603986", "002049", "600584"])

    def test_get_stock_industry_reverse_lookup(self):
        # 600519 贵州茅台 -> 酿酒
        maotai_ind = get_stock_industry("600519")
        assert maotai_ind is not None
        assert maotai_ind["name"] == "酿酒"
        assert maotai_ind["code"] == "881130"

        # 603986 兆易创新 -> 半导体
        zy_ind = get_stock_industry("603986")
        assert zy_ind is not None
        assert zy_ind["name"] == "半导体"

    def test_is_industry_scope(self):
        assert is_industry_scope("industry:半导体") is True
        assert is_industry_scope("industry:881319") is True
        assert is_industry_scope("半导体") is True
        assert is_industry_scope("881130") is True
        assert is_industry_scope("core") is False
        assert is_industry_scope("all") is False
        assert is_industry_scope("000001") is False


class TestUniverseIntegration:
    """测试 Universe 模块对行业板块选股范围的无缝支持"""

    def test_get_universe_symbols_for_industry(self):
        # 格式 1: industry:半导体
        syms1 = get_universe_symbols("industry:半导体")
        assert len(syms1) >= 100

        # 格式 2: 直接输入行业名
        syms2 = get_universe_symbols("半导体")
        assert syms1 == syms2

        # 格式 3: 行业板块代码
        syms3 = get_universe_symbols("881319")
        assert syms1 == syms3

    def test_get_universe_options_includes_industries(self):
        opts = get_universe_options()
        opt_ids = [opt["id"] for opt in opts]
        assert "core" in opt_ids
        assert "industry:半导体" in opt_ids
        assert "industry:电池" in opt_ids


class TestScreenerIndustryExecution:
    """测试选股策略对指定行业板块的筛选与字段丰富"""

    def test_scan_industry_symbols(self):
        # 针对酿酒板块成分股执行测试
        wine_symbols = get_industry_symbols("酿酒")[:5]
        results = scan_market_strategy(
            strategy_name="bull_trend",
            symbols=wine_symbols,
            period="DAY",
            lookback_bars=10,
            max_workers=2,
            force_refresh=False,
        )
        assert isinstance(results, list)
        for r in results:
            # 验证选股结果中必须包含行业元数据
            assert "industry_name" in r
            assert r["industry_name"] == "酿酒"
            assert r["industry_code"] == "881130"
            assert r.get("industry") == "酿酒"
