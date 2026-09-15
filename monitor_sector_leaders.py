#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
easy_tdx 板块龙头股票实时监测脚本 (Sector Leader Stocks Monitor)
================================================================

基于 easy_tdx 原生通达信行情链路，实时监测 A 股全市场领涨行业与概念板块，
并秒级识别各个强势板块的「领涨先锋」、「容量中军」与「短线连板龙头」。

功能特性：
1. 自动优选通达信低延迟行情主站 (MacClient.from_best_host)
2. 支持监测 行业板块 (HY) 与 概念板块 (GN)，或指定特定板块深度追踪
3. 多维龙头量化识别：
   - 👑 领涨先锋龙头：板块内涨幅第一/最先触板，带领板块情绪上攻
   - 🛡️ 容量中军龙头：板块内成交额最大且承接巨额主力资金的核心支柱
   - 🔥 连板高度龙头：板块内连板数最高、最具辨识度的短线龙头标杆
   - 🏆 综合龙头打分：结合涨幅、主力资金净流、成交规模、量比的多因子评级
4. 支持单次扫描输出与实时动态轮询 (--loop / -l)
5. 支持导出为 CSV 或 JSON 数据

使用示例：
    # 1. 扫描当前全市场领涨行业板块龙头 (单次输出)
    python monitor_sector_leaders.py

    # 2. 监测概念板块领涨龙头，取前 15 个强势板块
    python monitor_sector_leaders.py --type gn --top-boards 15

    # 3. 启动实时监控循环，每 5 秒刷新一次
    python monitor_sector_leaders.py --loop --interval 5

    # 4. 指定监控单个板块（支持板块名称或板块代码）
    python monitor_sector_leaders.py --board 半导体
    python monitor_sector_leaders.py --board 881094

    # 5. 导出监测结果到 CSV
    python monitor_sector_leaders.py --output output/sector_leaders.csv
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# 1. 确保标准输出为 UTF-8，杜绝 Windows 控制台中文乱码
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# 2. 自动配置 easy_tdx 导入路径
_ROOT = Path(__file__).resolve().parent
_SRC = _ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

try:
    from easy_tdx import MacClient
    from easy_tdx.mac.enums import BoardType, SortOrder, SortType
    from easy_tdx.market_ladder import compute_exact_tdx_lbc
    from easy_tdx.stock_lookup import get_stock_name
except ImportError as e:
    print(f"[错误] 导入 easy_tdx 失败: {e}", file=sys.stderr)
    print("请确认已安装 easy_tdx 或在仓库根目录执行此脚本。", file=sys.stderr)
    sys.exit(1)

logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("monitor_sector_leaders")


def _is_limit_up(code: str, price: float, pre_close: float) -> bool:
    """判定股票是否触及涨停板。"""
    if pre_close <= 0 or price <= 0:
        return False
    pct = (price - pre_close) / pre_close * 100.0
    clean = code.strip().upper().replace("SH", "").replace("SZ", "").replace("BJ", "")
    if clean.startswith(("30", "68")):
        zt_p = round(pre_close * 1.20, 2)
        return pct >= 19.8 or price >= zt_p - 0.01
    elif clean.startswith(("92", "8", "4")):
        zt_p = round(pre_close * 1.30, 2)
        return pct >= 29.5 or price >= zt_p - 0.01
    else:
        zt_p = round(pre_close * 1.10, 2)
        return pct >= 9.8 or price >= zt_p - 0.01


def _fmt_money(val: float) -> str:
    """格式化金额（元 -> 亿/万）。"""
    if abs(val) >= 1e8:
        return f"{val / 1e8:+.2f}亿" if val != 0 else "0.00亿"
    elif abs(val) >= 1e4:
        return f"{val / 1e4:+.1f}万"
    return f"{val:+.0f}元"


def _fmt_amt(val: float) -> str:
    """格式化绝对成交额。"""
    if val >= 1e8:
        return f"{val / 1e8:.2f}亿"
    elif val >= 1e4:
        return f"{val / 1e4:.1f}万"
    return f"{val:.0f}元"


