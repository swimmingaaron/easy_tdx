import json
import pytest
from pathlib import Path
from easy_tdx.watchlist_store import (
    parse_watchlist_data,
    merge_watchlist_items,
    merge_watchlist_file,
)


def test_parse_watchlist_data():
    raw_list = [
        {"code": "600519", "name": "贵州茅台"},
        {"code": "000001", "name": "平安银行"},
        "300750",
        {"symbol": "SZ002594", "name": "比亚迪"},
        {"invalid": "code"},
    ]
    parsed = parse_watchlist_data(raw_list)
    codes = [item["code"] for item in parsed]
    assert "600519" in codes
    assert "000001" in codes
    assert "300750" in codes
    assert "002594" in codes
    assert len(parsed) == 4


def test_merge_watchlist_items_union_and_dedup():
    base = [
        {"code": "600519", "name": "贵州茅台"},
        {"code": "000001", "name": "平安银行"},
    ]
    incoming = [
        {"code": "000001", "name": "平安银行"},  # 重复项
        {"code": "300750", "name": "宁德时代"},  # 新增项
        "601778",  # 字符串格式新增项
    ]
    merged = merge_watchlist_items(base, incoming)
    codes = [item["code"] for item in merged]
    assert codes == ["600519", "000001", "300750", "601778"]
    assert len(merged) == 4


def test_merge_watchlist_file(tmp_path: Path):
    target_f = tmp_path / "watchlist.json"
    with open(target_f, "w", encoding="utf-8") as f:
        json.dump([{"code": "600519", "name": "贵州茅台"}], f)

    source_f = tmp_path / "incoming.json"
    with open(source_f, "w", encoding="utf-8") as f:
        json.dump([{"code": "300750", "name": "宁德时代"}], f)

    merged = merge_watchlist_file(target_f, source_f)
    assert len(merged) == 2
    codes = [item["code"] for item in merged]
    assert "600519" in codes
    assert "300750" in codes

    # 验证写回
    with open(target_f, "r", encoding="utf-8") as f:
        saved = json.load(f)
    assert len(saved) == 2
