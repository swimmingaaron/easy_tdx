#!/usr/bin/env python3
"""自选股 (watchlist.json) 缠论多周期立体 K 线图定时推送至企业微信机器人。

支持盘中交易时段每 30 分钟轮询，自动生成缠论立体同图走势并推送快照至企业微信群。
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

# 1. 确保使用 Agg 后端，支持无图形界面/后台 cron 静默导出图片
import matplotlib

matplotlib.use("Agg")

# 2. 确保 easy_tdx 源码根目录加载
PROJECT_ROOT = Path(__file__).resolve().parent
src_path = PROJECT_ROOT / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("watchlist_wecom")


def load_env_webhook() -> str:
    """从 .env 或系统环境变量读取 WECHAT_WEBHOOK_URL。"""
    webhook = os.environ.get("WECHAT_WEBHOOK_URL", "").strip()
    if webhook:
        return webhook

    env_path = PROJECT_ROOT / ".env"
    if env_path.is_file():
        try:
            with open(env_path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("WECHAT_WEBHOOK_URL="):
                        webhook = line.split("=", 1)[1].strip().strip('"').strip("'")
                        if webhook:
                            return webhook
        except Exception as e:
            logger.debug(f"读取 .env 异常: {e}")
    return ""


def send_wecom_post(webhook_url: str, payload: dict[str, Any]) -> dict[str, Any]:
    """向企业微信 Webhook 机器人发送 JSON 请求。"""
    headers = {"Content-Type": "application/json; charset=utf-8"}
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(webhook_url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp_body = resp.read().decode("utf-8")
            return json.loads(resp_body)
    except Exception as e:
        logger.error(f"发送企业微信请求异常: {e}")
        return {"errcode": -1, "errmsg": str(e)}


def send_wecom_markdown(webhook_url: str, content: str) -> bool:
    """发送企业微信 Markdown 文本卡片。"""
    payload = {
        "msgtype": "markdown",
        "markdown": {
            "content": content
        }
    }
    res = send_wecom_post(webhook_url, payload)
    return res.get("errcode") == 0


def send_wecom_image(webhook_url: str, image_bytes: bytes) -> bool:
    """发送企业微信原生图片消息 (Base64 + MD5)。"""
    if not image_bytes:
        return False
    b64_str = base64.b64encode(image_bytes).decode("utf-8")
    md5_str = hashlib.md5(image_bytes).hexdigest()
    payload = {
        "msgtype": "image",
        "image": {
            "base64": b64_str,
            "md5": md5_str,
        }
    }
    res = send_wecom_post(webhook_url, payload)
    return res.get("errcode") == 0


def load_watchlist(watchlist_path: Path) -> list[dict[str, str]]:
    """加载 watchlist.json 标的配置。"""
    if not watchlist_path.is_file():
        logger.error(f"自选股文件不存在: {watchlist_path}")
        return []
    try:
        with open(watchlist_path, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return data
        elif isinstance(data, dict):
            # 支持字典格式兼容
            return [{"code": k, "name": str(v)} for k, v in data.items()]
    except Exception as e:
        logger.error(f"解析 watchlist.json 失败: {e}")
    return []


def push_watchlist_chanlun(
    watchlist_path: Path | None = None,
    webhook_url: str | None = None,
    periods: str = "WEEK,DAY,30F",
    limit: int | None = None,
) -> None:
    """核心逻辑：遍历自选股生成缠论走势图并推送至企业微信。"""
    from chanlun_resonance_kline import analyze_and_plot_resonance

    webhook = webhook_url or load_env_webhook()
    if not webhook:
        logger.error(
            "未找到企业微信机器人 Webhook 地址！请在 .env 或环境变量中配置 WECHAT_WEBHOOK_URL"
        )
        sys.exit(1)

    wl_file = watchlist_path or (PROJECT_ROOT / "watchlist.json")
    stocks = load_watchlist(wl_file)
    if not stocks:
        logger.warning("自选股列表为空，取消发送。")
        return

    if limit and limit > 0:
        stocks = stocks[:limit]

    out_dir = PROJECT_ROOT / "output" / "watchlist_chanlun_charts"
    out_dir.mkdir(parents=True, exist_ok=True)

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info(f"开始执行自选股缠论K线推送，共 {len(stocks)} 只标的，当前时间: {now_str}")

    # 1. 先推送一次汇总报头
    header_md = (
        f"### 📈 自选股缠论多周期立体走势监测\n"
        f"> **监测时间**: <font color=\"comment\">{now_str}</font>\n"
        f"> **监控周期**: <font color=\"info\">{periods}</font>\n"
        f"> **标的数量**: {len(stocks)} 只\n"
        f"> 正在逐一输出多周期同图走势快照，请查阅下方图表..."
    )
    send_wecom_markdown(webhook, header_md)
    time.sleep(1.0)

    success_count = 0
    for idx, item in enumerate(stocks, 1):
        code = str(item.get("code", "")).strip().zfill(6)
        name = str(item.get("name", "")).strip() or code
        if not code or len(code) != 6:
            continue

        logger.info(f"[{idx}/{len(stocks)}] 正在生成 {code} {name} 缠论多周期K线图...")
        png_target = out_dir / f"chanlun_{code}.png"

        try:
            ret = analyze_and_plot_resonance(
                code=code,
                periods=periods,
                bars_count=200,
                save_png=True,
                output_png_path=str(png_target),
                show_window=False,
            )

            png_path = ret.get("png_path")
            if not png_path or not Path(png_path).is_file():
                logger.warning(f"未能生成 {code} 的 K 线图片")
                continue

            # 构建标的简报文字
            resonances = ret.get("resonances", [])
            res_summary = "中枢震荡观察中"
            if resonances:
                latest_r = resonances[-1]
                dir_label = "买点 ▲" if latest_r.direction == "BUY" else "卖点 ▼"
                c_tag = "warning" if latest_r.direction == "BUY" else "info"
                res_summary = (
                    f"<font color=\"{c_tag}\">★ [{latest_r.grade}级共振] "
                    f"{latest_r.pattern_name} ({dir_label}) @ ¥{latest_r.price:.2f}</font>"
                )

            stock_md = (
                f"**【{name} ({code})】缠论多周期走势**\n"
                f"> **周期**: {periods}\n"
                f"> **共振形态**: {res_summary}\n"
                f"> **快照时间**: {datetime.now().strftime('%H:%M:%S')}"
            )
            send_wecom_markdown(webhook, stock_md)
            time.sleep(0.8)

            # 读取图片并发送
            with open(png_path, "rb") as f:
                img_data = f.read()
            img_ok = send_wecom_image(webhook, img_data)
            if img_ok:
                success_count += 1
                logger.info(f"✓ {name} ({code}) 缠论K线快照已成功推送到企业微信")
            else:
                logger.error(f"✗ {name} ({code}) 图片发送失败")

            # 遵守企业微信 20条/分钟 限流（发送 1 条文本+1 条图片，间隔 2 秒）
            time.sleep(2.0)

        except Exception as e:
            logger.error(f"处理 {name} ({code}) 失败: {e}")
            time.sleep(1.0)

    logger.info(f"自选股缠论K线推送完成，成功发送 {success_count}/{len(stocks)} 张走势图。")


def main() -> None:
    parser = argparse.ArgumentParser(description="自选股缠论多周期K线图推送企业微信工具")
    parser.add_argument("--watchlist", "-w", type=str, default=None, help="watchlist.json 路径")
    parser.add_argument("--webhook", type=str, default=None, help="企业微信 Webhook 地址")
    parser.add_argument(
        "--periods", "-p",
        type=str,
        default="WEEK,DAY,30F",
        help="分析周期组合 (默认: WEEK,DAY,30F)",
    )
    parser.add_argument(
        "--limit", "-n",
        type=int,
        default=None,
        help="仅发送前 N 只标的（调试测试用）",
    )
    args = parser.parse_args()

    wl_path = Path(args.watchlist) if args.watchlist else None
    push_watchlist_chanlun(
        watchlist_path=wl_path,
        webhook_url=args.webhook,
        periods=args.periods,
        limit=args.limit,
    )


if __name__ == "__main__":
    main()
