git co .
git pull

# 重启服务（不改plist，只重启进程）
sudo launchctl kickstart -k system/com.easytdx.service

# 卸载停止
sudo launchctl bootout system/com.easytdx.service

# 加载启动
sudo launchctl bootstrap system /Library/LaunchDaemons/com.easytdx.service.plist

