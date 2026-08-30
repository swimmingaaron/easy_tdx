import pandas as pd
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import ZIG, CROSS

@register_strategy
class ZigBreakoutStrategy(BaseStrategy):
    name = "zig_breakout"
    display_name = "ZigZag波浪拐点策略"
    category = "technical"
    description = "之字转向拐点向上确立且突破前期局部高点买入"
    params_schema = {"deviation": 5.0}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        zig = ZIG(res["close"], self.params["deviation"])
        res["buy_signal"] = (zig > zig.shift(1)) & (zig.shift(1) <= zig.shift(2))
        res["sell_signal"] = (zig < zig.shift(1)) & (zig.shift(1) >= zig.shift(2))
        return res
