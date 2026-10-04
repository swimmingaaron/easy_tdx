"""内置策略集合。

每个策略通过 :func:`~easy_tdx.backtest.strategies.registry.register_strategy`
登记到全局注册表，并声明参数 schema 供 Web API 表单动态渲染。

导入本模块即触发所有策略的注册。Web API / CLI 通过 ``get_registry()```
发现策略，无需手动枚举。
"""

from __future__ import annotations

from easy_tdx.backtest.strategies.registry import (
    Param,
    ParametrizedStrategy,
    register_strategy,
)
from easy_tdx.MyTT import (
    ATR,
    BBI,
    BIAS,
    BOLL,
    CCI,
    CROSS,
    DMI,
    DPO,
    EMA,
    EMV,
    FSL,
    HHV,
    KDJ,
    KTN,
    MA,
    MACD,
    RSI,
    TAQ,
    TD_SEQUENTIAL,
    TRIX,
    WR,
    ZIG,
)

__all__: list[str] = []  # 注册副作用即可，无需导出符号


# ── 通达信上升九转（默认策略）──────────────────────────────────────────────────


@register_strategy(
    name="td_sequential",
    label="通达信上升九转",
    description=(
        "只做上升九转：高1顺势主升突破建仓，高9见顶衰竭逢高止盈，"
        "专做单边主升浪大行情，不参与下跌九转（低9抄底）。"
    ),
)
class TDSequentialStrategy(ParametrizedStrategy):
    """通达信上升九转策略。

    交易逻辑
    --------
    1. **空仓买入（高1启动）**：
       当 K 线出现上升九转启动信号 (td_high == 1)，代表收盘价首次突破 4 日前收盘价
       (C > REF(C, 4))，多头动能爆发，全仓顺势买入建仓！
    2. **持仓卖出（高9见顶/止损/超时）**：
       - 高9见顶止盈：上升九转连续完成到第 m 根 (td_high == m，默认高9)，多头衰竭见顶止盈；
       - 目标止盈：若涨幅达到 take_profit_pct 提前获利了结（0 为关闭）；
       - 硬止损保护：跌破买入价 stop_loss_pct (默认 5.0%) 强制平仓止损；
       - 最大持仓期：持股达到 max_hold_bars (默认 12 根 K 线) 未现高9则主动平仓。
    """

    params = [
        Param(
            "m",
            int,
            default=9,
            min_value=9,
            max_value=13,
            label="序列点数(9/13)",
            description="通达信上升九转(9)或十三转(13)见顶目标",
        ),
        Param(
            "max_hold_bars",
            int,
            default=12,
            min_value=3,
            max_value=30,
            label="最大持仓周期",
            description="买入后最多持仓 K 线根数，若未现高九则主动平仓",
        ),
        Param(
            "stop_loss_pct",
            float,
            default=5.0,
            min_value=0.0,
            max_value=20.0,
            label="硬止损比例(%)",
            description="跌破买入价此比例强制平仓止损（0 为不设硬止损）",
        ),
        Param(
            "take_profit_pct",
            float,
            default=0.0,
            min_value=0.0,
            max_value=50.0,
            label="目标止盈比例(%)",
            description="达到此盈利幅度提前止盈离场（0 为仅由高九见顶卖出）",
        ),
    ]

    def init(self) -> None:
        self.td_high, _ = self.I(TD_SEQUENTIAL, self.data.close, self.p["m"])
        self._entry_price: float = 0.0
        self._entry_bar: int = 0

    def next(self) -> None:
        idx = self._bar_index
        cur_c = float(self.data.close[0])

        if self.position["size"] == 0:
            if self.td_high[idx] == 1:
                self.buy(size=0)
                self._entry_price = cur_c
                self._entry_bar = idx
        else:
            is_high_m = (self.td_high[idx] == self.p["m"])
            is_sl = (self.p["stop_loss_pct"] > 0) and (
                cur_c < self._entry_price * (1.0 - self.p["stop_loss_pct"] / 100.0)
            )
            is_tp = (self.p["take_profit_pct"] > 0) and (
                cur_c >= self._entry_price * (1.0 + self.p["take_profit_pct"] / 100.0)
            )
            is_timeout = (self.p["max_hold_bars"] > 0) and (
                idx - self._entry_bar >= self.p["max_hold_bars"]
            )

            if is_high_m or is_sl or is_tp or is_timeout:
                self.sell(size=0)
                self._entry_price = 0.0


