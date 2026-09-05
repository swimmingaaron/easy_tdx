"""通达信九转/十三转量化策略 (TD Sequential Strategy).

交易逻辑:
--------
1. 买入信号 (根据 trade_mode 参数支持多种风格):
   - 顺势主升买入 (Trend): 当出现上升九转启动信号 (td_high == 1)，代表收盘价有效突破前 4 日高点，多头主升启动，顺势建仓！
   - 超跌反转买入 (Reversal): 当出现下跌九转完成信号 (td_low == m)，代表空头动能耗尽、出现超跌支撑，左侧抄底！
   - 双向全能模式 (Both, 默认推荐): 既做低九超跌反转，也做高1顺势主升突破，绝不错过任何大行情！
2. 卖出信号:
   - 高九见顶止盈: 出现上升九转完成 (td_high == m)，多头动能衰竭、见顶滞涨，逢高获利了结；
   - 目标止盈: 涨幅达到 take_profit_pct 提前锁定利润 (0 为不设固定比例，由高九卖出)；
   - 硬止损保护: 跌破买入价 stop_loss_pct 强制止损，防范深度套牢；
   - 时间保护: 持仓达到 max_hold_bars 根 K 线若未现高九，则主动平仓释放资金。
"""
from __future__ import annotations
import pandas as pd
from easy_tdx.strategies.base import BaseStrategy, Param
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import TD_SEQUENTIAL


@register_strategy
class TDSequentialStrategy(BaseStrategy):
    name = "td_sequential"
    display_name = "通达信九转策略"
    category = "technical"
    description = "基于通达信标准九转/十三转，支持高1顺势主升追涨与低9超跌反弹抄底，并在高9见顶时精准逢高止盈。"
    
    params_list = [
        Param("m", int, default=9, min_value=9, max_value=13, step=4, label="序列点数 (9/13)", description="通达信九转 (9) 或十三转 (13) 序列"),
        Param("trade_mode", str, default="both", label="交易模式", description="both=双向全能(主升+抄底), trend=仅顺势主升(高1买), reversal=仅超跌反转(低9买)"),
        Param("max_hold_bars", int, default=15, min_value=3, max_value=40, step=1, label="最大持仓周期 (15)", description="买入后最多持仓 K 线根数，若未现高九则平仓"),
        Param("stop_loss_pct", float, default=5.0, min_value=0.0, max_value=15.0, step=0.5, label="硬止损比例 (%)", description="跌破买入价此比例强制平仓止损（0 为不设硬止损）"),
        Param("take_profit_pct", float, default=0.0, min_value=0.0, max_value=50.0, step=1.0, label="目标止盈比例 (%)", description="达到此盈利幅度提前止盈离场（0 为仅由高九见顶卖出）"),
    ]
    params_schema = {"m": 9, "trade_mode": "both", "max_hold_bars": 15, "stop_loss_pct": 5.0, "take_profit_pct": 0.0}

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        m_val = int(self.params.get("m", 9))
        mode = str(self.params.get("trade_mode", "both")).lower()
        max_hold = int(self.params.get("max_hold_bars", 15))
        sl_pct = float(self.params.get("stop_loss_pct", 5.0))
        tp_pct = float(self.params.get("take_profit_pct", 0.0))
        
        c_vals = res["close"].values
        td_high, td_low = TD_SEQUENTIAL(c_vals, m_val)
        
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
                # 1. 出现高九 (td_high == m_val) 见顶止盈
                is_high_m = (td_high[i] == m_val)
                # 2. 硬止损
                is_sl = (sl_pct > 0) and (cur_c < buy_price * (1.0 - sl_pct / 100.0))
                # 3. 目标止盈
                is_tp = (tp_pct > 0) and (cur_c >= buy_price * (1.0 + tp_pct / 100.0))
                # 4. 持仓超时
                is_timeout = (max_hold > 0) and (i - buy_idx >= max_hold)
                
                if is_high_m or is_sl or is_tp or is_timeout:
                    sell_sig[i] = True
                    in_pos = False
            else:
                # 买入条件：
                can_buy = False
                if mode in ("both", "reversal") and td_low[i] == m_val:
                    # 抄底反转买入：下跌九转低九完成
                    can_buy = True
                elif mode in ("both", "trend") and td_high[i] == 1:
                    # 顺势主升买入：上升九转第 1 根启动突破 (如 2026-06-12)
                    can_buy = True
                
                if can_buy:
                    buy_sig[i] = True
                    in_pos = True
                    buy_price = cur_c
                    buy_idx = i
                    
        res["buy_signal"] = buy_sig
        res["sell_signal"] = sell_sig
        return res
