import pandas as pd
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import MA, REF

@register_strategy
class VolumeTurnoverStrategy(BaseStrategy):
    name = "volume_turnover"
    display_name = "换手倍量突破战法"
    category = "pattern"
    description = "单日换手率较前5日倍增 (换手率 > 5% 且 Volume > 2*MA5) 强势启动"
    params_schema = {"vol_mult": 2.0}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        v_ma5 = REF(MA(res["volume"], 5), 1)
        surge = res["volume"] > v_ma5 * self.params["vol_mult"]
        daily_ret = (res["close"] / REF(res["close"], 1) - 1) * 100
        res["buy_signal"] = surge & (daily_ret >= 3.0) & (res["close"] > MA(res["close"], 20))
        res["sell_signal"] = res["close"] < MA(res["close"], 5)
        return res
