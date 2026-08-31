"""EXPMA 均线交叉策略。

EMA12 上穿 EMA50 买入，EMA12 下穿 EMA50 卖出。
严格参考 easy_tdx/strategies/expma_cross.py
"""
import pandas as pd
from easy_tdx.strategies.base import BaseStrategy, Param
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import EXPMA, CROSS

@register_strategy
class EXPMACrossStrategy(BaseStrategy):
    name = "expma_cross"
    display_name = "EXPMA指数均线交叉策略"
    category = "technical"
    description = "EMA12 上穿 EMA50 金叉买入，EMA12 下穿 EMA50 死叉卖出。"
    params_list = [
        Param("fast", int, default=12, min_value=2, max_value=60, step=1, label="快线 EMA 周期 (12)", description="短期指数平均线周期"),
        Param("slow", int, default=50, min_value=10, max_value=250, step=1, label="慢线 EMA 周期 (50)", description="长期指数平均线周期"),
    ]
    params_schema = {"fast": 12, "slow": 50}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        fast_p = int(self.params.get("fast", 12))
        slow_p = int(self.params.get("slow", 50))
        
        ema_fast, ema_slow = EXPMA(res["close"], fast_p, slow_p)
        res["buy_signal"] = CROSS(ema_fast, ema_slow)
        res["sell_signal"] = CROSS(ema_slow, ema_fast)
        return res
