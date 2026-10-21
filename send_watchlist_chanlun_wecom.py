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
logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)
logging.getLogger("matplotlib").setLevel(logging.WARNING)


def load_env_webhook() -> str:
    """从 .env 或系统环境变量读取 WECHAT_WEBHOOK_URL。"""
    webhook = os.environ.get("WECHAT_WEBHOOK_URL", "").strip()
    if webhook:
        return webhook

    # 检查 .env 以及可能的手误命名 .evn
    candidates = [PROJECT_ROOT / ".env", PROJECT_ROOT / ".evn"]
    for env_path in candidates:
        if env_path.is_file():
            try:
                with open(env_path, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line.startswith("WECHAT_WEBHOOK_URL="):
                            webhook = line.split("=", 1)[1].strip().strip('"').strip("'")
                            if webhook:
                                if env_path.name == ".evn":
                                    logger.warning("检测到环境变量配置文件命名为 .evn (建议重命名为标准 .env)")
                                return webhook
            except Exception as e:
                logger.debug(f"读取 {env_path.name} 异常: {e}")
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


def format_period_state(res: Any, period_name: str) -> str:
    """提取单个级别的笔走势方向与最新顶底买卖点标识。"""
    if res is None:
        return "数据暂缺"

    # 1. 笔方向
    bi_text = "震荡中"
    if hasattr(res, "bis") and res.bis:
        last_bi = res.bis[-1]
        is_up = getattr(last_bi, "is_up", False)
        bi_text = "向上笔 ↗" if is_up else "向下笔 ↘"

    # 2. 最新买卖点
    mmd_text = "中枢延伸"
    if hasattr(res, "mmds") and res.mmds:
        last_mmd = res.mmds[-1]
        mtype = getattr(last_mmd, "mmd_type", None)
        mval = mtype.value if hasattr(mtype, "value") else str(mtype)
        type_map = {
            "1buy": "1买(底背驰拐点) ▲",
            "2buy": "2买(回调确认) ▲",
            "3buy": "3买(中枢突破) ▲",
            "1sell": "1卖(极高顶背驰) ▼",
            "2sell": "2卖(反抽破位) ▼",
            "3sell": "3卖(破位杀跌) ▼",
        }
        raw_label = type_map.get(mval, mval.upper())
        if "buy" in mval:
            mmd_text = f"<font color=\"warning\">{raw_label}</font>"
        elif "sell" in mval:
            mmd_text = f"<font color=\"info\">{raw_label}</font>"
        else:
            mmd_text = raw_label

    return f"{bi_text} | {mmd_text}"


def combine_three_resonance_charts(
    path_super: Path,
    path_macro: Path,
    path_micro: Path,
    target_path: Path,
) -> Path:
    """将《月·周·日》、《周·日·30F》、《日·30F·5F》三张区间套图垂直无缝合并为单张超清长卷。

    自动优化图片体积，严格保证在企业微信 2MB 限制内。
    """
    from PIL import Image

    im_super = Image.open(path_super)
    im_macro = Image.open(path_macro)
    im_micro = Image.open(path_micro)

    target_w = im_super.width
    imgs = [im_super]
    for im in (im_macro, im_micro):
        if im.width != target_w:
            nh = int(im.height * (target_w / im.width))
            imgs.append(im.resize((target_w, nh), Image.Resampling.LANCZOS))
        else:
            imgs.append(im)

    total_h = sum(im.height for im in imgs)
    combined_img = Image.new("RGB", (target_w, total_h), (19, 23, 34))
    curr_y = 0
    for im in imgs:
        combined_img.paste(im, (0, curr_y))
        curr_y += im.height

    # 以优质 JPEG 格式保存，质量 84
    combined_img.save(target_path, format="JPEG", quality=84, optimize=True)
    if target_path.stat().st_size > 1900 * 1024:
        # 若超过 1.9MB，自适应缩放以确保企业微信可靠发送
        scale = 0.78
        nw, nh = int(target_w * scale), int(total_h * scale)
        small_img = combined_img.resize((nw, nh), Image.Resampling.BILINEAR)
        small_img.save(target_path, format="JPEG", quality=78, optimize=True)

    return target_path


def push_watchlist_chanlun(
    watchlist_path: Path | None = None,
    webhook_url: str | None = None,
    periods: str | None = None,
    limit: int | None = None,
) -> None:
    """核心逻辑：遍历自选股生成包含三重区间套《月·周·日》、《周·日·30F》、《日·30F·5F》的高清立体走势长卷并推送至企业微信。"""
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

    # 1. 推送一次汇总报头
    header_md = (
        f"### 📈 自选股缠论多周期立体走势监测 (三重区间套)\n"
        f"> **监测时间**: <font color=\"comment\">{now_str}</font>\n"
        f"> **🪐 超长线**: <font color=\"info\">月线 · 周线 · 日线 (宏观大势定乾坤)</font>\n"
        f"> **🔭 中长线**: <font color=\"info\">周线 · 日线 · 30F (主升波段寻中枢)</font>\n"
        f"> **🔬 微操盘**: <font color=\"info\">日线 · 30F · 5F (微观拐点抓买卖)</font>\n"
        f"> **标的数量**: {len(stocks)} 只\n"
        f"> 正在逐一输出包含三重区间套的立体同图长卷，请查阅下方图表..."
    )
    send_wecom_markdown(webhook, header_md)
    time.sleep(1.0)

    success_count = 0

    for idx, item in enumerate(stocks, 1):
        code = str(item.get("code", "")).strip().zfill(6)
        name = str(item.get("name", "")).strip() or code
        if not code or len(code) != 6:
            continue

        logger.info(f"[{idx}/{len(stocks)}] 正在生成 {code} {name} 缠论三重区间套走势长卷...")
        png_super = out_dir / f"chanlun_{code}_MONTH_WEEK_DAY.png"
        png_macro = out_dir / f"chanlun_{code}_WEEK_DAY_30F.png"
        png_micro = out_dir / f"chanlun_{code}_DAY_30F_5F.png"
        final_img_path = out_dir / f"chanlun_{code}_triple.jpg"

        try:
            # 1. 生成超长线区间套：《月线 · 周线 · 日线》（保留交易额副图）
            ret_super = analyze_and_plot_resonance(
                code=code,
                periods="MONTH,WEEK,DAY",
                bars_count=None,
                save_png=True,
                output_png_path=str(png_super),
                show_window=False,
                include_sub=True,
            )

            # 2. 生成中长线区间套：《周线 · 日线 · 30F》（仅针对微信去除副图，突出K线笔中枢）
            ret_macro = analyze_and_plot_resonance(
                code=code,
                periods="WEEK,DAY,30F",
                bars_count=None,
                save_png=True,
                output_png_path=str(png_macro),
                show_window=False,
                include_sub=False,
            )

            # 3. 生成微观操盘区间套：《日线 · 30F · 5F》（仅针对微信去除副图，突出K线笔中枢）
            ret_micro = analyze_and_plot_resonance(
                code=code,
                periods="DAY,30F,5F",
                bars_count=None,
                save_png=True,
                output_png_path=str(png_micro),
                show_window=False,
                include_sub=False,
            )

            if not (png_super.is_file() and png_macro.is_file() and png_micro.is_file()):
                logger.warning(f"未能完整生成 {code} 的三重区间套图片")
                continue

            # 4. 垂直拼合成一张包含三重区间套的高清长卷
            combine_three_resonance_charts(png_super, png_macro, png_micro, final_img_path)

            # 5. 提取三重区间套状态信息与买卖点
            res_super = ret_super.get("results", {})
            res_macro = ret_macro.get("results", {})
            res_micro = ret_micro.get("results", {})
            dfs_micro = ret_micro.get("dfs", {})

            # 获取最新价格
            price_str = "--"
            base_df = dfs_micro.get("5F")
            if base_df is not None and not base_df.empty and "close" in base_df.columns:
                last_price = float(base_df["close"].iloc[-1])
                price_str = f"¥{last_price:.2f}"

            # 状态提取
            state_month = format_period_state(res_super.get("MONTH"), "MONTH")
            state_week_super = format_period_state(res_super.get("WEEK"), "WEEK")
            state_day_super = format_period_state(res_super.get("DAY"), "DAY")

            state_week_macro = format_period_state(res_macro.get("WEEK"), "WEEK")
            state_day_macro = format_period_state(res_macro.get("DAY"), "DAY")
            state_m30_macro = format_period_state(res_macro.get("30F"), "30F")

            state_day_micro = format_period_state(res_micro.get("DAY"), "DAY")
            state_m30_micro = format_period_state(res_micro.get("30F"), "30F")
            state_m5_micro = format_period_state(res_micro.get("5F"), "5F")

            # 买卖点共振识别 (微观 -> 中观 -> 宏观多级共振)
            resonances = (
                ret_micro.get("resonances", [])
                or ret_macro.get("resonances", [])
                or ret_super.get("resonances", [])
            )
            if resonances:
                latest_r = resonances[-1]
                dir_label = "买点 ▲" if latest_r.direction == "BUY" else "卖点 ▼"
                c_tag = "warning" if latest_r.direction == "BUY" else "info"
                res_summary = (
                    f"<font color=\"{c_tag}\">★ [{latest_r.grade}级共振] "
                    f"{latest_r.pattern_name} ({dir_label}) @ ¥{latest_r.price:.2f}</font>"
                )
            else:
                low_mmds = getattr(res_micro.get("5F"), "mmds", []) if res_micro.get("5F") else []
                if low_mmds:
                    last_low = low_mmds[-1]
                    mval = last_low.mmd_type.value
                    if "buy" in mval:
                        res_summary = f"<font color=\"warning\">▲ [5F买点] 刚刚触发 {mval.upper()} 买点</font>"
                    elif "sell" in mval:
                        res_summary = f"<font color=\"info\">▼ [5F卖点] 刚刚触发 {mval.upper()} 卖点，注意减仓</font>"
                    else:
                        res_summary = "多周期中枢震荡整理中"
                else:
                    res_summary = "多周期中枢震荡整理中"

            stock_md = (
                f"### 📊 【{name} ({code})】缠论三重区间套立体走势\n"
                f"> **最新现价**: <font color=\"comment\">{price_str}</font>\n"
                f"> ───────────────\n"
                f"> 🪐 **超长线 [月线·周线·日线]**:\n"
                f"> • 🟣 **月线**: {state_month}\n"
                f"> • 🟡 **周线**: {state_week_super}\n"
                f"> • 🔵 **日线**: {state_day_super}\n"
                f"> ───────────────\n"
                f"> 🔭 **中长线 [周线·日线·30F]**:\n"
                f"> • 🟣 **周线**: {state_week_macro}\n"
                f"> • 🟡 **日线**: {state_day_macro}\n"
                f"> • 🔵 **30F**: {state_m30_macro}\n"
                f"> ───────────────\n"
                f"> 🔬 **微操盘 [日线·30F·5F]**:\n"
                f"> • 🟣 **日线**: {state_day_micro}\n"
                f"> • 🟡 **30F**: {state_m30_micro}\n"
                f"> • 🔵 **5F**: {state_m5_micro}\n"
                f"> ───────────────\n"
                f"> 🎯 **立体买卖研判**: {res_summary}\n"
                f"> ⏰ **快照时间**: {datetime.now().strftime('%H:%M:%S')}"
            )
            send_wecom_markdown(webhook, stock_md)
            time.sleep(0.8)

            # 读取合并后的长卷并发送
            with open(final_img_path, "rb") as f:
                img_data = f.read()
            img_ok = send_wecom_image(webhook, img_data)
            if img_ok:
                success_count += 1
                logger.info(f"✓ {name} ({code}) 三重区间套长卷已成功推送到企业微信")
            else:
                logger.error(f"✗ {name} ({code}) 图片发送失败")

            # 遵守企业微信限流
            time.sleep(2.0)

        except Exception as e:
            logger.error(f"处理 {name} ({code}) 失败: {e}")
            time.sleep(1.0)

    logger.info(f"自选股缠论三重区间套推送完成，成功发送 {success_count}/{len(stocks)} 张长卷。")


def main() -> None:
    parser = argparse.ArgumentParser(description="自选股缠论三重区间套走势长卷推送企业微信工具")
    parser.add_argument("--watchlist", "-w", type=str, default=None, help="watchlist.json 路径")
    parser.add_argument("--webhook", type=str, default=None, help="企业微信 Webhook 地址")
    parser.add_argument(
        "--periods", "-p",
        type=str,
        default=None,
        help="自选指定单个区间套（默认自动包含《月·周·日》、《周·日·30F》和《日·30F·5F》三重区间套）",
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