class SectorLeaderMonitor:
    """板块龙头股票监测引擎。"""

    def __init__(self, client: Optional[MacClient] = None):
        self._external_client = client

    def get_client(self) -> MacClient:
        """获取或创建通达信客户端连接。"""
        if self._external_client is not None:
            return self._external_client
        return MacClient.from_best_host()

    def fetch_top_boards(
        self,
        board_type: BoardType = BoardType.HY,
        top_n: int = 10,
        sort_by: str = "change_pct",
    ) -> List[Dict[str, Any]]:
        """获取全市场涨幅或资金排名前 N 的板块列表。"""
        with self.get_client() as c:
            df = c.get_board_ranking(board_type, top_n=top_n, sort_by=sort_by)
            if df is None or df.empty:
                return []
            return df.to_dict(orient="records")

    def search_board(self, query: str) -> Optional[Dict[str, Any]]:
        """按板块名称或代码搜索匹配的板块。"""
        q = query.strip().upper()
        with self.get_client() as c:
            for b_type in [BoardType.HY, BoardType.GN]:
                df = c.get_board_ranking(b_type, top_n=400, sort_by="change_pct")
                if df is None or df.empty:
                    continue
                for _, row in df.iterrows():
                    code_str = str(row.get("code", "")).strip()
                    name_str = str(row.get("name", "")).strip()
                    if q == code_str or q in name_str or name_str in q:
                        d = row.to_dict()
                        d["board_type"] = "行业" if b_type == BoardType.HY else "概念"
                        return d
        return None

    def analyze_board_leaders(
        self,
        board_code: str,
        board_name: str = "",
        top_candidates: int = 5,
    ) -> Dict[str, Any]:
        """
        深度分析指定板块，评选板块内的龙头股票矩阵。

        返回字典结构：
        - board_code: 板块代码
        - board_name: 板块名称
        - members_count: 成分股总数
        - leader_pioneer: 领涨先锋 (涨幅最大/触板龙头)
        - leader_capacity: 容量中军 (成交额最大/主力流入最大)
        - leader_ladder: 连板高度龙 (连板数最高)
        - candidates: 排序后的龙头候选列表
        """
        clean_board_code = str(board_code).strip()
        with self.get_client() as c:
            # 抓取成分股（按涨幅降序排列，取前 30 只作为备选池以准确找到中军与先锋）
            df_members = c.get_board_members(
                clean_board_code,
                count=30,
                sort_type=SortType.CHANGE_PCT,
                sort_order=SortOrder.DESC,
            )

        if df_members is None or df_members.empty:
            return {
                "board_code": clean_board_code,
                "board_name": board_name,
                "members_count": 0,
                "leader_pioneer": None,
                "leader_capacity": None,
                "leader_ladder": None,
                "candidates": [],
            }

        candidates = []
        max_amount = df_members["amount"].max() if "amount" in df_members else 1.0
        max_amount = max(1.0, float(max_amount))

        for idx, row in df_members.iterrows():
            code = str(row.get("code", "")).zfill(6)
            name = get_stock_name(code)
            if not name or name.startswith("标的_"):
                name = str(row.get("name", "")).strip() or code

            price = float(row.get("close", 0.0))
            pre_close = float(row.get("pre_close", 0.0))
            change_pct = ((price - pre_close) / pre_close * 100.0) if pre_close > 0 else 0.0
            amount = float(row.get("amount", 0.0))
            main_net = float(row.get("main_net_amount", 0.0))
            vol_ratio = float(row.get("vol_ratio", 1.0))
            turnover = float(row.get("turnover", 0.0))

            is_zt = _is_limit_up(code, price, pre_close)
            lbc = compute_exact_tdx_lbc(code) if (is_zt or change_pct >= 8.0) else 0

            # 计算龙头得分 (Leader Score, 0 ~ 100)
            # 1. 涨幅贡献 (0~35分)
            score_pct = min(35.0, max(0.0, (change_pct / 10.0) * 17.5))
            if change_pct >= 9.8:
                score_pct = 35.0

            # 2. 主力资金流入贡献 (0~25分)
            # 净流入 >= 2亿给满分25，负流入递减
            net_yi = main_net / 1e8
            if net_yi >= 2.0:
                score_flow = 25.0
            elif net_yi > 0:
                score_flow = 10.0 + (net_yi / 2.0) * 15.0
            else:
                score_flow = max(0.0, 10.0 + net_yi * 5.0)

            # 3. 容量中军流动性贡献 (0~20分)
            # 成交额占板块龙头备选池比例
            score_amt = min(20.0, (amount / max_amount) * 20.0)

            # 4. 活跃度与量比贡献 (0~10分)
            score_active = min(10.0, max(2.0, (vol_ratio / 2.0) * 5.0 + min(5.0, turnover / 3.0)))

            # 5. 涨停与连板溢价加分 (0~10分)
            score_bonus = 0.0
            if is_zt:
                score_bonus += 5.0
            if lbc > 1:
                score_bonus += min(5.0, (lbc - 1) * 2.0)

            leader_score = round(score_pct + score_flow + score_amt + score_active + score_bonus, 1)

            stock_info = {
                "code": code,
                "name": name,
                "price": price,
                "pre_close": pre_close,
                "change_pct": round(change_pct, 2),
                "amount": amount,
                "main_net_amount": main_net,
                "vol_ratio": round(vol_ratio, 2),
                "turnover": round(turnover, 2),
                "is_zt": is_zt,
                "lbc": lbc,
                "leader_score": leader_score,
                "role_tag": "领涨个股",
            }
            candidates.append(stock_info)

        # 确定各细分龙头角色
        # 1. 先锋龙头 (涨幅第一且触板优先)
        candidates.sort(key=lambda x: (x["is_zt"], x["change_pct"], x["amount"]), reverse=True)
        pioneer = candidates[0] if candidates else None

        # 2. 容量中军 (成交额 >= 3亿 且金额最高者)
        by_amount = sorted(candidates, key=lambda x: x["amount"], reverse=True)
        capacity = by_amount[0] if by_amount and by_amount[0]["amount"] >= 2e8 else None

        # 3. 连板高度龙 (连板数 >= 2 且最高)
        by_lbc = sorted(candidates, key=lambda x: x["lbc"], reverse=True)
        ladder = by_lbc[0] if by_lbc and by_lbc[0]["lbc"] >= 2 else None

        # 为各候选股标注角色
        for s in candidates:
            tags = []
            if pioneer and s["code"] == pioneer["code"]:
                tags.append("👑 领涨先锋")
            if capacity and s["code"] == capacity["code"]:
                tags.append("🛡️ 容量中军")
            if ladder and s["code"] == ladder["code"]:
                tags.append(f"🔥 {ladder['lbc']}连板龙头")
            elif s["is_zt"]:
                tags.append("涨停标杆")
            elif s["change_pct"] >= 7.0:
                tags.append("前排冲锋")
            elif s["vol_ratio"] >= 2.0:
                tags.append("放量突破")

            s["role_tag"] = " | ".join(tags) if tags else "跟随标的"

        # 按综合龙头得分重新对候选股排序输出
        candidates.sort(key=lambda x: x["leader_score"], reverse=True)

        return {
            "board_code": clean_board_code,
            "board_name": board_name,
            "members_count": len(df_members),
            "leader_pioneer": pioneer,
            "leader_capacity": capacity,
            "leader_ladder": ladder,
            "candidates": candidates[:top_candidates],
        }

    def scan_all_leaders(
        self,
        board_type: BoardType = BoardType.HY,
        top_boards: int = 10,
        top_stocks_per_board: int = 3,
    ) -> List[Dict[str, Any]]:
        """全流程扫描排名前 N 的板块及其龙头股票。"""
        boards = self.fetch_top_boards(board_type=board_type, top_n=top_boards)
        results = []
        for b in boards:
            b_code = str(b.get("code", ""))
            b_name = str(b.get("name", ""))
            b_pct = float(b.get("change_pct", 0.0))
            b_amt = float(b.get("amount", 0.0))
            b_net = float(b.get("main_net_amount", 0.0))
            b_up = int(b.get("up_count", 0))
            b_down = int(b.get("down_count", 0))

            analysis = self.analyze_board_leaders(
                board_code=b_code,
                board_name=b_name,
                top_candidates=top_stocks_per_board,
            )
            analysis["change_pct"] = b_pct
            analysis["amount"] = b_amt
            analysis["main_net_amount"] = b_net
            analysis["up_count"] = b_up
            analysis["down_count"] = b_down
            results.append(analysis)
        return results


