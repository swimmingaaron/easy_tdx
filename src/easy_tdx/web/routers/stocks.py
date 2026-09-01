"""Stock Lookup and Autocomplete API Endpoints for easy_tdx."""
from __future__ import annotations
from fastapi import APIRouter, Query
from easy_tdx.stock_lookup import search_stocks, get_stock_name

router = APIRouter(prefix="/api/stocks", tags=["stocks"])

@router.get("/search")
def api_search_stocks(q: str = Query("", description="Query keyword: 6-digit code, Pinyin initials, or Chinese name")):
    """Search stocks by code, Pinyin initials (e.g. payh), or Chinese name."""
    results = search_stocks(q, limit=15)
    return {
        "status": "success",
        "query": q,
        "count": len(results),
        "data": results
    }

@router.get("/info/{symbol}")
def api_get_stock_info(symbol: str):
    """Get stock name and formatted display info."""
    clean_sym = symbol.strip().upper().replace("SH", "").replace("SZ", "").replace("BJ", "")
    name = get_stock_name(clean_sym)
    return {
        "status": "success",
        "symbol": clean_sym,
        "name": name,
        "display": f"{clean_sym} {name}"
    }
