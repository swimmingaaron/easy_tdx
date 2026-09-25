#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
easy_tdx 自选监控池 30分钟 K线 ZIG 转向后台监测脚本
======================================================

功能特性：
1. A股交易时间内（09:30-11:30, 13:00-15:00），在每半点前 5 分钟（即 25 分与 55 分）自动执行：
   - 09:55 (针对 10:00 收线的前 5 分钟预警)
   - 10:25 (针对 10:30 收线的前 5 分钟预警)
   - 10:55 (针对 11:00 收线的前 5 分钟预警)
   - 11:25 (针对 11:30 午盘收线的前 5 分钟预警)
   - 13:25 (针对 13:30 收线的前 5 分钟预警)
   - 13:55 (针对 14:00 收线的前 5 分钟预警)
   - 14:25 (针对 14:30 收线的前 5 分钟预警)
   - 14:55 (针对 15:00 收盘收线的前 5 分钟预警)
2. 动态读取 watchlist.json（即 dashboard 自选监控实时行情池中的全部自选股）。
3. 多线程并发拉取 30分钟 K线并计算 ZIG 转向状态天数。
4. 筛选出当前 30分钟 ZIG 为 +1（向上反转首日，标红买入预警）或 -1（向下见顶首日，标绿卖出预警）的标的。
5. 自动推送格式化的 Markdown 警报消息到微信（支持 企业微信机器人 Webhook、Server酱、PushPlus、WxPusher）。
6. 支持测试模式（--now），立即扫描一次并输出结果，方便即时联调。

使用示例：
    # 1. 立即执行一次自选池 30分钟 ZIG 扫描（控制台查看）
    python monitor_watchlist_zig.py --now

    # 2. 立即执行并推送到企业微信群机器人
    python monitor_watchlist_zig.py --now --webhook "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=YOUR_KEY"

    # 3. 启动后台常驻监控服务（自动在 25分、55分触发）
    python monitor_watchlist_zig.py --daemon --webhook "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=YOUR_KEY"

    # 4. 指定 ZIG 转向阈值（默认 5.0%，可自选如 1.8% 或 3.0%）
    python monitor_watchlist_zig.py --now --delta 5.0
