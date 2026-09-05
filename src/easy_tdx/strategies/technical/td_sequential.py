"""通达信上升九转策略 (Ascending TD Sequential Strategy).

交易逻辑 (只做上升九转):
------------------------
1. 买入建仓:
   - 当 K 线上出现上升九转启动信号 (td_high == 1)，代表收盘价首次有效超越 4 日前收盘价 (C > REF(C, 4))，
     多头动能爆发、主升浪突破确立，以次日开盘价全仓顺势买入建仓！
2. 卖出平仓:
   - 见顶止盈: 当上升九转连续完成到第 m 根 (td_high == m，默认高九)，多头衰竭滞涨，逢高精准止盈离场！
   - 目标止盈: 若涨幅达到 take_profit_pct 提前获利了结 (0 为不设固定比例，由高九见顶卖出)；
   - 硬止损保护: 跌破买入价 stop_loss_pct (默认 5.0%) 强制平仓，防假突破套牢；
   - 最大持仓期: 持股达到 max_hold_bars (默认 12 根 K 线) 未现高九则平仓释放资金。
"""
from __future__ import annotations
import pandas as pd
from easy_tdx.strategies.base import BaseStrategy, Param
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import TD_SEQUENTIAL


@register_strategy
class TDSequentialStrategy(BaseStrategy):
    name = "td_sequential"
    display_name = "通达信上升九转策略"
    category = "technical"
    description = "只做上升九转：高1顺势主升突破建仓，高9见顶衰竭逢高止盈，专做单边主升浪大行情。"
    
    params_list = [
        Param("m", int, default=9, min_value=9, max_value=13, step=4, label="序列点数 (9/13)", description="通达信上升九转 (9) 或十三转 (13) 见顶目标"),
        Param("max_hold_bars", int, default=12, min_value=3, max_value=30, step=1, label="最大持仓周期 (12)", description="买入后最多持仓 K 线根数（交易日），若未现高九则主动平仓"),
        Param("stop_loss_pct", float, default=5.0, min_value=0.0, max_value=15.0, step=0.5, label="硬止损比例 (%)", description="跌破买入价此比例强制平仓止损（0 为不设硬止损）"),
        Param("take_profit_pct", float, default=0.0, min_value=0.0, max_value=50.0, step=1.0, label="目标止盈比例 (%)", description="达到此盈利幅度提前止盈离场（0 为仅由高九见顶卖出）"),
    ]
    params_schema = {"m": 9, "max_hold_bars": 12, "stop_loss_pct": 5.0, "take_profit_pct": 0.0}

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        m_val = int(self.params.get("m", 9))
        max_hold = int(self.params.get("max_hold_bars", 12))
        sl_pct = float(self.params.get("stop_loss_pct", 5.0))
        tp_pct = float(self.params.get("take_profit_pct", 0.0))
        
        c_vals = res["close"].values
        td_high, _ = TD_SEQUENTIAL(c_vals, m_val)
        
        n = len(res)
        buy_sig = [False] * n
        sell_sig = [False] * n
        in_pos = False
        buy_price = 0.0
        buy_idx = 0
        
        for i in range(1, n):
            cur_c = float(c_vals[i])
            
            if in_pos:
                # 卖出条件：
                # 1. 出现上升九转完成 (高九 / 高十三) 见顶止盈
                is_high_m = (td_high[i] == m_val)
                # 2. 硬止损保护
                is_sl = (sl_pct > 0) and (cur_c < buy_price * (1.0 - sl_pct / 100.0))
                # 3. 目标止盈提前锁定
                is_tp = (tp_pct > 0) and (cur_c >= buy_price * (1.0 + tp_pct / 100.0))
                # 4. 最大持仓天数保护
                is_timeout = (max_hold > 0) and (i - buy_idx >= max_hold)
                
                if is_high_m or is_sl or is_tp or is_timeout:
                    sell_sig[i] = True
                    in_pos = False
            else:
                # 只做上升九转：出现上升九转启动第 1 根时顺势建仓
                if td_high[i] == 1:
                    buy_sig[i] = True
                    in_pos = True
                    buy_price = cur_c
                    buy_idx = i
                    
        res["buy_signal"] = buy_sig
        res["sell_signal"] = sell_sig
        return res
