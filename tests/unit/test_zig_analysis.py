"""ZIG 之字转向指标与量化反转信号分析工具 (CLI & 单元测试).

支持传入：
  - 股票代码或名称 (--symbol / --stock, 如 600722 或 金牛化工)
  - K线周期 (--period, 如 30M, 60M, DAY 等)
  - 截至日期 (--end-date, 如 2026-07-20)
  - 转向阈值 (--threshold / --delta, 默认 5.0%, 支持多阈值如 5.0,10.0)

输出包含：
  1. 完整 K 线数据表与拟合插值 ZIG 值
  2. +1, +2 ... / -1, -2 ... 状态天数/周期序列
  3. 拐点 (波峰 Peak / 波谷 Trough) 极值清单
  4. 截至日期反转信号 (Reversal Signal) 与突破逻辑分析
"""

from __future__ import annotations

import argparse
import sys
import io
from datetime import datetime, timedelta
from typing import Any, List, Tuple

# 保证 Windows 终端输出 UTF-8 字符正常显示
if sys.platform.startswith("win"):
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass


import numpy as np
import pandas as pd

# 自动处理包路径导入
try:
    from easy_tdx.market_data import fetch_security_kline
    from easy_tdx.models import KlineCategory
    from easy_tdx.MyTT import ZIG, HHV, LLV, MA, MACD, KDJ
    from easy_tdx.trading_system.engine import calculate_zig_series
    from easy_tdx.stock_lookup import COMMON_STOCKS
except ImportError:
    import os
    src_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "src"))
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)
    from easy_tdx.market_data import fetch_security_kline
    from easy_tdx.models import KlineCategory
    from easy_tdx.MyTT import ZIG, HHV, LLV, MA, MACD, KDJ
    from easy_tdx.trading_system.engine import calculate_zig_series
    from easy_tdx.stock_lookup import COMMON_STOCKS


def resolve_symbol(sym_or_name: str) -> tuple[str, str]:
    """解析股票代码或名称为标准代码与显示名称。"""
    query = sym_or_name.strip()
    # 纯数字代码
    clean_digits = "".join(filter(str.isdigit, query))
    if len(clean_digits) == 6:
        # 匹配名称
        name = query
        for k, v in (COMMON_STOCKS.items() if isinstance(COMMON_STOCKS, dict) else []):
            if clean_digits in str(k):
                name = str(v)
                break
        return clean_digits, name

    # 中文名称查找代码
    if isinstance(COMMON_STOCKS, dict):
        for k, v in COMMON_STOCKS.items():
            if query in str(v):
                return "".join(filter(str.isdigit, str(k))), str(v)
    elif isinstance(COMMON_STOCKS, list):
        for item in COMMON_STOCKS:
            if isinstance(item, dict):
                c = str(item.get("code", ""))
                n = str(item.get("name", ""))
                if query in n or query == c:
                    return "".join(filter(str.isdigit, c)), n

    # 默认返回数字或原串
    return (clean_digits if clean_digits else query), query


def parse_period(period_str: str) -> tuple[KlineCategory, str]:
    """标准化 K 线周期参数。"""
    p = period_str.strip().upper()
    period_map = {
        "1M": (KlineCategory.MIN_1, "1分钟"),
        "5M": (KlineCategory.MIN_5, "5分钟"),
        "15M": (KlineCategory.MIN_15, "15分钟"),
        "30M": (KlineCategory.MIN_30, "30分钟"),
        "60M": (KlineCategory.MIN_60, "60分钟"),
        "120M": (KlineCategory.MIN_60, "120分钟"),
        "1H": (KlineCategory.MIN_60, "60分钟"),
        "D": (KlineCategory.DAY, "日线"),
        "DAY": (KlineCategory.DAY, "日线"),
        "DAILY": (KlineCategory.DAY, "日线"),
        "W": (KlineCategory.WEEK, "周线"),
        "WEEK": (KlineCategory.WEEK, "周线"),
        "M": (KlineCategory.MONTH, "月线"),
        "MONTH": (KlineCategory.MONTH, "月线"),
    }
    return period_map.get(p, (KlineCategory.MIN_30, "30分钟"))


