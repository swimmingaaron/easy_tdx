import pandas as pd
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import EXPMA, CROSS

@register_strategy
class EXPMACrossStrategy(BaseStrategy):
    name = "expma_cross"
    display_name = "EXPMA指数平均线策略"
    category = "technical"
    description = "快线 EXPMA(12) 上穿慢线 EXPMA(50) 金叉做多"
    params_schema = {"fast": 12, "slow": 50}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        fast, slow = EXPMA(res["close"], self.params["fast"], self.params["slow"])
        res["buy_signal"] = CROSS(fast, slow)
        res["sell_signal"] = CROSS(slow, fast)
        return res
