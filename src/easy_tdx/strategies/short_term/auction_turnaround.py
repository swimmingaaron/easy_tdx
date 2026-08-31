import pandas as pd
import numpy as np
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import REF

@register_strategy
class AuctionTurnaroundStrategy(BaseStrategy):
    name = "auction_turnaround"
    display_name = "集合竞价弱转强策略"
    category = "short_term"
    description = "昨日烂板或大阴线冲高回落，次日集合竞价超预期大幅高开抢筹"
    params_schema = {"min_gap_pct": 1.0}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        c = res["close"].values
        prev_c = pd.Series(REF(c, 1), index=res.index)
        prev_o = pd.Series(REF(res["open"].values, 1), index=res.index)
        prev_was_weak = (prev_c <= prev_o) | ((prev_c / pd.Series(REF(c, 2), index=res.index) - 1) * 100 < 1.0)
        
        gap_pct = (res["open"] / np.maximum(prev_c, 1e-4) - 1) * 100
        min_gap = float(self.params.get("min_gap_pct", 1.0))
        strong_auction = (gap_pct >= min_gap) & (res["close"] >= res["open"])
        
        buy_sig = prev_was_weak & strong_auction
        sell_sig = (res["close"] < res["open"] * 0.98) | (res["close"] < prev_c)
        
        res["buy_signal"] = buy_sig.fillna(False)
        res["sell_signal"] = sell_sig.fillna(False)
        return res
