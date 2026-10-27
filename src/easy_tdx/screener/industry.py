"""easy_tdx Industry & Sector Universe Definition and Management.
================================================================

提供 A 股全市场 128 大标准行业板块与 10 大核心产业赛道大类的规范化定义、
成分股检索、个股所属行业反查以及选股范围无缝接入。
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# 数据持久化存储路径
_DATA_DIR = Path(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "data")))
_INDUSTRY_FILE = _DATA_DIR / "industry_universe.json"

# 内存单例缓存
_INDUSTRY_CACHE: Optional[Dict[str, Any]] = None
_CACHE_TIMESTAMP: float = 0.0
_TTL: float = 3600.0 * 24  # 行业分类数据极稳定，强缓存 24 小时


def get_industry_universe_file() -> Path:
    """返回行业板块数据文件的绝对路径。"""
    return _INDUSTRY_FILE


def load_industry_universe(force_refresh: bool = False) -> Dict[str, Any]:
    """加载全市场行业板块定义与成分股知识库（支持极速内存与磁盘多级缓存）。"""
    global _INDUSTRY_CACHE, _CACHE_TIMESTAMP

    now = time.time()
    if not force_refresh and _INDUSTRY_CACHE is not None and (now - _CACHE_TIMESTAMP < _TTL):
        return _INDUSTRY_CACHE

    if not force_refresh and _INDUSTRY_FILE.is_file():
        try:
            with open(_INDUSTRY_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if data and "industries" in data:
                    _INDUSTRY_CACHE = data
                    _CACHE_TIMESTAMP = now
                    return data
        except Exception as e:
            logger.warning(f"读取行业知识库缓存异常: {e}，将尝试在线拉取刷新")

    # 若本地文件不存在或强制刷新，则从通达信主站动态同步
    try:
        from ...mac.client import MacClient
        from ...mac.enums import BoardType
        from ...scripts.sync_industry_universe import sync_all_industries
    except Exception:
        # 支持以根包或脚本路径导入
        try:
            from easy_tdx.scripts.sync_industry_universe import sync_all_industries
        except Exception:
            from scripts.sync_industry_universe import sync_all_industries

    try:
        data = sync_all_industries()
        _INDUSTRY_CACHE = data
        _CACHE_TIMESTAMP = time.time()
        return data
    except Exception as e:
        logger.error(f"同步通达信行业板块失败: {e}")
        # 如果有旧缓存则降级使用
        if _INDUSTRY_CACHE:
            return _INDUSTRY_CACHE
        return {
            "updated_at": "",
            "total_industries": 0,
            "total_unique_stocks": 0,
            "categories": [],
            "industries": [],
            "stock_to_industry": {},
        }


def list_all_industries() -> List[Dict[str, Any]]:
    """返回全部 128 个行业板块的元数据清单（包含大类、代码、名称、成分股数）。"""
    uni = load_industry_universe()
    return [
        {
            "code": ind["code"],
            "name": ind["name"],
            "category": ind.get("category", "其他行业"),
            "count": ind.get("count", len(ind.get("symbols", []))),
        }
        for ind in uni.get("industries", [])
    ]


def list_industry_categories() -> List[Dict[str, Any]]:
    """返回产业赛道大类及其包含的细分行业。"""
    uni = load_industry_universe()
    return uni.get("categories", [])


def find_industry(query: str) -> Optional[Dict[str, Any]]:
    """根据板块代码、行业名称精确或模糊匹配行业板块定义。
    
    支持:
    - 纯板块代码: "881319"
    - 带前缀代码: "hy_881319", "industry:881319"
    - 纯行业名称: "半导体", "白酒"
    - 包含匹配: "芯片" -> "半导体"
    """
    clean = str(query or "").strip().lower()
    if clean.startswith("industry:"):
        clean = clean[9:].strip()
    elif clean.startswith("hy_") or clean.startswith("hy:"):
        clean = clean[3:].strip()
    elif clean.startswith("industry_"):
        clean = clean[9:].strip()

    uni = load_industry_universe()
    industries = uni.get("industries", [])

    # 1. 精确代码匹配
    for ind in industries:
        if ind["code"].lower() == clean:
            return ind

    # 2. 精确名称匹配
    for ind in industries:
        if ind["name"].lower() == clean:
            return ind

    # 3. 常见同义词/简称映射
    alias_map = {
        "芯片": "半导体",
        "集成电路": "半导体",
        "白酒": "酿酒",
        "酒类": "酿酒",
        "银行": "全国性银行",
        "光伏": "光伏设备",
        "风电": "风电设备",
        "储能": "电池",
        "锂电": "电池",
        "锂电池": "电池",
        "军工": "航空装备",
        "券商": "证券",
        "汽车": "汽车零部件",
        "整车": "乘用车",
        "中药": "中药",
        "医药": "化学制药",
        "通信": "通信设备",
        "软件": "软件服务",
        "计算机": "软件服务",
        "游戏": "游戏",
    }
    if clean in alias_map:
        target_name = alias_map[clean]
        for ind in industries:
            if ind["name"] == target_name:
                return ind

    # 4. 模糊包含匹配
    for ind in industries:
        if clean in ind["name"].lower() or ind["name"].lower() in clean:
            return ind

    # 5. 大类匹配（如果传入大类名称，合成大类伪板块）
    for cat in uni.get("categories", []):
        cat_name = cat.get("category", "")
        if clean in cat_name.lower() or cat_name.lower() in clean:
            # 聚合该大类下所有细分行业的所有股票
            cat_symbols = []
            seen = set()
            for sub in cat.get("industries", []):
                sub_ind = find_industry(sub["code"])
                if sub_ind:
                    for s in sub_ind.get("symbols", []):
                        if s not in seen:
                            seen.add(s)
                            cat_symbols.append(s)
            return {
                "code": f"cat_{cat_name}",
                "name": cat_name,
                "category": cat_name,
                "count": len(cat_symbols),
                "symbols": cat_symbols,
                "is_category": True,
            }

    return None


def get_industry_symbols(key: str) -> List[str]:
    """根据行业代码或名称获取该行业下的所有成分股代码列表。"""
    ind = find_industry(key)
    if ind:
        return list(ind.get("symbols", []))
    return []


def get_stock_industry(symbol: str) -> Optional[Dict[str, str]]:
    """查询指定股票所属的行业板块信息（代码、行业名称、赛道大类）。"""
    code = str(symbol or "").strip().zfill(6)
    uni = load_industry_universe()
    stock_map = uni.get("stock_to_industry", {})
    return stock_map.get(code)


def is_industry_scope(scope: str) -> bool:
    """快速判断传入的选股范围标识是否属于行业板块。"""
    if not scope:
        return False
    s = str(scope).strip().lower()
    if s in ("core", "hs300", "zz500", "zz1000", "all", "market", "full", "custom"):
        return False
    if s.startswith("industry:") or s.startswith("hy_") or s.startswith("hy:") or s.startswith("industry_"):
        return True
    # 检查是否能够匹配到具体行业
    ind = find_industry(scope)
    return ind is not None
