"""
easy_tdx Sector Leader Stocks Engine (板块龙头股票量化分析引擎)
===========================================================

基于 easy_tdx 原生通达信行情链路与连板天梯多因子矩阵，
秒级识别全市场强势行业与概念板块中的「领涨先锋」、「容量中军」与「短线连板龙头」。
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple, Union

from easy_tdx import MacClient
from easy_tdx.mac.enums import BoardType, SortOrder, SortType
from easy_tdx.market_ladder import compute_exact_tdx_lbc
from easy_tdx.market_overview import is_trading_time
from easy_tdx.stock_lookup import get_stock_name

logger = logging.getLogger(__name__)

import threading

# 缓存配置与目录
_CACHE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "sector_leaders_cache"))
try:
    os.makedirs(_CACHE_DIR, exist_ok=True)
except Exception:
    pass

# 双层缓存体系：内存极速缓存 + 磁盘持久化快照
_SECTOR_LEADERS_CACHE: Dict[str, Tuple[float, List[Dict[str, Any]]]] = {}
_BOARD_DETAIL_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}
_SEARCH_CACHE: Dict[str, Tuple[float, Optional[Dict[str, Any]]]] = {}

# SWR (Stale-While-Revalidate) 异步后台更新锁与状态
_SWR_LOCK = threading.Lock()
_SWR_ACTIVE: set[str] = set()

# 交易时间内行情变化快强缓存30秒，收盘/非交易时段数据稳定强缓存3600秒
CACHE_TTL_INTRADAY = 30.0
CACHE_TTL_POST_MARKET = 3600.0


def _get_cache_ttl() -> float:
    """根据是否在交易时间动态返回有效 TTL。"""
    try:
        return CACHE_TTL_INTRADAY if is_trading_time() else CACHE_TTL_POST_MARKET
    except Exception:
        return CACHE_TTL_INTRADAY


def _trigger_async_sector_refresh(board_type: str, top_boards: int, top_stocks: int, sort_by: str) -> None:
    """SWR 核心机制：在后台异步静默更新板块龙头数据，绝不卡顿前端用户界面。"""
    cache_key = f"{board_type}_{top_boards}_{top_stocks}_{sort_by}"
    with _SWR_LOCK:
        if cache_key in _SWR_ACTIVE:
            return
        _SWR_ACTIVE.add(cache_key)

    def _worker():
        try:
            logger.info("Starting background SWR refresh for sector leaders: %s", cache_key)
            get_sector_leaders_data(
                board_type=board_type,
                top_boards=top_boards,
                top_stocks=top_stocks,
                sort_by=sort_by,
                force_refresh=True,
                use_cache=False,
            )
            logger.info("Background SWR refresh completed for: %s", cache_key)
        except Exception as e:
            logger.debug("Async sector leaders refresh error for %s: %s", cache_key, e)
        finally:
            with _SWR_LOCK:
                _SWR_ACTIVE.discard(cache_key)

    t = threading.Thread(target=_worker, daemon=True, name=f"SectorLeadersSWR-{cache_key}")
    t.start()


def _get_disk_cache_path(key: str) -> str:
    safe_key = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in key)
    return os.path.join(_CACHE_DIR, f"{safe_key}.json")


def _read_disk_cache(key: str, max_age: float) -> Optional[Tuple[float, Any]]:
    path = _get_disk_cache_path(key)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            wrapper = json.load(f)
            ts = wrapper.get("timestamp", 0.0)
            data = wrapper.get("data")
            if time.time() - ts < max_age and data is not None:
                return (ts, data)
    except Exception as e:
        logger.debug("Failed reading disk cache %s: %s", path, e)
    return None


def _write_disk_cache(key: str, data: Any, timestamp: float) -> None:
    path = _get_disk_cache_path(key)
    try:
        temp_path = f"{path}.tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump({"timestamp": timestamp, "data": data}, f, ensure_ascii=False, indent=1)
        os.replace(temp_path, path)
    except Exception as e:
        logger.debug("Failed writing disk cache %s: %s", path, e)


def clear_sector_leaders_cache() -> None:
    """清空板块龙头的所有内存与本地磁盘缓存。"""
    _SECTOR_LEADERS_CACHE.clear()
    _BOARD_DETAIL_CACHE.clear()
    _SEARCH_CACHE.clear()
    try:
        if os.path.exists(_CACHE_DIR):
            for fname in os.listdir(_CACHE_DIR):
                fpath = os.path.join(_CACHE_DIR, fname)
                if os.path.isfile(fpath):
                    try:
                        os.remove(fpath)
                    except Exception:
                        pass
    except Exception as e:
        logger.debug("Failed clearing sector leaders disk cache: %s", e)


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
    use_cache: bool = True,
    force_refresh: bool = False,
) -> Dict[str, Any]:
    """深度分析指定板块成分股，计算评选出龙头股票矩阵（支持双层缓存）。"""
    clean_board_code = str(board_code).strip()
    cache_key = f"board_{clean_board_code}_{top_candidates}"
    now = time.time()
    ttl = _get_cache_ttl()

    if use_cache and not force_refresh:
        if cache_key in _BOARD_DETAIL_CACHE:
            ts, cached_data = _BOARD_DETAIL_CACHE[cache_key]
            if now - ts < ttl and cached_data:
                return cached_data
        disk_hit = _read_disk_cache(cache_key, max_age=ttl)
        if disk_hit is not None:
            ts, cached_data = disk_hit
            _BOARD_DETAIL_CACHE[cache_key] = (ts, cached_data)
            return cached_data

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
        empty_res = {
            "board_code": clean_board_code,
            "board_name": board_name,
            "members_count": 0,
            "leader_pioneer": None,
            "leader_capacity": None,
            "leader_ladder": None,
            "candidates": [],
        }
        return empty_res

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

        # 计算基础龙头得分 (Leader Score, 0 ~ 100)
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
        score_bonus = 5.0 if is_zt else 0.0

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
            "lbc": 0,
            "leader_score": leader_score,
            "role_tag": "领涨个股",
        })

    # 先按基础综合得分初步排序，选出前排重点候选（仅对前排涨停股精确计算连板天梯，避免90%无意义网络IO）
    candidates.sort(key=lambda x: (x["is_zt"], x["leader_score"]), reverse=True)
    check_limit = min(len(candidates), max(top_candidates, 5))
    for s in candidates[:check_limit]:
        if s["is_zt"]:
            s_lbc = compute_exact_tdx_lbc(s["code"])
            s["lbc"] = s_lbc
            if s_lbc > 1:
                s["leader_score"] = round(s["leader_score"] + min(5.0, (s_lbc - 1) * 2.0), 1)

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

    result = {
        "board_code": clean_board_code,
        "board_name": board_name,
        "members_count": len(df_members),
        "leader_pioneer": pioneer,
        "leader_capacity": capacity,
        "leader_ladder": ladder,
        "candidates": candidates[:top_candidates],
    }
    _BOARD_DETAIL_CACHE[cache_key] = (now, result)
    _write_disk_cache(cache_key, result, now)
    return result


def get_sector_leaders_data(
    board_type: str = "hy",
    top_boards: int = 12,
    top_stocks: int = 4,
    sort_by: str = "change_pct",
    force_refresh: bool = False,
    use_cache: bool = True,
    return_meta: bool = False,
) -> Any:
    """获取板块龙头列表（含 SWR 极速响应双层 Cache 体系，默认开启）。"""
    cache_key = f"{board_type}_{top_boards}_{top_stocks}_{sort_by}"
    now = time.time()
    ttl = _get_cache_ttl()

    if use_cache and not force_refresh:
        # 1. 内存缓存命中 (SWR 模式：只要有缓存立即毫秒级返回，超过TTL静默后台异步刷新)
        if cache_key in _SECTOR_LEADERS_CACHE:
            ts, cached_data = _SECTOR_LEADERS_CACHE[cache_key]
            if cached_data:
                if now - ts < ttl:
                    logger.debug("Hit sector leaders memory cache: %s (age=%.1fs)", cache_key, now - ts)
                    return (cached_data, True, ts) if return_meta else cached_data
                # 超过 TTL：SWR 模式立即返回旧缓存，并静默后台更新
                logger.debug("SWR trigger background refresh for %s (age=%.1fs > %.1fs)", cache_key, now - ts, ttl)
                _trigger_async_sector_refresh(board_type, top_boards, top_stocks, sort_by)
                return (cached_data, True, ts) if return_meta else cached_data

        # 2. 本地持久化磁盘快照命中 (允许最长 30 天磁盘快照立即 0ms 呈现，并在后台自动静默刷新)
        disk_hit = _read_disk_cache(cache_key, max_age=86400.0 * 30)
        if disk_hit is not None:
            ts, cached_data = disk_hit
            _SECTOR_LEADERS_CACHE[cache_key] = (ts, cached_data)
            logger.debug("Hit sector leaders disk snapshot: %s (age=%.1fs)", cache_key, now - ts)
            if now - ts >= ttl:
                _trigger_async_sector_refresh(board_type, top_boards, top_stocks, sort_by)
            return (cached_data, True, ts) if return_meta else cached_data


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
                    use_cache=use_cache,
                    force_refresh=force_refresh,
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
    _write_disk_cache(cache_key, results, now)
    return (results, False, now) if return_meta else results


def search_sector_leader(
    query: str,
    top_stocks: int = 10,
    use_cache: bool = True,
    force_refresh: bool = False,
) -> Optional[Dict[str, Any]]:
    """搜索指定板块并深度分析龙头候选（支持双层缓存）。"""
    q = query.strip().upper()
    cache_key = f"search_{q}_{top_stocks}"
    now = time.time()
    ttl = _get_cache_ttl()

    if use_cache and not force_refresh:
        if cache_key in _SEARCH_CACHE:
            ts, cached = _SEARCH_CACHE[cache_key]
            if now - ts < ttl:
                return cached
        disk_hit = _read_disk_cache(cache_key, max_age=ttl)
        if disk_hit is not None:
            ts, cached = disk_hit
            _SEARCH_CACHE[cache_key] = (ts, cached)
            return cached

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
                        use_cache=use_cache,
                        force_refresh=force_refresh,
                    )
                    analysis["board_type"] = type_label
                    analysis["change_pct"] = round(float(row.get("change_pct", 0.0)), 2)
                    analysis["amount"] = float(row.get("amount", 0.0))
                    analysis["main_net_amount"] = float(row.get("main_net_amount", 0.0))
                    analysis["up_count"] = int(row.get("up_count", 0))
                    analysis["down_count"] = int(row.get("down_count", 0))
                    _SEARCH_CACHE[cache_key] = (now, analysis)
                    _write_disk_cache(cache_key, analysis, now)
                    return analysis
    return None
