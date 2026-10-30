#!/bin/bash
# ==============================================================================
# easy_tdx 自动化调度脚本 (macOS / Linux)
# 
# 功能规则：
# 1. 09:25 (09:25-09:29)、11:30 (11:30-11:35)、14:30 (14:30-14:34)、15:00 (15:00-15:05) 全市场扫描：
#    自动执行全市场 (5000+) 地毯式扫描，依次并发执行 30F、DAY(日线)、WEEK(周线) 的 3买 策略：
#    - 任务 1 (30F 3买): 缠论三级共振 (chanlun_resonance, WEEK_DAY_30F_3BUY: 周日大趋势多头共振，筛选 30F 3买)
#    - 任务 2 (DAY 3买): 缠论三级共振 (chanlun_resonance, MONTH_WEEK_DAY_3BUY: 月周大趋势多头共振，筛选 日线 3买)
#    - 任务 3 (WEEK 3买): 缠论三级共振 (chanlun_resonance, SEASON_MONTH_WEEK_3BUY: 季月大趋势多头共振，筛选 周线 3买)
#    注意：【全市场扫描不发送缠论K线图至微信】；
# 2. 其余交易时间内 (09:25-11:30, 12:55-15:00)：
#    将 watchlist.json 的 code 生成缠论立体K线图并推送至企业微信；
# 3. 自动排除周末（周六/周日），使用 caffeinate 防止 macOS 深度睡眠；
# 4. 命令行支持指定：--full-scan (全部3个3买策略)、--30f-scan (仅30F 3买)、--day-scan (仅日线 3买)、--week-scan (仅周线 3买)、--watchlist (仅盘中推送)。
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

# 3. 支持命令行显式强制模式：--full-scan、--tri-scan、--30f-scan、--day-scan、--week-scan 或 --watchlist
FORCE_MODE="$1"

# 4. 时间界限定义 (单位: 分钟)
# 09:25 扫描窗口: 09:25 ~ 09:29 -> 565 ~ 569 分钟
# 11:30 扫描窗口: 11:30 ~ 11:35 -> 690 ~ 695 分钟
# 14:30 扫描窗口: 14:30 ~ 14:34 -> 870 ~ 874 分钟
# 15:00 扫描窗口: 15:00 ~ 15:05 -> 900 ~ 905 分钟
# 上午交易时段:   09:25 ~ 11:30 -> 565 ~ 690 分钟
# 下午交易时段:   12:55 ~ 15:00 -> 775 ~ 900 分钟

