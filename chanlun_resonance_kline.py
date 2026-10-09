#!/usr/bin/env python3
"""
缠论理论多周期共振买卖点 K线图分析系统 (Python 脚本)
========================================================================

支持周期：
    月线 (MONTH) | 周线 (WEEK) | 日线 (DAY) | 120F (120分钟) |
    60F (60分钟) | 30F (30分钟) | 15F (15分钟) | 5F (5分钟)

默认周期组合：
    周线 (WEEK) + 日线 (DAY) + 30F (30分钟)
    （用户可通过 --periods 参数自由指定任意 3 个周期的立体共振分析）

核心理论与功能：
1. 缠论核心计算管道：
   - K线包含关系合并 (CKline)
   - 分型识别 (顶分型 / 底分型)
   - 笔划分 (向上笔 / 向下笔)
   - 中枢构建 (ZG / ZD / GG / DD 区间)
   - 买卖点识别 (1买 / 2买 / 3买 与 1卖 / 2卖 / 3卖)
   - 背驰判断 (笔背驰 / 盘整背驰 / 趋势背驰)
   - MACD 辅助动力学验证 (DIF / DEA / 柱状图)

2. 三周期立体共振买卖点引擎 (Three-Period Resonance Engine)：
   - 大级别 (宏观趋势定方向)：周线/月线确定大方向，处于向上笔、底背驰或大级别买点区间；
   - 中级别 (波段形态定走势)：日线/60F 确定波段结构，形成中枢震荡、突破或回踩确立；
   - 小级别 (微观入场定买点 - 区间套)：30F/15F/5F 精准捕捉底背驰、二买启动或三买爆发点。
   - 共振判定：
     * 【三周期共振买点】：小级别触发买点 (1B/2B/3B/底背驰) 时，中级别与大级别同时处于买点确认期或多头笔中！
     * 【三周期共振卖点】：小级别触发卖点 (1S/2S/3S/顶背驰) 时，中级别与大级别同时处于卖点确认期或空头笔中！
     * 评级分类：AAA级 (三级别全同构买卖点，如全一买/全二买/全三买)、AA级 (复合强共振)、A级 (立体趋势共振)。

3. 双模图表可视化：
   - 高清暗黑专业金融 K 线图 (PNG)：三联面板堆叠，K线、笔折线、中枢区域、买卖点、共振星标、MACD清晰呈现。
   - 交互式 HTML 报告 (--html)：内置 ECharts 联动缩放与十字光标悬浮，支持在浏览器中全屏查看与交互。

使用示例：
    # 1. 默认参数 (周线 + 日线 + 30分钟) 分析平安银行 (000001)
    python chanlun_resonance_kline.py --code 000001

    # 2. 自选三个周期：日线 + 60分钟 + 15分钟
    python chanlun_resonance_kline.py --code 600519 --periods DAY,60F,15F

    # 3. 宏观长线周期：月线 + 周线 + 日线
    python chanlun_resonance_kline.py --code 300750 --periods MONTH,WEEK,DAY

    # 4. 生成交互式 HTML 报告并在桌面查看
    python chanlun_resonance_kline.py --code 000001 --html --show
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

# Windows UTF-8 控制台兼容
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# 将工程 src 目录加入模块搜索路径
PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from easy_tdx.chanlun.analyser import ChanlunAnalyser, ChanlunResult
from easy_tdx.chanlun.types import BI, FX, MMD, ZS, Direction, FXType, MMDType
from easy_tdx.market_data import fetch_security_kline
from easy_tdx.stock_lookup import get_stock_name

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("chanlun_resonance")

# ==============================================================================
# 1. 周期规范与定义
# ==============================================================================

PERIOD_SPECS: dict[str, dict[str, Any]] = {
    "MONTH": {
        "aliases": ["MONTH", "MONTHLY", "月线", "月", "M"],
        "weight": 80,
        "market_cat": "MONTH",
        "chan_freq": "monthly",
        "label": "月线 (MONTH)",
        "short_name": "月线",
        "date_fmt": "%Y-%m",
    },
    "WEEK": {
        "aliases": ["WEEK", "WEEKLY", "周线", "周", "W"],
        "weight": 70,
        "market_cat": "WEEK",
        "chan_freq": "weekly",
        "label": "周线 (WEEK)",
        "short_name": "周线",
        "date_fmt": "%Y-%m-%d",
    },
    "DAY": {
        "aliases": ["DAY", "DAILY", "日线", "日", "D"],
        "weight": 60,
        "market_cat": "DAY",
        "chan_freq": "daily",
        "label": "日线 (DAY)",
        "short_name": "日线",
        "date_fmt": "%Y-%m-%d",
    },
    "120F": {
        "aliases": ["120F", "120M", "120MIN", "120", "120分钟", "2H"],
        "weight": 50,
        "market_cat": "120M",
        "chan_freq": "120min",
        "label": "120分钟 (120F)",
        "short_name": "120F",
        "date_fmt": "%m-%d %H:%M",
    },
    "60F": {
        "aliases": ["60F", "60M", "60MIN", "60", "60分钟", "1H"],
        "weight": 40,
        "market_cat": "60M",
        "chan_freq": "60min",
        "label": "60分钟 (60F)",
        "short_name": "60F",
        "date_fmt": "%m-%d %H:%M",
    },
    "30F": {
        "aliases": ["30F", "30M", "30MIN", "30", "30分钟"],
        "weight": 30,
        "market_cat": "30M",
        "chan_freq": "30min",
        "label": "30分钟 (30F)",
        "short_name": "30F",
        "date_fmt": "%m-%d %H:%M",
    },
    "15F": {
        "aliases": ["15F", "15M", "15MIN", "15", "15分钟"],
        "weight": 20,
        "market_cat": "15M",
        "chan_freq": "15min",
        "label": "15分钟 (15F)",
        "short_name": "15F",
        "date_fmt": "%m-%d %H:%M",
    },
    "5F": {
        "aliases": ["5F", "5M", "5MIN", "5", "5分钟"],
        "weight": 10,
        "market_cat": "5M",
        "chan_freq": "5min",
        "label": "5分钟 (5F)",
        "short_name": "5F",
        "date_fmt": "%m-%d %H:%M",
    },
}


def normalize_period(user_input: str) -> str:
    """将用户输入的任意周期名（如 '周线', '30M', '30F'）规范化为标准键名。"""
    raw = str(user_input).strip().upper()
    for key, spec in PERIOD_SPECS.items():
        if raw in [a.upper() for a in spec["aliases"]]:
            return key
    raise ValueError(
        f"未知周期 '{user_input}'，可选周期包括: "
        f"{', '.join(PERIOD_SPECS.keys())} (或中文如 月线/周线/日线/120F/60F/30F/15F/5F)"
    )


def parse_three_periods(periods_str: str) -> list[str]:
    """解析并校验 3 个周期，按大级别到小级别自动排序返回。"""
    parts = [p.strip() for p in periods_str.replace("，", ",").split(",") if p.strip()]
    if len(parts) != 3:
        raise ValueError(f"必须恰好指定 3 个周期，当前输入了 {len(parts)} 个: {periods_str}")

    normalized = [normalize_period(p) for p in parts]
    # 去重检查
    if len(set(normalized)) != 3:
        raise ValueError(f"选择的 3 个周期不能重复: {normalized}")

    # 按照权重从大到小排序（大级别在上，小级别在下）
    sorted_periods = sorted(normalized, key=lambda k: PERIOD_SPECS[k]["weight"], reverse=True)
    return sorted_periods


# ==============================================================================
# 2. 三周期立体共振买卖点引擎
# ==============================================================================


@dataclass
class PeriodState:
    """某一周期在特定时间戳下的走势状态。"""

    period: str
    bar_index: int
    bar_date: str
    price: float
    current_bi_direction: str  # "up" / "down" / "none"
    current_bi_start_val: float = 0.0
    current_bi_end_val: float = 0.0
    recent_mmd_type: str = ""  # "1buy", "2buy", "3buy", "1sell", "2sell", "3sell", ""
    recent_mmd_date: str = ""
    recent_mmd_bars_ago: int = 999
    is_bullish: bool = False
    is_bearish: bool = False
    detail: str = ""


@dataclass
class ResonanceSignal:
    """三周期共振买卖点事件。"""

    timestamp: str  # 小级别触发时间
    price: float  # 小级别触发价格
    direction: str  # "BUY" 或 "SELL"
    grade: str  # "AAA" / "AA" / "A"
    pattern_name: str  # 共振形态名称
    high_period: str
    mid_period: str
    low_period: str
    high_state: PeriodState
    mid_state: PeriodState
    low_state: PeriodState
    low_bar_idx: int  # 小级别图上的 K 线索引
    mid_bar_idx: int  # 中级别图上的对应 K 线索引
    high_bar_idx: int  # 大级别图上的对应 K 线索引
    description: str


def _to_dt(val: Any) -> datetime:
    """安全将任意时间格式 (str, pd.Timestamp, datetime) 转为 Python datetime。"""
    if isinstance(val, datetime):
        return val
    if isinstance(val, pd.Timestamp):
        return val.to_pydatetime()
    try:
        return pd.to_datetime(str(val)).to_pydatetime()
    except Exception:
        return datetime.now()


def _fmt_dt(val: Any, is_intraday: bool = False) -> str:
    """安全格式化日期。"""
    dt = _to_dt(val)
    return dt.strftime("%Y-%m-%d %H:%M") if is_intraday else dt.strftime("%Y-%m-%d")


class ThreePeriodResonanceEngine:
    """三周期缠论共振买卖点识别引擎。"""

    def __init__(
        self,
        high_period: str,
        mid_period: str,
        low_period: str,
        results: dict[str, ChanlunResult],
    ):
        self.p_high = high_period
        self.p_mid = mid_period
        self.p_low = low_period
        self.res_high = results[high_period]
        self.res_mid = results[mid_period]
        self.res_low = results[low_period]

    def _get_period_state_at(self, period: str, target_dt: Any) -> PeriodState:
        """评估指定周期在某一时间戳 target_dt 的多空状态。"""
        target_obj = _to_dt(target_dt)
        res = (
            self.res_high
            if period == self.p_high
            else (self.res_mid if period == self.p_mid else self.res_low)
        )
        klines = res.klines
        if not klines:
            return PeriodState(period, -1, "", 0.0, "none")

        # 找到最接近且 <= target_dt 的 K 线
        valid_bars = [i for i, k in enumerate(klines) if _to_dt(k.date) <= target_obj]
        if not valid_bars:
            bar_idx = 0
        else:
            bar_idx = valid_bars[-1]

        cur_k = klines[bar_idx]
        cur_date_str = _fmt_dt(cur_k.date, is_intraday=("min" in period.lower() or "f" in period.lower()))

        # 检查笔状态
        active_bi = None
        for bi in res.bis:
            if bi.start.k.k_index <= bar_idx:
                active_bi = bi

        bi_dir = active_bi.direction.value if active_bi else "none"
        bi_s_val = active_bi.start.val if active_bi else 0.0
        bi_e_val = active_bi.end.val if active_bi else 0.0

        # 检查在 target_dt 之前最近触发的 MMD
        prior_mmds = []
        for mmd in res.mmds:
            if mmd.bi and _to_dt(mmd.bi.end.k.date) <= target_obj:
                prior_mmds.append(mmd)

        last_mmd = prior_mmds[-1] if prior_mmds else None
        mmd_type = last_mmd.mmd_type.value if last_mmd else ""
        mmd_dt = (
            _fmt_dt(last_mmd.bi.end.k.date, is_intraday=("min" in period.lower() or "f" in period.lower()))
            if last_mmd and last_mmd.bi
            else ""
        )
        bars_ago = (
            (bar_idx - last_mmd.bi.end.k.k_index)
            if last_mmd and last_mmd.bi
            else 999
        )

        # 多空综合倾向判定
        is_bullish = False
        is_bearish = False
        detail_msg = []

        if mmd_type in ("1buy", "2buy", "3buy") and bars_ago <= 15:
            is_bullish = True
            detail_msg.append(f"{mmd_type.upper()}确立({bars_ago}根前)")
        elif bi_dir == "up":
            is_bullish = True
            detail_msg.append("处于向上笔运行中")

        if mmd_type in ("1sell", "2sell", "3sell") and bars_ago <= 15:
            is_bearish = True
            detail_msg.append(f"{mmd_type.upper()}确立({bars_ago}根前)")
        elif bi_dir == "down":
            is_bearish = True
            detail_msg.append("处于向下笔运行中")

        if is_bullish and is_bearish:
            # 依据最新的一笔方向仲裁
            if bi_dir == "up":
                is_bearish = False
            else:
                is_bullish = False

        return PeriodState(
            period=period,
            bar_index=bar_idx,
            bar_date=cur_date_str,
            price=cur_k.close,
            current_bi_direction=bi_dir,
            current_bi_start_val=bi_s_val,
            current_bi_end_val=bi_e_val,
            recent_mmd_type=mmd_type,
            recent_mmd_date=mmd_dt,
            recent_mmd_bars_ago=bars_ago,
            is_bullish=is_bullish,
            is_bearish=is_bearish,
            detail="; ".join(detail_msg) if detail_msg else "无明显单边倾向",
        )

    def scan_resonances(self) -> list[ResonanceSignal]:
        """扫描在小级别上触发的三周期共振买卖点。"""
        resonances: list[ResonanceSignal] = []
        low_res = self.res_low

        # 收集小级别所有的买卖点和转折点
        trigger_events = []
        for mmd in low_res.mmds:
            if not mmd.bi:
                continue
            trigger_events.append({
                "type": mmd.mmd_type.value,
                "dt": mmd.bi.end.k.date,
                "price": mmd.bi.end.val,
                "bar_idx": mmd.bi.end.k.k_index,
                "is_buy": "buy" in mmd.mmd_type.value,
                "msg": mmd.msg,
            })

        # 去重排序
        trigger_events = sorted(trigger_events, key=lambda x: _to_dt(x["dt"]))

        for ev in trigger_events:
            target_dt = ev["dt"]
            is_buy = ev["is_buy"]

            # 获取此时刻中级别与大级别状态
            low_state = self._get_period_state_at(self.p_low, target_dt)
            mid_state = self._get_period_state_at(self.p_mid, target_dt)
            high_state = self._get_period_state_at(self.p_high, target_dt)

            if is_buy:
                # 检查中级别与大级别是否支持做多
                if mid_state.is_bullish and high_state.is_bullish:
                    # 形成三周期共振买点！
                    grade, name = self._classify_resonance(
                        "BUY", high_state, mid_state, ev["type"]
                    )
                    desc = (
                        f"【{name}】\n"
                        f"- {self.p_high}(大): {high_state.detail}\n"
                        f"- {self.p_mid}(中): {mid_state.detail}\n"
                        f"- {self.p_low}(小): 触发 {ev['type'].upper()} ({ev['price']:.2f})"
                    )
                    is_intra = ("min" in self.p_low.lower() or "f" in self.p_low.lower() or "m" in self.p_low.lower())
                    resonances.append(
                        ResonanceSignal(
                            timestamp=_fmt_dt(target_dt, is_intraday=is_intra),
                            price=ev["price"],
                            direction="BUY",
                            grade=grade,
                            pattern_name=name,
                            high_period=self.p_high,
                            mid_period=self.p_mid,
                            low_period=self.p_low,
                            high_state=high_state,
                            mid_state=mid_state,
                            low_state=low_state,
                            low_bar_idx=ev["bar_idx"],
                            mid_bar_idx=mid_state.bar_index,
                            high_bar_idx=high_state.bar_index,
                            description=desc,
                        )
                    )
            else:
                # 检查中级别与大级别是否支持做空
                if mid_state.is_bearish and high_state.is_bearish:
                    # 形成三周期共振卖点！
                    grade, name = self._classify_resonance(
                        "SELL", high_state, mid_state, ev["type"]
                    )
                    desc = (
                        f"【{name}】\n"
                        f"- {self.p_high}(大): {high_state.detail}\n"
                        f"- {self.p_mid}(中): {mid_state.detail}\n"
                        f"- {self.p_low}(小): 触发 {ev['type'].upper()} ({ev['price']:.2f})"
                    )
                    is_intra = ("min" in self.p_low.lower() or "f" in self.p_low.lower() or "m" in self.p_low.lower())
                    resonances.append(
                        ResonanceSignal(
                            timestamp=_fmt_dt(target_dt, is_intraday=is_intra),
                            price=ev["price"],
                            direction="SELL",
                            grade=grade,
                            pattern_name=name,
                            high_period=self.p_high,
                            mid_period=self.p_mid,
                            low_period=self.p_low,
                            high_state=high_state,
                            mid_state=mid_state,
                            low_state=low_state,
                            low_bar_idx=ev["bar_idx"],
                            mid_bar_idx=mid_state.bar_index,
                            high_bar_idx=high_state.bar_index,
                            description=desc,
                        )
                    )

        return resonances

    def _classify_resonance(
        self,
        direction: str,
        high: PeriodState,
        mid: PeriodState,
        low_mmd: str,
    ) -> tuple[str, str]:
        """对共振信号进行评级与命名。"""
        p_names = f"{PERIOD_SPECS[self.p_high]['short_name']}·{PERIOD_SPECS[self.p_mid]['short_name']}·{PERIOD_SPECS[self.p_low]['short_name']}"

        if direction == "BUY":
            h_type = high.recent_mmd_type
            m_type = mid.recent_mmd_type
            # 1. AAA 级：三级别同构买点
            if "1buy" in h_type and "1buy" in m_type and "1buy" in low_mmd:
                return "AAA", f"★ [{p_names}] 全一买区间套极限抄底"
            if "2buy" in h_type and "2buy" in m_type and "2buy" in low_mmd:
                return "AAA", f"★ [{p_names}] 全二买主升浪确立共振"
            if "3buy" in h_type and "3buy" in m_type and "3buy" in low_mmd:
                return "AAA", f"★ [{p_names}] 全三买中枢爆发共振"

            # 2. AA 级：复合强共振
            if "3buy" in low_mmd:
                return "AA", f"★ [{p_names}] 三类买点中枢突破共振"
            if "2buy" in low_mmd:
                return "AA", f"★ [{p_names}] 二类买点起跑共振"
            if "1buy" in low_mmd:
                return "AA", f"★ [{p_names}] 一类买点底背驰共振"

            # 3. A 级：立体趋势多头共振
            return "A", f"★ [{p_names}] 多周期多头趋势共振买点"
        else:
            h_type = high.recent_mmd_type
            m_type = mid.recent_mmd_type
            if "1sell" in h_type and "1sell" in m_type and "1sell" in low_mmd:
                return "AAA", f"▼ [{p_names}] 全一卖顶背驰高抛共振"
            if "2sell" in h_type and "2sell" in m_type and "2sell" in low_mmd:
                return "AAA", f"▼ [{p_names}] 全二卖破位共振"
            if "3sell" in h_type and "3sell" in m_type and "3sell" in low_mmd:
                return "AAA", f"▼ [{p_names}] 全三卖中枢破位下杀共振"

            if "1sell" in low_mmd:
                return "AA", f"▼ [{p_names}] 一类卖点顶背驰共振"
            if "2sell" in low_mmd:
                return "AA", f"▼ [{p_names}] 二类卖点反弹不过共振"
            if "3sell" in low_mmd:
                return "AA", f"▼ [{p_names}] 三类卖点破位下杀共振"

            return "A", f"▼ [{p_names}] 多周期空头破位共振卖点"


# ==============================================================================
# 3. 高清专业金融暗黑 K 线图绘制 (Matplotlib)
# ==============================================================================


class ChanlunResonancePlotter:
    """高清专业金融暗黑风格 K 线图绘制器。"""

    def __init__(
        self,
        code: str,
        name: str,
        periods: list[str],
        dfs: dict[str, pd.DataFrame],
        results: dict[str, ChanlunResult],
        resonances: list[ResonanceSignal],
    ):
        self.code = code
        self.name = name
        self.periods = periods  # [High, Mid, Low]
        self.dfs = dfs
        self.results = results
        self.resonances = resonances

    def plot(self, save_path: str | Path | None = None, show: bool = False) -> Path | None:
        """生成三周期垂直联动暗黑风格 K 线图。"""
        import matplotlib
        if not show:
            matplotlib.use("Agg")
        import matplotlib.patches as patches
        import matplotlib.pyplot as plt

        # 字体与负号兼容设置
        plt.rcParams["font.sans-serif"] = [
            "Microsoft YaHei",
            "SimHei",
            "PingFang SC",
            "WenQuanYi Micro Hei",
            "sans-serif",
        ]
        plt.rcParams["axes.unicode_minus"] = False

        # 布局：3个周期，每个周期 2 个子图（主图K线 + 副图MACD）
        # 共 6 行，高度比例：[3, 1, 3, 1, 3, 1]
        fig = plt.figure(figsize=(16, 18), facecolor="#131722")
        gs = fig.add_gridspec(
            6,
            1,
            height_ratios=[3.2, 1.0, 3.2, 1.0, 3.2, 1.0],
            hspace=0.08,
            left=0.05,
            right=0.96,
            top=0.94,
            bottom=0.04,
        )

        axes = []
        for row in range(6):
            ax = fig.add_subplot(gs[row, 0])
            ax.set_facecolor("#181b27")
            axes.append(ax)

        # 3 个面板的主副图对
        panels = [
            (self.periods[0], axes[0], axes[1]),
            (self.periods[1], axes[2], axes[3]),
            (self.periods[2], axes[4], axes[5]),
        ]

        # 遍历绘制 3 个周期
        for p_idx, (period_key, ax_main, ax_macd) in enumerate(panels):
            df = self.dfs[period_key]
            res = self.results[period_key]
            p_spec = PERIOD_SPECS[period_key]
            n_bars = len(df)

            if n_bars == 0:
                ax_main.text(
                    0.5, 0.5, f"{p_spec['label']} 暂无数据",
                    color="#ffffff", ha="center", va="center"
                )
                continue

            # ------------------------------------------------------------------
            # (A) 绘制主图 K 线 (Candlesticks)
            # ------------------------------------------------------------------
            bar_width = 0.65
            min_body = (df["high"].max() - df["low"].min()) * 0.002 or 0.01

            for i in range(n_bars):
                row = df.iloc[i]
                op = float(row["open"])
                cl = float(row["close"])
                hi = float(row["high"])
                lo = float(row["low"])

                is_up = cl >= op
                c_wick = "#f23645" if is_up else "#089981"
                c_body = "#f23645" if is_up else "#089981"

                # 影线
                ax_main.plot([i, i], [lo, hi], color=c_wick, linewidth=1.1, zorder=3)
                # 实体
                body_y = min(op, cl)
                body_h = max(abs(cl - op), min_body)
                rect = patches.Rectangle(
                    (i - bar_width / 2, body_y),
                    bar_width,
                    body_h,
                    facecolor=c_body,
                    edgecolor=c_wick,
                    linewidth=0.8,
                    zorder=4,
                )
                ax_main.add_patch(rect)

            # ------------------------------------------------------------------
            # (B) 绘制缠论中枢 (ZhongShu Boxes)
            # ------------------------------------------------------------------
            for zs in res.zss:
                if not zs.start or not zs.end:
                    continue
                s_idx = max(0, zs.start.k.k_index)
                e_idx = min(n_bars - 1, zs.end.k.k_index)
                if e_idx < s_idx:
                    continue

                zs_w = max(1.0, e_idx - s_idx)
                zs_h = max(0.01, zs.zg - zs.zd)
                # 中枢主矩形
                zs_rect = patches.Rectangle(
                    (s_idx, zs.zd),
                    zs_w,
                    zs_h,
                    facecolor="#2962ff",
                    edgecolor="#2962ff",
                    alpha=0.22,
                    linestyle="--",
                    linewidth=1.2,
                    zorder=2,
                )
                ax_main.add_patch(zs_rect)

                # 中枢 ZG/ZD 标识线
                ax_main.hlines(
                    [zs.zg, zs.zd],
                    xmin=s_idx,
                    xmax=e_idx,
                    colors="#2962ff",
                    linestyles="solid",
                    linewidths=0.9,
                    alpha=0.75,
                    zorder=2,
                )
                # 中枢标注
                mid_x = (s_idx + e_idx) / 2
                ax_main.text(
                    mid_x,
                    zs.zg,
                    f"中枢[{zs.zd:.2f}~{zs.zg:.2f}]",
                    color="#82b1ff",
                    fontsize=8,
                    ha="center",
                    va="bottom",
                    alpha=0.9,
                    zorder=5,
                )

            # ------------------------------------------------------------------
            # (C) 绘制缠论笔 (Bi Lines)
            # ------------------------------------------------------------------
            if res.bis:
                bi_x = []
                bi_y = []
                for bi in res.bis:
                    bi_x.append(bi.start.k.k_index)
                    bi_y.append(bi.start.val)
                # 最后一笔终点
                last_bi = res.bis[-1]
                bi_x.append(last_bi.end.k.k_index)
                bi_y.append(last_bi.end.val)

                ax_main.plot(
                    bi_x,
                    bi_y,
                    color="#f0b90b",
                    linewidth=1.8,
                    linestyle="-",
                    marker="o",
                    markersize=3.5,
                    markerfacecolor="#ffffff",
                    markeredgecolor="#f0b90b",
                    alpha=0.92,
                    label="缠论笔",
                    zorder=6,
                )

            # ------------------------------------------------------------------
            # (D) 标注买卖点 (MMD Badges)
            # ------------------------------------------------------------------
            price_span = df["high"].max() - df["low"].min()
            offset = max(price_span * 0.05, 0.2)

            for mmd in res.mmds:
                if not mmd.bi:
                    continue
                k_idx = mmd.bi.end.k.k_index
                if k_idx < 0 or k_idx >= n_bars:
                    continue
                val = mmd.bi.end.val
                mtype = mmd.mmd_type.value

                is_buy = "buy" in mtype
                tag_color = "#f23645" if is_buy else "#089981"
                short_tag = mtype.upper().replace("BUY", "B").replace("SELL", "S")

                if is_buy:
                    ax_main.annotate(
                        f"▲{short_tag}",
                        xy=(k_idx, val),
                        xytext=(k_idx, val - offset * 1.2),
                        ha="center",
                        va="top",
                        fontsize=8.5,
                        fontweight="bold",
                        color="#ffffff",
                        bbox=dict(
                            boxstyle="round,pad=0.25",
                            facecolor=tag_color,
                            edgecolor="#ffffff",
                            alpha=0.92,
                        ),
                        arrowprops=dict(
                            facecolor=tag_color,
                            edgecolor="#ffffff",
                            shrink=0.1,
                            width=1.0,
                            headwidth=4,
                        ),
                        zorder=8,
                    )
                else:
                    ax_main.annotate(
                        f"▼{short_tag}",
                        xy=(k_idx, val),
                        xytext=(k_idx, val + offset * 1.2),
                        ha="center",
                        va="bottom",
                        fontsize=8.5,
                        fontweight="bold",
                        color="#ffffff",
                        bbox=dict(
                            boxstyle="round,pad=0.25",
                            facecolor=tag_color,
                            edgecolor="#ffffff",
                            alpha=0.92,
                        ),
                        arrowprops=dict(
                            facecolor=tag_color,
                            edgecolor="#ffffff",
                            shrink=0.1,
                            width=1.0,
                            headwidth=4,
                        ),
                        zorder=8,
                    )

            # ------------------------------------------------------------------
            # (E) 高亮三周期共振买卖点 (Resonance Stars & Badges)
            # ------------------------------------------------------------------
            for r in self.resonances:
                # 映射到当前周期的 K 线索引
                target_bar_idx = (
                    r.high_bar_idx
                    if p_idx == 0
                    else (r.mid_bar_idx if p_idx == 1 else r.low_bar_idx)
                )
                if 0 <= target_bar_idx < n_bars:
                    # 画贯穿该周期的垂直高亮基准线
                    v_color = "#ffeb3b" if r.direction == "BUY" else "#00e5ff"
                    ax_main.axvline(
                        x=target_bar_idx,
                        color=v_color,
                        linestyle=":",
                        linewidth=1.2,
                        alpha=0.7,
                        zorder=5,
                    )
                    ax_macd.axvline(
                        x=target_bar_idx,
                        color=v_color,
                        linestyle=":",
                        linewidth=1.2,
                        alpha=0.7,
                        zorder=5,
                    )

                    # 如果是小级别面板（面板 2），绘制显眼的共振大徽章
                    if p_idx == 2:
                        res_val = r.price
                        badge_bg = "#e91e63" if r.direction == "BUY" else "#00b0ff"
                        badge_text = (
                            f"★ 三周期共振买点 ({r.grade})\n¥{res_val:.2f}"
                            if r.direction == "BUY"
                            else f"▼ 三周期共振卖点 ({r.grade})\n¥{res_val:.2f}"
                        )
                        ax_main.annotate(
                            badge_text,
                            xy=(target_bar_idx, res_val),
                            xytext=(target_bar_idx, res_val - offset * 2.5 if r.direction == "BUY" else res_val + offset * 2.5),
                            ha="center",
                            va="top" if r.direction == "BUY" else "bottom",
                            fontsize=9.5,
                            fontweight="bold",
                            color="#ffffff",
                            bbox=dict(
                                boxstyle="round,pad=0.4",
                                facecolor=badge_bg,
                                edgecolor="#ffff00",
                                linewidth=1.5,
                                alpha=0.98,
                            ),
                            arrowprops=dict(
                                facecolor="#ffff00",
                                edgecolor="#ffffff",
                                shrink=0.08,
                                width=1.5,
                                headwidth=6,
                            ),
                            zorder=10,
                        )

            # ------------------------------------------------------------------
            # (F) 绘制副图 MACD
            # ------------------------------------------------------------------
            macd_data = res.macd
            if macd_data and "hist" in macd_data and len(macd_data["hist"]) == n_bars:
                hist = np.array(macd_data["hist"])
                dif = np.array(macd_data["dif"])
                dea = np.array(macd_data["dea"])

                for i in range(n_bars):
                    h_val = hist[i]
                    c_hist = "#f23645" if h_val >= 0 else "#089981"
                    ax_macd.bar(i, h_val * 2, color=c_hist, width=0.6, alpha=0.85)

                ax_macd.plot(range(n_bars), dif, color="#ffffff", linewidth=1.1, label="DIF")
                ax_macd.plot(range(n_bars), dea, color="#f0b90b", linewidth=1.1, label="DEA")
                ax_macd.axhline(0, color="#555555", linewidth=0.6, linestyle="--")

            # ------------------------------------------------------------------
            # (G) 坐标轴与标签美化
            # ------------------------------------------------------------------
            # 主图标题与统计
            last_c = float(df["close"].iloc[-1])
            first_c = float(df["open"].iloc[0])
            chg = (last_c - first_c) / first_c * 100 if first_c else 0
            sub_title = (
                f"【{p_spec['label']}】 最新价: ¥{last_c:.2f} ({chg:+.2f}%)   "
                f"分型: {len(res.fractals)} | 笔: {len(res.bis)} | 中枢: {len(res.zss)} | 买卖点: {len(res.mmds)}"
            )
            ax_main.set_title(
                sub_title,
                fontsize=11,
                fontweight="bold",
                color="#e0e0e0",
                loc="left",
                pad=6,
            )

            # Y 轴自适应预留边界
            ax_main.set_ylim(
                bottom=df["low"].min() - offset * 2.8,
                top=df["high"].max() + offset * 2.8,
            )

            # X 轴刻度
            step = max(1, n_bars // 7)
            xticks = list(range(0, n_bars, step))
            if (n_bars - 1) not in xticks:
                xticks.append(n_bars - 1)

            xlabels = [
                str(df["datetime"].iloc[idx])[5:16]
                if "min" in period_key.lower() or "f" in period_key.lower()
                else str(df["datetime"].iloc[idx])[:10]
                for idx in xticks
            ]
            ax_macd.set_xticks(xticks)
            ax_macd.set_xticklabels(xlabels, color="#9e9e9e", fontsize=8.5)
            ax_main.set_xticks([])

            ax_main.yaxis.tick_right()
            ax_macd.yaxis.tick_right()
            for ax in (ax_main, ax_macd):
                ax.tick_params(colors="#9e9e9e", labelsize=8)
                ax.grid(True, color="#252936", linestyle=":", linewidth=0.6, alpha=0.7)
                for spine in ax.spines.values():
                    spine.set_color("#2d313f")

        # ----------------------------------------------------------------------
        # 整体顶部标题仪表盘
        # ----------------------------------------------------------------------
        period_str = " · ".join([PERIOD_SPECS[p]["short_name"] for p in self.periods])
        res_summary = (
            f"共检出 {len(self.resonances)} 个三周期共振买卖点"
            if self.resonances
            else "当前周期组合暂无三级同向共振，维持中枢震荡观察"
        )
        if self.resonances:
            latest_r = self.resonances[-1]
            latest_str = f"最新信号: {latest_r.pattern_name} @ {latest_r.timestamp} (¥{latest_r.price:.2f})"
        else:
            latest_str = "最新状态: 多空平衡等待共振突破"

        header_title = f"{self.code} {self.name} · 缠论多周期立体共振分析 [{period_str}]"
        header_sub = f"{res_summary}   |   {latest_str}"

        fig.suptitle(
            header_title,
            fontsize=15,
            fontweight="bold",
            color="#ffffff",
            x=0.05,
            y=0.985,
            ha="left",
        )
        fig.text(
            0.05,
            0.962,
            header_sub,
            fontsize=10.5,
            color="#ffca28" if self.resonances else "#81c784",
            ha="left",
        )

        # 保存与显示
        if save_path is None:
            out_dir = PROJECT_ROOT / "output"
            out_dir.mkdir(parents=True, exist_ok=True)
            p_tag = "_".join(self.periods)
            save_path = out_dir / f"chanlun_resonance_{self.code}_{p_tag}.png"
        else:
            save_path = Path(save_path)
            save_path.parent.mkdir(parents=True, exist_ok=True)

        plt.savefig(
            save_path,
            dpi=150,
            facecolor=fig.get_facecolor(),
            edgecolor="none",
            bbox_inches="tight",
        )
        logger.info(f"高清三周期共振 K 线图已保存至: {save_path.resolve()}")

        if show:
            plt.show()

        plt.close(fig)
        return save_path


# ==============================================================================
# 4. 交互式 HTML 报告生成器 (ECharts)
# ==============================================================================


def export_interactive_html(
    code: str,
    name: str,
    periods: list[str],
    dfs: dict[str, pd.DataFrame],
    results: dict[str, ChanlunResult],
    resonances: list[ResonanceSignal],
    output_path: Path | str,
) -> Path:
    """生成内置 ECharts 的三周期全景交互式 HTML 报告。"""
    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    # 序列化每个周期的数据供前端 ECharts 渲染
    chart_payload = {}
    for p in periods:
        df = dfs[p]
        res = results[p]
        dates = df["datetime"].astype(str).tolist()
        k_values = df[["open", "close", "low", "high"]].values.tolist()

        # 笔折线数据
        bi_lines = []
        for bi in res.bis:
            bi_lines.append({
                "start_idx": bi.start.k.k_index,
                "start_val": round(bi.start.val, 2),
                "end_idx": bi.end.k.k_index,
                "end_val": round(bi.end.val, 2),
                "dir": bi.direction.value,
            })

        # 中枢矩形
        zs_boxes = []
        for zs in res.zss:
            if zs.start and zs.end:
                zs_boxes.append({
                    "start_idx": zs.start.k.k_index,
                    "end_idx": zs.end.k.k_index,
                    "zg": round(zs.zg, 2),
                    "zd": round(zs.zd, 2),
                    "gg": round(zs.gg, 2),
                    "dd": round(zs.dd, 2),
                })

        # 买卖点标记
        mmd_marks = []
        for mmd in res.mmds:
            if mmd.bi:
                mmd_marks.append({
                    "idx": mmd.bi.end.k.k_index,
                    "type": mmd.mmd_type.value,
                    "val": round(mmd.bi.end.val, 2),
                    "msg": mmd.msg,
                })

        # MACD
        macd_obj = res.macd if res.macd else {"dif": [], "dea": [], "hist": []}

        chart_payload[p] = {
            "label": PERIOD_SPECS[p]["label"],
            "dates": dates,
            "candles": k_values,
            "bis": bi_lines,
            "zss": zs_boxes,
            "mmds": mmd_marks,
            "macd": macd_obj,
        }

    # 共振列表
    res_list = [
        {
            "timestamp": r.timestamp,
            "price": r.price,
            "direction": r.direction,
            "grade": r.grade,
            "pattern_name": r.pattern_name,
            "high_bar_idx": r.high_bar_idx,
            "mid_bar_idx": r.mid_bar_idx,
            "low_bar_idx": r.low_bar_idx,
            "desc": r.description.replace("\n", "<br>"),
        }
        for r in resonances
    ]

    payload_json = json.dumps(
        {
            "code": code,
            "name": name,
            "periods": periods,
            "charts": chart_payload,
            "resonances": res_list,
        },
        ensure_ascii=False,
    )

    html_template = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{code} {name} - 缠论三周期共振买卖点交互K线图</title>
    <script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            background-color: #131722;
            color: #d1d4dc;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Microsoft YaHei", sans-serif;
            overflow-x: hidden;
            padding: 16px;
        }}
        .header {{
            background: linear-gradient(135deg, #1e222d 0%, #2a2e39 100%);
            border: 1px solid #363c4e;
            border-radius: 8px;
            padding: 16px 20px;
            margin-bottom: 16px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .title-box h1 {{
            font-size: 20px;
            font-weight: 700;
            color: #ffffff;
            margin-bottom: 6px;
        }}
        .title-box .tags {{
            font-size: 13px;
            color: #f0b90b;
        }}
        .summary-badge {{
            background: #2a2e39;
            border-radius: 6px;
            padding: 8px 14px;
            text-align: right;
            border: 1px solid #3a4055;
        }}
        .badge-buy {{ color: #f23645; font-weight: bold; }}
        .badge-sell {{ color: #089981; font-weight: bold; }}
        .res-table {{
            width: 100%;
            border-collapse: collapse;
            background: #1e222d;
            border-radius: 8px;
            overflow: hidden;
            margin-bottom: 20px;
            border: 1px solid #2d313f;
        }}
        .res-table th, .res-table td {{
            padding: 10px 14px;
            text-align: left;
            font-size: 12px;
            border-bottom: 1px solid #2d313f;
        }}
        .res-table th {{
            background: #262b3d;
            color: #a0a6b5;
        }}
        .chart-container {{
            background: #181b27;
            border: 1px solid #2d313f;
            border-radius: 8px;
            margin-bottom: 16px;
            padding: 10px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        }}
        .chart-title {{
            font-size: 14px;
            font-weight: 600;
            color: #ffffff;
            padding: 4px 8px 10px;
            border-bottom: 1px solid #262b3d;
            margin-bottom: 8px;
        }}
        .chart-dom {{
            width: 100%;
            height: 480px;
        }}
    </style>
</head>
<body>
    <div class="header">
        <div class="title-box">
            <h1>{code} {name} · 缠论三周期立体共振买卖点全景看板</h1>
            <div class="tags">
                选定周期: {PERIOD_SPECS[periods[0]]['label']} | {PERIOD_SPECS[periods[1]]['label']} | {PERIOD_SPECS[periods[2]]['label']}
            </div>
        </div>
        <div class="summary-badge">
            <div>共振信号数: <span style="color:#ffeb3b; font-weight:bold;">{len(resonances)}</span></div>
            <div style="font-size:12px; margin-top:4px;">技术系统: 通达信行情 + 缠论中枢笔引擎</div>
        </div>
    </div>

    <!-- 共振信号汇总清单 -->
    <div style="margin-bottom: 8px; font-size: 14px; font-weight: 600; color: #ffeb3b;">★ 三周期共振信号明细表</div>
    <table class="res-table">
        <thead>
            <tr>
                <th>触发时间</th>
                <th>共振方向</th>
                <th>评级</th>
                <th>共振形态</th>
                <th>触发价格</th>
                <th>三周期多空详情</th>
            </tr>
        </thead>
        <tbody id="res-tbody"></tbody>
    </table>

    <!-- 三周期图表区域 -->
    <div class="chart-container">
        <div class="chart-title">大级别: {PERIOD_SPECS[periods[0]]['label']}</div>
        <div id="chart-0" class="chart-dom"></div>
    </div>
    <div class="chart-container">
        <div class="chart-title">中级别: {PERIOD_SPECS[periods[1]]['label']}</div>
        <div id="chart-1" class="chart-dom"></div>
    </div>
    <div class="chart-container">
        <div class="chart-title">小级别 (区间套执行): {PERIOD_SPECS[periods[2]]['label']}</div>
        <div id="chart-2" class="chart-dom"></div>
    </div>

    <script>
        const DATA = {payload_json};
        const periods = DATA.periods;

        // 填充共振表格
        const tbody = document.getElementById('res-tbody');
        if (DATA.resonances.length === 0) {{
            tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; color:#888;">当前选定周期组合未捕捉到强共振信号，建议关注单级别中枢突破。</td></tr>';
        }} else {{
            DATA.resonances.forEach(r => {{
                const tr = document.createElement('tr');
                const isBuy = r.direction === 'BUY';
                tr.innerHTML = `
                    <td>${{r.timestamp}}</td>
                    <td class="${{isBuy ? 'badge-buy' : 'badge-sell'}}">${{isBuy ? '▲ 买点' : '▼ 卖点'}}</td>
                    <td><span style="background:${{isBuy ? '#d32f2f' : '#00796b'}}; padding:2px 6px; border-radius:4px; font-size:11px;">${{r.grade}}</span></td>
                    <td style="font-weight:bold; color:#ffffff;">${{r.pattern_name}}</td>
                    <td>¥${{r.price.toFixed(2)}}</td>
                    <td>${{r.desc}}</td>
                `;
                tbody.appendChild(tr);
            }});
        }}

        // 初始化三张 ECharts 图表
        const chartInstances = [];
        periods.forEach((p, idx) => {{
            const dom = document.getElementById(`chart-${{idx}}`);
            const myChart = echarts.init(dom, 'dark');
            chartInstances.push(myChart);

            const pData = DATA.charts[p];
            const dates = pData.dates;
            const candles = pData.candles;

            // 笔线条 markLine
            const markLineData = [];
            pData.bis.forEach(b => {{
                markLineData.push([
                    {{ coord: [dates[b.start_idx], b.start_val], lineStyle: {{ color: '#f0b90b', width: 2 }} }},
                    {{ coord: [dates[b.end_idx], b.end_val] }}
                ]);
            }});

            // 中枢矩形 markArea
            const markAreaData = [];
            pData.zss.forEach(zs => {{
                markAreaData.push([
                    {{
                        coord: [dates[zs.start_idx], zs.zg],
                        itemStyle: {{ color: 'rgba(41, 98, 255, 0.22)', borderColor: '#2962ff', borderWidth: 1, borderType: 'dashed' }}
                    }},
                    {{ coord: [dates[zs.end_idx], zs.zd] }}
                ]);
            }});

            // 买卖点 markPoint
            const markPointData = [];
            pData.mmds.forEach(m => {{
                const isBuy = m.type.includes('buy');
                markPointData.push({{
                    coord: [dates[m.idx], m.val],
                    value: m.type.toUpperCase().replace('BUY', 'B').replace('SELL', 'S'),
                    itemStyle: {{ color: isBuy ? '#f23645' : '#089981' }},
                    symbol: isBuy ? 'pin' : 'arrow',
                    symbolSize: 28,
                    symbolRotate: isBuy ? 0 : 180,
                }});
            }});

            // 注入共振星标
            DATA.resonances.forEach(r => {{
                const barIdx = (idx === 0) ? r.high_bar_idx : ((idx === 1) ? r.mid_bar_idx : r.low_bar_idx);
                if (barIdx >= 0 && barIdx < dates.length) {{
                    markPointData.push({{
                        coord: [dates[barIdx], r.price],
                        value: r.direction === 'BUY' ? '★共振买' : '▼共振卖',
                        itemStyle: {{ color: r.direction === 'BUY' ? '#ffd600' : '#00e5ff' }},
                        label: {{ color: '#000000', fontWeight: 'bold', fontSize: 10 }},
                        symbol: 'diamond',
                        symbolSize: 34,
                    }});
                }}
            }});

            const option = {{
                backgroundColor: '#181b27',
                animation: false,
                tooltip: {{
                    trigger: 'axis',
                    axisPointer: {{ type: 'cross' }},
                    backgroundColor: 'rgba(30, 34, 45, 0.95)',
                    borderColor: '#434651',
                    textStyle: {{ color: '#d1d4dc' }}
                }},
                axisPointer: {{ link: [{{ xAxisIndex: 'all' }}] }},
                grid: [
                    {{ left: '3%', right: '4%', top: '8%', height: '58%' }},
                    {{ left: '3%', right: '4%', top: '72%', height: '20%' }}
                ],
                xAxis: [
                    {{
                        type: 'category',
                        data: dates,
                        gridIndex: 0,
                        axisLine: {{ lineStyle: {{ color: '#434651' }} }},
                        axisLabel: {{ show: false }}
                    }},
                    {{
                        type: 'category',
                        data: dates,
                        gridIndex: 1,
                        axisLine: {{ lineStyle: {{ color: '#434651' }} }},
                        axisLabel: {{ color: '#888', fontSize: 11 }}
                    }}
                ],
                yAxis: [
                    {{
                        type: 'value',
                        scale: true,
                        gridIndex: 0,
                        position: 'right',
                        axisLine: {{ lineStyle: {{ color: '#434651' }} }},
                        splitLine: {{ lineStyle: {{ color: '#242838' }} }}
                    }},
                    {{
                        type: 'value',
                        scale: true,
                        gridIndex: 1,
                        position: 'right',
                        axisLine: {{ lineStyle: {{ color: '#434651' }} }},
                        splitLine: {{ lineStyle: {{ color: '#242838' }} }}
                    }}
                ],
                dataZoom: [
                    {{ type: 'inside', xAxisIndex: [0, 1], start: 40, end: 100 }},
                    {{ type: 'slider', xAxisIndex: [0, 1], top: '94%', height: 16 }}
                ],
                series: [
                    {{
                        name: 'K线',
                        type: 'candlestick',
                        data: candles,
                        itemStyle: {{
                            color: '#f23645',
                            color0: '#089981',
                            borderColor: '#f23645',
                            borderColor0: '#089981'
                        }},
                        markLine: {{ data: markLineData, symbol: ['circle', 'circle'] }},
                        markArea: {{ data: markAreaData }},
                        markPoint: {{ data: markPointData }}
                    }},
                    {{
                        name: 'MACD',
                        type: 'bar',
                        xAxisIndex: 1,
                        yAxisIndex: 1,
                        data: (pData.macd.hist || []).map(h => ({{
                            value: h * 2,
                            itemStyle: {{ color: h >= 0 ? '#f23645' : '#089981' }}
                        }}))
                    }},
                    {{
                        name: 'DIF',
                        type: 'line',
                        xAxisIndex: 1,
                        yAxisIndex: 1,
                        data: pData.macd.dif || [],
                        lineStyle: {{ color: '#ffffff', width: 1.2 }}
                    }},
                    {{
                        name: 'DEA',
                        type: 'line',
                        xAxisIndex: 1,
                        yAxisIndex: 1,
                        data: pData.macd.dea || [],
                        lineStyle: {{ color: '#f0b90b', width: 1.2 }}
                    }}
                ]
            }};

            myChart.setOption(option);
        }});

        window.addEventListener('resize', () => {{
            chartInstances.forEach(c => c.resize());
        }});
    </script>
</body>
</html>
"""
    out_file.write_text(html_template, encoding="utf-8")
    logger.info(f"交互式 HTML 全景报告已生成: {out_file.resolve()}")
    return out_file