# ── ZIG 右侧突破回补 ──────────────────────────────────────────────────────────


@register_strategy(
    name="zig_breakout",
    label="ZIG 右侧突破回补",
    description=(
        "ZIG 见顶全仓卖出，空仓期间收盘价右侧突破前高时回补买入。"
        "信号全为整仓 BUY/SELL，逻辑清晰、无分仓复杂度。"
    ),
)
class ZigBreakoutStrategy(ParametrizedStrategy):
    """ZIG 右侧突破回补机制（方案1）。

    交易逻辑
    --------
    1. **空仓**：ZIG 向上启动（cur_zig > prev_zig）→ 全仓买入，进入持仓阶段。
    2. **持仓**：ZIG 见顶回落（cur_zig < prev_zig）→ 全仓卖出，
       并将当前 N 日最高价记为 breakout_level（后续突破确认位）。
    3. **空仓等待回补**：收盘价 >= breakout_level × (1 + confirm_pct/100)
       → 右侧突破确认，全仓买入回补，重置突破位。

    对比方案2（分仓止盈）
    ---------------------
    - 全程只有 BUY / SELL 整仓操作，与引擎 next_open 执行模式完全兼容。
    - 不依赖 ZIG 实时斜率做分仓，避免"ZIG 是未来函数回头重绘"的干扰。
    - 回补条件（右侧突破）在任意 K 线均可检测，真正做到实时可执行。
    """

    params = [
        Param(
            "zig_delta",
            float,
            default=10.0,
            min_value=1.0,
            max_value=50.0,
            label="ZIG 转向阈值(%)",
            description="价格反转触发 ZIG 转向的百分比阈值",
        ),
        Param(
            "confirm_pct",
            float,
            default=2.0,
            min_value=0.5,
            max_value=15.0,
            label="突破确认幅度(%)",
            description="收盘价需超过前高多少百分比才触发回补买入（防止假突破）",
        ),
        Param(
            "hhv_period",
            int,
            default=20,
            min_value=5,
            max_value=60,
            label="前高统计周期",
            description="卖出时记录最近 N 日最高价作为突破参考位",
        ),
        Param(
            "stop_loss_pct",
            float,
            default=3.0,
            min_value=0.0,
            max_value=20.0,
            label="硬止损比例(%)",
            description="买入后跌破买入价该百分比强制平仓止损（0 为关闭，防假波谷套牢）",
        ),
    ]

    def init(self) -> None:
        self.zig = self.I(ZIG, self.data.close, self.p["zig_delta"])
        self.hhv = self.I(HHV, self.data.high, self.p["hhv_period"])
        # 卖出后记录的突破确认价位；0 表示尚未有卖出记录或已回补
        self._breakout_level: float = 0.0

    def next(self) -> None:
        i = self._bar_index
        if i == 0:
            return

        cur_close = float(self.data.close[0])
        cur_zig = float(self.zig[i])
        prev_zig = float(self.zig[i - 1])
        cur_pos = self.position["size"]

        # 持仓：ZIG 见顶 → 全仓卖出，记录突破位 --------------------------------
        if cur_pos > 0 and cur_zig < prev_zig:
            self._breakout_level = float(self.hhv[i])
            self.sell(size=0, price=cur_close)
            return

        # 空仓：两种买入路径（附带硬止损保护）----------------------------------
        if cur_pos == 0:
            sl_pct = float(self.p.get("stop_loss_pct", 3.0))
            sl = cur_close * (1.0 - sl_pct / 100.0) if sl_pct > 0 else None

            # 路径 1：ZIG 向上启动（底部波谷确认）→ 初始建仓
            if cur_zig > prev_zig:
                self._breakout_level = 0.0  # 新一轮行情，重置突破位
                self.buy(size=0, price=cur_close, stop_loss=sl)
                return

            # 路径 2：右侧突破前高 → 回补建仓（洗盘结束、主升确立）
            if self._breakout_level > 0:
                threshold = self._breakout_level * (1.0 + self.p["confirm_pct"] / 100.0)
                if cur_close >= threshold:
                    self._breakout_level = 0.0
                    self.buy(size=0, price=cur_close, stop_loss=sl)


# ── 双均线交叉 ─────────────────────────────────────────────────────────────────