def print_screen_table(results: List[Dict[str, Any]], title_suffix: str = ""):
    """在终端优雅打印板块龙头监测表格。"""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print("\n" + "=" * 110)
    print(f"  📊 easy_tdx 板块龙头股票实时监测监控池 {title_suffix}  (刷新时间: {now_str})")
    print("=" * 110)

    if not results:
        print("  [提示] 暂未获取到板块龙头数据，请检查行情网络或非交易时段。")
        print("=" * 110 + "\n")
        return

    for idx, b in enumerate(results, 1):
        b_name = b.get("board_name", "--")
        b_code = b.get("board_code", "--")
        b_pct = b.get("change_pct", 0.0)
        b_amt_str = _fmt_amt(b.get("amount", 0.0))
        b_net_str = _fmt_money(b.get("main_net_amount", 0.0))
        up_cnt = b.get("up_count", 0)
        down_cnt = b.get("down_count", 0)

        # 板块摘要行
        pct_color = "\033[31m" if b_pct > 0 else ("\033[32m" if b_pct < 0 else "")
        reset_color = "\033[0m"
        print(f"\n[{idx:02d}] 🏷️  板块: \033[1m{b_name:<8}\033[0m ({b_code}) | 涨跌幅: {pct_color}{b_pct:+.2f}%{reset_color} | 成交额: {b_amt_str} | 主力净流入: {b_net_str} | 涨跌比: {up_cnt}涨/{down_cnt}跌")

        # 核心龙头标识
        pioneer = b.get("leader_pioneer")
        capacity = b.get("leader_capacity")
        ladder = b.get("leader_ladder")
        tags = []
        if pioneer:
            tags.append(f"先锋: {pioneer['name']}({pioneer['code']} {pioneer['change_pct']:+.2f}%)")
        if capacity and (not pioneer or capacity["code"] != pioneer["code"]):
            tags.append(f"中军: {capacity['name']}({capacity['code']} 成交{_fmt_amt(capacity['amount'])})")
        if ladder and (not pioneer or ladder["code"] != pioneer["code"]):
            tags.append(f"高度龙: {ladder['name']}({ladder['lbc']}连板)")
        if tags:
            print(f"     💡 龙头矩阵: {' | '.join(tags)}")

        # 候选个股表头
        print("     " + "-" * 102)
        print(f"     {'代码':<8} {'股票名称':<8} {'现价':>8} {'涨跌幅':>8} {'成交额':>10} {'主力净流入':>12} {'量比':>6} {'连板':>5} {'龙头得分':>8}  {'龙头角色属性'}")
        print("     " + "-" * 102)

        candidates = b.get("candidates", [])
        for c in candidates:
            c_code = c["code"]
            c_name = c["name"]
            c_price = f"{c['price']:.2f}"
            c_pct = f"{c['change_pct']:+.2f}%"
            c_amt = _fmt_amt(c["amount"])
            c_net = _fmt_money(c["main_net_amount"])
            c_vr = f"{c['vol_ratio']:.2f}"
            c_lbc = f"{c['lbc']}板" if c["lbc"] > 0 else "-"
            c_score = f"{c['leader_score']:.1f}"
            c_role = c["role_tag"]

            pct_prefix = "\033[31m" if c["change_pct"] > 0 else ("\033[32m" if c["change_pct"] < 0 else "")
            print(f"     {c_code:<8} {c_name:<8} {c_price:>8} {pct_prefix}{c_pct:>8}{reset_color} {c_amt:>10} {c_net:>12} {c_vr:>6} {c_lbc:>5} {c_score:>8}  {c_role}")

    print("\n" + "=" * 110 + "\n")


