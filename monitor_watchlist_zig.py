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
import concurrent.futures
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

from easy_tdx.market_data import fetch_security_kline
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


# ==============================================================================
# 2. 30分钟 K线 ZIG 计算与自选池扫描
# ==============================================================================

def check_single_stock_zig(
    item: Dict[str, str], 
    change_pct: float = 0.05,
    count: int = 120
) -> Optional[Dict[str, Any]]:
    """检查单只标的的 30分钟 K线 ZIG 状态。"""
    code = item.get("code", "").strip()
    name = item.get("name", code).strip()
    if not code:
        return None

    try:
        df = fetch_security_kline(code, period="30M", count=count)
        if df is None or len(df) < 10:
            return None

        closes = df["close"].values
        zig_days = calculate_zig_series(closes, change_pct=change_pct)
        if not zig_days:
            return None

        cur_zig = int(zig_days[-1])
        # 仅关注反转首日 (+1 或 -1)
        if cur_zig not in (1, -1):
            return None

        last_bar = df.iloc[-1]
        prev_bar = df.iloc[-2] if len(df) >= 2 else last_bar
        cur_c = float(last_bar["close"])
        pre_c = float(prev_bar["close"])
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
        }
    except Exception as e:
        logger.debug(f"检查 {code} ({name}) 30M ZIG 出错: {e}")
        return None


def scan_watchlist_zig(
    change_pct: float = 0.05, 
    max_workers: int = 8
) -> Dict[str, List[Dict[str, Any]]]:
    """并发扫描整个 watchlist.json 中所有标的的 30分钟 ZIG。"""
    items = load_watchlist_items()
    if not items:
        logger.warning("未检测到有效自选股（watchlist.json 为空）")
        return {"buy_signals": [], "sell_signals": []}

    logger.info(f"开始扫描自选池 30分钟 ZIG 状态... 标的总数: {len(items)}, ZIG阈值: {change_pct*100:.1f}%")
    t0 = time.time()

    buy_signals = []
    sell_signals = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(check_single_stock_zig, item, change_pct): item
            for item in items
        }
        for future in concurrent.futures.as_completed(futures):
            res = future.result()
            if res:
                if res["zig"] == 1:
                    buy_signals.append(res)
                elif res["zig"] == -1:
                    sell_signals.append(res)

    # 排序：买入信号按30分钟涨幅从大到小，卖出信号按跌幅从小到大
    buy_signals.sort(key=lambda x: x["chg_pct"], reverse=True)
    sell_signals.sort(key=lambda x: x["chg_pct"])

    cost = time.time() - t0
    logger.info(
        f"自选池 30M 扫描完毕，耗时: {cost:.2f}秒 | 向上反转(+1): {len(buy_signals)} 只 | 见顶向下(-1): {len(sell_signals)} 只"
    )

    return {
        "buy_signals": buy_signals,
        "sell_signals": sell_signals,
    }


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
        else:
            logger.warning(
                "检测到 ZIG 转向信号，但尚未配置微信通知通道（企业微信 Webhook / PushPlus / Server酱）。"
            )
            logger.info("提示: 启动时可通过 --webhook 参数传入企业微信 Webhook 链接。")
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