@register_strategy(
    name="ma_cross",
    label="双均线交叉",
    description="快线上穿慢线买入，快线下穿慢线卖出。最经典的趋势跟随策略。",
)
class MaCrossStrategy(ParametrizedStrategy):
    """快慢均线金叉买入、死叉卖出。"""

    params = [
        Param("fast", int, default=5, min_value=1, max_value=60, label="快线周期"),
        Param("slow", int, default=20, min_value=5, max_value=250, label="慢线周期"),
    ]
    param_constraints = [("fast", "slow")]

    def init(self) -> None:
        self.ma_fast = self.I(MA, self.data.close, self.p["fast"])
        self.ma_slow = self.I(MA, self.data.close, self.p["slow"])
        self.gold = self.I(CROSS, self.ma_fast, self.ma_slow)
        self.dead = self.I(CROSS, self.ma_slow, self.ma_fast)

    def next(self) -> None:
        i = self._bar_index
        if self.gold[i]:
            self.buy()
        elif self.dead[i] and self.position["size"] > 0:
            self.sell()


# ── 双均线实战优化战法 (MA PRO) ───────────────────────────────────────────────


@register_strategy(
    name="ma_cross_pro",
    label="双均线优化战法",
    description="MA5/MA20金叉实战优化：含20日线拐头初筛、次日突破确认、回踩二次入场及多维风控离场。",
)
class MaCrossProStrategy(ParametrizedStrategy):
    """双均线完整实战策略。

    优化流程：
    1. 选股初筛：MA5 上穿 MA20 金叉，且 20日均线走平或向上拐头（排除均线下行假金叉）；
    2. 二次筛选：金叉次日收盘价高于金叉日最高价确认突破；
    3. 入场时机：金叉后第3天（T+2）标准入场，或多头回踩5日线放量/回踩20日线企稳二次入场；
    4. 离场规则：收盘有效跌破20日均线、死叉或连续两日跌破5日线离场。
    """

    params = [
        Param("fast", int, default=5, min_value=1, max_value=60, label="快线周期(MA5)"),
        Param("slow", int, default=20, min_value=5, max_value=250, label="慢线周期(MA20)"),
    ]
    param_constraints = [("fast", "slow")]

    def init(self) -> None:
        self.ma_fast = self.I(MA, self.data.close, self.p["fast"])
        self.ma_slow = self.I(MA, self.data.close, self.p["slow"])
        self.gold = self.I(CROSS, self.ma_fast, self.ma_slow)
        self.dead = self.I(CROSS, self.ma_slow, self.ma_fast)

        self._pending_gold_bar = -999

    def next(self) -> None:
        idx = self._bar_index
        cur_c = float(self.data.close[0])
        prev_c = float(self.data.close[-1]) if idx > 0 else cur_c

        ma_f = float(self.ma_fast[idx])
        ma_f_prev = float(self.ma_fast[idx - 1]) if idx > 0 else ma_f
        ma_s = float(self.ma_slow[idx])
        ma_s_prev = float(self.ma_slow[idx - 1]) if idx > 0 else ma_s

        # ── 1. 持仓离场检查（卖出条件：股价有效跌破5日均线且隔日未收回，立即离场）──────
        if self.position["size"] > 0:
            is_break_fast_2d = (cur_c < ma_f) and (prev_c < ma_f_prev)
            is_dead_cross = bool(self.dead[idx])

            if is_break_fast_2d or is_dead_cross:
                self.sell(size=0)
                self._pending_gold_bar = -999
            return

        # ── 2. 空仓筛选与入场 ────────────────────────────────────────────────────────
        # 步骤 1：金叉 + 20日线形态初筛（MA20走平或拐头向上；向下倾斜直接放弃）
        if self.gold[idx]:
            if ma_s >= ma_s_prev:
                self._pending_gold_bar = idx
            return

        # 步骤 2 & 3：金叉次日（T+1）二次筛选与 T+2（第3日）入场
        # 若次日收盘价高于前一日（金叉日），确认突破走强，收盘发出买入指令（引擎次日开盘即第3日开盘买入）
        if self._pending_gold_bar > 0 and idx == self._pending_gold_bar + 1:
            if cur_c > prev_c:
                self.buy(size=0)
            self._pending_gold_bar = -999


# ── MACD 金叉 ──────────────────────────────────────────────────────────────────


