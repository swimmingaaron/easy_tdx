"""AI Multi-Agent Stock Diagnosis, Market Review & Chat Assistant API Endpoints."""
from __future__ import annotations
from typing import Any
from fastapi import APIRouter, Query
from pydantic import BaseModel
from easy_tdx.ai.market_reviewer import market_reviewer
from easy_tdx.ai.strategy_agent import strategy_agent
from easy_tdx.ai.agents.decision_agent import decision_agent
from easy_tdx.market_data import fetch_security_kline
from easy_tdx.stock_lookup import get_stock_name

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


@router.get("/universe_ranking")
def get_universe_4d_ranking(
    universe: str = Query("hs300", description="core | hs300 | zz500 | zz1000 | all"),
    max_workers: int = Query(16, description="Parallel thread count"),
    top: int = Query(20, description="Top N ranked stocks to return")
):
    """Run batch 4D Multi-Agent diagnosis across stock universe with quote & capital inflow enrichment."""
    from concurrent.futures import ThreadPoolExecutor
    from easy_tdx.screener.universe import get_universe_symbols
    from easy_tdx.screener.scanner import enrich_stocks_with_inflows

    symbols = get_universe_symbols(universe)
    if not symbols:
        return {"status": "success", "universe": universe, "count": 0, "total_scanned": 0, "data": []}

    def _score_one(sym: str):
        clean_sym = sym.strip().upper().replace("SH", "").replace("SZ", "").replace("BJ", "").replace(".", "").zfill(6)
        if not clean_sym:
            return None
        df = fetch_security_kline(clean_sym, count=60)
        if df is None or df.empty or len(df) < 15:
            return None
        res = decision_agent.analyze(clean_sym, df)
        
        last_close = float(df["close"].iloc[-1])
        prev_close = float(df["close"].iloc[-2]) if len(df) >= 2 else last_close
        chg_pct = round((last_close / prev_close - 1.0) * 100.0, 2) if prev_close > 0 else 0.0
        amt_wan = round(float(df["amount"].iloc[-1]) / 10000.0, 1) if "amount" in df.columns else 0.0
        
        tech_info = res.get("agents_detail", {}).get("technical", {})
        intel_info = res.get("agents_detail", {}).get("intel", {})
        
        pattern = tech_info.get("trend_status", "多头排列")
        theme = intel_info.get("theme", "主线题材")
        
        # 参考自选监控实时行情池，从 TDX MAC 解析真实的所属行业板块
        from easy_tdx.web.routers.quotes import _resolve_stock_board_info
        b_info = _resolve_stock_board_info(clean_sym)
        b_code = b_info.get("board_code", "")
        b_name = b_info.get("board_name", "")
        ind = b_name if (b_name and b_name != "--") else (theme.split("/")[0] if "/" in theme else theme)
        
        return {
            "code": clean_sym,
            "symbol": clean_sym,
            "name": get_stock_name(clean_sym),
            "overall_score": res.get("overall_score", 0.0),
            "signal_display": res.get("signal_display", ""),
            "signal": res.get("signal", ""),
            "badge_color": res.get("badge_color", "cyan"),
            "industry": ind,
            "board_code": b_code,
            "board_name": ind,
            "price": last_close,
            "price_str": f"¥{last_close:.2f}",
            "change_pct": chg_pct,
            "change_pct_str": f"{chg_pct:+.2f}%",
            "amount_wan": amt_wan,
            "amount_wan_str": f"{amt_wan:,.1f}",
            "pattern": pattern,
            "summary": res.get("summary", "")
        }

    # Parallel score computation
    workers = min(32, max(1, max_workers))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        items = [r for r in pool.map(_score_one, symbols) if r is not None]

    # Enrich with real-time 1d/3d/5d capital inflows & total market cap
    enrich_stocks_with_inflows(items)
    
    # Sort descending by overall score
    items.sort(key=lambda x: x.get("overall_score", 0.0), reverse=True)
    
    # Format and return Top N
    top_items = items[:top]
    return {
        "status": "success",
        "universe": universe,
        "count": len(top_items),
        "total_scanned": len(items),
        "data": top_items
    }

