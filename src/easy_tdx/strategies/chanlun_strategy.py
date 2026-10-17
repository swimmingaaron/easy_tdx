import pandas as pd
import numpy as np
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.chanlun.analyser import ChanlunAnalyser
from easy_tdx.chanlun.types import FXType, Direction

@register_strategy
class ChanlunBuySellStrategy(BaseStrategy):
    name = "chanlun_strategy"
    display_name = "缠论1/2/3类买卖点战法"
    category = "chanlun"
    description = "基于缠论分型、笔、中枢与背驰买卖点体系，支持二三买主升共振、次级别稳健二买低吸与一买底背驰"
    params_schema = {
        "buy_mode": {
            "type": "choice",
            "choices": ["combo_23", "all_buys", "steady_2buy", "breakout_3buy", "nested_1buy"],
            "default": "combo_23",
            "label": "买点模式",
            "description": "combo_23(二三买组合,推荐)、steady_2buy(次级别二买)、breakout_3buy(三买突破)、all_buys(全部买点)、nested_1buy(一买底背驰)",
        },
        "entry_mode": {
            "type": "choice",
            "choices": ["confirmed", "immediate"],
            "default": "confirmed",
            "label": "入场时机",
            "description": "confirmed(分型右侧确认入场，无未来函数)、immediate(极值触发)",
        },
    }

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.buy_mode = self.params.get("buy_mode", "combo_23")
        self.entry_mode = self.params.get("entry_mode", "confirmed")

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        n_bars = len(res)
        buy_sig = pd.Series(False, index=res.index)
        sell_sig = pd.Series(False, index=res.index)
        signal_types = pd.Series("", index=res.index)
        stop_prices = pd.Series(np.nan, index=res.index)

        if n_bars < 5:
            res["buy_signal"] = buy_sig
            res["sell_signal"] = sell_sig
            res["signal_type"] = signal_types
            res["stop_price"] = stop_prices
            return res

        try:
            analyser = ChanlunAnalyser(frequency="DAILY")
            cl_res = analyser.process_klines(res)

            buy_mode = self.buy_mode
            entry_mode = self.entry_mode

            for mmd in cl_res.mmds:
                mtype = mmd.mmd_type.value
                bi = mmd.bi
                if not bi or not bi.end:
                    continue
                fx = bi.end
                mid_idx = fx.k.k_index
                if entry_mode == "confirmed" and len(fx.klines) > 2 and fx.klines[2].klines:
                    bar_idx = fx.klines[2].klines[-1].index
                else:
                    bar_idx = mid_idx

                if bar_idx < 0 or bar_idx >= n_bars:
                    continue

                is_buy = False
                if buy_mode == "all_buys" and "buy" in mtype:
                    is_buy = True
                elif buy_mode == "combo_23" and ("2buy" in mtype or "3buy" in mtype):
                    is_buy = True
                elif buy_mode == "steady_2buy" and "2buy" in mtype:
                    is_buy = True
                elif buy_mode == "breakout_3buy" and "3buy" in mtype:
                    is_buy = True
                elif buy_mode == "nested_1buy" and "1buy" in mtype:
                    is_buy = True

                if is_buy:
                    buy_sig.iloc[bar_idx] = True
                    signal_types.iloc[bar_idx] = mtype
                    stop_prices.iloc[bar_idx] = fx.val

                if "sell" in mtype:
                    sell_sig.iloc[bar_idx] = True
                    signal_types.iloc[bar_idx] = mtype
        except Exception:
            pass

        res["buy_signal"] = buy_sig
        res["sell_signal"] = sell_sig
        res["signal_type"] = signal_types
        res["stop_price"] = stop_prices
        return res

