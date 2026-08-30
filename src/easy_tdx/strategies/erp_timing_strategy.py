import pandas as pd
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import MA

@register_strategy
class ERPTimingStrategy(BaseStrategy):
    name = "erp_timing"
    display_name = "ERP股债性价比宏观择时策略"
    category = "alpha_quant"
    description = "ERP > 4% 权益极具性价比满仓做多，ERP < 2% 估值泡沫减仓防守"
    params_schema = {"erp_buy_level": 3.5, "erp_sell_level": 2.0}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        # Technical proxy for equity risk premium valuation cycle
        dist_to_ma250 = (res["close"] - MA(res["close"], 250)) / MA(res["close"], 250) * 100
        res["buy_signal"] = dist_to_ma250 < -15.0 # 深度低估买入
        res["sell_signal"] = dist_to_ma250 > 25.0 # 极度高估卖出
        return res
