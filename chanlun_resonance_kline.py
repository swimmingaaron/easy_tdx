#!/usr/bin/env python3
"""
缠论理论多周期共振买卖点 K线图分析系统 (Python 脚本)
========================================================================

支持周期：
    月线 (MONTH) | 周线 (WEEK) | 日线 (DAY) | 120F (120分钟) |
    60F (60分钟) | 30F (30分钟) | 15F (15分钟) | 5F (5分钟)

默认周期组合：
    日线 (DAY) + 30F (30分钟) + 5F (5分钟)
    （用户可通过 --periods 参数自由指定任意 3 个周期的立体共振分析）

核心设计（全新升级）：
1. 【以最小周期K线为基准，将 3 个周期画在同一图片中 (同图立体呈现)】：
   - 底图：以选定的最小周期（默认 5F 分钟线，保证1500周期）的每一根真实 K 线作为主水平坐标轴基准；
   - 大级别 (如日线)：鲜亮洋红粗折线 (实线厚笔) + 紫色半透明宏观中枢箱体 + [日]买卖点；
   - 中级别 (如30F)：亮青色中粗折线 (波段笔) + 青蓝半透明中枢箱体 + [30F]买卖点；
   - 小级别 (如5F)：金黄色细折线 (微观笔) + 琥珀橙半透明微观中枢 + 1B/2B/3B买卖点；
   - 三周期共振：贯穿主副图的荧光垂直穿透光柱 + 极具辨识度的黄金/霓虹星形大徽章：
     「★ [日·30F·5F] 三周期共振买点 (AAA级) ¥XX.XX」
   - 副图：基准小周期的 MACD 动能图 (DIF/DEA/红绿柱)，与各周期笔背驰直接印证。

2. 三周期立体共振买卖点引擎 (Three-Period Resonance Engine)：
   - 大级别 (宏观趋势定方向)：周线/月线确定大方向，处于向上笔、底背驰或大级别买点区间；
   - 中级别 (波段形态定走势)：日线/60F 确定波段结构，形成中枢震荡、突破或回踩确立；
   - 小级别 (微观入场定买点 - 区间套)：30F/15F/5F 精准捕捉底背驰、二买启动或三买爆发点。
   - 评级分类：AAA级 (全同构顶级共振，如全一买/全二买/全三买)、AA级 (复合强共振)、A级 (立体趋势共振)。

3. 双模图表可视化：
   - 默认模式：以最小周期为基准，将 3 个级别画在同一张高清暗黑专业金融 K 线图中 (PNG)；
   - 分屏模式 (--split)：亦可选择分 3 个独立子面板并列排布；
   - 交互式 HTML 报告 (--html)：内置 ECharts 联动缩放与十字光标，图例可一键切换开启/隐藏周线笔、日线笔、30F笔与中枢。

使用示例：
    # 1. 默认参数 (以 30F 为基准，同图画周线/日线/30F 三级笔与中枢)
    python chanlun_resonance_kline.py --code 000001

    # 2. 自选三个周期：日线 + 60分钟 + 15分钟 (以 15F 为基准画同图)
    python chanlun_resonance_kline.py --code 600519 --periods DAY,60F,15F

    # 3. 宏观长线周期：月线 + 周线 + 日线 (以 日线 为基准画同图)
    python chanlun_resonance_kline.py --code 300750 --periods MONTH,WEEK,DAY

    # 4. 生成交互式 HTML 网页并在浏览器中查看
    python chanlun_resonance_kline.py --code 000001 --html --show
"""

from __future__ import annotations

import argparse
import bisect
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


