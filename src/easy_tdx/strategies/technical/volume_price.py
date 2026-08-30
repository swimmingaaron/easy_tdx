import pandas as pd
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import MA, REF

@register_strategy
class VolumePriceStrategy(BaseStrategy):
    name = "volume_price"
    display_name = "放量突破量价共振策略"
    category = "technical"
    description = "今日成交量大于 5 日均量 2 倍且涨幅 > 4% 放量突破买入"
    params_schema = {"vol_mult": 2.0, "ret_threshold": 4.0}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        v_ma5 = REF(MA(res["volume"], 5), 1)
        daily_ret = (res["close"] / REF(res["close"], 1) - 1) * 100
        res["buy_signal"] = (res["volume"] > v_ma5 * self.params["vol_mult"]) & (daily_ret > self.params["ret_threshold"])
        res["sell_signal"] = res["close"] < MA(res["close"], 10)
        return res
