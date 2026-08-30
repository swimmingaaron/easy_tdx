import pandas as pd
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import BIAS

@register_strategy
class BiasReversalStrategy(BaseStrategy):
    name = "bias_reversal"
    display_name = "BIAS乖离率超跌反弹策略"
    category = "technical"
    description = "BIAS(6) 负乖离达到极端超跌阈值 (<-6%) 均值回归买入"
    params_schema = {"threshold": -6.0}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        b1, _, _ = BIAS(res["close"])
        res["buy_signal"] = b1 < self.params["threshold"]
        res["sell_signal"] = b1 > 5.0
        return res
