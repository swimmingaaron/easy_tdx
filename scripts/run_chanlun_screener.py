#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自动化全市场/核心池缠论选股脚本 (无需人工干预)

选股策略: 缠论1/2/3类买卖点与笔背驰策略 (chanlun_strategy)
默认周期: 日 30F 5F (DAY_30F_5F)
筛选条件: 大周期日线出现大买 (大级别 1BUY/2BUY/3BUY)

使用方法:
    python scripts/run_chanlun_screener.py
    python scripts/run_chanlun_screener.py --universe hs300 --force-refresh
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# 保证 Windows 终端标准输出支持 UTF-8 汉字
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# 若当前运行未在虚拟环境中且存在项目本地 .venv，自动重定向到 .venv 中的 Python 执行
repo_root = Path(__file__).resolve().parent.parent
venv_py = repo_root / ".venv" / "Scripts" / "python.exe"
if not venv_py.exists():
    venv_py = repo_root / ".venv" / "bin" / "python"

if venv_py.exists() and Path(sys.executable).resolve() != venv_py.resolve() and "EASY_TDX_VENV_LAUNCHED" not in os.environ:
    os.environ["EASY_TDX_VENV_LAUNCHED"] = "1"
    res = subprocess.run([str(venv_py), __file__] + sys.argv[1:])
    sys.exit(res.returncode)

# 将项目 src 目录加入模块搜索路径
src_dir = repo_root / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from easy_tdx.screener.scanner import scan_market_strategy, parse_chanlun_screener_preset
from easy_tdx.screener.universe import get_universe_symbols


def setup_logger(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S"
    )


def format_amount_wan(val: float | None) -> str:
    if val is None or abs(val) < 0.001:
        return "--"
    val_yi = val / 1e8
    if abs(val_yi) >= 1.0:
        return f"{val_yi:+.2f}亿"
    val_wan = val / 1e4
    return f"{val_wan:+.1f}万"


