"""
easy_tdx Sector Leader Stocks Engine (板块龙头股票量化分析引擎)
===========================================================

基于 easy_tdx 原生通达信行情链路与连板天梯多因子矩阵，
秒级识别全市场强势行业与概念板块中的「领涨先锋」、「容量中军」与「短线连板龙头」。
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from easy_tdx import MacClient
from easy_tdx.mac.enums import BoardType, SortOrder, SortType
from easy_tdx.market_ladder import compute_exact_tdx_lbc
from easy_tdx.stock_lookup import get_stock_name

logger = logging.getLogger(__name__)

# 轻量内存缓存，防止前端高频轮询耗尽 TDX 连接
_SECTOR_LEADERS_CACHE: Dict[str, tuple[float, List[Dict[str, Any]]]] = {}
CACHE_TTL = 8.0  # 8秒有效缓存


def _is_limit_up(code: str, price: float, pre_close: float) -> bool:
    """判定股票是否触及涨停板。"""
    if pre_close <= 0 or price <= 0 or price == pre_close:
        return False
    pct = (price - pre_close) / pre_close * 100.0
    clean = code.strip().upper().replace("SH", "").replace("SZ", "").replace("BJ", "")
    if clean.startswith(("30", "68")):
        zt_p = round(pre_close * 1.20, 2)
        return pct >= 19.8 or price >= zt_p - 0.01
    elif clean.startswith(("92", "8", "4")):
        zt_p = round(pre_close * 1.30, 2)
        return pct >= 29.5 or price >= zt_p - 0.01
    else:
        zt_p = round(pre_close * 1.10, 2)
        return pct >= 9.8 or price >= zt_p - 0.01


def analyze_single_board_leaders(
    board_code: str,
    board_name: str = "",
    top_candidates: int = 5,
    client: Optional[MacClient] = None,
) -> Dict[str, Any]:
    """深度分析指定板块成分股，计算评选出龙头股票矩阵。"""
    clean_board_code = str(board_code).strip()
    
    def _fetch(c: MacClient):
        return c.get_board_members(
            clean_board_code,
            count=40,
            sort_type=SortType.CHANGE_PCT,
            sort_order=SortOrder.DESC,
        )

    if client is not None:
        df_members = _fetch(client)
    else:
        with MacClient.from_best_host() as c:
            df_members = _fetch(c)

    if df_members is None or df_members.empty:
        return {
            "board_code": clean_board_code,
            "board_name": board_name,
            "members_count": 0,
            "leader_pioneer": None,
            "leader_capacity": None,
            "leader_ladder": None,
            "candidates": [],
        }

    candidates = []
    max_amount = float(df_members["amount"].max()) if "amount" in df_members and not df_members["amount"].empty else 1.0
    max_amount = max(1.0, max_amount)

    for idx, row in df_members.iterrows():
        code = str(row.get("code", "")).zfill(6)
        name = get_stock_name(code)
        if not name or name.startswith("标的_"):
            name = str(row.get("name", "")).strip() or code

        price = float(row.get("close", 0.0) or 0.0)
        pre_close = float(row.get("pre_close", 0.0) or 0.0)
        if price <= 0.0:
            price = pre_close
            change_pct = 0.0
        else:
            change_pct = ((price - pre_close) / pre_close * 100.0) if pre_close > 0 else 0.0
        amount = float(row.get("amount", 0.0))
        main_net = float(row.get("main_net_amount", 0.0))
        vol_ratio = float(row.get("vol_ratio", 1.0))
        turnover = float(row.get("turnover", 0.0))

        is_zt = _is_limit_up(code, price, pre_close)
        lbc = compute_exact_tdx_lbc(code) if (is_zt or change_pct >= 8.0) else 0

        # 计算龙头得分 (Leader Score, 0 ~ 100)
        score_pct = min(35.0, max(0.0, (change_pct / 10.0) * 17.5))
        if change_pct >= 9.8:
            score_pct = 35.0

        net_yi = main_net / 1e8
        if net_yi >= 2.0:
            score_flow = 25.0
        elif net_yi > 0:
            score_flow = 10.0 + (net_yi / 2.0) * 15.0
        else:
            score_flow = max(0.0, 10.0 + net_yi * 5.0)

        score_amt = min(20.0, (amount / max_amount) * 20.0)
        score_active = min(10.0, max(2.0, (vol_ratio / 2.0) * 5.0 + min(5.0, turnover / 3.0)))

        score_bonus = 0.0
        if is_zt:
            score_bonus += 5.0
        if lbc > 1:
            score_bonus += min(5.0, (lbc - 1) * 2.0)

        leader_score = round(score_pct + score_flow + score_amt + score_active + score_bonus, 1)

        candidates.append({
            "code": code,
            "name": name,
            "price": round(price, 2),
            "pre_close": round(pre_close, 2),
            "change_pct": round(change_pct, 2),
            "amount": amount,
            "main_net_amount": main_net,
            "vol_ratio": round(vol_ratio, 2),
            "turnover": round(turnover, 2),
            "is_zt": is_zt,
            "lbc": lbc,
            "leader_score": leader_score,
            "role_tag": "领涨个股",
        })

    # 1. 确定领涨先锋
    candidates.sort(key=lambda x: (x["is_zt"], x["change_pct"], x["amount"]), reverse=True)
    pioneer = candidates[0] if candidates else None

    # 2. 确定容量中军 (金额前列且主力大单关注)
    by_amount = sorted(candidates, key=lambda x: x["amount"], reverse=True)
    capacity = by_amount[0] if by_amount and by_amount[0]["amount"] >= 2e8 else None

    # 3. 确定连板高度龙
    by_lbc = sorted(candidates, key=lambda x: x["lbc"], reverse=True)
    ladder = by_lbc[0] if by_lbc and by_lbc[0]["lbc"] >= 2 else None

    for s in candidates:
        tags = []
        if pioneer and s["code"] == pioneer["code"]:
            tags.append("👑 领涨先锋")
        if capacity and s["code"] == capacity["code"]:
            tags.append("🛡️ 容量中军")
        if ladder and s["code"] == ladder["code"]:
            tags.append(f"🔥 {ladder['lbc']}连板龙头")
        elif s["is_zt"]:
            tags.append("涨停标杆")
        elif s["change_pct"] >= 7.0:
            tags.append("前排冲锋")
        elif s["vol_ratio"] >= 2.0:
            tags.append("放量突破")
        s["role_tag"] = " | ".join(tags) if tags else "跟随标的"

    # 按龙头得分排序输出
    candidates.sort(key=lambda x: x["leader_score"], reverse=True)

    return {
        "board_code": clean_board_code,
        "board_name": board_name,
        "members_count": len(df_members),
        "leader_pioneer": pioneer,
        "leader_capacity": capacity,
        "leader_ladder": ladder,
        "candidates": candidates[:top_candidates],
    }


def get_sector_leaders_data(
    board_type: str = "hy",
    top_boards: int = 12,
    top_stocks: int = 4,
    sort_by: str = "change_pct",
    force_refresh: bool = False,
) -> List[Dict[str, Any]]:
    """获取板块龙头列表（含缓存支持）。"""
    cache_key = f"{board_type}_{top_boards}_{top_stocks}_{sort_by}"
    now = time.time()
    if not force_refresh and cache_key in _SECTOR_LEADERS_CACHE:
        ts, cached_data = _SECTOR_LEADERS_CACHE[cache_key]
        if now - ts < CACHE_TTL:
            return cached_data

    target_types = []
    b_type_lower = board_type.lower().strip()
    if b_type_lower == "gn":
        target_types.append((BoardType.GN, "概念"))
    elif b_type_lower == "all":
        half = max(4, top_boards // 2)
        target_types.append((BoardType.HY, "行业"))
        target_types.append((BoardType.GN, "概念"))
    else:
        target_types.append((BoardType.HY, "行业"))

    results = []
    with MacClient.from_best_host() as c:
        for b_enum, type_label in target_types:
            fetch_count = top_boards if len(target_types) == 1 else max(4, top_boards // 2)
            df_ranking = c.get_board_ranking(b_enum, top_n=fetch_count, sort_by=sort_by)
            if df_ranking is not None and not df_ranking.empty and df_ranking["change_pct"].abs().max() == 0.0:
                try:
                    from easy_tdx.mac.enums import BoardSortColumn
                    df_5d = c.get_board_list(board_type=b_enum, count=fetch_count, sort_column=BoardSortColumn.CHANGE_5D)
                    if df_5d is not None and not df_5d.empty:
                        df_ranking = df_5d.rename(columns={"sort_value": "change_pct"})
                except Exception as e:
                    logger.debug("Fallback to CHANGE_5D failed: %s", e)
            if df_ranking is None or df_ranking.empty:
                continue

            for _, row in df_ranking.iterrows():
                b_code = str(row.get("code", "")).strip()
                b_name = str(row.get("name", "")).strip()
                b_pct = float(row.get("change_pct", 0.0))
                b_amt = float(row.get("amount", 0.0))
                b_net = float(row.get("main_net_amount", 0.0))
                up_cnt = int(row.get("up_count", 0))
                down_cnt = int(row.get("down_count", 0))

                analysis = analyze_single_board_leaders(
                    board_code=b_code,
                    board_name=b_name,
                    top_candidates=top_stocks,
                    client=c,
                )
                analysis["board_type"] = type_label
                analysis["change_pct"] = round(b_pct, 2)
                analysis["amount"] = b_amt
                analysis["main_net_amount"] = b_net
                analysis["up_count"] = up_cnt
                analysis["down_count"] = down_cnt
                results.append(analysis)

    # 排序
    if sort_by == "main_net_amount":
        results.sort(key=lambda x: x.get("main_net_amount", 0.0), reverse=True)
    elif sort_by == "amount":
        results.sort(key=lambda x: x.get("amount", 0.0), reverse=True)
    else:
        results.sort(key=lambda x: x.get("change_pct", 0.0), reverse=True)

    _SECTOR_LEADERS_CACHE[cache_key] = (now, results)
    return results


def search_sector_leader(
    query: str,
    top_stocks: int = 10,
) -> Optional[Dict[str, Any]]:
    """搜索指定板块并深度分析龙头候选。"""
    q = query.strip().upper()
    with MacClient.from_best_host() as c:
        for b_enum, type_label in [(BoardType.HY, "行业"), (BoardType.GN, "概念")]:
            df = c.get_board_ranking(b_enum, top_n=400, sort_by="change_pct")
            if df is None or df.empty:
                continue
            for _, row in df.iterrows():
                code_str = str(row.get("code", "")).strip()
                name_str = str(row.get("name", "")).strip()
                if q == code_str or q in name_str or name_str in q:
                    analysis = analyze_single_board_leaders(
                        board_code=code_str,
                        board_name=name_str,
                        top_candidates=top_stocks,
                        client=c,
                    )
                    analysis["board_type"] = type_label
                    analysis["change_pct"] = round(float(row.get("change_pct", 0.0)), 2)
                    analysis["amount"] = float(row.get("amount", 0.0))
                    analysis["main_net_amount"] = float(row.get("main_net_amount", 0.0))
                    analysis["up_count"] = int(row.get("up_count", 0))
                    analysis["down_count"] = int(row.get("down_count", 0))
                    return analysis
    return None
