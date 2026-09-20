import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from easy_tdx.sector_leaders import (
    _BOARD_DETAIL_CACHE,
    _SEARCH_CACHE,
    _SECTOR_LEADERS_CACHE,
    _read_disk_cache,
    _write_disk_cache,
    analyze_single_board_leaders,
    clear_sector_leaders_cache,
    get_sector_leaders_data,
    search_sector_leader,
)
from easy_tdx.web.app import _create_app


@pytest.fixture(autouse=True)
def clean_cache():
    clear_sector_leaders_cache()
    yield
    clear_sector_leaders_cache()


def test_sector_leaders_memory_and_disk_cache():
    cache_key = "hy_12_4_change_pct"
    sample_data = [{"board_code": "881094", "board_name": "测试半导体", "candidates": []}]

    # 写入缓存
    _SECTOR_LEADERS_CACHE[cache_key] = (time.time(), sample_data)
    _write_disk_cache(cache_key, sample_data, time.time())

    # 默认 use_cache=True 应该命中缓存
    res, from_cache, _ = get_sector_leaders_data(
        board_type="hy",
        top_boards=12,
        top_stocks=4,
        sort_by="change_pct",
        force_refresh=False,
        use_cache=True,
        return_meta=True,
    )
    assert from_cache is True
    assert len(res) == 1
    assert res[0]["board_name"] == "测试半导体"

    # 清空内存缓存后，读取持久化磁盘缓存
    _SECTOR_LEADERS_CACHE.clear()
    res2, from_cache2, _ = get_sector_leaders_data(
        board_type="hy",
        top_boards=12,
        top_stocks=4,
        sort_by="change_pct",
        force_refresh=False,
        use_cache=True,
        return_meta=True,
    )
    assert from_cache2 is True
    assert len(res2) == 1
    assert res2[0]["board_code"] == "881094"


def test_sector_leaders_search_and_detail_cache():
    # 测试单板块分析缓存
    board_code = "881999"
    detail_data = {"board_code": board_code, "board_name": "测试板块", "candidates": []}
    _BOARD_DETAIL_CACHE[f"board_{board_code}_5"] = (time.time(), detail_data)

    res = analyze_single_board_leaders(board_code=board_code, top_candidates=5, use_cache=True)
    assert res["board_name"] == "测试板块"

    # 测试搜索缓存
    query = "芯片"
    search_data = {"board_code": "881094", "board_name": "半导体芯片"}
    _SEARCH_CACHE[f"search_{query}_10"] = (time.time(), search_data)

    res_search = search_sector_leader(query=query, top_stocks=10, use_cache=True)
    assert res_search is not None
    assert res_search["board_name"] == "半导体芯片"


def test_sector_leaders_api_cache_endpoint():
    app = _create_app()
    client = TestClient(app)

    # 预置缓存
    cache_key = "hy_12_4_change_pct"
    sample_data = [{"board_code": "881094", "board_name": "测试半导体", "candidates": []}]
    _SECTOR_LEADERS_CACHE[cache_key] = (time.time(), sample_data)

    # 请求 API，验证 use_cache 默认开启且返回 from_cache
    resp = client.get("/api/sector_leaders")
    assert resp.status_code == 200
    json_data = resp.json()
    assert json_data["success"] is True
    assert json_data["from_cache"] is True
    assert json_data["stat"]["total_boards"] == 1
