#!/bin/bash
# ==============================================================================
# easy_tdx Mac 端自动化更新与服务重载脚本
# 
# 核心保证：
# 1. 本地增加的自选股与远端仓库自选股智能无损合并并集，杜绝覆盖；
# 2. 不使用 git checkout，安全保留所有本地更新；
# 3. 自动平滑重启后台 LaunchDaemon 服务。
# ==============================================================================

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_DIR" || exit 1

# 1. 优先选择 Python 解释器
if [ -f "$PROJECT_DIR/.venv/bin/python" ]; then
    PYTHON_BIN="$PROJECT_DIR/.venv/bin/python"
elif [ -f "$PROJECT_DIR/.venv/bin/python3" ]; then
    PYTHON_BIN="$PROJECT_DIR/.venv/bin/python3"
else
    PYTHON_BIN=$(which python3)
fi

echo "============================================================"
echo "🚀 开始拉取远端更新并同步自选股..."
echo "============================================================"

# 2. 若本地存在 watchlist.json，先创建临时副本以防冲突
BACKUP_WL="/tmp/watchlist_local_$(date +%s).json"
if [ -f "watchlist.json" ]; then
    cp watchlist.json "$BACKUP_WL"
fi

# 3. 暂存所有本地工作区变动（安全可靠，不需要 git checkout）
git stash --include-untracked >/dev/null 2>&1 || true

# 4. 安全拉取远端代码
echo "正在拉取远端最新代码 (git pull origin dev)..."
git pull origin dev || git pull

# 5. 恢复暂存的工作区文件（如有）
git stash pop >/dev/null 2>&1 || true

# 6. 核心步骤：将本地新增的自选股与远端拉取下来的 watchlist.json 智能无损合并
if [ -f "$BACKUP_WL" ] && [ -n "$PYTHON_BIN" ]; then
    echo "正在智能合并本地自选股与远端自选股 (无损并集去重)..."
    "$PYTHON_BIN" scripts/merge_watchlist.py "$BACKUP_WL"
    rm -f "$BACKUP_WL"
fi

echo "✅ 自选股与代码更新完成！"

# 7. 重启服务（若已配置 LaunchDaemon）
if [ -f "/Library/LaunchDaemons/com.easytdx.service.plist" ]; then
    echo "正在平滑重启 easy_tdx 守护服务..."
    sudo launchctl kickstart -k system/com.easytdx.service 2>/dev/null || {
        sudo launchctl bootout system/com.easytdx.service 2>/dev/null || true
        sudo launchctl bootstrap system /Library/LaunchDaemons/com.easytdx.service.plist 2>/dev/null || true
    }
    echo "✅ easy_tdx 守护服务已重启！"
fi
