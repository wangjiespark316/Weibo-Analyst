#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微博扫码登录自动恢复服务（无人值守，纯 requests，不装浏览器）
=============================================================
由 weibo-health-watchdog 在连续多轮确认 Cookie 失效（COOKIE_INVALID）后按需启动。
本脚本 --daemon 流程：
  1. 先复核当前 Cookie 是否已恢复（避免无谓推码）；
  2. 走 passport.weibo.com 网页版扫码协议生成二维码（手机微博 App 扫码）；
  3. 把二维码 PNG 推送到飞书群；每 ~150s 未扫则自动作废旧码、生成新码重推；
  4. 扫码成功后收集 passport 票据，经 m.weibo.cn 补全移动端 Cookie；
  5. 用最终 Cookie 经住宅代理验证 data.login=True / uid，才写回 .env（先备份）；
  6. 重启 weibo-scheduler / weibo-api 让子进程加载新 Cookie，飞书群推恢复通知。

安全约定：日志与通知只打印 Cookie 长度 / 键数 / 状态，绝不打印 Cookie 值。
依赖：requests（venv 已装）；二维码本身由微博返回，无需本地生成。

用法：
  .venv/bin/python scripts/weibo_qr_login.py --daemon      # 看门狗调用的常驻恢复流程
  .venv/bin/python scripts/weibo_qr_login.py --check       # 仅复核当前 Cookie 登录态
"""
import os
import sys
import json
import time
import shutil
import argparse
import datetime
import traceback
import requests

ENV_PATH = "/opt/Weibo-Analyst/.env"
LOG_DIR = "/opt/Weibo-Analyst/logs"
LOG = os.path.join(LOG_DIR, "weibo_qr_login.log")
QR_PNG = os.path.join(LOG_DIR, "weibo_qr.png")

# ---- passport.weibo.com 扫码协议常量（对照 jackwener/weibo-cli）----
PASSPORT_URL = "https://passport.weibo.com"
SSO_SIGNIN_URL = PASSPORT_URL + "/sso/signin"
QR_IMAGE_URL = PASSPORT_URL + "/sso/v2/qrcode/image"
QR_CHECK_URL = PASSPORT_URL + "/sso/v2/qrcode/check"
MBASE = "https://m.weibo.cn"
QR_ENTRY = "miniblog"
QR_SOURCE = "miniblog"
QR_REDIRECT = "https://weibo.com/"
QR_VERSION = "20250520"

RETCODE_SUCCESS = 20000000
RETCODE_NOT_SCANNED = 50114001
RETCODE_SCANNED = 50114002
RETCODE_EXPIRED = 50114004

POLL_INTERVAL = 2          # 扫码状态轮询间隔（秒）
QR_LIFETIME = 150          # 单张二维码等待时长（秒），过期前主动刷新
MAX_TOTAL = 1200           # 整个恢复流程最长等待（秒，约 20 分钟）
HTTP_TIMEOUT = 25

BJ = datetime.timezone(datetime.timedelta(hours=8))

DESKTOP_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36")
MOBILE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
             "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 "
             "Mobile/15E148 Safari/604.1")

PASSPORT_HEADERS = {
    "User-Agent": DESKTOP_UA,
    "sec-ch-ua": '"Not:A-Brand";v="99", "Google Chrome";v="145", "Chromium";v="145"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "x-requested-with": "XMLHttpRequest",
    "Referer": PASSPORT_URL + "/sso/signin?entry=miniblog&source=miniblog&url=https://weibo.com/",
}
MOBILE_HEADERS = {
    "User-Agent": MOBILE_UA,
    "Accept": "application/json, text/plain, */*",
    "Referer": MBASE + "/",
    "X-Requested-With": "XMLHttpRequest",
}


def now_bj():
    return datetime.datetime.now(BJ)


def log(s):
    line = "[%s] %s" % (now_bj().strftime("%Y-%m-%d %H:%M:%S"), s)
    print(line, flush=True)
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


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


def proxies_for(proxy):
    """requests 远程解析 DNS：socks5:// -> socks5h://；http(s) 原样。"""
    if not proxy:
        return None
    p = proxy.strip()
    if p.startswith("socks5://"):
        p = "socks5h://" + p[len("socks5://"):]
    elif p.startswith("socks5h://"):
        pass
    return {"http": p, "https": p}


