"""通达信均线四边形策略 (Moving Average Quadrilateral Strategy).

通达信指标公式源语:
------------------------
DD:=CURRBARSCOUNT, NODRAW;
MA5:=MA(C,5);
MA10:=MA(C,10);
MA20:=MA(C,20);
MA60:=MA(C,60);
P1:=CROSS(MA5,MA20);
D1:=REF(DD,BARSLAST(P1));
P2:=CROSS(MA5,MA60);
D2:=REF(DD,BARSLAST(P2));
P3:=CROSS(MA10,MA20);
D3:=REF(DD,BARSLAST(P3));
P4:=CROSS(MA10,MA60);
D4:=REF(DD,BARSLAST(P4));
XG: EXIST(P1,10) AND EXIST(P2,10) AND EXIST(P3,10) AND EXIST(P4,10) 
AND D1!=D2 AND D1!=D3 AND D1!=D4
AND D2!=D3 AND D2!=D4 AND D3!=D4;

战法机理:
------------------------
1. 短周期快速均线 (MA5, MA10) 由下至上加速穿越中长期生命均线 (MA20, MA60)。
2. 四次金叉:
   - P1: MA5 向上金叉 MA20 (短线突破中线)
   - P2: MA5 向上金叉 MA60 (短线突破长线生命线)
   - P3: MA10 向上金叉 MA20 (次短线确认突破中线)
   - P4: MA10 向上金叉 MA60 (次短线确认突破长线)
3. 且四次金叉在短周期 (默认 10 根 K 线) 内集中爆发，且发生在不同交易日 (D1!=D2!=D3!=D4)，
   在 K 线价格-时间二维平面形成具有四个独立时间顶点的“均线金叉封闭四边形”。
4. 这代表多头量能极速爆发，均线系统彻底由缠绕反转为多头排列发散，是胜率极高的右侧加速战法！
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from easy_tdx.strategies.base import BaseStrategy, Param
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import MA, CROSS


@register_strategy
class MAQuadrilateralStrategy(BaseStrategy):
    name = "ma_quadrilateral"
    display_name = "通达信均线四边形策略"
    category = "technical"
    description = "MA5与MA10相继向上金叉MA20与MA60，并在10日内形成四角各异的闭合四边形，捕捉四线共振主升浪起爆点。"

    params_list = [
        Param(
            "window",
            int,
            default=10,
            min_value=5,
            max_value=30,
            step=1,
            label="四边形跨度 (10)",
            description="四次金叉必须全部发生的最近K线周期窗口 (通达信默认 10 根K线)",
        ),
        Param(
            "stop_loss_pct",
            float,
            default=5.0,
            min_value=0.0,
            max_value=15.0,
            step=0.5,
            label="硬止损比例 (%)",
            description="跌破买入价此比例强制平仓止损（0 为不设硬止损）",
        ),
        Param(
            "take_profit_pct",
            float,
            default=15.0,
            min_value=0.0,
            max_value=50.0,
            step=1.0,
            label="目标止盈比例 (%)",
            description="达到此盈利幅度提前止盈离场（0 为仅由均线破位死叉卖出）",
        ),
        Param(
            "max_hold_bars",
            int,
            default=20,
            min_value=3,
            max_value=60,
            step=1,
            label="最大持仓周期 (20)",
            description="买入后最多持仓K线根数，超时主动平仓释放资金",
        ),
    ]
    params_schema = {
        "window": 10,
        "stop_loss_pct": 5.0,
        "take_profit_pct": 15.0,
        "max_hold_bars": 20,
    }

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        n = len(res)
        if n < 65:
            # 均线需至少 60 根数据计算 MA60
            res["buy_signal"] = False
            res["sell_signal"] = False
            res["xg"] = False
            return res

        window = int(self.params.get("window", 10))
        sl_pct = float(self.params.get("stop_loss_pct", 5.0))
        tp_pct = float(self.params.get("take_profit_pct", 15.0))
        max_hold = int(self.params.get("max_hold_bars", 20))

        c = res["close"].values
        ma5 = MA(c, 5)
        ma10 = MA(c, 10)
        ma20 = MA(c, 20)
        ma60 = MA(c, 60)

        # 四次金叉事件判断
        p1 = CROSS(ma5, ma20)   # P1: MA5 上穿 MA20
        p2 = CROSS(ma5, ma60)   # P2: MA5 上穿 MA60
        p3 = CROSS(ma10, ma20)  # P3: MA10 上穿 MA20
        p4 = CROSS(ma10, ma60)  # P4: MA10 上穿 MA60

        xg = np.zeros(n, dtype=bool)
        last_1 = -9999
        last_2 = -9999
        last_3 = -9999
        last_4 = -9999

        for i in range(n):
            if p1[i]:
                last_1 = i
            if p2[i]:
                last_2 = i
            if p3[i]:
                last_3 = i
            if p4[i]:
                last_4 = i

            # 对应通达信公式:
            # EXIST(P1,10) AND EXIST(P2,10) AND EXIST(P3,10) AND EXIST(P4,10)
            if (
                (i - last_1 < window)
                and (i - last_2 < window)
                and (i - last_3 < window)
                and (i - last_4 < window)
            ):
                # 对应通达信公式: D1!=D2 AND D1!=D3 AND D1!=D4 AND D2!=D3 AND D2!=D4 AND D3!=D4
                # 即四次金叉分别发生在4个不同的独立交易日，形成时空四边形闭合
                if len({last_1, last_2, last_3, last_4}) == 4:
                    xg[i] = True

        # 生成买卖交易信号
        buy_sig = np.zeros(n, dtype=bool)
        sell_sig = np.zeros(n, dtype=bool)
        in_pos = False
        buy_price = 0.0
        buy_idx = 0

        # 死叉破位: MA5 下穿 MA20 或收盘价跌破 MA20 趋势破位
        dead_cross = CROSS(ma20, ma5)

        for i in range(1, n):
            cur_c = float(c[i])

            if in_pos:
                # 卖出条件:
                # 1. 均线死叉破位
                is_dead = bool(dead_cross[i]) or (cur_c < ma20[i] * 0.98)
                # 2. 硬止损保护
                is_sl = (sl_pct > 0) and (cur_c < buy_price * (1.0 - sl_pct / 100.0))
                # 3. 目标止盈
                is_tp = (tp_pct > 0) and (cur_c >= buy_price * (1.0 + tp_pct / 100.0))
                # 4. 最大持仓期超时
                is_timeout = (max_hold > 0) and (i - buy_idx >= max_hold)

                if is_dead or is_sl or is_tp or is_timeout:
                    sell_sig[i] = True
                    in_pos = False
            else:
                # 买入条件: 四边形初次闭合达成起爆点 (XG 从 False 转为 True)
                if xg[i] and not xg[i - 1]:
                    buy_sig[i] = True
                    in_pos = True
                    buy_price = cur_c
                    buy_idx = i

        res["ma5"] = ma5
        res["ma10"] = ma10
        res["ma20"] = ma20
        res["ma60"] = ma60
        res["xg"] = xg
        res["buy_signal"] = buy_sig
        res["sell_signal"] = sell_sig
        return res
