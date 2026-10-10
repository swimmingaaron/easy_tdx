"""缠论多周期立体共振买卖点计算引擎与数据格式化模块。

支持周期：
    月线 (MONTH) | 周线 (WEEK) | 日线 (DAY) | 120F (120分钟) |
    60F (60分钟) | 30F (30分钟) | 15F (15分钟) | 5F (5分钟) | 1F (1分钟)

核心能力：
1. 三周期立体共振买卖点识别引擎 (ThreePeriodResonanceEngine)；
2. 大/中级别分型、笔、中枢向基准小级别的坐标精确对齐映射；
3. 支持历史截断回溯 (Backtracking / Replay)；
4. 格式化生成 ECharts / Web 前端图表所需的统一立体结构及各周期独立分屏结构。
"""

from __future__ import annotations

import bisect
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import numpy as np
import pandas as pd

from easy_tdx.chanlun.analyser import ChanlunAnalyser, ChanlunResult
from easy_tdx.chanlun.types import BI, FX, MMD, ZS, Direction, FXType, MMDType
from easy_tdx.market_data import fetch_security_kline
from easy_tdx.stock_lookup import get_stock_name

logger = logging.getLogger("chanlun.resonance")

# ==============================================================================
# 1. 周期规范与定义
# ==============================================================================

