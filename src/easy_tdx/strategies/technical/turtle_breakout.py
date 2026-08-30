import pandas as pd
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import HHV, LLV, ATR, REF

@register_strategy
class TurtleBreakoutStrategy(BaseStrategy):
    name = "turtle_breakout"
    display_name = "海龟交易法则策略"
    category = "technical"
    description = "价格突破 20 日最高价入场，跌破 10 日最低价离场"
    params_schema = {"entry_period": 20, "exit_period": 10}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        high_20 = REF(HHV(res["high"], self.params["entry_period"]), 1)
        low_10 = REF(LLV(res["low"], self.params["exit_period"]), 1)
        res["buy_signal"] = res["close"] > high_20
        res["sell_signal"] = res["close"] < low_10
        return res