def export_to_csv(results: List[Dict[str, Any]], filepath: str):
    """将板块龙头监测数据导出为 CSV 文件。"""
    import csv

    out_path = Path(filepath)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with open(out_path, mode="w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow([
            "板块代码",
            "板块名称",
            "板块涨跌幅%",
            "板块成交额",
            "板块主力净流入",
            "股票代码",
            "股票名称",
            "最新价",
            "个股涨跌幅%",
            "成交额",
            "主力净流入",
            "量比",
            "换手率%",
            "连板数",
            "龙头评分",
            "龙头角色属性",
            "更新时间",
        ])
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for b in results:
            b_code = b.get("board_code", "")
            b_name = b.get("board_name", "")
            b_pct = b.get("change_pct", 0.0)
            b_amt = b.get("amount", 0.0)
            b_net = b.get("main_net_amount", 0.0)
            for c in b.get("candidates", []):
                writer.writerow([
                    b_code,
                    b_name,
                    b_pct,
                    b_amt,
                    b_net,
                    c["code"],
                    c["name"],
                    c["price"],
                    c["change_pct"],
                    c["amount"],
                    c["main_net_amount"],
                    c["vol_ratio"],
                    c["turnover"],
                    c["lbc"],
                    c["leader_score"],
                    c["role_tag"],
                    now_str,
                ])
    print(f"✅ 成功导出板块龙头监测数据至: {out_path.resolve()}")


