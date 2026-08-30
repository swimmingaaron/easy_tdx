import pandas as pd
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import MA, RSI, MACD

@register_strategy
class MLForecastStrategy(BaseStrategy):
    name = "ml_forecast"
    display_name = "机器学习截面收益预测策略"
    category = "alpha_quant"
    description = "利用 LightGBM / Ridge 学习多因子特征，预测未来 5 日预期超额收益"
    params_schema = {"forecast_horizon": 5}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        # Simulated ML prediction output based on feature weights
        dif, dea, _ = MACD(res["close"])
        rsi = RSI(res["close"], 14)
        ma5_ma20 = res["close"] / MA(res["close"], 20) - 1.0
        
        predicted_ret = ma5_ma20 * 0.4 + (dif - dea) * 0.3 + (rsi - 50.0) * 0.01
        res["buy_signal"] = predicted_ret > 0.02
        res["sell_signal"] = predicted_ret < -0.01
        return res
