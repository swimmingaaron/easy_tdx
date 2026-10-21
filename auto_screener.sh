#!/bin/bash
# ==============================================================================
# easy_tdx 自动化调度脚本 (macOS / Linux)
# 
# 功能规则：
# 1. 交易时间内 (09:25-11:35, 12:55-15:00)：
#    每 30 分钟执行一次，将 watchlist.json 的 code 生成缠论立体K线图并推送至企业微信；
# 2. 15时01分 (15:01-15:05)：
#    自动执行全市场地毯式扫描，注意：【不发送缠论K线图至微信】；
# 3. 自动排除周末（周六/周日），使用 caffeinate 防止 macOS 深度睡眠。
# ==============================================================================

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR" || exit 1

# 1. 星期判断：1-5 为交易日，6-7 为周末
DAY_OF_WEEK=$(date +%u)
if [ "$DAY_OF_WEEK" -gt 5 ]; then
    echo "$(date '+%Y-%m-%d %H:%M:%S') [SKIP] 今天是周末 (周 $DAY_OF_WEEK)，不执行任务。"
    exit 0
fi

# 2. Python 解释器选择 (优先虚拟环境)
if [ -f "$PROJECT_DIR/.venv/bin/python" ]; then
    PYTHON_BIN="$PROJECT_DIR/.venv/bin/python"
elif [ -f "$PROJECT_DIR/.venv/Scripts/python.exe" ]; then
    PYTHON_BIN="$PROJECT_DIR/.venv/Scripts/python.exe"
else
    PYTHON_BIN=$(which python3)
fi

mkdir -p "$PROJECT_DIR/output"
LOG_DATE=$(date +%Y%m%d)
CURRENT_H=$(date +%-H)
CURRENT_M=$(date +%-M)
# 转换为自 00:00 起的绝对分钟数，彻底杜绝字符串比较或八进制前导零错误
CURRENT_MINUTES=$((CURRENT_H * 60 + CURRENT_M))
CURRENT_TIME=$(date '+%Y-%m-%d %H:%M:%S')

# 3. 支持命令行显式强制模式：--full-scan 或 --watchlist
FORCE_MODE="$1"

# 4. 时间界限定义 (单位: 分钟)
# 15:01 ~ 15:05 -> 901 ~ 905 分钟
# 上午交易时段 09:25 ~ 11:35 -> 565 ~ 695 分钟
# 下午交易时段 12:55 ~ 15:00 -> 775 ~ 900 分钟

# ==============================================================================
# 分支 A: 15时01分 收盘全市场扫描 (不发送缠论K线图至微信)
# ==============================================================================
if [ "$FORCE_MODE" = "--full-scan" ] || ( [ "$CURRENT_MINUTES" -ge 901 ] && [ "$CURRENT_MINUTES" -le 905 ] ); then
    LOG_FILE="$PROJECT_DIR/output/screener_market_${LOG_DATE}.log"
    echo "============================================================" >> "$LOG_FILE"
    echo "【15:01 全市场选股扫描启动】 $CURRENT_TIME" >> "$LOG_FILE"
    echo "参数: -s chanlun_resonance -p ALL_CASCADE -u all -w 16 --refresh" >> "$LOG_FILE"
    echo "注意: 按照预设规则，全市场扫描结果不发送K线图至微信" >> "$LOG_FILE"
    echo "============================================================" >> "$LOG_FILE"

    # 执行全市场并发选股
    if command -v caffeinate >/dev/null 2>&1; then
        caffeinate -i "$PYTHON_BIN" run_screener.py \
            -s chanlun_resonance \
            -p ALL_CASCADE \
            -u all \
            -w 16 \
            --refresh \
            --no-interactive >> "$LOG_FILE" 2>&1
    else
        "$PYTHON_BIN" run_screener.py \
            -s chanlun_resonance \
            -p ALL_CASCADE \
            -u all \
            -w 16 \
            --refresh \
            --no-interactive >> "$LOG_FILE" 2>&1
    fi

    EXIT_CODE=$?
    echo "【全市场选股完成】 $(date '+%Y-%m-%d %H:%M:%S') Exit Code: $EXIT_CODE" >> "$LOG_FILE"
    
    # macOS 桌面横幅提醒
    if command -v osascript >/dev/null 2>&1; then
        if [ $EXIT_CODE -eq 0 ]; then
            osascript -e 'display notification "A股全市场缠论共振扫描已完成，报表已生成！" with title "easy_tdx 选股提醒"'
        else
            osascript -e 'display notification "全市场选股执行异常，请查看日志！" with title "easy_tdx 异常提醒"'
        fi
    fi
    exit $EXIT_CODE

# ==============================================================================
# 分支 B: 交易时间内 (09:25-11:35, 12:55-15:00) 盘中推送 watchlist 缠论K线至微信
# ==============================================================================
elif [ "$FORCE_MODE" = "--watchlist" ] || \
     ( [ "$CURRENT_MINUTES" -ge 565 ] && [ "$CURRENT_MINUTES" -le 695 ] ) || \
     ( [ "$CURRENT_MINUTES" -ge 775 ] && [ "$CURRENT_MINUTES" -le 900 ] ); then

    LOG_FILE="$PROJECT_DIR/output/watchlist_wecom_${LOG_DATE}.log"
    echo "============================================================" >> "$LOG_FILE"
    echo "【盘中自选股缠论K线微信推送启动】 $CURRENT_TIME" >> "$LOG_FILE"
    echo "============================================================" >> "$LOG_FILE"

    if command -v caffeinate >/dev/null 2>&1; then
        caffeinate -i "$PYTHON_BIN" send_watchlist_chanlun_wecom.py >> "$LOG_FILE" 2>&1
    else
        "$PYTHON_BIN" send_watchlist_chanlun_wecom.py >> "$LOG_FILE" 2>&1
    fi

    EXIT_CODE=$?
    echo "【自选股缠论K线微信推送完成】 $(date '+%Y-%m-%d %H:%M:%S') Exit Code: $EXIT_CODE" >> "$LOG_FILE"
    exit $EXIT_CODE

# ==============================================================================
# 分支 C: 非交易时间且非 15:01
# ==============================================================================
else
    echo "$CURRENT_TIME [SKIP] 当前时间 (${CURRENT_H}:${CURRENT_M}) 不在交易时段且非 15:01，跳过执行。"
    exit 0
fi
