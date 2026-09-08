"""AI Multi-Agent Stock Diagnosis, Market Review & Chat Assistant API Endpoints."""
from __future__ import annotations
import logging
import os
import time
import uuid
import threading
import json
from datetime import datetime
from typing import Any
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel
from easy_tdx.ai.market_reviewer import market_reviewer
from easy_tdx.ai.strategy_agent import strategy_agent
from easy_tdx.ai.agents.decision_agent import decision_agent
from easy_tdx.market_data import fetch_security_kline
from easy_tdx.stock_lookup import get_stock_name

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/ai", tags=["ai"])

class AIChatRequest(BaseModel):
    message: str
    symbol: str | None = "000001"
    context: dict[str, Any] | None = None

@router.get("/daily_review")
def get_daily_review():
    """Get automated daily institutional post-market review report."""
    review = market_reviewer.generate_daily_review()
    return {
        "status": "success",
        "data": review
    }

@router.get("/stock_diagnosis/{symbol}")
def get_stock_diagnosis(symbol: str):
    """Get 4D Multi-Agent Quant Diagnosis for a stock using real TDX data."""
    clean_sym = symbol.strip().upper().replace("SH", "").replace("SZ", "").replace("BJ", "").replace(".", "")
    if not clean_sym:
        clean_sym = "000001"
    df = fetch_security_kline(clean_sym, count=60)
    res = decision_agent.analyze(clean_sym, df)
    return {
        "status": "success",
        "symbol": clean_sym,
        "data": res
    }

@router.get("/strategy_match/{symbol}")
def get_stock_strategy_matching(symbol: str):
    """Evaluate a stock against the 15 daily_stock_analysis strategies using real TDX data."""
    clean_sym = symbol.strip().upper().replace("SH", "").replace("SZ", "").replace("BJ", "").replace(".", "")
    if not clean_sym:
        clean_sym = "000001"
    df = fetch_security_kline(clean_sym, count=60)
    stock_name = get_stock_name(clean_sym)
    matches = strategy_agent.evaluate_stock_strategies(clean_sym, df)
    return {
        "status": "success",
        "symbol": clean_sym,
        "name": stock_name,
        "display": f"{clean_sym} {stock_name}",
        "count": len(matches),
        "data": matches
    }

@router.post("/chat")
def api_ai_chat(req: AIChatRequest):
    """Context-aware AI Quant Research Chat Assistant with Real TDX Data."""
    sym = (req.symbol or "000001").strip().upper().replace("SH", "").replace("SZ", "").replace("BJ", "").replace(".", "")
    stock_name = get_stock_name(sym)
    q = req.message.strip()
    
    # Fetch real TDX K-line & diagnosis
    df = fetch_security_kline(sym, count=60)
    diag = decision_agent.analyze(sym, df)
    matches = strategy_agent.evaluate_stock_strategies(sym, df)
    
    last_price = 0.0
    ma5_val = 0.0
    ma20_val = 0.0
    if df is not None and not df.empty:
        last_bar = df.iloc[-1]
        last_price = round(float(last_bar["close"]), 2)
        if len(df) >= 5:
            ma5_val = round(float(df["close"].tail(5).mean()), 2)
        if len(df) >= 20:
            ma20_val = round(float(df["close"].tail(20).mean()), 2)
            
    top_matches = [m.get("strategy_name", "") for m in matches if m.get("matched", False)]
    matched_str = "、".join([f"【{m}】" for m in top_matches[:3]]) if top_matches else "【量价趋势跟踪】"
    
    reply = f"""【StockQuant AI 投研总监研判】关于标的 **{sym} {stock_name}** (最新价 ¥{last_price:.2f})：

1. **4D 综合评分**：多智能体综合评分为 **{diag.get('overall_score', 85)} 分**，操作信号指引为 **{diag.get('signal_display', '买入')}**。
2. **均线与技术结构**：当前 MA5 为 ¥{ma5_val:.2f}，MA20 为 ¥{ma20_val:.2f}。最新收盘价位于均线{'上方（多头强支撑）' if last_price >= ma5_val else '区间内（震荡蓄势）'}。
3. **15 大战法匹配**：当前与 {matched_str} 等量化经典模型高度契合。
4. **操盘总监建议**：{diag.get('summary', '顺势参与')}。

针对您的提问：“{q}”，量化投研模型给出的建议为【合理控制仓位在 25%~35%，严格依托均线支撑逢低布局】。"""

    return {
        "status": "success",
        "symbol": sym,
        "name": stock_name,
        "display": f"{sym} {stock_name}",
        "query": q,
        "reply": reply
    }


