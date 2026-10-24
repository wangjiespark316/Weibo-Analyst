#!/bin/bash
# =============================================================================
# 小米12 微博扫码登录 · 完整自动恢复链路（服务器端，经 frp 隧道 home_adb，幂等）
# 链路: 服务器 adb -> 127.0.0.1:15555(frps) -> N100 PVE frpc(home_adb) -> 手机 192.168.0.107:5555
# 流程: 检查登录态 -> adb 保活/手机可达 -> 唤醒解锁 -> 游戏保护 -> 建码(fork)
#       -> 推码 -> 扫一扫选图 -> 验证页点「允许登录」-> 本地轮询换票写回重启 -> 独立复核
# 安全: 不发飞书/不推码到群；检测到王者荣耀在前台立即中止，绝不打断用户；
#       已登录直接退出；屏幕设置运行后恢复原值。
# 退出码: 0=已登录或恢复成功; 20=游戏在前台中止; 21=手机不可达; 22=未到验证页;
#         23=确认后超时; 24=写回后复核失败; 1=建码失败
# =============================================================================
ADB=adb
APP=/opt/Weibo-Analyst
PY="$APP/.venv/bin/python"
DEV=127.0.0.1:15555
WORK=/opt/Weibo-Analyst/logs/auto_scan
GAME=com.tencent.tmgp.sgame
WEIBO=com.sina.weibo
mkdir -p "$WORK"
cd "$WORK" || exit 1

dev_sh() { "$ADB" -s "$DEV" shell "$@"; }
topact() { dev_sh dumpsys activity activities 2>/dev/null | grep -E "ResumedActivity" | head -1; }
py_check() { ( cd "$APP" && "$PY" scripts/weibo_qr_login.py --check 2>/dev/null ) | tail -1; }

echo "== A) 检查当前登录态（已登录则直接退出，幂等）=="
CHK=$(py_check)
echo "check: $CHK"
if echo "$CHK" | grep -q "login=True"; then
  echo "ALREADY_LOGGED_IN"
  exit 0
fi

echo "== B) frp adb 保活 + 手机可达性检查 =="
for i in 1 2 3; do
  "$ADB" connect "$DEV" >/dev/null 2>&1
  sleep 2
  if "$ADB" -s "$DEV" get-state >/dev/null 2>&1; then break; fi
  sleep 2
done
if ! "$ADB" -s "$DEV" get-state >/dev/null 2>&1; then
  echo "ABORT_PHONE_UNREACHABLE"; exit 21
fi

echo "== C) 唤醒并解锁（无密码锁屏，上滑）=="
dev_sh input keyevent KEYCODE_WAKEUP >/dev/null 2>&1
sleep 1
dev_sh input swipe 540 1900 540 500 300 >/dev/null 2>&1
sleep 1

echo "== D) 游戏保护：王者荣耀在前台则中止（不打断用户）=="
if topact | grep -q "$GAME"; then
  echo "ABORT_GAME_FOREGROUND"; exit 20
fi
# 游戏不在前台：后台清理，避免其更新/弹窗抢前台（用户未在玩，安全）
dev_sh am force-stop "$GAME" >/dev/null 2>&1

echo "== E) 保存并临时设置屏幕常亮 =="
ORIG_TIMEOUT=$(dev_sh settings get system screen_off_timeout 2>/dev/null | tr -d '\r')
ORIG_STAYON=$(dev_sh settings get global stay_on_while_plugged_in 2>/dev/null | tr -d '\r')
dev_sh settings put system screen_off_timeout 1800000 >/dev/null 2>&1
dev_sh svc power stayon true >/dev/null 2>&1
restore_screen() {
  [ -n "$ORIG_TIMEOUT" ] && dev_sh settings put system screen_off_timeout "$ORIG_TIMEOUT" >/dev/null 2>&1
  dev_sh svc power stayon false >/dev/null 2>&1
}

echo "== F) 本地建码（fork，父进程拿 base64，子进程后台轮询换票）=="
rm -f /tmp/weibo_oneoff_state.txt
( cd "$APP" && "$PY" scripts/qr_fork.py ) > qr_out.txt 2>/dev/null
if ! grep -q QRB64_BEGIN qr_out.txt; then
  echo "BUILD_FAILED"; cat qr_out.txt; restore_screen; exit 1
