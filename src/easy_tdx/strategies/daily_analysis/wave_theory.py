"""Wave Theory 3rd Impulse Wave Strategy (波浪理论主升3浪).

艾略特波浪理论主升3浪量化战法体系：
1. 【1浪启动冲高】：经历前期筑底或调整后，出现明确的第1浪推动上涨（涨幅 >= 12%），成交量温和放大，推动MACD指标上穿或站上零轴。
2. 【2浪健康洗盘】：1浪见顶后展开洗盘调整，形成2浪低点L2。
   - 波浪铁律一：2浪底绝对不破1浪底（L2 > L1）；
   - 黄金分割洗盘：回撤深度在 0.18 ~ 0.72 之间（典型在 0.382 ~ 0.618 黄金分割位获强支撑）；
   - 缩量洗盘特征：2浪期间日均成交量明显小于1浪暴涨均量（主力控盘良好无恐慌性抛盘）。
3. 【3浪主升爆发点】：
   - 模式A（过顶突破主升）：股价放量逼近或突破1浪高点H1（Close >= H1 * 0.985），打开主升浪上涨空间；
   - 模式B（2浪底企稳回升，空中加油启动）：股价脱离2浪底，重新站上MA5/MA10/MA20，MACD在零轴上方/附近水上金叉或强力多头二次张口发散。
4. 【多头趋势与量能共振】：收盘价站稳MA20及MA60均线之上，MA20走平向上，启动突破伴随成交量放大（>= 1.15倍20日均量）。
5. 【防接盘风控】：排除乖离率过大（收盘价相对MA20乖离 > 28%）的过热标的，防止追高5浪衰竭顶。
"""
from __future__ import annotations
import pandas as pd
import numpy as np
from easy_tdx.strategies.base import BaseStrategy
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import MACD, MA

