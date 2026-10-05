"""缠论分析路由。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from easy_tdx.web.convert import category_from_str, market_from_str, adjust_from_str, period_times_from_category
from easy_tdx.web.deps import get_client, get_mac_client_optional
from easy_tdx.web.schemas import ChanlunRequest

router = APIRouter(tags=["chanlun"])


@router.post("/chanlun/analyze")
async def chanlun_analyze(
    req: ChanlunRequest,
    client: Any = Depends(get_client),
    mac_client: Any = Depends(get_mac_client_optional),
) -> dict[str, Any]:
    """执行缠论分析。

    自动从 TDX 服务器获取 K 线数据（默认前复权），运行完整缠论计算管道，
    返回笔、中枢、线段、买卖点、背驰等分析结果。
    """
    from easy_tdx.chanlun import ChanlunAnalyser

    # 1. Fetch kline data (prefer MacClient for QFQ support)
    cat = category_from_str(req.category)
    if mac_client is not None:
        period, times = period_times_from_category(cat)
        mkt_val = 1 if req.market == "SH" else (2 if req.market == "BJ" else 0)
        df = await mac_client.get_stock_kline(
            mkt_val,
            req.code,
            period,
            req.start,
            req.count,
            times,
            adjust=adjust_from_str(req.adjust),
        )
    else:
        df = await client.get_security_bars(
            market_from_str(req.market),
            req.code,
            cat,
            req.start,
            req.count,
        )

    # 2. Run chanlun analysis
    symbol = f"{req.market}{req.code}"
    frequency_map: dict[str, str] = {
        "MIN_1": "1min",
        "MIN_5": "5min",
        "MIN_15": "15min",
        "MIN_30": "30min",
        "MIN_60": "60min",
        "DAY": "daily",
        "WEEK": "weekly",
        "MONTH": "monthly",
        "YEAR": "yearly",
    }
    freq = frequency_map.get(req.category.upper(), req.category)
    analyser = ChanlunAnalyser(code=symbol, frequency=freq)
    result = analyser.process_klines(df)

    return result.to_dict()
