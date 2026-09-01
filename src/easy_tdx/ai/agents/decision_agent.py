"""Decision Agent: Multi-Agent Consensus Synthesizer & 4D Diagnostic Engine."""
from __future__ import annotations
from typing import Any
import pandas as pd
from easy_tdx.ai.agents.base_agent import BaseAgent
from easy_tdx.ai.agents.intel_agent import intel_agent
from easy_tdx.ai.agents.technical_agent import technical_agent
from easy_tdx.ai.agents.risk_agent import risk_agent
from easy_tdx.ai.agents.portfolio_agent import portfolio_agent
from easy_tdx.ai.llm_client import llm_client
from easy_tdx.stock_lookup import get_stock_name

class DecisionAgent(BaseAgent):
    agent_name = "decision_agent"
    role_description = "量化投资决策总监，整合情报、技术、风控与仓位多智能体输出，给出终极交易评级"

    def analyze(self, symbol: str, kline_df: pd.DataFrame, context: dict[str, Any] | None = None) -> dict[str, Any]:
        intel_res = intel_agent.analyze(symbol, kline_df, context)
        tech_res = technical_agent.analyze(symbol, kline_df, context)
        risk_res = risk_agent.analyze(symbol, kline_df, context)
        port_res = portfolio_agent.analyze(symbol, kline_df, context)

        # 4D 评分与综合总分
        t_score = tech_res["score"]
        f_score = intel_res["score"]
        r_score = risk_res["score"]
        
        # 资金面评分 (结合量能比与乖离率)
        vol_r = tech_res.get("volume_ratio", 1.0)
        c_score = min(96.0, max(50.0, 70.0 + (vol_r - 1.0) * 12.0))
        
        # 情绪面评分
        s_score = min(95.0, max(45.0, (t_score + f_score) / 2.0))

        # 综合加权评分 (技术 35%, 基本面/情报 25%, 资金 20%, 风控 20%)
        overall_score = round(t_score * 0.35 + f_score * 0.25 + c_score * 0.20 + r_score * 0.20, 1)

        # 买卖信号分级
        if overall_score >= 86.0 and r_score >= 75.0:
            signal = "STRONG_BUY"
            signal_text = "强烈买入 (优质主升)"
            badge_color = "rose"
        elif overall_score >= 76.0 and r_score >= 65.0:
            signal = "BUY"
            signal_text = "买入 (顺势回踩低吸)"
            badge_color = "emerald"
        elif overall_score >= 65.0:
            signal = "HOLD"
            signal_text = "持有 (沿均线持股观察)"
            badge_color = "cyan"
        elif overall_score >= 50.0:
            signal = "WAIT"
            signal_text = "观望 (等待企稳或突破)"
            badge_color = "amber"
        else:
            signal = "SELL"
            signal_text = "卖出 / 避险 (防范破位下行)"
            badge_color = "slate"

        stock_name = get_stock_name(symbol)

        summary_text = (
            f"标的 {symbol} {stock_name} 综合量化评分 【{overall_score} / 100】，投资决策评级为 【{signal_text}】。"
            f"技术面呈现【{tech_res['trend_status']}】，{tech_res['summary']} "
            f"消息与基本面显示【{intel_res['sentiment_summary']}】 "
            f"风控提示【{risk_res['summary']}】 "
            f"操作指引：{port_res['summary']}"
        )

        return {
            "symbol": symbol,
            "name": stock_name,
            "display": f"{symbol} {stock_name}",
            "overall_score": overall_score,
            "signal": signal,
            "signal_display": signal_text,
            "badge_color": badge_color,
            "ratings_4d": {
                "technical": round(t_score, 1),
                "fundamental": round(f_score, 1),
                "capital_flow": round(c_score, 1),
                "sentiment": round(s_score, 1),
                "risk_safety": round(r_score, 1)
            },
            "agents_detail": {
                "intel": intel_res,
                "technical": tech_res,
                "risk": risk_res,
                "portfolio": port_res
            },
            "summary": summary_text
        }

decision_agent = DecisionAgent()
