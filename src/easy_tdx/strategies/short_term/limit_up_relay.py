import pandas as pd
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import REF

@register_strategy
class LimitUpRelayStrategy(BaseStrategy):
    name = "limit_up_relay"
    display_name = "连板接力 / 1进2打板策略"
    category = "short_term"
    description = "首板涨停确立后，次日早盘高开 (2%~5%) 且分时强势上攻冲板接力"
    params_schema = {"min_open_pct": 2.0, "max_open_pct": 6.5}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        prev_close = REF(res["close"], 1)
        prev_ret = (prev_close / REF(res["close"], 2) - 1) * 100
        was_limit_up = prev_ret >= 9.8  # 昨日涨停
        
        open_pct = (res["open"] / prev_close - 1) * 100
        is_good_open = (open_pct >= self.params["min_open_pct"]) & (open_pct <= self.params["max_open_pct"])
        today_ret = (res["close"] / prev_close - 1) * 100
        
        res["buy_signal"] = was_limit_up & is_good_open & (today_ret >= 9.8)
        res["sell_signal"] = (today_ret < 5.0) & was_limit_up.shift(1)
        return res