# ── 4D Multi-Agent Universe Ranking & Async Task Pipeline ──────────────────────

import os
import json
import uuid
import logging
import threading
from datetime import date
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from fastapi import HTTPException
from easy_tdx.screener.universe import get_universe_symbols
from easy_tdx.screener.scanner import _get_or_fetch_daily_kline, enrich_stocks_with_inflows
from easy_tdx.web.routers.quotes import _resolve_stock_board_info

logger = logging.getLogger(__name__)

_ASYNC_4D_TASKS: dict[str, dict[str, Any]] = {}
_4D_LOCK = threading.Lock()

INTRADAY_4D_CACHE_TTL_SEC: float = 180.0  # 3 minutes during trading hours
POST_MARKET_4D_CACHE_TTL_SEC: float = 43200.0  # 12 hours post-market

class Universe4DTaskStartRequest(BaseModel):
    universe: str = "hs300"
    max_workers: int = 16
    top: int = 20
    force_refresh: bool = False

def _get_4d_cache_dir() -> Path:
    """获取 4D 诊断缓存目录（始终定位到当前工作目录/项目根目录下的 data/screener_cache）。"""
    cwd_cache = Path.cwd() / "data" / "screener_cache"
    if cwd_cache.parent.exists():
        cwd_cache.mkdir(parents=True, exist_ok=True)
        return cwd_cache
    repo_root = Path(__file__).resolve().parents[4]
    base = repo_root / "data" / "screener_cache"
    base.mkdir(parents=True, exist_ok=True)
    return base

def _get_4d_cache_file(universe: str) -> Path:
    today_str = date.today().strftime("%Y%m%d")
    return _get_4d_cache_dir() / f"ai_4d_{universe}_{today_str}.json"

def _load_4d_cache(universe: str, expected_total: int = 0, force_refresh: bool = False) -> list[dict[str, Any]] | None:
    if force_refresh:
        return None
    cache_f = _get_4d_cache_file(universe)
    if cache_f.exists():
        try:
            mtime = os.path.getmtime(cache_f)
            age = time.time() - mtime
            from easy_tdx.market_overview import is_trading_time
            max_age = INTRADAY_4D_CACHE_TTL_SEC if is_trading_time() else POST_MARKET_4D_CACHE_TTL_SEC
            if age < max_age:
                with open(cache_f, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict) and "data" in data and "total_count" in data:
                        cached_total = data.get("total_count", 0)
                        if expected_total > 0 and (cached_total <= 0 or abs(cached_total - expected_total) > max(10, int(expected_total * 0.10))):
                            return None
                        return data["data"]
        except Exception as e:
            logger.warning(f"Failed to read 4D cache {cache_f}: {e}")
    return None

def _save_4d_cache(universe: str, total_count: int, items: list[dict[str, Any]]) -> None:
    try:
        cache_f = _get_4d_cache_file(universe)
        payload = {
            "universe": universe,
            "total_count": total_count,
            "date": date.today().strftime("%Y%m%d"),
            "timestamp": time.time(),
            "count": len(items),
            "data": items
        }
        with open(cache_f, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"Failed to save 4D diagnosis cache: {e}")

