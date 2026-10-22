#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""全市场多策略多线程并发选股执行脚本 (run_screener.py)

功能特性：
1. 交互式菜单：按序号快速选择战略（策略）、周期、选股范围（支持直接回车默认运行）；
2. 默认模式：缠论三级联共振校验规则 (chanlun_resonance, ALL_CASCADE, 全市场全部股票 all, CPU最大线程数)；
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
from datetime import date
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
from easy_tdx.screener.universe import get_universe_symbols, get_universe_options, CORE_UNIVERSE


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
            elif name_code == "chanlun_strategy":
                tag = _colored(" [缠论主升3买 / 4级联]", Colors.BLUE + Colors.BOLD)
                print(f"  {_colored(f'[{seq:2d}]', Colors.YELLOW)} {name_code:24s} {disp_name}{tag}")
                print(f"       {_colored('└─ ' + desc, Colors.CYAN)}")
            else:
                print(f"  [{seq:2d}] {name_code:24s} {disp_name}  {Colors.RESET}({desc})")

    print("\n" + "=" * 80)
    prompt_txt = _colored("请输入策略序号 [1-54] (直接回车默认: 1. 缠论共振策略): ", Colors.BOLD + Colors.GREEN)
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
    """打印周期选项并提示选择（默认推荐 ALL_CASCADE 或 DAY）"""
    print("\n" + "=" * 80)
    print(_colored("【第二步：周期选择】请选择策略执行周期：", Colors.BOLD + Colors.CYAN))
    print("=" * 80)

    is_chanlun = "chanlun" in strategy_name

    if is_chanlun:
        periods = [
            ("ALL_CASCADE", "全级别三级联共振 (月周日+周日30M+日30M5F)", "【默认推荐】月周日大买+周日30M大买+日30M5F大买+5M2买"),
            ("DAY_30F_5F", "日 30F 5F 区间套", "日线大买+30F中枢承接+5M 2买"),
            ("WEEK_DAY_30F", "周 日 30F 区间套", "周线大买+日线稳健中枢+30M 1买"),
            ("MONTH_WEEK_DAY", "月 周 日 区间套", "超大级别月线大买+日线 1买"),
            ("30F_5F_1F", "30F 5F 1F 区间套", "超短日内高频 T+0 买卖点联动"),
        ]
        for seq, (p_code, p_name, p_desc) in enumerate(periods, 1):
            if seq == 1:
                print(f"  {_colored(f'[{seq}]', Colors.GREEN + Colors.BOLD)} {_colored(p_code, Colors.BOLD):18s} {p_name} {_colored('[默认推荐]', Colors.GREEN)}")
            else:
                print(f"  [{seq}] {p_code:18s} {p_name}")
            print(f"      {_colored('└─ ' + p_desc, Colors.CYAN)}")

        prompt_txt = _colored("\n请输入周期序号 [1-5] (直接回车默认: 1. ALL_CASCADE 全级别共振): ", Colors.BOLD + Colors.GREEN)
        choice = input(prompt_txt).strip()
        if not choice or choice == "1":
            return "ALL_CASCADE"
        if choice.isdigit() and 1 <= int(choice) <= len(periods):
            return periods[int(choice) - 1][0]
        for p_code, _, _ in periods:
            if choice.upper() == p_code:
                return p_code
        return "ALL_CASCADE"
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