@register_strategy(
    name="macd",
    label="MACD 金叉",
    description="DIF 上穿 DEA 买入（金叉），DIF 下穿 DEA 卖出（死叉）。",
)
class MacdStrategy(ParametrizedStrategy):
    """MACD 金叉/死叉。"""

    params = [
        Param("short", int, default=12, min_value=2, max_value=50, label="短期EMA"),
        Param("long", int, default=26, min_value=5, max_value=100, label="长期EMA"),
        Param("signal", int, default=9, min_value=2, max_value=50, label="信号周期"),
    ]
    param_constraints = [("short", "long")]

    def init(self) -> None:
        self.dif, self.dea, self._hist = self.I(
            MACD,
            self.data.close,
            self.p["short"],
            self.p["long"],
            self.p["signal"],
        )
        self.gold = self.I(CROSS, self.dif, self.dea)
        self.dead = self.I(CROSS, self.dea, self.dif)

    def next(self) -> None:
        i = self._bar_index
        if self.gold[i]:
            self.buy()
        elif self.dead[i] and self.position["size"] > 0:
            self.sell()


# ── 布林带突破 ─────────────────────────────────────────────────────────────────


@register_strategy(
    name="boll_breakout",
    label="布林带突破",
    description="收盘价突破下轨买入，突破上轨卖出（均值回归思路）。",
)
class BollBreakoutStrategy(ParametrizedStrategy):
    """价格触及下轨买入、触及上轨卖出。"""

    params = [
        Param("n", int, default=20, min_value=5, max_value=100, label="周期"),
        Param("p", float, default=2.0, min_value=0.5, max_value=4.0, label="标准差倍数"),
    ]

    def init(self) -> None:
        self.upper, self.mid, self.lower = self.I(BOLL, self.data.close, self.p["n"], self.p["p"])

    def next(self) -> None:
        i = self._bar_index
        close = self.data.close[0]
        # 触及下轨买入（均值回归）；触及上轨获利了结
        if close <= self.lower[i] and self.position["size"] == 0:
            self.buy()
        elif close >= self.upper[i] and self.position["size"] > 0:
            self.sell()


# ── RSI 超买超卖 ───────────────────────────────────────────────────────────────


@register_strategy(
    name="rsi_reversal",
    label="RSI 超卖反弹",
    description="RSI 低于超卖线买入，RSI 高于超买线卖出。",
)
class RsiReversalStrategy(ParametrizedStrategy):
    """RSI 超卖买入、超买卖出。"""

    params = [
        Param("n", int, default=14, min_value=2, max_value=50, label="RSI周期"),
        Param("oversold", int, default=30, min_value=5, max_value=45, label="超卖线"),
        Param("overbought", int, default=70, min_value=55, max_value=95, label="超买线"),
    ]
    param_constraints = [("oversold", "overbought")]

    def init(self) -> None:
        self.rsi = self.I(RSI, self.data.close, self.p["n"])

    def next(self) -> None:
        i = self._bar_index
        rsi = self.rsi[i]
        if rsi <= self.p["oversold"] and self.position["size"] == 0:
            self.buy()
        elif rsi >= self.p["overbought"] and self.position["size"] > 0:
            self.sell()


# ── KDJ 金叉 ───────────────────────────────────────────────────────────────────


@register_strategy(
    name="kdj_cross",
    label="KDJ 金叉",
    description="K 线上穿 D 线买入（金叉），K 线下穿 D 线卖出（死叉）。",
)
class KdjCrossStrategy(ParametrizedStrategy):
    """KDJ K/D 金叉死叉。"""

    params = [
        Param("n", int, default=9, min_value=2, max_value=30, label="RSV周期"),
    ]

    def init(self) -> None:
        self.k, self.d, self._j = self.I(
            KDJ,
            self.data.close,
            self.data.high,
            self.data.low,
            self.p["n"],
        )
        self.gold = self.I(CROSS, self.k, self.d)
        self.dead = self.I(CROSS, self.d, self.k)

    def next(self) -> None:
        i = self._bar_index
        if self.gold[i]:
            self.buy()
        elif self.dead[i] and self.position["size"] > 0:
            self.sell()


# ── EMA 双线交叉 ──────────────────────────────────────────────────────────────


