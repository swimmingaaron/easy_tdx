import pandas as pd
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import MA, DMA, CROSS

@register_strategy
class MagicSquareDMAStrategy(BaseStrategy):
    name = "magic_square_dma"
    display_name = "九宫格DMA多空战法"
    category = "pattern"
    description = "九宫格中位放量形态结合 DMA 动态均线黄金交叉共振买入"
    params_schema = {}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        dma_fast = MA(res["close"], 10) - MA(res["close"], 50)
        dma_slow = MA(dma_fast, 10)
        res["buy_signal"] = CROSS(dma_fast, dma_slow) & (res["close"] > MA(res["close"], 20))
        res["sell_signal"] = CROSS(dma_slow, dma_fast)
        return res
