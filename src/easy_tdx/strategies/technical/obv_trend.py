"""OBV 能量潮趋势策略。

OBV 超过 MAOBV（30 日均线）一定缓冲带后确认多头，MAOBV 自身趋势向上时买入。
OBV 跌破 MAOBV 时卖出——资金流向转空即离场。
严格参考 easy_tdx/strategies/obv_trend.py
"""
import pandas as pd
from easy_tdx.strategies.base import BaseStrategy, Param
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import OBV, MA

@register_strategy
class OBVTrendStrategy(BaseStrategy):
    name = "obv_trend"
    display_name = "OBV能量潮趋势策略"
    category = "technical"
    description = "OBV 超过 MAOBV 一定缓冲带且 MAOBV 向上买入；OBV 跌破 MAOBV 卖出。"
    params_list = [
        Param("maobv_period", int, default=30, min_value=5, max_value=120, step=1, label="MAOBV 均线周期 (30)", description="OBV 的平滑均线周期"),
        Param("maobv_lookback", int, default=20, min_value=5, max_value=60, step=1, label="MAOBV 趋势判定回溯根数 (20)", description="判断 MAOBV 是否向上的回溯周期"),
        Param("obv_buffer", float, default=0.02, min_value=0.0, max_value=0.1, step=0.005, label="OBV 入场缓冲带比例 (2%)", description="OBV 需领先 MAOBV 的百分比幅度"),
    ]
    params_schema = {"maobv_period": 30, "maobv_lookback": 20, "obv_buffer": 0.02}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        p = int(self.params.get("maobv_period", 30))
        lb = int(self.params.get("maobv_lookback", 20))
        buf = float(self.params.get("obv_buffer", 0.02))
        
        vol = res["volume"] if "volume" in res.columns else res["vol"]
        obv = pd.Series(OBV(res["close"], vol), index=res.index)
        maobv = pd.Series(MA(obv.values, p), index=res.index)
        
        maobv_prev = maobv.shift(lb).bfill()
        maobv_rising = maobv > maobv_prev
        
        res["buy_signal"] = (obv > maobv * (1.0 + buf)) & maobv_rising
        res["sell_signal"] = obv < maobv
        return res
