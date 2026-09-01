"""Strategy Screener API Endpoints for easy_tdx.

Features:
- Plan A: Multi-tier universe selection (core, hs300, zz500, zz1000, all)
- Plan B: Background async task management for full-market screening with real-time progress & cancellation
- Daily disk caching for fast result re-display
"""
from __future__ import annotations
import time
import uuid
import logging
import threading
from typing import Any
from fastapi import APIRouter, Query, BackgroundTasks, HTTPException
from pydantic import BaseModel

from easy_tdx.screener.scanner import scan_market_strategy
from easy_tdx.screener.universe import get_universe_options, get_universe_symbols
from easy_tdx.strategies.registry import list_all_strategies, get_strategy

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/screener", tags=["screener"])

# In-memory background task registry
# Key: task_id -> {status, strategy, universe, total, processed, percent, matched_count, matches, error, started_at, finished_at, stop_event}
_ASYNC_TASKS: dict[str, dict[str, Any]] = {}
_TASKS_LOCK = threading.Lock()

class ScreenerScanRequest(BaseModel):
    strategy: str
    universe: str = "core"
    symbols: list[str] | None = None
    lookback_bars: int = 20

class ScreenerTaskStartRequest(BaseModel):
    strategy: str
    universe: str = "all"
    lookback_bars: int = 20

@router.get("/universes")
def get_universes():
    """Get all available universe tiers with descriptions and counts."""
    options = get_universe_options()
    return {
        "status": "success",
        "universes": options
    }

@router.get("/strategies")
def get_screener_strategies():
    """Get all 48 available strategies for screener."""
    strategies = list_all_strategies()
    return {
        "status": "success",
        "count": len(strategies),
        "strategies": strategies
    }

@router.get("/scan")
def api_scan_get(
    strategy: str = Query("zig_breakout", description="Strategy identifier name"),
    universe: str = Query("core", description="Universe tier: core, hs300, zz500, zz1000, all"),
):
    """Scan market against selected strategy synchronously (GET request)."""
    matches = scan_market_strategy(strategy, universe=universe)
    return {
        "status": "success",
        "strategy": strategy,
        "universe": universe,
        "count": len(matches),
        "matches": matches,
        "data": matches
    }

@router.post("/scan")
def api_scan_post(req: ScreenerScanRequest):
    """Scan market against selected strategy synchronously (POST request)."""
    matches = scan_market_strategy(
        strategy_name=req.strategy, 
        symbols=req.symbols, 
        universe=req.universe,
        lookback_bars=req.lookback_bars
    )
    return {
        "status": "success",
        "strategy": req.strategy,
        "universe": req.universe,
        "count": len(matches),
        "matches": matches,
        "data": matches
    }

def _run_async_screener_worker(task_id: str, strategy: str, universe: str, lookback_bars: int):
    """Background worker for long-running screening tasks (e.g. all 5,200+ A-shares)."""
    with _TASKS_LOCK:
        task = _ASYNC_TASKS.get(task_id)
        if not task:
            return
        stop_event: threading.Event = task["stop_event"]

    def on_progress(processed: int, total: int, matched_cnt: int, percent: float):
        with _TASKS_LOCK:
            t = _ASYNC_TASKS.get(task_id)
            if t:
                t["processed"] = processed
                t["total"] = total
                t["matched_count"] = matched_cnt
                t["percent"] = percent

    try:
        symbols = get_universe_symbols(universe)
        with _TASKS_LOCK:
            if task_id in _ASYNC_TASKS:
                _ASYNC_TASKS[task_id]["total"] = len(symbols)

        matches = scan_market_strategy(
            strategy_name=strategy,
            symbols=None,
            universe=universe,
            lookback_bars=lookback_bars,
            use_cache=True,
            progress_callback=on_progress,
            stop_event=stop_event
        )

        with _TASKS_LOCK:
            t = _ASYNC_TASKS.get(task_id)
            if t:
                t["status"] = "completed" if not stop_event.is_set() else "cancelled"
                t["percent"] = 100.0
                t["processed"] = t["total"]
                t["matched_count"] = len(matches)
                t["matches"] = matches
                t["finished_at"] = time.time()
    except Exception as e:
        logger.exception(f"Async screener task {task_id} failed: {e}")
        with _TASKS_LOCK:
            t = _ASYNC_TASKS.get(task_id)
            if t:
                t["status"] = "failed"
                t["error"] = str(e)
                t["finished_at"] = time.time()

@router.post("/task/start")
def api_start_task(req: ScreenerTaskStartRequest):
    """Start an asynchronous background screener task (Plan B)."""
    task_id = f"scr_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    symbols = get_universe_symbols(req.universe)
    stop_event = threading.Event()

    task_info = {
        "task_id": task_id,
        "strategy": req.strategy,
        "universe": req.universe,
        "status": "running",
        "total": len(symbols),
        "processed": 0,
        "percent": 0.0,
        "matched_count": 0,
        "matches": [],
        "error": None,
        "started_at": time.time(),
        "finished_at": None,
        "stop_event": stop_event,
    }

    with _TASKS_LOCK:
        _ASYNC_TASKS[task_id] = task_info

    # Launch in a daemon thread so it runs independently in the background
    th = threading.Thread(
        target=_run_async_screener_worker,
        args=(task_id, req.strategy, req.universe, req.lookback_bars),
        daemon=True
    )
    th.start()

    return {
        "status": "success",
        "task_id": task_id,
        "strategy": req.strategy,
        "universe": req.universe,
        "total": len(symbols),
        "message": f"异步任务已启动，总计扫描 {len(symbols)} 只标的"
    }

@router.get("/task/status/{task_id}")
def api_get_task_status(task_id: str):
    """Query background task progress and results."""
    with _TASKS_LOCK:
        task = _ASYNC_TASKS.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")

        # Return sanitized dict without non-serializable objects like stop_event
        return {
            "status": "success",
            "task_id": task["task_id"],
            "task_status": task["status"],
            "strategy": task["strategy"],
            "universe": task["universe"],
            "total": task["total"],
            "processed": task["processed"],
            "percent": task["percent"],
            "matched_count": task["matched_count"],
            "matches": task["matches"] if task["status"] == "completed" else [],
            "error": task["error"],
            "elapsed_seconds": round(time.time() - task["started_at"], 1),
            "finished": task["status"] in ("completed", "failed", "cancelled")
        }

@router.post("/task/cancel/{task_id}")
def api_cancel_task(task_id: str):
    """Cancel a running background screening task."""
    with _TASKS_LOCK:
        task = _ASYNC_TASKS.get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        task["stop_event"].set()
        task["status"] = "cancelling"
        return {
            "status": "success",
            "message": "已向后台任务发送中止指令"
        }
