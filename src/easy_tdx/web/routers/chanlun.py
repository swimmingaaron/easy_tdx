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
            adjust=adjust_from_str(req.adjust),
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


@router.get("/chanlun/resonance")
async def chanlun_resonance_get(
    code: str = "000001",
    periods: str = "DAY,30F,5F",
    count: int = 300,
    cutoff_date: str | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """执行缠论多周期立体共振买卖点分析（GET 接口）。

    支持实时刷新、任意三个周期自定义、以及历史回溯（cutoff_date）。
    """
    import asyncio
    from easy_tdx.chanlun.resonance import analyze_multi_period_resonance

    return await asyncio.to_thread(
        analyze_multi_period_resonance,
        code=code,
        periods=periods,
        count=count,
        cutoff_date=cutoff_date,
        force_refresh=force_refresh,
    )


from pydantic import BaseModel, Field


class ChanlunResonanceRequest(BaseModel):
    code: str = Field(default="000001", description="股票代码")
    periods: list[str] | str = Field(default="DAY,30F,5F", description="3个周期组合")
    count: int = Field(default=300, ge=50, le=10000, description="基准K线数量")
    cutoff_date: str | None = Field(default=None, description="回溯截止时间")
    force_refresh: bool = Field(default=False, description="是否强制刷新最新数据")


@router.post("/chanlun/resonance")
async def chanlun_resonance_post(
    req: ChanlunResonanceRequest,
) -> dict[str, Any]:
    """执行缠论多周期立体共振买卖点分析（POST 接口）。"""
    import asyncio
    from easy_tdx.chanlun.resonance import analyze_multi_period_resonance

    return await asyncio.to_thread(
        analyze_multi_period_resonance,
        code=req.code,
        periods=req.periods,
        count=req.count,
        cutoff_date=req.cutoff_date,
        force_refresh=req.force_refresh,
    )


DEFAULT_HOT_STOCKS: list[dict[str, Any]] = [
    {"code": "000001", "name": "平安银行", "price": 12.5, "chg": "+0.00%", "tag": "金融核心"},
    {"code": "600519", "name": "贵州茅台", "price": 1700.0, "chg": "+0.00%", "tag": "白酒中军"},
    {"code": "300750", "name": "宁德时代", "price": 250.0, "chg": "+0.00%", "tag": "创业板中军"},
    {"code": "002594", "name": "比亚迪", "price": 280.0, "chg": "+0.00%", "tag": "新能源领军"},
    {"code": "300308", "name": "中际旭创", "price": 150.0, "chg": "+0.00%", "tag": "光模块龙头"},
    {"code": "601127", "name": "赛力斯", "price": 90.0, "chg": "+0.00%", "tag": "智驾总龙"},
]


def get_chanlun_hot_stocks(limit: int = 8) -> list[dict[str, Any]]:
    """获取当前市场最新热门股票（优先连板高度龙、板块先锋龙，兜底使用核心标的）。"""
    hot_stocks: list[dict[str, Any]] = []
    seen: set[str] = set()

    # 1. 优先获取全市场连板天梯与空间高度龙 / 突破先锋
    try:
        from easy_tdx.market_ladder import get_market_ladder_and_matrix

        result = get_market_ladder_and_matrix()
        for tier in result.get("ladder", []):
            for s in tier.get("stocks", []):
                code = str(s.get("code", "")).strip()
                name = str(s.get("name", "")).strip()
                if code and name and code not in seen:
                    seen.add(code)
                    hot_stocks.append({
                        "code": code,
                        "name": name,
                        "price": s.get("price", 0.0),
                        "chg": str(s.get("chg", "")),
                        "tag": s.get("role_tag") or f"{s.get('lbc', 1)}连板",
                    })
                if len(hot_stocks) >= limit:
                    break
            if len(hot_stocks) >= limit:
                break
    except Exception:
        pass

    # 2. 若连板天梯标的不足，补充行业板块龙头先锋
    if len(hot_stocks) < limit:
        try:
            from easy_tdx.sector_leaders import get_sector_leaders

            res = get_sector_leaders(top_boards=4, top_stocks=2)
            for b in res.get("boards", []):
                p = b.get("leader_pioneer")
                if p and p.get("code") and p.get("name"):
                    c = str(p["code"]).strip()
                    if c not in seen:
                        seen.add(c)
                        chg_pct = float(p.get("change_pct", 0.0))
                        hot_stocks.append({
                            "code": c,
                            "name": str(p["name"]).strip(),
                            "price": p.get("price", 0.0),
                            "chg": f"+{chg_pct:.2f}%" if chg_pct > 0 else f"{chg_pct:.2f}%",
                            "tag": f"{b.get('board_name', '板块')}先锋",
                        })
                if len(hot_stocks) >= limit:
                    break
        except Exception:
            pass

    # 3. 兜底补足常用知名标的
    if not hot_stocks:
        hot_stocks = [dict(d) for d in DEFAULT_HOT_STOCKS[:limit]]
    elif len(hot_stocks) < 5:
        for d in DEFAULT_HOT_STOCKS:
            if d["code"] not in seen:
                seen.add(d["code"])
                hot_stocks.append(dict(d))
            if len(hot_stocks) >= limit:
                break

    return hot_stocks[:limit]


@router.get("/chanlun/hot_stocks")
async def chanlun_hot_stocks_get(limit: int = 8) -> dict[str, Any]:
    """获取实时全市场热门标的（连板龙头、板块先锋与市场主线）。"""
    import asyncio

    stocks = await asyncio.to_thread(get_chanlun_hot_stocks, limit=limit)
    return {
        "status": "success",
        "count": len(stocks),
        "data": stocks,
    }