# ==============================================================================
# 5. 主流程与调度器
# ==============================================================================


def analyze_and_plot_resonance(
    code: str = "000001",
    periods: list[str] | str | None = None,
    bars_count: int = 140,
    save_png: bool = True,
    save_html: bool = False,
    show_window: bool = False,
    output_png_path: str | Path | None = None,
    output_html_path: str | Path | None = None,
) -> dict[str, Any]:
    """多周期立体共振分析与图表生成主函数。

    Args:
        code: 证券代码 (如 "000001", "600519")
        periods: 选定的 3 个周期 (支持逗号分隔字符串或列表，默认 "WEEK,DAY,30F")
        bars_count: 每个周期拉取的 K 线根数 (默认 140)
        save_png: 是否生成 PNG 高清图
        save_html: 是否生成交互式 HTML
        show_window: 是否调用 plt.show() 弹窗展示
        output_png_path: 指定 PNG 保存路径
        output_html_path: 指定 HTML 保存路径

    Returns:
        包含分析结果、共振列表及文件路径的字典
    """
    clean_code = (
        str(code)
        .strip()
        .upper()
        .replace("SZ", "")
        .replace("SH", "")
        .replace("BJ", "")
    )

    # 1. 规范化周期
    if periods is None:
        p_list = ["WEEK", "DAY", "30F"]
    elif isinstance(periods, str):
        p_list = parse_three_periods(periods)
    else:
        p_list = sorted(
            [normalize_period(p) for p in periods],
            key=lambda k: PERIOD_SPECS[k]["weight"],
            reverse=True,
        )
        if len(p_list) != 3:
            raise ValueError(f"必须恰好提供 3 个周期，当前提供了: {periods}")

    name = get_stock_name(clean_code) or "标的资产"
    logger.info(
        f"🚀 开始执行【{clean_code} {name}】缠论多周期立体共振分析: "
        f"[{PERIOD_SPECS[p_list[0]]['short_name']} · {PERIOD_SPECS[p_list[1]]['short_name']} · {PERIOD_SPECS[p_list[2]]['short_name']}]"
    )

    # 2. 拉取 3 个周期的 K 线数据
    dfs: dict[str, pd.DataFrame] = {}
    for p in p_list:
        spec = PERIOD_SPECS[p]
        cat_str = spec["market_cat"]
        logger.info(f"正在拉取 {spec['label']} 数据 (count={bars_count})...")
        df = fetch_security_kline(clean_code, category=cat_str, count=bars_count)
        if df is None or df.empty:
            logger.warning(f"未能获取到 {p} 级别 K 线数据！")
            df = pd.DataFrame(columns=["datetime", "open", "high", "low", "close", "volume", "amount"])
        dfs[p] = df

    # 3. 运行缠论分析计算管道
    results: dict[str, ChanlunResult] = {}
    for p in p_list:
        spec = PERIOD_SPECS[p]
        analyser = ChanlunAnalyser(code=clean_code, frequency=spec["chan_freq"])
        res = analyser.process_klines(dfs[p])
        results[p] = res
        logger.info(
            f"✅ {spec['short_name']} 计算完毕: K线={len(res.klines)}根, "
            f"笔={len(res.bis)}笔, 中枢={len(res.zss)}个, 买卖点={len(res.mmds)}个"
        )

    # 4. 运行三周期共振引擎
    engine = ThreePeriodResonanceEngine(p_list[0], p_list[1], p_list[2], results)
    resonances = engine.scan_resonances()

    logger.info(f"🎯 三周期立体共振扫描完成，共识别出 {len(resonances)} 个买卖点共振事件！")
    for r in resonances:
        logger.info(f"   [{r.grade}] {r.timestamp} {r.pattern_name} @ ¥{r.price:.2f}")

    # 5. 绘制并输出高清 PNG 图表
    png_path = None
    if save_png or show_window:
        plotter = ChanlunResonancePlotter(clean_code, name, p_list, dfs, results, resonances)
        png_path = plotter.plot(save_path=output_png_path, show=show_window)

    # 6. 生成交互式 HTML 报告
    html_path = None
    if save_html:
        if output_html_path is None:
            out_dir = PROJECT_ROOT / "output"
            out_dir.mkdir(parents=True, exist_ok=True)
            p_tag = "_".join(p_list)
            output_html_path = out_dir / f"chanlun_resonance_{clean_code}_{p_tag}.html"
        html_path = export_interactive_html(
            clean_code, name, p_list, dfs, results, resonances, output_html_path
        )

    return {
        "code": clean_code,
        "name": name,
        "periods": p_list,
        "dfs": dfs,
        "results": results,
        "resonances": resonances,
        "png_path": str(png_path) if png_path else None,
        "html_path": str(html_path) if html_path else None,
    }