PERIOD_SPECS: dict[str, dict[str, Any]] = {
    "MONTH": {
        "aliases": ["MONTH", "MONTHLY", "月线", "月", "M"],
        "weight": 90,
        "market_cat": "MONTH",
        "chan_freq": "monthly",
        "label": "月线 (MONTH)",
        "short_name": "月线",
        "date_fmt": "%Y-%m",
    },
    "WEEK": {
        "aliases": ["WEEK", "WEEKLY", "周线", "周", "W"],
        "weight": 80,
        "market_cat": "WEEK",
        "chan_freq": "weekly",
        "label": "周线 (WEEK)",
        "short_name": "周线",
        "date_fmt": "%Y-%m-%d",
    },
    "DAY": {
        "aliases": ["DAY", "DAILY", "日线", "日", "D"],
        "weight": 70,
        "market_cat": "DAY",
        "chan_freq": "daily",
        "label": "日线 (DAY)",
        "short_name": "日线",
        "date_fmt": "%Y-%m-%d",
    },
    "120F": {
        "aliases": ["120F", "120M", "120MIN", "120", "120分钟", "2H"],
        "weight": 60,
        "market_cat": "120M",
        "chan_freq": "120min",
        "label": "120分钟 (120F)",
        "short_name": "120F",
        "date_fmt": "%m-%d %H:%M",
    },
    "60F": {
        "aliases": ["60F", "60M", "60MIN", "60", "60分钟", "1H"],
        "weight": 50,
        "market_cat": "60M",
        "chan_freq": "60min",
        "label": "60分钟 (60F)",
        "short_name": "60F",
        "date_fmt": "%m-%d %H:%M",
    },
    "30F": {
        "aliases": ["30F", "30M", "30MIN", "30", "30分钟"],
        "weight": 40,
        "market_cat": "30M",
        "chan_freq": "30min",
        "label": "30分钟 (30F)",
        "short_name": "30F",
        "date_fmt": "%m-%d %H:%M",
    },
    "15F": {
        "aliases": ["15F", "15M", "15MIN", "15", "15分钟"],
        "weight": 30,
        "market_cat": "15M",
        "chan_freq": "15min",
        "label": "15分钟 (15F)",
        "short_name": "15F",
        "date_fmt": "%m-%d %H:%M",
    },
    "5F": {
        "aliases": ["5F", "5M", "5MIN", "5", "5分钟"],
        "weight": 20,
        "market_cat": "5M",
        "chan_freq": "5min",
        "label": "5分钟 (5F)",
        "short_name": "5F",
        "date_fmt": "%m-%d %H:%M",
    },
    "1F": {
        "aliases": ["1F", "1M", "1MIN", "1", "1分钟"],
        "weight": 10,
        "market_cat": "1M",
        "chan_freq": "1min",
        "label": "1分钟 (1F)",
        "short_name": "1F",
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
        f"{', '.join(PERIOD_SPECS.keys())}"
    )


def parse_three_periods(periods_input: list[str] | str | None) -> list[str]:
    """解析并校验 3 个周期，按大级别到小级别自动排序返回。"""
    if periods_input is None:
        return ["DAY", "30F", "5F"]

    if isinstance(periods_input, str):
        parts = [p.strip() for p in periods_input.replace("，", ",").split(",") if p.strip()]
    else:
        parts = [str(p).strip() for p in periods_input if str(p).strip()]

    if len(parts) != 3:
        raise ValueError(f"必须恰好指定 3 个周期，当前输入了 {len(parts)} 个: {periods_input}")

    normalized = [normalize_period(p) for p in parts]
    if len(set(normalized)) != 3:
        raise ValueError(f"选择的 3 个周期不能重复: {normalized}")

    # 按照权重从大到小排序（大级别在上，小级别为底图基准）
    return sorted(normalized, key=lambda k: PERIOD_SPECS[k]["weight"], reverse=True)


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
    recent_mmd_type: str = ""
    recent_mmd_date: str = ""
    recent_mmd_bars_ago: int = 999
    is_bullish: bool = False
    is_bearish: bool = False
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "period": self.period,
            "period_label": PERIOD_SPECS.get(self.period, {}).get("short_name", self.period),
            "bar_index": self.bar_index,
            "bar_date": self.bar_date,
            "price": round(self.price, 2),
            "bi_direction": self.current_bi_direction,
            "recent_mmd": self.recent_mmd_type.upper() if self.recent_mmd_type else "",
            "recent_mmd_bars_ago": self.recent_mmd_bars_ago,
            "is_bullish": self.is_bullish,
            "is_bearish": self.is_bearish,
            "detail": self.detail,
        }


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
    mid_bar_idx: int
    high_bar_idx: int
    description: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "price": round(self.price, 2),
            "direction": self.direction,
            "grade": self.grade,
            "pattern_name": self.pattern_name,
            "high_period": self.high_period,
            "mid_period": self.mid_period,
            "low_period": self.low_period,
            "low_bar_idx": self.low_bar_idx,
            "high_state": self.high_state.to_dict(),
            "mid_state": self.mid_state.to_dict(),
            "low_state": self.low_state.to_dict(),
            "description": self.description,
        }


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

    def get_period_state_at(self, period: str, target_dt: Any) -> PeriodState:
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

            low_state = self.get_period_state_at(self.p_low, target_dt)
            mid_state = self.get_period_state_at(self.p_mid, target_dt)
            high_state = self.get_period_state_at(self.p_high, target_dt)

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
                        f"- {PERIOD_SPECS[self.p_high]['short_name']}(大): {high_state.detail}\n"
                        f"- {PERIOD_SPECS[self.p_mid]['short_name']}(中): {mid_state.detail}\n"
                        f"- {PERIOD_SPECS[self.p_low]['short_name']}(小): 触发 {ev['type'].upper()} ({ev['price']:.2f})"
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
                        f"- {PERIOD_SPECS[self.p_high]['short_name']}(大): {high_state.detail}\n"
                        f"- {PERIOD_SPECS[self.p_mid]['short_name']}(中): {mid_state.detail}\n"
                        f"- {PERIOD_SPECS[self.p_low]['short_name']}(小): 触发 {ev['type'].upper()} ({ev['price']:.2f})"
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
                return "AAA", f"★ [{p_names}] 全一买三套极限抄底"
            if "2buy" in h_type and "2buy" in m_type and "2buy" in low_mmd:
                return "AAA", f"★ [{p_names}] 全二买主升浪确立共振"
            if "3buy" in h_type and "3buy" in m_type and "3buy" in low_mmd:
                return "AAA", f"★ [{p_names}] 全三买中枢爆发共振"

            # 花姐核心区间套模型：大级别1买确立后，次级别/小级别2买二次确认 (蓝2进1蓝2)
            if "1buy" in h_type and "2buy" in low_mmd:
                return "AAA", f"★ [{p_names}] 区间套·蓝2进1双重确认买点"
            if "1buy" in m_type and "2buy" in low_mmd:
                return "AAA", f"★ [{p_names}] 区间套·次一买小二买共振点"

            if "3buy" in low_mmd:
                return "AA", f"★ [{p_names}] 三类买点中枢突破共振"
            if "2buy" in low_mmd:
                return "AA", f"★ [{p_names}] 二类买点起跑共振"
            if "1buy" in low_mmd:
                return "AA", f"★ [{p_names}] 底背驰 T1 拐点共振"

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

            # 花姐核心区间套卖点：大级别1卖出顶，次级别/小级别2卖破位确认
            if "1sell" in h_type and "2sell" in low_mmd:
                return "AAA", f"▼ [{p_names}] 区间套·大一卖小二卖破位确认"
            if "1sell" in m_type and "2sell" in low_mmd:
                return "AAA", f"▼ [{p_names}] 区间套·次一卖小二卖破位点"

            if "1sell" in low_mmd:
                return "AA", f"▼ [{p_names}] 顶背驰 T1 拐点共振"
            if "2sell" in low_mmd:
                return "AA", f"▼ [{p_names}] 二类卖点反弹不过共振"
            if "3sell" in low_mmd:
                return "AA", f"▼ [{p_names}] 三类卖点破位下杀共振"

            return "A", f"▼ [{p_names}] 多周期空头破位共振卖点"


