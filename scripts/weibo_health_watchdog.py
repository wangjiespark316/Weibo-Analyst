#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微博综合健康看门狗（云端，不依赖本地电脑/Mac）。
定时经住宅 socks5 隧道(N100 frpc home_residential)，带 Cookie 请求 m.weibo.cn/api/config，
一次探测同时覆盖：
  1) 隧道是否可用；2) /etc/hosts 固定的微博 IP 是否仍有效；3) Cookie 登录态 (data.login)。
Cookie 失效的恢复策略（2026-10-16 方案 C 改版，彻底脱 Mac）：
  - 不启动会向飞书群刷二维码的 weibo-qr-login daemon，绝不向群推码；
  - 服务器经 frp 反向隧道 home_adb(127.0.0.1:15555 -> N100 PVE frpc -> 小米12:5555)
    直接 adb 控制小米12，幂等运行 auto_scan_via_frp.sh：
    建码 -> 推码到手机相册 -> 手机微博 App 扫码并自动点「允许登录」-> 服务器换票写回；
  - 该脚本幂等且含游戏保护：已登录立即退出；王者荣耀在前台直接退出(20)不打扰；
    手机不可达退出(21)；均静默等下一周期重试，成功后静默；
  - 失效后给 SERVER_RECOVERY_GRACE 秒静默窗口反复尝试，超窗仍未恢复（唯一已知断点是
    手机重启后 adbd 5555 重置，需人工 USB 跳板约 1 分钟）才低频发一条飞书提示。
  - LINK_DOWN 链路异常仍按状态变化/REMIND_AFTER 提醒。
只用标准库 + curl + adb（探测/发群走 curl，扫码恢复走 adb+bash，均 subprocess）。

【2026-10-08 升级】区分「链路/网络层异常」与「Cookie 登录态失效」，避免隧道抖动误报 Cookie：
  1) 先「不带 Cookie」经隧道请求 m.weibo.cn/api/config 做链路基线（公开端点，无论登录与否都应 ok=1）；
  2) 基线正常后，「带 Cookie」同端点重试 LOGIN_PROBE_RETRIES 次，全部稳定 login=False 才记 1 次 Cookie 阴性；
  3) 连续 COOKIE_FAIL_THRESHOLD 个周期（约 30 分钟）均稳定阴性，才发 Cookie 失效告警；中途任一 login=True 即清零。
  链路层失败（连不上/超时/非JSON/ok!=1，或带 Cookie 探测中夹杂传输失败）一律判 LINK_DOWN，
  不计 Cookie 阴性、不报 Cookie 失效。
