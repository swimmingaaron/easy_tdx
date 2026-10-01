"""通达信均线四边形策略 (Moving Average Quadrilateral Strategy) - 擒牛实战与指标共振优化版.

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
{ P3、P4 交叉点收盘价不能低于 MA60 }
C3_OK:=REF(C>=MA60*0.995,BARSLAST(P3));
C4_OK:=REF(C>=MA60*0.995,BARSLAST(P4));
XG: EXIST(P1,10) AND EXIST(P2,10) AND EXIST(P3,10) AND EXIST(P4,10) 
AND D1!=D2 AND D1!=D3 AND D1!=D4
AND D2!=D3 AND D2!=D4 AND D3!=D4
AND C3_OK AND C4_OK;

四边形擒牛实战图解与深度量化优化精要:
----------------------------------------
1. 图形结构与时序拓扑：
   - 5、10、20、60日均线在低位围成规则的几何四边形。
   - 左边为 5日线(白线)，右边为 10日线(黄线)，下边为 20日线(紫线)，上边为 60日线(绿线)。
   - 突破进攻时，允许 MA5 同日上穿 MA20与MA60，或 MA10 同日上穿 MA20与MA60（大阳线强力起爆一穿二）。
   - 【关键铁律】：P3(10日线上穿20日线) 与 P4(10日线上穿60日线) 交叉发生当日，收盘价绝对不能低于生命线 MA60，坚决排除右侧在生命线下方弱势缠绕的假突破。
2. 生命线 MA60 与中线 MA20 趋势铁律：
   - 成功案例的收盘价必须突破并站在 MA60 之上，彻底摆脱 60日生命线压制；
   - MA60 必须止跌走平或向上拐头（坚决排除 MA60 呈陡峭下行压制走势的假突破诱多反弹）；
   - MA20 必须走平或向上翘起，并在四边形闭合后配合向上金叉 MA60 构筑大级别多头全排列。
3. 辅助指标多头共振把关：
   - KDJ 过滤：买入点与闭合确认时，KDJ_J 必须 >= 50（坚决一票否决高位死叉崩落、J值跌破50甚至击穿20的衰竭形态）；
   - RSI 过滤：6日 RSI 必须 >= 50 处于多头强弱分水岭上方；
   - MACD 过滤：拒绝处于水下深度死叉恶性区间。
4. 空中加油与买入位置：
   - 【位置 A·闭合加速】：四边形闭合首日大阳线脱离成本区。
   - 【位置 B·回踩10日线抢筹】：在 MA60 上方强势横盘，盘中回踩 10日线抢筹且收盘不破（实战典型）。
   - 【位置 C·空中加油二次起爆】：在 10日线确认支撑后放量长阳突破横盘平台，展开第二波主升浪！
   - 【位置 D·沿5日线强攻 / 回踩20/60日线】：极强连板推升或波段深度回踩中长线支撑低吸。
5. 底价锚定：记录四边形起爆前阶段最低价，作为防守基准与空间测算锚。
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from easy_tdx.strategies.base import BaseStrategy, Param
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import MA, CROSS, KDJ, MACD, RSI


@register_strategy
class MAQuadrilateralStrategy(BaseStrategy):
    name = "ma_quadrilateral"
    display_name = "通达信均线四边形策略"
    category = "technical"
    description = "MA5与MA10相继向上金叉MA20与MA60闭合成规则四边形，支持底价锚定、MA60上方空中加油回踩10日线抢筹与二次起爆擒牛。"

    params_list = [
        Param(
            "window",
            int,
            default=10,
            min_value=5,
            max_value=30,
            step=1,
            label="四边形跨度 (10)",
            description="四次金叉必须全部发生的最近K线周期窗口 (默认 10 根K线)",
        ),
        Param(
            "pullback_window",
            int,
            default=12,
            min_value=3,
            max_value=20,
            step=1,
            label="回踩观察窗口 (12)",
            description="四边形闭合后持续寻找回踩10/20/60日均线抢筹与空中加油二次起爆买点的K线周期",
        ),
        Param(
            "require_ma60_support",
            bool,
            default=True,
            label="生命线MA60趋势过滤",
            description="要求收盘价站稳MA60之上，且MA60止跌走平或上翘，彻底过滤中长期均线下压假反弹",
        ),
        Param(
            "require_indicator_resonance",
            bool,
            default=True,
            label="动能指标共振过滤",
            description="结合KDJ(J>=50)、RSI(6>=50)与MACD共振过滤，坚决剔除高位死叉断头及动能衰竭案例",
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
            default=20.0,
            min_value=0.0,
            max_value=50.0,
            step=1.0,
            label="目标止盈比例 (%)",
            description="达到此盈利幅度提前止盈离场（0 为仅由均线破位死叉卖出）",
        ),
        Param(
            "no_candle_in_quad",
            bool,
            default=True,
            label="四边形内无K线",
            description="四边形形成区域内严禁有蜡烛图穿越（实体、上影线、下影线均不得进入四边形内部）",
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
        "pullback_window": 12,
        "require_ma60_support": True,
        "require_indicator_resonance": True,
        "no_candle_in_quad": True,
        "stop_loss_pct": 5.0,
        "take_profit_pct": 20.0,
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
            res["quad_bottom_price"] = 0.0
            return res

        window = int(self.params.get("window", 10))
        pullback_window = int(self.params.get("pullback_window", 12))
        req_ma60 = bool(self.params.get("require_ma60_support", True))
        req_ind = bool(self.params.get("require_indicator_resonance", True))
        no_candle_req = bool(self.params.get("no_candle_in_quad", True))
        sl_pct = float(self.params.get("stop_loss_pct", 5.0))
        tp_pct = float(self.params.get("take_profit_pct", 20.0))
        max_hold = int(self.params.get("max_hold_bars", 20))

        c = res["close"].values
        h = res["high"].values
        l = res["low"].values
        o = res["open"].values if "open" in res.columns else c

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

        # 辅助动能指标预计算
        dif, dea, macd_bar = MACD(c, 12, 26, 9)
        k_val, d_val, j_val = KDJ(c, h, l, 9, 3, 3)
        rsi6_val = RSI(c, 6)

        xg = np.zeros(n, dtype=bool)
        quad_regularity = np.zeros(n, dtype=float)
        quad_bottom_price = np.zeros(n, dtype=float)
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
            # EXIST(P1,window) AND EXIST(P2,window) AND EXIST(P3,window) AND EXIST(P4,window)
            if (
                (i - last_1 < window)
                and (i - last_2 < window)
                and (i - last_3 < window)
                and (i - last_4 < window)
            ):
                # 空间几何拓扑结构校验:
                # 1. 均线时序顺畅: MA5 金叉必须先于或同步于 MA10 (last_1 <= last_3 且 last_2 <= last_4)
                #    且由下至上穿越逻辑顺畅，杜绝逆向严重时间倒挂 (last_1 - last_2 <= 2 且 last_3 - last_4 <= 2)
                geo_order_ok = (
                    (last_1 <= last_3)
                    and (last_2 <= last_4)
                    and (last_1 - last_2 <= 2)
                    and (last_3 - last_4 <= 2)
                )

                # 2. 通达信原版非退化四边形约束 (D2!=D4 且 D1!=D3):
                #    5日线与10日线上穿60日线不可在同日发生(顶边退化)，上穿20日线亦不可在同日发生(底边退化)
                no_degenerate = (last_2 != last_4) and (last_1 != last_3)
                not_all_same = not (last_1 == last_2 == last_3 == last_4) and no_degenerate

                # 3. 底边与顶边稳定性: 坚决排除如 600233 这类 20日线暴跌死叉下穿 60日线的下坠倒挂形态
                # 若 20日线在金叉前5日高于60日线且当前跌破60日线且斜率为负，属于跳水死叉
                is_plunging_dead_cross = (
                    (last_1 >= 5)
                    and (ma20[last_1 - 5] > ma60[last_1 - 5])
                    and (ma20[last_1] < ma60[last_1])
                    and (ma20[last_1] < ma20[last_1 - 5] * 0.99)
                )
                base_stable = not is_plunging_dead_cross

                # 4. MA20 趋势过滤: MA20 跌势完全止住 (走平或微翘)
                ma20_slope_ok = (i < 3) or (ma20[i] >= ma20[i - 3] * 0.992)
                ma20_slope_p1 = (last_1 < 5) or (ma20[last_1] >= ma20[last_1 - 5] * 0.980)

                # 5. 生命线 MA60 与收盘价位置过滤 (关键分水岭)
                ma60_val = ma60[i]
                cur_c = c[i]
                if req_ma60:
                    ma60_ref10 = ma60[max(0, i - 10)]
                    ma60_slope_10d = (ma60_val - ma60_ref10) / ma60_ref10 * 100
                    if ma60_slope_10d >= -1.0:
                        # 正常企稳上翘形态: 要求收盘价站稳 MA60 附近或上方
                        ma60_filter_ok = cur_c >= ma60_val * 0.99
                    else:
                        # MA60 仍在下倾: 要求收盘价强力大阳突破 MA60 (+3%以上) 且 J值极强
                        ma60_filter_ok = (ma60_slope_10d >= -3.5) and (cur_c >= ma60_val * 1.03) and (j_val[i] >= 70.0)
                else:
                    ma60_filter_ok = True

                # 6. 辅助动能指标多头共振 (坚决过滤 KDJ 高位死叉、J<50 及 RSI<50 弱势跳水案例)
                if req_ind:
                    kdj_ok = j_val[i] >= 48.0
                    rsi_ok = rsi6_val[i] >= 48.0
                    macd_ok = (dif[i] >= -0.3) and not (dif[i] < dea[i] and dif[i] < 0)
                    resonance_ok = kdj_ok and rsi_ok and macd_ok
                else:
                    resonance_ok = True

                # 7. 四边形区域蜡烛图侵入检测 (实体深入或深影线刺穿严禁进入四边形腹地)
                no_candle_inside = True
                if no_candle_req:
                    quad_start = min(last_1, last_2, last_3, last_4)
                    for k in range(quad_start + 1, i + 1):
                        y_top = min(ma5[k], ma60[k])
                        y_bot = max(ma10[k], ma20[k])
                        if y_top > y_bot:
                            # 实体直接收在四边形内部，或实体深幅陷在四边形中
                            body_inside = (c[k] < y_top and c[k] > y_bot) or (
                                min(o[k], c[k]) < y_top * 0.985 and max(o[k], c[k]) > y_bot and c[k] < y_top
                            )
                            # 影线自上方深探穿入四边形腹地
                            shadow_penetrate = (l[k] < y_top * 0.985) and (h[k] > y_top) and (l[k] > y_bot * 0.98)
                            if body_inside or shadow_penetrate:
                                no_candle_inside = False
                                break

                # 8. P3 与 P4 交叉点收盘价硬约束:
                #    P3(10日线上穿20日线) 与 P4(10日线上穿60日线) 交叉发生当日，收盘价均不能低于生命线 MA60
                p3_c_ok = (last_3 >= 0) and (c[last_3] >= ma60[last_3] * 0.995)
                p4_c_ok = (last_4 >= 0) and (c[last_4] >= ma60[last_4] * 0.995)
                p3_p4_above_ma60 = p3_c_ok and p4_c_ok

                if (
                    geo_order_ok
                    and not_all_same
                    and base_stable
                    and ma20_slope_p1
                    and ma20_slope_ok
                    and ma60_filter_ok
                    and resonance_ok
                    and no_candle_inside
                    and p3_p4_above_ma60
                ):
                    xg[i] = True

                    # 计算四边形规则度 (近似平行四边形评分，满分 100 分)
                    dt_bottom = abs(last_3 - last_1)
                    dt_top = abs(last_4 - last_2)
                    span_diff = abs(dt_bottom - dt_top)
                    score = max(50.0, 95.0 - span_diff * 6.0)
                    if ma5[i] >= ma10[i]:
                        score = min(100.0, score + 5.0)
                    quad_regularity[i] = round(score, 1)

                    # 记录起爆底价
                    lookback_start = max(0, min(last_1, last_2, last_3, last_4) - 8)
                    bot_val = float(np.min(l[lookback_start : i + 1]))
                    quad_bottom_price[i] = round(bot_val, 2)

        # 3. 买卖交易信号与图解买点精确定位
        buy_sig = np.zeros(n, dtype=bool)
        sell_sig = np.zeros(n, dtype=bool)
        in_pos = False
        buy_price = 0.0
        buy_idx = 0
        last_formed_bar = -9999
        tested_ma10 = False

        # 死叉破位: MA5 下穿 MA20 且收盘跌破 MA20 趋势破位
        dead_cross = CROSS(ma20, ma5)

        for i in range(1, n):
            cur_c = float(c[i])
            cur_o = float(o[i])
            cur_l = float(l[i])
            cur_h = float(h[i])
            cur_ma5 = float(ma5[i])
            cur_ma10 = float(ma10[i])
            cur_ma20 = float(ma20[i])
            cur_ma60 = float(ma60[i])

            if xg[i] and not xg[i - 1]:
                last_formed_bar = i
                tested_ma10 = False

            if in_pos:
                # 卖出条件:
                # 1. 均线死叉且破位
                is_dead = (bool(dead_cross[i]) and cur_c < cur_ma20) or (cur_c < cur_ma20 * 0.96)
                # 2. 硬止损保护
                is_sl = (sl_pct > 0) and (cur_c < buy_price * (1.0 - sl_pct / 100.0))
                # 3. 目标止盈
                is_tp = (tp_pct > 0) and (cur_c >= buy_price * (1.0 + tp_pct / 100.0))
                # 4. 最大持仓期超时
                is_timeout = (max_hold > 0) and (i - buy_idx >= max_hold)

                if is_dead or is_sl or is_tp or is_timeout:
                    sell_sig[i] = True
                    in_pos = False
                    tested_ma10 = False
                    # 若因死叉或硬止损出局，说明四边形支撑已被有效打穿，熔断形态生命周期
                    if is_dead or is_sl:
                        last_formed_bar = -9999
            else:
                is_within_watch = (i - last_formed_bar <= pullback_window) and (last_formed_bar > 0)
                trigger_buy = False
                buy_type = ""

                # 是否处于 MA60 上方强势运行 (空中加油平台特征)
                is_above_ma60 = (cur_c >= cur_ma60 * 0.985) and (cur_l >= cur_ma60 * 0.97)

                # 辅助动能确认: 买入时 J>=50, RSI6>=50
                momentum_ok = (j_val[i] >= 48.0) and (rsi6_val[i] >= 48.0)

                # 严格空中加油与健康回踩确认:
                # 1. 短期均线不可死叉倒挂: MA5 必须在 MA10 上方 (cur_ma5 >= cur_ma10 * 0.995)
                # 2. 四边形闭合以来，从未破位跌穿 MA20 防守线
                c_since = c[last_formed_bar : i + 1] if last_formed_bar > 0 else []
                ma20_since = ma20[last_formed_bar : i + 1] if last_formed_bar > 0 else []
                never_broke_ma20 = len(c_since) > 0 and bool(np.all(c_since >= ma20_since * 0.985))
                ma5_above_ma10 = cur_ma5 >= cur_ma10 * 0.995
                pullback_valid = is_within_watch and momentum_ok and ma5_above_ma10 and never_broke_ma20

                if xg[i] and not xg[i - 1]:
                    # 刚闭合当日突破: 必须保持主动进攻姿态
                    if cur_c >= cur_ma5 * 0.99 and cur_ma5 >= cur_ma10:
                        trigger_buy = True
                        buy_type = "沿5日线强攻"
                    elif cur_c >= cur_ma10:
                        trigger_buy = True
                        buy_type = "闭合加速"
                elif pullback_valid:
                    # 实战图解重点形态：
                    # 1. 【回踩10日线抢筹】(图中洗盘K线低点精准触碰黄色10日线，收盘守住10日线)
                    if cur_l <= cur_ma10 * 1.02 and cur_c >= cur_ma10 * 0.985 and is_above_ma60:
                        trigger_buy = True
                        tested_ma10 = True
                        has_lower_shadow = (cur_c - cur_l) >= (cur_h - cur_l) * 0.35 or (cur_c >= cur_o)
                        buy_type = "回踩10日线抢筹" if has_lower_shadow else "回踩10日线"

                    # 2. 【空中加油二次起爆】(在确认10日线支撑后，长阳突破平台高点展开第二波主升浪)
                    elif tested_ma10 and (cur_c > cur_ma5) and (cur_c > float(c[i - 1])) and is_above_ma60:
                        trigger_buy = True
                        buy_type = "空中加油二次起爆"

                    # 3. 【沿5日线强势不回调】(极度强势连板攻坚)
                    elif cur_l >= cur_ma5 * 0.99 and cur_c > cur_ma5 and cur_ma5 > cur_ma10:
                        trigger_buy = True
                        buy_type = "沿5日线强攻"

                    # 4. 【回踩20日线强支撑抢筹】
                    elif cur_l <= cur_ma20 * 1.02 and cur_c >= cur_ma20 * 0.985:
                        trigger_buy = True
                        buy_type = "回踩20日线"

                    # 5. 【回踩60日线季线支撑】
                    elif cur_l <= cur_ma60 * 1.02 and cur_c >= cur_ma60 * 0.985:
                        trigger_buy = True
                        buy_type = "回踩60日线"

                if trigger_buy:
                    buy_sig[i] = True
                    in_pos = True
                    buy_price = cur_c
                    buy_idx = i
                    quad_buy_types[i] = buy_type
                    # 继承形成日的四边形规则度与起爆底价
                    if quad_regularity[i] == 0.0 and last_formed_bar >= 0:
                        quad_regularity[i] = quad_regularity[last_formed_bar]
                    if quad_bottom_price[i] == 0.0 and last_formed_bar >= 0:
                        quad_bottom_price[i] = quad_bottom_price[last_formed_bar]

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
        res["quad_bottom_price"] = quad_bottom_price
        res["quad_buy_type"] = quad_buy_types
        res["buy_signal"] = buy_sig
        res["sell_signal"] = sell_sig
        return res
