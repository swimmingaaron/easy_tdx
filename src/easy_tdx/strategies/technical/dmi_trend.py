"""DMI 趋势跟踪策略。

PDI > MDI（多头方向力强）且 ADX > 25（趋势强度足够）时买入。
PDI < MDI 或 ADX < 20 时卖出——方向反转或趋势消失即离场。
严格参考 easy_tdx/strategies/dmi_trend.py
"""
import pandas as pd
from easy_tdx.strategies.base import BaseStrategy, Param
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import DMI

@register_strategy
class DMITrendStrategy(BaseStrategy):
    name = "dmi_trend"
    display_name = "DMI趋势跟踪策略"
    category = "technical"
    description = "PDI > MDI（多头强）且 ADX > 25（趋势强）买入；PDI < MDI 或 ADX < 20 卖出。"
    params_list = [
        Param("n", int, default=14, min_value=5, max_value=60, step=1, label="DMI 周期 (14)", description="动向指标统计周期"),
        Param("m", int, default=6, min_value=2, max_value=20, step=1, label="ADX 平滑周期 (6)", description="平均动向指数的平滑周期"),
        Param("adx_buy", float, default=25.0, min_value=10.0, max_value=50.0, step=1.0, label="入场趋势强度阈值 (ADX>25)", description="ADX 超过此值确认趋势强劲可追"),
        Param("adx_sell", float, default=20.0, min_value=5.0, max_value=40.0, step=1.0, label="离场趋势消退阈值 (ADX<20)", description="ADX 低于此值代表趋势衰竭"),
    ]
    params_schema = {"n": 14, "m": 6, "adx_buy": 25.0, "adx_sell": 20.0}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        n = int(self.params.get("n", 14))
        m = int(self.params.get("m", 6))
        adx_buy = float(self.params.get("adx_buy", 25.0))
        adx_sell = float(self.params.get("adx_sell", 20.0))
        
        pdi, mdi, adx, _ = DMI(res["close"], res["high"], res["low"], n, m)
        res["buy_signal"] = (pdi > mdi) & (adx > adx_buy)
        res["sell_signal"] = (pdi < mdi) | (adx < adx_sell)
        return res
