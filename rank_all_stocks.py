"""全市场股票 4D 多智能体深度诊断打分与降序排名脚本"""

import concurrent.futures
import sys
import time
from pathlib import Path
import pandas as pd

# 1. 自动添加 easy_tdx 源码路径 (防止 ModuleNotFoundError)
src_path = Path(__file__).resolve().parent / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from easy_tdx.ai.agents.decision_agent import decision_agent
from easy_tdx.market_data import fetch_security_kline
from easy_tdx.screener.universe import get_universe_symbols
from easy_tdx.stock_lookup import get_stock_name


def score_single_stock(symbol: str) -> dict | None:
    """对单只股票获取 K 线并进行 4D 多智能体深度诊断打分"""
    try:
        clean_sym = (
            symbol.strip()
            .upper()
            .replace("SH", "")
            .replace("SZ", "")
            .replace("BJ", "")
            .replace(".", "")
        )
        if not clean_sym:
            return None
        if clean_sym.isdigit():
            clean_sym = clean_sym.zfill(6)

        # 获取近 60 日真实 TDX K 线数据
        df = fetch_security_kline(clean_sym, count=60)
        if df is None or df.empty or len(df) < 15:
            return None

        # 调用决策总监智能体进行 4D 评分
        res = decision_agent.analyze(clean_sym, df)
        ratings = res.get("ratings_4d", {})

        return {
            "代码": clean_sym,
            "名称": get_stock_name(clean_sym),
            "综合得分": res.get("overall_score", 0.0),
            "交易评级": res.get("signal_display", ""),
            "信号代码": res.get("signal", ""),
            "技术面分": ratings.get("technical", 0.0),
            "基本面分": ratings.get("fundamental", 0.0),
            "资金面分": ratings.get("capital_flow", 0.0),
            "情绪面分": ratings.get("sentiment", 0.0),
            "风控安全分": ratings.get("risk_safety", 0.0),
            "诊断结论": res.get("summary", ""),
        }
    except Exception as e:
        # 异常跳过
        return None


def run_market_4d_ranking(
    universe_type: str = "hs300", max_workers: int = 16
) -> pd.DataFrame:
    """全市场/指定股票池并发打分并按得分降序排列

    :param universe_type: 股票池选型 ('core' 核心159只, 'hs300' 沪深300, 'zz500' 中证500, 'all' 全市场5000+只)
    :param max_workers: 并发线程数 (推荐 16~32 线程)
    :return: 按综合得分降序排列的 DataFrame
    """
    print(
        f"🚀 开始加载【{universe_type}】股票池并启动 4D 多智能体并发诊断打分..."
    )
    start_time = time.time()

    # 获取标的列表
    symbols = get_universe_symbols(universe_type)
    print(f"📦 待打分标的总数: {len(symbols)} 只股票, 线程池配置: {max_workers} 线程")

    results = []
    completed_count = 0

    # 使用线程池并发抓取 K 线并打分
    with concurrent.futures.ThreadPoolExecutor(
        max_workers=max_workers
    ) as executor:
        future_to_sym = {
            executor.submit(score_single_stock, sym): sym for sym in symbols
        }

        for future in concurrent.futures.as_completed(future_to_sym):
            completed_count += 1
            if completed_count % 50 == 0 or completed_count == len(symbols):
                print(
                    f"进度: [{completed_count}/{len(symbols)}] ({completed_count / len(symbols) * 100:.1f}%)"
                )

            res = future.result()
            if res is not None:
                results.append(res)

    if not results:
        print("⚠️ 未获取到有效的打分结果")
        return pd.DataFrame()

    # 转为 DataFrame 并按 综合得分 降序排列
    df_rank = pd.DataFrame(results)
    df_rank.sort_values(by="综合得分", ascending=False, inplace=True)
    df_rank.reset_index(drop=True, inplace=True)
    df_rank.index += 1  # 排名从 1 开始
    df_rank.index.name = "排名"

    elapsed = time.time() - start_time
    print(
        f"\n✅ 诊断打分完成！共成功诊断 {len(df_rank)} 只股票，耗时: {elapsed:.2f} 秒\n"
    )

    return df_rank


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="全市场/指定股票池 4D 多智能体深度诊断打分与降序排名工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  python rank_all_stocks.py --help
  python rank_all_stocks.py -u hs300 -w 16
  python rank_all_stocks.py --universe all --workers 32 --top 50 --output result.csv
        """,
    )
    parser.add_argument(
        "-u",
        "--universe",
        type=str,
        default="hs300",
        choices=["core", "hs300", "zz500", "zz1000", "all"],
        help="股票池范围选择: core (核心龙头159只), hs300 (沪深300), zz500 (中证500), zz1000 (中证1000), all (全市场5000+只全量A股). 默认: hs300",
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=16,
        help="并发线程池大小 (推荐 16~32 线程). 默认: 16",
    )
    parser.add_argument(
        "-t",
        "--top",
        type=int,
        default=20,
        help="终端输出榜单显示的 Top N 股票数量. 默认: 20",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default="market_4d_ranking_result.csv",
        help="打分结果导出的 CSV 文件保存路径. 默认: market_4d_ranking_result.csv",
    )

    args = parser.parse_args()

    # 1. 运行打分与排序
    rank_df = run_market_4d_ranking(
        universe_type=args.universe, max_workers=args.workers
    )

    if not rank_df.empty:
        # 2. 打印得分最高的 Top N 股票
        top_n = min(args.top, len(rank_df))
        print(f"\n================ 🏆 4D 深度诊断得分最高 Top {top_n} 榜单 ================")
        cols_display = [
            "代码",
            "名称",
            "综合得分",
            "交易评级",
            "技术面分",
            "基本面分",
            "资金面分",
            "风控安全分",
        ]
        print(rank_df[cols_display].head(top_n).to_string())

        # 3. 导出完整排名为 CSV 文件 (为代码补齐 \t 防止 Excel 打开时丢失前导 0)
        export_df = rank_df.copy()
        export_df["代码"] = export_df["代码"].astype(str).str.zfill(6).apply(lambda x: f"\t{x}")
        export_df.to_csv(args.output, encoding="utf-8-sig")
        print(f"\n💾 完整打分排名结果已保存至本地文件: {args.output} (已完美解决 0 开头代码丢失前导 0 问题)")