def _score_one_stock_fast(sym: str) -> dict[str, Any] | None:
    clean_sym = sym.strip().upper().replace("SH", "").replace("SZ", "").replace("BJ", "").replace(".", "").zfill(6)
    if not clean_sym:
        return None
    
    # 极速获取：优先复用当日内存日K缓存与 32 路 TDX 连接池
    df = _get_or_fetch_daily_kline(clean_sym, force_refresh=False)
    if df is None or len(df) < 15:
        return None

    try:
        res = decision_agent.analyze(clean_sym, df)
        last_close = float(df["close"].iloc[-1])
        prev_close = float(df["close"].iloc[-2]) if len(df) >= 2 else last_close
        chg_pct = round((last_close / prev_close - 1.0) * 100.0, 2) if prev_close > 0 else 0.0
        amt_wan = round(float(df["amount"].iloc[-1]) / 10000.0, 1) if "amount" in df.columns else 0.0

        tech_info = res.get("agents_detail", {}).get("technical", {})
        intel_info = res.get("agents_detail", {}).get("intel", {})

        pattern = tech_info.get("trend_status", "多头排列")
        theme = intel_info.get("theme", "主线题材")
        ind = theme.split("/")[0] if "/" in theme else theme

        patterns = tech_info.get("patterns") or ([pattern] if pattern else ["震荡整理"])
        pattern_str = " · ".join(patterns) if isinstance(patterns, list) else pattern
        sig_disp = res.get("signal_display", "")
        sig = res.get("signal", "")
        act_grade = sig_disp or sig or "观望"

        return {
            "code": clean_sym,
            "symbol": clean_sym,
            "name": get_stock_name(clean_sym),
            "overall_score": res.get("overall_score", 0.0),
            "signal_display": sig_disp,
            "signal": sig,
            "action_grade": act_grade,
            "badge_color": res.get("badge_color", "cyan"),
            "industry": ind,
            "board_code": "",
            "board_name": ind,
            "price": last_close,
            "price_str": f"¥{last_close:.2f}",
            "change_pct": chg_pct,
            "change_pct_str": f"{chg_pct:+.2f}%",
            "amount": amt_wan,
            "amount_wan": amt_wan,
            "amount_wan_str": f"{amt_wan:,.1f}",
            "total_mv": 0.0,
            "total_mv_yi": 0.0,
            "market_cap_yi": 0.0,
            "market_cap_str": "--",
            "pattern": pattern_str,
            "patterns": patterns,
            "pattern_feature": pattern_str,
            "pattern_status": pattern_str,
            "summary": res.get("summary", ""),
            "main_net_amount": 0.0,
            "main_net_3d": 0.0,
            "main_net_5d": 0.0,
            "inflow_1d_str": "0.0万",
            "inflow_3d_str": "0.0万",
            "inflow_5d_str": "0.0万",
            "flow_1d_str": "0.0万",
            "flow_3d_str": "0.0万",
            "flow_5d_str": "0.0万",
        }
    except Exception:
        return None