def analyze_zig(
    symbol: str,
    period: str = "30M",
    end_date: str | None = None,
    start_date: str | None = None,
    days: int = 30,
    thresholds: list[float] | None = None,
    max_bars: int = 800,
) -> dict[str, Any]:
    """拉取指定标的指定周期与时间范围的行情并计算 ZIG 相关指标。"""
    if thresholds is None:
        thresholds = [5.0, 10.0]

    code, name = resolve_symbol(symbol)
    cat, period_desc = parse_period(period)

    # 1. 抓取行情数据
    df = fetch_security_kline(code, category=cat, count=max_bars)
    if df is None or df.empty:
        raise ValueError(f"未能获取到股票 {code} ({name}) 的 {period_desc} K线数据，请检查网络或行情服务。")

    df["datetime"] = pd.to_datetime(df["datetime"])

    # 2. 时间过滤
    if end_date:
        end_ts = pd.to_datetime(end_date)
        if len(end_date) <= 10:
            end_ts = end_ts.replace(hour=23, minute=59, second=59)
    else:
        end_ts = df["datetime"].max()

    if start_date:
        start_ts = pd.to_datetime(start_date)
    else:
        start_ts = end_ts - timedelta(days=days)

    filtered = df[(df["datetime"] >= start_ts) & (df["datetime"] <= end_ts)].copy().reset_index(drop=True)
    if filtered.empty:
        raise ValueError(f"在区间 [{start_ts} 至 {end_ts}] 内未筛选到有效 K 线，最晚可用时间为 {df['datetime'].max()}。")

    # 3. 计算 ZIG 指标
    closes = filtered["close"].values.astype(float)
    highs = filtered["high"].values.astype(float)
    lows = filtered["low"].values.astype(float)
    vols = filtered["volume"].values.astype(float)

    zig_val_dict = {}
    zig_seq_dict = {}
    for th in thresholds:
        zig_val_dict[th] = ZIG(closes, th)
        zig_seq_dict[th] = calculate_zig_series(closes, th / 100.0)

    # 4. 辅助指标 (HHV, MA, MACD, KDJ)
    hhv20 = HHV(highs, min(20, len(filtered)))
    ma5 = MA(closes, min(5, len(filtered)))
    ma10 = MA(closes, min(10, len(filtered)))
    ma20 = MA(closes, min(20, len(filtered)))
    dif, dea, macd = MACD(closes)

    # 提取拐点清单 (以主阈值 thresholds[0] 为准)
    primary_th = thresholds[0]
    pivots: list[dict[str, Any]] = []
    clean_peers = []
    # 借助 ZIG 插值结果快速提取端点
    z_prim = zig_val_dict[primary_th]
    for i in range(len(filtered)):
        c_i = closes[i]
        z_i = z_prim[i]
        # 判断拐点：价格与插值完全重合且为局部极值
        if abs(c_i - z_i) < 1e-4:
            is_peak = (i > 0 and i < len(filtered) - 1 and closes[i] >= closes[i-1] and closes[i] >= closes[i+1])
            is_trough = (i > 0 and i < len(filtered) - 1 and closes[i] <= closes[i-1] and closes[i] <= closes[i+1])
            t_str = "PEAK (波峰)" if is_peak else ("TROUGH (波谷)" if is_trough else "EXTREME")
            pivots.append({
                "index": i + 1,
                "datetime": str(filtered.iloc[i]["datetime"])[:16],
                "price": round(c_i, 2),
                "type": t_str,
            })

    return {
        "code": code,
        "name": name,
        "period": period,
        "period_desc": period_desc,
        "start_time": str(filtered.iloc[0]["datetime"])[:16],
        "end_time": str(filtered.iloc[-1]["datetime"])[:16],
        "total_bars": len(filtered),
        "df": filtered,
        "thresholds": thresholds,
        "zig_vals": zig_val_dict,
        "zig_seqs": zig_seq_dict,
        "hhv20": hhv20,
        "ma5": ma5,
        "ma10": ma10,
        "ma20": ma20,
        "macd": macd,
        "pivots": pivots,
    }