def main():
    parser = argparse.ArgumentParser(
        description="缠论理论多周期共振买卖点 K线图分析系统 (支持月线/周线/日线/120F/60F/30F/15F/5F 自选三周期)"
    )
    parser.add_argument(
        "--code", "-c",
        type=str,
        default="000001",
        help="股票代码 (如 000001, 600519, 300750，默认 000001)",
    )
    parser.add_argument(
        "--periods", "-p",
        type=str,
        default="WEEK,DAY,30F",
        help=(
            "自选 3 个周期，逗号分隔 (默认: WEEK,DAY,30F)。\n"
            "可选范围: MONTH, WEEK, DAY, 120F, 60F, 30F, 15F, 5F (亦支持中文如 周线,日线,30分钟)"
        ),
    )
    parser.add_argument(
        "--bars", "-b",
        type=int,
        default=130,
        help="每个周期抓取的 K 线数量 (默认 130 根)",
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        default=None,
        help="输出 PNG 图片保存路径 (默认保存到 output/ 目录)",
    )
    parser.add_argument(
        "--html",
        action="store_true",
        help="同时生成交互式 ECharts HTML 报告并在浏览器中自适应查看",
    )
    parser.add_argument(
        "--show", "-s",
        action="store_true",
        help="运行后直接弹出 Matplotlib 交互窗口查看 (适用于桌面环境)",
    )

    args = parser.parse_args()

    try:
        ret = analyze_and_plot_resonance(
            code=args.code,
            periods=args.periods,
            bars_count=args.bars,
            save_png=True,
            save_html=args.html,
            show_window=args.show,
            output_png_path=args.output,
        )

        print("\n" + "=" * 70)
        print(f"📊 【{ret['code']} {ret['name']}】缠论多周期立体共振分析报告")
        print("=" * 70)
        print(f"周期组合: {' -> '.join([PERIOD_SPECS[p]['short_name'] for p in ret['periods']])}")
        if ret["png_path"]:
            print(f"🖼  高清 K线图: {ret['png_path']}")
        if ret["html_path"]:
            print(f"🌐 交互式网页: {ret['html_path']}")

        resonances = ret["resonances"]
        print(f"\n共振买卖点事件数量: {len(resonances)}")
        if resonances:
            print("-" * 70)
            print(f"{'触发时间':<18} {'方向':<6} {'评级':<6} {'价格':<9} {'形态名称'}")
            print("-" * 70)
            for r in resonances:
                dir_str = "买点 ▲" if r.direction == "BUY" else "卖点 ▼"
                print(f"{r.timestamp:<18} {dir_str:<6} {r.grade:<6} {r.price:<9.2f} {r.pattern_name}")
            print("-" * 70)
        else:
            print("注: 选定周期内未发现强共振买卖点，建议结合中枢震荡与单级别拐点综合研判。")
        print("=" * 70 + "\n")

    except Exception as e:
        logger.exception(f"执行失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