# ==============================================================================
# 3. 跨级别笔与中枢向基准周期的对齐映射
# ==============================================================================


def map_pivot_to_base(
    dt_val: Any,
    val: float,
    is_high: bool,
    period_key: str,
    base_df: pd.DataFrame,
    base_dts: pd.Series,
) -> int:
    """将较高级别的笔分型端点精确映射到基准小周期的某根 K 线索引。"""
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


# ==============================================================================
# 4. 核心主函数：多周期立体分析与数据结构组织
# ==============================================================================


def analyze_multi_period_resonance(
    code: str = "000001",
    periods: list[str] | str | None = None,
    count: int = 300,
    cutoff_date: str | None = None,
    force_refresh: bool = False,
) -> dict[str, Any]:
    """执行三周期缠论立体共振分析，支持历史回溯与实时计算。

    Args:
        code: 证券代码（如 000001, 600519）
        periods: 3 个周期组合（如 ["DAY", "30F", "5F"] 或 "DAY,30F,5F"，默认 "DAY,30F,5F"）
        count: 基准最小周期 K 线根数（默认 300）
        cutoff_date: 回溯截止日期时间（若提供则只计算 <= 该时间的数据，模拟历史当下）
        force_refresh: 是否强制穿透缓存获取最新实时行情
    """
    clean_code = (
        str(code)
        .strip()
        .upper()
        .replace("SZ", "")
        .replace("SH", "")
        .replace("BJ", "")
    )
    if not clean_code:
        clean_code = "000001"

    p_list = parse_three_periods(periods)
    high_p, mid_p, low_p = p_list[0], p_list[1], p_list[2]
    stock_name = get_stock_name(clean_code) or "标的资产"

    # 请求 K 线数量
    # 若启用了 cutoff_date 回溯，适当增加拉取基准根数以覆盖更远的历史点
    multiplier = 2 if (cutoff_date and str(cutoff_date).strip()) else 1
    req_counts = {
        high_p: max(100, (count // 3) * multiplier),
        mid_p: max(160, int(count * 0.7) * multiplier),
        low_p: max(200, count * multiplier),
    }
    # 5F / 1F 级别保证至少拉取 1500 根 K 线，充分覆盖微观走势与共振形态
    for p in p_list:
        if p in ("5F", "5M", "1F", "1M"):
            req_counts[p] = max(req_counts.get(p, 0), 1500 * multiplier)

    # 拉取三周期 K 线
    raw_dfs: dict[str, pd.DataFrame] = {}
    for p in p_list:
        spec = PERIOD_SPECS[p]
        df = fetch_security_kline(
            clean_code,
            category=spec["market_cat"],
            count=req_counts[p],
            force_refresh=force_refresh,
        )
        if df is None or df.empty:
            df = pd.DataFrame(columns=["datetime", "open", "high", "low", "close", "volume", "amount"])
        raw_dfs[p] = df

    # 获取完整可用时间跨度（用于前端时间滑块和回溯导航）
    base_full_df = raw_dfs[low_p]
    available_dates = (
        base_full_df["datetime"].astype(str).tolist()
        if not base_full_df.empty
        else []
    )
    min_date = available_dates[0] if available_dates else ""
    max_date = available_dates[-1] if available_dates else ""

    # 如果指定了 cutoff_date，进行历史切除回溯
    dfs: dict[str, pd.DataFrame] = {}
    is_backtracking = False
    if cutoff_date and str(cutoff_date).strip() and not base_full_df.empty:
        cutoff_str = str(cutoff_date).strip()
        cutoff_dt = _to_dt(cutoff_str)
        is_backtracking = True
        for p in p_list:
            df_cur = raw_dfs[p]
            if not df_cur.empty and "datetime" in df_cur.columns:
                # 过滤 <= cutoff_dt
                dts = pd.to_datetime(df_cur["datetime"].astype(str))
                mask = dts <= cutoff_dt
                sub_df = df_cur[mask].copy().reset_index(drop=True)
                # 至少保留 30 根 K 线供缠论计算，避免历史过早导致全空
                if len(sub_df) < 15:
                    sub_df = df_cur.iloc[:min(len(df_cur), 30)].copy().reset_index(drop=True)
                dfs[p] = sub_df
            else:
                dfs[p] = df_cur.copy()
    else:
        dfs = {k: v.copy() for k, v in raw_dfs.items()}

    # 运行缠论分析管道
    results: dict[str, ChanlunResult] = {}
    for p in p_list:
        spec = PERIOD_SPECS[p]
        analyser = ChanlunAnalyser(code=clean_code, frequency=spec["chan_freq"])
        results[p] = analyser.process_klines(dfs[p])

    # 运行三周期共振引擎
    engine = ThreePeriodResonanceEngine(high_p, mid_p, low_p, results)
    resonances = engine.scan_resonances()

    # 获取当前最新时点的多空态势
    base_df = dfs[low_p]
    latest_dt = base_df["datetime"].iloc[-1] if not base_df.empty else ""
    current_high_state = engine.get_period_state_at(high_p, latest_dt)
    current_mid_state = engine.get_period_state_at(mid_p, latest_dt)
    current_low_state = engine.get_period_state_at(low_p, latest_dt)

    # 组装基准 K 线坐标轴与图表序列
    n_base = len(base_df)
    dates = base_df["datetime"].astype(str).tolist() if not base_df.empty else []
    candles = (
        base_df[["open", "close", "low", "high"]].values.tolist()
        if not base_df.empty
        else []
    )
    volumes = (
        [
            [i, row["volume"], 1 if row["close"] >= row["open"] else -1]
            for i, (_, row) in enumerate(base_df.iterrows())
        ]
        if not base_df.empty
        else []
    )
    base_dts = (
        pd.to_datetime(base_df["datetime"].astype(str))
        if not base_df.empty
        else pd.Series(dtype="datetime64[ns]")
    )

    # 1. 映射大级别笔与中枢
    high_res = results[high_p]
    high_bis = []
    for bi in high_res.bis:
        s_i = map_pivot_to_base(bi.start.k.date, bi.start.val, bi.direction.value == "down", high_p, base_df, base_dts)
        e_i = map_pivot_to_base(bi.end.k.date, bi.end.val, bi.direction.value == "up", high_p, base_df, base_dts)
        if s_i < 0 and e_i < 0:
            continue
        s_clamp = max(0, min(n_base - 1, s_i))
        e_clamp = max(0, min(n_base - 1, e_i))
        high_bis.append({
            "start": [dates[s_clamp], bi.start.val],
            "end": [dates[e_clamp], bi.end.val],
            "start_idx": s_clamp,
            "end_idx": e_clamp,
            "direction": bi.direction.value,
        })

    high_zss = []
    for zs in results[high_p].zss:
        if not zs.start or not zs.end:
            continue
        s_i = map_pivot_to_base(zs.start.k.date, zs.zd, False, high_p, base_df, base_dts)
        e_i = map_pivot_to_base(zs.end.k.date, zs.zg, True, high_p, base_df, base_dts)
        if e_i < 0 or s_i >= n_base:
            continue
        s_clamp = max(0, min(n_base - 1, s_i))
        e_clamp = max(0, min(n_base - 1, e_i))
        high_zss.append({
            "start_date": dates[s_clamp],
            "end_date": dates[e_clamp],
            "start_idx": s_clamp,
            "end_idx": e_clamp,
            "zg": round(zs.zg, 2),
            "zd": round(zs.zd, 2),
            "gg": round(zs.gg, 2),
            "dd": round(zs.dd, 2),
        })

    # 2. 映射中级别笔与中枢
    mid_res = results[mid_p]
    mid_bis = []
    for bi in mid_res.bis:
        s_i = map_pivot_to_base(bi.start.k.date, bi.start.val, bi.direction.value == "down", mid_p, base_df, base_dts)
        e_i = map_pivot_to_base(bi.end.k.date, bi.end.val, bi.direction.value == "up", mid_p, base_df, base_dts)
        if s_i < 0 and e_i < 0:
            continue
        s_clamp = max(0, min(n_base - 1, s_i))
        e_clamp = max(0, min(n_base - 1, e_i))
        mid_bis.append({
            "start": [dates[s_clamp], bi.start.val],
            "end": [dates[e_clamp], bi.end.val],
            "start_idx": s_clamp,
            "end_idx": e_clamp,
            "direction": bi.direction.value,
        })

    mid_zss = []
    for zs in results[mid_p].zss:
        if not zs.start or not zs.end:
            continue
        s_i = map_pivot_to_base(zs.start.k.date, zs.zd, False, mid_p, base_df, base_dts)
        e_i = map_pivot_to_base(zs.end.k.date, zs.zg, True, mid_p, base_df, base_dts)
        if e_i < 0 or s_i >= n_base:
            continue
        s_clamp = max(0, min(n_base - 1, s_i))
        e_clamp = max(0, min(n_base - 1, e_i))
        mid_zss.append({
            "start_date": dates[s_clamp],
            "end_date": dates[e_clamp],
            "start_idx": s_clamp,
            "end_idx": e_clamp,
            "zg": round(zs.zg, 2),
            "zd": round(zs.zd, 2),
            "gg": round(zs.gg, 2),
            "dd": round(zs.dd, 2),
        })

    # 3. 小级别（基准）笔与中枢
    low_res = results[low_p]
    low_bis = []
    for bi in low_res.bis:
        s_i = max(0, min(n_base - 1, bi.start.k.k_index))
        e_i = max(0, min(n_base - 1, bi.end.k.k_index))
        low_bis.append({
            "start": [dates[s_i], bi.start.val],
            "end": [dates[e_i], bi.end.val],
            "start_idx": s_i,
            "end_idx": e_i,
            "direction": bi.direction.value,
        })

    low_zss = []
    for zs in low_res.zss:
        if not zs.start or not zs.end:
            continue
        s_i = max(0, min(n_base - 1, zs.start.k.k_index))
        e_i = max(0, min(n_base - 1, zs.end.k.k_index))
        if e_i < s_i:
            continue
        low_zss.append({
            "start_date": dates[s_i],
            "end_date": dates[e_i],
            "start_idx": s_i,
            "end_idx": e_i,
            "zg": round(zs.zg, 2),
            "zd": round(zs.zd, 2),
            "gg": round(zs.gg, 2),
            "dd": round(zs.dd, 2),
        })

    # 4. 买卖点标记点 (多级别同图融合与区间套专业标识)
    mmd_marks = []

    # 小级别自身买卖点 (底背驰 T1 / 顶背驰 T1 / 2买 / 3买)
    for mmd in low_res.mmds:
        if mmd.bi:
            k_idx = max(0, min(n_base - 1, mmd.bi.end.k.k_index))
            is_buy = "buy" in mmd.mmd_type.value
            m_type = mmd.mmd_type.value.lower()
            if "1buy" in m_type:
                label_txt = "底背驰 T1"
            elif "2buy" in m_type:
                label_txt = "2买"
            elif "3buy" in m_type:
                label_txt = "3买"
            elif "1sell" in m_type:
                label_txt = "顶背驰 T1"
            elif "2sell" in m_type:
                label_txt = "2卖"
            elif "3sell" in m_type:
                label_txt = "3卖"
            else:
                label_txt = mmd.mmd_type.value.upper()

            mmd_marks.append({
                "coord": [dates[k_idx], mmd.bi.end.val],
                "date": dates[k_idx],
                "price": round(mmd.bi.end.val, 2),
                "type": mmd.mmd_type.value.upper(),
                "level": "low",
                "label": label_txt,
                "is_buy": is_buy,
                "msg": mmd.msg,
            })

    # 中级别买卖点向底图映射 (次二买 / 次二卖 / 可能的三卖)
    for mmd in mid_res.mmds:
        if mmd.bi:
            end_val = mmd.bi.end.val
            is_high = mmd.bi.direction.value == "up"
            b_idx = map_pivot_to_base(mmd.bi.end.k.date, end_val, is_high, mid_p, base_df, base_dts)
            if 0 <= b_idx < n_base:
                is_buy = "buy" in mmd.mmd_type.value
                m_type = mmd.mmd_type.value.lower()
                if "1buy" in m_type:
                    label_txt = f"[{PERIOD_SPECS[mid_p]['short_name']}]1买"
                elif "2buy" in m_type:
                    label_txt = "次二买"
                elif "3buy" in m_type:
                    label_txt = "次三买"
                elif "1sell" in m_type:
                    label_txt = f"[{PERIOD_SPECS[mid_p]['short_name']}]1卖"
                elif "2sell" in m_type:
                    label_txt = "次二卖"
                elif "3sell" in m_type:
                    label_txt = "可能的三卖"
                else:
                    label_txt = f"[{PERIOD_SPECS[mid_p]['short_name']}]{mmd.mmd_type.value.upper()}"

                mmd_marks.append({
                    "coord": [dates[b_idx], end_val],
                    "date": dates[b_idx],
                    "price": round(end_val, 2),
                    "type": mmd.mmd_type.value.upper(),
                    "level": "mid",
                    "label": label_txt,
                    "is_buy": is_buy,
                    "msg": f"{PERIOD_SPECS[mid_p]['label']}: {mmd.msg}",
                })

    # 大级别买卖点向底图映射 (大级别1买 / 大级别1卖 / 大级别2买)
    for mmd in high_res.mmds:
        if mmd.bi:
            end_val = mmd.bi.end.val
            is_high = mmd.bi.direction.value == "up"
            b_idx = map_pivot_to_base(mmd.bi.end.k.date, end_val, is_high, high_p, base_df, base_dts)
            if 0 <= b_idx < n_base:
                is_buy = "buy" in mmd.mmd_type.value
                m_type = mmd.mmd_type.value.lower()
                if "1buy" in m_type:
                    label_txt = "大级别走势1买"
                elif "2buy" in m_type:
                    label_txt = "大级别2买"
                elif "1sell" in m_type:
                    label_txt = "大级别1卖"
                elif "2sell" in m_type:
                    label_txt = "大级别2卖"
                else:
                    label_txt = f"大级别{mmd.mmd_type.value.upper()}"

                mmd_marks.append({
                    "coord": [dates[b_idx], end_val],
                    "date": dates[b_idx],
                    "price": round(end_val, 2),
                    "type": mmd.mmd_type.value.upper(),
                    "level": "high",
                    "label": label_txt,
                    "is_buy": is_buy,
                    "msg": f"{PERIOD_SPECS[high_p]['label']}: {mmd.msg}",
                })

    # 5. 共振买卖点标记
    res_marks = []
    for r in resonances:
        if 0 <= r.low_bar_idx < n_base:
            res_marks.append({
                "coord": [dates[r.low_bar_idx], r.price],
                "date": dates[r.low_bar_idx],
                "price": round(r.price, 2),
                "direction": r.direction,
                "grade": r.grade,
                "pattern_name": r.pattern_name,
                "label": f"★{r.grade}买" if r.direction == "BUY" else f"▼{r.grade}卖",
                "desc": r.description,
            })

    # 6. MACD 数据及背离（底背离 / 顶背离）识别
    macd_data = low_res.macd or {}
    macd_hist = [round(h * 2, 3) for h in (macd_data.get("hist") or [])]
    macd_dif = [round(d, 3) for d in (macd_data.get("dif") or [])]
    macd_dea = [round(d, 3) for d in (macd_data.get("dea") or [])]

    macd_marks = []
    seen_macd_bars = set()

    # 6.1 结合缠论背驰点 (笔背驰 / 盘整背驰 / 趋势背驰)
    for bc in getattr(low_res, "bcs", []):
        if not bc.curr or not getattr(bc, "bc", False):
            continue
        bar_idx = getattr(bc.curr.end.k, "k_index", -1)
        if 0 <= bar_idx < n_base and bar_idx not in seen_macd_bars:
            seen_macd_bars.add(bar_idx)
            is_bottom = getattr(bc.curr.direction, "value", "") == "down"
            m_dif = macd_dif[bar_idx] if bar_idx < len(macd_dif) else 0.0
            m_hist = macd_hist[bar_idx] if bar_idx < len(macd_hist) else 0.0
            macd_marks.append({
                "date": dates[bar_idx],
                "bar_idx": bar_idx,
                "type": "bottom" if is_bottom else "top",
                "label": "▲底背离" if is_bottom else "▼顶背离",
                "dif": m_dif,
                "hist": m_hist,
                "price": round(float(base_df["close"].iloc[bar_idx]), 2),
                "msg": bc.msg or ("缠论底背驰(MACD绿柱动能衰竭)" if is_bottom else "缠论顶背驰(MACD红柱动能衰竭)"),
            })

    # 6.2 结合缠论一类买卖点 (天然对应标准走势终结底背离/顶背离)
    for mmd in low_res.mmds:
        if not mmd.bi:
            continue
        bar_idx = getattr(mmd.bi.end.k, "k_index", -1)
        if 0 <= bar_idx < n_base and bar_idx not in seen_macd_bars:
            m_type = mmd.mmd_type.value.lower()
            if "1buy" in m_type:
                seen_macd_bars.add(bar_idx)
                m_dif = macd_dif[bar_idx] if bar_idx < len(macd_dif) else 0.0
                m_hist = macd_hist[bar_idx] if bar_idx < len(macd_hist) else 0.0
                macd_marks.append({
                    "date": dates[bar_idx],
                    "bar_idx": bar_idx,
                    "type": "bottom",
                    "label": "▲底背离",
                    "dif": m_dif,
                    "hist": m_hist,
                    "price": round(float(base_df["close"].iloc[bar_idx]), 2),
                    "msg": "一买底背驰: 价格见底且MACD动能底背离",
                })
            elif "1sell" in m_type:
                seen_macd_bars.add(bar_idx)
                m_dif = macd_dif[bar_idx] if bar_idx < len(macd_dif) else 0.0
                m_hist = macd_hist[bar_idx] if bar_idx < len(macd_hist) else 0.0
                macd_marks.append({
                    "date": dates[bar_idx],
                    "bar_idx": bar_idx,
                    "type": "top",
                    "label": "▼顶背离",
                    "dif": m_dif,
                    "hist": m_hist,
                    "price": round(float(base_df["close"].iloc[bar_idx]), 2),
                    "msg": "一卖顶背驰: 价格冲顶且MACD动能顶背离",
                })

    # 6.3 经典技术指标 MACD 峰谷背离检测 (价格创极值但 DIF 未创新极值)
    if len(macd_dif) >= 20 and not base_df.empty:
        closes = base_df["close"].values
        for i in range(10, len(macd_dif) - 5):
            if i in seen_macd_bars:
                continue
            # 谷底底背离候选 (DIF < 0 且局部低谷)
            if macd_dif[i] < macd_dif[i - 1] and macd_dif[i] < macd_dif[i + 1] and macd_dif[i] < 0:
                prev_valley = None
                for j in range(i - 8, max(0, i - 80), -1):
                    if macd_dif[j] < macd_dif[j - 1] and macd_dif[j] < macd_dif[j + 1] and macd_dif[j] < 0:
                        prev_valley = j
                        break
                if prev_valley is not None:
                    if closes[i] <= closes[prev_valley] * 0.998 and macd_dif[i] > macd_dif[prev_valley]:
                        seen_macd_bars.add(i)
                        macd_marks.append({
                            "date": dates[i],
                            "bar_idx": i,
                            "type": "bottom",
                            "label": "▲底背离",
                            "dif": macd_dif[i],
                            "hist": macd_hist[i],
                            "price": round(float(closes[i]), 2),
                            "msg": f"MACD底背离: 现价 ¥{closes[i]:.2f} 低于前低 ¥{closes[prev_valley]:.2f}，但DIF明显抬高",
                        })
            # 峰顶顶背离候选 (DIF > 0 且局部高峰)
            elif macd_dif[i] > macd_dif[i - 1] and macd_dif[i] > macd_dif[i + 1] and macd_dif[i] > 0:
                prev_peak = None
                for j in range(i - 8, max(0, i - 80), -1):
                    if macd_dif[j] > macd_dif[j - 1] and macd_dif[j] > macd_dif[j + 1] and macd_dif[j] > 0:
                        prev_peak = j
                        break
                if prev_peak is not None:
                    if closes[i] >= closes[prev_peak] * 1.002 and macd_dif[i] < macd_dif[prev_peak]:
                        seen_macd_bars.add(i)
                        macd_marks.append({
                            "date": dates[i],
                            "bar_idx": i,
                            "type": "top",
                            "label": "▼顶背离",
                            "dif": macd_dif[i],
                            "hist": macd_hist[i],
                            "price": round(float(closes[i]), 2),
                            "msg": f"MACD顶背离: 现价 ¥{closes[i]:.2f} 高于前高 ¥{closes[prev_peak]:.2f}，但DIF明显衰退",
                        })

    macd_marks.sort(key=lambda x: x["bar_idx"])

    # 7. 各周期独立分屏数据（用于切换分屏联动视图或单独看某个周期）
    levels_data = {}
    for p in p_list:
        p_res = results[p]
        p_df = dfs[p]
        p_dates = p_df["datetime"].astype(str).tolist() if not p_df.empty else []
        p_candles = p_df[["open", "close", "low", "high"]].values.tolist() if not p_df.empty else []
        p_bis = [
            [[p_dates[bi.start.k.k_index], bi.start.val], [p_dates[bi.end.k.k_index], bi.end.val]]
            for bi in p_res.bis
            if 0 <= bi.start.k.k_index < len(p_dates) and 0 <= bi.end.k.k_index < len(p_dates)
        ]
        p_zss = [
            {
                "start_date": p_dates[zs.start.k.k_index],
                "end_date": p_dates[zs.end.k.k_index],
                "zg": round(zs.zg, 2),
                "zd": round(zs.zd, 2),
            }
            for zs in p_res.zss
            if zs.start and zs.end
            and 0 <= zs.start.k.k_index < len(p_dates)
            and 0 <= zs.end.k.k_index < len(p_dates)
        ]
        p_macd = p_res.macd or {}
        levels_data[p] = {
            "period": p,
            "label": PERIOD_SPECS[p]["label"],
            "short_name": PERIOD_SPECS[p]["short_name"],
            "dates": p_dates,
            "candles": p_candles,
            "bis": p_bis,
            "zss": p_zss,
            "macd": {
                "hist": [round(h * 2, 3) for h in (p_macd.get("hist") or [])],
                "dif": [round(d, 3) for d in (p_macd.get("dif") or [])],
                "dea": [round(d, 3) for d in (p_macd.get("dea") or [])],
            },
        }

    # 最新价格与涨跌
    latest_close = base_df["close"].iloc[-1] if not base_df.empty else 0.0
    prev_close = base_df["close"].iloc[-2] if len(base_df) >= 2 else latest_close
    chg_pct = round((latest_close - prev_close) / prev_close * 100, 2) if prev_close else 0.0

    return {
        "code": clean_code,
        "name": stock_name,
        "periods": {
            "high": {"key": high_p, "label": PERIOD_SPECS[high_p]["label"], "name": PERIOD_SPECS[high_p]["short_name"]},
            "mid": {"key": mid_p, "label": PERIOD_SPECS[mid_p]["label"], "name": PERIOD_SPECS[mid_p]["short_name"]},
            "low": {"key": low_p, "label": PERIOD_SPECS[low_p]["label"], "name": PERIOD_SPECS[low_p]["short_name"]},
        },
        "base_period": low_p,
        "summary": {
            "latest_price": round(latest_close, 2),
            "change_pct": chg_pct,
            "latest_date": latest_dt,
            "high_state": current_high_state.to_dict(),
            "mid_state": current_mid_state.to_dict(),
            "low_state": current_low_state.to_dict(),
            "resonance_count": len(resonances),
            "is_backtracking": is_backtracking,
            "cutoff_date": cutoff_date if is_backtracking else None,
        },
        "resonances": [r.to_dict() for r in resonances],
        "unified_chart": {
            "dates": dates,
            "candles": candles,
            "volumes": volumes,
            "high_bis": high_bis,
            "high_zss": high_zss,
            "mid_bis": mid_bis,
            "mid_zss": mid_zss,
            "low_bis": low_bis,
            "low_zss": low_zss,
            "mmd_marks": mmd_marks,
            "res_marks": res_marks,
            "macd": {
                "hist": macd_hist,
                "dif": macd_dif,
                "dea": macd_dea,
                "marks": macd_marks,
            },
            "macd_marks": macd_marks,
        },
        "levels_data": levels_data,
        "backtrack_timeline": {
            "min_date": min_date,
            "max_date": max_date,
            "available_dates": available_dates,
            "current_date": latest_dt,
            "total_bars": len(available_dates),
            "current_bar_index": len(base_df) - 1 if not base_df.empty else 0,
        },
    }
