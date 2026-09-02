"""ZIG 右侧突破回补策略（方案 1：Re-entry on Breakout + 硬止损保护）。

交易逻辑
--------
1. 空仓：ZIG 向上启动（底部波谷确认）→ 买入建仓。
2. 持仓：ZIG 见顶回落 → 卖出，并记录 N 日最高价为 breakout_level。
3. 空仓等待回补：收盘价突破 breakout_level × (1 + confirm_pct/100)
   → 右侧突破确认，洗盘结束主升确立，买入回补。
4. 硬止损保护：跌破买入价 stop_loss_pct 时止损。
严格参考 easy_tdx/strategies/zig_breakout.py
"""
import pandas as pd
from easy_tdx.strategies.base import BaseStrategy, Param
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import ZIG, HHV

@register_strategy
class ZigBreakoutStrategy(BaseStrategy):
    name = "zig_breakout"
    display_name = "ZIG 右侧突破回补"
    category = "technical"
    description = (
        "ZIG 见顶全仓卖出，空仓期间收盘价右侧突破前高时回补买入。"
        "信号全为整仓 BUY/SELL，逻辑清晰、无分仓复杂度。"
    )
    params_list = [
        Param("zig_delta", float, default=10.0, min_value=1.0, max_value=50.0, step=1.0, label="ZIG 转向阈值(%)", description="价格反转触发 ZIG 转向的百分比阈值"),
        Param("confirm_pct", float, default=1.0, min_value=0.5, max_value=15.0, step=0.5, label="突破确认幅度(%)", description="收盘价需超过前高多少百分比才触发回补买入（防止假突破）"),
        Param("hhv_period", int, default=20, min_value=5, max_value=60, step=1, label="前高统计周期", description="卖出时记录最近 N 日最高价作为突破参考位"),
        Param("stop_loss_pct", float, default=3.0, min_value=0.0, max_value=20.0, step=0.5, label="硬止损比例(%)", description="买入后跌破买入价该百分比强制平仓止损（0 为关闭，防假波谷套牢）"),
    ]
    params_schema = {"zig_delta": 10.0, "confirm_pct": 1.0, "hhv_period": 20, "stop_loss_pct": 3.0}
    
    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        z_delta = float(self.params.get("zig_delta", 10.0))
        conf_pct = float(self.params.get("confirm_pct", 1.0))
        hhv_p = int(self.params.get("hhv_period", 20))
        sl_pct = float(self.params.get("stop_loss_pct", 3.0))
        
        zig_arr = ZIG(res["close"].values, z_delta)
        hhv_arr = HHV(res["high"].values, hhv_p)
        
        n = len(res)
        buy_sig = [False] * n
        sell_sig = [False] * n
        breakout_level = 0.0
        in_pos = False
        buy_price = 0.0
        
        for i in range(1, n):
            cur_c = float(res["close"].iloc[i])
            cur_z = float(zig_arr[i])
            prev_z = float(zig_arr[i - 1])
            
            # 持仓中检查硬止损与见顶卖出
            if in_pos:
                is_stop_loss = (sl_pct > 0) and (cur_c < buy_price * (1.0 - sl_pct / 100.0))
                if cur_z < prev_z or is_stop_loss:
                    breakout_level = float(hhv_arr[i])
                    sell_sig[i] = True
                    in_pos = False
                    buy_price = 0.0
            # 空仓：波谷启动 或 突破前高回补
            elif not in_pos:
                if cur_z > prev_z:
                    breakout_level = 0.0
                    buy_sig[i] = True
                    in_pos = True
                    buy_price = cur_c
                elif breakout_level > 0:
                    threshold = breakout_level * (1.0 + conf_pct / 100.0)
                    if cur_c >= threshold:
                        breakout_level = 0.0
                        buy_sig[i] = True
                        in_pos = True
                        buy_price = cur_c
                        
        res["buy_signal"] = buy_sig
        res["sell_signal"] = sell_sig
        return res
