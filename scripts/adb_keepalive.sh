#!/bin/bash
# =============================================================================
# 服务器 -> 小米12 adb 隧道保活（经 frp home_adb，幂等，不打扰手机）
# 网络 adb 在手机 WiFi 抖动 / frpc 重启 / 手机 doze 后会断开，adb 客户端不会自动重连。
# 本脚本由 systemd timer 每 2 分钟跑一次：在线则直接退出，离线则 adb connect 重连。
# 只做 connect/get-state，不点亮屏幕、不操作前台。
# =============================================================================
export HOME=/root
DEV=127.0.0.1:15555
LOG=/var/log/weibo-adb-keepalive.log

stamp() { date "+%Y-%m-%d %H:%M:%S"; }

if adb -s "$DEV" get-state >/dev/null 2>&1; then
  exit 0
fi

echo "[$(stamp)] $DEV 离线，尝试重连" >> "$LOG"
adb start-server >/dev/null 2>&1
for i in 1 2 3; do
  adb connect "$DEV" >/dev/null 2>&1
  sleep 2
  if adb -s "$DEV" get-state >/dev/null 2>&1; then
    echo "[$(stamp)] 重连成功 (第 $i 次)" >> "$LOG"
    exit 0
  fi
  sleep 2
done
echo "[$(stamp)] 重连失败（3 次），等待下个周期" >> "$LOG"
exit 0
