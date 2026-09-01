"""MFI 量价反转策略。

MFI < 20（资金流量超卖）买入；MFI > 80（资金流量超买）卖出。
严格参考 easy_tdx/strategies/mfi_volume.py
"""
import pandas as pd
from easy_tdx.strategies.base import BaseStrategy, Param
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import MFI

@register_strategy
class MFIVolumeStrategy(BaseStrategy):
    name = "mfi_volume"
    display_name = "MFI量价反转策略"
    category = "technical"
    description = "MFI < 20（资金超卖见底）买入，MFI > 80（资金过热超买）卖出。"
    params_list = [
        Param("period", int, default=14, min_value=5, max_value=60, step=1, label="MFI 周期 (14)", description="资金流量指标的计算周期"),
        Param("buy_threshold", float, default=20.0, min_value=5.0, max_value=40.0, step=1.0, label="超卖买入阈值 (20)", description="资金流出恐慌见底入场线"),
        Param("sell_threshold", float, default=80.0, min_value=60.0, max_value=95.0, step=1.0, label="超买卖出阈值 (80)", description="资金涌入过热离场线"),
    ]
    params_schema = {"period": 14, "buy_threshold": 20.0, "sell_threshold": 80.0}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        p = int(self.params.get("period", 14))
        buy_th = float(self.params.get("buy_threshold", 20.0))
        sell_th = float(self.params.get("sell_threshold", 80.0))
        
        vol = res["volume"] if "volume" in res.columns else res["vol"]
        mfi = MFI(res["close"], res["high"], res["low"], vol, p)
        res["buy_signal"] = mfi < buy_th
        res["sell_signal"] = mfi > sell_th
        return res