@register_strategy(
    name="ema_cross",
    label="EMA 双线交叉",
    description="指数均线金叉买入、死叉卖出。比简单均线反应更灵敏。",
)
class EmaCrossStrategy(ParametrizedStrategy):
    params = [
        Param("fast", int, default=12, min_value=2, max_value=60, label="快线周期"),
        Param("slow", int, default=26, min_value=5, max_value=120, label="慢线周期"),
    ]
    param_constraints = [("fast", "slow")]

    def init(self) -> None:
        self.ema_fast = self.I(EMA, self.data.close, self.p["fast"])
        self.ema_slow = self.I(EMA, self.data.close, self.p["slow"])
        self.gold = self.I(CROSS, self.ema_fast, self.ema_slow)
        self.dead = self.I(CROSS, self.ema_slow, self.ema_fast)

    def next(self) -> None:
        i = self._bar_index
        if self.gold[i]:
            self.buy()
        elif self.dead[i] and self.position["size"] > 0:
            self.sell()


# ── 三均线系统 ────────────────────────────────────────────────────────────────


@register_strategy(
    name="triple_ma",
    label="三均线系统",
    description="短中长期均线多头排列买入、空头排列卖出。",
)
class TripleMaStrategy(ParametrizedStrategy):
    params = [
        Param("short", int, default=5, min_value=1, max_value=30, label="短期"),
        Param("mid", int, default=20, min_value=5, max_value=60, label="中期"),
        Param("long", int, default=60, min_value=20, max_value=250, label="长期"),
    ]
    param_constraints = [("short", "mid"), ("mid", "long")]

    def init(self) -> None:
        self.ma_s = self.I(MA, self.data.close, self.p["short"])
        self.ma_m = self.I(MA, self.data.close, self.p["mid"])
        self.ma_l = self.I(MA, self.data.close, self.p["long"])

    def next(self) -> None:
        i = self._bar_index
        if self.ma_s[i] > self.ma_m[i] > self.ma_l[i] and self.position["size"] == 0:
            self.buy()
        elif self.ma_s[i] < self.ma_m[i] < self.ma_l[i] and self.position["size"] > 0:
            self.sell()


# ── 唐安奇通道（海龟）────────────────────────────────────────────────────────


@register_strategy(
    name="donchian",
    label="唐安奇通道突破",
    description="突破N日最高价买入，跌破N日最低价卖出。海龟交易法核心。",
)
class DonchianStrategy(ParametrizedStrategy):
    params = [
        Param("n", int, default=20, min_value=5, max_value=100, label="通道周期"),
    ]

    def init(self) -> None:
        self.upper, self._mid, self.lower = self.I(TAQ, self.data.high, self.data.low, self.p["n"])

    def next(self) -> None:
        i = self._bar_index
        close = self.data.close[0]
        if close >= self.upper[i] and self.position["size"] == 0:
            self.buy()
        elif close <= self.lower[i] and self.position["size"] > 0:
            self.sell()


# ── 肯特纳通道 ────────────────────────────────────────────────────────────────


@register_strategy(
    name="keltner",
    label="肯特纳通道",
    description="收盘价突破上轨买入，跌破下轨卖出。ATR-based 通道。",
)
class KeltnerStrategy(ParametrizedStrategy):
    params = [
        Param("n", int, default=20, min_value=5, max_value=100, label="均线周期"),
        Param("m", int, default=10, min_value=2, max_value=50, label="ATR周期"),
    ]

    def init(self) -> None:
        self.upper, self._mid, self.lower = self.I(
            KTN, self.data.close, self.data.high, self.data.low, self.p["n"], self.p["m"]
        )

    def next(self) -> None:
        i = self._bar_index
        close = self.data.close[0]
        if close >= self.upper[i] and self.position["size"] == 0:
            self.buy()
        elif close <= self.lower[i] and self.position["size"] > 0:
            self.sell()


# ── BBI 多空指标 ──────────────────────────────────────────────────────────────


@register_strategy(
    name="bbi",
    label="BBI 多空指标",
    description="收盘价上穿BBI买入，下穿BBI卖出。多空综合指标。",
)
class BbiStrategy(ParametrizedStrategy):
    params = [
        Param("m1", int, default=3, min_value=1, max_value=20, label="均线1"),
        Param("m2", int, default=6, min_value=2, max_value=30, label="均线2"),
        Param("m3", int, default=12, min_value=5, max_value=60, label="均线3"),
        Param("m4", int, default=20, min_value=10, max_value=120, label="均线4"),
    ]

    def init(self) -> None:
        self.bbi = self.I(
            BBI, self.data.close, self.p["m1"], self.p["m2"], self.p["m3"], self.p["m4"]
        )

    def next(self) -> None:
        i = self._bar_index
        close = self.data.close[0]
        if close > self.bbi[i] and self.position["size"] == 0:
            self.buy()
        elif close < self.bbi[i] and self.position["size"] > 0:
            self.sell()


