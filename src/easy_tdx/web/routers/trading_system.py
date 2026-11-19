"""Trading System Web API Router for easy_tdx

提供对齐原 trading_system.cgi 的全部后台服务：
- /api/trading_system/dashboard: 信号看板
- /api/trading_system/screener: 5 大共振选股
- /api/trading_system/fina_analysis/{code}: 业绩诊断与近 8 期财报
- /api/trading_system/history/{code}: 单股历史变迁回溯
- /api/trading_system/toggle_watchlist: 自选股联动
- /api/trading_system/watchlist: 获取当前自选
"""
from __future__ import annotations

import logging
import os
import json
import threading
from typing import Any, Dict, List, Optional, Tuple
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel

from easy_tdx.trading_system.engine import (
    generate_llm_fina_analysis,
    evaluate_universe,
    fetch_stock_financials,
    evaluate_stock_history,
    compute_fina_score,
    get_universe_eval_progress,
    has_universe_cache,
    is_universe_evaluating,
    start_background_universe_eval,
    _PERSISTENT_HOLDERS_DATA,
    fetch_stock_holders,
)
from easy_tdx.watchlist_store import load_watchlist, save_watchlist, load_watchlist_items
from easy_tdx.screener.universe import get_universe_symbols
from easy_tdx.stock_lookup import get_stock_name

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/trading_system", tags=["trading_system"])


class WatchlistToggleReq(BaseModel):
    stock_code: str
    status: bool  # True for add, False for remove
    stock_name: Optional[str] = None


@router.get("/watchlist")
def get_current_watchlist() -> Dict[str, Any]:
    """获取当前所有自选股代码列表与标的名称。"""
    try:
        wl = load_watchlist()
        items = load_watchlist_items()
        return {"success": True, "watchlist": wl, "items": items}
    except Exception as e:
        logger.error(f"Failed to load watchlist: {e}")
        return {"success": False, "watchlist": [], "items": [], "error": str(e)}


@router.post("/toggle_watchlist")
def toggle_watchlist_stock(req: WatchlistToggleReq) -> Dict[str, Any]:
    """一键将个股加入或移出自选，持久化保存到 watchlist.json。"""
    clean_code = req.stock_code.strip().upper().replace("SH", "").replace("SZ", "").replace("BJ", "")
    try:
        existing_items = load_watchlist_items()
        items_map = {str(item["code"]): str(item.get("name") or "") for item in existing_items}

        if req.status:
            # 添加自选
            name = (req.stock_name or "").strip()
            if not name or name.startswith("标的_"):
                name = items_map.get(clean_code) or get_stock_name(clean_code) or clean_code
            items_map[clean_code] = name
            # 保证最新加入的排在前面
            new_items = [{"code": clean_code, "name": name}] + [
                {"code": c, "name": n} for c, n in items_map.items() if c != clean_code
            ]
        else:
            # 移出自选
            items_map.pop(clean_code, None)
            new_items = [{"code": c, "name": n} for c, n in items_map.items()]

        saved = save_watchlist(new_items, allow_empty=True)
        fresh_items = load_watchlist_items()

        # 触发清理实时行情缓存
        try:
            import easy_tdx.web.routers.quotes as q_mod
            with q_mod._REALTIME_QUOTES_LOCK:
                q_mod._REALTIME_QUOTES_CACHE = None
        except Exception:
            pass

        return {
            "success": True,
            "stock_code": clean_code,
            "status": req.status,
            "watchlist": saved,
            "items": fresh_items,
        }
    except Exception as e:
        logger.error(f"Failed to toggle watchlist for {clean_code}: {e}")
        return {"success": False, "error": str(e)}


@router.get("/progress")
def get_evaluation_progress(
    universe: str = Query("core"),
    period: str = Query("day", description="K线周期: 30m, 60m, 120m, day, week, month"),
) -> Dict[str, Any]:
    """获取股票池量化计算实时进度与当前正在处理的股票"""
    from easy_tdx.trading_system.engine import get_universe_eval_progress
    return get_universe_eval_progress(universe, period=period)


