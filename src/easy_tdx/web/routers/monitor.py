"""Market Pulse & Tickflow Monitoring API Endpoints for easy_tdx."""
from __future__ import annotations
from fastapi import APIRouter
from easy_tdx.market_pulse.emotion_meter import emotion_meter
from easy_tdx.market_pulse.abnormal_radar import abnormal_radar

router = APIRouter(prefix="/api/monitor", tags=["monitor"])

@router.get("/sentiment")
def get_sentiment():
    """Get market sentiment thermometer score (0-100) and breadth statistics."""
    return {
        "status": "success",
        "data": emotion_meter.get_market_sentiment()
    }

@router.get("/ladder")
def get_limit_up_ladder():
    """Get short-term dragon limit-up ladder tiers."""
    return {
        "status": "success",
        "data": emotion_meter.get_limit_up_ladder()
    }

@router.get("/abnormal")
def get_auction_anomalies():
    """Get call auction weak-to-strong anomalies."""
    return {
        "status": "success",
        "data": abnormal_radar.get_auction_anomalies()
    }

@router.get("/intraday")
def get_intraday_anomalies():
    """Get intraday fast surges and big order transactions."""
    return {
        "status": "success",
        "data": abnormal_radar.get_intraday_anomalies()
    }

@router.get("/deviation")
def get_deviation_limits():
    """Get exchange deviation limits compliance warnings (3-day 20%/30%)."""
    return {
        "status": "success",
        "data": abnormal_radar.get_deviation_limits()
    }