def parse_three_periods(periods_str: str | None = None) -> list[str]:
    """解析并校验 3 个周期，按大级别到小级别自动排序返回。"""
    if not periods_str:
        return ["DAY", "30F", "5F"]

    parts = [p.strip() for p in str(periods_str).replace("，", ",").split(",") if p.strip()]
    if len(parts) != 3:
        raise ValueError(f"必须恰好指定 3 个周期，当前输入了 {len(parts)} 个: {periods_str}")

    normalized = [normalize_period(p) for p in parts]
    if len(set(normalized)) != 3:
        raise ValueError(f"选择的 3 个周期不能重复: {normalized}")

    # 按照权重从大到小排序（大级别在上，小级别为底图基准）
    sorted_periods = sorted(normalized, key=lambda k: PERIOD_SPECS[k]["weight"], reverse=True)
    return sorted_periods


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

        # 预先构建各周期时间戳索引与买卖点时间轴，加速状态检索到 O(log N)
        self._period_cache: dict[str, dict[str, Any]] = {}
        for p in (high_period, mid_period, low_period):
            res = results.get(p)
            if not res or not res.klines:
                self._period_cache[p] = {
                    "klines": [],
                    "k_dts": [],
                    "bis": [],
                    "bi_starts": [],
                    "mmd_entries": [],
                    "mmd_dts": [],
                    "is_intra": "min" in p.lower() or "f" in p.lower() or "m" in p.lower(),
                }
                continue

            k_dts = [_to_dt(k.date) for k in res.klines]
            bis = res.bis or []
            bi_starts = [bi.start.k.k_index for bi in bis]

            mmd_entries = []
            for mmd in (res.mmds or []):
                if mmd.bi:
                    mmd_entries.append((_to_dt(mmd.bi.end.k.date), mmd))
            mmd_entries.sort(key=lambda x: x[0])
            mmd_dts = [x[0] for x in mmd_entries]

            self._period_cache[p] = {
                "klines": res.klines,
                "k_dts": k_dts,
                "bis": bis,
                "bi_starts": bi_starts,
                "mmd_entries": mmd_entries,
                "mmd_dts": mmd_dts,
                "is_intra": "min" in p.lower() or "f" in p.lower() or "m" in p.lower(),
            }

    def _get_period_state_at(self, period: str, target_dt: Any) -> PeriodState:
        """评估指定周期在某一时间戳 target_dt 的多空状态。"""
        target_obj = _to_dt(target_dt)
        cache = self._period_cache.get(period)
        if not cache or not cache["klines"]:
            return PeriodState(period, -1, "", 0.0, "none")

        klines = cache["klines"]
        k_dts = cache["k_dts"]

        # 二分查找 target_obj 对应的最大 bar_idx (k_dts[i] <= target_obj)
        pos = bisect.bisect_right(k_dts, target_obj) - 1
        if pos < 0:
            bar_idx = 0
        else:
            bar_idx = min(pos, len(klines) - 1)

        cur_k = klines[bar_idx]
        is_intra = cache["is_intra"]
        cur_date_str = _fmt_dt(cur_k.date, is_intraday=is_intra)

        # 二分查找当前活跃笔 (bi.start.k.k_index <= bar_idx)
        active_bi = None
        bi_starts = cache["bi_starts"]
        if bi_starts:
            bi_pos = bisect.bisect_right(bi_starts, bar_idx) - 1
            if bi_pos >= 0:
                active_bi = cache["bis"][bi_pos]

        bi_dir = active_bi.direction.value if active_bi else "none"
        bi_s_val = active_bi.start.val if active_bi else 0.0
        bi_e_val = active_bi.end.val if active_bi else 0.0

        # 二分查找 target_obj 之前的最近买卖点
        mmd_dts = cache["mmd_dts"]
        last_mmd = None
        if mmd_dts:
            mmd_pos = bisect.bisect_right(mmd_dts, target_obj) - 1
            if mmd_pos >= 0:
                last_mmd = cache["mmd_entries"][mmd_pos][1]

        mmd_type = last_mmd.mmd_type.value if last_mmd else ""
        mmd_dt = (
            _fmt_dt(last_mmd.bi.end.k.date, is_intraday=is_intra)
            if last_mmd and last_mmd.bi
            else ""
        )
        bars_ago = (
            (bar_idx - last_mmd.bi.end.k.k_index)
            if last_mmd and last_mmd.bi
            else 999
        )

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

        trigger_events = sorted(trigger_events, key=lambda x: _to_dt(x["dt"]))

        for ev in trigger_events:
            target_dt = ev["dt"]
            is_buy = ev["is_buy"]

            low_state = self._get_period_state_at(self.p_low, target_dt)
            mid_state = self._get_period_state_at(self.p_mid, target_dt)
            high_state = self._get_period_state_at(self.p_high, target_dt)

            is_intra = (
                "min" in self.p_low.lower()
                or "f" in self.p_low.lower()
                or "m" in self.p_low.lower()
            )

            if is_buy:
                if mid_state.is_bullish and high_state.is_bullish:
                    grade, name = self._classify_resonance(
                        "BUY", high_state, mid_state, ev["type"]
                    )
                    desc = (
                        f"【{name}】\n"
                        f"- {self.p_high}(大): {high_state.detail}\n"
                        f"- {self.p_mid}(中): {mid_state.detail}\n"
                        f"- {self.p_low}(小): 触发 {ev['type'].upper()} ({ev['price']:.2f})"
                    )
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
                if mid_state.is_bearish and high_state.is_bearish:
                    grade, name = self._classify_resonance(
                        "SELL", high_state, mid_state, ev["type"]
                    )
                    desc = (
                        f"【{name}】\n"
                        f"- {self.p_high}(大): {high_state.detail}\n"
                        f"- {self.p_mid}(中): {mid_state.detail}\n"
                        f"- {self.p_low}(小): 触发 {ev['type'].upper()} ({ev['price']:.2f})"
                    )
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
        p_names = f"{PERIOD_SPECS[self.p_high]['short_name']}·{PERIOD_SPECS[self.p_mid]['short_name']}·{PERIOD_SPECS[self.p_low]['short_name']}"

        if direction == "BUY":
            h_type = high.recent_mmd_type
            m_type = mid.recent_mmd_type
            if "1buy" in h_type and "1buy" in m_type and "1buy" in low_mmd:
                return "AAA", f"★ [{p_names}] 全一买区间套极限抄底"
            if "2buy" in h_type and "2buy" in m_type and "2buy" in low_mmd:
                return "AAA", f"★ [{p_names}] 全二买主升浪确立共振"
            if "3buy" in h_type and "3buy" in m_type and "3buy" in low_mmd:
                return "AAA", f"★ [{p_names}] 全三买中枢爆发共振"

            if "3buy" in low_mmd:
                return "AA", f"★ [{p_names}] 三类买点中枢突破共振"
            if "2buy" in low_mmd:
                return "AA", f"★ [{p_names}] 二类买点起跑共振"
            if "1buy" in low_mmd:
                return "AA", f"★ [{p_names}] 一类买点底背驰共振"

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
# 3. 高清同图立体嵌套 K 线图绘制器 (以最小周期为基准，将 3 个周期画在同一图片中)
# ==============================================================================