fi
"$PY" - <<'PYEOF'
import re, base64
t = open('/opt/Weibo-Analyst/logs/auto_scan/qr_out.txt').read()
m = re.search(r'QRB64_BEGIN\s*\n(.*?)\nQRB64_END', t, re.S)
assert m, "no base64"
b = base64.b64decode(m.group(1).strip())
open('/opt/Weibo-Analyst/logs/auto_scan/qr_new.png','wb').write(b)
print("decoded", len(b), "bytes")
PYEOF

echo "== G) 推送新码到专属相册（先删旧避免缓存）+ 媒体扫描 =="
dev_sh "mkdir -p /sdcard/Pictures/WeiboLogin; rm -f /sdcard/Pictures/WeiboLogin/qr.png" >/dev/null 2>&1
"$ADB" -s "$DEV" push qr_new.png /sdcard/Pictures/WeiboLogin/qr.png >/dev/null 2>&1
dev_sh am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d "file:///sdcard/Pictures/WeiboLogin/qr.png" >/dev/null 2>&1
sleep 1

echo "== H) 打开扫一扫并选最新二维码（动态解析控件）=="
dev_sh am start -a android.intent.action.VIEW -d "sinaweibo://qrcode" >/dev/null 2>&1
# 等待相机就绪（冷启动最多16秒），期间处理MIUI权限弹窗
CAM_READY=0
for ci in $(seq 1 8); do
  sleep 2
  ACT=$(topact)
  if echo "$ACT" | grep -q "GrantPermissionsActivity"; then
    dev_sh input tap 540 1850 >/dev/null 2>&1
    sleep 2
  fi
  if echo "$ACT" | grep -q "TakePhotoActivity"; then CAM_READY=1; break; fi
done
if [ "$CAM_READY" != "1" ]; then echo "ABORT_NO_CAMERA"; topact; restore_screen; exit 22; fi
# 动态解析相册网格：展开抽屉并点击第一张（最新二维码）
python3 "$APP/scripts/ui_pick.py" || { echo "ABORT_UI_PICK"; topact; restore_screen; exit 22; }

echo "== I) 轮询等待验证页(WeiboBrowser)，最多 24 秒 =="
GOT_VERIFY=0
for i in $(seq 1 12); do
  sleep 2
  ACT=$(topact)
  if echo "$ACT" | grep -q "$WEIBO/.browser.WeiboBrowser"; then GOT_VERIFY=1; break; fi
  if echo "$ACT" | grep -q "$GAME"; then echo "ABORT_GAME_FOREGROUND"; restore_screen; exit 20; fi
done
dev_sh screencap -p /data/local/tmp/verify.png >/dev/null 2>&1
"$ADB" -s "$DEV" pull /data/local/tmp/verify.png ./verify.png >/dev/null 2>&1
if [ "$GOT_VERIFY" != "1" ]; then
  echo "ABORT_NO_VERIFY_PAGE"; topact; restore_screen; exit 22
fi
echo "verify page reached"

echo "== J) 点橙色「允许登录」(540,1030) =="
dev_sh input tap 540 1030 >/dev/null 2>&1
sleep 3
dev_sh screencap -p /data/local/tmp/after.png >/dev/null 2>&1
"$ADB" -s "$DEV" pull /data/local/tmp/after.png ./after.png >/dev/null 2>&1

echo "== K) 轮询本地 oneoff 状态，最多 120 秒 =="
OK=0
for i in $(seq 1 40); do
  ST=$(tail -1 /tmp/weibo_oneoff_state.txt 2>/dev/null | tr -d '\r')
  echo "  [$i] $ST"
  if echo "$ST" | grep -q "SUCCESS"; then OK=1; break; fi
  if echo "$ST" | grep -qiE "FAIL|ERROR|Traceback"; then break; fi
  sleep 3
done
if [ "$OK" != "1" ]; then echo "ABORT_CONFIRM_TIMEOUT"; restore_screen; exit 23; fi

echo "== L) 独立复核 login=True =="
sleep 2
CHK2=$(py_check)
echo "final check: $CHK2"
restore_screen
if echo "$CHK2" | grep -q "login=True"; then
  echo "RECOVERED_OK"; exit 0
else
  echo "ABORT_FINAL_CHECK_FAILED"; exit 24
fi