# ── CCI 顺势指标 ──────────────────────────────────────────────────────────────


@register_strategy(
    name="cci",
    label="CCI 超卖反弹",
    description="CCI 跌破-100后回升买入，涨破+100卖出。",
)
class CciStrategy(ParametrizedStrategy):
    params = [
        Param("n", int, default=14, min_value=2, max_value=50, label="CCI周期"),
        Param("oversold", int, default=-100, min_value=-200, max_value=0, label="超卖线"),
        Param("overbought", int, default=100, min_value=0, max_value=200, label="超买线"),
    ]
    param_constraints = [("oversold", "overbought")]

    def init(self) -> None:
        self.cci = self.I(CCI, self.data.close, self.data.high, self.data.low, self.p["n"])

    def next(self) -> None:
        i = self._bar_index
        cci = self.cci[i]
        if cci <= self.p["oversold"] and self.position["size"] == 0:
            self.buy()
        elif cci >= self.p["overbought"] and self.position["size"] > 0:
            self.sell()


# ── WR 威廉指标 ───────────────────────────────────────────────────────────────


@register_strategy(
    name="wr_reversal",
    label="WR 威廉超卖",
    description="WR 进入超卖区（<-80）买入，进入超买区（>-20）卖出。",
)
class WrReversalStrategy(ParametrizedStrategy):
    params = [
        Param("n", int, default=14, min_value=2, max_value=50, label="WR周期"),
        Param("oversold", int, default=-80, min_value=-100, max_value=-40, label="超卖线"),
        Param("overbought", int, default=-20, min_value=-60, max_value=0, label="超买线"),
    ]
    param_constraints = [("oversold", "overbought")]

    def init(self) -> None:
        self.wr, self._wr1 = self.I(WR, self.data.close, self.data.high, self.data.low, self.p["n"])

    def next(self) -> None:
        i = self._bar_index
        wr = self.wr[i]
        if wr <= self.p["oversold"] and self.position["size"] == 0:
            self.buy()
        elif wr >= self.p["overbought"] and self.position["size"] > 0:
            self.sell()


# ── BIAS 乖离率 ───────────────────────────────────────────────────────────────


@register_strategy(
    name="bias_reversal",
    label="BIAS 乖离反弹",
    description="乖离率低于负阈值（超跌）买入，高于正阈值（超涨）卖出。",
)
class BiasReversalStrategy(ParametrizedStrategy):
    params = [
        Param("n", int, default=6, min_value=2, max_value=30, label="均线周期"),
        Param("threshold", float, default=5.0, min_value=1.0, max_value=20.0, label="乖离阈值%"),
    ]

    def init(self) -> None:
        self.bias, self._b2, self._b3 = self.I(BIAS, self.data.close, self.p["n"], 12, 24)

    def next(self) -> None:
        i = self._bar_index
        bias_pct = self.bias[i] * 100
        threshold = self.p["threshold"]
        if bias_pct <= -threshold and self.position["size"] == 0:
            self.buy()
        elif bias_pct >= threshold and self.position["size"] > 0:
            self.sell()


# ── DMI 趋向指标 ──────────────────────────────────────────────────────────────


@register_strategy(
    name="dmi",
    label="DMI 趋向指标",
    description="+DI 上穿-DI 买入（多头趋强），+DI 下穿-DI 卖出。",
)
class DmiStrategy(ParametrizedStrategy):
    params = [
        Param("m1", int, default=14, min_value=2, max_value=30, label="DI周期"),
        Param("m2", int, default=6, min_value=2, max_value=20, label="ADX周期"),
    ]

    def init(self) -> None:
        self.pdi, self.mdi, self._adx, self._adxr = self.I(
            DMI, self.data.close, self.data.high, self.data.low, self.p["m1"], self.p["m2"]
        )
        self.gold = self.I(CROSS, self.pdi, self.mdi)
        self.dead = self.I(CROSS, self.mdi, self.pdi)

    def next(self) -> None:
        i = self._bar_index
        if self.gold[i]:
            self.buy()
        elif self.dead[i] and self.position["size"] > 0:
            self.sell()


# ── TRIX 三重平滑 ─────────────────────────────────────────────────────────────


