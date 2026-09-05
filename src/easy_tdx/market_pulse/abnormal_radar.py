"""Abnormal Market Activity, Auction Anomalies, and Deviation Compliance Monitor.

Delegates 100% to easy_tdx native anomaly engine.
"""
from __future__ import annotations
from typing import Any
from easy_tdx.market_anomalies import fetch_realtime_anomalies

class AbnormalRadar:
    """Monitors live unusual volume, rapid price surges, and exchange deviation limits via easy_tdx."""

    def get_auction_anomalies(self) -> list[dict[str, Any]]:
        anomalies = fetch_realtime_anomalies()
        return anomalies.get("auction", [])

    def get_intraday_anomalies(self) -> list[dict[str, Any]]:
        anomalies = fetch_realtime_anomalies()
        return anomalies.get("intraday", [])

    def get_deviation_limits(self) -> list[dict[str, Any]]:
        anomalies = fetch_realtime_anomalies()
        return anomalies.get("deviation", [])

abnormal_radar = AbnormalRadar()
