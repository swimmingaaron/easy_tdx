"""双均线交叉策略。

MA5 上穿 MA20（金叉）全仓买入，MA5 下穿 MA20（死叉）全部卖出。
严格参考 easy_tdx/strategies/ma_cross.py
"""
import pandas as pd
from easy_tdx.strategies.base import BaseStrategy, Param
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import MA, CROSS

@register_strategy
class MACrossStrategy(BaseStrategy):
    name = "ma_cross"
    display_name = "双均线交叉策略 (MA)"
    category = "technical"
    description = "快线上穿慢线金叉买入，快线下穿慢线死叉卖出。经典趋势跟踪策略。"
    params_list = [
        Param("fast_period", int, default=5, min_value=1, max_value=60, step=1, label="快线周期 (MA5)", description="短期移动平均线周期，通常为 5 日"),
        Param("slow_period", int, default=20, min_value=5, max_value=250, step=1, label="慢线周期 (MA20)", description="长期移动平均线周期，通常为 20 日"),
    ]
    params_schema = {"fast_period": 5, "slow_period": 20}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        fast_p = int(self.params.get("fast_period", 5))
        slow_p = int(self.params.get("slow_period", 20))
        
        ma_fast = MA(res["close"], fast_p)
        ma_slow = MA(res["close"], slow_p)
        res["buy_signal"] = CROSS(ma_fast, ma_slow)
        res["sell_signal"] = CROSS(ma_slow, ma_fast)
        return res