class ChanlunUnifiedResonancePlotter:
    """以最小周期 K 线为基准，将 3 个周期的 K 线、笔、中枢及共振买卖点画在同一张图片中。"""

    def __init__(
        self,
        code: str,
        name: str,
        periods: list[str],  # [High, Mid, Low]
        dfs: dict[str, pd.DataFrame],
        results: dict[str, ChanlunResult],
        resonances: list[ResonanceSignal],
    ):
        self.code = code
        self.name = name
        self.periods = periods
        self.p_high = periods[0]
        self.p_mid = periods[1]
        self.p_low = periods[2]  # 基准最小周期
        self.dfs = dfs
        self.results = results
        self.resonances = resonances

    def _map_pivot_to_base(
        self,
        dt_val: Any,
        val: float,
        is_high: bool,
        period_key: str,
        base_df: pd.DataFrame,
        base_dts: pd.Series,
    ) -> int:
        """将较高级别的笔分型端点精确对齐映射到基准小周期的某根 K 线索引。"""
        p_dt = _to_dt(dt_val)
        n_bars = len(base_df)
        if n_bars == 0:
            return 0
        if p_dt < base_dts.iloc[0]:
            return -1
        if p_dt > base_dts.iloc[-1]:
            return n_bars - 1

        if period_key == "WEEK":
            w_start = (p_dt - pd.Timedelta(days=6)).date()
            w_end = (p_dt + pd.Timedelta(days=1)).date()
            mask = (base_dts.dt.date >= w_start) & (base_dts.dt.date <= w_end)
        elif period_key == "DAY":
            mask = base_dts.dt.date == p_dt.date()
        elif period_key == "MONTH":
            mask = (base_dts.dt.year == p_dt.year) & (base_dts.dt.month == p_dt.month)
        else:
            diffs = np.abs((base_dts - p_dt).dt.total_seconds().values)
            return int(np.argmin(diffs))

        idxs = np.where(mask)[0]
        if len(idxs) > 0:
            if is_high:
                sub_vals = base_df["high"].iloc[idxs].values
                return int(idxs[np.argmax(sub_vals)])
            else:
                sub_vals = base_df["low"].iloc[idxs].values
                return int(idxs[np.argmin(sub_vals)])

        diffs = np.abs((base_dts - p_dt).dt.total_seconds().values)
        return int(np.argmin(diffs))

    def plot(self, save_path: str | Path | None = None, show: bool = False) -> Path | None:
        """在单张画板中绘制同图多周期立体嵌套图。"""
        import matplotlib
        if not show:
            matplotlib.use("Agg")
        import matplotlib.patches as patches
        import matplotlib.pyplot as plt

        plt.rcParams["font.sans-serif"] = [
            "Microsoft YaHei",
            "SimHei",
            "PingFang SC",
            "WenQuanYi Micro Hei",
            "sans-serif",
        ]
        plt.rcParams["axes.unicode_minus"] = False

        base_df = self.dfs[self.p_low]
        base_res = self.results[self.p_low]
        res_mid = self.results[self.p_mid]
        res_high = self.results[self.p_high]

        n_bars = len(base_df)
        if n_bars == 0:
            logger.warning("基准最小周期数据为空，无法绘图")
            return None

        base_dts = pd.to_datetime(base_df["datetime"].astype(str))

        # 画布尺寸：宽 18 吋，高 12 吋
        fig = plt.figure(figsize=(18, 12), facecolor="#131722")
        gs = fig.add_gridspec(
            2,
            1,
            height_ratios=[3.8, 1.0],
            hspace=0.06,
            left=0.04,
            right=0.96,
            top=0.93,
            bottom=0.05,
        )

        ax_main = fig.add_subplot(gs[0, 0])
        ax_main.set_facecolor("#181b27")
        ax_macd = fig.add_subplot(gs[1, 0])
        ax_macd.set_facecolor("#181b27")

        # ----------------------------------------------------------------------
        # 1. 绘制基准最小周期 K 线 (Candlesticks)
        # ----------------------------------------------------------------------
        bar_width = 0.65
        price_span = base_df["high"].max() - base_df["low"].min()
        min_body = price_span * 0.002 or 0.01

        for i in range(n_bars):
            row = base_df.iloc[i]
            op = float(row["open"])
            cl = float(row["close"])
            hi = float(row["high"])
            lo = float(row["low"])

            is_up = cl >= op
            c_color = "#f23645" if is_up else "#089981"

            ax_main.plot([i, i], [lo, hi], color=c_color, linewidth=1.1, zorder=3)
            body_y = min(op, cl)
            body_h = max(abs(cl - op), min_body)
            rect = patches.Rectangle(
                (i - bar_width / 2, body_y),
                bar_width,
                body_h,
                facecolor=c_color,
                edgecolor=c_color,
                linewidth=0.8,
                zorder=4,
            )
            ax_main.add_patch(rect)

        # ----------------------------------------------------------------------
        # 2. 绘制大级别 (Level 1, 如周线) 笔与中枢 (洋红/紫罗兰色，最粗)
        # ----------------------------------------------------------------------
        high_name = PERIOD_SPECS[self.p_high]["short_name"]
        c_high = "#e040fb"  # 亮紫色
        bg_high = "#9c27b0"

        # 大级别中枢
        for zs in res_high.zss:
            if not zs.start or not zs.end:
                continue
            x_s = self._map_pivot_to_base(zs.start.k.date, zs.zd, False, self.p_high, base_df, base_dts)
            x_e = self._map_pivot_to_base(zs.end.k.date, zs.zg, True, self.p_high, base_df, base_dts)
            if x_e < 0 or x_s >= n_bars:
                continue
            x_s = max(0, x_s)
            x_e = min(n_bars - 1, x_e)
            zs_w = max(1.0, x_e - x_s)
            zs_h = max(0.01, zs.zg - zs.zd)

            rect = patches.Rectangle(
                (x_s, zs.zd),
                zs_w,
                zs_h,
                facecolor=bg_high,
                edgecolor=c_high,
                alpha=0.15,
                linestyle="-.",
                linewidth=1.6,
                zorder=2,
            )
            ax_main.add_patch(rect)
            ax_main.hlines([zs.zg, zs.zd], xmin=x_s, xmax=x_e, colors=c_high, linestyles="-.", linewidths=1.2, alpha=0.8, zorder=2)
            mid_x = (x_s + x_e) / 2
            ax_main.text(mid_x, zs.zg, f"[{high_name}中枢 {zs.zd:.2f}~{zs.zg:.2f}]", color=c_high, fontsize=8.5, ha="center", va="bottom", alpha=0.9, zorder=5)

        # 大级别笔
        high_bi_pts = []
        for bi in res_high.bis:
            s_idx = self._map_pivot_to_base(bi.start.k.date, bi.start.val, bi.direction.value == "down", self.p_high, base_df, base_dts)
            e_idx = self._map_pivot_to_base(bi.end.k.date, bi.end.val, bi.direction.value == "up", self.p_high, base_df, base_dts)
            if s_idx < 0 and e_idx < 0:
                continue
            s_clamp = max(0, s_idx)
            e_clamp = max(0, min(n_bars - 1, e_idx))
            high_bi_pts.append((s_clamp, bi.start.val, e_clamp, bi.end.val))

        for seg_i, (sx, sy, ex, ey) in enumerate(high_bi_pts):
            lbl = f"大级别 ({high_name}) 笔" if seg_i == 0 else ""
            ax_main.plot(
                [sx, ex], [sy, ey],
                color=c_high,
                linewidth=3.6,
                linestyle="-",
                marker="o",
                markersize=7.5,
                markerfacecolor="#ffffff",
                markeredgecolor=c_high,
                alpha=0.95,
                label=lbl,
                zorder=7,
            )

        # ----------------------------------------------------------------------
        # 3. 绘制中级别 (Level 2, 如日线) 笔与中枢 (青蓝色，中粗)
        # ----------------------------------------------------------------------
        mid_name = PERIOD_SPECS[self.p_mid]["short_name"]
        c_mid = "#00e5ff"  # 亮青色
        bg_mid = "#00bcd4"

        # 中级别中枢
        for zs in res_mid.zss:
            if not zs.start or not zs.end:
                continue
            x_s = self._map_pivot_to_base(zs.start.k.date, zs.zd, False, self.p_mid, base_df, base_dts)
            x_e = self._map_pivot_to_base(zs.end.k.date, zs.zg, True, self.p_mid, base_df, base_dts)
            if x_e < 0 or x_s >= n_bars:
                continue
            x_s = max(0, x_s)
            x_e = min(n_bars - 1, x_e)
            zs_w = max(1.0, x_e - x_s)
            zs_h = max(0.01, zs.zg - zs.zd)

            rect = patches.Rectangle(
                (x_s, zs.zd),
                zs_w,
                zs_h,
                facecolor=bg_mid,
                edgecolor=c_mid,
                alpha=0.18,
                linestyle="--",
                linewidth=1.4,
                zorder=2,
            )
            ax_main.add_patch(rect)
            ax_main.hlines([zs.zg, zs.zd], xmin=x_s, xmax=x_e, colors=c_mid, linestyles="--", linewidths=1.0, alpha=0.8, zorder=2)
            mid_x = (x_s + x_e) / 2
            ax_main.text(mid_x, zs.zd, f"[{mid_name}中枢 {zs.zd:.2f}~{zs.zg:.2f}]", color=c_mid, fontsize=8.0, ha="center", va="top", alpha=0.9, zorder=5)

        # 中级别笔
        mid_bi_pts = []
        for bi in res_mid.bis:
            s_idx = self._map_pivot_to_base(bi.start.k.date, bi.start.val, bi.direction.value == "down", self.p_mid, base_df, base_dts)
            e_idx = self._map_pivot_to_base(bi.end.k.date, bi.end.val, bi.direction.value == "up", self.p_mid, base_df, base_dts)
            if s_idx < 0 and e_idx < 0:
                continue
            s_clamp = max(0, s_idx)
            e_clamp = max(0, min(n_bars - 1, e_idx))
            mid_bi_pts.append((s_clamp, bi.start.val, e_clamp, bi.end.val))

        for seg_i, (sx, sy, ex, ey) in enumerate(mid_bi_pts):
            lbl = f"中级别 ({mid_name}) 笔" if seg_i == 0 else ""
            ax_main.plot(
                [sx, ex], [sy, ey],
                color=c_mid,
                linewidth=2.4,
                linestyle="-",
                marker="o",
                markersize=5.0,
                markerfacecolor="#ffffff",
                markeredgecolor=c_mid,
                alpha=0.92,
                label=lbl,
                zorder=8,
            )

        # ----------------------------------------------------------------------
        # 4. 绘制小级别 (Level 3, 基准 30F) 笔与中枢 (金黄色细线)
        # ----------------------------------------------------------------------
        low_name = PERIOD_SPECS[self.p_low]["short_name"]
        c_low = "#ffd600"  # 金黄色
        bg_low = "#ff9800"

        # 小级别中枢
        for zs in base_res.zss:
            if not zs.start or not zs.end:
                continue
            s_idx = max(0, zs.start.k.k_index)
            e_idx = min(n_bars - 1, zs.end.k.k_index)
            if e_idx < s_idx:
                continue
            zs_w = max(1.0, e_idx - s_idx)
            zs_h = max(0.01, zs.zg - zs.zd)
            rect = patches.Rectangle(
                (s_idx, zs.zd),
                zs_w,
                zs_h,
                facecolor=bg_low,
                edgecolor="#ffa726",
                alpha=0.20,
                linestyle=":",
                linewidth=1.2,
                zorder=2,
            )
            ax_main.add_patch(rect)
            ax_main.hlines([zs.zg, zs.zd], xmin=s_idx, xmax=e_idx, colors="#ffa726", linestyles=":", linewidths=0.9, alpha=0.85, zorder=2)
            mid_x = (s_idx + e_idx) / 2
            ax_main.text(mid_x, zs.zg, f"[{low_name}中枢]", color="#ffa726", fontsize=7.5, ha="center", va="bottom", alpha=0.9, zorder=5)

        # 小级别笔
        if base_res.bis:
            low_bi_x = []
            low_bi_y = []
            for bi in base_res.bis:
                low_bi_x.append(bi.start.k.k_index)
                low_bi_y.append(bi.start.val)
            last_bi = base_res.bis[-1]
            low_bi_x.append(last_bi.end.k.k_index)
            low_bi_y.append(last_bi.end.val)

            ax_main.plot(
                low_bi_x,
                low_bi_y,
                color=c_low,
                linewidth=1.4,
                linestyle="-",
                marker="o",
                markersize=3.0,
                markerfacecolor="#ffffff",
                markeredgecolor=c_low,
                alpha=0.88,
                label=f"小级别 ({low_name}) 笔",
                zorder=9,
            )

        # ----------------------------------------------------------------------
        # 5. 绘制买卖点标签 (基准小级别 MMDs)
        # ----------------------------------------------------------------------
        offset = max(price_span * 0.04, 0.15)
        for mmd in base_res.mmds:
            if not mmd.bi:
                continue
            k_idx = mmd.bi.end.k.k_index
            if 0 <= k_idx < n_bars:
                val = mmd.bi.end.val
                mtype = mmd.mmd_type.value
                is_buy = "buy" in mtype
                short_tag = mtype.upper().replace("BUY", "B").replace("SELL", "S")
                c_tag = "#f23645" if is_buy else "#089981"
                ax_main.annotate(
                    f"▲{short_tag}" if is_buy else f"▼{short_tag}",
                    xy=(k_idx, val),
                    xytext=(k_idx, val - offset * 1.1 if is_buy else val + offset * 1.1),
                    ha="center",
                    va="top" if is_buy else "bottom",
                    fontsize=8.0,
                    fontweight="bold",
                    color="#ffffff",
                    bbox=dict(boxstyle="round,pad=0.2", facecolor=c_tag, edgecolor="#ffffff", alpha=0.9),
                    arrowprops=dict(facecolor=c_tag, edgecolor="#ffffff", shrink=0.1, width=0.8, headwidth=3.5),
                    zorder=10,
                )

        # ----------------------------------------------------------------------
        # 6. 高亮标注三周期共振买卖点 (Resonance Stars & Neon Guide Lines)
        # ----------------------------------------------------------------------
        for r in self.resonances:
            target_idx = r.low_bar_idx
            if 0 <= target_idx < n_bars:
                v_color = "#ffff00" if r.direction == "BUY" else "#00e5ff"
                # 穿透垂直线
                ax_main.axvline(x=target_idx, color=v_color, linestyle=":", linewidth=1.4, alpha=0.85, zorder=6)
                ax_macd.axvline(x=target_idx, color=v_color, linestyle=":", linewidth=1.4, alpha=0.85, zorder=6)

                badge_bg = "#e91e63" if r.direction == "BUY" else "#00b0ff"
                badge_text = (
                    f"★ 三周期共振买点 ({r.grade})\n[{high_name}·{mid_name}·{low_name}] ¥{r.price:.2f}"
                    if r.direction == "BUY"
                    else f"▼ 三周期共振卖点 ({r.grade})\n[{high_name}·{mid_name}·{low_name}] ¥{r.price:.2f}"
                )
                ax_main.annotate(
                    badge_text,
                    xy=(target_idx, r.price),
                    xytext=(target_idx, r.price - offset * 2.8 if r.direction == "BUY" else r.price + offset * 2.8),
                    ha="center",
                    va="top" if r.direction == "BUY" else "bottom",
                    fontsize=9.5,
                    fontweight="bold",
                    color="#ffffff",
                    bbox=dict(
                        boxstyle="round,pad=0.45",
                        facecolor=badge_bg,
                        edgecolor="#ffff00",
                        linewidth=1.8,
                        alpha=0.98,
                    ),
                    arrowprops=dict(
                        facecolor="#ffff00",
                        edgecolor="#ffffff",
                        shrink=0.08,
                        width=1.8,
                        headwidth=6.5,
                    ),
                    zorder=12,
                )

        # ----------------------------------------------------------------------
        # 7. 绘制副图 MACD (基准小级别)
        # ----------------------------------------------------------------------
        macd_data = base_res.macd
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
            ax_macd.legend(loc="upper left", facecolor="#181b27", edgecolor="#2d313f", fontsize=8.5, labelcolor="#e0e0e0")

        # ----------------------------------------------------------------------
        # 8. 图例与美化
        # ----------------------------------------------------------------------
        ax_main.legend(
            loc="upper left",
            facecolor="#181b27",
            edgecolor="#363c4e",
            fontsize=9.5,
            labelcolor="#ffffff",
            framealpha=0.88,
        )

        ax_main.set_ylim(
            bottom=base_df["low"].min() - offset * 3.2,
            top=base_df["high"].max() + offset * 3.2,
        )

        step = max(1, n_bars // 8)
        xticks = list(range(0, n_bars, step))
        if (n_bars - 1) not in xticks:
            xticks.append(n_bars - 1)

        is_intra = "min" in self.p_low.lower() or "f" in self.p_low.lower()
        xlabels = [
            str(base_df["datetime"].iloc[idx])[5:16] if is_intra else str(base_df["datetime"].iloc[idx])[:10]
            for idx in xticks
        ]
        ax_macd.set_xticks(xticks)
        ax_macd.set_xticklabels(xlabels, color="#9e9e9e", fontsize=8.5)
        ax_main.set_xticks([])

        ax_main.yaxis.tick_right()
        ax_macd.yaxis.tick_right()
        for ax in (ax_main, ax_macd):
            ax.tick_params(colors="#9e9e9e", labelsize=8.5)
            ax.grid(True, color="#252936", linestyle=":", linewidth=0.6, alpha=0.7)
            for spine in ax.spines.values():
                spine.set_color("#2d313f")

        # 顶部 Header 状态信息
        last_c = float(base_df["close"].iloc[-1])
        first_c = float(base_df["open"].iloc[0])
        chg = (last_c - first_c) / first_c * 100 if first_c else 0
        p_triplet = f"{high_name} · {mid_name} · {low_name}"

        res_summary = (
            f"共振信号: {len(self.resonances)} 个"
            if self.resonances
            else "当前三级多空平衡中"
        )
        if self.resonances:
            latest_r = self.resonances[-1]
            latest_str = f"最新共振: {latest_r.pattern_name} @ {latest_r.timestamp} (¥{latest_r.price:.2f})"
        else:
            latest_str = "最新状态: 走势中枢震荡推进"

        header_title = f"{self.code} {self.name} · 缠论多周期立体同图走势 [以 {PERIOD_SPECS[self.p_low]['label']} 为基准K线]"
        header_sub = f"嵌套周期: {p_triplet}   |   最新收盘: ¥{last_c:.2f} ({chg:+.2f}%)   |   {res_summary}   |   {latest_str}"

        fig.suptitle(
            header_title,
            fontsize=15,
            fontweight="bold",
            color="#ffffff",
            x=0.04,
            y=0.985,
            ha="left",
        )
        fig.text(
            0.04,
            0.952,
            header_sub,
            fontsize=10.0,
            color="#ffca28" if self.resonances else "#81c784",
            ha="left",
        )

        # 保存
        if save_path is None:
            out_dir = PROJECT_ROOT / "output"
            out_dir.mkdir(parents=True, exist_ok=True)
            p_tag = "_".join(self.periods)
            save_path = out_dir / f"chanlun_resonance_{self.code}_{p_tag}_unified.png"
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
        logger.info(f"以最小周期为基准的三周期同图 K 线图已保存至: {save_path.resolve()}")

        if show:
            plt.show()

        plt.close(fig)
        return save_path


# ==============================================================================
# 4. 独立分屏绘制器 (兼容 --split 参数)
# ==============================================================================


class ChanlunSplitResonancePlotter:
    """分屏模式绘制器（3 个独立垂直子图并列排布）。"""

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
        self.periods = periods
        self.dfs = dfs
        self.results = results
        self.resonances = resonances

    def plot(self, save_path: str | Path | None = None, show: bool = False) -> Path | None:
        import matplotlib
        if not show:
            matplotlib.use("Agg")
        import matplotlib.patches as patches
        import matplotlib.pyplot as plt

        plt.rcParams["font.sans-serif"] = [
            "Microsoft YaHei", "SimHei", "PingFang SC", "WenQuanYi Micro Hei", "sans-serif"
        ]
        plt.rcParams["axes.unicode_minus"] = False

        fig = plt.figure(figsize=(16, 18), facecolor="#131722")
        gs = fig.add_gridspec(
            6, 1, height_ratios=[3.2, 1.0, 3.2, 1.0, 3.2, 1.0],
            hspace=0.08, left=0.05, right=0.96, top=0.94, bottom=0.04
        )

        axes = []
        for row in range(6):
            ax = fig.add_subplot(gs[row, 0])
            ax.set_facecolor("#181b27")
            axes.append(ax)

        panels = [
            (self.periods[0], axes[0], axes[1]),
            (self.periods[1], axes[2], axes[3]),
            (self.periods[2], axes[4], axes[5]),
        ]

        for p_idx, (period_key, ax_main, ax_macd) in enumerate(panels):
            df = self.dfs[period_key]
            res = self.results[period_key]
            p_spec = PERIOD_SPECS[period_key]
            n_bars = len(df)
            if n_bars == 0:
                continue

            bar_width = 0.65
            price_span = df["high"].max() - df["low"].min()
            min_body = price_span * 0.002 or 0.01

            for i in range(n_bars):
                row = df.iloc[i]
                op, cl, hi, lo = float(row["open"]), float(row["close"]), float(row["high"]), float(row["low"])
                c_wick = "#f23645" if cl >= op else "#089981"
                ax_main.plot([i, i], [lo, hi], color=c_wick, linewidth=1.1, zorder=3)
                rect = patches.Rectangle(
                    (i - bar_width / 2, min(op, cl)),
                    bar_width, max(abs(cl - op), min_body),
                    facecolor=c_wick, edgecolor=c_wick, linewidth=0.8, zorder=4
                )
                ax_main.add_patch(rect)

            for zs in res.zss:
                if not zs.start or not zs.end:
                    continue
                s_idx, e_idx = max(0, zs.start.k.k_index), min(n_bars - 1, zs.end.k.k_index)
                if e_idx < s_idx:
                    continue
                rect = patches.Rectangle(
                    (s_idx, zs.zd), max(1.0, e_idx - s_idx), max(0.01, zs.zg - zs.zd),
                    facecolor="#2962ff", edgecolor="#2962ff", alpha=0.22, linestyle="--", linewidth=1.2, zorder=2
                )
                ax_main.add_patch(rect)

            if res.bis:
                bx = [bi.start.k.k_index for bi in res.bis] + [res.bis[-1].end.k.k_index]
                by = [bi.start.val for bi in res.bis] + [res.bis[-1].end.val]
                ax_main.plot(bx, by, color="#f0b90b", linewidth=1.8, marker="o", markersize=3.5, zorder=6)

            macd_data = res.macd
            if macd_data and "hist" in macd_data and len(macd_data["hist"]) == n_bars:
                hist = np.array(macd_data["hist"])
                for i in range(n_bars):
                    c_h = "#f23645" if hist[i] >= 0 else "#089981"
                    ax_macd.bar(i, hist[i] * 2, color=c_h, width=0.6, alpha=0.85)
                ax_macd.plot(range(n_bars), macd_data["dif"], color="#ffffff", linewidth=1.1)
                ax_macd.plot(range(n_bars), macd_data["dea"], color="#f0b90b", linewidth=1.1)

            ax_main.set_title(f"【{p_spec['label']}】", fontsize=11, color="#e0e0e0", loc="left")
            ax_main.set_xticks([])
            ax_macd.yaxis.tick_right()
            ax_main.yaxis.tick_right()

        if save_path is None:
            out_dir = PROJECT_ROOT / "output"
            out_dir.mkdir(parents=True, exist_ok=True)
            p_tag = "_".join(self.periods)
            save_path = out_dir / f"chanlun_resonance_{self.code}_{p_tag}_split.png"
        else:
            save_path = Path(save_path)
            save_path.parent.mkdir(parents=True, exist_ok=True)

        plt.savefig(save_path, dpi=150, facecolor=fig.get_facecolor(), bbox_inches="tight")
        if show:
            plt.show()
        plt.close(fig)
        return save_path


# ==============================================================================
# 5. 交互式 HTML 报告生成器 (ECharts，同图立体展示)
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
    """生成以最小周期为基准，三级别同图叠加的 ECharts 交互式 HTML 报告。"""
    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)

    base_p = periods[-1]
    base_df = dfs[base_p]
    base_res = results[base_p]
    base_dts = pd.to_datetime(base_df["datetime"].astype(str))
    dates = base_df["datetime"].astype(str).tolist()
    candles = base_df[["open", "close", "low", "high"]].values.tolist()

    def _map_to_base_idx(dt_val, val, is_high, period_key):
        p_dt = _to_dt(dt_val)
        if len(base_df) == 0:
            return 0
        if p_dt < base_dts.iloc[0]:
            return 0
        if p_dt > base_dts.iloc[-1]:
            return len(base_df) - 1
        if period_key == "WEEK":
            mask = (base_dts.dt.date >= (p_dt - pd.Timedelta(days=6)).date()) & (base_dts.dt.date <= (p_dt + pd.Timedelta(days=1)).date())
        elif period_key == "DAY":
            mask = base_dts.dt.date == p_dt.date()
        elif period_key == "MONTH":
            mask = (base_dts.dt.year == p_dt.year) & (base_dts.dt.month == p_dt.month)
        else:
            diffs = np.abs((base_dts - p_dt).dt.total_seconds().values)
            return int(np.argmin(diffs))

        idxs = np.where(mask)[0]
        if len(idxs) > 0:
            sub_vals = base_df["high"].iloc[idxs].values if is_high else base_df["low"].iloc[idxs].values
            return int(idxs[np.argmax(sub_vals) if is_high else np.argmin(sub_vals)])
        diffs = np.abs((base_dts - p_dt).dt.total_seconds().values)
        return int(np.argmin(diffs))

    # 大级别笔线条
    high_p = periods[0]
    high_bis = []
    for bi in results[high_p].bis:
        s_i = _map_to_base_idx(bi.start.k.date, bi.start.val, bi.direction.value == "down", high_p)
        e_i = _map_to_base_idx(bi.end.k.date, bi.end.val, bi.direction.value == "up", high_p)
        high_bis.append([[dates[s_i], bi.start.val], [dates[e_i], bi.end.val]])

    # 中级别笔线条
    mid_p = periods[1]
    mid_bis = []
    for bi in results[mid_p].bis:
        s_i = _map_to_base_idx(bi.start.k.date, bi.start.val, bi.direction.value == "down", mid_p)
        e_i = _map_to_base_idx(bi.end.k.date, bi.end.val, bi.direction.value == "up", mid_p)
        mid_bis.append([[dates[s_i], bi.start.val], [dates[e_i], bi.end.val]])

    # 小级别笔线条
    low_bis = []
    for bi in base_res.bis:
        s_i = min(len(dates) - 1, max(0, bi.start.k.k_index))
        e_i = min(len(dates) - 1, max(0, bi.end.k.k_index))
        low_bis.append([[dates[s_i], bi.start.val], [dates[e_i], bi.end.val]])

    # 买卖点 markPoints
    mmd_marks = []
    for mmd in base_res.mmds:
        if mmd.bi:
            idx = min(len(dates) - 1, max(0, mmd.bi.end.k.k_index))
            is_buy = "buy" in mmd.mmd_type.value
            mmd_marks.append({
                "coord": [dates[idx], mmd.bi.end.val],
                "value": mmd.mmd_type.value.upper().replace("BUY", "B").replace("SELL", "S"),
                "itemStyle": {"color": "#f23645" if is_buy else "#089981"},
            })

    # 共振买卖点
    res_marks = []
    for r in resonances:
        if 0 <= r.low_bar_idx < len(dates):
            res_marks.append({
                "coord": [dates[r.low_bar_idx], r.price],
                "value": f"★共振买({r.grade})" if r.direction == "BUY" else f"▼共振卖({r.grade})",
                "itemStyle": {"color": "#ffd600" if r.direction == "BUY" else "#00e5ff"},
            })

    # MACD
    macd_hist = (base_res.macd.get("hist") or []) if base_res.macd else []
    dif = (base_res.macd.get("dif") or []) if base_res.macd else []
    dea = (base_res.macd.get("dea") or []) if base_res.macd else []

    payload_json = json.dumps({
        "code": code,
        "name": name,
        "base_period": PERIOD_SPECS[base_p]["label"],
        "periods_str": f"{PERIOD_SPECS[high_p]['short_name']} · {PERIOD_SPECS[mid_p]['short_name']} · {PERIOD_SPECS[base_p]['short_name']}",
        "dates": dates,
        "candles": candles,
        "high_bis": high_bis,
        "mid_bis": mid_bis,
        "low_bis": low_bis,
        "mmd_marks": mmd_marks,
        "res_marks": res_marks,
        "macd_hist": [h * 2 for h in macd_hist],
        "dif": dif,
        "dea": dea,
        "resonances": [
            {
                "timestamp": r.timestamp,
                "price": r.price,
                "direction": r.direction,
                "grade": r.grade,
                "pattern_name": r.pattern_name,
                "desc": r.description.replace("\n", "<br>"),
            }
            for r in resonances
        ],
    }, ensure_ascii=False)

    html_template = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{code} {name} - 缠论三周期立体同图K线</title>
    <script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ background-color: #131722; color: #d1d4dc; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Microsoft YaHei", sans-serif; padding: 16px; }}
        .header {{ background: linear-gradient(135deg, #1e222d 0%, #2a2e39 100%); border: 1px solid #363c4e; border-radius: 8px; padding: 16px 20px; margin-bottom: 16px; display: flex; justify-content: space-between; align-items: center; }}
        .header h1 {{ font-size: 20px; font-weight: 700; color: #ffffff; margin-bottom: 6px; }}
        .res-table {{ width: 100%; border-collapse: collapse; background: #1e222d; border-radius: 8px; overflow: hidden; margin-bottom: 16px; border: 1px solid #2d313f; }}
        .res-table th, .res-table td {{ padding: 10px 14px; text-align: left; font-size: 12px; border-bottom: 1px solid #2d313f; }}
        .res-table th {{ background: #262b3d; color: #a0a6b5; }}
        .badge-buy {{ color: #f23645; font-weight: bold; }}
        .badge-sell {{ color: #089981; font-weight: bold; }}
        #chart {{ width: 100%; height: 720px; background: #181b27; border: 1px solid #2d313f; border-radius: 8px; }}
    </style>
</head>
<body>
    <div class="header">
        <div>
            <h1>{code} {name} · 缠论多周期立体同图 K 线图</h1>
            <div style="color: #ffeb3b; font-size: 13px;">以 {PERIOD_SPECS[base_p]['label']} 为基准K线，同图立体嵌套 [{PERIOD_SPECS[high_p]['short_name']} · {PERIOD_SPECS[mid_p]['short_name']} · {PERIOD_SPECS[base_p]['short_name']}]</div>
        </div>
        <div style="text-align: right;">
            <div>共振信号: <span style="color:#ffeb3b; font-weight:bold;">{len(resonances)}</span></div>
        </div>
    </div>

    <div style="margin-bottom: 8px; font-size: 14px; font-weight: 600; color: #ffeb3b;">★ 三周期共振信号明细表</div>
    <table class="res-table">
        <thead><tr><th>触发时间</th><th>方向</th><th>评级</th><th>形态名称</th><th>触发价格</th><th>多空详情</th></tr></thead>
        <tbody id="res-tbody"></tbody>
    </table>

    <div id="chart"></div>

    <script>
        const D = {payload_json};
        const tbody = document.getElementById('res-tbody');
        if (D.resonances.length === 0) {{
            tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; color:#888;">当前选定周期组合未捕捉到强共振信号。</td></tr>';
        }} else {{
            D.resonances.forEach(r => {{
                const isBuy = r.direction === 'BUY';
                tbody.innerHTML += `<tr>
                    <td>${{r.timestamp}}</td>
                    <td class="${{isBuy ? 'badge-buy' : 'badge-sell'}}">${{isBuy ? '▲ 买点' : '▼ 卖点'}}</td>
                    <td><span style="background:${{isBuy ? '#d32f2f' : '#00796b'}}; padding:2px 6px; border-radius:4px; font-size:11px;">${{r.grade}}</span></td>
                    <td style="font-weight:bold; color:#ffffff;">${{r.pattern_name}}</td>
                    <td>¥${{r.price.toFixed(2)}}</td>
                    <td>${{r.desc}}</td>
                </tr>`;
            }});
        }}

        const myChart = echarts.init(document.getElementById('chart'), 'dark');
        const option = {{
            backgroundColor: '#181b27',
            animation: false,
            legend: {{
                data: ['基准K线', '大级别笔(周线)', '中级别笔(日线)', '小级别笔(30F)', 'MACD'],
                selected: {{ '基准K线': true, '大级别笔(周线)': true, '中级别笔(日线)': true, '小级别笔(30F)': true, 'MACD': true }},
                top: 10,
                textStyle: {{ color: '#ffffff' }}
            }},
            tooltip: {{ trigger: 'axis', axisPointer: {{ type: 'cross' }} }},
            grid: [
                {{ left: '3%', right: '4%', top: '8%', height: '62%' }},
                {{ left: '3%', right: '4%', top: '75%', height: '18%' }}
            ],
            xAxis: [
                {{ type: 'category', data: D.dates, gridIndex: 0, axisLabel: {{ show: false }} }},
                {{ type: 'category', data: D.dates, gridIndex: 1, axisLabel: {{ color: '#888' }} }}
            ],
            yAxis: [
                {{ type: 'value', scale: true, gridIndex: 0, position: 'right', splitLine: {{ lineStyle: {{ color: '#242838' }} }} }},
                {{ type: 'value', scale: true, gridIndex: 1, position: 'right', splitLine: {{ lineStyle: {{ color: '#242838' }} }} }}
            ],
            dataZoom: [
                {{ type: 'inside', xAxisIndex: [0, 1], start: 40, end: 100 }},
                {{ type: 'slider', xAxisIndex: [0, 1], top: '95%', height: 16 }}
            ],
            series: [
                {{
                    name: '基准K线',
                    type: 'candlestick',
                    data: D.candles,
                    itemStyle: {{ color: '#f23645', color0: '#089981', borderColor: '#f23645', borderColor0: '#089981' }},
                    markPoint: {{ data: [...D.mmd_marks, ...D.res_marks] }}
                }},
                {{
                    name: '大级别笔(周线)',
                    type: 'line',
                    data: [],
                    lineStyle: {{ color: '#e040fb', width: 3.5 }},
                    markLine: {{ data: D.high_bis.map(b => [{{ coord: b[0], lineStyle: {{ color: '#e040fb', width: 3.5 }} }}, {{ coord: b[1] }}]), symbol: ['circle', 'circle'] }}
                }},
                {{
                    name: '中级别笔(日线)',
                    type: 'line',
                    data: [],
                    lineStyle: {{ color: '#00e5ff', width: 2.5 }},
                    markLine: {{ data: D.mid_bis.map(b => [{{ coord: b[0], lineStyle: {{ color: '#00e5ff', width: 2.5 }} }}, {{ coord: b[1] }}]), symbol: ['circle', 'circle'] }}
                }},
                {{
                    name: '小级别笔(30F)',
                    type: 'line',
                    data: [],
                    lineStyle: {{ color: '#ffd600', width: 1.5 }},
                    markLine: {{ data: D.low_bis.map(b => [{{ coord: b[0], lineStyle: {{ color: '#ffd600', width: 1.5 }} }}, {{ coord: b[1] }}]), symbol: ['circle', 'circle'] }}
                }},
                {{
                    name: 'MACD',
                    type: 'bar',
                    xAxisIndex: 1,
                    yAxisIndex: 1,
                    data: D.macd_hist.map(v => ({{ value: v, itemStyle: {{ color: v >= 0 ? '#f23645' : '#089981' }} }}))
                }}
            ]
        }};
        myChart.setOption(option);
        window.addEventListener('resize', () => myChart.resize());
    </script>
</body>
</html>
"""
    out_file.write_text(html_template, encoding="utf-8")
    logger.info(f"同图 ECharts 交互式 HTML 报告已生成: {out_file.resolve()}")
    return out_file


# ==============================================================================
# 6. 主流程与调度器
# ==============================================================================


def analyze_and_plot_resonance(
    code: str = "000001",
    periods: list[str] | str | None = None,
    bars_count: int | None = None,
    split_panels: bool = False,
    save_png: bool = True,
    save_html: bool = False,
    show_window: bool = False,
    output_png_path: str | Path | None = None,
    output_html_path: str | Path | None = None,
) -> dict[str, Any]:
    """多周期立体共振分析与图表生成主函数。

    默认以最小周期 K 线为基准，将 3 个周期的笔、中枢及共振买卖点画在同一张图片中。
    """
    clean_code = (
        str(code)
        .strip()
        .upper()
        .replace("SZ", "")
        .replace("SH", "")
        .replace("BJ", "")
    )

    if periods is None:
        p_list = ["DAY", "30F", "5F"]
    elif isinstance(periods, str):
        p_list = parse_three_periods(periods)
    else:
        p_list = sorted(
            [normalize_period(p) for p in periods],
            key=lambda k: PERIOD_SPECS[k]["weight"],
            reverse=True,
        )

    name = get_stock_name(clean_code) or "标的资产"
    base_period = p_list[-1]
    logger.info(
        f"🚀 开始执行【{clean_code} {name}】缠论多周期立体同图共振分析: "
        f"[大:{PERIOD_SPECS[p_list[0]]['short_name']} · 中:{PERIOD_SPECS[p_list[1]]['short_name']} · 基准小:{PERIOD_SPECS[base_period]['short_name']}]"
    )

    # 确定各周期拉取 K 线数量（基准小周期需要足够数量以充分映射大级别形态）
    if bars_count is None:
        req_counts = {
            p_list[0]: 100,  # 大级别
            p_list[1]: 150,  # 中级别
            base_period: 300,  # 基准小级别 (约30-40个交易日)
        }
    else:
        req_counts = {
            p_list[0]: max(80, bars_count // 2),
            p_list[1]: max(100, int(bars_count * 0.8)),
            base_period: bars_count,
        }

    # 5F / 1F 级别保证至少拉取 1500 根 K 线
    for p in p_list:
        if p in ("5F", "5M", "1F", "1M"):
            req_counts[p] = max(req_counts.get(p, 0), 1500)

    dfs: dict[str, pd.DataFrame] = {}
    for p in p_list:
        spec = PERIOD_SPECS[p]
        cat_str = spec["market_cat"]
        cnt = req_counts[p]
        logger.info(f"正在拉取 {spec['label']} 数据 (count={cnt})...")
        df = fetch_security_kline(clean_code, category=cat_str, count=cnt)
        if df is None or df.empty:
            logger.warning(f"未能获取到 {p} 级别 K 线数据！")
            df = pd.DataFrame(columns=["datetime", "open", "high", "low", "close", "volume", "amount"])
        dfs[p] = df

    # 运行缠论分析计算管道
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

    # 运行三周期共振引擎
    engine = ThreePeriodResonanceEngine(p_list[0], p_list[1], p_list[2], results)
    resonances = engine.scan_resonances()

    logger.info(f"🎯 三周期立体共振扫描完成，共识别出 {len(resonances)} 个买卖点共振事件！")
    for r in resonances:
        logger.info(f"   [{r.grade}] {r.timestamp} {r.pattern_name} @ ¥{r.price:.2f}")

    # 绘制图片：默认统一同图模式，--split 则使用分屏模式
    png_path = None
    if save_png or show_window:
        if split_panels:
            plotter = ChanlunSplitResonancePlotter(clean_code, name, p_list, dfs, results, resonances)
        else:
            plotter = ChanlunUnifiedResonancePlotter(clean_code, name, p_list, dfs, results, resonances)
        png_path = plotter.plot(save_path=output_png_path, show=show_window)

    # 生成 HTML
    html_path = None
    if save_html:
        if output_html_path is None:
            out_dir = PROJECT_ROOT / "output"
            out_dir.mkdir(parents=True, exist_ok=True)
            p_tag = "_".join(p_list)
            output_html_path = out_dir / f"chanlun_resonance_{clean_code}_{p_tag}_unified.html"
        html_path = export_interactive_html(
            clean_code, name, p_list, dfs, results, resonances, output_html_path
        )

    return {
        "code": clean_code,
        "name": name,
        "periods": p_list,
        "base_period": base_period,
        "dfs": dfs,
        "results": results,
        "resonances": resonances,
        "png_path": str(png_path) if png_path else None,
        "html_path": str(html_path) if html_path else None,
    }


def main():
    parser = argparse.ArgumentParser(
        description="缠论理论多周期共振买卖点 K线图分析系统 (以最小周期K线为基准，同图立体绘制 3 个周期)"
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
        default="DAY,30F,5F",
        help=(
            "自选 3 个周期，逗号分隔 (默认: DAY,30F,5F)。\n"
            "可选范围: MONTH, WEEK, DAY, 120F, 60F, 30F, 15F, 5F (亦支持中文如 周线,日线,30分钟)"
        ),
    )
    parser.add_argument(
        "--bars", "-b",
        type=int,
        default=None,
        help="基准最小周期抓取的 K 线数量 (默认自动匹配 300 根)",
    )
    parser.add_argument(
        "--split",
        action="store_true",
        help="采用旧版 3 分屏独立子图模式 (默认关闭，默认画在同一张图片中)",
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
        help="同时生成交互式同图 ECharts HTML 报告",
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
            split_panels=args.split,
            save_png=True,
            save_html=args.html,
            show_window=args.show,
            output_png_path=args.output,
        )

        p_names = [PERIOD_SPECS[p]["short_name"] for p in ret["periods"]]
        base_name = PERIOD_SPECS[ret["base_period"]]["short_name"]
        print("\n" + "=" * 75)
        print(f"📊 【{ret['code']} {ret['name']}】缠论多周期同图立体走势报告")
        print("=" * 75)
        print(f"基准底图周期: {base_name} (最小周期)")
        print(f"同图嵌套周期: {' -> '.join(p_names)}")
        if ret["png_path"]:
            print(f"🖼  同图 K线图: {ret['png_path']}")
        if ret["html_path"]:
            print(f"🌐 交互式网页: {ret['html_path']}")

        resonances = ret["resonances"]
        print(f"\n共振买卖点事件数量: {len(resonances)}")
        if resonances:
            print("-" * 75)
            print(f"{'触发时间':<18} {'方向':<6} {'评级':<6} {'价格':<9} {'形态名称'}")
            print("-" * 75)
            for r in resonances:
                dir_str = "买点 ▲" if r.direction == "BUY" else "卖点 ▼"
                print(f"{r.timestamp:<18} {dir_str:<6} {r.grade:<6} {r.price:<9.2f} {r.pattern_name}")
            print("-" * 75)
        else:
            print("注: 选定周期内未发现强共振买卖点，维持中枢走势震荡观察。")
        print("=" * 75 + "\n")

    except Exception as e:
        logger.exception(f"执行失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