def run_screener(
    universe: str = "core",
    period: str = "DAY_30F_5F",
    force_refresh: bool = False,
    output_dir: str | Path | None = None
) -> list[dict]:
    """执行缠论全自动选股并输出结构化结果。"""
    t0 = time.time()
    preset = parse_chanlun_screener_preset(period)
    symbols = get_universe_symbols(universe)

    print("=" * 90)
    print("【EasyTDX 自动化缠论选股运行终端】")
    print(f"  * 策略名称: 缠论1/2/3类买卖点与笔背驰策略 (chanlun_strategy)")
    print(f"  * 选股周期: {preset['label']} ({preset['desc']})")
    print(f"  * 立体组合: 大周期={preset['high_name']} ({preset['high_p']}) | 跨周期三级套={preset['periods']}")
    print(f"  * 股票池  : {universe} (共计 {len(symbols)} 只)")
    print(f"  * 刷新模式: {'强制刷新 (忽略缓存)' if force_refresh else '智能缓存加速'}")
    print(f"  * 启动时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 90)

    def on_progress(total: int, processed: int, matched_cnt: int, pct: float):
        if total <= 200 or processed % 50 == 0 or processed == total:
            print(f"\r[扫描进度] {processed}/{total} ({pct:.1f}%) | 已捕获大买标的: {matched_cnt} 只", end="", flush=True)

    print("\n正在启动多线程高并发选股引擎，请稍候...\n")
    matches = scan_market_strategy(
        strategy_name="chanlun_strategy",
        universe=universe,
        period=period,
        lookback_bars=20,
        use_cache=True,
        force_refresh=force_refresh,
        progress_callback=on_progress
    )
    print("\n")

    cost_sec = time.time() - t0

    # 结果按日期倒序、主力资金流入降序排序
    matches.sort(
        key=lambda x: (
            str(x.get("trigger_date", "")),
            float(x.get("main_net_amount") or 0.0),
            float(x.get("amount_wan") or 0.0)
        ),
        reverse=True
    )

    # 打印格式化表格
    print("=" * 110)
    print(f"【选股结果报告】共扫描 {len(symbols)} 只标的，成功捕获 {len(matches)} 只符合【{preset['label']}】大买条件的优质标的 (耗时: {cost_sec:.2f}s)")
    print("=" * 110)

    header = f"{'序号':<4} | {'代码':<6} | {'股票名称':<8} | {'触发价':<7} | {'触发涨跌':<8} | {'缠论信号标签':<18} | {'触发日期':<10} | {'主力净流入(1D)':<12} | {'形态特征 (当日/自触发/触发日及形态)'}"
    print(header)
    print("-" * 130)

    if not matches:
        print("  当前未扫描到符合大周期大买信号的个股，建议扩大股票池或盘中实时监控。")
    else:
        for idx, m in enumerate(matches, 1):
            code = m.get("symbol") or m.get("code") or ""
            name = (m.get("name") or "")[:6]
            price = f"{float(m.get('price') or 0.0):.2f}"
            chg = f"{float(m.get('change_pct') or 0.0):+.2f}%"
            status = m.get("status_label") or "大买信号"
            dt = m.get("trigger_date") or m.get("signal_date") or "--"
            net_amt = m.get("main_net_amount")
            net_str = format_amount_wan(net_amt) if net_amt is not None else "--"
            
            # 形态特征列：增加当日涨幅、自触发涨幅、当日形态特征、触发日及形态特征
            days = m.get("days_ago") or 0
            latest_chg = m.get("latest_change_pct") if m.get("latest_change_pct") is not None else float(m.get("change_pct") or 0.0)
            since_chg = float(m.get("since_signal_pct") or 0.0)
            latest_pat = m.get("latest_pattern_status") or m.get("pattern_status") or "--"
            trig_pat = m.get("trigger_pattern_status") or m.get("pattern_status") or "--"
            trig_dt = str(m.get("trigger_date") or m.get("signal_date") or "--")[:10]
            if days == 0:
                pat = f"当日:{latest_chg:+.2f}% | 今日触发 | 形态:{latest_pat}"
            else:
                pat = f"当日:{latest_chg:+.2f}%(形态:{latest_pat}) 自触发:{since_chg:+.2f}% | 触发:{trig_dt}({days}天前,形态:{trig_pat})"
            print(f"{idx:<4} | {code:<6} | {name:<8} | {price:<7} | {chg:<8} | {status:<18} | {dt:<10} | {net_str:<12} | {pat}")

    print("-" * 130)

    # 保存结果到本地文件 (JSON + CSV)
    if output_dir is None:
        output_dir = repo_root / "output"
    else:
        output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    today_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"chanlun_screener_{universe}_{preset['key']}_{today_str}.json"
    latest_json = output_dir / "chanlun_screener_latest.json"
    csv_path = output_dir / f"chanlun_screener_{universe}_{preset['key']}_{today_str}.csv"
    latest_csv = output_dir / "chanlun_screener_latest.csv"

    report_payload = {
        "strategy": "chanlun_strategy",
        "strategy_name": "缠论1/2/3类买卖点与笔背驰策略",
        "universe": universe,
        "period": period,
        "period_preset": preset["key"],
        "period_label": preset["label"],
        "high_period": preset["high_period"],
        "periods_triplet": preset["periods"],
        "scanned_total": len(symbols),
        "matches_count": len(matches),
        "execution_time_sec": round(cost_sec, 2),
        "timestamp": datetime.now().isoformat(),
        "matches": matches
    }

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report_payload, f, ensure_ascii=False, indent=2)
    with open(latest_json, "w", encoding="utf-8") as f:
        json.dump(report_payload, f, ensure_ascii=False, indent=2)

    # 导出 CSV 便于 Excel 打开研判
    try:
        import pandas as pd
        if matches:
            export_cols = [
                "symbol", "name", "price", "change_pct", "latest_change_pct", "since_signal_pct",
                "status_label", "trigger_date", "days_ago", "volume", "amount_wan", 
                "pattern_status", "trigger_pattern_status", "pattern_full_desc"
            ]
            df = pd.DataFrame(matches)
            sub_cols = [c for c in export_cols if c in df.columns]
            df[sub_cols].to_csv(csv_path, index=False, encoding="utf-8-sig")
            df[sub_cols].to_csv(latest_csv, index=False, encoding="utf-8-sig")
    except Exception as e:
        pass

    print(f"\n[结果已持久化保存]")
    print(f"  * JSON结果: {json_path}")
    print(f"  * 最新快捷: {latest_json}")
    if csv_path.exists():
        print(f"  * CSV表格 : {csv_path}")
        print(f"  * 最新表格: {latest_csv}")
    print("=" * 110 + "\n")

    return matches


def main():
    parser = argparse.ArgumentParser(description="自动执行缠论选股并输出结果 (无需人工选择或干预)")
    parser.add_argument(
        "--universe", "-u",
        default="core",
        choices=["core", "hs300", "zz500", "zz1000", "all"],
        help="选股股票池 (默认: core 核心龙头池 159只)"
    )
    parser.add_argument(
        "--period", "-p",
        default="DAY_30F_5F",
        choices=["DAY_30F_5F", "30F_5F_1F", "WEEK_DAY_30F", "MONTH_WEEK_DAY"],
        help="缠论级联周期 (默认: DAY_30F_5F 日 30F 5F 大周期日线大买)"
    )
    parser.add_argument(
        "--force-refresh", "-f",
        action="store_true",
        help="强制绕过本地缓存重新拉取行情扫描"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="输出详细调试日志"
    )
    args = parser.parse_args()

    setup_logger(args.verbose)
    run_screener(
        universe=args.universe,
        period=args.period,
        force_refresh=args.force_refresh
    )


if __name__ == "__main__":
    main()