def parse_args():
    parser = argparse.ArgumentParser(
        description="easy_tdx 板块龙头股票实时监测监控脚本",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--type",
        "-t",
        choices=["hy", "gn", "all"],
        default="hy",
        help="板块分类: hy (行业板块, 默认), gn (概念板块), all (行业与概念同时监测)",
    )
    parser.add_argument(
        "--top-boards",
        "-b",
        type=int,
        default=8,
        help="监测涨幅排名前 N 的强势板块 (默认: 8)",
    )
    parser.add_argument(
        "--top-stocks",
        "-s",
        type=int,
        default=3,
        help="每个板块提取前 M 只龙头候选股 (默认: 3)",
    )
    parser.add_argument(
        "--board",
        type=str,
        default="",
        help="指定追踪单个板块名称或代码（如: --board 半导体 或 --board 881094）",
    )
    parser.add_argument(
        "--loop",
        "-l",
        action="store_true",
        help="启用实时动态轮询监控模式 (按 Ctrl+C 退出)",
    )
    parser.add_argument(
        "--interval",
        "-i",
        type=int,
        default=5,
        help="实时轮询间隔秒数 (默认: 5 秒)",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default="",
        help="将监测结果保存为 CSV 文件路径 (例如: output/sector_leaders.csv)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="以 JSON 格式输出监测结果 (便于下游程序或前端解析)",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    monitor = SectorLeaderMonitor()

    def run_once():
        results = []
        if args.board:
            # 模式 1: 指定单个板块追踪
            target = monitor.search_board(args.board)
            if not target:
                print(f"[错误] 未找到板块: {args.board}", file=sys.stderr)
                return []
            analysis = monitor.analyze_board_leaders(
                board_code=str(target.get("code", "")),
                board_name=str(target.get("name", "")),
                top_candidates=args.top_stocks,
            )
            analysis["change_pct"] = float(target.get("change_pct", 0.0))
            analysis["amount"] = float(target.get("amount", 0.0))
            analysis["main_net_amount"] = float(target.get("main_net_amount", 0.0))
            analysis["up_count"] = int(target.get("up_count", 0))
            analysis["down_count"] = int(target.get("down_count", 0))
            results = [analysis]
        else:
            # 模式 2: 全局强势板块排行榜
            if args.type == "hy":
                results = monitor.scan_all_leaders(
                    BoardType.HY, top_boards=args.top_boards, top_stocks_per_board=args.top_stocks
                )
            elif args.type == "gn":
                results = monitor.scan_all_leaders(
                    BoardType.GN, top_boards=args.top_boards, top_stocks_per_board=args.top_stocks
                )
            else:
                r_hy = monitor.scan_all_leaders(
                    BoardType.HY, top_boards=args.top_boards // 2, top_stocks_per_board=args.top_stocks
                )
                r_gn = monitor.scan_all_leaders(
                    BoardType.GN, top_boards=args.top_boards // 2, top_stocks_per_board=args.top_stocks
                )
                results = r_hy + r_gn

        return results

    if args.loop:
        print(f"🚀 启动 easy_tdx 板块龙头实时监测循环 (刷新频率: 每 {args.interval} 秒)... 按 Ctrl+C 停止")
        try:
            while True:
                # 清屏保持终端整洁
                if sys.platform == "win32":
                    os.system("cls")
                else:
                    os.system("clear")

                data = run_once()
                print_screen_table(data, title_suffix="[实时轮询模式]")
                if args.output and data:
                    export_to_csv(data, args.output)

                time.sleep(args.interval)
        except KeyboardInterrupt:
            print("\n👋 监测循环已停止。")
    else:
        # 单次执行
        data = run_once()
        if args.json:
            print(json.dumps(data, ensure_ascii=False, indent=2))
        else:
            print_screen_table(data, title_suffix="[单次快照]")

        if args.output and data:
            export_to_csv(data, args.output)


if __name__ == "__main__":
    main()
