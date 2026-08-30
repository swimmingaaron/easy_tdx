import pandas as pd
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import MA, REF

@register_strategy
class DeviationReversionStrategy(BaseStrategy):
    name = "deviation_reversion"
    display_name = "交易所偏离值低吸策略"
    category = "short_term"
    description = "监控主板 3日 20% 偏离值红线，在极限压异动洗盘后首阳低吸"
    params_schema = {"safe_deviation_pct": 18.0}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        cum_3d = (res["close"] / REF(res["close"], 3) - 1) * 100
        safe_zone = (cum_3d <= self.params["safe_deviation_pct"]) & (cum_3d >= 10.0)
        res["buy_signal"] = safe_zone & (res["close"] > res["open"]) & (res["close"] > MA(res["close"], 5))
        res["sell_signal"] = res["close"] < MA(res["close"], 5)
        return res
