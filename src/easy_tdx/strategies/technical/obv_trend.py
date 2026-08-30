import pandas as pd
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import OBV, MA, CROSS

@register_strategy
class OBVTrendStrategy(BaseStrategy):
    name = "obv_trend"
    display_name = "OBV能量潮筹码策略"
    category = "technical"
    description = "OBV 能量潮上穿其 30 日均线且突破前期高点买入"
    params_schema = {"ma_period": 30}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        obv = OBV(res["close"], res["volume"])
        obv_ma = MA(obv, self.params["ma_period"])
        res["buy_signal"] = CROSS(obv, obv_ma)
        res["sell_signal"] = CROSS(obv_ma, obv)
        return res