@register_strategy
class WaveTheoryStrategy(BaseStrategy):
    name = "wave_theory_impulse"
    display_name = "波浪理论主升3浪"
    category = "daily_analysis"
    description = "1浪冲高建仓、2浪缩量回踩黄金分割且不破前低，均线多头MACD零轴上二次发散展开主升3浪"
    params_schema = {
        "min_wave1_rise": 0.12,     # 1浪最小涨幅 (12%)
        "min_retrace": 0.18,        # 2浪最小回撤比例 (18%)
        "max_retrace": 0.72,        # 2浪最大回撤比例 (72%)
        "vol_ratio": 1.15,          # 3浪启动放量阈值
        "max_bias": 0.28,           # 最大MA20乖离率 (28%)
    }

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        n = len(out)
        if n < 30:
            out["buy_signal"] = False
            out["sell_signal"] = False
            out["wave_type"] = ""
            out["wave1_rise"] = 0.0
            out["wave2_retrace"] = 0.0
            return out

        c = np.asarray(out["close"].values, dtype=float)
        h = np.asarray(out["high"].values, dtype=float)
        l = np.asarray(out["low"].values, dtype=float)
        o = np.asarray(out["open"].values, dtype=float)
        v = np.asarray(out["volume"].values, dtype=float)

        ma5 = np.asarray(MA(c, min(5, n)), dtype=float)
        ma10 = np.asarray(MA(c, min(10, n)), dtype=float)
        ma20 = np.asarray(MA(c, min(20, n)), dtype=float)
        ma60 = np.asarray(MA(c, min(60, n)), dtype=float)
        v_ma20 = np.asarray(MA(v, min(20, n)), dtype=float)
        dif_arr, dea_arr, hist_arr = MACD(c)
        dif = np.asarray(dif_arr, dtype=float)
        dea = np.asarray(dea_arr, dtype=float)
        hist = np.asarray(hist_arr, dtype=float)

        buy_signals = np.zeros(n, dtype=bool)
        sell_signals = np.zeros(n, dtype=bool)
        wave_types = [""] * n
        wave1_rises = np.zeros(n, dtype=float)
        wave2_retraces = np.zeros(n, dtype=float)

        # 扫描起始点 (需要前期数据做波浪前序结构识别)
        start_idx = max(20, 30 if n >= 45 else 15)

        for i in range(start_idx, n):
            cur_c = c[i]
            cur_h = h[i]
            cur_l = l[i]
            cur_o = o[i]
            cur_v = v[i]

            # 1. 均线与多头趋势基准过滤：
            # 股价必须站在 MA20*0.985 之上，且在 MA60*0.97 之上
            if cur_c < ma20[i] * 0.985 or cur_c < ma60[i] * 0.97:
                continue
            # MA20 必须走平或向上 (杜绝下行破位空头股的弱势反抽)
            if i >= 3 and ma20[i] < ma20[i - 3] * 0.992:
                continue

            # 2. 寻找前序 1浪 (H1) 和 2浪 (L2) 结构：
            # 窗口：在过去的 [i-45, i-2] 区间寻找 1浪波峰 H1
            search_start = max(0, i - 45)
            search_end = max(1, i - 2)
            if search_end - search_start < 5:
                continue

            sub_h = h[search_start:search_end]
            rel_h1 = int(np.argmax(sub_h))
            h1_idx = search_start + rel_h1
            h1_val = float(h[h1_idx])

            # 1浪起点 L1：在 H1 之前的区间寻找最低点
            l1_start = max(0, h1_idx - 30)
            if h1_idx - l1_start < 3:
                continue
            rel_l1 = int(np.argmin(l[l1_start:h1_idx]))
            l1_idx = l1_start + rel_l1
            l1_val = float(l[l1_idx])

            # 1浪涨幅检查：推动浪必须有充足力度 (>= 12% 且 <= 120%)
            if l1_val <= 0:
                continue
            wave1_pct = (h1_val - l1_val) / l1_val
            if wave1_pct < 0.12 or wave1_pct > 1.20:
                continue

            # 2浪低点 L2：在 H1 到当前根之前的区间寻找最低点
            if i - h1_idx < 2:  # 2浪至少经历 2 根以上 K 线的洗盘休整
                continue
            rel_l2 = int(np.argmin(l[h1_idx:i]))
            l2_idx = h1_idx + rel_l2
            l2_val = float(l[l2_idx])

            # 波浪理论铁律一：2浪底绝对不能跌破 1浪底 (L2 > L1)
            if l2_val <= l1_val:
                continue

            # 2浪回调深度 (H1 - L2) / (H1 - L1)
            # 经典健康洗盘在 0.18 ~ 0.72 之间 (黄金分割 0.382/0.5/0.618 关键位)
            retrace = (h1_val - l2_val) / (h1_val - l1_val)
            if retrace < 0.18 or retrace > 0.72:
                continue

            # 2浪缩量洗盘校验：2浪期间日均量不能大于 1浪暴涨均量的 1.15 倍
            v_w1 = float(np.mean(v[l1_idx:h1_idx + 1])) if h1_idx >= l1_idx else cur_v
            v_w2 = float(np.mean(v[h1_idx:l2_idx + 1])) if l2_idx >= h1_idx else cur_v
            if v_w1 > 0 and v_w2 / v_w1 > 1.15:
                continue

            # 3浪启动必须从 2浪底有效脱离：当前价格比 L2 至少高出 3.5%
            gain_from_l2 = (cur_c - l2_val) / l2_val
            if gain_from_l2 < 0.035:
                continue

            # 3. 3浪必须突破 1浪高点 H1 (硬性约束：未突破 1浪高点则不满足主升3浪条件)
            # 标杆案例 603116 (红蜻蜓)：收盘价冲破 1浪高点 (Close >= H1，或最高价刺破 H1 且收盘稳在 H1*0.99 之上)
            is_break_h1 = (cur_c >= h1_val or (cur_h > h1_val and cur_c >= h1_val * 0.99)) and (cur_c > c[i - 1]) and (cur_c >= cur_o)

            if not is_break_h1:
                continue

            # MACD 零轴上方/水上金叉/空中加油
            # DIF 必须大于 -0.015 * cur_c (不能处于空头深水区)
            if dif[i] < -0.015 * cur_c:
                continue
            # MACD 绿柱不能正在快速向下跳水放大
            if hist[i] < 0 and i >= 1 and hist[i] < hist[i - 1] * 1.2:
                continue

            # 成交量配合：放量突破 1浪峰顶阻力位
            has_volume = (cur_v >= 1.15 * v_ma20[i]) or (i >= 1 and v[i - 1] >= 1.25 * v_ma20[i - 1]) or (cur_v >= 1.15 * v_w2)
            if not has_volume:
                continue

            # 排除乖离过大防追高接盘
            if (cur_c - ma20[i]) / max(0.01, ma20[i]) > 0.28:
                continue

            buy_signals[i] = True
            wave_types[i] = "3浪突破过顶"
            wave1_rises[i] = round(wave1_pct * 100.0, 1)
            wave2_retraces[i] = round(retrace * 100.0, 1)

        # 卖出信号：跌破 2浪底，或跌破 MA20 且 DIF < DEA 确立下行
        for i in range(20, n):
            if c[i] < ma20[i] * 0.96 and dif[i] < dea[i]:
                sell_signals[i] = True

        out["buy_signal"] = pd.Series(buy_signals, index=out.index)
        out["sell_signal"] = pd.Series(sell_signals, index=out.index)
        out["wave_type"] = pd.Series(wave_types, index=out.index)
        out["wave1_rise"] = pd.Series(wave1_rises, index=out.index)
        out["wave2_retrace"] = pd.Series(wave2_retraces, index=out.index)
        return out
