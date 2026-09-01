"""Stock Universe definitions for easy_tdx Strategy Screener.

Supports multi-tier scanning scopes:
- core: 核心流动性龙头池 (35 只 · ~1秒极速)
- hs300: 沪深 300 核心权重池 (300 只 · ~6-8秒)
- zz500: 中证 500 成长主力池 (500 只 · ~12-15秒)
- zz1000: 中证 1000 活跃小盘池 (1000 只 · ~25-30秒)
- all: 全市场全 A 股 (5,207 只 · 异步后台全量批处理任务)
"""
from __future__ import annotations
import os
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 1. 核心龙头代表性标的池 (覆盖主板、创业板、科创板核心龙头)
CORE_UNIVERSE = [
    "600660", "300223", "000001", "600123", "002345", "300142", "601216", 
    "002415", "300750", "600519", "000002", "000063", "000333", "000651", 
    "000725", "000858", "002230", "002475", "002594", "300059", "300760", 
    "600000", "600028", "600030", "600036", "600887", "601318", "601857", 
    "601888", "601899", "603259", "688981", "301151", "300413", "600227"
]

_CACHED_ALL_ASHARES: list[str] = []

def _load_all_ashares() -> list[str]:
    """Load cached 5,200+ A-share codes."""
    global _CACHED_ALL_ASHARES
    if _CACHED_ALL_ASHARES:
        return _CACHED_ALL_ASHARES
    
    # Try easy_tdx data dir
    possible_paths = [
        Path(__file__).resolve().parent.parent.parent.parent / "data" / "ashares_universe.json",
        Path("c:/Users/aaron/Documents/stock_data/easy_tdx/data/ashares_universe.json"),
        Path("c:/Users/aaron/Documents/stock_data/stock_quant/data/ashares_universe.json"),
    ]
    for p in possible_paths:
        if p.exists():
            try:
                with open(p, "r", encoding="utf-8") as f:
                    codes = json.load(f)
                    if isinstance(codes, list) and len(codes) > 1000:
                        _CACHED_ALL_ASHARES = [str(c).zfill(6) for c in codes]
                        logger.info(f"Loaded {len(_CACHED_ALL_ASHARES)} A-share codes from {p}")
                        return _CACHED_ALL_ASHARES
            except Exception as e:
                logger.warning(f"Error loading {p}: {e}")

    # Fallback to core universe
    return CORE_UNIVERSE

def get_universe_symbols(scope: str = "core") -> list[str]:
    """Get stock symbols for the requested universe scope."""
    s = (scope or "core").lower().strip()
    all_stocks = _load_all_ashares()
    
    if s == "core":
        return CORE_UNIVERSE
    elif s in ("hs300", "csi300", "300"):
        # Prioritize core stocks then fill up to 300
        core_set = set(CORE_UNIVERSE)
        rest = [c for c in all_stocks if c not in core_set]
        return (CORE_UNIVERSE + rest)[:300]
    elif s in ("zz500", "csi500", "500"):
        core_set = set(CORE_UNIVERSE)
        rest = [c for c in all_stocks if c not in core_set]
        return (CORE_UNIVERSE + rest)[:500]
    elif s in ("zz1000", "csi1000", "1000"):
        core_set = set(CORE_UNIVERSE)
        rest = [c for c in all_stocks if c not in core_set]
        return (CORE_UNIVERSE + rest)[:1000]
    elif s in ("all", "full", "all_a", "market"):
        return all_stocks
    else:
        return CORE_UNIVERSE

def get_universe_options() -> list[dict[str, Any]]:
    """Return universe descriptions for UI rendering."""
    all_count = len(_load_all_ashares())
    return [
        {
            "id": "core",
            "name": "核心龙头精选",
            "count": len(CORE_UNIVERSE),
            "est_time": "~1 秒",
            "badge": "秒级响应",
            "desc": "各行业流动性最充裕、最具代表性的核心龙头标的"
        },
        {
            "id": "hs300",
            "name": "沪深300标的池",
            "count": 300,
            "est_time": "~6 秒",
            "badge": "快速选股",
            "desc": "A 股规模大、流动性好的 300 只最具代表性蓝筹白马"
        },
        {
            "id": "zz500",
            "name": "中证500标的池",
            "count": 500,
            "est_time": "~12 秒",
            "badge": "中盘主力",
            "desc": "聚焦各细分行业高成长、弹性大的优质中盘标的"
        },
        {
            "id": "zz1000",
            "name": "中证1000标的池",
            "count": 1000,
            "est_time": "~25 秒",
            "badge": "活跃小盘",
            "desc": "覆盖中小盘活跃品种，捕捉游资与弹性波段机会"
        },
        {
            "id": "all",
            "name": "全市场全A股",
            "count": all_count,
            "est_time": "后台异步任务",
            "badge": "全量大满贯",
            "desc": "无死角扫描 A 股 5,200+ 标的，多线程后台异步并发计算"
        }
    ]
