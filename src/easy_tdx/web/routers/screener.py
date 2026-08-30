"""Strategy Screener API Endpoints for easy_tdx."""
from __future__ import annotations
from typing import Any
from fastapi import APIRouter, Query
from pydantic import BaseModel
from easy_tdx.screener.scanner import scan_market_strategy
from easy_tdx.strategies.registry import list_all_strategies

router = APIRouter(prefix="/api/screener", tags=["screener"])

class ScreenerScanRequest(BaseModel):
    strategy: str
    symbols: list[str] | None = None

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
    strategy: str = Query("bull_trend", description="Strategy identifier name"),
):
    """Scan market against selected strategy (GET request)."""
    matches = scan_market_strategy(strategy)
    return {
        "status": "success",
        "strategy": strategy,
        "count": len(matches),
        "matches": matches,
        "data": matches
    }

@router.post("/scan")
def api_scan_post(req: ScreenerScanRequest):
    """Scan market against selected strategy (POST request)."""
    matches = scan_market_strategy(req.strategy, req.symbols)
    return {
        "status": "success",
        "strategy": req.strategy,
        "count": len(matches),
        "matches": matches,
        "data": matches
    }
