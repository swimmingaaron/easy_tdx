#!/usr/bin/env python3
"""
easy_tdx 自选监控池 均线四边形策略 (擒牛战法) 后台监测与微信预警脚本
========================================================================

功能特性：
1. 战法原理：
   - 通达信经典「均线四边形擒牛战法」：MA5、MA10、MA20、MA30 在低位完成四次交叉形成闭合几何四边形：
     * P1: MA5 向上金叉 MA20 (左下角)
     * P2: MA5 向上金叉 MA30 (左上角)
     * P3: MA10 向上金叉 MA20 (右下角)
     * P4: MA10 向上金叉 MA30 (右上角)
   - 过滤与评级：
     * 生命线 MA30 走平或上翘趋势过滤，彻底杜绝单边下行中继伪反弹
     * 动能指标共振确认 (KDJ / RSI / MACD)
     * 近似平行四边形几何规则度打分 (0-100分)
     * 底价锚定：记录形态起爆前阶段最低价作为防守基准与止损锚
   - 实战细分买点识别：
     * 【沿5日线强攻】/【闭合加速】：刚闭合当日放量阳线脱离成本区
     * 【回踩10日线抢筹】：洗盘K线低点精准触碰10日均线守住支撑
     * 【空中加油二次起爆】：确认10日线支撑后，长阳突破平台展开第二波主升浪
     * 【回踩20日线】/【回踩30日线】：生命线平台稳健低吸
   - 风险防守预警：跌破 MA20 趋势破位死叉或硬止损离场。

2. 监控周期：
   - 默认支持「日线 (DAY)」级别（擒牛主战场），亦支持「周线 (WEEK)」大波段擒牛及「60M/30M」短线级别。
   - 盘中实时价格注入：交易时段通过 Level-2 实时行情快照动态校准当日未收盘 K 线，实现盘中瞬时买点捕捉。

3. 微信多通道告警：
   - 企业微信群机器人 Webhook (支持 Markdown 消息 + 高清暗黑风 K 线快照图片直接推送)
   - PushPlus (推送加 - 个人微信模板消息)
   - Server酱 (FTQQ - 微信服务号通知)
   - WxPusher (微信推送平台)

4. 执行模式：
   - 单次即时扫描 (--now)：立即执行一次扫描并控制台打印结果。
   - 后台守护进程 (--daemon)：在交易日关键决策时段（如 09:35, 10:00, 11:20, 13:30, 14:30, 14:55）自动巡检。
   - 全市场扫描 (--all / -a)：扫描全市场 5,200+ 只 A 股标的，并自动多线程并发提速与导出 CSV。
   - 指数标的池 (--universe core / hs300 / zz500 / zz1000)：快速扫描主流权重与中盘成长龙头。

使用示例：
    # 1. 立即执行一次自选池均线四边形日线扫描（控制台查看）
    python monitor_watchlist_quadrilateral.py --now

    # 2. 全市场 5,200+ 只股票均线四边形大满贯扫描，自动导出 CSV
    python monitor_watchlist_quadrilateral.py --all --now

    # 3. 全市场扫描，仅保留高规则度(>=85分)且在近3日内触发的标的
    python monitor_watchlist_quadrilateral.py --all --lookback 3 --min-score 85 --now

    # 4. 扫描中证500或沪深300指数成分股并导出结果
    python monitor_watchlist_quadrilateral.py --universe zz500 --now -o output/quad_zz500.csv

    # 5. 扫描指定股票池并推送到企业微信群机器人
    python monitor_watchlist_quadrilateral.py --now --stock 600592,600072,000668 --webhook "YOUR_WEBHOOK_URL"

    # 6. 启动后台常驻守护监控服务（交易日定时自动扫描）
    python monitor_watchlist_quadrilateral.py --daemon
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
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

# 确保控制台支持 UTF-8 输出，杜绝 Windows 乱码
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
                with open(env_path, encoding="utf-8-sig") as f:
                    cfg = json.load(f)
                    for k, v in cfg.items():
                        if isinstance(v, str) and k.upper() not in os.environ:
                            os.environ[k.upper()] = v
            else:
                with open(env_path, encoding="utf-8-sig") as f:
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

from easy_tdx.market_data import fetch_security_kline
from easy_tdx.stock_lookup import get_stock_name
from easy_tdx.strategies.registry import get_strategy
from easy_tdx.watchlist_store import load_watchlist_items
from easy_tdx.screener.universe import get_universe_symbols

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("WatchlistQuadMonitor")


# ==============================================================================
# 1. 交易时间与守护进程触发时机判定
# ==============================================================================

# 日线级别常驻监控的关键时点 (时, 分)
# 涵盖：早盘初筛 (09:35)、早盘量能确立 (10:00)、午盘收盘前 (11:20)、午后初段 (13:30)、尾盘抢筹 (14:30)、收盘定型 (14:55)
DAY_CHECK_SLOTS: list[tuple[int, int]] = [
    (9, 35),
    (10, 0),
    (11, 20),
    (13, 30),
    (14, 30),
    (14, 55),
]

# 分钟级别监控时点 (每半点前 5 分钟)
INTRADAY_CHECK_SLOTS: list[tuple[int, int]] = [
    (9, 55),
    (10, 25),
    (10, 55),
    (11, 25),
    (13, 25),
    (13, 55),
    (14, 25),
    (14, 55),
]


def is_trading_day(dt: datetime | None = None) -> bool:
    """判断是否为周一至周五交易日。"""
    if dt is None:
        dt = datetime.now()
    return dt.weekday() < 5


def is_in_trading_hours(now: datetime | None = None) -> bool:
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


def get_current_check_slot(
    now: datetime | None = None,
    slots: list[tuple[int, int]] | None = None
) -> tuple[int, int] | None:
    """判断当前时间是否正好命中预警时间窗（分钟匹配）。"""
    if now is None:
        now = datetime.now()
    if slots is None:
        slots = DAY_CHECK_SLOTS
    h, m = now.hour, now.minute
    for sh, sm in slots:
        if h == sh and m == sm:
            return (sh, sm)
    return None


def get_next_slot_info(
    now: datetime | None = None,
    slots: list[tuple[int, int]] | None = None
) -> tuple[str, float]:
    """获取下一个监控时间点及等待秒数。"""
    if now is None:
        now = datetime.now()
    if slots is None:
        slots = DAY_CHECK_SLOTS
    today = now.date()

    for sh, sm in slots:
        target_dt = datetime(today.year, today.month, today.day, sh, sm, 0)
        diff = (target_dt - now).total_seconds()
        if diff > 0:
            return f"{sh:02d}:{sm:02d}", diff

    # 今天所有时段已过，指向明天的第一个时点
    days_to_add = 1
    if now.weekday() == 4:  # 周五 -> 周一
        days_to_add = 3
    elif now.weekday() == 5:  # 周六 -> 周一
        days_to_add = 2

    next_day = today.fromordinal(today.toordinal() + days_to_add)
    first_sh, first_sm = slots[0]
    next_target = datetime(next_day.year, next_day.month, next_day.day, first_sh, first_sm, 0)
    diff = (next_target - now).total_seconds()
    return f"{next_day.strftime('%Y-%m-%d')} {first_sh:02d}:{first_sm:02d}", diff


# ==============================================================================
# 2. 实时行情抓取与 K线 实时校准
# ==============================================================================

def fetch_realtime_snapshot_quotes(stock_codes: list[str]) -> dict[str, dict[str, Any]]:
    """批量高速抓取股票实时快照行情 (最新现价, 开高低收, 涨跌幅, 成交量, 成交额)。"""
    if not stock_codes:
        return {}

    def _pfx(c: str) -> str:
        c = str(c).strip()
        p = "sh" if (c.startswith("6") or c.startswith("9")) else ("bj" if (c.startswith("8") or c.startswith("4")) else "sz")
        return f"{p}{c}"

    q_codes = [_pfx(c) for c in stock_codes]
    chunk_size = 70
    chunks = [q_codes[i:i + chunk_size] for i in range(0, len(q_codes), chunk_size)]
    res: dict[str, dict[str, Any]] = {}

    def _fetch_chunk(chk: list[str]) -> dict[str, dict[str, Any]]:
        sub_res: dict[str, dict[str, Any]] = {}
        url = "https://qt.gtimg.cn/q=" + ",".join(chk)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=4.0) as resp:
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
                        sub_res[code] = {
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
        return sub_res

    if len(chunks) <= 1:
        for chk in chunks:
            res.update(_fetch_chunk(chk))
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(12, len(chunks))) as executor:
            futures = [executor.submit(_fetch_chunk, chk) for chk in chunks]
            for f in concurrent.futures.as_completed(futures):
                try:
                    res.update(f.result())
                except Exception:
                    pass

    return res


def ensure_realtime_kline(
    df: pd.DataFrame,
    realtime_quote: dict[str, Any] | None = None,
    period: str = "DAY",
    now: datetime | None = None,
) -> pd.DataFrame:
    """
    确保 K 线末端数据与最新实时行情快照严格同步：
    - 盘中交易时段将末端 Bar 校准为实时最新现价与量能，杜绝盘中判断延迟；
    - 盘后或非交易时段保持历史收盘数据原样。
    """
    if df is None or df.empty or not realtime_quote or not realtime_quote.get("price"):
        return df

    if now is None:
        now = datetime.now()

    # 仅在盘中交易时间进行实时合成校准
    if not is_in_trading_hours(now):
        return df

    quote_time = str(realtime_quote.get("time", "")).strip().replace("-", "").replace(":", "").replace(" ", "")
    today_str = now.strftime("%Y%m%d")
    if len(quote_time) >= 8 and quote_time[:8] != today_str:
        return df

    cur_price = float(realtime_quote["price"])
    q_high = float(realtime_quote.get("high", cur_price))
    q_low = float(realtime_quote.get("low", cur_price))
    q_vol = int(realtime_quote.get("volume", 0))
    q_amt = float(realtime_quote.get("amount", 0.0))

    df = df.copy()
    last_idx = df.index[-1]
    last_dt_str = str(df.loc[last_idx, "datetime"]).strip()
    today_dash = now.strftime("%Y-%m-%d")

    if period.upper() in ("DAY", "D"):
        if last_dt_str.startswith(today_dash):
            # 当日 Bar 已经存在，更新其最高/最低/收盘/成交
            df.loc[last_idx, "close"] = cur_price
            df.loc[last_idx, "high"] = max(df.loc[last_idx, "high"], cur_price, q_high)
            df.loc[last_idx, "low"] = min(df.loc[last_idx, "low"], cur_price, q_low)
            if q_vol > 0:
                df.loc[last_idx, "volume"] = q_vol
            if q_amt > 0:
                df.loc[last_idx, "amount"] = q_amt
        elif last_dt_str < today_dash:
            # 盘中数据源尚未生成今日 Bar，追加今日实时 Bar
            new_row = {
                "datetime": today_dash,
                "open": float(realtime_quote.get("open", cur_price)),
                "high": max(cur_price, q_high),
                "low": min(cur_price, q_low),
                "close": cur_price,
                "volume": q_vol,
                "amount": q_amt,
            }
            df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)

    return df


# ==============================================================================
# 3. 均线四边形策略量化检测
# ==============================================================================

def check_single_stock_quadrilateral(
    item: dict[str, str],
    period: str = "DAY",
    lookback_bars: int = 1,
    window: int = 10,
    pullback_window: int = 12,
    count: int = 220,
    realtime_quote: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """
    检查单只股票在指定周期下的均线四边形信号状态。
    返回值包含：
      - status: 'BUY' (买点触发), 'CLOSURE' (四边形刚闭合待确认), 'SELL' (均线破位死叉/止损)
      - buy_type: 具体买点细分类型
      - regularity: 规则度打分
      - bottom_price: 起爆底价
    """
    code = item.get("code", "").strip()
    if not code:
        return None
    code = code.zfill(6)
    name = item.get("name", "").strip()
    if not name or name == code:
        name = get_stock_name(code) or code

    try:
        df = fetch_security_kline(code, period=period, count=count, force_refresh=True)
        if df is None or len(df) < 40:
            return None

        # 实时注入盘中行情
        df = ensure_realtime_kline(df, realtime_quote, period=period)

        # 实例化均线四边形策略
        strategy = get_strategy(
            "ma_quadrilateral",
            window=window,
            pullback_window=pullback_window,
            require_ma30_support=True,
            require_indicator_resonance=True,
            no_candle_in_quad=True,
        )

        sig_df = strategy.generate_signals(df)
        if sig_df is None or sig_df.empty:
            return None

        n = len(sig_df)
        last_bar = sig_df.iloc[-1]
        cur_c = float(last_bar["close"])
        prev_bar = sig_df.iloc[-2] if n >= 2 else last_bar
        pre_c = float(prev_bar["close"])

        # 涨跌幅优先取实时快照
        if realtime_quote and "change_pct" in realtime_quote and realtime_quote["change_pct"] is not None:
            chg_pct = float(realtime_quote["change_pct"])
        else:
            chg_pct = round((cur_c - pre_c) / max(0.001, pre_c) * 100, 2)

        # 检查最近 lookback_bars 范围内的信号
        search_start = max(0, n - max(1, lookback_bars))
        recent_bars = sig_df.iloc[search_start:]

        # 1. 查找是否命中买入信号 (buy_signal)
        hit_buy = False
        buy_info: dict[str, Any] = {}
        for idx in range(len(recent_bars) - 1, -1, -1):
            r = recent_bars.iloc[idx]
            if bool(r.get("buy_signal", False)):
                hit_buy = True
                days_ago = len(recent_bars) - 1 - idx
                buy_info = {
                    "days_ago": days_ago,
                    "buy_type": str(r.get("quad_buy_type", "闭合买点")),
                    "regularity": float(r.get("quad_regularity", 0.0)),
                    "bottom_price": float(r.get("quad_bottom_price", 0.0)),
                    "trigger_time": str(r.get("datetime", "")),
                    "trigger_price": float(r.get("close", cur_c)),
                }
                break

        # 2. 检查末端是否发生均线破位卖出 (sell_signal)
        hit_sell = bool(last_bar.get("sell_signal", False))

        # 3. 检查末端是否处于刚闭合待确认阶段 (xg 为 True 但尚未形成二次买点)
        hit_closure = bool(last_bar.get("xg", False)) and not hit_buy

        if not (hit_buy or hit_sell or hit_closure):
            return None

        signal_status = "BUY" if hit_buy else ("SELL" if hit_sell else "CLOSURE")

        return {
            "code": code,
            "name": name,
            "period": period,
            "status": signal_status,
            "close": cur_c,
            "chg_pct": chg_pct,
            "volume": int(last_bar.get("volume", 0)),
            "amount": float(last_bar.get("amount", 0.0)),
            "bar_time": str(last_bar.get("datetime", "")),
            "buy_info": buy_info if hit_buy else {},
            "ma5": float(last_bar.get("ma5", 0.0)),
            "ma10": float(last_bar.get("ma10", 0.0)),
            "ma20": float(last_bar.get("ma20", 0.0)),
            "ma30": float(last_bar.get("ma30", 0.0)),
            "sig_df": sig_df,
        }
    except Exception as e:
        logger.debug(f"检查 {code} ({name}) 均线四边形出错: {e}")
        return None


def scan_watchlist_quadrilateral(
    stocks: list[dict[str, str]] | None = None,
    period: str = "DAY",
    lookback_bars: int = 1,
    window: int = 10,
    pullback_window: int = 12,
    min_score: float = 0.0,
    max_workers: int = 2,
) -> dict[str, list[dict[str, Any]]]:
    """扫描指定股票池的均线四边形策略状态。"""
    if stocks is None:
        stocks = load_watchlist_items()
    if not stocks:
        logger.warning("未检测到有效股票池（watchlist.json 为空或未指定）")
        return {"buy_signals": [], "closure_signals": [], "sell_signals": []}

    total_stocks = len(stocks)
    logger.info(
        f"开始扫描均线四边形策略... 标的总数: {total_stocks}, 周期: {period}, 回溯窗口: {lookback_bars}根K线, 线程数: {max_workers}"
    )
    t0 = time.time()

    codes = [item["code"] for item in stocks if item.get("code")]
    quotes_map = fetch_realtime_snapshot_quotes(codes)

    buy_signals: list[dict[str, Any]] = []
    closure_signals: list[dict[str, Any]] = []
    sell_signals: list[dict[str, Any]] = []

    def _process_result(res: dict[str, Any] | None):
        if not res:
            return
        if res["status"] == "BUY":
            reg = res.get("buy_info", {}).get("regularity", 0.0)
            if min_score <= 0.0 or reg >= min_score:
                buy_signals.append(res)
        elif res["status"] == "CLOSURE":
            closure_signals.append(res)
        elif res["status"] == "SELL":
            sell_signals.append(res)

    if max_workers <= 1:
        for idx, item in enumerate(stocks, 1):
            res = check_single_stock_quadrilateral(
                item=item,
                period=period,
                lookback_bars=lookback_bars,
                window=window,
                pullback_window=pullback_window,
                count=160,
                realtime_quote=quotes_map.get(item.get("code", "")),
            )
            _process_result(res)
            if total_stocks >= 100 and (idx % 100 == 0 or idx == total_stocks):
                cost = time.time() - t0
                logger.info(
                    f"扫描进度: {idx}/{total_stocks} ({idx/total_stocks*100:.1f}%) | "
                    f"买点: {len(buy_signals)} 只 | 闭合: {len(closure_signals)} 只 | 耗时: {cost:.1f}s"
                )
    else:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_stock = {
                executor.submit(
                    check_single_stock_quadrilateral,
                    item,
                    period,
                    lookback_bars,
                    window,
                    pullback_window,
                    160,
                    quotes_map.get(item.get("code", "")),
                ): item
                for item in stocks
            }
            completed = 0
            # 报告步长：全市场时每 250 只或 5% 报告一次
            step = 250 if total_stocks >= 1000 else (50 if total_stocks >= 100 else 999999)
            for future in concurrent.futures.as_completed(future_to_stock):
                completed += 1
                try:
                    res = future.result()
                    _process_result(res)
                except Exception as e:
                    logger.debug(f"分析股票异常: {e}")

                if total_stocks >= 100 and (completed % step == 0 or completed == total_stocks):
                    cost = time.time() - t0
                    speed = completed / max(0.1, cost)
                    logger.info(
                        f"扫描进度: {completed}/{total_stocks} ({completed/total_stocks*100:.1f}%) | "
                        f"已发现买点: {len(buy_signals)} 只 | 刚闭合: {len(closure_signals)} 只 | 速度: {speed:.1f}只/秒"
                    )

    # 排序：买点优先按触发就近(days_ago 越小越优先)，其次按规则度打分，再按今日涨幅
    buy_signals.sort(
        key=lambda x: (
            x["buy_info"].get("days_ago", 999),
            -x["buy_info"].get("regularity", 0.0),
            -x["chg_pct"],
        )
    )
    closure_signals.sort(key=lambda x: -x["chg_pct"])
    sell_signals.sort(key=lambda x: x["chg_pct"])

    cost = time.time() - t0
    logger.info(
        f"均线四边形扫描完毕，耗时: {cost:.2f}秒 | 🔴 买入预警: {len(buy_signals)} 只 | "
        f"🟡 刚闭合待确认: {len(closure_signals)} 只 | 🟢 破位卖出: {len(sell_signals)} 只"
    )

    return {
        "buy_signals": buy_signals,
        "closure_signals": closure_signals,
        "sell_signals": sell_signals,
    }


# ==============================================================================
# 4. 高清暗黑风 K线快照与四边形色带绘制
# ==============================================================================

_MATPLOTLIB_FONT_CONFIGURED = False


def _configure_matplotlib_chinese_fonts():
    """配置 matplotlib 中文字体以兼容 macOS、Windows、Linux。"""
    global _MATPLOTLIB_FONT_CONFIGURED
    if _MATPLOTLIB_FONT_CONFIGURED:
        return

    import matplotlib.pyplot as plt
    from matplotlib import font_manager

    candidates = [
        "Microsoft YaHei",      # Windows 微软雅黑
        "SimHei",               # Windows 黑体
        "PingFang SC",          # macOS 苹方
        "Hiragino Sans GB",     # macOS 冬青黑体
        "Noto Sans CJK SC",     # Linux 思源黑体
        "SimSun",               # Windows 宋体
        "WenQuanYi Micro Hei",  # Linux 文泉驿微米黑
    ]

    installed = {f.name for f in font_manager.fontManager.ttflist}
    available = [f for f in candidates if f in installed]

    if available:
        plt.rcParams["font.sans-serif"] = available + ["sans-serif"]
    else:
        plt.rcParams["font.sans-serif"] = candidates + ["sans-serif"]

    plt.rcParams["axes.unicode_minus"] = False
    _MATPLOTLIB_FONT_CONFIGURED = True


def generate_quadrilateral_snapshot(
    code: str,
    name: str,
    sig_df: pd.DataFrame,
    buy_type: str = "闭合买点",
    regularity: float = 85.0,
    bottom_price: float = 0.0,
    change_pct: float = 0.0,
    period: str = "DAY",
    n_bars: int = 55,
) -> bytes:
    """生成专业的均线四边形及 DRAWBAND 色带形态快照图片字节流 (PNG)。"""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.patches as patches
        import matplotlib.pyplot as plt
    except ImportError:
        logger.warning("未安装 matplotlib，跳过 K 线快照生成。")
        return b""

    try:
        df_plot = sig_df.tail(n_bars).reset_index(drop=True)
        if len(df_plot) < 10:
            return b""

        _configure_matplotlib_chinese_fonts()

        last_idx = len(df_plot) - 1
        last_row = df_plot.iloc[last_idx]
        last_c = float(last_row["close"])

        fig, (ax1, ax2) = plt.subplots(
            2, 1,
            figsize=(10.2, 6.2),
            gridspec_kw={"height_ratios": [3.8, 1.0]},
            facecolor="#18191d"
        )
        ax1.set_facecolor("#18191d")
        ax2.set_facecolor("#18191d")

        ax1.grid(True, linestyle="--", alpha=0.15, color="#ffffff")
        ax2.grid(True, linestyle="--", alpha=0.15, color="#ffffff")

        # 1. 绘制蜡烛图
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

        # 2. 均线与 DRAWBAND 色带
        x_axis = np.arange(len(df_plot))
        ma5 = df_plot["ma5"].values.astype(float) if "ma5" in df_plot else df_plot["close"].rolling(5).mean().values
        ma10 = df_plot["ma10"].values.astype(float) if "ma10" in df_plot else df_plot["close"].rolling(10).mean().values
        ma20 = df_plot["ma20"].values.astype(float) if "ma20" in df_plot else df_plot["close"].rolling(20).mean().values
        ma30 = df_plot["ma30"].values.astype(float) if "ma30" in df_plot else df_plot["close"].rolling(30).mean().values

        ax1.plot(x_axis, ma5, color="#ffd700", label="MA5 (黄)", linewidth=1.3, alpha=0.9, zorder=4)
        ax1.plot(x_axis, ma10, color="#00e5ff", label="MA10 (青)", linewidth=1.3, alpha=0.9, zorder=4)
        ax1.plot(x_axis, ma20, color="#ff4081", label="MA20 (洋红)", linewidth=1.4, alpha=0.95, zorder=4)
        ax1.plot(x_axis, ma30, color="#69f0ae", label="MA30 (翠绿)", linewidth=1.6, alpha=0.95, zorder=4)

        # 绘制通达信色带模拟 (5-10 均线带 与 20-30 均线带)
        ax1.fill_between(x_axis, ma5, ma10, where=(ma5 >= ma10), color="#ff5252", alpha=0.18, zorder=1)
        ax1.fill_between(x_axis, ma20, ma30, where=(ma20 >= ma30), color="#69f0ae", alpha=0.15, zorder=1)

        # 3. 标记底价锚线 (如果有效)
        if bottom_price > 0:
            ax1.axhline(bottom_price, color="#ffab00", linestyle=":", linewidth=1.1, alpha=0.75, zorder=3)
            ax1.text(
                0.5, bottom_price, f" 底价锚: ¥{bottom_price:.2f}",
                color="#ffab00", fontsize=8.2, va="bottom", alpha=0.85
            )

        # 4. 标注买入信号点与卖出离场点
        price_span = df_plot["high"].max() - df_plot["low"].min()
        offset = max(price_span * 0.08, 0.25)

        for i, row in df_plot.iterrows():
            c_val = float(row["close"])
            l_val = float(row["low"])
            h_val = float(row["high"])
            is_latest = (i == last_idx)

            if bool(row.get("buy_signal", False)):
                b_type = str(row.get("quad_buy_type", buy_type))
                score = float(row.get("quad_regularity", regularity))
                score_str = f" ({score:.0f}分)" if score > 0 else ""
                tag = f"▲ 【{b_type}】\n¥{c_val:.2f}{score_str}"
                ax1.annotate(
                    tag,
                    xy=(i, l_val),
                    xytext=(i, l_val - offset),
                    arrowprops=dict(facecolor="#f23645", edgecolor="#ffffff", shrink=0.08, width=1.5, headwidth=5),
                    ha="center", va="top", fontsize=8.8 if is_latest else 7.8, fontweight="bold", color="#ffffff",
                    bbox=dict(
                        boxstyle="round,pad=0.32",
                        facecolor="#f23645",
                        edgecolor="#ffffff" if is_latest else "none",
                        alpha=0.95 if is_latest else 0.85
                    ),
                    zorder=7 if is_latest else 6
                )
            elif bool(row.get("sell_signal", False)):
                tag = f"▼ 破位/止损\n¥{c_val:.2f}"
                ax1.annotate(
                    tag,
                    xy=(i, h_val),
                    xytext=(i, h_val + offset),
                    arrowprops=dict(facecolor="#089981", edgecolor="#ffffff", shrink=0.08, width=1.5, headwidth=5),
                    ha="center", va="bottom", fontsize=8.8 if is_latest else 7.8, fontweight="bold", color="#ffffff",
                    bbox=dict(
                        boxstyle="round,pad=0.32",
                        facecolor="#089981",
                        edgecolor="#ffffff" if is_latest else "none",
                        alpha=0.95 if is_latest else 0.85
                    ),
                    zorder=7 if is_latest else 6
                )

        ax1.set_ylim(bottom=df_plot["low"].min() - offset * 1.8, top=df_plot["high"].max() + offset * 1.8)

        # 5. 标题与状态栏
        period_name = "日线" if period.upper() in ("DAY", "D") else ("周线" if period.upper() in ("WEEK", "W") else f"{period}分时")
        chg_color = "#f23645" if change_pct >= 0 else "#089981"
        bar_dt = str(last_row.get("datetime", ""))
        title_str = f"{code} {name} · {period_name} K线 [ 均线四边形·擒牛战法 ]"
        status_str = (
            f"最新价: ¥{last_c:.2f} ({change_pct:+.2f}%)   买点形态: 【{buy_type}】   "
            f"规则度: {regularity:.0f}分   底价防守: ¥{bottom_price:.2f}   时间: {bar_dt}"
        )

        fig.suptitle(title_str, fontsize=13, fontweight="bold", color="#ffffff", x=0.10, y=0.97, ha="left")
        ax1.set_title(status_str, fontsize=9.2, color=chg_color, loc="left", pad=6)

        # 6. 成交量副图
        for i, row in df_plot.iterrows():
            c = float(row["close"])
            o = float(row["open"])
            v = float(row.get("volume", 0))
            color = "#f23645" if c >= o else "#089981"
            ax2.bar(i, v, color=color, width=0.7, alpha=0.85)

        # 7. X轴与样式细节
        n = len(df_plot)
        step = max(1, n // 6)
        xticks = list(range(0, n, step))
        if (n - 1) not in xticks:
            xticks.append(n - 1)

        def _fmt_x(dt_str: str) -> str:
            s = str(dt_str).strip()
            return s[5:10] if len(s) >= 10 else s

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

        ax1.legend(loc="upper left", facecolor="#212226", edgecolor="none", fontsize=8, labelcolor="#d0d0d0")
        plt.tight_layout(rect=[0, 0, 1, 0.95])

        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=130, facecolor=fig.get_facecolor(), edgecolor="none")
        plt.close(fig)

        img_bytes = buf.getvalue()

        # 自动归档至 data/snapshots/
        try:
            snapshot_dir = PROJECT_ROOT / "data" / "snapshots"
            snapshot_dir.mkdir(parents=True, exist_ok=True)
            clean_time = bar_dt.replace("-", "").replace(":", "").replace(" ", "_")
            img_path = snapshot_dir / f"{code}_QUAD_{clean_time}.png"
            img_path.write_bytes(img_bytes)
            logger.info(f"已生成 {code} {name} 四边形走势快照: {img_path.relative_to(PROJECT_ROOT)}")
        except Exception as e:
            logger.debug(f"保存快照图片到本地出错: {e}")

        return img_bytes
    except Exception as exc:
        logger.error(f"生成 {code} {name} 四边形快照失败: {exc}")
        return b""


# ==============================================================================
# 5. 微信通知推送客户端 (多通道支持)
# ==============================================================================

class WeChatNotifier:
    """统一微信通知推送客户端 (支持企业微信机器人 Webhook、PushPlus、Server酱、WxPusher)。"""

    def __init__(
        self,
        wecom_webhook: str | None = None,
        pushplus_token: str | None = None,
        serverchan_key: str | None = None,
        wxpusher_app_token: str | None = None,
        wxpusher_uids: list[str] | None = None,
    ):
        self.wecom_webhook = wecom_webhook or os.environ.get("WECHAT_WEBHOOK_URL", "")
        self.pushplus_token = pushplus_token or os.environ.get("PUSHPLUS_TOKEN", "")
        self.serverchan_key = serverchan_key or os.environ.get("SERVERCHAN_KEY", "")
        self.wxpusher_app_token = wxpusher_app_token or os.environ.get("WXPUSHER_APP_TOKEN", "")
        self.wxpusher_uids = wxpusher_uids or (
            [u.strip() for u in os.environ.get("WXPUSHER_UIDS", "").split(",") if u.strip()]
        )
        self._wecom_sent_count = 0

    def is_configured(self) -> bool:
        """检查是否有任何一个推送通道配置有效。"""
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

    def _send_wecom_with_rate_limit(self, payload: dict) -> dict:
        """带频率限制保护 (20条/分) 的企业微信消息推送方法。

        每成功发送 20 条消息，自动等待 60 秒后再继续发送。
        若触发 45009 频控限制，自动等待 60 秒后重试。
        """
        if self._wecom_sent_count > 0 and self._wecom_sent_count % 20 == 0:
            logger.info(
                f"已累计向企业微信发送 {self._wecom_sent_count} 条消息，达到 20条/分 频率限制，等待 60 秒后继续发送..."
            )
            time.sleep(60)

        res_data = {}
        for attempt in range(2):
            res_data = self._post_json(self.wecom_webhook, payload)
            if res_data.get("errcode") == 45009:
                logger.warning(
                    f"触发企业微信机器人发送频率限制 (20条/分)，等待 60 秒后进行第 {attempt + 1} 次重试..."
                )
                time.sleep(60)
                continue
            break

        if res_data.get("errcode") == 0:
            self._wecom_sent_count += 1

        return res_data

    @staticmethod
    def _split_markdown_chunks(content: str, max_bytes: int = 3800) -> list[str]:
        """将超长 Markdown 按行安全切分为符合微信限制 (<=4096字节) 的多个块。"""
        lines = content.split("\n")
        chunks: list[str] = []
        cur_lines: list[str] = []
        cur_bytes = 0
        for line in lines:
            line_bytes = len((line + "\n").encode("utf-8"))
            if cur_bytes + line_bytes > max_bytes and cur_lines:
                chunks.append("\n".join(cur_lines))
                cur_lines = [line]
                cur_bytes = line_bytes
            else:
                cur_lines.append(line)
                cur_bytes += line_bytes
        if cur_lines:
            chunks.append("\n".join(cur_lines))
        return chunks

    def send_notification(self, title: str, markdown_content: str) -> bool:
        """多通道推送微信 Markdown 预警通知（支持超长内容自动分段推送）。"""
        success = False

        # 1. 企业微信机器人 Webhook (严格限制 4096 字节，超长自动分段推送)
        if self.wecom_webhook:
            try:
                full_content = f"### {title}\n\n{markdown_content}"
                if len(full_content.encode("utf-8")) <= 3900:
                    chunks = [full_content]
                else:
                    chunks = self._split_markdown_chunks(markdown_content, max_bytes=3500)
                    # 为每个分段补充标题前缀
                    chunks = [
                        f"### {title} ({idx+1}/{len(chunks)})\n\n{c}"
                        for idx, c in enumerate(chunks)
                    ]

                for idx, chunk in enumerate(chunks, 1):
                    payload = {
                        "msgtype": "markdown",
                        "markdown": {
                            "content": chunk
                        }
                    }
                    res_data = self._send_wecom_with_rate_limit(payload)
                    if res_data.get("errcode") == 0:
                        part_info = f" [分段 {idx}/{len(chunks)}]" if len(chunks) > 1 else ""
                        logger.info(f"企业微信机器人通知发送成功！{part_info}")
                        success = True
                    else:
                        logger.error(f"企业微信机器人发送失败: {res_data}")
            except Exception as e:
                logger.error(f"企业微信机器人请求异常: {e}")

        # 2. PushPlus (推送加)
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

        # 3. Server酱
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
                    "contentType": 3,
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
        if not image_bytes or not self.wecom_webhook:
            return False

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
            res_data = self._send_wecom_with_rate_limit(payload)
            if res_data.get("errcode") == 0:
                logger.info("企业微信机器人 K线快照图片 发送成功！")
                return True
            else:
                logger.error(f"企业微信机器人图片发送失败: {res_data}")
        except Exception as e:
            logger.error(f"企业微信机器人发送图片异常: {e}")

        return False


def export_results_to_csv(
    scan_results: dict[str, list[dict[str, Any]]],
    output_path: Path | str,
) -> str:
    """导出扫描结果至 CSV 文件（支持 Excel 中文无乱码 utf-8-sig）。"""
    rows = []
    for item in scan_results.get("buy_signals", []):
        b_info = item.get("buy_info", {})
        rows.append({
            "代码": item["code"],
            "名称": item["name"],
            "状态": "买入信号",
            "买点类型": b_info.get("buy_type", ""),
            "规则度评分": b_info.get("regularity", 0.0),
            "底价锚定": b_info.get("bottom_price", 0.0),
            "距触发周期数": b_info.get("days_ago", 0),
            "最新价": item["close"],
            "涨跌幅(%)": item["chg_pct"],
            "成交额(亿)": round(item["amount"] / 1e8, 2) if item.get("amount") else 0.0,
            "触发时间": b_info.get("trigger_time", item["bar_time"]),
            "最新Bar时间": item["bar_time"],
        })
    for item in scan_results.get("closure_signals", []):
        rows.append({
            "代码": item["code"],
            "名称": item["name"],
            "状态": "刚闭合待确认",
            "买点类型": "闭合蓄势",
            "规则度评分": 0.0,
            "底价锚定": 0.0,
            "距触发周期数": 0,
            "最新价": item["close"],
            "涨跌幅(%)": item["chg_pct"],
            "成交额(亿)": round(item["amount"] / 1e8, 2) if item.get("amount") else 0.0,
            "触发时间": item["bar_time"],
            "最新Bar时间": item["bar_time"],
        })
    for item in scan_results.get("sell_signals", []):
        rows.append({
            "代码": item["code"],
            "名称": item["name"],
            "状态": "破位卖出/止损",
            "买点类型": "破位离场",
            "规则度评分": 0.0,
            "底价锚定": 0.0,
            "距触发周期数": 0,
            "最新价": item["close"],
            "涨跌幅(%)": item["chg_pct"],
            "成交额(亿)": round(item["amount"] / 1e8, 2) if item.get("amount") else 0.0,
            "触发时间": item["bar_time"],
            "最新Bar时间": item["bar_time"],
        })
    df_out = pd.DataFrame(rows)
    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    df_out.to_csv(out_p, index=False, encoding="utf-8-sig")
    logger.info(f"已导出全部 {len(rows)} 条扫描记录至: {out_p}")
    return str(out_p)


def format_quadrilateral_message(
    scan_results: dict[str, list[dict[str, Any]]],
    period: str,
    slot_desc: str,
    pool_name: str = "自选池",
    max_buy_display: int = 10,
    max_closure_display: int = 4,
    max_sell_display: int = 4,
    output_path: str | None = None,
) -> tuple[str, str]:
    """格式化均线四边形 Markdown 预警通知（带字节预算守卫，杜绝微信 4096 字节超长报错）。"""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    buy_list = scan_results.get("buy_signals", [])
    closure_list = scan_results.get("closure_signals", [])
    sell_list = scan_results.get("sell_signals", [])

    p_desc = "日线" if period.upper() in ("DAY", "D") else ("周线" if period.upper() in ("WEEK", "W") else f"{period}分时")
    title = f"🔔 {pool_name} 均线四边形预警 [{slot_desc}]"
    file_note = f" (完整清单详见 `{Path(output_path).name}`)" if output_path else " (完整清单已导出至本地文件)"

    md_lines = [
        f"> **触发时间**: `{now_str}`",
        f"> **监控周期**: `{p_desc} K线` (MA5/10/20/30 擒牛战法)",
        f"> **最新预警**: 🔴 四边形买点 `{len(buy_list)}` 只 | 🟡 刚闭合待确认 `{len(closure_list)}` 只 | 🟢 破位减仓 `{len(sell_list)}` 只",
        "",
    ]

    # 1. 精选买点部分（严格字节预算控制在 3200 字节以内）
    if buy_list:
        md_lines.append(f"### 🔴 均线四边形精选买点 (展示前 {min(len(buy_list), max_buy_display)} 只)")
        displayed_buys = 0
        for item in buy_list:
            if displayed_buys >= max_buy_display:
                break
            b_info = item.get("buy_info", {})
            b_type = b_info.get("buy_type", "闭合加速")
            score = b_info.get("regularity", 0.0)
            bot_price = b_info.get("bottom_price", 0.0)
            days_ago = b_info.get("days_ago", 0)
            amt_yi = round(item["amount"] / 1e8, 2) if item.get("amount") else 0
            chg_sign = "+" if item["chg_pct"] >= 0 else ""
            timing_desc = "今日最新触发" if days_ago == 0 else f"{days_ago}日前触发"

            line = (
                f"- **{item['code']} {item['name']}** : 【`{b_type}`】最新价 `¥{item['close']:.2f}` ({chg_sign}{item['chg_pct']}%) | "
                f"规则度 `{score:.0f}分` | 底价锚 `¥{bot_price:.2f}` | 成交 `{amt_yi}亿` | `{timing_desc}`"
            )
            # 字节预算守卫：单条消息不超过 3200 字节
            cur_bytes = len("\n".join(md_lines + [line]).encode("utf-8"))
            if cur_bytes > 3200:
                break
            md_lines.append(line)
            displayed_buys += 1

        if len(buy_list) > displayed_buys:
            md_lines.append(f"- *... 等共计 {len(buy_list)} 只标的命中买点{file_note}*")
        md_lines.append("")

    # 2. 闭合待确认部分
    if closure_list:
        md_lines.append("### 🟡 四边形闭合蓄势 (观察回踩与起爆)")
        displayed_clos = 0
        for item in closure_list:
            if displayed_clos >= max_closure_display:
                break
            chg_sign = "+" if item["chg_pct"] >= 0 else ""
            line = f"- **{item['code']} {item['name']}** : 最新价 `¥{item['close']:.2f}` ({chg_sign}{item['chg_pct']}%) | 时间 `{item['bar_time']}`"
            cur_bytes = len("\n".join(md_lines + [line]).encode("utf-8"))
            if cur_bytes > 3400:
                break
            md_lines.append(line)
            displayed_clos += 1

        if len(closure_list) > displayed_clos:
            md_lines.append(f"- *... 等其余 {len(closure_list) - displayed_clos} 只标的处于闭合观察期*")
        md_lines.append("")

    # 3. 破位卖出/止损部分
    if sell_list:
        md_lines.append("### 🟢 破位风险提示 (MA20失守或止损离场)")
        displayed_sells = 0
        for item in sell_list:
            if displayed_sells >= max_sell_display:
                break
            chg_sign = "+" if item["chg_pct"] >= 0 else ""
            line = f"- **{item['code']} {item['name']}** : 最新价 `¥{item['close']:.2f}` ({chg_sign}{item['chg_pct']}%) | 时间 `{item['bar_time']}`"
            cur_bytes = len("\n".join(md_lines + [line]).encode("utf-8"))
            if cur_bytes > 3600:
                break
            md_lines.append(line)
            displayed_sells += 1

        if len(sell_list) > displayed_sells:
            md_lines.append(f"- *... 等其余 {len(sell_list) - displayed_sells} 只标的已破位*")
        md_lines.append("")

    if not buy_list and not closure_list and not sell_list:
        md_lines.append(f"{pool_name}各标的当前未出现均线四边形触发信号。")

    md_lines.append("---")
    md_lines.append("*easy_tdx 原生量化投研引擎 · 均线四边形擒牛战法*")

    return title, "\n".join(md_lines)


# ==============================================================================
# 6. 主流程与常驻调度器
# ==============================================================================

def run_single_scan_and_notify(
    notifier: WeChatNotifier,
    stocks: list[dict[str, str]] | None = None,
    period: str = "DAY",
    lookback: int = 1,
    slot_desc: str = "即时扫描",
    pool_name: str = "自选池",
    notify_if_empty: bool = False,
    generate_images: bool = True,
    max_images: int = 50,
    workers: int = 2,
    min_score: float = 0.0,
    output_path: str | None = None,
) -> int:
    """执行一次均线四边形扫描，并在控制台展示与发送微信预警。"""
    res = scan_watchlist_quadrilateral(
        stocks=stocks,
        period=period,
        lookback_bars=lookback,
        min_score=min_score,
        max_workers=workers,
    )

    buy_list = res.get("buy_signals", [])
    closure_list = res.get("closure_signals", [])
    sell_list = res.get("sell_signals", [])
    total_signals = len(buy_list) + len(closure_list) + len(sell_list)

    # 导出 CSV 记录
    if output_path:
        export_results_to_csv(res, output_path)

    title, content = format_quadrilateral_message(
        res, period, slot_desc, pool_name=pool_name, output_path=output_path
    )

    # 控制台打印
    print("\n" + "=" * 76)
    print(f"【{title}】")
    print("-" * 76)
    print(content)
    print("=" * 76 + "\n")

    if total_signals > 0 or notify_if_empty:
        if notifier.is_configured():
            notifier.send_notification(title, content)
            if generate_images and buy_list:
                img_targets = buy_list[:max_images]
                logger.info(f"正在生成并推送前 {len(img_targets)} 只标的的 K 线形态快照图片...")
                for idx, sig in enumerate(img_targets, 1):
                    sig_df = sig.get("sig_df")
                    if sig_df is not None and not sig_df.empty:
                        b_info = sig.get("buy_info", {})
                        img_bytes = generate_quadrilateral_snapshot(
                            code=sig["code"],
                            name=sig["name"],
                            sig_df=sig_df,
                            buy_type=b_info.get("buy_type", "闭合加速"),
                            regularity=b_info.get("regularity", 80.0),
                            bottom_price=b_info.get("bottom_price", 0.0),
                            change_pct=sig.get("chg_pct", 0.0),
                            period=period,
                        )
                        if img_bytes:
                            sent = notifier.send_image(img_bytes)
                            if sent:
                                logger.info(f"[{idx}/{len(img_targets)}] {sig['code']} {sig['name']} 快照已推送")
                            # 发送间隔保护，防止高频触发微信频控
                            time.sleep(0.3)
        else:
            logger.warning(
                "检测到均线四边形信号，但尚未配置微信通知通道（企业微信 Webhook / PushPlus / Server酱）。"
            )
            logger.info("提示: 启动时可通过 --webhook 传入企业微信 Webhook 链接。")
            if generate_images and buy_list:
                img_targets = buy_list[:max_images]
                logger.info(f"正在本地生成前 {len(img_targets)} 只标的的 K 线形态快照图片...")
                for idx, sig in enumerate(img_targets, 1):
                    sig_df = sig.get("sig_df")
                    if sig_df is not None and not sig_df.empty:
                        b_info = sig.get("buy_info", {})
                        generate_quadrilateral_snapshot(
                            code=sig["code"],
                            name=sig["name"],
                            sig_df=sig_df,
                            buy_type=b_info.get("buy_type", "闭合加速"),
                            regularity=b_info.get("regularity", 80.0),
                            bottom_price=b_info.get("bottom_price", 0.0),
                            change_pct=sig.get("chg_pct", 0.0),
                            period=period,
                        )
    else:
        logger.info(f"当前{pool_name}无最新均线四边形买点/卖出标的，跳过微信推送。")

    return total_signals


def run_daemon_loop(
    notifier: WeChatNotifier,
    stocks: list[dict[str, str]] | None = None,
    period: str = "DAY",
    lookback: int = 1,
    force_trading_day_check: bool = True,
    generate_images: bool = True,
    max_images: int = 50,
    workers: int = 2,
    pool_name: str = "自选池",
    min_score: float = 0.0,
    output_path: str | None = None,
) -> None:
    """后台常驻监控服务，在交易日设定的关键时段自动触发扫描。"""
    is_intraday = period.upper() in ("30M", "60M")
    slots = INTRADAY_CHECK_SLOTS if is_intraday else DAY_CHECK_SLOTS

    logger.info("=" * 76)
    logger.info(f"easy_tdx {pool_name} 均线四边形策略 微信推送后台守护服务已启动！")
    logger.info(f"监控周期: {period} K线 | 回溯: {lookback}根K线 | 并发线程: {workers}")
    slot_strs = [f"{h:02d}:{m:02d}" for h, m in slots]
    logger.info(f"监控触发时点: {', '.join(slot_strs)}")
    logger.info(f"微信通知配置: {'已就绪' if notifier.is_configured() else '未配置 (控制台日志模式)'}")
    logger.info("=" * 76)

    last_executed_slot: str | None = None

    while True:
        try:
            now = datetime.now()
            today_str = now.strftime("%Y-%m-%d")

            # 1. 检查是否为交易日（周一至周五）
            if force_trading_day_check and not is_trading_day(now):
                next_desc, wait_sec = get_next_slot_info(now, slots)
                logger.info(f"今日为非交易日（周末/休市）。下次监控时间: {next_desc}，休眠中...")
                time.sleep(min(300, max(10, wait_sec)))
                continue

            # 2. 检查是否命中预警时点
            matched_slot = get_current_check_slot(now, slots)
            if matched_slot:
                slot_key = f"{today_str}_{matched_slot[0]:02d}:{matched_slot[1]:02d}"
                if slot_key != last_executed_slot:
                    slot_desc = f"{matched_slot[0]:02d}:{matched_slot[1]:02d}"
                    logger.info(f"⏰ 命中监控时点 [{slot_desc}]，正在触发均线四边形扫描...")
                    run_single_scan_and_notify(
                        notifier=notifier,
                        stocks=stocks,
                        period=period,
                        lookback=lookback,
                        slot_desc=slot_desc,
                        pool_name=pool_name,
                        notify_if_empty=False,
                        generate_images=generate_images,
                        max_images=max_images,
                        workers=workers,
                        min_score=min_score,
                        output_path=output_path,
                    )
                    last_executed_slot = slot_key

            time.sleep(10)

        except KeyboardInterrupt:
            logger.info("接收到退出指令，后台守护监控服务终止。")
            break
        except Exception as e:
            logger.error(f"监控主循环异常: {e}", exc_info=True)
            time.sleep(15)


def main():
    parser = argparse.ArgumentParser(
        description="easy_tdx 自选监控池 / 全市场 均线四边形策略 (擒牛战法) 监测与预警脚本"
    )
    parser.add_argument(
        "--now",
        action="store_true",
        help="立即执行一次均线四边形扫描并输出结果",
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="启动后台常驻监控守护服务（在交易日关键时段自动触发）",
    )
    parser.add_argument(
        "-a", "--all", "--all-market",
        action="store_true",
        dest="all_market",
        help="【全市场扫描】扫描全市场全部 A 股标的 (5,200+ 只)",
    )
    parser.add_argument(
        "--universe",
        type=str,
        default=None,
        choices=["all", "core", "hs300", "zz500", "zz1000"],
        help="指定股票池范围 (core: 核心龙头159只, hs300: 沪深300, zz500: 中证500, zz1000: 中证1000, all: 全市场5200+只)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="限制最大扫描标的数量 (例如 --limit 500，0为不限制)",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=0.0,
        help="最低规则度评分过滤 (例如 85.0，默认 0 为不限制)",
    )
    parser.add_argument(
        "-o", "--output",
        type=str,
        default=None,
        help="指定结果导出 CSV 文件路径 (例如 output/quad_all_market.csv)",
    )
    parser.add_argument(
        "-p", "--period",
        type=str,
        default="DAY",
        choices=["DAY", "WEEK", "60M", "30M"],
        help="K线监控周期 (默认: DAY，可选 WEEK / 60M / 30M)",
    )
    parser.add_argument(
        "--lookback",
        type=int,
        default=1,
        help="信号回溯根数 (默认: 1，即仅最新一根K线触发的买点；设为 3 或 5 可扫描近期形成标的)",
    )
    parser.add_argument(
        "-s", "--stock",
        type=str,
        default=None,
        help="指定单只或多只股票代码扫描，逗号分隔 (例如: 600592,600072,000668)",
    )
    parser.add_argument(
        "--watchlist",
        type=str,
        default=None,
        help="指定自定义自选股 JSON 文件路径 (默认自动读取 watchlist.json)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=2,
        help="并发拉取分析线程数 (默认自选池 2 线程，全市场/指数池自动提升为 8-12 线程)",
    )
    parser.add_argument(
        "--no-image",
        action="store_true",
        help="禁用 K 线快照走势图生成",
    )
    parser.add_argument(
        "--max-images",
        type=int,
        default=50,
        help="最多生成/推送的走势图快照数量 (默认: 50)",
    )

    default_webhook = os.environ.get("WECHAT_WEBHOOK_URL") or os.environ.get("WECHAT_WEBHOOK")
    default_pushplus = os.environ.get("PUSHPLUS_TOKEN")
    default_serverchan = os.environ.get("SERVERCHAN_KEY")

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
        help="PushPlus (推送加) Token (默认自动从 PUSHPLUS_TOKEN 读取)",
    )
    parser.add_argument(
        "--serverchan-key",
        type=str,
        default=default_serverchan,
        help="Server酱 SendKey (默认自动从 SERVERCHAN_KEY 读取)",
    )
    parser.add_argument(
        "--notify-empty",
        action="store_true",
        help="当无买卖信号时也推送微信通知（默认仅在有信号时推送）",
    )
    parser.add_argument(
        "--ignore-trading-day",
        action="store_true",
        help="忽略周末交易日限制（调试测试用途）",
    )

    args = parser.parse_args()

    # 1. 解析目标监控股票池与显示名称
    stocks_to_scan: list[dict[str, str]] = []
    pool_desc = "自选池"

    if args.all_market or args.universe:
        scope = "all" if args.all_market else (args.universe or "all")
        raw_codes = get_universe_symbols(scope)
        if args.limit and args.limit > 0:
            raw_codes = raw_codes[:args.limit]
        stocks_to_scan = [
            {"code": c.zfill(6), "name": get_stock_name(c.zfill(6)) or c}
            for c in raw_codes
        ]
        if scope == "all":
            pool_desc = f"全市场 A 股 ({len(stocks_to_scan)}只)"
        else:
            pool_desc = f"{scope.upper()} 指数池 ({len(stocks_to_scan)}只)"
    elif args.stock:
        raw_codes = [c.strip() for c in args.stock.split(",") if c.strip()]
        for c in raw_codes:
            clean_c = c.zfill(6)
            real_name = get_stock_name(clean_c) or clean_c
            stocks_to_scan.append({"code": clean_c, "name": real_name})
        pool_desc = f"指定股票 ({len(stocks_to_scan)}只)"
    else:
        if args.watchlist and Path(args.watchlist).is_file():
            try:
                with open(args.watchlist, encoding="utf-8") as f:
                    raw_data = json.load(f)
                    for item in raw_data:
                        if isinstance(item, dict):
                            c = str(item.get("code") or item.get("symbol") or "").strip().zfill(6)
                            n = str(item.get("name") or "").strip() or get_stock_name(c) or c
                            if c:
                                stocks_to_scan.append({"code": c, "name": n})
                        elif isinstance(item, str) and item.strip():
                            c = item.strip().zfill(6)
                            stocks_to_scan.append({"code": c, "name": get_stock_name(c) or c})
            except Exception as e:
                logger.warning(f"读取自定义自选股文件 {args.watchlist} 失败: {e}，将使用系统自选股。")
                stocks_to_scan = load_watchlist_items()
        else:
            stocks_to_scan = load_watchlist_items()

        # 补全股票名称
        for s in stocks_to_scan:
            s["code"] = s["code"].zfill(6)
            if not s.get("name") or s["name"] == s["code"] or s["name"].startswith("标的_"):
                s["name"] = get_stock_name(s["code"]) or s["code"]
        pool_desc = f"自选池 ({len(stocks_to_scan)}只)"

    # 并发线程数智能调优：对于大盘子自动提高线程数
    effective_workers = args.workers
    if len(stocks_to_scan) >= 100 and effective_workers <= 2:
        effective_workers = min(12, max(6, os.cpu_count() or 8))

    # 输出导出路径自动处理
    output_csv = args.output
    if not output_csv and (args.all_market or args.universe or len(stocks_to_scan) >= 100):
        ts_tag = datetime.now().strftime("%Y%m%d_%H%M%S")
        scope_tag = "all" if args.all_market else (args.universe or "pool")
        output_csv = str(PROJECT_ROOT / "output" / f"quadrilateral_{scope_tag}_{ts_tag}.csv")

    notifier = WeChatNotifier(
        wecom_webhook=args.webhook,
        pushplus_token=args.pushplus_token,
        serverchan_key=args.serverchan_key,
    )

    if args.now or not args.daemon:
        # 单次执行模式
        run_single_scan_and_notify(
            notifier=notifier,
            stocks=stocks_to_scan,
            period=args.period,
            lookback=args.lookback,
            slot_desc="即时扫描",
            pool_name=pool_desc,
            notify_if_empty=args.notify_empty,
            generate_images=not args.no_image,
            max_images=args.max_images,
            workers=effective_workers,
            min_score=args.min_score,
            output_path=output_csv,
        )
        if not args.daemon:
            return

    # 常驻监控模式
    run_daemon_loop(
        notifier=notifier,
        stocks=stocks_to_scan,
        period=args.period,
        lookback=args.lookback,
        force_trading_day_check=not args.ignore_trading_day,
        generate_images=not args.no_image,
        max_images=args.max_images,
        workers=effective_workers,
        pool_name=pool_desc,
        min_score=args.min_score,
        output_path=output_csv,
    )


if __name__ == "__main__":
    main()
