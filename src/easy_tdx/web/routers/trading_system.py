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
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel

from easy_tdx.trading_system.engine import (
    evaluate_universe,
    fetch_stock_financials,
    evaluate_stock_history,
)
from easy_tdx.watchlist_store import load_watchlist, save_watchlist
from easy_tdx.screener.universe import get_universe_symbols

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/trading_system", tags=["trading_system"])


class WatchlistToggleReq(BaseModel):
    stock_code: str
    status: bool  # True for add, False for remove


@router.get("/watchlist")
def get_current_watchlist() -> Dict[str, Any]:
    """获取当前所有自选股代码列表。"""
    try:
        wl = load_watchlist()
        return {"success": True, "watchlist": wl}
    except Exception as e:
        logger.error(f"Failed to load watchlist: {e}")
        return {"success": False, "watchlist": [], "error": str(e)}


@router.post("/toggle_watchlist")
def toggle_watchlist_stock(req: WatchlistToggleReq) -> Dict[str, Any]:
    """一键将个股加入或移出自选。"""
    clean_code = req.stock_code.strip().upper().replace("SH", "").replace("SZ", "").replace("BJ", "")
    try:
        current = load_watchlist()
        if req.status:
            if clean_code not in current:
                current.append(clean_code)
        else:
            current = [c for c in current if c != clean_code]
        saved = save_watchlist(current)
        return {"success": True, "stock_code": clean_code, "status": req.status, "watchlist": saved}
    except Exception as e:
        logger.error(f"Failed to toggle watchlist for {clean_code}: {e}")
        return {"success": False, "error": str(e)}


@router.get("/progress")
def get_evaluation_progress(universe: str = Query("core")) -> Dict[str, Any]:
    """获取股票池量化计算实时进度与当前正在处理的股票"""
    from easy_tdx.trading_system.engine import get_universe_eval_progress
    return get_universe_eval_progress(universe)


@router.get("/dashboard")
def get_signal_dashboard(
    min_buy: int = Query(0, description="最低买入分"),
    max_sell: int = Query(10, description="最高卖出分"),
    industry: str = Query("", description="行业分类"),
    search_stock: str = Query("", description="搜索代码或名称"),
    my_optional: bool = Query(False, description="仅看我的自选"),
    universe: str = Query("core", description="股票池: core, hs300, zz500, all"),
    sort_col: str = Query("buy_score", description="排序字段"),
    sort_dir: str = Query("desc", description="排序方向: asc, desc"),
    selected_date: str = Query("", description="选定日期"),
    force_refresh: bool = Query(False, description="强制刷新缓存"),
    symbols: Optional[str] = Query(None, description="逗号分隔的个股代码列表"),
) -> Dict[str, Any]:
    """
    信号看板：包含 18 项买入打分、9 项卖出预警打分、量价红星/绿星、ZIG转向与战法识别。
    """
    try:
        search_kw = search_stock.strip().upper()
        symbols_set = None
        if search_kw.isdigit() and len(search_kw) == 6:
            # 优先回溯历史或精准评估该股
            single_res = evaluate_universe([search_kw], max_workers=1)
            all_stocks = single_res
        elif symbols:
            clean_syms = [s.strip().upper().replace("SH", "").replace("SZ", "").replace("BJ", "") for s in symbols.split(",") if s.strip()]
            symbols_set = set(clean_syms)
            all_stocks = evaluate_universe(symbols=clean_syms, universe_type="custom", force_refresh=force_refresh)
        else:
            wl_symbols = None
            if my_optional:
                wl_symbols = load_watchlist()
                if not wl_symbols:
                    return {
                        "success": True,
                        "total_count": 0,
                        "stat": {"total": 0, "strong_buy": 0, "buy": 0, "watch": 0, "danger": 0, "star_buy": 0, "star_sell": 0},
                        "rows": [],
                        "industries": [],
                        "watchlist": [],
                    }
            all_stocks = evaluate_universe(symbols=wl_symbols, universe_type=universe, force_refresh=force_refresh)

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

            # 搜索过滤
            if search_kw:
                code_match = search_kw in s["stock_code"]
                name_match = search_kw in s["stock_name"]
                if not (code_match or name_match):
                    continue
            
            # 自选过滤
            if my_optional and s["stock_code"] not in watchlist_set:
                continue

            # 行业过滤
            if industry and industry != "全部" and s.get("industry") != industry:
                continue

            # 买入分/卖出分过滤
            if s.get("buy_score", 0) < min_buy:
                continue
            if s.get("sell_score", 0) > max_sell:
                continue

            # 标记自选状态
            s["is_optional"] = s["stock_code"] in watchlist_set
            filtered.append(s)

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
        reverse = (sort_dir.lower() == "desc")
        if sort_col in filtered[0] if filtered else {}:
            filtered.sort(key=lambda x: (x.get(sort_col) is not None, x.get(sort_col) or 0), reverse=reverse)
        else:
            filtered.sort(key=lambda x: x.get("buy_score", 0), reverse=True)

        return {
            "success": True,
            "total_count": total_cnt,
            "stat": stat,
            "rows": filtered,
            "industries": industries,
            "watchlist": list(watchlist_set),
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
        if search_kw.isdigit() and len(search_kw) == 6:
            single_res = evaluate_universe([search_kw], max_workers=1)
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
                    }
            all_stocks = evaluate_universe(symbols=symbols, universe_type=universe, force_refresh=force_refresh)

        watchlist_set = set(load_watchlist())

        industries_set = {s["industry"] for s in all_stocks if s.get("industry") and s["industry"] != "--"}
        industries = sorted(list(industries_set))

        filtered: List[Dict[str, Any]] = []
        for s in all_stocks:
            # 搜索过滤
            if search_kw:
                code_match = search_kw in s["stock_code"]
                name_match = search_kw in s["stock_name"]
                if not (code_match or name_match):
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
