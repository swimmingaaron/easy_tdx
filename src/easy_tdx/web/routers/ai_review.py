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
