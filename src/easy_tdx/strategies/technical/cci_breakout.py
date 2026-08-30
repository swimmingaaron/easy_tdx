import pandas as pd
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import CCI, CROSS

@register_strategy
class CCIBreakoutStrategy(BaseStrategy):
    name = "cci_breakout"
    display_name = "CCI顺势突破策略"
    category = "technical"
    description = "CCI 向上突破 +100 超买强势区追涨入场，跌破 0 轴离场"
    params_schema = {"period": 14}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        cci = CCI(res["close"], res["high"], res["low"], self.params["period"])
        res["buy_signal"] = CROSS(cci, 100.0)
        res["sell_signal"] = CROSS(0.0, cci)
        return res
