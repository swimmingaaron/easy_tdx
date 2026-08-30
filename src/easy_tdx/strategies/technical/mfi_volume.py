import pandas as pd
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import MFI, CROSS

@register_strategy
class MFIVolumeStrategy(BaseStrategy):
    name = "mfi_volume"
    display_name = "MFI资金流量指标策略"
    category = "technical"
    description = "资金流量指标超卖区 (<20) 回升放量买入，超买区 (>80) 卖出"
    params_schema = {"period": 14}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        mfi = MFI(res["close"], res["high"], res["low"], res["volume"], self.params["period"])
        res["buy_signal"] = CROSS(mfi, 20.0)
        res["sell_signal"] = CROSS(80.0, mfi)
        return res
