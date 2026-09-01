"""RSI 超买超卖策略。

RSI < 30（超卖）买入，RSI > 70（超买）卖出。
严格参考 easy_tdx/strategies/rsi_reversal.py
"""
import pandas as pd
from easy_tdx.strategies.base import BaseStrategy, Param
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import RSI

@register_strategy
class RSIReversalStrategy(BaseStrategy):
    name = "rsi_reversal"
    display_name = "RSI超买超卖反转策略"
    category = "technical"
    description = "RSI < 30（超卖）买入，RSI > 70（超买）卖出。"
    params_list = [
        Param("period", int, default=14, min_value=2, max_value=50, step=1, label="RSI 周期 (14)", description="相对强弱指标的计算周期"),
        Param("buy_threshold", float, default=30.0, min_value=5.0, max_value=45.0, step=1.0, label="超卖买入线 (30)", description="RSI 低于此值触发超跌买入"),
        Param("sell_threshold", float, default=70.0, min_value=55.0, max_value=95.0, step=1.0, label="超买卖出线 (70)", description="RSI 高于此值触发超买止盈"),
    ]
    params_schema = {"period": 14, "buy_threshold": 30.0, "sell_threshold": 70.0}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        p = int(self.params.get("period", 14))
        buy_th = float(self.params.get("buy_threshold", 30.0))
        sell_th = float(self.params.get("sell_threshold", 70.0))
        
        rsi = RSI(res["close"], p)
        res["buy_signal"] = rsi < buy_th
        res["sell_signal"] = rsi > sell_th
        return res
