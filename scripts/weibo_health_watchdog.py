#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微博综合健康看门狗（云端，不依赖本地电脑）。
定时经手机住宅 socks5 隧道，带 Cookie 请求 m.weibo.cn/api/config，一次探测同时覆盖：
  1) 隧道是否可用；2) /etc/hosts 固定的微博 IP 是否仍有效；3) Cookie 登录态 (data.login)。
仅在「状态变化」时由 codex-bridge 发飞书群：健康->异常发告警、异常->健康发恢复；
同一异常持续超过 REMIND_AFTER 秒会再提醒一次，避免告警沉底。
只用标准库 + curl（探测与发群均走 curl subprocess）。
"""
import os, sys, json, subprocess, datetime, traceback

ENV_PATH = "/opt/Weibo-Analyst/.env"
LOG = "/opt/Weibo-Analyst/logs/weibo_health.log"
STATE = "/opt/Weibo-Analyst/logs/weibo_health.state"
REMIND_AFTER = 6 * 3600
BJ = datetime.timezone(datetime.timedelta(hours=8))
UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
      "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1")


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


def probe(proxy, cookie):
    """返回 (status, detail)；status ∈ HEALTHY / COOKIE_INVALID / LINK_DOWN。"""
    cmd = ["curl", "-x", proxy, "-s", "-m", "15",
           "-H", "User-Agent: " + UA,
           "-H", "X-Requested-With: XMLHttpRequest",
           "-H", "Cookie: " + cookie,
           "https://m.weibo.cn/api/config"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    except subprocess.TimeoutExpired:
        return "LINK_DOWN", "请求超时（隧道断开或微博固定IP不可达）"
    body = (p.stdout or "").strip()
    if p.returncode != 0 or not body:
        return "LINK_DOWN", "curl rc=%s %s" % (p.returncode, (p.stderr or "")[:120])
    try:
        j = json.loads(body)
    except Exception:
        return "LINK_DOWN", "返回非JSON（可能被拦截/IP失效）: " + body[:120]
    data = j.get("data") or {}
    if j.get("ok") == 1 and data.get("login") is True:
        return "HEALTHY", "登录正常 uid=%s" % data.get("uid")
    if j.get("ok") == 1:
        return "COOKIE_INVALID", "data.login=%s（Cookie 已失效，需重新登录）" % data.get("login")
    return "LINK_DOWN", "响应 ok=%s: %s" % (j.get("ok"), body[:120])


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


def save_state(status, ts, detail):
    try:
        with open(STATE, "w", encoding="utf-8") as f:
            json.dump({"status": status, "ts": ts, "detail": detail}, f, ensure_ascii=False)
    except Exception as e:
        log("WARN save_state: %s" % e)


ALERT_TEXT = {
    "COOKIE_INVALID": "⚠️ 微博 Cookie 已失效，自动采集将无法获取数据。\n请重新登录微博并更新服务器 .env 的 WEIBO_COOKIE（参考之前的更新流程）。",
    "LINK_DOWN": "⚠️ 微博住宅链路异常：经手机 socks5 无法正常访问 m.weibo.cn。\n可能是隧道断开或 /etc/hosts 固定的微博IP已失效；隧道看门狗会自动尝试重连，若持续请检查小米手机 Termux 与网络。",
}


def main():
    env = load_env()
    proxy = env.get("WEIBO_PROXY", "socks5://127.0.0.1:18888")
    cookie = env.get("WEIBO_COOKIE", "")
    app, sec, chat = env.get("FEISHU_APP_ID"), env.get("FEISHU_APP_SECRET"), env.get("FEISHU_CHAT_ID")

    status, detail = probe(proxy, cookie)
    ts = now_bj().timestamp()
    prev = load_state()
    log("probe status=%s detail=%s" % (status, detail))

    recovered = status == "HEALTHY" and prev and prev.get("status") != "HEALTHY"
    new_alert = status != "HEALTHY" and (
        prev is None or prev.get("status") == "HEALTHY"
        or prev.get("status") != status
        or ts - float(prev.get("ts", 0)) >= REMIND_AFTER)

    if recovered or new_alert:
        try:
            token = get_token(app, sec)
            if recovered:
                text = "✅ 微博链路已恢复：登录态正常，自动采集可继续。\n恢复时间：%s" % now_bj().strftime("%H:%M:%S")
            else:
                text = ALERT_TEXT.get(status, "⚠️ 微博链路异常：%s" % detail) + \
                       "\n探测时间：%s\n详情：%s" % (now_bj().strftime("%Y-%m-%d %H:%M"), detail)
            r = send(token, chat, text)
            log("feishu send code=%s recovered=%s new_alert=%s" % (r.get("code"), recovered, new_alert))
        except Exception as e:
            log("WARN feishu send failed: %s" % e)

    if status == "HEALTHY":
        save_state(status, ts, detail)
    elif new_alert or prev is None:
        save_state(status, ts, detail)
    elif prev:
        save_state(status, float(prev.get("ts", ts)), detail)

    print("STATUS=%s" % status)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log("FATAL: %s\n%s" % (e, traceback.format_exc()))
        sys.exit(1)
