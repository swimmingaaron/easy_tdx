import pandas as pd
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import TRIX, CROSS

@register_strategy
class TRIXCrossStrategy(BaseStrategy):
    name = "trix_cross"
    display_name = "TRIX三重平滑交叉策略"
    category = "technical"
    description = "TRIX 滤除市场杂波，快线上穿慢线金叉买入"
    params_schema = {"n": 12, "m": 9}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        trix, matrix = TRIX(res["close"], self.params["n"], self.params["m"])
        res["buy_signal"] = CROSS(trix, matrix)
        res["sell_signal"] = CROSS(matrix, trix)
        return res
