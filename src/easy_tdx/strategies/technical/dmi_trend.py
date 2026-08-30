import pandas as pd
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import DMI, CROSS

@register_strategy
class DMITrendStrategy(BaseStrategy):
    name = "dmi_trend"
    display_name = "DMI趋向指标策略"
    category = "technical"
    description = "+DI 上穿 -DI 且 ADX 趋势强度大于 25 确认买入"
    params_schema = {"n": 14, "m": 6}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        pdi, mdi, adx, _ = DMI(res["close"], res["high"], res["low"], self.params["n"], self.params["m"])
        res["buy_signal"] = CROSS(pdi, mdi) & (adx > 25)
        res["sell_signal"] = CROSS(mdi, pdi)
        return res