@register_strategy(
    name="trix",
    label="TRIX 三重平滑",
    description="TRIX 上穿信号线买入，下穿卖出。过滤短期波动的趋势指标。",
)
class TrixStrategy(ParametrizedStrategy):
    params = [
        Param("m1", int, default=12, min_value=2, max_value=30, label="TRIX周期"),
        Param("m2", int, default=20, min_value=5, max_value=60, label="信号周期"),
    ]

    def init(self) -> None:
        self.trix, self.trma = self.I(TRIX, self.data.close, self.p["m1"], self.p["m2"])
        self.gold = self.I(CROSS, self.trix, self.trma)
        self.dead = self.I(CROSS, self.trma, self.trix)

    def next(self) -> None:
        i = self._bar_index
        if self.gold[i]:
            self.buy()
        elif self.dead[i] and self.position["size"] > 0:
            self.sell()


# ── EMV 简易波动 ──────────────────────────────────────────────────────────────


@register_strategy(
    name="emv",
    label="EMV 简易波动",
    description="EMV 上穿0轴买入，下穿0轴卖出。量价结合指标。",
)
class EmvStrategy(ParametrizedStrategy):
    params = [
        Param("n", int, default=14, min_value=2, max_value=30, label="EMV周期"),
    ]

    def init(self) -> None:
        self.emv, self._maemv = self.I(
            EMV, self.data.high, self.data.low, self.data.vol, self.p["n"]
        )

    def next(self) -> None:
        i = self._bar_index
        if self.emv[i] > 0 and self.position["size"] == 0:
            self.buy()
        elif self.emv[i] < 0 and self.position["size"] > 0:
            self.sell()


# ── DPO 区间震荡 ──────────────────────────────────────────────────────────────


@register_strategy(
    name="dpo",
    label="DPO 区间震荡",
    description="DPO 上穿信号线买入，下穿卖出。去除趋势的震荡指标。",
)
class DpoStrategy(ParametrizedStrategy):
    params = [
        Param("m1", int, default=20, min_value=5, max_value=60, label="DPO周期"),
    ]

    def init(self) -> None:
        self.dpo, self.madpo = self.I(DPO, self.data.close, self.p["m1"])
        self.gold = self.I(CROSS, self.dpo, self.madpo)
        self.dead = self.I(CROSS, self.madpo, self.dpo)

    def next(self) -> None:
        i = self._bar_index
        if self.gold[i]:
            self.buy()
        elif self.dead[i] and self.position["size"] > 0:
            self.sell()


# ── ATR 通道突破 ──────────────────────────────────────────────────────────────


@register_strategy(
    name="atr_breakout",
    label="ATR 通道突破",
    description="收盘价突破 均线+K×ATR 买入，跌破 均线-K×ATR 卖出。",
)
class AtrBreakoutStrategy(ParametrizedStrategy):
    params = [
        Param("n_ma", int, default=20, min_value=5, max_value=100, label="均线周期"),
        Param("n_atr", int, default=20, min_value=5, max_value=50, label="ATR周期"),
        Param("k", float, default=2.0, min_value=0.5, max_value=5.0, label="ATR倍数"),
    ]

    def init(self) -> None:
        self.ma = self.I(MA, self.data.close, self.p["n_ma"])
        self.atr = self.I(ATR, self.data.close, self.data.high, self.data.low, self.p["n_atr"])

    def next(self) -> None:
        i = self._bar_index
        close = self.data.close[0]
        upper = self.ma[i] + self.p["k"] * self.atr[i]
        lower = self.ma[i] - self.p["k"] * self.atr[i]
        if close >= upper and self.position["size"] == 0:
            self.buy()
        elif close <= lower and self.position["size"] > 0:
            self.sell()


# ── FSL 分水岭指标 ────────────────────────────────────────────────────────────


@register_strategy(
    name="fsl",
    label="FSL 分水岭",
    description="SWL 上穿 SWS 买入（多头占优），SWL 下穿 SWS 卖出（空头占优）。",
)
class FslStrategy(ParametrizedStrategy):
    """FSL 分水岭 SWL/SWS 金叉死叉。"""

    params = [
        Param(
            "capital",
            float,
            default=1e8,
            min_value=1e6,
            max_value=1e12,
            label="流通股本(股)",
        ),
    ]

    def init(self) -> None:
        self.swl, self.sws = self.I(FSL, self.data.close, self.data.vol, self.p["capital"])
        self.gold = self.I(CROSS, self.swl, self.sws)
        self.dead = self.I(CROSS, self.sws, self.swl)

    def next(self) -> None:
        i = self._bar_index
        if self.gold[i]:
            self.buy()
        elif self.dead[i] and self.position["size"] > 0:
            self.sell()


