"""TRIX 三重平滑趋势策略。

TRIX 上穿信号线（TRIX_MA）买入；下穿卖出。
严格参考 easy_tdx/strategies/trix_cross.py
"""
import pandas as pd
from easy_tdx.strategies.base import BaseStrategy, Param
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import TRIX, CROSS

@register_strategy
class TRIXCrossStrategy(BaseStrategy):
    name = "trix_cross"
    display_name = "TRIX三重平滑趋势策略"
    category = "technical"
    description = "TRIX 上穿信号线（TRMA）金叉买入，下穿死叉卖出。"
    params_list = [
        Param("n", int, default=12, min_value=2, max_value=60, step=1, label="TRIX 平滑周期 (12)", description="三次指数平滑周期"),
        Param("m", int, default=20, min_value=2, max_value=60, step=1, label="TRMA 信号线周期 (20)", description="TRIX 的移动平均周期"),
    ]
    params_schema = {"n": 12, "m": 20}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        n = int(self.params.get("n", 12))
        m = int(self.params.get("m", 20))
        
        trix, trma = TRIX(res["close"], n, m)
        res["buy_signal"] = CROSS(trix, trma)
        res["sell_signal"] = CROSS(trma, trix)
        return res
