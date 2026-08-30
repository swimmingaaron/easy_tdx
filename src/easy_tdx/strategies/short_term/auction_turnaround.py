import pandas as pd
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import REF

@register_strategy
class AuctionTurnaroundStrategy(BaseStrategy):
    name = "auction_turnaround"
    display_name = "集合竞价弱转强策略"
    category = "short_term"
    description = "昨日烂板或大阴线冲高回落，次日集合竞价超预期大幅高开抢筹"
    params_schema = {"min_gap_pct": 3.0}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        prev_c = REF(res["close"], 1)
        prev_o = REF(res["open"], 1)
        prev_was_weak = (prev_c < prev_o) | ((prev_c / REF(res["close"], 2) - 1) * 100 < 2.0)
        
        gap_pct = (res["open"] / prev_c - 1) * 100
        strong_auction = gap_pct >= self.params["min_gap_pct"]
        
        res["buy_signal"] = prev_was_weak & strong_auction
        res["sell_signal"] = res["close"] < res["open"]
        return res