# ---------------- 飞书 ----------------
def feishu_token(app, sec):
    r = requests.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        headers={"Content-Type": "application/json; charset=utf-8"},
        json={"app_id": app, "app_secret": sec}, timeout=HTTP_TIMEOUT)
    j = r.json()
    if j.get("code") != 0:
        raise RuntimeError("feishu token failed: %s" % j.get("code"))
    return j["tenant_access_token"]


def feishu_send_text(token, chat, text):
    r = requests.post(
        "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
        headers={"Authorization": "Bearer " + token,
                 "Content-Type": "application/json; charset=utf-8"},
        json={"receive_id": chat, "msg_type": "text",
              "content": json.dumps({"text": text}, ensure_ascii=False)},
        timeout=HTTP_TIMEOUT)
    return r.json()


def feishu_upload_image(token, png_bytes):
    r = requests.post(
        "https://open.feishu.cn/open-apis/im/v1/images",
        headers={"Authorization": "Bearer " + token},
        data={"image_type": "message"},
        files={"image": ("weibo_qr.png", png_bytes, "image/png")},
        timeout=HTTP_TIMEOUT)
    j = r.json()
    if j.get("code") != 0:
        raise RuntimeError("feishu image upload failed: %s %s" % (j.get("code"), j.get("msg")))
    return j["data"]["image_key"]


def feishu_send_image(token, chat, image_key):
    r = requests.post(
        "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
        headers={"Authorization": "Bearer " + token,
                 "Content-Type": "application/json; charset=utf-8"},
        json={"receive_id": chat, "msg_type": "image",
              "content": json.dumps({"image_key": image_key}, ensure_ascii=False)},
        timeout=HTTP_TIMEOUT)
    return r.json()


# ---------------- 登录态复核 ----------------
def check_login(cookie, proxy):
    """经住宅代理 GET m.weibo.cn/api/config，返回 (login:bool, uid)。"""
    try:
        headers = dict(MOBILE_HEADERS)
        if cookie:
            headers["Cookie"] = cookie
        r = requests.get(MBASE + "/api/config",
                         headers=headers,
                         proxies=proxies_for(proxy),
                         timeout=HTTP_TIMEOUT)
        j = r.json()
        if j.get("ok") != 1:
            return False, None
        data = j.get("data") or {}
        uid = data.get("uid")
        if not uid:
            u = data.get("user")
            uid = u.get("id") if isinstance(u, dict) else None
        return bool(data.get("login")), uid
    except Exception as e:
        log("WARN check_login: %s" % e)
        return False, None