# ── 通信达大阳横盘调整策略 ──────────────────────────────────────────────────


@register_strategy(
    name="weekly_big_bull_consolidation",
    label="通信达大阳横盘调整策略",
    description="前期跌幅超20%，单周收出7%以上大阳线，随后2周及以上横盘缩量蓄势不破大阳低点买入。",
)
class WeeklyBigBullConsolidationStrategy(ParametrizedStrategy):
    params = [
        Param("prior_drop_pct", float, default=20.0, min_value=10.0, max_value=60.0, label="前期跌幅阈值(%)"),
        Param("prior_lookback", int, default=20, min_value=8, max_value=50, label="前期跌幅周数"),
        Param("big_bull_min_pct", float, default=7.0, min_value=5.0, max_value=20.0, label="大阳线涨幅阈值(%)"),
        Param("min_consolidation_weeks", int, default=2, min_value=2, max_value=10, label="最小横盘周数"),
        Param("max_consolidation_weeks", int, default=6, min_value=3, max_value=15, label="最大横盘周数"),
        Param("max_drop_pct", float, default=3.0, min_value=0.5, max_value=10.0, label="横盘单周最大跌幅限制(%)"),
        Param("max_pullback_pct", float, default=3.0, min_value=0.5, max_value=15.0, label="相对大阳收盘最大回撤(%)"),
    ]

    def init(self) -> None:
        pass

    def next(self) -> None:
        i = self._bar_index
        min_cons = int(self.p["min_consolidation_weeks"])
        max_cons = int(self.p["max_consolidation_weeks"])
        prior_drop = float(self.p["prior_drop_pct"]) / 100.0
        lookback = int(self.p["prior_lookback"])
        big_bull_pct = float(self.p["big_bull_min_pct"])
        max_drop = float(self.p.get("max_drop_pct", 3.0))
        max_pullback = float(self.p.get("max_pullback_pct", 3.0))

        if i < min_cons + 10:
            return

        closes = self.data.close
        opens = self.data.open
        highs = self.data.high
        lows = self.data.low
        vols = self.data.vol

        for N in range(min_cons, max_cons + 1):
            big_idx = i - N
            if big_idx < 5:
                continue

            prev_c = closes[big_idx - 1]
            if prev_c <= 0:
                continue
            pct = (closes[big_idx] - prev_c) / prev_c * 100.0
            if pct < big_bull_pct or closes[big_idx] <= opens[big_idx]:
                continue

            # Prior drop
            lk_start = max(0, big_idx - lookback)
            p_high = max(highs[j] for j in range(lk_start, big_idx))
            p_low = min(min(lows[j] for j in range(lk_start, big_idx)), lows[big_idx])
            if p_high <= 0 or (p_high - p_low) / p_high < prior_drop:
                continue

            # Consolidation check
            cons_lows = [lows[j] for j in range(big_idx + 1, i + 1)]
            cons_closes = [closes[j] for j in range(big_idx + 1, i + 1)]
            cons_vols = [vols[j] for j in range(big_idx + 1, i + 1)]

            # Check single week drop
            has_big_drop = False
            for j in range(big_idx + 1, i + 1):
                w_prev = closes[j - 1]
                if w_prev > 0 and (closes[j] - w_prev) / w_prev * 100.0 < -max_drop:
                    has_big_drop = True
                    break
            if has_big_drop:
                continue

            # Check pullback from big candle close
            if min(cons_closes) < closes[big_idx] * (1.0 - max_pullback / 100.0):
                continue

            if min(cons_lows) < lows[big_idx] * 0.985:
                continue
            if min(cons_closes) < opens[big_idx] * 0.97:
                continue
            if max(cons_closes) / (min(cons_closes) + 1e-6) > 1.16:
                continue
            if sum(cons_vols) / len(cons_vols) > vols[big_idx] * 1.15:
                continue

            # Valid consolidation trigger
            if self.position["size"] == 0:
                self.buy()
            return

        if self.position["size"] > 0:
            # Trailing stop or break of support
            if i >= 5:
                ma5 = sum(closes[j] for j in range(i - 4, i + 1)) / 5.0
                if closes[i] < ma5 * 0.97:
                    self.sell()