_RANGE_PRICE_CACHE: Dict[Tuple[str, str, str], Tuple[Optional[float], Optional[str], Optional[float], Optional[str]]] = {}
_RANGE_CACHE_LOCK = threading.Lock()
_SNAPSHOT_DATE_MAP: Dict[str, Dict[str, float]] = {}
_SNAPSHOT_MAP_LOCK = threading.Lock()


def _ensure_snapshot_map() -> Dict[str, Dict[str, float]]:
    """加载历史全市场量化快照底表数据，用于全量标的秒级区间基准价对齐。"""
    global _SNAPSHOT_DATE_MAP
    with _SNAPSHOT_MAP_LOCK:
        if _SNAPSHOT_DATE_MAP:
            return _SNAPSHOT_DATE_MAP
        import glob
        import re
        from easy_tdx.trading_system.engine import _CACHE_DIR
        pattern = os.path.join(_CACHE_DIR, "universe_all_*.json")
        files = glob.glob(pattern)
        m_map: Dict[str, Dict[str, float]] = {}
        for f in files:
            m = re.search(r"2026\d{4}", f)
            if not m:
                continue
            raw_d = m.group(0)
            fmt_d = f"{raw_d[:4]}-{raw_d[4:6]}-{raw_d[6:8]}"
            try:
                with open(f, "r", encoding="utf-8") as fp:
                    data = json.load(fp)
                    c_map: Dict[str, float] = {}
                    for item in data:
                        c = item.get("stock_code")
                        p = float(item.get("close") or 0.0)
                        if c and p > 0:
                            c_map[c] = p
                    if c_map:
                        m_map[fmt_d] = c_map
            except Exception:
                pass
        _SNAPSHOT_DATE_MAP = m_map
        return _SNAPSHOT_DATE_MAP


