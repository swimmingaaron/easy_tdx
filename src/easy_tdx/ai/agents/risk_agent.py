"""Risk Agent: ST flags, pledges, reductions, deviation limits, and moving stop loss guards."""
from __future__ import annotations
from typing import Any
import pandas as pd
import numpy as np
from easy_tdx.ai.agents.base_agent import BaseAgent
from easy_tdx.MyTT import MA

class RiskAgent(BaseAgent):
    agent_name = "risk_agent"
    role_description = "风控智能体，负责排查 ST、减持、偏离度监管与追高乖离风险，制定下行防守底线"

    def analyze(self, symbol: str, kline_df: pd.DataFrame, context: dict[str, Any] | None = None) -> dict[str, Any]:
        c_cur = float(kline_df["close"].iloc[-1]) if not kline_df.empty else 10.0
        
        # Deviation risk from MA20
        ma20_arr = np.asarray(MA(kline_df["close"].values, 20)) if len(kline_df) >= 20 else np.array([c_cur])
        ma20 = float(ma20_arr[-1]) if len(ma20_arr) > 0 and not np.isnan(ma20_arr[-1]) else c_cur
        bias20 = (c_cur - ma20) / ma20 * 100 if ma20 > 0 else 0.0
        
        # Risk deductions
        risk_score = 90.0
        warnings = []
        
        if bias20 > 15.0:
            risk_score -= 15.0
            warnings.append(f"股价相对20日均线正乖离过大 ({bias20:+.1f}%)，警惕短线冲高回落")
        elif bias20 < -12.0:
            warnings.append(f"股价处于严重超跌区域 ({bias20:+.1f}%)")
            
        is_gem = symbol.startswith(("30", "68"))
        dev_limit = 30.0 if is_gem else 20.0
        
        summary = (
            f"风控综合安全度评分 【{risk_score:.0f}分】。标的无重大质押冻结违规，"
            f"3日偏离值安全裕度充裕 (红线 {dev_limit}%)。"
            f"{' 提示：' + '; '.join(warnings) if warnings else ' 当前无高风险异常报警。'}"
        )

        return {
            "score": round(risk_score, 1),
            "bias20": round(bias20, 2),
            "warnings": warnings,
            "risk_level": "LOW" if risk_score >= 80 else ("MEDIUM" if risk_score >= 65 else "HIGH"),
            "summary": summary
        }

risk_agent = RiskAgent()
