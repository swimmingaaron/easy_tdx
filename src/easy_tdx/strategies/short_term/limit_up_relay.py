import pandas as pd
import numpy as np
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import REF

@register_strategy
class LimitUpRelayStrategy(BaseStrategy):
    name = "limit_up_relay"
    display_name = "连板接力 / 1进2打板策略"
    category = "short_term"
    description = "首板涨停确立后，次日早盘高开 (2%~5%) 且分时强势上攻冲板接力"
    params_schema = {"min_open_pct": 1.5, "max_open_pct": 7.0}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        c = res["close"].values
        prev_close = pd.Series(REF(c, 1), index=res.index)
        prev_close_2 = pd.Series(REF(c, 2), index=res.index)
        
        prev_ret = (prev_close / np.maximum(prev_close_2, 1e-4) - 1) * 100
        was_limit_up = prev_ret >= 5.0  # 扩大触发灵敏度
        
        open_pct = (res["open"] / np.maximum(prev_close, 1e-4) - 1) * 100
        min_op = float(self.params.get("min_open_pct", 1.5))
        max_op = float(self.params.get("max_open_pct", 7.0))
        is_good_open = (open_pct >= min_op) & (open_pct <= max_op)
        today_ret = (res["close"] / np.maximum(prev_close, 1e-4) - 1) * 100
        
        buy_sig = (was_limit_up & is_good_open & (today_ret >= 3.0)) | ((today_ret >= 6.0) & (res["close"] > res["open"]))
        sell_sig = (today_ret < 0.0) | (res["close"] < prev_close * 0.96)
        
        res["buy_signal"] = buy_sig.fillna(False)
        res["sell_signal"] = sell_sig.fillna(False)
        return res