"""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import hashlib
import io
import json
import logging
import os
import sys
import time
from datetime import datetime, time as dtime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import urllib.request
import urllib.parse
import pandas as pd

# 确保控制台支持 UTF-8 输出
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# 将 src 加入 sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))


def _load_env_file():
    """读取工程目录下的 .evn / .env 文件或 notification_config.json 并载入环境变量。"""
    candidate_files = [
        PROJECT_ROOT / ".evn",
        PROJECT_ROOT / ".env",
        PROJECT_ROOT / "notification_config.json",
        PROJECT_ROOT.parent / ".evn",
        PROJECT_ROOT.parent / ".env",
    ]
    for env_path in candidate_files:
        if not env_path.is_file():
            continue
        try:
            if env_path.suffix == ".json":
                with open(env_path, "r", encoding="utf-8-sig") as f:
                    cfg = json.load(f)
                    for k, v in cfg.items():
                        if isinstance(v, str) and k.upper() not in os.environ:
                            os.environ[k.upper()] = v
            else:
                with open(env_path, "r", encoding="utf-8-sig") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            k = k.strip()
                            v = v.strip().strip("'\"")
                            if k and k not in os.environ:
                                os.environ[k] = v
        except Exception:
            pass

_load_env_file()

from easy_tdx.market_data import fetch_security_kline, fetch_realtime_pool_quotes
from easy_tdx.trading_system.engine import calculate_zig_series
from easy_tdx.watchlist_store import load_watchlist_items

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("WatchlistZigMonitor")


# ==============================================================================
# 1. 交易时间与触发时机判定
# ==============================================================================

# A 股 30 分钟 K 线半点前 5 分钟触发时段列表 (时, 分)
CHECK_SLOTS: List[Tuple[int, int]] = [
    (9, 55),
    (10, 25),
    (10, 55),
    (11, 25),
    (13, 25),
    (13, 55),
    (14, 25),
    (14, 55),
]


def is_trading_day(dt: Optional[datetime] = None) -> bool:
    """判断是否为周一至周五交易日。"""
    if dt is None:
        dt = datetime.now()
    # 0=Monday, 4=Friday, 5=Saturday, 6=Sunday
    return dt.weekday() < 5


def get_current_check_slot(now: Optional[datetime] = None) -> Optional[Tuple[int, int]]:
    """判断当前时间是否正好命中预警时间窗（分钟匹配）。"""
    if now is None:
        now = datetime.now()
    h, m = now.hour, now.minute
    for sh, sm in CHECK_SLOTS:
        if h == sh and m == sm:
            return (sh, sm)
    return None


def get_next_slot_info(now: Optional[datetime] = None) -> Tuple[str, float]:
    """获取下一个监控时间点及等待秒数。"""
    if now is None:
        now = datetime.now()
    today = now.date()

    for sh, sm in CHECK_SLOTS:
        target_dt = datetime(today.year, today.month, today.day, sh, sm, 0)
        diff = (target_dt - now).total_seconds()
        if diff > 0:
            return f"{sh:02d}:{sm:02d}", diff

    # 今天的所有时段已过，指向明天的 09:55
    tomorrow = now.date()
    # 如果明天是周六，顺延到下周一
    days_to_add = 1
    if now.weekday() == 4:  # 周五 -> 周一
        days_to_add = 3
    elif now.weekday() == 5:  # 周六 -> 周一
        days_to_add = 2

    next_day = tomorrow.fromordinal(tomorrow.toordinal() + days_to_add)
    first_sh, first_sm = CHECK_SLOTS[0]
    next_target = datetime(next_day.year, next_day.month, next_day.day, first_sh, first_sm, 0)
    diff = (next_target - now).total_seconds()
    return f"{next_day.strftime('%Y-%m-%d')} {first_sh:02d}:{first_sm:02d}", diff


def is_in_trading_hours(now: Optional[datetime] = None) -> bool:
    """判断当前时间是否处于 A 股盘中连续竞价交易时段 (09:25-11:30, 13:00-15:00)。"""
    if now is None:
        now = datetime.now()
    if not is_trading_day(now):
        return False
    t = now.time()
    from datetime import time as dt_time
    m_start = dt_time(9, 25)
    m_end = dt_time(11, 30)
    a_start = dt_time(13, 0)
    a_end = dt_time(15, 0)
    return (m_start <= t <= m_end) or (a_start <= t <= a_end)


def get_ongoing_30m_bar_label(now: Optional[datetime] = None) -> Optional[str]:
    """获取当前盘中进行中的 30分钟 Bar 时间戳标签（对齐通达信右端点格式 YYYY-MM-DD HH:MM）。"""
    if now is None:
        now = datetime.now()
    if not is_in_trading_hours(now):
        return None
    h, m = now.hour, now.minute
    total_m = h * 60 + m
    if total_m <= 10 * 60:
        target_hm = "10:00"
    elif total_m <= 10 * 60 + 30:
        target_hm = "10:30"
    elif total_m <= 11 * 60:
        target_hm = "11:00"
    elif total_m <= 11 * 60 + 30:
        target_hm = "11:30"
    elif total_m <= 13 * 60 + 30:
        target_hm = "13:30"
    elif total_m <= 14 * 60:
        target_hm = "14:00"
    elif total_m <= 14 * 60 + 30:
        target_hm = "14:30"
    else:
        target_hm = "15:00"
    return f"{now.strftime('%Y-%m-%d')} {target_hm}"


# ==============================================================================
# 2. 30分钟 K线 实时校准与 ZIG 计算
# ==============================================================================

def ensure_realtime_30m_kline(
    df: pd.DataFrame, 
    realtime_quote: Optional[Dict[str, Any]] = None,
    now: Optional[datetime] = None,
) -> pd.DataFrame:
    """
    确保 30 分钟 K 线末端数据与最新实时行情快照严格同步：
    1. 非盘中交易时段（收盘后、休市、午盘）：历史已收盘 K 线属于定型数据，严格保持原样，杜绝离线数据偏差；
    2. 盘中交易时段：
       - 若末根 Bar 正处于进行中窗口，将其收盘价校准为最新实时现价；
       - 若数据源尚未产生进行中的 Bar，将实时快照作为新 Bar 追加至末尾，确保 100% 对应盘中最新瞬时真实状态。
    """
    if df is None or df.empty:
        return df
    if not realtime_quote or not realtime_quote.get("price") or realtime_quote["price"] <= 0:
        return df

    if now is None:
        now = datetime.now()

    # 非盘中时段，不对历史定型 K 线进行覆盖
    if not is_in_trading_hours(now):
        return df

    # 快照日期校验：如果快照包含明确时间戳且非今日（如行情源仍为上一交易日昨收状态），不追加未发生周期的伪造 Bar
    quote_time = str(realtime_quote.get("time", "")).strip().replace("-", "").replace(":", "").replace(" ", "")
    today_str = now.strftime("%Y%m%d")
    if len(quote_time) >= 8 and quote_time[:8] != today_str:
        return df

    cur_price = float(realtime_quote["price"])
    ongoing_label = get_ongoing_30m_bar_label(now)
    if not ongoing_label:
        return df

    df = df.copy()
    last_dt = str(df.iloc[-1].get("datetime", "")).strip()

    if last_dt == ongoing_label:
        # 当前末根 Bar 对应进行中的时间窗，更新收盘价与最高最低价
        last_idx = df.index[-1]
        df.loc[last_idx, "close"] = cur_price
        if cur_price > df.loc[last_idx, "high"]:
            df.loc[last_idx, "high"] = cur_price
        if cur_price < df.loc[last_idx, "low"] and cur_price > 0:
            df.loc[last_idx, "low"] = cur_price
    elif last_dt < ongoing_label:
        # 进行中的时间窗尚未产生，追加为临时最新 Bar
        new_row = {
            "datetime": ongoing_label,
            "open": cur_price,
            "high": cur_price,
            "low": cur_price,
            "close": cur_price,
            "volume": 0,
            "amount": 0.0,
        }
        df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)

    return df


def check_single_stock_zig(
    item: Dict[str, str], 
    change_pct: float = 0.05,
    count: int = 120,
    realtime_quote: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """检查单只标的的 30分钟 K线 ZIG 状态（保证实时值）。"""
    code = item.get("code", "").strip()
    name = item.get("name", code).strip()
    if not code:
        return None

    try:
        # 强制穿透缓存 (force_refresh=True)，获取原生 Socket 直连的最新 30M K线
        df = fetch_security_kline(code, period="30M", count=count, force_refresh=True)
        if df is None or len(df) < 10:
            return None

        # 检查是否为有效 30分钟 分时 K 线（必须具备 HH:MM 分时时间戳）
        last_dt_str = str(df.iloc[-1].get("datetime", "")).strip()
        if len(last_dt_str) < 16 or ":" not in last_dt_str:
            return None

        # 实时合线：将实时行情快照注入 30M K线末端，保证瞬时成交价最新
        df = ensure_realtime_30m_kline(df, realtime_quote)

        closes = df["close"].values.astype(float)
        zig_days = calculate_zig_series(closes, change_pct=change_pct)
        if not zig_days:
            return None
        df["zig"] = zig_days

        cur_zig = int(zig_days[-1])
        # 仅关注反转首日 (+1 或 -1)
        if cur_zig not in (1, -1):
            return None

        last_bar = df.iloc[-1]
        prev_bar = df.iloc[-2] if len(df) >= 2 else last_bar
        cur_c = float(last_bar["close"])
        pre_c = float(prev_bar["close"])
        
        # 涨跌幅优先取实时行情，若无则基于上一根 30M Bar 计算
        if realtime_quote and "change_pct" in realtime_quote and realtime_quote["change_pct"] is not None:
            chg_pct = float(realtime_quote["change_pct"])
        else:
            chg_pct = round((cur_c - pre_c) / max(0.001, pre_c) * 100, 2)
            
        bar_time = str(last_bar.get("datetime", ""))

        return {
            "code": code,
            "name": name,
            "zig": cur_zig,
            "type": "BUY" if cur_zig == 1 else "SELL",
            "type_desc": "反转向上 (+1)" if cur_zig == 1 else "见顶向下 (-1)",
            "close": cur_c,
            "chg_pct": chg_pct,
            "volume": int(last_bar.get("volume", 0)),
            "amount": float(last_bar.get("amount", 0.0)),
            "bar_time": bar_time,
            "is_realtime_verified": True,
            "kline_df": df,
        }
    except Exception as e:
        logger.debug(f"检查 {code} ({name}) 30M ZIG 出错: {e}")
        return None


def fetch_realtime_snapshot_quotes(stock_codes: List[str]) -> Dict[str, Dict[str, Any]]:
    """批量高速抓取股票实时快照行情 (最新价, 开高低收, 涨跌幅, 成交量, 成交额, 时间)。"""
    if not stock_codes:
        return {}

    def _pfx(c: str) -> str:
        c = str(c).strip()
        p = "sh" if (c.startswith("6") or c.startswith("9")) else ("bj" if (c.startswith("8") or c.startswith("4")) else "sz")
        return f"{p}{c}"

    q_codes = [_pfx(c) for c in stock_codes]
    chunk_size = 70
    chunks = [q_codes[i:i + chunk_size] for i in range(0, len(q_codes), chunk_size)]
    res: Dict[str, Dict[str, Any]] = {}

    for chk in chunks:
        url = "https://qt.gtimg.cn/q=" + ",".join(chk)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                text = resp.read().decode("gbk", errors="ignore")
            for line in text.strip().split(";"):
                line = line.strip()
                if not line or "=" not in line:
                    continue
                val = line.split("=")[1].strip('"')
                p = val.split("~")
                if len(p) >= 35:
                    code = p[2]
                    price = float(p[3]) if p[3] and p[3] != "0.00" else None
                    if price is not None and price > 0:
                        res[code] = {
                            "code": code,
                            "name": p[1],
                            "price": price,
                            "pre_close": float(p[4]) if p[4] else price,
                            "open": float(p[5]) if p[5] else price,
                            "high": float(p[33]) if p[33] else price,
                            "low": float(p[34]) if p[34] else price,
                            "volume": int(p[36]) * 100 if p[36] else 0,
                            "amount": float(p[37]) * 10000.0 if p[37] else 0.0,
                            "time": p[30],
                            "change_pct": float(p[32]) if p[32] else 0.0,
                        }
        except Exception:
            pass

    return res


def scan_watchlist_zig(
    change_pct: float = 0.05, 
    max_workers: int = 1
) -> Dict[str, List[Dict[str, Any]]]:
    """扫描整个 watchlist.json 中所有标的的 30分钟实时 ZIG。"""
    items = load_watchlist_items()
    if not items:
        logger.warning("未检测到有效自选股（watchlist.json 为空）")
        return {"buy_signals": [], "sell_signals": []}

    logger.info(f"开始扫描自选池 30分钟 ZIG 实时状态... 标的总数: {len(items)}, ZIG阈值: {change_pct*100:.1f}%")
    t0 = time.time()

    # 1. 批量预先拉取全自选池的瞬时实时行情快照 (Level-2 级别毫秒级更新)
    codes = [item["code"] for item in items if item.get("code")]
    quotes_map = fetch_realtime_snapshot_quotes(codes)

    buy_signals = []
    sell_signals = []

    # 2. 依次/并发穿透缓存获取 30M K线并实时合线计算 ZIG
    if max_workers <= 1:
        for item in items:
            res = check_single_stock_zig(
                item, 
                change_pct, 
                120, 
                quotes_map.get(item.get("code", ""))
            )
            if res:
                if res["zig"] == 1:
                    buy_signals.append(res)
                elif res["zig"] == -1:
                    sell_signals.append(res)
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(
                    check_single_stock_zig, 
                    item, 
                    change_pct, 
                    120, 
                    quotes_map.get(item.get("code", ""))
                ): item
                for item in items
            }
            for future in concurrent.futures.as_completed(futures):
                res = future.result()
                if res:
                    if res["zig"] == 1:
                        buy_signals.append(res)
                    elif res["zig"] == -1:
                        sell_signals.append(res)

    # 排序：买入信号按涨幅从大到小，卖出信号按跌幅从小到大
    buy_signals.sort(key=lambda x: x["chg_pct"], reverse=True)
    sell_signals.sort(key=lambda x: x["chg_pct"])

    cost = time.time() - t0
    logger.info(
        f"自选池 30M 实时扫描完毕，耗时: {cost:.2f}秒 | 向上反转(+1): {len(buy_signals)} 只 | 见顶向下(-1): {len(sell_signals)} 只"
    )

    return {
        "buy_signals": buy_signals,
        "sell_signals": sell_signals,
    }


_MATPLOTLIB_FONT_CONFIGURED = False

def _configure_matplotlib_chinese_fonts() -> None:
    """跨平台自动适配中文字体（macOS Apple Silicon M1-M4 / Windows / Linux），杜绝字体缺失方块乱码。"""
    global _MATPLOTLIB_FONT_CONFIGURED
    if _MATPLOTLIB_FONT_CONFIGURED:
        return

    import platform
    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    # 1. macOS (Apple Silicon M1-M4 / Intel) 系统中文字体直接注册支持
    if platform.system() == "Darwin":
        mac_fonts = [
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/STHeiti Light.ttc",
            "/System/Library/Fonts/STHeiti Medium.ttc",
            "/System/Library/Fonts/Hiragino Sans GB.ttc",
            "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
            "/System/Library/Fonts/Supplemental/Songti.ttc",
            "/Library/Fonts/Arial Unicode.ttf",
        ]
        for fpath in mac_fonts:
            if os.path.exists(fpath):
                try:
                    font_manager.fontManager.addfont(fpath)
                except Exception:
                    pass

    # 2. 候选字体优先队列（macOS 优先 -> Windows 优先 -> Linux 开源）
    candidates = [
        "PingFang SC",          # macOS 苹方（系统默认首选）
        "Hiragino Sans GB",     # macOS 冬青黑体
        "Heiti SC",             # macOS 黑体-简
        "STHeiti",              # macOS 华文黑体
        "Songti SC",            # macOS 宋体-简
        "Arial Unicode MS",     # macOS / 通用
        "Microsoft YaHei",      # Windows 微软雅黑
        "SimHei",               # Windows 中易黑体
        "SimSun",               # Windows 宋体
        "Noto Sans CJK SC",     # Linux 思源黑体
        "WenQuanYi Micro Hei",  # Linux 文泉驿微米黑
        "WenQuanYi Zen Hei",
    ]

    installed = {f.name for f in font_manager.fontManager.ttflist}
    available = [f for f in candidates if f in installed]

    if available:
        plt.rcParams["font.sans-serif"] = available + ["sans-serif"]
    else:
        plt.rcParams["font.sans-serif"] = candidates + ["sans-serif"]

    plt.rcParams["axes.unicode_minus"] = False
    _MATPLOTLIB_FONT_CONFIGURED = True


def generate_kline_snapshot(
    code: str,
    name: str,
    df: pd.DataFrame,
    zig_val: int,
    change_pct: float = 0.0,
    delta_pct: float = 0.05,
    n_bars: int = 50,
) -> bytes:
    """生成专业的 30M K线及 ZIG 转向快照图片字节流 (PNG)。"""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.patches as patches
    except ImportError:
        logger.warning("未安装 matplotlib，跳过 30M K线快照图片生成。可通过 pip install matplotlib 安装。")
        return b""

    try:
        if "zig" not in df.columns:
            closes = df["close"].values.astype(float)
            df["zig"] = calculate_zig_series(closes, change_pct=delta_pct)

        df_plot = df.tail(n_bars).reset_index(drop=True)
        if len(df_plot) < 5:
            return b""

        last_idx = len(df_plot) - 1
        last_row = df_plot.iloc[last_idx]
        last_c = float(last_row["close"])

        # 跨平台自动配置中文字体 (兼容 macOS M1-M4 苹方/冬青, Windows 微软雅黑, Linux 思源)
        _configure_matplotlib_chinese_fonts()

        fig, (ax1, ax2) = plt.subplots(
            2, 1,
            figsize=(9.4, 5.8),
            gridspec_kw={"height_ratios": [3.6, 1.0]},
            facecolor="#18191d"
        )
        ax1.set_facecolor("#18191d")
        ax2.set_facecolor("#18191d")

        # 细灰背景网格
        ax1.grid(True, linestyle="--", alpha=0.15, color="#ffffff")
        ax2.grid(True, linestyle="--", alpha=0.15, color="#ffffff")

        # 1. 蜡烛图
        for i, row in df_plot.iterrows():
            o = float(row["open"])
            c = float(row["close"])
            h = float(row["high"])
            l = float(row["low"])
            color = "#f23645" if c >= o else "#089981"
            ax1.vlines(i, l, h, color=color, linewidth=1.2, zorder=2)
            lower = min(o, c)
            height = max(abs(c - o), 0.01)
            rect = patches.Rectangle(
                (i - 0.35, lower), 0.7, height,
                facecolor=color, edgecolor=color, zorder=3
            )
            ax1.add_patch(rect)

        # 2. 均线 MA5, MA10
        ma5 = df_plot["close"].rolling(5).mean()
        ma10 = df_plot["close"].rolling(10).mean()
        ax1.plot(ma5, color="#ffd700", label="MA5", linewidth=1.1, alpha=0.8, zorder=4)
        ax1.plot(ma10, color="#00bcd4", label="MA10", linewidth=1.1, alpha=0.8, zorder=4)

        # 3. ZIG 波峰波谷折线 (ZigZag 转向轨迹)
        pivots_x = []
        pivots_y = []
        full_zig = df["zig"].values
        offset_in_full = len(df) - len(df_plot)
        for idx_full in range(1, len(df)):
            z_curr = full_zig[idx_full]
            # 顶反转 (-1): 前一个点是波峰最高价
            if z_curr == -1:
                p_idx = (idx_full - 1) - offset_in_full
                if 0 <= p_idx < len(df_plot):
                    pivots_x.append(p_idx)
                    pivots_y.append(float(df_plot.iloc[p_idx]["high"]))
            # 底反转 (+1): 前一个点是波谷最低价
            elif z_curr == 1:
                p_idx = (idx_full - 1) - offset_in_full
                if 0 <= p_idx < len(df_plot):
                    pivots_x.append(p_idx)
                    pivots_y.append(float(df_plot.iloc[p_idx]["low"]))

        if pivots_x and pivots_x[-1] != last_idx:
            pivots_x.append(last_idx)
            pivots_y.append(last_c)

        if len(pivots_x) >= 2:
            ax1.plot(
                pivots_x, pivots_y,
                color="#ff9800", linestyle="--", linewidth=1.5,
                alpha=0.9, zorder=5, label="ZIG 轨迹"
            )

        # 4. 标记当前视图中的所有反转点 (买入 / 卖出)
        price_span = df_plot["high"].max() - df_plot["low"].min()
        offset = max(price_span * 0.08, 0.3)

        for i in range(len(df_plot)):
            row_i = df_plot.iloc[i]
            z_i = int(row_i.get("zig", 0))
            c_val = float(row_i["close"])
            l_val = float(row_i["low"])
            h_val = float(row_i["high"])
            is_latest = (i == last_idx)

            if z_i == 1:
                # 向上反转 -> 买入信号
                tag = f"▲ 买入 (+1)\n¥{c_val:.2f}" if is_latest else f"▲ 买入\n¥{c_val:.2f}"
                ax1.annotate(
                    tag,
                    xy=(i, l_val),
                    xytext=(i, l_val - offset),
                    arrowprops=dict(facecolor="#f23645", edgecolor="#ffffff", shrink=0.08, width=1.5, headwidth=5),
                    ha="center", va="top", fontsize=9.5 if is_latest else 8.2, fontweight="bold", color="#ffffff",
                    bbox=dict(
                        boxstyle="round,pad=0.32",
                        facecolor="#f23645",
                        edgecolor="#ffffff" if is_latest else "none",
                        alpha=0.95 if is_latest else 0.88
                    ),
                    zorder=7 if is_latest else 6
                )
            elif z_i == -1:
                # 向下见顶 -> 卖出信号
                tag = f"▼ 卖出 (-1)\n¥{c_val:.2f}" if is_latest else f"▼ 卖出\n¥{c_val:.2f}"
                ax1.annotate(
                    tag,
                    xy=(i, h_val),
                    xytext=(i, h_val + offset),
                    arrowprops=dict(facecolor="#089981", edgecolor="#ffffff", shrink=0.08, width=1.5, headwidth=5),
                    ha="center", va="bottom", fontsize=9.5 if is_latest else 8.2, fontweight="bold", color="#ffffff",
                    bbox=dict(
                        boxstyle="round,pad=0.32",
                        facecolor="#089981",
                        edgecolor="#ffffff" if is_latest else "none",
                        alpha=0.95 if is_latest else 0.88
                    ),
                    zorder=7 if is_latest else 6
                )

        # Y 轴自适应留白，保证所有买卖点文字标签清晰完整
        ax1.set_ylim(bottom=df_plot["low"].min() - offset * 1.8, top=df_plot["high"].max() + offset * 1.8)

        # 5. 顶部 Header 与状态栏
        chg_color = "#f23645" if change_pct >= 0 else "#089981"
        sig_text = "向上反转买入 (+1)" if zig_val == 1 else "见顶向下卖出 (-1)"
        title_str = f"{code} {name}  ·  30分钟 K线  [ 全反转点标记 ]"
        bar_dt = str(last_row.get("datetime", ""))
        status_str = f"最新收盘: ¥{last_c:.2f} ({change_pct:+.2f}%)   当前信号: {sig_text}   时间: {bar_dt}   ZIG阈值: {delta_pct*100:.1f}%"

        fig.suptitle(title_str, fontsize=13, fontweight="bold", color="#ffffff", x=0.12, y=0.96, ha="left")
        ax1.set_title(status_str, fontsize=9.2, color=chg_color, loc="left", pad=6)

        # 6. 成交量副图
        for i, row in df_plot.iterrows():
            c = float(row["close"])
            o = float(row["open"])
            v = float(row.get("volume", 0))
            color = "#f23645" if c >= o else "#089981"
            ax2.bar(i, v, color=color, width=0.7, alpha=0.85)

        # 7. X轴时间刻度
        n = len(df_plot)
        step = max(1, n // 6)
        xticks = list(range(0, n, step))
        if (n - 1) not in xticks:
            xticks.append(n - 1)

        def _fmt_x(dt_str: str) -> str:
            s = str(dt_str).strip()
            if len(s) >= 16:
                return s[5:16]  # MM-DD HH:MM
            return s

        xlabels = [_fmt_x(df_plot.iloc[idx]["datetime"]) for idx in xticks]
        ax2.set_xticks(xticks)
        ax2.set_xticklabels(xlabels, color="#a0a0a0", fontsize=8)
        ax1.set_xticks([])

        ax1.yaxis.tick_right()
        ax2.yaxis.tick_right()
        for ax in (ax1, ax2):
            ax.tick_params(colors="#a0a0a0", labelsize=8)
            for spine in ax.spines.values():
                spine.set_color("#2d2e33")

        plt.tight_layout(rect=[0, 0, 1, 0.94])

        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=130, facecolor=fig.get_facecolor(), edgecolor="none")
        plt.close(fig)

        img_bytes = buf.getvalue()

        # 自动归档至 data/snapshots/
        try:
            snapshot_dir = PROJECT_ROOT / "data" / "snapshots"
            snapshot_dir.mkdir(parents=True, exist_ok=True)
            clean_time = bar_dt.replace("-", "").replace(":", "").replace(" ", "_")
            sig_name = "BUY" if zig_val == 1 else "SELL"
            img_path = snapshot_dir / f"{code}_{sig_name}_{clean_time}.png"
            img_path.write_bytes(img_bytes)
            logger.info(f"已生成 {code} {name} 30M K线快照: {img_path.relative_to(PROJECT_ROOT)}")
        except Exception as e:
            logger.debug(f"保存快照图片到本地出错: {e}")

        return img_bytes
    except Exception as exc:
        logger.error(f"生成 {code} {name} 30M K线快照失败: {exc}")
        return b""


# ==============================================================================
# 3. 微信通知推送实现 (支持企微机器人、Server酱、PushPlus、WxPusher)
# ==============================================================================

class WeChatNotifier:
    """统一微信通知推送客户端。"""

    def __init__(
        self,
        wecom_webhook: Optional[str] = None,
        pushplus_token: Optional[str] = None,
        serverchan_key: Optional[str] = None,
        wxpusher_app_token: Optional[str] = None,
        wxpusher_uids: Optional[List[str]] = None,
    ):
        self.wecom_webhook = wecom_webhook or os.environ.get("WECHAT_WEBHOOK_URL", "")
        self.pushplus_token = pushplus_token or os.environ.get("PUSHPLUS_TOKEN", "")
        self.serverchan_key = serverchan_key or os.environ.get("SERVERCHAN_KEY", "")
        self.wxpusher_app_token = wxpusher_app_token or os.environ.get("WXPUSHER_APP_TOKEN", "")
        self.wxpusher_uids = wxpusher_uids or (
            [u.strip() for u in os.environ.get("WXPUSHER_UIDS", "").split(",") if u.strip()]
        )

    def is_configured(self) -> bool:
        """检查是否有任何一个微信推送通道配置有效。"""
        return bool(
            self.wecom_webhook or self.pushplus_token or self.serverchan_key or self.wxpusher_app_token
        )

    def _post_json(self, url: str, data: dict, timeout: int = 8) -> dict:
        req = urllib.request.Request(
            url,
            data=json.dumps(data, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8", "User-Agent": "easy_tdx/1.0"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)

    def send_notification(self, title: str, markdown_content: str) -> bool:
        """多通道推送微信通知。"""
        success = False

        # 1. 企业微信机器人 Webhook (官方推荐通道)
        if self.wecom_webhook:
            try:
                payload = {
                    "msgtype": "markdown",
                    "markdown": {
                        "content": f"### {title}\n\n{markdown_content}"
                    }
                }
                res_data = self._post_json(self.wecom_webhook, payload)
                if res_data.get("errcode") == 0:
                    logger.info("企业微信机器人通知发送成功！")
                    success = True
                else:
                    logger.error(f"企业微信机器人发送失败: {res_data}")
            except Exception as e:
                logger.error(f"企业微信机器人请求异常: {e}")

        # 2. PushPlus (推送加 - 个人微信模板消息)
        if self.pushplus_token:
            try:
                url = "http://www.pushplus.plus/send"
                payload = {
                    "token": self.pushplus_token,
                    "title": title,
                    "content": markdown_content,
                    "template": "markdown",
                }
                res_data = self._post_json(url, payload)
                if res_data.get("code") == 200:
                    logger.info("PushPlus 微信通知发送成功！")
                    success = True
                else:
                    logger.error(f"PushPlus 发送失败: {res_data}")
            except Exception as e:
                logger.error(f"PushPlus 请求异常: {e}")

        # 3. Server酱 (FTQQ)
        if self.serverchan_key:
            try:
                url = f"https://sctapi.ftqq.com/{self.serverchan_key}.send"
                encoded_data = urllib.parse.urlencode({"title": title, "desp": markdown_content}).encode("utf-8")
                req = urllib.request.Request(
                    url,
                    data=encoded_data,
                    headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "easy_tdx/1.0"},
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=8) as resp:
                    res_data = json.loads(resp.read().decode("utf-8"))
                    if res_data.get("code") == 0:
                        logger.info("Server酱微信通知发送成功！")
                        success = True
                    else:
                        logger.error(f"Server酱发送失败: {res_data}")
            except Exception as e:
                logger.error(f"Server酱请求异常: {e}")

        # 4. WxPusher
        if self.wxpusher_app_token and self.wxpusher_uids:
            try:
                url = "https://wxpusher.zjiecode.com/api/send/message"
                payload = {
                    "appToken": self.wxpusher_app_token,
                    "content": f"## {title}\n\n{markdown_content}",
                    "contentType": 3,  # 3: markdown
                    "uids": self.wxpusher_uids,
                }
                res_data = self._post_json(url, payload)
                if res_data.get("code") == 1000:
                    logger.info("WxPusher 微信通知发送成功！")
                    success = True
                else:
                    logger.error(f"WxPusher 发送失败: {res_data}")
            except Exception as e:
                logger.error(f"WxPusher 请求异常: {e}")

        return success

    def send_image(self, image_bytes: bytes) -> bool:
        """推送 K 线快照图片消息（支持企业微信机器人）。"""
        if not image_bytes:
            return False

        success = False
        # 1. 企业微信机器人原生图片接口 (msgtype: image, base64 + md5)
        if self.wecom_webhook:
            try:
                b64_str = base64.b64encode(image_bytes).decode("utf-8")
                md5_str = hashlib.md5(image_bytes).hexdigest()
                payload = {
                    "msgtype": "image",
                    "image": {
                        "base64": b64_str,
                        "md5": md5_str,
                    },
                }
                res_data = self._post_json(self.wecom_webhook, payload)
                if res_data.get("errcode") == 0:
                    logger.info("企业微信机器人 30M K线快照图片 发送成功！")
                    success = True
                else:
                    logger.error(f"企业微信机器人图片发送失败: {res_data}")
            except Exception as e:
                logger.error(f"企业微信机器人发送图片异常: {e}")

        return success



def format_zig_message(
    scan_results: Dict[str, List[Dict[str, Any]]],
    slot_desc: str,
    delta_pct: float
) -> Tuple[str, str]:
    """格式化微信 Markdown 预警通知。"""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    buy_list = scan_results.get("buy_signals", [])
    sell_list = scan_results.get("sell_signals", [])

    total_count = len(buy_list) + len(sell_list)
    title = f"🔔 自选池 30M ZIG 转向预警 [{slot_desc}]"

    md_lines = [
        f"> **触发时间**: `{now_str}`",
        f"> **监控周期**: `30分钟 K线` (转向阈值: `{delta_pct*100:.1f}%`)",
        f"> **最新预警**: 🔴 向上反转 `{len(buy_list)}` 只 | 🟢 见顶回落 `{len(sell_list)}` 只",
        "",
    ]

    if buy_list:
        md_lines.append("### 🔴 向上反转信号 (+1 反转买入)")
        for item in buy_list:
            amt_yi = round(item['amount'] / 1e8, 2) if item.get('amount') else 0
            chg_sign = "+" if item['chg_pct'] >= 0 else ""
            md_lines.append(
                f"- **{item['code']} {item['name']}** : 最新价 `¥{item['close']:.2f}` ({chg_sign}{item['chg_pct']}%) | 30M成交 `{amt_yi}亿` | 时间 `{item['bar_time']}`"
            )
        md_lines.append("")

    if sell_list:
        md_lines.append("### 🟢 向下见顶信号 (-1 见顶卖出)")
        for item in sell_list:
            amt_yi = round(item['amount'] / 1e8, 2) if item.get('amount') else 0
            chg_sign = "+" if item['chg_pct'] >= 0 else ""
            md_lines.append(
                f"- **{item['code']} {item['name']}** : 最新价 `¥{item['close']:.2f}` ({chg_sign}{item['chg_pct']}%) | 30M成交 `{amt_yi}亿` | 时间 `{item['bar_time']}`"
            )
        md_lines.append("")

    if not buy_list and not sell_list:
        md_lines.append("自选监控池内各标的当前未出现 30分钟 ZIG 转向首日信号。")

    md_lines.append("---")
    md_lines.append("*easy_tdx 原生量化投研引擎 · 自动实时监测*")

    return title, "\n".join(md_lines)


# ==============================================================================
# 4. 主流程与常驻调度器
# ==============================================================================

def run_single_scan_and_notify(
    notifier: WeChatNotifier,
    delta: float = 0.05,
    slot_desc: str = "即时扫描",
    notify_if_empty: bool = False
) -> int:
    """执行一次扫描，并根据配置发送通知。"""
    res = scan_watchlist_zig(change_pct=delta)
    buy_list = res.get("buy_signals", [])
    sell_list = res.get("sell_signals", [])
    total_signals = len(buy_list) + len(sell_list)

    title, content = format_zig_message(res, slot_desc, delta)

    # 打印到控制台
    print("\n" + "=" * 68)
    print(f"【{title}】")
    print("-" * 68)
    print(content)
    print("=" * 68 + "\n")

    if total_signals > 0 or notify_if_empty:
        if notifier.is_configured():
            notifier.send_notification(title, content)
            # 为检测到的转向标的生成并推送 30M K 线走势快照图片
            all_signals = buy_list + sell_list
            for sig in all_signals[:5]:
                kline_df = sig.get("kline_df")
                if kline_df is not None and not kline_df.empty:
                    img_bytes = generate_kline_snapshot(
                        code=sig["code"],
                        name=sig["name"],
                        df=kline_df,
                        zig_val=sig["zig"],
                        change_pct=sig.get("chg_pct", 0.0),
                        delta_pct=delta,
                    )
                    if img_bytes:
                        notifier.send_image(img_bytes)
        else:
            logger.warning(
                "检测到 ZIG 转向信号，但尚未配置微信通知通道（企业微信 Webhook / PushPlus / Server酱）。"
            )
            logger.info("提示: 启动时可通过 --webhook 参数传入企业微信 Webhook 链接。")
            # 即使未配置通知，也生成并归档本地快照供查看
            for sig in (buy_list + sell_list)[:5]:
                kline_df = sig.get("kline_df")
                if kline_df is not None and not kline_df.empty:
                    generate_kline_snapshot(
                        code=sig["code"],
                        name=sig["name"],
                        df=kline_df,
                        zig_val=sig["zig"],
                        change_pct=sig.get("chg_pct", 0.0),
                        delta_pct=delta,
                    )
    else:
        logger.info("当前自选股无 30M ZIG 转向首日(+1/-1)标的，跳过微信推送。")

    return total_signals


def run_daemon_loop(
    notifier: WeChatNotifier,
    delta: float = 0.05,
    force_trading_day_check: bool = True
) -> None:
    """后台常驻监控服务，在每个交易日的 25分与 55分自动执行。"""
    logger.info("=" * 68)
    logger.info("easy_tdx 自选池 30分钟 ZIG 微信推送后台守护服务已启动！")
    logger.info(f"监控触发时段: 每半点前 5 分钟 (09:55, 10:25, 10:55, 11:25, 13:25, 13:55, 14:25, 14:55)")
    logger.info(f"ZIG 转向阈值: {delta*100:.1f}%")
    logger.info(f"微信通知配置: {'已就绪' if notifier.is_configured() else '未配置 (控制台日志模式)'}")
    logger.info("=" * 68)

    last_executed_slot: Optional[str] = None

    while True:
        try:
            now = datetime.now()
            today_str = now.strftime("%Y-%m-%d")

            # 1. 检查是否为交易日（周一至周五）
            if force_trading_day_check and not is_trading_day(now):
                next_desc, wait_sec = get_next_slot_info(now)
                logger.info(f"今日为非交易日（周末）。下次监控时间: {next_desc}，休眠中...")
                time.sleep(min(300, max(10, wait_sec)))
                continue

            # 2. 检查当前是否命中监控时间点 (25分 或 55分)
            matched_slot = get_current_check_slot(now)
            if matched_slot:
                slot_key = f"{today_str}_{matched_slot[0]:02d}:{matched_slot[1]:02d}"
                if slot_key != last_executed_slot:
                    slot_desc = f"{matched_slot[0]:02d}:{matched_slot[1]:02d}"
                    logger.info(f"⏰ 命中监控时间点 [{slot_desc}]，正在触发自选池 30分钟 ZIG 扫描...")
                    run_single_scan_and_notify(
                        notifier=notifier,
                        delta=delta,
                        slot_desc=slot_desc,
                        notify_if_empty=False
                    )
                    last_executed_slot = slot_key

            # 3. 动态休眠 10 秒
            time.sleep(10)

        except KeyboardInterrupt:
            logger.info("接收到退出指令，后台监控服务正常终止。")
            break
        except Exception as e:
            logger.error(f"监控主循环异常: {e}", exc_info=True)
            time.sleep(15)


def main():
    parser = argparse.ArgumentParser(
        description="easy_tdx 自选监控池 30分钟 K线 ZIG 转向后台监测与微信预警脚本"
    )
    parser.add_argument(
        "--now",
        action="store_true",
        help="立即执行一次 30M ZIG 扫描测试并输出结果",
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="启动后台常驻监控服务（在交易日 25分与 55分自动触发）",
    )
    default_webhook = os.environ.get("WECHAT_WEBHOOK_URL") or os.environ.get("WECHAT_WEBHOOK")
    default_pushplus = os.environ.get("PUSHPLUS_TOKEN")
    default_serverchan = os.environ.get("SERVERCHAN_KEY")

    parser.add_argument(
        "--delta",
        type=float,
        default=5.0,
        help="ZIG 转向百分比阈值 (默认: 5.0，即 5%%)",
    )
    parser.add_argument(
        "--webhook",
        type=str,
        default=default_webhook,
        help="企业微信机器人 Webhook 链接 (默认自动从 .env/.evn 中的 WECHAT_WEBHOOK_URL 读取)",
    )
    parser.add_argument(
        "--pushplus-token",
        type=str,
        default=default_pushplus,
        help="PushPlus (推送加) Token，用于推送至个人微信 (默认自动从 PUSHPLUS_TOKEN 读取)",
    )
    parser.add_argument(
        "--serverchan-key",
        type=str,
        default=default_serverchan,
        help="Server酱 SendKey，用于推送至微信服务号 (默认自动从 SERVERCHAN_KEY 读取)",
    )
    parser.add_argument(
        "--notify-empty",
        action="store_true",
        help="当无反转信号时也推送微信通知（默认仅在有信号时推送）",
    )
    parser.add_argument(
        "--ignore-trading-day",
        action="store_true",
        help="忽略周末交易日限制（调试测试用途）",
    )

    args = parser.parse_args()

    change_pct = args.delta / 100.0 if args.delta > 1.0 else args.delta

    notifier = WeChatNotifier(
        wecom_webhook=args.webhook,
        pushplus_token=args.pushplus_token,
        serverchan_key=args.serverchan_key,
    )

    if args.now or not args.daemon:
        # 单次执行模式
        run_single_scan_and_notify(
            notifier=notifier,
            delta=change_pct,
            slot_desc="即时扫描",
            notify_if_empty=args.notify_empty
        )
        if not args.daemon:
            return

    # 常驻监控模式
    run_daemon_loop(
        notifier=notifier,
        delta=change_pct,
        force_trading_day_check=not args.ignore_trading_day
    )


if __name__ == "__main__":
    main()
