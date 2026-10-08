#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微博综合健康看门狗（云端，不依赖本地电脑）。
定时经住宅 socks5 隧道(N100主/手机备)，带 Cookie 请求 m.weibo.cn/api/config，一次探测同时覆盖：
  1) 隧道是否可用；2) /etc/hosts 固定的微博 IP 是否仍有效；3) Cookie 登录态 (data.login)。
仅在「状态变化」时由 codex-bridge 发飞书群：健康->异常发告警、异常->健康发恢复；
同一异常持续超过 REMIND_AFTER 秒会再提醒一次，避免告警沉底。
只用标准库 + curl（探测与发群均走 curl subprocess）。

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
BASELINE_PROBE_RETRIES = 2    # 链路基线（不带Cookie）重试次数
LOGIN_PROBE_RETRIES = 3       # 带 Cookie 登录探测重试次数
RETRY_GAP = 3                 # 重试间隔秒数
BJ = datetime.timezone(datetime.timedelta(hours=8))
UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
      "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1")

COOKIE_STATES = ("COOKIE_SUSPECT", "COOKIE_INVALID")


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
        "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
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
        "请重新登录微博并更新服务器 .env 的 WEIBO_COOKIE（参考之前的更新流程）。",
    "LINK_DOWN":
        "⚠️ 微博住宅链路异常：经住宅 socks5 隧道无法正常访问 m.weibo.cn。\n"
        "可能是隧道断开或微博固定IP已失效；隧道看门狗会自动尝试重连，"
        "若持续请检查 N100 代理/旁路由（主）或小米手机 Termux（备）。",
}


def main():
    env = load_env()
    proxy = env.get("WEIBO_PROXY", "socks5://127.0.0.1:18888")
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

    # 通知判定（COOKIE_SUSPECT 静默，不打扰）
    text = None
    if status == "HEALTHY":
        if prev_status == "COOKIE_INVALID":
            text = "✅ 微博登录态已恢复：Cookie 登录正常，自动采集可继续。\n恢复时间：%s" % \
                   now_bj().strftime("%H:%M:%S")
        elif prev_status == "LINK_DOWN":
            text = "✅ 微博住宅链路已恢复：登录态正常，自动采集可继续。\n恢复时间：%s" % \
                   now_bj().strftime("%H:%M:%S")
    elif status in ("LINK_DOWN", "COOKIE_INVALID"):
        first = prev_status != status
        remind = (now - last_notify_ts >= REMIND_AFTER) if last_notify_ts else True
        if first or remind:
            if status == "LINK_DOWN":
                text = ALERT_TEXT["LINK_DOWN"] + "\n探测时间：%s\n详情：%s" % (
                    now_bj().strftime("%Y-%m-%d %H:%M"), detail)
            else:
                mins = max(1, int((now - ts) // 60))
                text = ALERT_TEXT["COOKIE_INVALID"] + \
                       "\n已连续约 %s 分钟、经 %s 轮探测确认登录态为未登录。\n探测时间：%s\n详情：%s" % (
                           mins, count, now_bj().strftime("%Y-%m-%d %H:%M"), detail)

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
