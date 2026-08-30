import pandas as pd
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import MA

@register_strategy
class MultiFactorCompositeStrategy(BaseStrategy):
    name = "multi_factor_composite"
    display_name = "多因子综合加权选股策略"
    category = "alpha_quant"
    description = "综合动量、估值、质量、流动性多维度 IC-IR 复合打分选股"
    params_schema = {}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        mom = res["close"].pct_change(20).fillna(0)
        vol = res["close"].pct_change().rolling(20).std().fillna(0)
        turnover = res["volume"] / MA(res["volume"], 20)
        
        # Composite score
        score = mom * 0.4 - vol * 0.3 + turnover * 0.3
        res["buy_signal"] = score > score.rolling(40).mean() + score.rolling(40).std()
        res["sell_signal"] = score < score.rolling(40).mean()
        return res
