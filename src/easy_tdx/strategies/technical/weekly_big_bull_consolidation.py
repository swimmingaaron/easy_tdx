"""通信达上涨旗形策略 (Weekly Bull Flag Strategy).

经典上涨旗形 (Bull Flag) 深度量化模型与形态拓扑:
------------------------------------------------------------------------
上涨旗形是技术分析中爆发力最强、胜率最高的主升浪中继形态之一。
在周线级别，由「坚挺旗杆 (Flagpole)」与「紧凑旗面 (Flag Body)」组成：

       │                     突破旗面上沿起爆点 (主升浪第二波爆发)
       │                        ▲
       │        旗面紧凑缩量    ╱
       │        ┌──┐┌──┐┌──┐  ╱
       │        │  ││  ││  │ ╱
       │   ─────┴──┴──┴──┴──┘  ◄── 旗面承托防守线 (不破旗杆50%腰线)
       │  ▲
       │  │ 旗杆 (Flagpole): 前期超跌>20%后的突破大阳线 (+7%以上放量长阳)
       │  ▼
       └─────────────────────────

核心量化特征:
1. 旗杆拔起 (Flagpole): 前期波段下跌超 20%，单周收出 >= 7% 的放量突破大阳线，确立旗杆。
2. 旗面高位承托 (Retracement Defense):
   - 旗面整理期间各周收盘价与最低价必须承托在旗杆实体中轴 (50% 分位) 及开盘价之上，重心极度坚挺；
3. 旗面基准稳定性 (Benchmark Stability):
   - 以大阳后第一根交易周的收盘价为旗面价格中枢，横盘期间各周涨跌幅偏离严格控制在 ±3% 以内；
   - 排除单周跌幅大于 3% 的长阴砸盘；
4. 旗面阶梯缩量 (Volume Contraction):
   - 旗杆放量，旗面持续显著缩量 (成交量缩减 30%~70%)，表明浮筹洗净、筹码高度惜售锁定；
5. 旗形突破起爆 (Breakout Launch):
   - 旗面蓄势 2 ~ 6 周，在旗面末期低吸潜伏，或放量突破旗面上沿时追击展开第二波等长主升浪！

通达信选股公式代码 (周期选择：周线):
------------------------------------------------------------------------
{ 1. 旗杆确立：前期波段跌幅超20%，单周收出7%以上大阳线 }
BIG_BULL := C > O AND (C - REF(C, 1)) / REF(C, 1) >= 0.07;
PRIOR_HHV := REF(HHV(H, 20), 1);
PRIOR_LLV := REF(LLV(L, 20), 1);
PRIOR_DROP := (PRIOR_HHV - PRIOR_LLV) / PRIOR_HHV >= 0.20;
FLAGPOLE := BIG_BULL AND PRIOR_DROP;

{ 2. 旗面时间跨度：大阳线之后连续横盘 2 ~ 6 周 }
N := BARSLAST(FLAGPOLE);
FLAG_TIME := N >= 2 AND N <= 6;

{ 3. 旗面基准日：以大阳之后的第一根交易周收盘价为基准 }
BASE_C := REF(C, N - 1);

{ 4. 旗面价格通道：各周期相对基准涨跌幅不超过 ±3% (绝对偏离 <= 3%) }
FLAG_CHANNEL := HHV(C, N) <= BASE_C * 1.03 AND LLV(C, N) >= BASE_C * 0.97;

{ 5. 旗杆腰线承托：旗面最低价不破旗杆实体50%中轴与大阳低点，且单周跌幅不破3% }
POLE_MID := (REF(O, N) + REF(C, N)) * 0.50;
POLE_DEFENSE := LLV(L, N) >= MIN(POLE_MID, REF(L, N) * 0.985);
NO_CRASH := COUNT((C - REF(C, 1)) / REF(C, 1) < -0.03, N) = 0;

{ 6. 旗面缩量洗盘：旗面平均成交量低于旗杆放量周的 75% }
FLAG_VOL_SHRINK := MA(V, N) <= REF(V, N) * 0.75;

{ 7. 均线与动能指标共振过滤：周线MA5>=MA10且收盘踩上MA10 + 周MACD金叉红柱多头掌控 }
MA_OK := MA(C, 5) >= MA(C, 10) AND C >= MA(C, 10);
MACD_OK := MACD.DIF >= MACD.DEA;

{ 最终选股输出：全市场控仓高胜率标的在100只以内 }
XG: FLAG_TIME AND FLAG_CHANNEL AND POLE_DEFENSE AND NO_CRASH AND FLAG_VOL_SHRINK AND MA_OK AND MACD_OK;
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from easy_tdx.strategies.base import BaseStrategy, Param
from easy_tdx.strategies.registry import register_strategy
from easy_tdx.MyTT import MA, HHV, LLV, MACD


@register_strategy
class WeeklyBullFlagStrategy(BaseStrategy):
    name = "weekly_bull_flag"
    display_name = "通信达上涨旗形策略"
    category = "technical"
    description = "前期周线超跌>20%，标志性大阳(+7%)立起旗杆，随后2~6周缩量水平或微斜整理不破旗杆中轴，各周相对首日基准波动<=±3%，结合周线均线与MACD多头共振，控制优质标的在100只以内。"

    params_list = [
        Param("prior_drop_pct", float, default=20.0, min_value=10.0, max_value=60.0, step=5.0, label="前期跌幅阈值(%)", description="大阳旗杆前波段最大跌幅要求"),
        Param("prior_lookback", int, default=20, min_value=8, max_value=50, step=2, label="前期跌幅统计周数", description="大阳旗杆前寻找高低点的回溯周数"),
        Param("pole_min_pct", float, default=7.0, min_value=5.0, max_value=20.0, step=0.5, label="旗杆长阳涨幅阈值(%)", description="标志性旗杆大阳线的单周涨幅下限"),
        Param("min_flag_weeks", int, default=2, min_value=2, max_value=10, step=1, label="旗面最小周数", description="旗杆后连续横盘旗面的最少周数"),
        Param("max_flag_weeks", int, default=6, min_value=3, max_value=12, step=1, label="旗面最大周数", description="旗杆后旗面整理考察的最长周数"),
        Param("base_dev_pct", float, default=3.0, min_value=0.5, max_value=10.0, step=0.5, label="基准首周偏离限制(%)", description="以旗面第一根交易周为基准，旗面所有周期的收盘价相对基准的绝对偏离百分比"),
        Param("max_single_drop_pct", float, default=3.0, min_value=0.5, max_value=10.0, step=0.5, label="旗面单周最大跌幅(%)", description="旗面整理期间任意一周的最大下跌幅度限制"),
        Param("pole_retrace_ratio", float, default=0.50, min_value=0.30, max_value=0.90, step=0.05, label="旗杆腰线承托位", description="旗面最低价相对旗杆实体的承托分位(默认0.50中轴)"),
        Param("vol_shrink_ratio", float, default=0.75, min_value=0.3, max_value=1.2, step=0.05, label="旗面缩量容差比例", description="旗面均量相对于旗杆大阳周成交量的倍数上限(默认0.75倍缩量)"),
        Param("enable_ma_filter", bool, default=True, label="均线多头共振过滤", description="要求MA5>=MA10且收盘价站上MA10生命线"),
        Param("enable_macd_filter", bool, default=True, label="MACD金叉共振过滤", description="要求周线MACD DIF>=DEA处于红柱多头掌控区"),
    ]

    params_schema = {
        "prior_drop_pct": 20.0,
        "prior_lookback": 20,
        "pole_min_pct": 7.0,
        "min_flag_weeks": 2,
        "max_flag_weeks": 6,
        "base_dev_pct": 3.0,
        "max_single_drop_pct": 3.0,
        "pole_retrace_ratio": 0.50,
        "vol_shrink_ratio": 0.75,
        "enable_ma_filter": True,
        "enable_macd_filter": True,
    }

    def generate_signals(self, df: pd.DataFrame) -> pd.DataFrame:
        res = df.copy()
        n = len(res)
        if n < 20:
            res["buy_signal"] = False
            res["sell_signal"] = False
            return res

        prior_drop_pct = float(self.params.get("prior_drop_pct", 20.0)) / 100.0
        prior_lookback = int(self.params.get("prior_lookback", 20))
        pole_min_pct = float(self.params.get("pole_min_pct", 7.0))
        min_flag = int(self.params.get("min_flag_weeks", 2))
        max_flag = int(self.params.get("max_flag_weeks", 6))
        base_dev_pct = float(self.params.get("base_dev_pct", 3.0))
        max_single_drop = float(self.params.get("max_single_drop_pct", 3.0))
        pole_retrace = float(self.params.get("pole_retrace_ratio", 0.50))
        vol_tol = float(self.params.get("vol_shrink_ratio", 0.75))
        enable_ma = bool(self.params.get("enable_ma_filter", True))
        enable_macd = bool(self.params.get("enable_macd_filter", True))

        opens = res["open"].values
        highs = res["high"].values
        lows = res["low"].values
        closes = res["close"].values
        volumes = res["volume"].values if "volume" in res.columns else res["vol"].values

        # Precompute technical indicators
        ma5 = MA(closes, 5) if enable_ma else None
        ma10 = MA(closes, 10) if enable_ma else None
        if enable_macd:
            dif, dea, _ = MACD(closes)
        else:
            dif, dea = None, None

        # Calculate percentage change
        pcts = np.zeros(n)
        for i in range(1, n):
            prev = closes[i - 1]
            pcts[i] = (closes[i] - prev) / prev * 100.0 if prev > 0 else 0.0

        buy_signal = np.zeros(n, dtype=bool)
        sell_signal = np.zeros(n, dtype=bool)
        is_pattern = np.zeros(n, dtype=bool)

        for i in range(min_flag + 10, n):
            for N in range(min_flag, max_flag + 1):
                big_idx = i - N
                if big_idx < 5:
                    continue

                b_pct = pcts[big_idx]
                b_open = opens[big_idx]
                b_close = closes[big_idx]
                b_low = lows[big_idx]
                b_vol = volumes[big_idx]

                # 1. 旗杆检验：单周涨幅 >= 7%，实体收阳
                if b_pct < pole_min_pct or b_close <= b_open:
                    continue

                # 2. 前期跌幅检验：大阳线前波段跌幅 >= 20%
                look_start = max(0, big_idx - prior_lookback)
                prior_h = np.max(highs[look_start:big_idx])
                prior_l = min(np.min(lows[look_start:big_idx]), b_low)
                if prior_h <= 0:
                    continue
                drop = (prior_h - prior_l) / prior_h
                if drop < prior_drop_pct:
                    continue

                # 3. 旗面 K 线切片：从 big_idx + 1 到 i
                cons_l = lows[big_idx + 1 : i + 1]
                cons_c = closes[big_idx + 1 : i + 1]
                cons_v = volumes[big_idx + 1 : i + 1]
                cons_pcts = pcts[big_idx + 1 : i + 1]

                # (1) 旗面基准稳定性：以大阳后第一根交易周收盘价为中枢基准
                base_close = cons_c[0]
                devs = np.abs(cons_c - base_close) / (base_close + 1e-6) * 100.0
                if np.max(devs) > base_dev_pct:
                    continue

                # (2) 旗面单周防下砸：任意单周跌幅不能超过 max_single_drop (默认 3%)
                if np.min(cons_pcts) < -max_single_drop:
                    continue

                # (3) 旗杆实体承托 (黄金腰线保护)：
                # 旗面最低价不跌破大阳线实体腰线 (50% 分位) 及起爆低点
                pole_midpoint = b_open + (b_close - b_open) * (1.0 - pole_retrace)
                retrace_support = min(pole_midpoint, b_open * 0.985)
                if np.min(cons_l) < retrace_support:
                    continue

                # 收盘价必须稳稳托在大阳线开盘价及腰线附近
                if np.min(cons_c) < b_open * 0.97:
                    continue

                # (4) 旗面缩量洗盘特征：旗面均量明显萎缩
                if np.mean(cons_v) > b_vol * vol_tol:
                    continue

                # (5) 均线与动能指标共振过滤：周线MA5>=MA10且收盘踩上MA10 + 周MACD金叉红柱多头掌控
                if enable_ma and ma5 is not None and ma10 is not None:
                    if ma5[i] < ma10[i] or closes[i] < ma10[i]:
                        continue
                if enable_macd and dif is not None and dea is not None:
                    if dif[i] < dea[i]:
                        continue

                # 上涨旗形确立！
                is_pattern[i] = True
                buy_signal[i] = True
                break

            # 卖出防守：跌破旗杆腰线或 MA5 趋势破位
            if i >= 1 and is_pattern[i - 1] and not is_pattern[i]:
                if closes[i] < closes[i - 1] * 0.95 or (i >= 5 and closes[i] < np.mean(closes[i - 5 : i])):
                    sell_signal[i] = True

        res["buy_signal"] = buy_signal
        res["sell_signal"] = sell_signal
        res["is_pattern"] = is_pattern
        return res


# 兼容原类名与别名注册
@register_strategy
class WeeklyBigBullConsolidationStrategy(WeeklyBullFlagStrategy):
    name = "weekly_big_bull_consolidation"
    display_name = "通信达上涨旗形策略"
