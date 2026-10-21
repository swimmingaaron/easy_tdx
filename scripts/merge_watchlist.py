#!/usr/bin/env python3
"""
watchlist.json 智能无损合并工具
================================
用法示例:
    # 1. 将临时备份文件合并回主 watchlist.json
    python scripts/merge_watchlist.py /tmp/watchlist_local.json

    # 2. 将 source.json 合并到 target.json
    python scripts/merge_watchlist.py target.json source.json

    # 3. 命令行直接追加新股票代码并去重合并
    python scripts/merge_watchlist.py --add 600519,300750,000001
"""
from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

# Windows UTF-8 控制台兼容
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# 将项目 src 加入路径
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = PROJECT_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from easy_tdx.watchlist_store import merge_watchlist_file, parse_watchlist_data


def main() -> None:
    parser = argparse.ArgumentParser(description="watchlist.json 智能无损合并工具")
    parser.add_argument(
        "files",
        nargs="*",
        help="目标与源文件路径。若仅传一个文件，则将其合并入根目录 watchlist.json",
    )
    parser.add_argument(
        "--target", "-t",
        type=str,
        default=str(PROJECT_ROOT / "watchlist.json"),
        help="目标 watchlist.json 路径（默认根目录下 watchlist.json）",
    )
    parser.add_argument(
        "--add", "-a",
        type=str,
        default=None,
        help="要追加并合并的股票代码，逗号分隔（如 600519,300750）",
    )

    args = parser.parse_args()

    target_file = Path(args.target)
    source_items = []

    # 命令行直接追加
    if args.add:
        codes = [c.strip() for c in args.add.replace("，", ",").split(",") if c.strip()]
        source_items.extend(codes)

    # 位置参数解析
    if len(args.files) == 1:
        source_items.append(Path(args.files[0]))
    elif len(args.files) >= 2:
        target_file = Path(args.files[0])
        for f in args.files[1:]:
            source_items.append(Path(f))

    if not source_items and not target_file.exists():
        print(f"⚠️ 未指定源文件且目标文件 {target_file} 不存在")
        sys.exit(0)

    if source_items:
        for src in source_items:
            res = merge_watchlist_file(target_file, src)
        print(f"✅ 自选股合并完成！当前 {target_file.name} 共有 {len(res)} 只标的。")
    else:
        # 自我格式化整理去重
        res = merge_watchlist_file(target_file, target_file)
        print(f"✅ 自选股整理去重完成！当前 {target_file.name} 共有 {len(res)} 只标的。")


if __name__ == "__main__":
    main()