def _get_range_prices(
    code: str,
    start_date: str,
    end_date: Optional[str] = None,
    allow_network: bool = False,
) -> Tuple[Optional[float], Optional[str], Optional[float], Optional[str]]:
    """
    获取标的在 start_date 当天或其后首个交易日的收盘基准价，以及在 end_date 当天或其前最后交易日的收盘价。
    多级高速缓存设计：
      1. 内存高速缓存 (_RANGE_PRICE_CACHE)
      2. 本地磁盘持久化 K 线库 (KlineDiskCache) 极速秒读 (无网络开销与锁争用)
      3. 历史全市场量化快照底表 (_SNAPSHOT_DATE_MAP) O(1) 瞬时补齐
      4. 仅在小型自选/核心池 (allow_network=True) 且确实无缓存时，才发起网络兜底
    返回: (start_price, act_start_date, end_price, act_end_date)
    """
    clean_sd = start_date.strip()[:10] if start_date else ""
    clean_ed = end_date.strip()[:10] if (end_date and str(end_date).strip()) else ""
    if not clean_sd:
        return None, None, None, None

    cache_key = (code, clean_sd, clean_ed)
    with _RANGE_CACHE_LOCK:
        if cache_key in _RANGE_PRICE_CACHE:
            return _RANGE_PRICE_CACHE[cache_key]

    # 1. 优先从本地磁盘持久化 K 线缓存直接读取 (无需网络交互，并行极速)
    try:
        from easy_tdx.kline_cache import get_global_kline_disk_cache
        from easy_tdx.market_data import _get_market, Market
        disk_cache = get_global_kline_disk_cache()
        market = _get_market(code)
        cache_sym = f"SH_{code}" if (market == Market.SH and code.startswith("00")) else code
        df = disk_cache.read_cached(cache_sym, "DAY", "QFQ")
        if df is not None and not df.empty and "datetime" in df.columns:
            sub_start = df[df["datetime"] >= clean_sd]
            if not sub_start.empty:
                start_row = sub_start.iloc[0]
                start_price = float(start_row["close"])
                act_sd = str(start_row["datetime"])[:10]

                if clean_ed:
                    sub_end = df[df["datetime"] <= clean_ed]
                    if not sub_end.empty:
                        end_row = sub_end.iloc[-1]
                        end_price = float(end_row["close"])
                        act_ed = str(end_row["datetime"])[:10]
                    else:
                        end_price = None
                        act_ed = None
                else:
                    end_row = df.iloc[-1]
                    end_price = float(end_row["close"])
                    act_ed = str(end_row["datetime"])[:10]

                res = (start_price, act_sd, end_price, act_ed)
                with _RANGE_CACHE_LOCK:
                    _RANGE_PRICE_CACHE[cache_key] = res
                return res
    except Exception as ex:
        logger.debug(f"disk_cache lookup failed for {code}: {ex}")

    # 2. 查阅历史全市场量化快照底表数据对齐基准价
    try:
        snap_map = _ensure_snapshot_map()
        if snap_map:
            avail_dates = sorted(snap_map.keys())
            target_sd = None
            for d in avail_dates:
                if d >= clean_sd:
                    target_sd = d
                    break
            if not target_sd and avail_dates:
                target_sd = avail_dates[-1]

            sp = snap_map.get(target_sd, {}).get(code) if target_sd else None
            act_sd = target_sd if sp else None

            ep = None
            act_ed = None
            if clean_ed:
                target_ed = None
                for d in reversed(avail_dates):
                    if d <= clean_ed:
                        target_ed = d
                        break
                if target_ed:
                    ep = snap_map.get(target_ed, {}).get(code)
                    act_ed = target_ed if ep else None

            if sp:
                res = (sp, act_sd, ep, act_ed)
                with _RANGE_CACHE_LOCK:
                    _RANGE_PRICE_CACHE[cache_key] = res
                return res
    except Exception as ex:
        logger.debug(f"snapshot map lookup failed for {code}: {ex}")

    # 3. 仅在允许网络请求（标的数量 <= 200）且以上两层均未命中时发起网络兜底
    if allow_network:
        try:
            from easy_tdx.market_data import fetch_security_kline
            df = fetch_security_kline(code, count=300, period="DAY")
            if df is not None and not df.empty and "datetime" in df.columns:
                sub_start = df[df["datetime"] >= clean_sd]
                if not sub_start.empty:
                    start_row = sub_start.iloc[0]
                    start_price = float(start_row["close"])
                    act_sd = str(start_row["datetime"])[:10]

                    if clean_ed:
                        sub_end = df[df["datetime"] <= clean_ed]
                        if not sub_end.empty:
                            end_row = sub_end.iloc[-1]
                            end_price = float(end_row["close"])
                            act_ed = str(end_row["datetime"])[:10]
                        else:
                            end_price = None
                            act_ed = None
                    else:
                        end_row = df.iloc[-1]
                        end_price = float(end_row["close"])
                        act_ed = str(end_row["datetime"])[:10]

                    res = (start_price, act_sd, end_price, act_ed)
                    with _RANGE_CACHE_LOCK:
                        _RANGE_PRICE_CACHE[cache_key] = res
                    return res
        except Exception as ex:
            logger.debug(f"fetch_security_kline network failed for {code}: {ex}")

    return None, None, None, None


