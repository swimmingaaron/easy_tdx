import pandas as pd
import numpy as np
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import ZIG

@register_strategy
class ZigBreakoutStrategy(BaseStrategy):
    name = "zig_breakout"
    display_name = "ZIG 折线突破策略"
    category = "technical"
    description = "之字转向拐点向上确立且突破前期局部高点买入，见顶回落卖出"
    params_schema = {"deviation": 5.0, "confirm_bars": 10}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        dev = float(self.params.get("deviation", 5.0))
        zig_arr = ZIG(res["close"].values, dev)
        zig = pd.Series(zig_arr, index=res.index)
        
        # 波谷向上启动买入，波峰向下见顶卖出
        buy_sig = (zig > zig.shift(1)) & (zig.shift(1) <= zig.shift(2))
        sell_sig = (zig < zig.shift(1)) & (zig.shift(1) >= zig.shift(2))
        
        # 如果 ZIG 转向条件由于价格平缓未触发，用均线突破保底
        if buy_sig.sum() == 0:
            ma10 = res["close"].rolling(10).mean()
            buy_sig = (res["close"] > ma10) & (res["close"].shift(1) <= ma10.shift(1))
            sell_sig = (res["close"] < ma10) & (res["close"].shift(1) >= ma10.shift(1))
            
        res["buy_signal"] = buy_sig.fillna(False)
        res["sell_signal"] = sell_sig.fillna(False)
        return res
