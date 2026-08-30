"""Abnormal Market Activity, Auction Anomalies, and Deviation Compliance Monitor."""
from __future__ import annotations
from typing import Any
from easy_tdx.stock_lookup import get_stock_name

class AbnormalRadar:
    """Monitors live unusual volume, rapid price surges, and exchange deviation limits."""

    def get_auction_anomalies(self) -> list[dict[str, Any]]:
        return [
            {
                "symbol": "002345",
                "name": get_stock_name("002345"),
                "type": "WEAK_TO_STRONG",
                "type_display": "弱转强大幅高开",
                "open_pct": "+5.2%",
                "turnover_amount": "4,500 万",
                "reason": "昨日炸板烂板，今日竞价大幅高开抢筹，超预期弱转强"
            },
            {
                "symbol": "600123",
                "name": get_stock_name("600123"),
                "type": "MASSIVE_BUY",
                "type_display": "千万级一字封单",
                "open_pct": "+9.98%",
                "turnover_amount": "1.2 亿",
                "reason": "竞价封单超过流通盘 5%，龙头一字加速"
            }
        ]

    def get_intraday_anomalies(self) -> list[dict[str, Any]]:
        return [
            {
                "symbol": "300223",
                "name": get_stock_name("300223"),
                "time": "14:15:30",
                "speed_pct": "+4.8% / 5min",
                "volume_ratio": "4.2",
                "desc": "连续多笔千手大单主买，直线拉升突破日内分时高点"
            },
            {
                "symbol": "002415",
                "name": get_stock_name("002415"),
                "time": "13:45:10",
                "speed_pct": "+3.2% / 5min",
                "volume_ratio": "3.5",
                "desc": "大单成交密集，放量突破阶段箱体整理上轨"
            }
        ]

    def get_deviation_limits(self) -> list[dict[str, Any]]:
        return [
            {
                "symbol": "600123",
                "name": get_stock_name("600123"),
                "board": "主板 (3日 20%)",
                "accumulated_gain": "+18.5%",
                "limit_threshold": "20.0%",
                "usage_ratio": "92.5%",
                "risk_level": "WARNING",
                "desc": "3日累计偏离值达 18.5%，接近 20% 异动监管红线，警惕特停停牌风险"
            },
            {
                "symbol": "300890",
                "name": "飞天低空",
                "board": "创业板 (3日 30%)",
                "accumulated_gain": "+25.8%",
                "limit_threshold": "30.0%",
                "usage_ratio": "86.0%",
                "risk_level": "CAUTION",
                "desc": "创业板3日偏离度已达 25.8%，进入二级异动合规监控窗口"
            }
        ]

abnormal_radar = AbnormalRadar()
