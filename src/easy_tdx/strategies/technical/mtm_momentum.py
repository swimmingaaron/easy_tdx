import pandas as pd
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import MTM, CROSS

@register_strategy
class MTMMomentumStrategy(BaseStrategy):
    name = "mtm_momentum"
    display_name = "MTM动量加速策略"
    category = "technical"
    description = "MTM 动量线上穿其移动平均线，动量加速确立买入"
    params_schema = {"n": 12, "m": 6}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        mtm, mtmma = MTM(res["close"], self.params["n"], self.params["m"])
        res["buy_signal"] = CROSS(mtm, mtmma) & (mtm > 0)
        res["sell_signal"] = CROSS(mtmma, mtm)
        return res
