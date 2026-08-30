"""Technical Agent: Multi-timeframe trend, moving averages, volume-price, and oscillator analysis."""
from __future__ import annotations
from typing import Any
import pandas as pd
import numpy as np
from easy_tdx.ai.agents.base_agent import BaseAgent
from easy_tdx.MyTT import MA, MACD

class TechnicalAgent(BaseAgent):
    agent_name = "technical_agent"
    role_description = "技术面量化智能体，负责均线多空、量价背离、KDJ/MACD 指标与形态结构研判"

    def analyze(self, symbol: str, kline_df: pd.DataFrame, context: dict[str, Any] | None = None) -> dict[str, Any]:
        if kline_df.empty or len(kline_df) < 20:
            return {
                "score": 60.0,
                "trend_status": "DATA_INSUFFICIENT",
                "summary": "K线数据量不足以进行深度技术分析"
            }

        close = kline_df["close"].values
        vol = kline_df["volume"].values
        
        # Moving averages
        ma5 = np.asarray(MA(close, 5))
        ma10 = np.asarray(MA(close, 10))
        ma20 = np.asarray(MA(close, 20))
        
        c_cur = float(close[-1])
        m5_cur = float(ma5[-1])
        m10_cur = float(ma10[-1])
        m20_cur = float(ma20[-1])
        
        # Multi-MA Bull alignment
        is_bull = (m5_cur >= m10_cur >= m20_cur) and (c_cur >= m5_cur)
        
        # Volume ratio (vol / ma_vol5)
        vol_ma5 = np.asarray(MA(vol, 5))
        vol_ratio = float(vol[-1] / vol_ma5[-1]) if float(vol_ma5[-1]) > 0 else 1.0
        
        # MACD
        dif, dea, macd = MACD(close)
        dif_arr = np.asarray(dif)
        dea_arr = np.asarray(dea)
        is_macd_gold = bool(float(dif_arr[-1]) > float(dea_arr[-1]))
        
        # Calculate Technical Score (0 ~ 100)
        score = 65.0
        if is_bull:
            score += 18.0
        if is_macd_gold:
            score += 8.0
        if 1.2 <= vol_ratio <= 3.0:
            score += 7.0
        elif vol_ratio > 3.5:
            score -= 5.0  # Excessive turnover warning
            
        score = min(98.0, max(40.0, score))
        trend_status = "多头排列 · 顺势主升" if is_bull else ("震荡整理 · 均线粘合" if c_cur >= m20_cur else "空头破位 · 弱势整理")
        
        summary = (
            f"当前价格 ¥{c_cur:.2f}，呈现【{trend_status}】，MA5/10/20 分别为 ¥{m5_cur:.2f}/¥{m10_cur:.2f}/¥{m20_cur:.2f}。"
            f"日内量比 {vol_ratio:.2f}，MACD {'金叉多头区域' if is_macd_gold else '死叉整理区域'}。"
        )

        return {
            "score": round(score, 1),
            "trend_status": trend_status,
            "is_bull_alignment": is_bull,
            "volume_ratio": round(vol_ratio, 2),
            "support_price": round(m10_cur, 2),
            "resistance_price": round(c_cur * 1.08, 2),
            "summary": summary
        }

technical_agent = TechnicalAgent()
