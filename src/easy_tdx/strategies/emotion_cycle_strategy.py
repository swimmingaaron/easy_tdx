import pandas as pd
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import RSI, MA

@register_strategy
class EmotionCycleStrategy(BaseStrategy):
    name = "emotion_cycle"
    display_name = "情绪周期状态机波段策略"
    category = "alpha_quant"
    description = "冰点期恐慌出清左侧低吸建仓，主升期满仓加仓，高潮退潮期果断止盈防守"
    params_schema = {}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        # Proxy emotion index with RSI and Volatility
        rsi = RSI(res["close"], 6)
        c = res["close"]
        
        is_freezing = rsi < 20.0 # 冰点
        is_surging = (c > MA(c, 5)) & (MA(c, 5) > MA(c, 10)) & (rsi >= 55.0) & (rsi <= 75.0) # 主升
        is_climax = rsi > 85.0 # 高潮退潮
        
        res["buy_signal"] = is_freezing | is_surging
        res["sell_signal"] = is_climax
        return res
