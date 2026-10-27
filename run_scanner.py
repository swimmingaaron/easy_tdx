#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""全市场多策略多线程并发选股执行脚本 (run_scanner.py)

功能特性：
1. 交互式菜单：按序号快速选择战略（策略）、周期、选股范围（支持直接回车默认运行）；
2. 推荐模式：缠论三级联共振 (chanlun_resonance) 与 缠论二级共振 (chanlun_dual_resonance)；
3. 多线程并发：支持动态指定线程数 (默认程序自适应判断当前系统CPU最大线程数)；
4. 缓存加速：从通达信行情服务器拉取数据并自动持久化保存在本地 cache 中，二次运行秒级复用；
5. 结果导出：自动在终端格式化输出命中列表，并生成 CSV 和 JSON 结果报表；
6. 命令行支持：支持非交互式 CLI 参数快速启动。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import sys
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

# 1. 确保 easy_tdx 源码路径优先加载
src_path = Path(__file__).resolve().parent / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

# 配置基础日志 (关闭冗余调试信息，保持终端清爽)
logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")
logger = logging.getLogger("run_screener")

from easy_tdx.strategies.registry import list_all_strategies, get_strategy
from easy_tdx.screener.scanner import scan_market_strategy, CHANLUN_PERIOD_PRESETS
from easy_tdx.screener.universe import get_universe_symbols, get_universe_options, CORE_UNIVERSE, sync_new_stocks


