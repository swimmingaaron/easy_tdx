import pandas as pd
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import MA, HHV, LLV

@register_strategy
class MagicSquareStrategy(BaseStrategy):
    name = "magic_square"
    display_name = "九宫格量价形态战法"
    category = "pattern"
    description = "九宫格量价划分法：价格处于中低位箱体且成交量出现梯级放大放量启动点"
    params_schema = {"period": 60}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        c, v = res["close"], res["volume"]
        h_60 = HHV(res["high"], self.params["period"])
        l_60 = LLV(res["low"], self.params["period"])
        
        # 价格处于 60 日区间 30%~60% 中低位
        price_pos = (c - l_60) / (h_60 - l_60 + 1e-6)
        is_mid_low = (price_pos >= 0.25) & (price_pos <= 0.65)
        
        # 成交量明显放大
        vol_surge = v > MA(v, 20) * 1.8
        res["buy_signal"] = is_mid_low & vol_surge & (c > MA(c, 20))
        res["sell_signal"] = c < MA(c, 20)
        return res
