import pandas as pd
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import MA, RSI, MACD

@register_strategy
class RankICDecileStrategy(BaseStrategy):
    name = "rank_ic_decile"
    display_name = "Alpha因子Rank IC分层多头策略"
    category = "alpha_quant"
    description = "跟踪有效 Alpha 因子（动量+资金流）Top 10% 组合轮动持有"
    params_schema = {"top_percent": 0.10}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        # Alpha score formulation: 0.5 * mom_20d + 0.3 * rsi_14 + 0.2 * vol_ratio
        mom20 = res["close"] / res["close"].shift(20) - 1.0
        rsi = RSI(res["close"], 14)
        vol_ratio = res["volume"] / MA(res["volume"], 20)
        alpha_score = mom20 * 0.5 + (rsi / 100.0) * 0.3 + vol_ratio * 0.2
        
        res["buy_signal"] = alpha_score > alpha_score.rolling(60).quantile(0.90)
        res["sell_signal"] = alpha_score < alpha_score.rolling(60).quantile(0.50)
        return res
