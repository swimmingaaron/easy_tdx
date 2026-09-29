"""通达信均线四边形策略 (Moving Average Quadrilateral Strategy) - 优化增强版.

通达信指标公式源语:
------------------------
MA5:=MA(C,5);
MA10:=MA(C,10);
MA20:=MA(C,20);
MA60:=MA(C,60);

MM:=MIN(MA5,MA60);
MM2:=MIN(MA10,MA60);
SS:DRAWBAND(MM,RGB(250,0,250),MM2,0 );

HM:=MAX(MA5,MA60);
HM2:=MAX(MA10,MA60);
{DRAWBAND(HM2,RGB(0,255,190),HM,0);}

DRAWKLINE(HIGH,OPEN,LOW,CLOSE);

KK:=MIN(MA5,MA20);
KK2:=MIN(MA10,MA20);
DRAWBAND(KK,RGB(0,255,190),KK2,0);

选股公式源语:
------------------------
DD:=CURRBARSCOUNT, NODRAW;
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

四边形擒牛技巧核心精要:
------------------------
1. 图形结构：由 5、10、20、60 日均线围成一个几何四边形（近似于平行四边形），形状越规则越好。
2. 均线要求：四边形的左边为 5日线，右边为 10日线，下边为 20日线，上边为 60日线。均线系统呈多头排列或者由下跌开始走平。
3. 买入位置：四边形形成后，等股价回踩 10日线、20日线、60日线均可抢筹！也有的沿 5日线强势上涨一时不回调（游资大单涨停抢筹横扫千军）。
4. 图形原理：机构在低位拉高建仓时留下的量价时空闭合轨迹。
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
    description = "MA5与MA10相继向上金叉MA20与MA60闭合成规则四边形，支持沿5日线主升强攻与回踩10/20/60日线抢筹多点位擒牛。"

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
            "pullback_window",
            int,
            default=8,
            min_value=3,
            max_value=15,
            step=1,
            label="回踩观察窗口 (8)",
            description="四边形闭合后持续寻找回踩10/20/60日均线低吸买点的K线周期",
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
        "pullback_window": 8,
        "stop_loss_pct": 5.0,
        "take_profit_pct": 15.0,
        "max_hold_bars": 20,
    }

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        n = len(res)
        if n < 65:
            res["buy_signal"] = False
            res["sell_signal"] = False
            res["xg"] = False
            res["quad_buy_type"] = ""
            res["quad_regularity"] = 0.0
            return res

        window = int(self.params.get("window", 10))
        pullback_window = int(self.params.get("pullback_window", 8))
        sl_pct = float(self.params.get("stop_loss_pct", 5.0))
        tp_pct = float(self.params.get("take_profit_pct", 15.0))
        max_hold = int(self.params.get("max_hold_bars", 20))

        c = res["close"].values
        h = res["high"].values
        l = res["low"].values

        ma5 = MA(c, 5)
        ma10 = MA(c, 10)
        ma20 = MA(c, 20)
        ma60 = MA(c, 60)

        # 1. 通达信色带指标计算 (DRAWBAND)
        band_mm = np.minimum(ma5, ma60)
        band_mm2 = np.minimum(ma10, ma60)
        band_kk = np.minimum(ma5, ma20)
        band_kk2 = np.minimum(ma10, ma20)

        # 2. 四次金叉事件
        # P1: 5日线上穿20日线 (左下角)
        # P2: 5日线上穿60日线 (左上角)
        # P3: 10日线上穿20日线 (右下角)
        # P4: 10日线上穿60日线 (右上角)
        p1 = CROSS(ma5, ma20)
        p2 = CROSS(ma5, ma60)
        p3 = CROSS(ma10, ma20)
        p4 = CROSS(ma10, ma60)

        xg = np.zeros(n, dtype=bool)
        quad_regularity = np.zeros(n, dtype=float)
        quad_buy_types = ["" for _ in range(n)]

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

            # 通达信核心条件:
            # EXIST(P1,10) AND EXIST(P2,10) AND EXIST(P3,10) AND EXIST(P4,10)
            if (
                (i - last_1 < window)
                and (i - last_2 < window)
                and (i - last_3 < window)
                and (i - last_4 < window)
            ):
                # 互异性条件: D1!=D2 AND D1!=D3 AND D1!=D4 AND D2!=D3 AND D2!=D4 AND D3!=D4
                if len({last_1, last_2, last_3, last_4}) == 4:
                    # 严格符合“四边形擒牛技巧”空间几何拓扑结构:
                    # 1. 左边为5日线，右边为10日线: 5日线金叉先于10日线金叉 (last_1 < last_3 且 last_2 < last_4)
                    # 2. 下边为20日线，上边为60日线: 先金叉下边20日线，再金叉上边60日线 (last_1 <= last_2 且 last_3 <= last_4)
                    # 3. 几何高度真实存在: 在形成期间 MA60 位于 MA20 上方构成上下边界
                    geo_order_ok = (last_1 < last_3) and (last_2 < last_4) and (last_1 <= last_2) and (last_3 <= last_4)
                    height_ok = (ma60[i] >= ma20[i] * 1.001)

                    # 4. 均线系统呈多头排列或者由下跌开始走平 (MA20和MA60不加速深跌)
                    ma20_slope_ok = (i < 3) or (ma20[i] >= ma20[i - 3] * 0.985)
                    ma60_slope_ok = (i < 5) or (ma60[i] >= ma60[i - 5] * 0.985)

                    if geo_order_ok and height_ok and ma20_slope_ok and ma60_slope_ok:
                        xg[i] = True

                        # 计算四边形规则度 (近似平行四边形评分，满分 100 分):
                        # 底边跨度: |last_3 - last_1| (MA10穿MA20 与 MA5穿MA20 的时间差)
                        # 顶边跨度: |last_4 - last_2| (MA10穿MA60 与 MA5穿MA60 的时间差)
                        dt_bottom = abs(last_3 - last_1)
                        dt_top = abs(last_4 - last_2)
                        span_diff = abs(dt_bottom - dt_top)
                        
                        score = max(50.0, 95.0 - span_diff * 8.0)
                        if ma5[i] >= ma10[i]:
                            score = min(100.0, score + 5.0)
                        quad_regularity[i] = round(score, 1)

        # 3. 买卖交易信号与擒牛买点类型生成
        buy_sig = np.zeros(n, dtype=bool)
        sell_sig = np.zeros(n, dtype=bool)
        in_pos = False
        buy_price = 0.0
        buy_idx = 0
        last_formed_bar = -9999

        # 死叉破位: MA5 下穿 MA20 或收盘跌破 MA20 趋势破位
        dead_cross = CROSS(ma20, ma5)

        for i in range(1, n):
            cur_c = float(c[i])
            cur_l = float(l[i])
            cur_h = float(h[i])
            cur_ma5 = float(ma5[i])
            cur_ma10 = float(ma10[i])
            cur_ma20 = float(ma20[i])
            cur_ma60 = float(ma60[i])

            if xg[i] and not xg[i - 1]:
                last_formed_bar = i

            if in_pos:
                # 卖出条件:
                # 1. 均线死叉破位
                is_dead = bool(dead_cross[i]) or (cur_c < cur_ma20 * 0.975)
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
                # 寻找四边形买入点:
                # 条件 A: 四边形刚闭合 (xg[i] and not xg[i-1])
                # 条件 B: 四边形形成后 pullback_window 内，股价回踩 10日线/20日线/60日线抢筹，或沿5日线强势加速
                is_within_watch = (i - last_formed_bar <= pullback_window) and (last_formed_bar > 0)

                trigger_buy = False
                buy_type = ""

                if xg[i] and not xg[i - 1]:
                    # 刚闭合当日：
                    if cur_c >= cur_ma5 * 0.995 and cur_ma5 >= cur_ma10:
                        trigger_buy = True
                        buy_type = "沿5日线强攻"
                    else:
                        trigger_buy = True
                        buy_type = "闭合加速"
                elif is_within_watch:
                    # 形成后的后续交易日内回踩低吸机会:
                    # 1. 沿5日线强势不回调
                    if cur_l >= cur_ma5 * 0.99 and cur_c > cur_ma5 and cur_ma5 > cur_ma10:
                        trigger_buy = True
                        buy_type = "沿5日线强攻"
                    # 2. 回踩10日线抢筹 (探到10日线附近且收盘守住10日线)
                    elif cur_l <= cur_ma10 * 1.015 and cur_c >= cur_ma10 * 0.985:
                        trigger_buy = True
                        buy_type = "回踩10日线"
                    # 3. 回踩20日线抢筹 (下探20日月线强支撑)
                    elif cur_l <= cur_ma20 * 1.015 and cur_c >= cur_ma20 * 0.985:
                        trigger_buy = True
                        buy_type = "回踩20日线"
                    # 4. 回踩60日线抢筹 (下探60日季线支撑)
                    elif cur_l <= cur_ma60 * 1.015 and cur_c >= cur_ma60 * 0.985:
                        trigger_buy = True
                        buy_type = "回踩60日线"

                if trigger_buy:
                    buy_sig[i] = True
                    in_pos = True
                    buy_price = cur_c
                    buy_idx = i
                    quad_buy_types[i] = buy_type
                    # 继承形成日的四边形规则度
                    if quad_regularity[i] == 0.0 and last_formed_bar >= 0:
                        quad_regularity[i] = quad_regularity[last_formed_bar]

        res["ma5"] = ma5
        res["ma10"] = ma10
        res["ma20"] = ma20
        res["ma60"] = ma60

        # 通达信绘图色带列 (DRAWBAND)
        res["band_mm"] = band_mm
        res["band_mm2"] = band_mm2
        res["band_kk"] = band_kk
        res["band_kk2"] = band_kk2

        res["xg"] = xg
        res["quad_regularity"] = quad_regularity
        res["quad_buy_type"] = quad_buy_types
        res["buy_signal"] = buy_sig
        res["sell_signal"] = sell_sig
        return res
