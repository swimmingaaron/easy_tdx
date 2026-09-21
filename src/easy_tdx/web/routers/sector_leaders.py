"""
Sector Leaders Web API Router for easy_tdx
==========================================

提供板块龙头实时监测与深度量化分析服务：
- /api/sector_leaders: 领涨板块及各板块龙头股票矩阵
- /api/sector_leaders/search: 按板块名称或代码搜索
- /api/sector_leaders/detail: 深度查看单板块全量成分股及龙头排位
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Query

from easy_tdx.sector_leaders import (
    get_sector_leaders_data,
    search_sector_leader,
    analyze_single_board_leaders,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/sector_leaders", tags=["sector_leaders"])


@router.get("")
@router.get("/")
def get_sector_leaders(
    type: str = Query("hy", description="板块类型: hy (行业), gn (概念), all (全部)"),
    top_boards: int = Query(12, ge=1, le=50, description="前N个领涨板块"),
    top_stocks: int = Query(4, ge=1, le=20, description="每个板块展示前M只龙头候选"),
    sort_by: str = Query("change_pct", description="板块排序指标: change_pct, main_net_amount, amount"),
    force_refresh: bool = Query(False, description="是否强制刷新缓存"),
    use_cache: bool = Query(True, description="是否使用Cache缓存（默认开启）"),
) -> Dict[str, Any]:
    """获取全市场强势板块及其龙头股票监测池（支持双层缓存，默认开启）。"""
    try:
        data, from_cache, cache_time = get_sector_leaders_data(
            board_type=type,
            top_boards=top_boards,
            top_stocks=top_stocks,
            sort_by=sort_by,
            force_refresh=force_refresh,
            use_cache=use_cache,
            return_meta=True,
        )

        # 统计指标
        total_boards = len(data)
        zt_stocks_count = sum(
            1 for b in data for s in b.get("candidates", []) if s.get("is_zt")
        )
        ladder_stocks_count = sum(
            1 for b in data for s in b.get("candidates", []) if s.get("lbc", 0) >= 2
        )
        total_inflow = sum(b.get("main_net_amount", 0.0) for b in data)

        # 全市场连板高度龙联动（确保连板天梯与板块龙头数据一致性）
        best_ladder = None
        market_zt_count = zt_stocks_count
        try:
            from easy_tdx.market_ladder import get_market_ladder_and_matrix
            l_info = get_market_ladder_and_matrix()
            l_tiers = l_info.get("ladder", [])
            if l_tiers and l_tiers[0].get("stocks"):
                top_s = l_tiers[0]["stocks"][0]
                best_ladder = {
                    "code": str(top_s.get("code")),
                    "name": str(top_s.get("name")),
                    "lbc": int(top_s.get("lbc", 1)),
                    "price": float(top_s.get("price", 0.0)),
                    "change_pct": 10.0,
                    "amount": float(top_s.get("amt_yi", 1.0)) * 1e8,
                    "main_net_amount": float(top_s.get("main_net_amount", 0.0)),
                    "board_name": str(top_s.get("board_name", "空间高度")),
                    "role_tag": f"🔥 {top_s.get('lbc', 1)}连板龙头",
                }
            if l_info.get("stats", {}).get("zt_count"):
                market_zt_count = int(l_info["stats"]["zt_count"])
        except Exception as e:
            logger.debug("Failed to link market ladder dragon: %s", e)

        return {
            "success": True,
            "stat": {
                "total_boards": total_boards,
                "zt_count": market_zt_count,
                "ladder_count": ladder_stocks_count,
                "total_inflow": total_inflow,
                "best_ladder": best_ladder,
            },
            "boards": data,
            "from_cache": from_cache,
            "cache_time": cache_time,
        }
    except Exception as e:
        logger.exception("Failed to get sector leaders data: %s", e)
        return {"success": False, "error": str(e), "boards": [], "from_cache": False}


@router.get("/search")
def search_board_leader(
    query: str = Query(..., description="板块名称或代码，如 '半导体' 或 '881094'"),
    top_stocks: int = Query(10, ge=1, le=50, description="候选股票数量"),
    use_cache: bool = Query(True, description="是否使用Cache缓存（默认开启）"),
    force_refresh: bool = Query(False, description="是否强制刷新缓存"),
) -> Dict[str, Any]:
    """按名称或代码检索特定板块的龙头股票（支持缓存）。"""
    try:
        res = search_sector_leader(
            query=query,
            top_stocks=top_stocks,
            use_cache=use_cache,
            force_refresh=force_refresh,
        )
        if res:
            return {"success": True, "board": res, "from_cache": use_cache and not force_refresh}
        return {"success": False, "message": f"未找到匹配板块: {query}", "board": None}
    except Exception as e:
        logger.exception("Failed to search board leader: %s", e)
        return {"success": False, "error": str(e), "board": None}


@router.get("/detail")
def get_board_detail(
    board_code: str = Query(..., description="板块代码"),
    board_name: str = Query("", description="板块名称"),
    count: int = Query(30, ge=1, le=100, description="成分股数量"),
    use_cache: bool = Query(True, description="是否使用Cache缓存（默认开启）"),
    force_refresh: bool = Query(False, description="是否强制刷新缓存"),
) -> Dict[str, Any]:
    """获取指定板块的成分股排位与龙头细分（支持缓存）。"""
    try:
        res = analyze_single_board_leaders(
            board_code=board_code,
            board_name=board_name,
            top_candidates=count,
            use_cache=use_cache,
            force_refresh=force_refresh,
        )
        return {"success": True, "data": res, "from_cache": use_cache and not force_refresh}
    except Exception as e:
        logger.exception("Failed to get board detail: %s", e)
        return {"success": False, "error": str(e)}