@router.get("/dashboard")
def get_signal_dashboard(
    min_buy: int = Query(0, description="最低买入分"),
    max_sell: int = Query(10, description="最高卖出分"),
    industry: str = Query("", description="行业分类"),
    search_stock: str = Query("", description="搜索代码或名称"),
    my_optional: bool = Query(False, description="仅看我的自选"),
    universe: str = Query("core", description="股票池: core, hs300, zz500, all"),
    period: str = Query("day", description="K线周期: 30m, 60m, 120m, day, week, month"),
    sort_col: str = Query("buy_score", description="排序字段"),
    sort_dir: str = Query("desc", description="排序方向: asc, desc"),
    selected_date: str = Query("", description="选定日期"),
    force_refresh: bool = Query(False, description="强制刷新缓存"),
    symbols: Optional[str] = Query(None, description="逗号分隔的个股代码列表"),
    start_date: Optional[str] = Query(None, description="区间统计起始时间 YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="区间统计截至时间 YYYY-MM-DD"),
) -> Dict[str, Any]:
    """
    信号看板：包含 18 项买入打分、9 项卖出预警打分、量价红星/绿星、ZIG转向与战法识别。
    """
    try:
        search_kw = search_stock.strip().upper() if isinstance(search_stock, str) else ""
        symbols_str = symbols if isinstance(symbols, str) and symbols.strip() else None
        univ = universe if isinstance(universe, str) else "core"
        is_my_opt = bool(my_optional) if isinstance(my_optional, bool) else False
        force_ref = bool(force_refresh) if isinstance(force_refresh, bool) else False
        ind_filter = industry.strip() if isinstance(industry, str) else ""
        min_b = min_buy if isinstance(min_buy, (int, float)) else 0
        max_s = max_sell if isinstance(max_sell, (int, float)) else 10
        sort_field = sort_col if isinstance(sort_col, str) else "buy_score"
        sort_direction = sort_dir if isinstance(sort_dir, str) else "desc"

        symbols_set = None
        matched_search_codes: set[str] = set()
        if search_kw:
            from easy_tdx.stock_lookup import search_stocks
            s_matches = search_stocks(search_kw, limit=10)
            matched_search_codes = {str(item["code"]) for item in s_matches}

        if search_kw.isdigit() and len(search_kw) == 6:
            # 优先回溯历史或精准评估该股
            single_res = evaluate_universe([search_kw], max_workers=1, period=period)
            all_stocks = single_res
        elif len(matched_search_codes) == 1 and not symbols_str and not is_my_opt:
            # 拼音或名称唯一定位单个标的 (如 rssh -> 002493)
            resolved_code = list(matched_search_codes)[0]
            single_res = evaluate_universe([resolved_code], max_workers=1, period=period)
            all_stocks = single_res
        elif symbols_str:
            clean_syms = [s.strip().upper().replace("SH", "").replace("SZ", "").replace("BJ", "") for s in symbols_str.split(",") if s.strip()]
            symbols_set = set(clean_syms)
            all_stocks = evaluate_universe(symbols=clean_syms, universe_type="custom", period=period, force_refresh=force_ref)
        else:
            wl_symbols = None
            if is_my_opt:
                wl_symbols = load_watchlist()
                if not wl_symbols:
                    return {
                        "success": True,
                        "total_count": 0,
                        "stat": {"total": 0, "strong_buy": 0, "buy": 0, "watch": 0, "danger": 0, "star_buy": 0, "star_sell": 0},
                        "rows": [],
                        "industries": [],
                        "watchlist": [],
                        "period": period,
                    }
            # 对于大股票池（如 all 全市场 5000+ 或 zz1000）：
            # 1. 若强制刷新：如果未在计算则启动后台线程，立即返回 running 状态，避免反向代理超时
            # 2. 若未强制刷新：只要已有缓存，则直接读取缓存返回数据；若完全无缓存且未在计算，才启动后台线程
            if univ in ("all", "zz1000") and not is_my_opt:
                if force_ref:
                    if not is_universe_evaluating(univ, period=period):
                        start_background_universe_eval(univ, period=period, force_refresh=True)
                    return {
                        "success": True,
                        "status": "running",
                        "message": f"{univ} 股票池量化模型正在后台极速重算...",
                        "progress": get_universe_eval_progress(univ, period=period),
                        "period": period,
                    }
                elif not has_universe_cache(univ, period=period):
                    if not is_universe_evaluating(univ, period=period):
                        start_background_universe_eval(univ, period=period, force_refresh=False)
                    return {
                        "success": True,
                        "status": "running",
                        "message": f"{univ} 股票池量化模型初次载入中，正在后台极速计算...",
                        "progress": get_universe_eval_progress(univ, period=period),
                        "period": period,
                    }

            all_stocks = evaluate_universe(symbols=wl_symbols, universe_type=univ, period=period, force_refresh=force_ref)

        # 确保每只标的均含有真实股票名称与量化体检得分
        for s in all_stocks:
            sc = str(s.get("stock_code") or "")
            sn = str(s.get("stock_name") or "")
            if not sn or sn.startswith("标的_"):
                rn = get_stock_name(sc)
                if rn and not rn.startswith("标的_"):
                    s["stock_name"] = rn
            if s.get("fina_score") is None:
                s["fina_score"] = compute_fina_score([s])
            if sc in _PERSISTENT_HOLDERS_DATA:
                p_data = _PERSISTENT_HOLDERS_DATA[sc]
                if (not s.get("holder_ratio") or float(s.get("holder_ratio") or 0) <= 0) and float(p_data.get("holder_ratio") or 0) > 0:
                    s["holder_ratio"] = float(p_data["holder_ratio"])
                if (not s.get("holder_focus") or s.get("holder_focus") == "--") and p_data.get("holder_focus") and p_data["holder_focus"] != "--":
                    s["holder_focus"] = p_data["holder_focus"]
                if not s.get("holders_changes") and p_data.get("holders_changes"):
                    s["holders_changes"] = list(p_data["holders_changes"])
                if not s.get("holders_history") and p_data.get("holders_history"):
                    s["holders_history"] = list(p_data["holders_history"])
                if (not s.get("holders_num") or s.get("holders_num") == 0) and p_data.get("holders_num"):
                    s["holders_num"] = int(p_data["holders_num"])
                    s["holders_str"] = str(p_data.get("holders_str", "--"))

        watchlist_set = set(load_watchlist())

        # 收集所有行业供前端下拉筛选
        industries_set = {s["industry"] for s in all_stocks if s.get("industry") and s["industry"] != "--"}
        industries = sorted(list(industries_set))

        # 过滤
        filtered: List[Dict[str, Any]] = []
        for s in all_stocks:
            # 指定股票列表过滤
            if symbols_set and s["stock_code"] not in symbols_set:
                continue

            # 搜索过滤（支持 6位代码、拼音首字母、中文名称）
            if search_kw:
                code_match = search_kw in s["stock_code"] or s["stock_code"] in matched_search_codes
                name_match = search_kw in s["stock_name"]
                pinyin_match = False
                py = s.get("pinyin")
                if not py:
                    from easy_tdx.stock_lookup import get_stock_pinyin
                    py = get_stock_pinyin(s["stock_code"])
                    s["pinyin"] = py
                if py and search_kw in py:
                    pinyin_match = True
                if not (code_match or name_match or pinyin_match):
                    continue
            
            # 自选过滤
            if is_my_opt and s["stock_code"] not in watchlist_set:
                continue

            # 行业过滤
            if ind_filter and ind_filter != "全部" and s.get("industry") != ind_filter:
                continue

            # 买入分/卖出分过滤
            if s.get("buy_score", 0) < min_b:
                continue
            if s.get("sell_score", 0) > max_s:
                continue

            # 标记自选状态
            s["is_optional"] = s["stock_code"] in watchlist_set
            filtered.append(s)

        # 区间统计计算
        if start_date and str(start_date).strip():
            clean_sd = str(start_date).strip()[:10]
            clean_ed = str(end_date).strip()[:10] if (end_date and str(end_date).strip()) else ""
            from concurrent.futures import ThreadPoolExecutor

            allow_net = len(filtered) <= 200

            def _attach_range_stats(s_item: Dict[str, Any]) -> None:
                sc = str(s_item.get("stock_code") or "")
                sp, act_sd, ep, act_ed = _get_range_prices(sc, clean_sd, clean_ed, allow_network=allow_net)
                curr_p = float(s_item.get("close") or s_item.get("price") or 0.0)
                # 若无指定截至日或截至日即今日，采用实时最新价；若指定了历史截至日，采用该截至日收盘价
                effective_end_p = ep if (clean_ed and ep is not None and ep > 0) else curr_p
                if sp and sp > 0 and effective_end_p > 0:
                    r_pct = round(((effective_end_p - sp) / sp) * 100.0, 2)
                    s_item["range_pct"] = r_pct
                    s_item["start_price"] = sp
                    s_item["start_date"] = act_sd
                    s_item["end_price"] = effective_end_p
                    s_item["end_date"] = act_ed
                else:
                    s_item["range_pct"] = None
                    s_item["start_price"] = None
                    s_item["start_date"] = None
                    s_item["end_price"] = None
                    s_item["end_date"] = None

            max_workers = min(32, max(1, len(filtered)))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                list(executor.map(_attach_range_stats, filtered))
        else:
            for s_item in filtered:
                s_item["range_pct"] = None
                s_item["start_price"] = None
                s_item["start_date"] = None
                s_item["end_price"] = None
                s_item["end_date"] = None

        # 统计面板数据
        total_cnt = len(filtered)
        strong_buy_cnt = sum(1 for s in filtered if s.get("buy_score", 0) >= 10)
        buy_cnt = sum(1 for s in filtered if 8 <= s.get("buy_score", 0) < 10)
        watch_cnt = sum(1 for s in filtered if 5 <= s.get("buy_score", 0) < 8)
        danger_cnt = sum(1 for s in filtered if s.get("sell_score", 0) >= 3)
        star_buy_cnt = sum(1 for s in filtered if s.get("star_buy"))
        star_sell_cnt = sum(1 for s in filtered if s.get("star_sell"))

        stat = {
            "total": total_cnt,
            "strong_buy": strong_buy_cnt,
            "buy": buy_cnt,
            "watch": watch_cnt,
            "danger": danger_cnt,
            "star_buy": star_buy_cnt,
            "star_sell": star_sell_cnt,
        }

        # 排序
        reverse = (sort_direction.lower() == "desc")
        if filtered and sort_field in filtered[0]:
            filtered.sort(key=lambda x: (x.get(sort_field) is not None, x.get(sort_field) or 0), reverse=reverse)
        else:
            filtered.sort(key=lambda x: x.get("buy_score", 0), reverse=True)

        return {
            "success": True,
            "total_count": total_cnt,
            "stat": stat,
            "rows": filtered,
            "industries": industries,
            "watchlist": list(watchlist_set),
            "period": period,
            "start_date": start_date,
            "end_date": end_date,
        }
    except Exception as e:
        logger.exception("Failed to get signal dashboard")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/screener")
def get_resonance_screener(
    min_rules: int = Query(3, description="最少满足指标数 (3, 4, 5)"),
    f_trend: bool = Query(False, description="强制要求均线多头 (r1)"),
    f_vol_price: bool = Query(False, description="强制要求量价回踩 (r2)"),
    f_zombie: bool = Query(False, description="强制要求拒绝僵尸 (r3)"),
    f_macd: bool = Query(False, description="强制要求MACD吸筹 (r4)"),
    f_boll: bool = Query(False, description="强制要求布林护盘 (r5)"),
    industry: str = Query("", description="行业分类"),
    search_stock: str = Query("", description="搜索代码或名称"),
    my_optional: bool = Query(False, description="仅看我的自选"),
    universe: str = Query("core", description="股票池: core, hs300, zz500, all"),
    period: str = Query("day", description="K线周期: 30m, 60m, 120m, day, week, month"),
    sort_col: str = Query("matched_count", description="排序字段"),
    sort_dir: str = Query("desc", description="排序方向: asc, desc"),
    force_refresh: bool = Query(False, description="强制刷新缓存"),
) -> Dict[str, Any]:
    """
    5 大实战选股指标共振池：
    1.均线多头, 2.量价回踩, 3.拒绝僵尸, 4.MACD低位吸筹, 5.布林护盘
    """
    try:
        search_kw = search_stock.strip().upper()
        matched_search_codes: set[str] = set()
        if search_kw:
            from easy_tdx.stock_lookup import search_stocks
            s_matches = search_stocks(search_kw, limit=10)
            matched_search_codes = {str(item["code"]) for item in s_matches}

        if search_kw.isdigit() and len(search_kw) == 6:
            single_res = evaluate_universe([search_kw], max_workers=1, period=period)
            all_stocks = single_res
        elif len(matched_search_codes) == 1 and not my_optional:
            # 拼音或名称唯一定位单个标的 (如 rssh -> 002493)
            resolved_code = list(matched_search_codes)[0]
            single_res = evaluate_universe([resolved_code], max_workers=1, period=period)
            all_stocks = single_res
        else:
            symbols = None
            if my_optional:
                symbols = load_watchlist()
                if not symbols:
                    return {
                        "success": True,
                        "total_count": 0,
                        "stat": {"total": 0, "r5_cnt": 0, "r4_cnt": 0, "r3_cnt": 0},
                        "rows": [],
                        "industries": [],
                        "watchlist": [],
                        "period": period,
                    }
            # 对于大股票池（如 all 全市场 5000+ 或 zz1000）：
            # 1. 若强制刷新：如果未在计算则启动后台线程，立即返回 running 状态，避免反向代理超时
            # 2. 若未强制刷新：只要已有缓存，则直接读取缓存返回数据；若完全无缓存且未在计算，才启动后台线程
            if universe in ("all", "zz1000") and not my_optional:
                if force_refresh:
                    if not is_universe_evaluating(universe, period=period):
                        start_background_universe_eval(universe, period=period, force_refresh=True)
                    return {
                        "success": True,
                        "status": "running",
                        "message": f"{universe} 股票池量化模型正在后台极速重算...",
                        "progress": get_universe_eval_progress(universe, period=period),
                        "period": period,
                    }
                elif not has_universe_cache(universe, period=period):
                    if not is_universe_evaluating(universe, period=period):
                        start_background_universe_eval(universe, period=period, force_refresh=False)
                    return {
                        "success": True,
                        "status": "running",
                        "message": f"{universe} 股票池量化模型初次载入中，正在后台极速计算...",
                        "progress": get_universe_eval_progress(universe, period=period),
                        "period": period,
                    }

            all_stocks = evaluate_universe(symbols=symbols, universe_type=universe, period=period, force_refresh=force_refresh)

        watchlist_set = set(load_watchlist())

        industries_set = {s["industry"] for s in all_stocks if s.get("industry") and s["industry"] != "--"}
        industries = sorted(list(industries_set))

        filtered: List[Dict[str, Any]] = []
        for s in all_stocks:
            # 搜索过滤（支持 6位代码、拼音首字母、中文名称）
            if search_kw:
                code_match = search_kw in s["stock_code"] or s["stock_code"] in matched_search_codes
                name_match = search_kw in s["stock_name"]
                pinyin_match = False
                py = s.get("pinyin")
                if not py:
                    from easy_tdx.stock_lookup import get_stock_pinyin
                    py = get_stock_pinyin(s["stock_code"])
                    s["pinyin"] = py
                if py and search_kw in py:
                    pinyin_match = True
                if not (code_match or name_match or pinyin_match):
                    continue

            # 自选过滤
            if my_optional and s["stock_code"] not in watchlist_set:
                continue

            # 行业过滤
            if industry and industry != "全部" and s.get("industry") != industry:
                continue

            # 5 项规则强制过滤
            if f_trend and s.get("r1") != 1:
                continue
            if f_vol_price and s.get("r2") != 1:
                continue
            if f_zombie and s.get("r3") != 1:
                continue
            if f_macd and s.get("r4") != 1:
                continue
            if f_boll and s.get("r5") != 1:
                continue

            # 满足最低指标数
            matched = s.get("matched_count", 0)
            if matched < min_rules:
                continue

            s["is_optional"] = s["stock_code"] in watchlist_set
            filtered.append(s)

        # 统计指标
        r5_cnt = sum(1 for s in filtered if s.get("matched_count", 0) == 5)
        r4_cnt = sum(1 for s in filtered if s.get("matched_count", 0) == 4)
        r3_cnt = sum(1 for s in filtered if s.get("matched_count", 0) == 3)
        stat = {
            "total": len(filtered),
            "r5_cnt": r5_cnt,
            "r4_cnt": r4_cnt,
            "r3_cnt": r3_cnt,
        }

        reverse = (sort_dir.lower() == "desc")
        if sort_col in filtered[0] if filtered else {}:
            filtered.sort(key=lambda x: (x.get(sort_col) is not None, x.get(sort_col) or 0), reverse=reverse)
        else:
            filtered.sort(key=lambda x: (x.get("matched_count", 0), x.get("buy_score", 0)), reverse=True)

        return {
            "success": True,
            "total_count": len(filtered),
            "stat": stat,
            "rows": filtered,
            "industries": industries,
            "watchlist": list(watchlist_set),
            "period": period,
        }
    except Exception as e:
        logger.exception("Failed to get resonance screener")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/fina_analysis/{code}")
def get_fina_analysis(code: str) -> Dict[str, Any]:
    """
    获取个股近 8 期完整财报指标趋势与智能深度诊断。
    """
    clean_code = code.strip().upper().replace("SH", "").replace("SZ", "").replace("BJ", "")
    try:
        data = fetch_stock_financials(clean_code)
        return data
    except Exception as e:
        logger.exception(f"Failed to fetch fina analysis for {clean_code}")
        return {"success": False, "error": str(e), "stock_code": clean_code}


@router.get("/history/{code}")
def get_stock_history_signals(code: str, days: int = Query(45, description="回溯天数")) -> Dict[str, Any]:
    """
    单只股票多日打分与买卖信号时序变迁。
    """
    clean_code = code.strip().upper().replace("SH", "").replace("SZ", "").replace("BJ", "")
    try:
        history = evaluate_stock_history(clean_code, days_count=days)
        return {
            "success": True,
            "stock_code": clean_code,
            "history": history,
        }
    except Exception as e:
        logger.exception(f"Failed to fetch history for {clean_code}")
        return {"success": False, "error": str(e), "stock_code": clean_code}


@router.get("/holders_batch")
def batch_fetch_holders(symbols: str = Query(..., description="逗号分隔的个股代码列表，最多30个")) -> Dict[str, Any]:
    """批量异步补全个股股东人数与集中度数据（如前台当前页标的缺失股东集中度时调用）。"""
    sym_list = [s.strip().upper().replace("SH", "").replace("SZ", "").replace("BJ", "") for s in symbols.split(",") if s.strip()][:30]
    results = {}
    for code in sym_list:
        try:
            h = fetch_stock_holders(code, quick=False)
            results[code] = {
                "holder_ratio": h.get("holder_ratio", 0.0),
                "holder_focus": h.get("holder_focus", "--"),
                "holders_changes": h.get("holders_changes", []),
                "holders_num": h.get("holders_num", 0),
                "holders_str": h.get("holders_str", "--"),
            }
        except Exception as e:
            logger.debug(f"Failed to batch fetch holders for {code}: {e}")
    return {"success": True, "data": results}


@router.get("/ai_llm_analysis/{code}")
def get_ai_llm_analysis(
    code: str,
    provider: str = Query("deepseek", description="AI 提供商: deepseek 或 doubao"),
    force_refresh: bool = Query(False, description="是否强制重新生成"),
) -> Dict[str, Any]:
    """调用 DeepSeek 或 豆包 API 进行针对个股的投研诊断分析与前瞻预测。"""
    clean_code = code.strip().upper().replace("SH", "").replace("SZ", "").replace("BJ", "")
    return generate_llm_fina_analysis(clean_code, provider=provider, force_refresh=force_refresh)