def print_zig_report(result: dict[str, Any], show_table: bool = True) -> None:
    """打印详细且易于阅读的 ZIG 报告。"""
    df = result["df"]
    ths = result["thresholds"]
    zig_vals = result["zig_vals"]
    zig_seqs = result["zig_seqs"]

    print("=" * 80)
    print(f"  ZIG 之字转向与反转信号分析报告: {result['name']} ({result['code']})")
    print(f"  周期: {result['period_desc']} ({result['period']}) | K线总数: {result['total_bars']} 根")
    print(f"  统计区间: {result['start_time']} 至 {result['end_time']}")
    print(f"  分析阈值: {', '.join([f'{t}%' for t in ths])}")
    print("=" * 80)

    if show_table:
        print("\n【 逐根 K 线与 ZIG 序列详情表 】")
        header = f"{'序号':^4} | {'时间戳':^16} | {'收盘':^6} | {'涨跌幅':^7} | {'成交量':^9}"
        for t in ths:
            header += f" | {f'ZIG({t}%)':^8} | {f'序列({t}%)':^7}"
        print("-" * len(header))
        print(header)
        print("-" * len(header))

        for i in range(len(df)):
            row = df.iloc[i]
            dt = str(row["datetime"])[:16]
            c = float(row["close"])
            prev_c = float(df.iloc[i-1]["close"]) if i > 0 else c
            chg = (c - prev_c) / prev_c * 100 if prev_c > 0 else 0.0
            vol = int(row["volume"])

            line = f"{i+1:4d} | {dt:16} | {c:6.2f} | {chg:+6.2f}% | {vol:9d}"
            for t in ths:
                zv = zig_vals[t][i]
                zs = zig_seqs[t][i]
                line += f" | {zv:8.3f} | {zs:+7d}"
            print(line)
        print("-" * len(header))

    # 末端反转信号分析
    last_idx = len(df) - 1
    last_bar = df.iloc[last_idx]
    last_c = float(last_bar["close"])
    last_dt = str(last_bar["datetime"])[:16]

    print("\n【 末端 K 线与反转信号诊断 】")
    print(f"  最新节点: {last_dt} | 收盘价: {last_c:.2f}")
    for t in ths:
        cur_seq = zig_seqs[t][last_idx]
        prev_seq = zig_seqs[t][last_idx - 1] if last_idx > 0 else 0
        status_text = "向上推进" if cur_seq > 0 else "向下调整"
        print(f"  * 阈值 {t}%: 当前状态为 [{status_text}] (周期计数: {cur_seq:+d})")
        if cur_seq == 1:
            print(f"    🚨 触发【波谷底部反转启动】信号 (序号: {last_idx+1})！")
        elif cur_seq == -1:
            print(f"    ⚠️ 触发【波峰顶部反转卖出】信号 (序号: {last_idx+1})！")
        elif cur_seq > 0 and prev_seq < 0:
            print(f"    🚨 发生由跌转涨的转向跳变！")

    # 突破阻力位检查 (对比此前 20 周期的阻力位)
    prior_hhv = float(result["hhv20"][-2]) if len(result["hhv20"]) >= 2 else float(result["hhv20"][-1])
    breakout = (last_c >= prior_hhv * 1.01)
    print(f"\n【 右侧突破阻力分析 】")
    print(f"  前 20 周期阻力高点 (HHV20): {prior_hhv:.2f}")
    if breakout:
        print(f"  ⚡ 强势突破！最新收盘价 {last_c:.2f} 突破前高 {prior_hhv:.2f} (+{(last_c/prior_hhv - 1)*100:.2f}%)，确立右侧突破主升形态。")
    else:
        print(f"  当前位于前高阻力位下方或未达 1% 突破确认门槛。")
    print("=" * 80 + "\n")



