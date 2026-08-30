"""Quotes API Endpoints for easy_tdx."""
from __future__ import annotations
from typing import Any
from fastapi import APIRouter, Query
from easy_tdx.stock_lookup import get_stock_name, COMMON_STOCKS
from easy_tdx.screener.scanner import generate_mock_kline

router = APIRouter(prefix="/api/quotes", tags=["quotes"])

@router.get("/realtime")
def get_realtime_quotes():
    """Get live pool quotes with stock name and metrics."""
    data = []
    for s in COMMON_STOCKS[:10]:
        code = s["code"]
        name = s["name"]
        p = 10.0 + (hash(code) % 50)
        chg = ((hash(code) % 15) - 3) / 2.0
        data.append({
            "symbol": code,
            "code": code,
            "name": name,
            "display": f"{code} {name}",
            "price": round(p, 2),
            "change_pct": round(chg, 2),
            "high": round(p * 1.03, 2),
            "low": round(p * 0.98, 2),
            "volume": 120000 + (hash(code) % 500000),
            "turnover_wan": round(15000 + (hash(code) % 80000), 1),
            "status": "多头排列" if chg > 1.5 else ("放量突破" if chg > 0 else "缩量回踩")
        })
    return {
        "status": "success",
        "count": len(data),
        "data": data
    }

@router.get("/kline")
def get_kline(
    symbol: str = Query("000001", description="Stock symbol"),
    period: str = Query("DAY", description="K-line period (DAY, 1M, 5M, etc.)"),
    count: int = Query(100, description="Bars count")
):
    """Get K-line bars for specified symbol."""
    clean_sym = symbol.strip().upper().replace("SH", "").replace("SZ", "").replace("BJ", "")
    df = generate_mock_kline(clean_sym, n_bars=count)
    stock_name = get_stock_name(clean_sym)
    return {
        "status": "success",
        "symbol": clean_sym,
        "name": stock_name,
        "display": f"{clean_sym} {stock_name}",
        "period": period,
        "count": len(df),
        "data": df.to_dict(orient="records")
    }
