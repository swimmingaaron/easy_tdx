"""量价配合策略。

放量上涨（成交量 > MA(vol,5) 且收阳线）买入，
缩量下跌（成交量 < MA(vol,5) 且收阴线）卖出。
严格参考 easy_tdx/strategies/volume_price.py
"""
import pandas as pd
from easy_tdx.strategies.base import BaseStrategy, Param
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import MA

@register_strategy
class VolumePriceStrategy(BaseStrategy):
    name = "volume_price"
    display_name = "量价配合策略"
    category = "technical"
    description = "放量上涨（成交量 > MA(vol,5) 且收阳线）买入，缩量下跌（成交量 < MA(vol,5) 且收阴线）卖出。"
    params_list = [
        Param("ma_period", int, default=5, min_value=2, max_value=30, step=1, label="均量线周期 MA(vol, N)", description="基准成交量均线周期"),
    ]
    params_schema = {"ma_period": 5}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        p = int(self.params.get("ma_period", 5))
        vol = res["volume"] if "volume" in res.columns else res["vol"]
        vol_ma = MA(vol, p)
        
        is_yang = res["close"] > res["open"]
        is_yin = res["close"] < res["open"]
        is_vol_up = vol > vol_ma
        is_vol_down = vol < vol_ma
        
        res["buy_signal"] = is_yang & is_vol_up
        res["sell_signal"] = is_yin & is_vol_down
        return res
