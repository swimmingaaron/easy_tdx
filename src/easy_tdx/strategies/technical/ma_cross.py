import pandas as pd
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import MA, CROSS

@register_strategy
class MACrossStrategy(BaseStrategy):
    name = "ma_cross"
    display_name = "双均线交叉策略"
    category = "technical"
    description = "短期均线上穿长期均线金叉买入，死叉卖出"
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