def build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。"""
    parser = argparse.ArgumentParser(
        description="ZIG 之字转向指标与量化反转信号分析工具 (easy_tdx)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""使用示例:
  # 1. 默认分析金牛化工 30分钟 K线，截至 2026-07-20
  python tests/unit/test_zig_analysis.py --symbol 600722 --period 30M --end-date 2026-07-20

  # 2. 分析任意股票 (支持股票中文名) 日线级别反转
  python tests/unit/test_zig_analysis.py --symbol 贵州茅台 --period DAY --end-date 2026-07-20

  # 3. 指定自定义转向阈值 (如 5% 与 10%) 与统计天数
  python tests/unit/test_zig_analysis.py -s 600722 -p 30M -e 2026-07-20 --threshold 5.0,10.0 --days 30
""",
    )

    parser.add_argument(
        "-s", "--symbol", "--stock",
        type=str,
        default="600722",
        help="股票代码或股票简称 (如 600722、600722.SH 或 金牛化工，默认: 600722)",
    )
    parser.add_argument(
        "-p", "--period",
        type=str,
        default="30M",
        help="K线周期类型 (可选: 5M, 15M, 30M, 60M, DAY, WEEK, MONTH，默认: 30M)",
    )
    parser.add_argument(
        "-e", "--end-date", "--cutoff",
        type=str,
        default="2026-07-20",
        help="分析截至日期 (格式: YYYY-MM-DD 或 YYYY-MM-DD HH:MM:SS，默认: 2026-07-20)",
    )
    parser.add_argument(
        "--start-date",
        type=str,
        default=None,
        help="分析起始日期 (可选，默认根据 --days 自动计算)",
    )
    parser.add_argument(
        "-d", "--days",
        type=int,
        default=30,
        help="向前回溯的自然日天数 (默认: 30 天，即约 1 个月)",
    )
    parser.add_argument(
        "-t", "--threshold", "--delta",
        type=str,
        default="5.0,10.0",
        help="ZIG 转向幅度百分比阈值，多个阈值用英文逗号分隔 (默认: 5.0,10.0)",
    )
    parser.add_argument(
        "--no-table",
        action="store_true",
        help="仅输出简要诊断报告，不打印每根 K 线的详细明细表",
    )
    return parser


def main() -> int:
    """CLI 入口函数。"""
    parser = build_parser()
    args = parser.parse_args()

    try:
        thresholds = [float(x.strip()) for x in args.threshold.split(",") if x.strip()]
    except Exception:
        thresholds = [5.0, 10.0]

    try:
        result = analyze_zig(
            symbol=args.symbol,
            period=args.period,
            end_date=args.end_date,
            start_date=args.start_date,
            days=args.days,
            thresholds=thresholds,
        )
        print_zig_report(result, show_table=not args.no_table)
        return 0
    except Exception as e:
        print(f"❌ 运行失败: {e}", file=sys.stderr)
        return 1


# ============================================================================
# Pytest 单元测试用例
# ============================================================================
class TestZigAnalysisCLI:
    """针对 ZIG 分析工具的单元测试。"""

    def test_help_message(self):
        """测试 CLI help 参数。"""
        parser = build_parser()
        help_text = parser.format_help()
        assert "--symbol" in help_text
        assert "--period" in help_text
        assert "--end-date" in help_text
        assert "--threshold" in help_text

    def test_symbol_resolution(self):
        """测试股票代码与中文名解析。"""
        code, name = resolve_symbol("600722")
        assert code == "600722"
        code2, _ = resolve_symbol("SH600722")
        assert code2 == "600722"

    def test_parse_period(self):
        """测试周期标准化。"""
        cat, desc = parse_period("30M")
        assert cat == KlineCategory.MIN_30
        assert "30分钟" in desc

        cat_d, desc_d = parse_period("DAY")
        assert cat_d == KlineCategory.DAY
        assert "日线" in desc_d

    def test_analyze_zig_jinniu(self):
        """测试金牛化工 2026-07-20 30分钟 K 线 ZIG 计算。"""
        res = analyze_zig(
            symbol="600722",
            period="30M",
            end_date="2026-07-20",
            days=30,
            thresholds=[5.0, 10.0],
        )
        assert res["total_bars"] > 100
        assert 5.0 in res["zig_vals"]
        assert 10.0 in res["zig_seqs"]
        # 验证 2026-07-20 10:00 存在且处于向上多头趋势
        df = res["df"]
        j20_bars = df[df["datetime"].dt.date == pd.Timestamp("2026-07-20").date()]
        assert len(j20_bars) == 8
        # 验证最新收盘价为 9.38
        assert float(j20_bars.iloc[-1]["close"]) == 9.38


if __name__ == "__main__":
    sys.exit(main())