def display_universe_menu() -> tuple[str, list[str] | None]:
    """打印选股范围选项并提示选择（默认 1: all 全市场全部股票）"""
    print("\n" + "=" * 80)
    print(_colored("【第三步：选股范围】请选择扫描范围（默认: 全市场全A股）：", Colors.BOLD + Colors.CYAN))
    print("=" * 80)

    options = [
        ("all", "全市场全A股 (5,200+ 只股票)", "全市场无死角多线程地毯式深度扫描", "【默认推荐】"),
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
    print(_colored("【第四步：多线程并发与缓存设置】", Colors.BOLD + Colors.CYAN))
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


def print_results_table(results: list[dict[str, Any]], strategy_name: str, period: str, universe: str, elapsed_sec: float) -> None:
    """以精美表格形式格式化输出最终选股命中结果"""
    print("\n" + "=" * 118)
    header_title = f"【选股完成】策略: {strategy_name} | 周期: {period} | 范围: {universe} | 命中: {len(results)} 只 | 耗时: {elapsed_sec:.2f}s"
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


def export_results(results: list[dict[str, Any]], strategy_name: str, period: str, universe: str, total_scanned: int = 0) -> tuple[Path, Path]:
    """将选股结果导出为 CSV 与 JSON 持久化报告，并同步写入 data/screener_cache 确保 48 大策略选股系统直接无缝复用"""
    output_dir = Path.cwd() / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    today_str = date.today().strftime("%Y%m%d")
    p_clean = str(period).strip().upper()
    base_name = f"screener_{strategy_name}_{universe}_{p_clean}_{today_str}"
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
    parser.add_argument("-s", "--strategy", type=str, default="", help="选股策略名称（默认: chanlun_resonance 缠论共振策略）")
    parser.add_argument("-p", "--period", type=str, default="", help="分析周期（默认: ALL_CASCADE 全级别共振 / DAY）")
    parser.add_argument("-u", "--universe", type=str, default="", help="选股范围：all/core/hs300/zz500/zz1000/代码列表（默认: all）")
    cpu_threads = max(1, os.cpu_count() or 4)
    parser.add_argument("-w", "--workers", type=int, default=0, help=f"并发线程数（默认: 当前CPU最大线程数 {cpu_threads}）")
    parser.add_argument("--refresh", action="store_true", help="强制从行情服务器穿透下载全量数据")
    parser.add_argument("--no-interactive", action="store_true", help="禁用交互式菜单，完全依靠命令行参数执行")

    args = parser.parse_args()

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

        # 3. 选股范围选择
        universe_choice, custom_symbols = display_universe_menu()

        # 4. 并发线程与缓存设置
        max_workers, force_refresh = display_concurrency_menu()
    else:
        strategy_name = args.strategy.strip() or "chanlun_resonance"
        period = args.period.strip() or ("ALL_CASCADE" if "chanlun" in strategy_name else "DAY")
        universe_choice = args.universe.strip() or "all"
        custom_symbols = None
        if "," in universe_choice:
            custom_symbols = [c.strip().zfill(6) for c in universe_choice.split(",") if c.strip()]
            universe_choice = "custom"
        max_workers = args.workers if args.workers > 0 else cpu_threads
        force_refresh = args.refresh

    # 解析标的股票列表
    if custom_symbols:
        symbols_to_scan = custom_symbols
        universe_desc = f"自定义 {len(symbols_to_scan)} 只"
    else:
        symbols_to_scan = get_universe_symbols(universe_choice)
        universe_desc = f"{universe_choice} ({len(symbols_to_scan)} 只)"

    print("\n" + "=" * 80)
    print(_colored(f"【准备就绪，开始多线程选股扫描】", Colors.BOLD + Colors.CYAN))
    print(f"● 选股策略: {_colored(strategy_name, Colors.GREEN + Colors.BOLD)} ({get_strategy(strategy_name).display_name})")
    print(f"● 执行周期: {_colored(period, Colors.GREEN)}")
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
            lookback_bars=22,
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
    print_results_table(results, strategy_name, period, universe_choice, elapsed_total)

    # 导出报表与同步缓存 (无论是否命中皆生成标准结构，确保 48 大策略系统直接无缝复用)
    csv_p, json_p = export_results(results, strategy_name, period, universe_choice, total_scanned=len(symbols_to_scan))
    print(_colored(f"[+] 选股结果报表与系统缓存已自动同步更新 (与 48 大策略选股系统完全一致):", Colors.BOLD + Colors.CYAN))
    if results:
        print(f"   CSV 报表 : {_colored(str(csv_p), Colors.GREEN)}")
    print(f"   JSON 数据: {_colored(str(json_p), Colors.GREEN)}")
    print(f"   磁盘缓存 : {_colored('data/screener_cache/ (48 大策略选股系统已可直接秒级复用)', Colors.YELLOW)}\n")


if __name__ == "__main__":
    main()