"""
import os, sys, json, time, subprocess, datetime, traceback

ENV_PATH = "/opt/Weibo-Analyst/.env"
LOG = "/opt/Weibo-Analyst/logs/weibo_health.log"
STATE = "/opt/Weibo-Analyst/logs/weibo_health.state"
REMIND_AFTER = 6 * 3600
COOKIE_FAIL_THRESHOLD = 3     # 连续多少个周期稳定 login=False 才判 Cookie 失效（每周期约10分钟）
# 失效后服务器经 frp 隧道每周期幂等运行 auto_scan_via_frp.sh 静默扫码恢复；
# 给 SERVER_RECOVERY_GRACE 秒静默窗口反复尝试，窗口内不打扰、不推码；
# 超窗仍未恢复（通常是手机重启后 adbd 5555 重置、隧道/手机长期不可达）才提醒人工 USB 跳板。
SERVER_RECOVERY_GRACE = 2 * 3600
AUTO_SCAN = "/opt/Weibo-Analyst/scripts/auto_scan_via_frp.sh"
ADB_DEV = "127.0.0.1:15555"
AUTO_SCAN_TIMEOUT = 280
BASELINE_PROBE_RETRIES = 2    # 链路基线（不带Cookie）重试次数
LOGIN_PROBE_RETRIES = 3       # 带 Cookie 登录探测重试次数
RETRY_GAP = 3                 # 重试间隔秒数
BJ = datetime.timezone(datetime.timedelta(hours=8))
UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
      "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1")

COOKIE_STATES = ("COOKIE_SUSPECT", "COOKIE_INVALID")

# auto_scan_via_frp.sh 退出码 -> 可读说明
SCAN_RC = {
    0: "成功(已登录或已恢复)", 20: "游戏在前台，本轮跳过", 21: "手机不可达(隧道/手机)",
    22: "未到达验证页", 23: "确认后超时", 24: "写回后复核失败", 1: "建码失败",
}


def now_bj():
    return datetime.datetime.now(BJ)


def load_env():
    env = {}
    try:
        for line in open(ENV_PATH, encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    except Exception as e:
        log("WARN load_env: %s" % e)
    return env


def log(s):
    line = "[%s] %s" % (now_bj().strftime("%Y-%m-%d %H:%M:%S"), s)
    print(line)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def curl_json(url, extra_headers=None, body=None, timeout=25):
    cmd = ["curl", "-s", "-X", "POST" if body is not None else "GET", url,
           "-H", "Content-Type: application/json; charset=utf-8"]
    for h in (extra_headers or []):
        cmd += ["-H", h]
    if body is not None:
        cmd += ["-d", json.dumps(body, ensure_ascii=False)]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    out = (p.stdout or "").strip()
    try:
        return p.returncode, json.loads(out), out
    except Exception:
        return p.returncode, None, out


def http_get_config(proxy, cookie=None, timeout=15):
    """经 proxy GET m.weibo.cn/api/config。
    返回 ("OK", data_dict) 或 ("LINK_FAIL", reason_str)。"""
    cmd = ["curl", "-x", proxy, "-s", "-m", str(timeout),
           "-H", "User-Agent: " + UA,
           "-H", "X-Requested-With: XMLHttpRequest"]
    if cookie is not None:
        cmd += ["-H", "Cookie: " + cookie]
    cmd.append("https://m.weibo.cn/api/config")
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 5)
    except subprocess.TimeoutExpired:
        return "LINK_FAIL", "请求超时（隧道断开或微博固定IP不可达）"
    body = (p.stdout or "").strip()
    if p.returncode != 0 or not body:
        return "LINK_FAIL", "curl rc=%s %s" % (p.returncode, (p.stderr or "")[:120])
    try:
        j = json.loads(body)
    except Exception:
        return "LINK_FAIL", "返回非JSON（可能被拦截/IP失效）: " + body[:120]
    if j.get("ok") == 1:
        return "OK", (j.get("data") or {})
    return "LINK_FAIL", "响应 ok=%s: %s" % (j.get("ok"), body[:120])


def run_probe(proxy, cookie):
    """返回 (raw_status, detail, cookie_negative)
    raw_status ∈ HEALTHY / LINK_DOWN / COOKIE_NEGATIVE；
    COOKIE_NEGATIVE 表示链路正常、但本轮带 Cookie 多次稳定 login=False（一次有效阴性）。"""
    # 1) 链路基线（不带 Cookie）
    base_ok = False
    reason = "链路基线失败"
    for i in range(BASELINE_PROBE_RETRIES):
        kind, payload = http_get_config(proxy, cookie=None)
        if kind == "OK":
            base_ok = True
            break
        reason = payload
        time.sleep(RETRY_GAP)
    if not base_ok:
        return "LINK_DOWN", reason, 0

    # 2) 带 Cookie 登录探测，重试多次
    false_n = 0
    transport_fail = None
    for i in range(LOGIN_PROBE_RETRIES):
        kind, payload = http_get_config(proxy, cookie=cookie)
        if kind == "OK":
            if payload.get("login") is True:
                uid = payload.get("uid")
                if not uid:
                    u = payload.get("user")
                    uid = u.get("id") if isinstance(u, dict) else None
                return "HEALTHY", "登录正常 uid=%s" % uid, 0
            false_n += 1
        else:
            transport_fail = payload
        if i < LOGIN_PROBE_RETRIES - 1:
            time.sleep(RETRY_GAP)

    # 3) 汇总
    if false_n == LOGIN_PROBE_RETRIES:
        return "COOKIE_NEGATIVE", "链路正常，但连续 %d 次 data.login=False" % false_n, 1
    if false_n == 0:
        return "LINK_DOWN", transport_fail or "登录探测传输异常", 0
    # 既有 login=False 又有传输失败 → 链路抖动，按 LINK_DOWN（不计 Cookie 阴性）
    return "LINK_DOWN", "链路抖动（%d 次 login=False、%d 次传输失败：%s）" % (
        false_n, LOGIN_PROBE_RETRIES - false_n, transport_fail), 0


def adb_reconnect(retries=3):
    """经 frp 隧道保活 adb 连接；返回 True 表示设备在线。"""
    try:
        subprocess.run(["adb", "start-server"], capture_output=True, timeout=30)
    except Exception:
        pass
    for _ in range(retries):
        try:
            p = subprocess.run(["adb", "-s", ADB_DEV, "get-state"],
                               capture_output=True, text=True, timeout=15)
            if p.returncode == 0 and "device" in (p.stdout or ""):
                return True
            subprocess.run(["adb", "connect", ADB_DEV], capture_output=True, timeout=20)
        except Exception:
            pass
        time.sleep(2)
    return False


def attempt_auto_scan():
    """Cookie 失效：经 frp 隧道控制小米12 静默扫码恢复。
    返回 (rc, tail)。幂等、不推码到群；游戏前台/手机不可达自动跳过。"""
    online = adb_reconnect()
    if not online:
        log("auto_scan: 设备 %s 不在线，跳过本轮（不建码）" % ADB_DEV)
        return 21, SCAN_RC[21]
    try:
        p = subprocess.run(["bash", AUTO_SCAN], capture_output=True,
                           text=True, timeout=AUTO_SCAN_TIMEOUT)
        out = ((p.stdout or "") + (p.stderr or "")).strip().splitlines()
        tail = " | ".join(out[-6:])
        return p.returncode, tail
    except subprocess.TimeoutExpired:
        return -1, "auto_scan 超时(%ss)" % AUTO_SCAN_TIMEOUT
    except Exception as e:
        return -2, "auto_scan 异常: %s" % e


def get_token(app, sec):
    rc, r, raw = curl_json(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        body={"app_id": app, "app_secret": sec})
    if not r or r.get("code") != 0:
        raise RuntimeError("tenant_token failed: %s" % raw[:200])
    return r["tenant_access_token"]


def send(token, chat, text):
    body = {"receive_id": chat, "msg_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False)}
    rc, r, raw = curl_json(
        "https://open.feishu.cn/open-apis/im/v1/messages?receive_id=chat_id",
        extra_headers=["Authorization: Bearer " + token], body=body)
    return r if r else {"code": -99, "msg": raw[:200]}


def load_state():
    try:
        return json.load(open(STATE, encoding="utf-8"))
    except Exception:
        return None


def save_state(state):
    try:
        with open(STATE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
    except Exception as e:
        log("WARN save_state: %s" % e)


ALERT_TEXT = {
    "COOKIE_INVALID":
        "⚠️ 微博 Cookie 登录态已失效（已连续多轮确认，非网络抖动），自动采集将无法获取数据。\n"
        "服务器经 frp 隧道自动控制小米12 扫码恢复，在 2 小时窗口内多次尝试均未成功。\n"
        "最常见原因是小米12 重启后 adbd 5555 无线调试被重置——请将手机用 USB 连一次 N100 或电脑、"
        "重新执行 adb tcpip 5555（约 1 分钟，之后恢复全自动）；也可确认手机与 N100 同 WiFi、微博 App 仍登录。\n"
        "恢复后系统自动停止提醒，无需手动改 .env。",
    "LINK_DOWN":
        "⚠️ 微博住宅链路异常：经住宅 socks5 隧道无法正常访问 m.weibo.cn。\n"
        "可能是隧道断开或微博固定IP已失效；隧道看门狗会自动尝试重连，"
        "若持续请检查 N100 上的 frpc/socks5 容器与家庭宽带。",
}


def main():
    env = load_env()
    proxy = env.get("WEIBO_PROXY", "socks5://127.0.0.1:18889")
    cookie = env.get("WEIBO_COOKIE", "")
    app = env.get("FEISHU_APP_ID")
    sec = env.get("FEISHU_APP_SECRET")
    chat = env.get("FEISHU_CHAT_ID")

    prev = load_state() or {}
    prev_status = prev.get("status")
    prev_count = int(prev.get("cookie_fail_count", 0) or 0)
    prev_ts = float(prev.get("ts", 0) or 0)
    last_notify_ts = float(prev.get("last_notify_ts", 0) or 0)

    raw, detail, neg = run_probe(proxy, cookie)
    now = now_bj().timestamp()

    # 聚合 cookie_fail_count 与最终对外状态
    if raw == "HEALTHY":
        status, count = "HEALTHY", 0
    elif raw == "LINK_DOWN":
        status, count = "LINK_DOWN", prev_count  # 链路断不动 Cookie 计数
    else:  # COOKIE_NEGATIVE
        count = prev_count + 1
        status = "COOKIE_INVALID" if count >= COOKIE_FAIL_THRESHOLD else "COOKIE_SUSPECT"

    # 连续异常起始时间（SUSPECT→INVALID 视为同一过程，不重置）
    continuous = (prev_status == status) or (
        prev_status in COOKIE_STATES and status in COOKIE_STATES)
    if status == "HEALTHY":
        ts = now
    elif continuous and prev_ts:
        ts = prev_ts
    else:
        ts = now

    log("raw=%s status=%s cookie_fail_count=%s detail=%s" % (raw, status, count, detail))

    # Cookie 确认失效：经 frp 隧道静默控制小米12 自动扫码恢复（不推码到群、不打扰游戏）
    if status == "COOKIE_INVALID":
        rc, tail = attempt_auto_scan()
        log("auto_scan rc=%s (%s) tail=%s" % (
            rc, SCAN_RC.get(rc, "未知"), tail.replace("\n", " ")))

    # 通知判定（成功/恢复一律静默；COOKIE_SUSPECT 静默；
    # COOKIE_INVALID 先给服务器自动恢复静默窗口，超窗仍未恢复才低频提醒）
    text = None
    if status == "LINK_DOWN":
        first = prev_status != status
        remind = (now - last_notify_ts >= REMIND_AFTER) if last_notify_ts else True
        if first or remind:
            text = ALERT_TEXT["LINK_DOWN"] + "\n探测时间：%s\n详情：%s" % (
                now_bj().strftime("%Y-%m-%d %H:%M"), detail)
    elif status == "COOKIE_INVALID":
        elapsed = now - ts
        if elapsed < SERVER_RECOVERY_GRACE:
            log("cookie invalid within server recovery grace window (%ds/%ds), silent" % (
                int(elapsed), SERVER_RECOVERY_GRACE))
        else:
            remind = (now - last_notify_ts >= REMIND_AFTER) if last_notify_ts else True
            if remind:
                mins = max(1, int(elapsed // 60))
                text = ALERT_TEXT["COOKIE_INVALID"] + \
                       "\n已连续约 %s 分钟、经 %s 轮探测确认未登录。\n探测时间：%s\n详情：%s" % (
                           mins, count, now_bj().strftime("%Y-%m-%d %H:%M"), detail)
    # HEALTHY（含从异常恢复）一律静默，不打扰用户。

    new_last_notify = last_notify_ts
    if text is not None:
        try:
            token = get_token(app, sec)
            r = send(token, chat, text)
            log("feishu send code=%s status=%s" % (r.get("code"), status))
            if r and r.get("code") == 0:
                new_last_notify = now
        except Exception as e:
            log("WARN feishu send failed: %s" % e)

    save_state({"status": status, "ts": ts, "detail": detail,
                "cookie_fail_count": count, "last_notify_ts": new_last_notify})
    print("STATUS=%s" % status)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log("FATAL: %s\n%s" % (e, traceback.format_exc()))
        sys.exit(1)
