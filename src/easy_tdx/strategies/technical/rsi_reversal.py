import pandas as pd
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import RSI, CROSS

@register_strategy
class RSIReversalStrategy(BaseStrategy):
    name = "rsi_reversal"
    display_name = "RSI极值反转策略"
    category = "technical"
    description = "RSI 深度超卖 (<25) 回升买入，超买 (>75) 止盈"
    params_schema = {"period": 14, "oversold": 25, "overbought": 75}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        rsi = RSI(res["close"], self.params["period"])
        res["buy_signal"] = CROSS(rsi, self.params["oversold"])
        res["sell_signal"] = CROSS(self.params["overbought"], rsi)
        return res