# 终端 ANSI 色彩定义
class Colors:
    HEADER = "\033[95m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    BOLD = "\033[1m"
    UNDERLINE = "\033[4m"
    RESET = "\033[0m"


def _colored(text: str, color: str) -> str:
    """包装带有颜色的终端文本"""
    return f"{color}{text}{Colors.RESET}"


def display_strategy_menu(strategies: list[dict[str, Any]]) -> str:
    """打印策略列表并提示用户按序列号选择（默认 1: 缠论共振策略）"""
    print("\n" + "=" * 80)
    print(_colored("【第一步：战略选择】请选择要执行的选股策略（支持 48+ 全量策略库）：", Colors.BOLD + Colors.CYAN))
    print("=" * 80)

    # 按照分类组织展示
    categories: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for idx, st in enumerate(strategies):
        cat = st.get("category", "综合策略")
        categories.setdefault(cat, []).append((idx + 1, st))

    for cat_name, items in categories.items():
        print(f"\n{_colored('● ' + cat_name, Colors.YELLOW + Colors.BOLD)}")
        print("-" * 80)
        for seq, st in items:
            name_code = st["name"]
            disp_name = st["display_name"]
            desc = (st.get("description") or "").split("\n")[0][:45]
            if name_code == "chanlun_resonance":
                tag = _colored(" [★系统默认推荐 / 三级联共振]", Colors.GREEN + Colors.BOLD)
                print(f"  {_colored(f'[{seq:2d}]', Colors.GREEN + Colors.BOLD)} {_colored(name_code, Colors.BOLD):24s} {disp_name}{tag}")
                print(f"       {_colored('└─ ' + desc, Colors.CYAN)}")
            elif name_code == "chanlun_dual_resonance":
                tag = _colored(" [★系统重点推荐 / 二级共振]", Colors.GREEN + Colors.BOLD)
                print(f"  {_colored(f'[{seq:2d}]', Colors.GREEN + Colors.BOLD)} {_colored(name_code, Colors.BOLD):24s} {disp_name}{tag}")
                print(f"       {_colored('└─ ' + desc, Colors.CYAN)}")
            elif name_code == "chanlun_strategy":
                tag = _colored(" [缠论主升3买 / 4级联]", Colors.BLUE + Colors.BOLD)
                print(f"  {_colored(f'[{seq:2d}]', Colors.YELLOW)} {name_code:24s} {disp_name}{tag}")
                print(f"       {_colored('└─ ' + desc, Colors.CYAN)}")
            else:
                print(f"  [{seq:2d}] {name_code:24s} {disp_name}  {Colors.RESET}({desc})")

    print("\n" + "=" * 80)
    prompt_txt = _colored("请输入策略序号 [1-54] (直接回车默认: 1. 缠论共振策略 / 2. 缠论二级共振策略): ", Colors.BOLD + Colors.GREEN)
    choice = input(prompt_txt).strip()

    if not choice:
        return "chanlun_resonance"

    if choice.isdigit():
        seq_num = int(choice)
        if 1 <= seq_num <= len(strategies):
            chosen = strategies[seq_num - 1]["name"]
            print(_colored(f"已选择策略: {chosen} ({strategies[seq_num - 1]['display_name']})", Colors.GREEN))
            return chosen
    # 支持直接输入策略名称
    for st in strategies:
        if choice.lower() in (st["name"].lower(), st["display_name"].lower()):
            return st["name"]

    print(_colored("输入无效，默认使用: 1. chanlun_resonance (缠论共振策略)", Colors.YELLOW))
    return "chanlun_resonance"


def display_period_menu(strategy_name: str) -> str:
    """打印周期选项并提示选择（默认推荐 ALL_CASCADE, DUAL_CASCADE 或 DAY）"""
    print("\n" + "=" * 80)
    print(_colored("【第二步：周期选择】请选择策略执行周期：", Colors.BOLD + Colors.CYAN))
    print("=" * 80)

    if strategy_name == "chanlun_resonance":
        periods = [
            ("MONTH_WEEK_DAY_2BUY", "月周日 共振 (日线 2买 · 默认推荐)", "【默认推荐】月周大趋势多头共振，筛选日线上出现2买的起爆标的"),
            ("MONTH_WEEK_DAY_3BUY", "月周日 共振 (日线 3买)", "月周大趋势多头共振，筛选日线上出现3买确认的突破标的"),
            ("SEASON_MONTH_WEEK_2BUY", "季月周 共振 (周线 2买)", "季月大趋势多头共振，筛选周线上出现2买的优质标的"),
            ("SEASON_MONTH_WEEK_3BUY", "季月周 共振 (周线 3买)", "季月大趋势多头共振，筛选周线上出现3买确认的标的"),
            ("WEEK_DAY_30F_2BUY", "周日30F 共振 (30F 2买)", "周日趋势多头共振，筛选30分钟级别上出现2买的精准进场标的"),
            ("WEEK_DAY_30F_3BUY", "周日30F 共振 (30F 3买)", "周日趋势多头共振，筛选30分钟级别上出现3买确认的标的"),
            ("ALL_CASCADE", "全级别三级联共振 (月周日+周日30M+日30M5F)", "全级别大买严苛共振，要求月周日、周日30M、日30M5F全部满足"),
        ]
        for seq, (p_code, p_name, p_desc) in enumerate(periods, 1):
            if seq == 1:
                print(f"  {_colored(f'[{seq}]', Colors.GREEN + Colors.BOLD)} {_colored(p_code, Colors.BOLD):24s} {p_name} {_colored('[默认推荐]', Colors.GREEN)}")
            else:
                print(f"  [{seq}] {p_code:24s} {p_name}")
            print(f"      {_colored('└─ ' + p_desc, Colors.CYAN)}")

        prompt_txt = _colored("\n请输入周期序号 [1-7] (直接回车默认: 1. MONTH_WEEK_DAY_2BUY 月周日共振 日线2买): ", Colors.BOLD + Colors.GREEN)
        choice = input(prompt_txt).strip()
        if not choice or choice == "1":
            return "MONTH_WEEK_DAY_2BUY"
        if choice.isdigit() and 1 <= int(choice) <= len(periods):
            return periods[int(choice) - 1][0]
        for p_code, _, _ in periods:
            if choice.upper() == p_code:
                return p_code
        return "MONTH_WEEK_DAY_2BUY"

    if strategy_name == "chanlun_dual_resonance":
        periods = [
            ("DUAL_CASCADE", "二级级联共振 (周日30F+日30F5F)", "【默认推荐】周日30F周线1买+日30F5F日线1买+次级别2/3买"),
            ("DAY_30F_5F", "日 30F 5F 区间套", "日线1买+30F中枢承接+5M 2/3买"),
            ("WEEK_DAY_30F", "周 日 30F 区间套", "周线1买+日线稳健中枢+30M 2/3买"),
        ]
        for seq, (p_code, p_name, p_desc) in enumerate(periods, 1):
            if seq == 1:
                print(f"  {_colored(f'[{seq}]', Colors.GREEN + Colors.BOLD)} {_colored(p_code, Colors.BOLD):18s} {p_name} {_colored('[默认推荐]', Colors.GREEN)}")
            else:
                print(f"  [{seq}] {p_code:18s} {p_name}")
            print(f"      {_colored('└─ ' + p_desc, Colors.CYAN)}")

        prompt_txt = _colored("\n请输入周期序号 [1-3] (直接回车默认: 1. DUAL_CASCADE 二级共振): ", Colors.BOLD + Colors.GREEN)
        choice = input(prompt_txt).strip()
        if not choice or choice == "1":
            return "DUAL_CASCADE"
        if choice.isdigit() and 1 <= int(choice) <= len(periods):
            return periods[int(choice) - 1][0]
        for p_code, _, _ in periods:
            if choice.upper() == p_code:
                return p_code
        return "DUAL_CASCADE"

    is_chanlun = "chanlun" in strategy_name

    if is_chanlun:
        periods = [
            ("MONTH_WEEK_DAY_2BUY", "月周日 共振 (日线 2买 · 默认推荐)", "【默认推荐】月周大买多头趋势共振 + 日线 2买"),
            ("MONTH_WEEK_DAY_3BUY", "月周日 共振 (日线 3买)", "月周大买多头趋势共振 + 日线 3买"),
            ("SEASON_MONTH_WEEK_2BUY", "季月周 共振 (周线 2买)", "季月大买多头趋势共振 + 周线 2买"),
            ("SEASON_MONTH_WEEK_3BUY", "季月周 共振 (周线 3买)", "季月大买多头趋势共振 + 周线 3买"),
            ("WEEK_DAY_30F_2BUY", "周日30F 共振 (30F 2买)", "周日大买多头趋势共振 + 30F 2买"),
            ("WEEK_DAY_30F_3BUY", "周日30F 共振 (30F 3买)", "周日大买多头趋势共振 + 30F 3买"),
            ("DAY_30F_5F", "日 30F 5F 区间套", "日线大买+30F中枢承接+5M 2买"),
            ("ALL_CASCADE", "全级别三级联共振 (月周日+周日30M+日30M5F)", "月周日大买+周日30M大买+日30M5F大买+5M2买"),
            ("30F_5F_1F", "30F 5F 1F 区间套", "超短日内高频 T+0 买卖点联动"),
        ]
        for seq, (p_code, p_name, p_desc) in enumerate(periods, 1):
            if seq == 1:
                print(f"  {_colored(f'[{seq}]', Colors.GREEN + Colors.BOLD)} {_colored(p_code, Colors.BOLD):24s} {p_name} {_colored('[默认推荐]', Colors.GREEN)}")
            else:
                print(f"  [{seq}] {p_code:24s} {p_name}")
            print(f"      {_colored('└─ ' + p_desc, Colors.CYAN)}")

        prompt_txt = _colored("\n请输入周期序号 [1-9] (直接回车默认: 1. MONTH_WEEK_DAY_2BUY 月周日共振 日线2买): ", Colors.BOLD + Colors.GREEN)
        choice = input(prompt_txt).strip()
        if not choice or choice == "1":
            return "MONTH_WEEK_DAY_2BUY"
        if choice.isdigit() and 1 <= int(choice) <= len(periods):
            return periods[int(choice) - 1][0]
        for p_code, _, _ in periods:
            if choice.upper() == p_code:
                return p_code
        return "MONTH_WEEK_DAY_2BUY"
    else:
        periods = [
            ("DAY", "日线 (主选周期，信号稳健，过滤盘中噪音)", "默认推荐"),
            ("30M", "30分钟线 (日内活跃波段，买卖点更灵敏)", ""),
            ("60M", "60分钟线 (小时级波段走势)", ""),
            ("WEEK", "周线 (大波段长线牛股捕捉)", ""),
            ("MONTH", "月线 (超大周期长牛选股)", ""),
        ]
        for seq, (p_code, p_name, tag) in enumerate(periods, 1):
            tag_str = _colored(f"[{tag}]", Colors.GREEN) if tag else ""
            if seq == 1:
                print(f"  {_colored(f'[{seq}]', Colors.GREEN + Colors.BOLD)} {p_code:10s} {p_name} {tag_str}")
            else:
                print(f"  [{seq}] {p_code:10s} {p_name}")

        prompt_txt = _colored("\n请输入周期序号 [1-5] (直接回车默认: 1. DAY 日线): ", Colors.BOLD + Colors.GREEN)
        choice = input(prompt_txt).strip()
        if not choice or choice == "1":
            return "DAY"
        if choice.isdigit() and 1 <= int(choice) <= len(periods):
            return periods[int(choice) - 1][0]
        return "DAY"


def parse_time_param(time_input: str | None) -> tuple[int, str, str]:
    """解析时间参数/回溯窗口，支持天数(如 22)、时间缩写(如 1m, 1w, 2m, 3m) 或具体起始日期(如 2026-09-24)
    
    返回: (lookback_bars, time_desc, start_date_str)
    默认: 22 交易日 (约1个月前 / 30自然日)
    """
    today = date.today()
    s = str(time_input or "").strip().lower()

    if not s or s in ("1m", "1月", "1月前", "month", "1month", "30d", "30天"):
        bars = 22
        cal_days = 30
        st_date = today - timedelta(days=cal_days)
        return bars, "1个月前 (22交易日)", st_date.strftime("%Y-%m-%d")

    if s in ("1w", "1周", "1周前", "week", "1week", "5d", "5天"):
        bars = 5
        st_date = today - timedelta(days=7)
        return bars, "1周前 (5交易日)", st_date.strftime("%Y-%m-%d")

    if s in ("2w", "2周", "2周前", "10d", "10天"):
        bars = 10
        st_date = today - timedelta(days=14)
        return bars, "2周前 (10交易日)", st_date.strftime("%Y-%m-%d")

    if s in ("2m", "2月", "2月前", "60d", "60天"):
        bars = 44
        st_date = today - timedelta(days=60)
        return bars, "2个月前 (44交易日)", st_date.strftime("%Y-%m-%d")

    if s in ("3m", "3月", "3月前", "90d", "90天", "quarter"):
        bars = 66
        st_date = today - timedelta(days=90)
        return bars, "3个月前 (66交易日)", st_date.strftime("%Y-%m-%d")

    if s in ("6m", "半年", "半年内", "180d"):
        bars = 125
        st_date = today - timedelta(days=180)
        return bars, "半年内 (125交易日)", st_date.strftime("%Y-%m-%d")

    if s in ("1y", "1年", "1年内", "365d", "year"):
        bars = 250
        st_date = today - timedelta(days=365)
        return bars, "1年内 (250交易日)", st_date.strftime("%Y-%m-%d")

    # 尝试解析为纯数字 (交易日天数或自然天数)
    clean_num = s.rstrip("d天日bars")
    if clean_num.isdigit():
        val = int(clean_num)
        bars = max(1, val)
        cal_days = max(1, int(bars * 7 / 5))
        st_date = today - timedelta(days=cal_days)
        return bars, f"{bars} 交易日前", st_date.strftime("%Y-%m-%d")

    # 尝试解析为具体日期 (YYYY-MM-DD, YYYY/MM/DD, YYYYMMDD)
    date_clean = s.replace("/", "-").replace(".", "")
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            target_dt = datetime.strptime(date_clean, fmt).date()
            diff_days = (today - target_dt).days
            if diff_days <= 0:
                bars = 1
                return bars, f"{target_dt.strftime('%Y-%m-%d')} (今日最新)", target_dt.strftime("%Y-%m-%d")
            # 估算交易日 (约为自然日的 5/7)
            bars = max(1, int(diff_days * 5 / 7))
            return bars, f"{target_dt.strftime('%Y-%m-%d')} 至今 (约{bars}交易日)", target_dt.strftime("%Y-%m-%d")
        except ValueError:
            pass

    # 兜底默认 1 个月前 (22 交易日)
    bars = 22
    st_date = today - timedelta(days=30)
    return bars, "1个月前 (22交易日)", st_date.strftime("%Y-%m-%d")


def display_time_menu(strategy_name: str) -> tuple[int, str, str]:
    """打印时间参数与信号回溯窗口选项并提示选择（默认 1: 1个月前 / 22交易日）"""
    print("\n" + "=" * 80)
    print(_colored("【第三步：时间范围与信号回溯】请选择买点有效时效（默认: 1个月前）：", Colors.BOLD + Colors.CYAN))
    print("=" * 80)

    options = [
        ("1m", "1个月前 (22 交易日，兼顾稳定性与时效波段)", "【默认推荐】捕捉近一个月内出现的优质买点与共振转折"),
        ("1w", "1周前 (5 交易日，极速超短)", "仅锁定近 5 个交易日内刚刚启动的最新买点"),
        ("2w", "2周前 (10 交易日，短线主升)", "捕捉半月内确认次级别2/3买并刚开始加速拉升的标的"),
        ("2m", "2个月前 (44 交易日，中线波段)", "跟踪近两月来筑底反转的中期上升趋势标的"),
        ("3m", "3个月前 (66 交易日，大波段底部布局)", "季度级别大底部反转信号"),
        ("custom", "自定义天数或起始日期", "手动输入交易日天数(如 15)或具体日期(如 2026-09-24)"),
    ]

    for seq, (t_code, t_name, t_desc) in enumerate(options, 1):
        if seq == 1:
            print(f"  {_colored(f'[{seq}]', Colors.GREEN + Colors.BOLD)} {_colored(t_code, Colors.BOLD):8s} {t_name} {_colored('[默认推荐]', Colors.GREEN)}")
        else:
            print(f"  [{seq}] {t_code:8s} {t_name}")
        print(f"      {_colored('└─ ' + t_desc, Colors.CYAN)}")

    prompt_txt = _colored("\n请输入时间范围序号 [1-6] 或天数/日期 (直接回车默认: 1. 1m 一个月前): ", Colors.BOLD + Colors.GREEN)
    choice = input(prompt_txt).strip()

    if not choice or choice == "1":
        res = parse_time_param("1m")
        print(_colored(f"已选择时间范围: {res[1]} (起始约 {res[2]} 至今)", Colors.GREEN))
        return res
    if choice.isdigit() and 1 <= int(choice) <= len(options):
        sel_code = options[int(choice) - 1][0]
        if sel_code == "custom":
            custom_input = input(_colored("请输入自定义交易日天数(如 15)或具体日期(如 2026-09-24): ", Colors.YELLOW)).strip()
            res = parse_time_param(custom_input)
            print(_colored(f"已设置时间范围: {res[1]} (起始约 {res[2]} 至今)", Colors.GREEN))
            return res
        res = parse_time_param(sel_code)
        print(_colored(f"已选择时间范围: {res[1]} (起始约 {res[2]} 至今)", Colors.GREEN))
        return res

    res = parse_time_param(choice)
    print(_colored(f"已设置时间范围: {res[1]} (起始约 {res[2]} 至今)", Colors.GREEN))
    return res


def display_universe_menu() -> tuple[str, list[str] | None]:
    """打印选股范围选项并提示选择（默认 1: all 全市场全部股票）"""
    print("\n" + "=" * 80)
    print(_colored("【第四步：选股范围】请选择扫描范围（默认: 全市场全A股）：", Colors.BOLD + Colors.CYAN))
    print("=" * 80)

    all_cnt = len(get_universe_symbols("all"))
    options = [
        ("all", f"全市场全A股 ({all_cnt} 只股票，支持新股自动扩容)", "全市场无死角多线程地毯式深度扫描", "【默认推荐】"),
        ("core", f"核心流动性龙头池 ({len(CORE_UNIVERSE)} 只)", "东方财富全行业冠军、全球领跑龙头核心资产精选", "极速体验"),
        ("hs300", "沪深300标的池 (300 只)", "A股规模大、流动性好的最具代表性白马蓝筹", "稳健白马"),
        ("zz500", "中证500标的池 (500 只)", "聚焦各细分行业高成长、弹性大的优质中盘主力", "成长弹性"),
        ("zz1000", "中证1000标的池 (1000 只)", "中小盘活跃品种，捕捉游资与弹性主升机会", "中小盘热点"),
        ("custom", "自定义股票代码列表", "手动输入股票代码（如 002439, 600519, 000001 等）", "自由定制"),
    ]

    for seq, (u_code, u_name, u_desc, badge) in enumerate(options, 1):
        if seq == 1:
            print(f"  {_colored(f'[{seq}]', Colors.GREEN + Colors.BOLD)} {_colored(u_code, Colors.BOLD):10s} {u_name} {_colored(badge, Colors.GREEN)}")
        else:
            print(f"  [{seq}] {u_code:10s} {u_name} {_colored(badge, Colors.YELLOW)}")
        print(f"      {_colored('└─ ' + u_desc, Colors.CYAN)}")

    prompt_txt = _colored("\n请输入选股范围序号 [1-6] (直接回车默认: 1. all 全市场全A股): ", Colors.BOLD + Colors.GREEN)
    choice = input(prompt_txt).strip()

    if not choice or choice == "1":
        return "all", None
    if choice.isdigit():
        seq_num = int(choice)
        if 1 <= seq_num <= len(options):
            u_code = options[seq_num - 1][0]
            if u_code == "custom":
                raw_codes = input(_colored("请输入自选股票代码（逗号或空格隔开，如 002439,600519）: ", Colors.YELLOW)).strip()
                symbols = [c.strip().zfill(6) for c in raw_codes.replace("，", ",").replace(" ", ",").split(",") if c.strip()]
                return "custom", symbols
            return u_code, None

    for u_code, _, _, _ in options:
        if choice.lower() == u_code:
            return u_code, None

    return "all", None


def display_concurrency_menu() -> tuple[int, bool]:
    """配置并发线程数与缓存刷新行为"""
    print("\n" + "=" * 80)
    print(_colored("【第五步：多线程并发与缓存设置】", Colors.BOLD + Colors.CYAN))
    print("=" * 80)

    # 1. 线程数（动态读取当前系统 CPU 逻辑核心/最大线程数）
    cpu_threads = max(1, os.cpu_count() or 4)
    prompt_threads = _colored(
        f"请输入并发工作线程数 [1-64] (直接回车默认当前系统CPU最大线程数: {cpu_threads} 线程): ",
        Colors.BOLD + Colors.GREEN,
    )
    threads_input = input(prompt_threads).strip()
    workers = cpu_threads
    if threads_input.isdigit():
        workers = max(1, min(int(threads_input), 128))

    # 2. 缓存策略
    prompt_refresh = _colored("是否穿透缓存从行情服务器强制重新下载全部数据？[y/N] (直接回车默认 N 优先读取/复用本地有效缓存): ", Colors.BOLD + Colors.YELLOW)
    refresh_input = input(prompt_refresh).strip().lower()
    force_refresh = refresh_input in ("y", "yes", "true", "1")

    print(_colored(f"\n配置完成: 并发线程数 = {workers} | 穿透强制刷新 = {'是 (全部重新下载)' if force_refresh else '否 (优先复用有效缓存并自动补全更新)'}", Colors.GREEN))
    return workers, force_refresh


def print_results_table(results: list[dict[str, Any]], strategy_name: str, period: str, universe: str, elapsed_sec: float, time_desc: str = "") -> None:
    """以精美表格形式格式化输出最终选股命中结果"""
    print("\n" + "=" * 118)
    time_tag = f" | 回溯: {time_desc}" if time_desc else " | 回溯: 1个月前"
    header_title = f"【选股完成】策略: {strategy_name} | 周期: {period}{time_tag} | 范围: {universe} | 命中: {len(results)} 只 | 耗时: {elapsed_sec:.2f}s"
    print(_colored(header_title, Colors.BOLD + Colors.GREEN))
    print("=" * 118)

    if not results:
        print(_colored(" [!] 当前筛选条件下无满足条件的股票（全满足强约束一票否决有效滤除假信号）。", Colors.YELLOW))
        print("=" * 118 + "\n")
        return

    # 按涨跌幅倒序排列
    sorted_res = sorted(results, key=lambda x: float(x.get("change_pct") or 0.0), reverse=True)

    header = f"{'序号':^4} | {'代码':^8} | {'股票名称':^10} | {'触发价':^8} | {'触发日涨跌':^10} | {'自触发涨幅':^10} | {'触发信号/买卖点':^28} | {'触发日期':^12} | {'距今'}"
    print(_colored(header, Colors.BOLD))
    print("-" * 118)

    for i, r in enumerate(sorted_res, 1):
        sym = r.get("code") or r.get("symbol") or "--"
        name = r.get("name") or "--"
        price = float(r.get("price") or 0.0)
        chg = float(r.get("change_pct") or r.get("latest_change_pct") or 0.0)
        since_chg = float(r.get("since_signal_pct") or 0.0)
        pat = r.get("status_label") or r.get("pattern_status") or r.get("trigger_patterns") or "--"
        if isinstance(pat, list):
            pat = " · ".join(pat)
        sig_date = str(r.get("signal_date") or r.get("trigger_date") or "--")[:10]
        days = r.get("days_ago") or 0

        # 色彩标注涨跌
        chg_str = f"{chg:+.2f}%"
        if chg > 0:
            chg_colored = _colored(f"{chg_str:>9}", Colors.RED)
        elif chg < 0:
            chg_colored = _colored(f"{chg_str:>9}", Colors.GREEN)
        else:
            chg_colored = f"{chg_str:>9}"

        since_str = f"{since_chg:+.2f}%"
        if since_chg > 0:
            since_colored = _colored(f"{since_str:>10}", Colors.RED)
        elif since_chg < 0:
            since_colored = _colored(f"{since_str:>10}", Colors.GREEN)
        else:
            since_colored = f"{since_str:>10}"

        print(f"{i:4d} | {sym:8s} | {name:10s} | {price:8.2f} | {chg_colored} | {since_colored} | {pat:28s} | {sig_date:12s} | {days}天前")

    print("-" * 118)
    print(_colored(f"总计选出 {len(sorted_res)} 只标的资产，全部信号已严格通过三级联区间套与大趋势防线校验！", Colors.GREEN + Colors.BOLD))
    print("=" * 118 + "\n")


def export_results(
    results: list[dict[str, Any]], 
    strategy_name: str, 
    period: str, 
    universe: str, 
    total_scanned: int = 0,
    lookback_bars: int = 22,
    time_desc: str = "",
    start_date: str = ""
) -> tuple[Path, Path]:
    """将选股结果导出为 CSV 与 JSON 持久化报告，并同步写入 data/screener_cache 确保 48 大策略选股系统直接无缝复用"""
    output_dir = Path.cwd() / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    today_str = date.today().strftime("%Y%m%d")
    p_clean = str(period).strip().upper()
    base_name = f"scanner_{strategy_name}_{universe}_{p_clean}_{today_str}"
    csv_file = output_dir / f"{base_name}.csv"
    json_file = output_dir / f"{base_name}.json"

    # 统一标准缓存结构 (与 48 大策略全市场选股系统完全一致)
    total_cnt = total_scanned if total_scanned > 0 else len(results)
    if total_cnt == 0 and universe != "custom":
        try:
            total_cnt = len(get_universe_symbols(universe))
        except Exception:
            total_cnt = len(results)

    report_payload = {
        "strategy": strategy_name,
        "universe": universe,
        "period": p_clean,
        "lookback_bars": lookback_bars,
        "time_desc": time_desc,
        "start_date": start_date,
        "total_count": total_cnt,
        "date": today_str,
        "timestamp": time.time(),
        "matches_count": len(results),
        "matches": results,
    }

    # 1. 导出 output/ 目录 JSON 报告 (标准字典结构)
    try:
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump(report_payload, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"Failed to export JSON: {e}")

    # 2. 同步写入 data/screener_cache 供 Web UI 48大策略系统直接秒级复用
    try:
        from easy_tdx.screener.scanner import _save_cache
        _save_cache(strategy_name, universe, total_cnt, results, period=p_clean)
    except Exception as e:
        logger.warning(f"Failed to sync screener cache: {e}")

    # 2. 导出 CSV
    try:
        import pandas as pd
        if results:
            clean_rows = []
            for r in results:
                days = r.get("days_ago") or 0
                latest_chg = r.get("latest_change_pct") if r.get("latest_change_pct") is not None else float(r.get("change_pct") or 0.0)
                since_chg = float(r.get("since_signal_pct") or 0.0)
                latest_pat = r.get("latest_pattern_status") or r.get("pattern_status") or "--"
                trig_pat = r.get("trigger_pattern_status") or r.get("pattern_status") or r.get("status_label") or "--"
                trig_dt = r.get("signal_date") or r.get("trigger_date") or "--"
                pat_desc = r.get("pattern_full_desc") or (f"当日:{latest_chg:+.2f}% | 自触发:{since_chg:+.2f}% | 形态:{latest_pat}" if days == 0 else f"当日:{latest_chg:+.2f}%(形态:{latest_pat}) 自触发:{since_chg:+.2f}% | 触发:{trig_dt}({days}天前,形态:{trig_pat})")

                clean_rows.append({
                    "代码": r.get("code") or r.get("symbol"),
                    "名称": r.get("name"),
                    "触发价": r.get("price"),
                    "触发日涨跌%": r.get("change_pct"),
                    "当日涨跌%": latest_chg,
                    "自触发涨幅%": since_chg,
                    "触发信号形态": r.get("status_label") or r.get("pattern_status"),
                    "触发日期": r.get("signal_date") or r.get("trigger_date"),
                    "距今交易日": days,
                    "形态特征全景": pat_desc,
                    "策略": r.get("strategy"),
                    "周期": r.get("period"),
                })
            df_out = pd.DataFrame(clean_rows)
            df_out.to_csv(csv_file, index=False, encoding="utf-8-sig")
    except Exception as e:
        logger.warning(f"Failed to export CSV: {e}")

    return csv_file, json_file


def main() -> None:
    parser = argparse.ArgumentParser(description="easy_tdx 全市场多策略多线程并发选股执行工具")
    parser.add_argument("-s", "--strategy", type=str, default="", help="选股策略名称（默认: chanlun_resonance 缠论共振策略 / 可选 chanlun_dual_resonance 缠论二级共振策略等）")
    parser.add_argument("-p", "--period", type=str, default="", help="分析周期（默认: MONTH_WEEK_DAY_2BUY 月周日2买共振 / 可选 1-7序号, MONTH_WEEK_DAY_3BUY, SEASON_MONTH_WEEK_2BUY, SEASON_MONTH_WEEK_3BUY, WEEK_DAY_30F_2BUY, WEEK_DAY_30F_3BUY, ALL_CASCADE 等）")
    parser.add_argument("-t", "--time", "--lookback", dest="time_param", type=str, default="", help="信号回溯时间范围：支持天数(如 22)、时间跨度(如 1m, 1w, 2m, 3m) 或具体起始日期(如 2026-09-24)（默认: 1m / 22交易日，即约一月前）")
    parser.add_argument("-u", "--universe", type=str, default="", help="选股范围：all/core/hs300/zz500/zz1000/代码列表（默认: all）")
    cpu_threads = max(1, os.cpu_count() or 4)
    parser.add_argument("-w", "--workers", type=int, default=0, help=f"并发线程数（默认: 当前CPU最大线程数 {cpu_threads}）")
    parser.add_argument("--refresh", action="store_true", help="强制从行情服务器穿透下载全量数据")
    parser.add_argument("--sync-ipo", "--sync-new-stocks", dest="sync_ipo", action="store_true", help="主动扫描通达信行情，自动扩容最新发行/上市的新股到全市场股票池 (data/ashares_universe.json)")
    parser.add_argument("--no-interactive", action="store_true", help="禁用交互式菜单，完全依靠命令行参数执行")

    args = parser.parse_args()

    if getattr(args, "sync_ipo", False):
        print("\n" + "=" * 80)
        print(_colored("【主动同步】正在从通达信行情网络扫描最新发行/上市新股...", Colors.BOLD + Colors.CYAN))
        print("=" * 80)
        new_stocks = sync_new_stocks()
        if new_stocks:
            print(_colored(f"✔ 成功扩容 {len(new_stocks)} 只新股: {', '.join(new_stocks)}", Colors.BOLD + Colors.GREEN))
        else:
            print(_colored("✔ 全市场股票池已是最新，无新增未登记新股。", Colors.GREEN))
        all_now = len(get_universe_symbols("all"))
        print(_colored(f"当前全市场股票总数: {all_now} 只\n", Colors.BOLD + Colors.YELLOW))
        return

    # 加载系统注册的所有策略
    all_strategies = list_all_strategies()

    is_interactive = not args.no_interactive and not (args.strategy and args.universe)

    if is_interactive:
        print("\n" + "=" * 80)
        print(_colored("   ★ easy_tdx 48大选股策略多线程并发控制系统 ★", Colors.BOLD + Colors.GREEN))
        print(_colored("   缠论全级别共振 | 5200+ A股地毯式扫描 | 服务器数据自动缓存", Colors.CYAN))
        print("=" * 80)

        # 1. 策略选择
        strategy_name = display_strategy_menu(all_strategies)

        # 2. 周期选择
        period = display_period_menu(strategy_name)

        # 3. 时间范围选择
        lookback_bars, time_desc, start_date_str = display_time_menu(strategy_name)

        # 4. 选股范围选择
        universe_choice, custom_symbols = display_universe_menu()

        # 5. 并发线程与缓存设置
        max_workers, force_refresh = display_concurrency_menu()
    else:
        strategy_name = args.strategy.strip() or "chanlun_resonance"
        if args.period.strip():
            raw_p = args.period.strip()
            if strategy_name == "chanlun_resonance":
                seq_map = {
                    "1": "MONTH_WEEK_DAY_2BUY",
                    "2": "MONTH_WEEK_DAY_3BUY",
                    "3": "SEASON_MONTH_WEEK_2BUY",
                    "4": "SEASON_MONTH_WEEK_3BUY",
                    "5": "WEEK_DAY_30F_2BUY",
                    "6": "WEEK_DAY_30F_3BUY",
                    "7": "ALL_CASCADE",
                }
                period = seq_map.get(raw_p, raw_p)
            else:
                period = raw_p
        elif strategy_name == "chanlun_dual_resonance":
            period = "DUAL_CASCADE"
        elif strategy_name == "chanlun_resonance":
            period = "MONTH_WEEK_DAY_2BUY"
        elif strategy_name == "chanlun_strategy":
            period = "DAY_30F_5F"
        else:
            period = "DAY"
        universe_choice = args.universe.strip() or "all"
        custom_symbols = None
        if "," in universe_choice or universe_choice.isdigit():
            custom_symbols = [c.strip().zfill(6) for c in universe_choice.split(",") if c.strip()]
            universe_choice = "custom"
        lookback_bars, time_desc, start_date_str = parse_time_param(args.time_param or "1m")
        max_workers = args.workers if args.workers > 0 else cpu_threads
        force_refresh = args.refresh

    # 解析标的股票列表
    if custom_symbols:
        symbols_to_scan = custom_symbols
        universe_desc = f"自定义 {len(symbols_to_scan)} 只"
    else:
        symbols_to_scan = get_universe_symbols(universe_choice, force_refresh=force_refresh)
        universe_desc = f"{universe_choice} ({len(symbols_to_scan)} 只)"

    print("\n" + "=" * 80)
    print(_colored(f"【准备就绪，开始多线程选股扫描】", Colors.BOLD + Colors.CYAN))
    print(f"● 选股策略: {_colored(strategy_name, Colors.GREEN + Colors.BOLD)} ({get_strategy(strategy_name).display_name})")
    print(f"● 执行周期: {_colored(period, Colors.GREEN)}")
    print(f"● 信号时效: {_colored(f'{time_desc} (起始约 {start_date_str} 至今)', Colors.CYAN)}")
    print(f"● 选股范围: {_colored(universe_desc, Colors.YELLOW)}")
    print(f"● 并发配置: {_colored(str(max_workers) + ' 线程', Colors.BOLD)}")
    print(f"● 行情来源: {_colored('通达信实时行情服务器 (自动写入本地 cache)', Colors.CYAN)}")
    print("=" * 80 + "\n")

    # 优雅支持 Ctrl+C 中断
    stop_event = threading.Event()

    def _sig_handler(sig, frame):
        print(_colored("\n[!] 收到用户中断请求 (Ctrl+C)，正在安全停止各线程并整理已扫描结果...", Colors.YELLOW))
        stop_event.set()

    signal.signal(signal.SIGINT, _sig_handler)

    # 动态终端进度条
    start_time = time.time()
    last_print_time = 0.0

    def progress_callback(processed: int, total: int, matches_count: int, pct: float) -> None:
        nonlocal last_print_time
        now = time.time()
        # 限制终端刷新频率 (每 0.3 秒刷新一次，避免控制台抖动)
        if now - last_print_time >= 0.3 or processed >= total:
            last_print_time = now
            elapsed = now - start_time
            speed = processed / elapsed if elapsed > 0 else 0
            bar_len = 25
            filled = int(bar_len * processed / total) if total > 0 else 0
            bar_str = "=" * filled + ">" + " " * max(0, bar_len - filled - 1) if filled < bar_len else "=" * bar_len
            msg = (
                f"\r{_colored('进度:', Colors.CYAN)} [{bar_str}] "
                f"{processed}/{total} ({pct:.1f}%) | "
                f"{_colored('命中:', Colors.GREEN)} {_colored(str(matches_count), Colors.BOLD + Colors.GREEN)} 只 | "
                f"耗时: {elapsed:.1f}s | "
                f"速度: {speed:.1f} 股/s"
            )
            sys.stdout.write(msg)
            sys.stdout.flush()

    # 核心并发执行
    try:
        results = scan_market_strategy(
            strategy_name=strategy_name,
            symbols=symbols_to_scan,
            universe=universe_choice if not custom_symbols else "custom",
            period=period,
            lookback_bars=lookback_bars,
            use_cache=not force_refresh,
            force_refresh=force_refresh,
            progress_callback=progress_callback,
            stop_event=stop_event,
            max_workers=max_workers,
        )
    except Exception as e:
        print(_colored(f"\n[!] 选股执行异常: {e}", Colors.RED))
        results = []

    elapsed_total = time.time() - start_time
    print()  # 换行

    # 格式化打印结果表格
    print_results_table(results, strategy_name, period, universe_choice, elapsed_total, time_desc=time_desc)

    # 导出报表与同步缓存 (无论是否命中皆生成标准结构，确保 48 大策略系统直接无缝复用)
    csv_p, json_p = export_results(
        results, 
        strategy_name, 
        period, 
        universe_choice, 
        total_scanned=len(symbols_to_scan),
        lookback_bars=lookback_bars,
        time_desc=time_desc,
        start_date=start_date_str
    )
    print(_colored(f"[+] 选股结果报表与系统缓存已自动同步更新 (与 48 大策略选股系统完全一致):", Colors.BOLD + Colors.CYAN))
    if results:
        print(f"   CSV 报表 : {_colored(str(csv_p), Colors.GREEN)}")
    print(f"   JSON 数据: {_colored(str(json_p), Colors.GREEN)}")
    print(f"   磁盘缓存 : {_colored('data/screener_cache/ (48 大策略选股系统已可直接秒级复用)', Colors.YELLOW)}\n")


if __name__ == "__main__":
    main()