# ---------------- 扫码协议 ----------------
def make_qr():
    """新建一个 passport 会话并生成二维码。
    返回 (session, qrid, png_bytes)。"""
    s = requests.Session()
    s.headers.update(PASSPORT_HEADERS)
    # 1) 取 X-CSRF-TOKEN
    r = s.get(SSO_SIGNIN_URL,
              params={"entry": QR_ENTRY, "source": QR_SOURCE, "url": QR_REDIRECT},
              timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    csrf = s.cookies.get("X-CSRF-TOKEN")
    if not csrf:
        raise RuntimeError("未获取到 X-CSRF-TOKEN")
    s.headers["x-csrf-token"] = csrf
    # 2) 取二维码
    r = s.get(QR_IMAGE_URL, params={"entry": QR_ENTRY, "size": "180"},
              timeout=HTTP_TIMEOUT)
    j = r.json()
    if j.get("retcode") != RETCODE_SUCCESS:
        raise RuntimeError("取二维码失败 retcode=%s msg=%s" % (j.get("retcode"), j.get("msg")))
    qrid = j["data"]["qrid"]
    image_url = j["data"]["image"]
    # 3) 下载二维码 PNG
    ir = s.get(image_url, timeout=HTTP_TIMEOUT)
    if ir.status_code != 200 or not ir.content:
        raise RuntimeError("二维码图片下载失败 http=%s" % ir.status_code)
    png = ir.content
    try:
        with open(QR_PNG, "wb") as f:
            f.write(png)
        os.chmod(QR_PNG, 0o600)
    except Exception:
        pass
    return s, qrid, png


def poll_qr(session, qrid, lifetime):
    """在同一会话内轮询扫码状态，最长 lifetime 秒。
    返回 ("ok", cross_url, alt) / ("expired",...) / ("timeout",...)。"""
    deadline = time.time() + lifetime
    last = None
    while time.time() < deadline:
        try:
            r = session.get(QR_CHECK_URL,
                            params={"entry": QR_ENTRY, "source": QR_SOURCE,
                                    "url": QR_REDIRECT, "qrid": qrid,
                                    "rid": "", "ver": QR_VERSION},
                            timeout=HTTP_TIMEOUT)
            j = r.json()
        except Exception as e:
            log("WARN poll 请求异常: %s" % e)
            time.sleep(POLL_INTERVAL)
            continue
        ret = j.get("retcode")
        msg = j.get("msg", "")
        if ret != last:
            log("扫码状态 retcode=%s msg=%s" % (ret, msg))
            last = ret
        if ret == RETCODE_SUCCESS:
            data = j.get("data") or {}
            return "ok", data.get("url", ""), data.get("alt", "")
        if ret == RETCODE_EXPIRED:
            return "expired", None, None
        # 50114001 未扫 / 50114002 已扫待确认：继续等
        time.sleep(POLL_INTERVAL)
    return "timeout", None, None


def collect_passport_cookies(session, cross_url, alt, proxy):
    """扫码成功后收集 passport 票据 + crossdomain + alt 重定向链 Cookie。
    重要：这些换票请求必须走住宅代理，使登录会话与后续 m 域使用同一出口 IP，
    避免机房直连触发微博异地风控导致 SUB 被踢。"""
    cookies = {}
    for c in session.cookies:
        cookies[c.name] = c.value
    proxies = proxies_for(proxy)
    headers = {"User-Agent": DESKTOP_UA,
               "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}
    if cross_url:
        try:
            with requests.Session() as cs:
                cs.headers.update(headers)
                if proxies:
                    cs.proxies.update(proxies)
                cs.get(cross_url, allow_redirects=True, timeout=HTTP_TIMEOUT)
                for c in cs.cookies:
                    cookies[c.name] = c.value
        except Exception as e:
            log("WARN crossdomain follow: %s" % e)
    if alt:
        try:
            alt_url = ("https://login.sina.com.cn/sso/login.php?entry=miniblog&alt=%s"
                       "&returntype=TEXT" % alt)
            with requests.Session() as as_:
                as_.headers.update(headers)
                if proxies:
                    as_.proxies.update(proxies)
                as_.get(alt_url, allow_redirects=True, timeout=HTTP_TIMEOUT)
                for c in as_.cookies:
                    cookies[c.name] = c.value
        except Exception as e:
            log("WARN alt exchange: %s" % e)
    return cookies


def build_mobile_cookies(passport_cookies, proxy):
    """用移动 UA 会话经住宅代理补全 m.weibo.cn 域 Cookie，并验证登录态。
    返回 (cookie_dict, login, uid, cookie_header)。"""
    s = requests.Session()
    s.headers.update(MOBILE_HEADERS)
    s.proxies.update(proxies_for(proxy) or {})
    # 先种 passport 票据（SUB/SUBP 等对 m.weibo.cn 生效）
    for k, v in passport_cookies.items():
        s.cookies.set(k, v, domain=".weibo.cn", path="/")
    # 1) 先访问首页种访客 Cookie
    s.get(MBASE + "/", timeout=HTTP_TIMEOUT)
    # 2) config 触发登录态并补全移动端 Cookie
    r = s.get(MBASE + "/api/config", timeout=HTTP_TIMEOUT)
    j = r.json()
    data = j.get("data") or {}
    login = bool(data.get("login"))
    uid = data.get("uid")
    if not uid:
        u = data.get("user")
        uid = u.get("id") if isinstance(u, dict) else None
    final = {}
    for c in s.cookies:
        final[c.name] = c.value
    # 兜底：会话里没带到的关键票据（SUB/SUBP）
    for k, v in passport_cookies.items():
        final.setdefault(k, v)
    header = "; ".join("%s=%s" % (k, v) for k, v in final.items())
    return final, login, uid, header


def verify_cookie_header(cookie_header, proxy):
    """用最终 Cookie 串再验证一次，返回 (login, uid)。"""
    headers = dict(MOBILE_HEADERS)
    headers["Cookie"] = cookie_header
    r = requests.get(MBASE + "/api/config", headers=headers,
                     proxies=proxies_for(proxy), timeout=HTTP_TIMEOUT)
    j = r.json()
    data = j.get("data") or {}
    uid = data.get("uid")
    if not uid:
        u = data.get("user")
        uid = u.get("id") if isinstance(u, dict) else None
    return bool(data.get("login")), uid


def write_env_cookie(new_cookie):
    """备份后按行替换 WEIBO_COOKIE，返回备份文件名。"""
    ts = now_bj().strftime("%Y%m%d-%H%M%S")
    backup = ENV_PATH + ".bak.cookie" + ts
    shutil.copy2(ENV_PATH, backup)
    try:
        os.chmod(backup, 0o600)
    except Exception:
        pass
    lines = open(ENV_PATH, encoding="utf-8").read().splitlines()
    out, found = [], False
    for ln in lines:
        if ln.strip().startswith("WEIBO_COOKIE="):
            out.append("WEIBO_COOKIE=" + new_cookie)
            found = True
        else:
            out.append(ln)
    if not found:
        out.append("WEIBO_COOKIE=" + new_cookie)
    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    os.chmod(ENV_PATH, 0o600)
    return os.path.basename(backup)


def restart_services():
    """写回后重启 scheduler/api，使子进程重新加载新 Cookie。"""
    import subprocess
    p = subprocess.run(["systemctl", "restart",
                        "weibo-scheduler.service", "weibo-api.service"],
                       capture_output=True, text=True, timeout=90)
    return p.returncode, (p.stderr or "")[:200]


# ---------------- daemon 主流程 ----------------
def daemon(force=False):
    env = load_env()
    proxy = env.get("WEIBO_PROXY", "")
    cookie = env.get("WEIBO_COOKIE", "")
    app, sec, chat = env.get("FEISHU_APP_ID"), env.get("FEISHU_APP_SECRET"), env.get("FEISHU_CHAT_ID")
    if not (app and sec and chat):
        log("FATAL 缺少飞书凭证/群配置，无法推码")
        return 3
    token = feishu_token(app, sec)

    # 0) 复核：当前 Cookie 仍登录则直接退出，不打扰（--force 跳过，用于手动刷新/测试）
    if not force and cookie:
        login, uid = check_login(cookie, proxy)
        if login:
            log("复核当前 Cookie 已登录 uid=%s，无需扫码，退出" % uid)
            return 0
        log("复核当前 Cookie 未登录，启动扫码恢复")
    elif force:
        log("--force 强制扫码模式：跳过登录态复核")

    feishu_send_text(
        token, chat,
        "⚠️ 微博 Cookie 已失效，已自动发起扫码登录。\n"
        "请在 20 分钟内用【微博 App → 我的 → 扫一扫】扫描下方二维码并确认登录；"
        "二维码约 2 分钟自动刷新一次，请以最新一张为准。")

    deadline = time.time() + MAX_TOTAL
    qr_no = 0
    while time.time() < deadline:
        qr_no += 1
        try:
            session, qrid, png = make_qr()
        except Exception as e:
            log("WARN 生成二维码失败(%s)，%ds 后重试" % (e, 10))
            time.sleep(10)
            continue
        try:
            image_key = feishu_upload_image(token, png)
            tip = "【第 %d 张】请用微博 App 扫码确认登录" % qr_no if qr_no > 1 \
                else "👉 扫码登录二维码（微博 App 扫一扫）"
            feishu_send_text(token, chat, tip)
            feishu_send_image(token, chat, image_key)
        except Exception as e:
            log("WARN 飞书推码失败: %s" % e)
        log("已推送第 %d 张二维码，等待扫码（最长 %ds）" % (qr_no, QR_LIFETIME))

        status, cross_url, alt = poll_qr(session, qrid, QR_LIFETIME)
        if status != "ok":
            log("第 %d 张二维码结果=%s，准备刷新" % (qr_no, status))
            continue

        # 扫码成功：收集票据 + 补全 m 域 + 验证 + 写回
        try:
            passport = collect_passport_cookies(session, cross_url, alt, proxy)
            if not passport.get("SUB"):
                log("扫码成功但未取到 SUB 票据，重试新码")
                continue
            final, login, uid, header = build_mobile_cookies(passport, proxy)
            if not login:
                # 会话内验证未登录，再用最终 Cookie 串独立验证一次
                login, uid = verify_cookie_header(header, proxy)
            if not login:
                log("扫码后验证仍未登录，重试新码")
                continue
            backup = write_env_cookie(header)
            log("Cookie 已写回 len=%d keys=%d backup=%s uid=%s"
                % (len(header), len(final), backup, uid))
            rc, err = restart_services()
            if rc != 0:
                log("ERROR 重启服务失败 rc=%s %s" % (rc, err))
                feishu_send_text(
                    token, chat,
                    "✅ 微博扫码登录已完成、Cookie 已写回，但采集服务重启失败，请人工检查。")
                return 4
            feishu_send_text(
                token, chat,
                "✅ 微博登录态已自动恢复：扫码成功，新 Cookie 已生效（uid=%s），"
                "采集服务已重启，自动采集可继续。\n恢复时间：%s"
                % (uid, now_bj().strftime("%Y-%m-%d %H:%M:%S")))
            log("DONE 登录态恢复 uid=%s" % uid)
            return 0
        except Exception as e:
            log("WARN 扫码后处理异常: %s\n%s" % (e, traceback.format_exc()))
            time.sleep(5)

    feishu_send_text(
        token, chat,
        "⏳ 微博扫码登录等待超时（20 分钟内未检测到扫码确认），本次已停止。"
        "看门狗稍后会在确认 Cookie 仍失效时再次推送二维码。")
    log("等待扫码超时，退出")
    return 2


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--daemon", action="store_true", help="无人值守扫码恢复流程")
    ap.add_argument("--force", action="store_true", help="配合 --daemon 跳过登录复核，强制推码（手动刷新/测试）")
    ap.add_argument("--check", action="store_true", help="仅复核当前 Cookie 登录态")
    args = ap.parse_args()
    if args.check:
        env = load_env()
        login, uid = check_login(env.get("WEIBO_COOKIE", ""), env.get("WEIBO_PROXY", ""))
        print("login=%s uid=%s" % (login, uid))
        return 0 if login else 1
    if args.daemon:
        return daemon(force=args.force)
    ap.print_help()
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log("FATAL: %s\n%s" % (e, traceback.format_exc()))
        sys.exit(1)
