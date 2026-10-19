import pandas as pd
import numpy as np
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.chanlun.analyser import ChanlunAnalyser
from easy_tdx.chanlun.types import FXType, Direction

@register_strategy
class ChanlunBuySellStrategy(BaseStrategy):
    name = "chanlun_strategy"
    display_name = "缠论主升3买与中枢突破策略"
    category = "chanlun"
    description = "基于缠论分型、笔与中枢体系，以主升3买（次级别突破中枢回抽不破ZG确认）为核心买入点，捕捉主升浪起跑，大幅提升交易胜率"
    params_schema = {
        "buy_mode": {
            "type": "choice",
            "choices": ["breakout_3buy", "combo_23", "all_buys", "steady_2buy", "nested_1buy"],
            "default": "breakout_3buy",
            "label": "买点模式",
            "description": "breakout_3buy(主升3买突破确认,胜率最高·推荐)、combo_23(二三买组合)、steady_2buy(次级别二买)、all_buys(全部买点)、nested_1buy(一买底背驰)",
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
        bm = self.params.get("buy_mode", "breakout_3buy")
        if isinstance(bm, dict):
            bm = bm.get("default", "breakout_3buy")
        self.buy_mode = str(bm) if bm else "breakout_3buy"

        em = self.params.get("entry_mode", "confirmed")
        if isinstance(em, dict):
            em = em.get("default", "confirmed")
        self.entry_mode = str(em) if em else "confirmed"

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

            buy_mode = str(self.buy_mode).strip().lower()
            entry_mode = str(self.entry_mode).strip().lower()

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