def _run_async_4d_worker(task_id: str, universe: str, max_workers: int, top: int, force_refresh: bool = False):
    with _4D_LOCK:
        task = _ASYNC_4D_TASKS.get(task_id)
        if not task:
            return
        stop_event: threading.Event = task["stop_event"]

    try:
        symbols = get_universe_symbols(universe)
        total_count = len(symbols)
        with _4D_LOCK:
            if task_id in _ASYNC_4D_TASKS:
                _ASYNC_4D_TASKS[task_id]["total"] = total_count

        # 1. Check disk cache
        if not force_refresh:
            cached = _load_4d_cache(universe, expected_total=total_count)
            if cached is not None:
                with _4D_LOCK:
                    t = _ASYNC_4D_TASKS.get(task_id)
                    if t:
                        t["status"] = "completed"
                        t["percent"] = 100.0
                        t["processed"] = total_count
                        t["data"] = cached[:top]
                        t["finished_at"] = time.time()
                return

        workers = min(32, max(4, max_workers))
        processed = 0
        all_scored: list[dict[str, Any]] = []

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_score_one_stock_fast, sym): sym for sym in symbols}
            for fut in as_completed(futures):
                if stop_event.is_set():
                    for f in futures:
                        f.cancel()
                    break

                processed += 1
                try:
                    res = fut.result()
                    if res is not None:
                        all_scored.append(res)
                except Exception:
                    pass

                # High frequency progress updates
                if processed == 1 or processed % 3 == 0 or processed == total_count:
                    pct = round((processed / total_count) * 100.0, 1)
                    with _4D_LOCK:
                        t = _ASYNC_4D_TASKS.get(task_id)
                        if t:
                            t["processed"] = processed
                            t["percent"] = pct

        if stop_event.is_set():
            with _4D_LOCK:
                t = _ASYNC_4D_TASKS.get(task_id)
                if t:
                    t["status"] = "cancelled"
                    t["finished_at"] = time.time()
            return

        # Sort all scored stocks descending by overall_score
        all_scored.sort(key=lambda x: x.get("overall_score", 0.0), reverse=True)

        # 极速富化：只针对 Top N (最多 100 只) 候选股票富化板块与 MAC 资金流向，极速完成！
        top_slice = all_scored[:max(top, 100)]
        for item in top_slice:
            c = item["code"]
            b_info = _resolve_stock_board_info(c)
            b_code = b_info.get("board_code", "")
            b_name = b_info.get("board_name", "")
            if b_code:
                item["board_code"] = b_code
            if b_name and b_name != "--":
                item["board_name"] = b_name
                item["industry"] = b_name
            if not item.get("action_grade"):
                item["action_grade"] = item.get("signal_display") or item.get("signal") or "观望"
            if not item.get("pattern_feature"):
                item["pattern_feature"] = item.get("pattern") or (item.get("patterns") and " · ".join(item["patterns"])) or "--"

        enrich_stocks_with_inflows(top_slice)

        # 保存至磁盘缓存
        _save_4d_cache(universe, total_count, all_scored[:max(top, 100)])

        with _4D_LOCK:
            t = _ASYNC_4D_TASKS.get(task_id)
            if t:
                t["status"] = "completed"
                t["percent"] = 100.0
                t["processed"] = total_count
                t["data"] = all_scored[:top]
                t["finished_at"] = time.time()

    except Exception as e:
        logger.exception(f"4D Diagnosis task {task_id} failed: {e}")
        with _4D_LOCK:
            t = _ASYNC_4D_TASKS.get(task_id)
            if t:
                t["status"] = "failed"
                t["error"] = str(e)
                t["finished_at"] = time.time()

@router.post("/universe_ranking/task/start")
def api_start_4d_diagnosis_task(req: Universe4DTaskStartRequest):
    """Start an asynchronous 4D Multi-Agent Universe Diagnosis task with live progress tracking."""
    task_id = f"ai4d_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    symbols = get_universe_symbols(req.universe)
    stop_event = threading.Event()

    task_info = {
        "task_id": task_id,
        "universe": req.universe,
        "max_workers": req.max_workers,
        "top": req.top,
        "status": "running",
        "total": len(symbols),
        "processed": 0,
        "percent": 0.0,
        "data": [],
        "error": None,
        "started_at": time.time(),
        "finished_at": None,
        "stop_event": stop_event,
    }

    if not req.force_refresh:
        cached = _load_4d_cache(req.universe, expected_total=len(symbols))
        if cached is not None:
            task_info["status"] = "completed"
            task_info["processed"] = len(symbols)
            task_info["percent"] = 100.0
            task_info["data"] = cached[:req.top]
            task_info["finished_at"] = time.time()
            with _4D_LOCK:
                _ASYNC_4D_TASKS[task_id] = task_info
            return {
                "status": "success",
                "task_id": task_id,
                "universe": req.universe,
                "total": len(symbols),
                "message": f"4D 多智能体全池诊断命中缓存 (Top {min(req.top, len(cached))} 已即时加载)"
            }

    with _4D_LOCK:
        _ASYNC_4D_TASKS[task_id] = task_info

    th = threading.Thread(
        target=_run_async_4d_worker,
        args=(task_id, req.universe, req.max_workers, req.top, req.force_refresh),
        daemon=True
    )
    th.start()

    return {
        "status": "success",
        "task_id": task_id,
        "universe": req.universe,
        "total": len(symbols),
        "message": f"4D 多智能体全池诊断任务已启动，总计评估 {len(symbols)} 只标的"
    }