# ==============================================================================
# 分支 A: 09:25 / 11:30 / 14:30 / 15:00 全市场扫描 (30F / DAY / WEEK 的 3买 策略)
# (不发送缠论K线图至微信)
# ==============================================================================
if [ "$FORCE_MODE" = "--full-scan" ] || [ "$FORCE_MODE" = "--tri-scan" ] || \
   [ "$FORCE_MODE" = "--30f-scan" ] || [ "$FORCE_MODE" = "--day-scan" ] || [ "$FORCE_MODE" = "--week-scan" ] || \
   ( [ "$CURRENT_MINUTES" -ge 565 ] && [ "$CURRENT_MINUTES" -le 569 ] ) || \
   ( [ "$CURRENT_MINUTES" -ge 690 ] && [ "$CURRENT_MINUTES" -le 695 ] ) || \
   ( [ "$CURRENT_MINUTES" -ge 870 ] && [ "$CURRENT_MINUTES" -le 874 ] ) || \
   ( [ "$CURRENT_MINUTES" -ge 900 ] && [ "$CURRENT_MINUTES" -le 905 ] ); then

    SCAN_TAG="定时全量"
    if [ "$CURRENT_MINUTES" -ge 565 ] && [ "$CURRENT_MINUTES" -le 569 ]; then
        SCAN_TAG="09:25 早盘竞价"
    elif [ "$CURRENT_MINUTES" -ge 690 ] && [ "$CURRENT_MINUTES" -le 695 ]; then
        SCAN_TAG="11:30 午盘收盘"
    elif [ "$CURRENT_MINUTES" -ge 870 ] && [ "$CURRENT_MINUTES" -le 874 ]; then
        SCAN_TAG="14:30 尾盘抢筹"
    elif [ "$CURRENT_MINUTES" -ge 900 ] && [ "$CURRENT_MINUTES" -le 905 ]; then
        SCAN_TAG="15:00 下午收盘"
    fi

    LOG_FILE="$PROJECT_DIR/output/screener_market_${LOG_DATE}.log"
    OVERALL_EXIT_CODE=0

    # --------------------------------------------------------------------------
    # 任务 1: 全市场缠论 30F 3买 选股 (chanlun_resonance, WEEK_DAY_30F_3BUY)
    # --------------------------------------------------------------------------
    if [ "$FORCE_MODE" != "--day-scan" ] && [ "$FORCE_MODE" != "--week-scan" ]; then
        CURRENT_TIME_30F=$(date '+%Y-%m-%d %H:%M:%S')
        echo "============================================================" >> "$LOG_FILE"
        echo "【${SCAN_TAG} 全市场 30F 3买 选股扫描启动】 $CURRENT_TIME_30F" >> "$LOG_FILE"
        echo "策略: chanlun_resonance (周期模式: WEEK_DAY_30F_3BUY 周日30F共振 · 30F 3买)" >> "$LOG_FILE"
        echo "参数: -s chanlun_resonance -p WEEK_DAY_30F_3BUY -u all -w 16 --refresh" >> "$LOG_FILE"
        echo "注意: 按照预设规则，全市场扫描结果不发送K线图至微信" >> "$LOG_FILE"
        echo "============================================================" >> "$LOG_FILE"

        if command -v caffeinate >/dev/null 2>&1; then
            caffeinate -i "$PYTHON_BIN" run_scanner.py \
                -s chanlun_resonance \
                -p WEEK_DAY_30F_3BUY \
                -u all \
                -w 16 \
                --refresh \
                --no-interactive >> "$LOG_FILE" 2>&1
        else
            "$PYTHON_BIN" run_scanner.py \
                -s chanlun_resonance \
                -p WEEK_DAY_30F_3BUY \
                -u all \
                -w 16 \
                --refresh \
                --no-interactive >> "$LOG_FILE" 2>&1
        fi

        EXIT_CODE_30F=$?
        echo "【全市场 30F 3买 选股完成】 $(date '+%Y-%m-%d %H:%M:%S') Exit Code: $EXIT_CODE_30F" >> "$LOG_FILE"
        if [ $EXIT_CODE_30F -ne 0 ]; then
            OVERALL_EXIT_CODE=$EXIT_CODE_30F
        fi
    fi

    # --------------------------------------------------------------------------
    # 任务 2: 全市场缠论 DAY(日线) 3买 选股 (chanlun_resonance, MONTH_WEEK_DAY_3BUY)
    # --------------------------------------------------------------------------
    if [ "$FORCE_MODE" != "--30f-scan" ] && [ "$FORCE_MODE" != "--week-scan" ]; then
        CURRENT_TIME_DAY=$(date '+%Y-%m-%d %H:%M:%S')
        echo "============================================================" >> "$LOG_FILE"
        echo "【${SCAN_TAG} 全市场 日线(DAY) 3买 选股扫描启动】 $CURRENT_TIME_DAY" >> "$LOG_FILE"
        echo "策略: chanlun_resonance (周期模式: MONTH_WEEK_DAY_3BUY 月周日共振 · 日线 3买)" >> "$LOG_FILE"
        echo "参数: -s chanlun_resonance -p MONTH_WEEK_DAY_3BUY -u all -w 16 --refresh" >> "$LOG_FILE"
        echo "注意: 按照预设规则，全市场扫描结果不发送K线图至微信" >> "$LOG_FILE"
        echo "============================================================" >> "$LOG_FILE"

        if command -v caffeinate >/dev/null 2>&1; then
            caffeinate -i "$PYTHON_BIN" run_scanner.py \
                -s chanlun_resonance \
                -p MONTH_WEEK_DAY_3BUY \
                -u all \
                -w 16 \
                --refresh \
                --no-interactive >> "$LOG_FILE" 2>&1
        else
            "$PYTHON_BIN" run_scanner.py \
                -s chanlun_resonance \
                -p MONTH_WEEK_DAY_3BUY \
                -u all \
                -w 16 \
                --refresh \
                --no-interactive >> "$LOG_FILE" 2>&1
        fi

        EXIT_CODE_DAY=$?
        echo "【全市场 日线(DAY) 3买 选股完成】 $(date '+%Y-%m-%d %H:%M:%S') Exit Code: $EXIT_CODE_DAY" >> "$LOG_FILE"
        if [ $EXIT_CODE_DAY -ne 0 ]; then
            OVERALL_EXIT_CODE=$EXIT_CODE_DAY
        fi
    fi

    # --------------------------------------------------------------------------
    # 任务 3: 全市场缠论 WEEK(周线) 3买 选股 (chanlun_resonance, SEASON_MONTH_WEEK_3BUY)
    # --------------------------------------------------------------------------
    if [ "$FORCE_MODE" != "--30f-scan" ] && [ "$FORCE_MODE" != "--day-scan" ]; then
        CURRENT_TIME_WEEK=$(date '+%Y-%m-%d %H:%M:%S')
        echo "============================================================" >> "$LOG_FILE"
        echo "【${SCAN_TAG} 全市场 周线(WEEK) 3买 选股扫描启动】 $CURRENT_TIME_WEEK" >> "$LOG_FILE"
        echo "策略: chanlun_resonance (周期模式: SEASON_MONTH_WEEK_3BUY 季月周共振 · 周线 3买)" >> "$LOG_FILE"
        echo "参数: -s chanlun_resonance -p SEASON_MONTH_WEEK_3BUY -u all -w 16 --refresh" >> "$LOG_FILE"
        echo "注意: 按照预设规则，全市场扫描结果不发送K线图至微信" >> "$LOG_FILE"
        echo "============================================================" >> "$LOG_FILE"

        if command -v caffeinate >/dev/null 2>&1; then
            caffeinate -i "$PYTHON_BIN" run_scanner.py \
                -s chanlun_resonance \
                -p SEASON_MONTH_WEEK_3BUY \
                -u all \
                -w 16 \
                --refresh \
                --no-interactive >> "$LOG_FILE" 2>&1
        else
            "$PYTHON_BIN" run_scanner.py \
                -s chanlun_resonance \
                -p SEASON_MONTH_WEEK_3BUY \
                -u all \
                -w 16 \
                --refresh \
                --no-interactive >> "$LOG_FILE" 2>&1
        fi

        EXIT_CODE_WEEK=$?
        echo "【全市场 周线(WEEK) 3买 选股完成】 $(date '+%Y-%m-%d %H:%M:%S') Exit Code: $EXIT_CODE_WEEK" >> "$LOG_FILE"
        if [ $EXIT_CODE_WEEK -ne 0 ]; then
            OVERALL_EXIT_CODE=$EXIT_CODE_WEEK
        fi
    fi

    # macOS 桌面横幅提醒
    if command -v osascript >/dev/null 2>&1; then
        if [ $OVERALL_EXIT_CODE -eq 0 ]; then
            osascript -e "display notification \"A股全市场缠论3买扫描(${SCAN_TAG}: 30F + 日线 + 周线)已完成，报表已生成！\" with title \"easy_tdx 选股提醒\""
        else
            osascript -e "display notification \"全市场选股执行异常(${SCAN_TAG})，请查看日志！\" with title \"easy_tdx 异常提醒\""
        fi
    fi
    exit $OVERALL_EXIT_CODE

# ==============================================================================
# 分支 B: 交易时间内 (09:25-11:30, 12:55-15:00) 盘中推送 watchlist 缠论K线至微信
# ==============================================================================
elif [ "$FORCE_MODE" = "--watchlist" ] || \
     ( [ "$CURRENT_MINUTES" -ge 565 ] && [ "$CURRENT_MINUTES" -le 690 ] ) || \
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
# 分支 C: 非交易时间且非扫描时段
# ==============================================================================
else
    echo "$CURRENT_TIME [SKIP] 当前时间 (${CURRENT_H}:${CURRENT_M}) 不在交易时段且非全市场定时扫描时间 (09:25 / 11:30 / 14:30 / 15:00)，跳过执行。"
    exit 0
fi