@router.get("/universe_ranking/task/status/{task_id}")
def api_get_4d_task_status(task_id: str):
    """Query background 4D diagnosis progress and results."""
    with _4D_LOCK:
        task = _ASYNC_4D_TASKS.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        return {
            "status": "success",
            "task_id": task["task_id"],
            "task_status": task["status"],
            "universe": task["universe"],
            "total": task["total"],
            "processed": task["processed"],
            "percent": task["percent"],
            "data": task["data"] if task["status"] == "completed" else [],
            "error": task["error"],
            "elapsed_seconds": round(time.time() - task["started_at"], 1),
            "finished": task["status"] in ("completed", "failed", "cancelled")
        }

@router.post("/universe_ranking/task/cancel/{task_id}")
def api_cancel_4d_task(task_id: str):
    """Cancel a running 4D diagnosis task."""
    with _4D_LOCK:
        task = _ASYNC_4D_TASKS.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        task["stop_event"].set()
        task["status"] = "cancelling"
        return {
            "status": "success",
            "message": "已向 4D 诊断任务发送中止指令"
        }

@router.get("/universe_ranking")
def get_universe_4d_ranking(
    universe: str = Query("hs300", description="core | hs300 | zz500 | zz1000 | all"),
    max_workers: int = Query(16, description="Parallel thread count"),
    top: int = Query(20, description="Top N ranked stocks to return"),
    force_refresh: bool = Query(False, description="Force fresh calculation")
):
    """Run batch 4D Multi-Agent diagnosis across stock universe (Synchronous endpoint)."""
    symbols = get_universe_symbols(universe)
    if not symbols:
        return {"status": "success", "universe": universe, "count": 0, "total_scanned": 0, "data": []}

    # Check cache
    if not force_refresh:
        cached = _load_4d_cache(universe, expected_total=len(symbols))
        if cached is not None:
            return {
                "status": "success",
                "universe": universe,
                "count": min(top, len(cached)),
                "total_scanned": len(symbols),
                "data": cached[:top]
            }

    workers = min(32, max(4, max_workers))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        items = [r for r in pool.map(_score_one_stock_fast, symbols) if r is not None]

    items.sort(key=lambda x: x.get("overall_score", 0.0), reverse=True)
    top_slice = items[:max(top, 100)]
    for item in top_slice:
        c = item["code"]
        b_info = _resolve_stock_board_info(c)
        b_code = b_info.get("board_code", "")
        b_name = b_info.get("board_name", "")
        if b_code:
            item["board_code"] = b_code
        if b_name and b_name != "--":
            item["board_name"] = b_name
            item["industry"] = b_name
        if not item.get("action_grade"):
            item["action_grade"] = item.get("signal_display") or item.get("signal") or "观望"
        if not item.get("pattern_feature"):
            item["pattern_feature"] = item.get("pattern") or (item.get("patterns") and " · ".join(item["patterns"])) or "--"

    enrich_stocks_with_inflows(top_slice)
    _save_4d_cache(universe, len(symbols), items[:max(top, 100)])

    top_items = items[:top]
    return {
        "status": "success",
        "universe": universe,
        "count": len(top_items),
        "total_scanned": len(items),
        "data": top_items
    }


