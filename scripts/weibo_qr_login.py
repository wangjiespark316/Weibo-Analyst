#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微博扫码登录自动恢复服务（无人值守，纯 requests，不装浏览器）
=============================================================
由 weibo-health-watchdog 在连续多轮确认 Cookie 失效（COOKIE_INVALID）后按需启动。
本脚本 --daemon 流程：
  1. 先复核当前 Cookie 是否已恢复（避免无谓推码）；
  2. 推码前确认住宅代理可用（代理不可用不推码，避免发码后换票失败）；
  3. 走 passport.weibo.com 网页版扫码协议生成二维码（手机微博 App 扫码）；
     —— 建码 / 轮询 / 换票 / 移动端补全 / 验证「全程走同一个住宅代理出口」，
        避免机房 IP 与住宅 IP 跨地域触发微博风控导致 SUB 被快速回收；
  4. 把二维码 PNG 推送到飞书群；每 ~150s 未扫则自动作废旧码、生成新码重推；
  5. 扫码成功后收集 passport 票据，跟进 crossdomain 换票链，
     再走 sinawap 移动端 SSO（service=sinawap / entry=sinawap），让
     m.weibo.cn 签发 SSOLoginState、补全移动端 Cookie（缺这一步会 login=false）；
  6. 写回前用全新请求「连续多次」验证 data.login 稳定为 True（防止瞬时放行后被回收），
     重启服务后再独立复核一次，确认登录态持续有效，才最终判为成功；
  7. 扫码成功但登录态不稳定时：只发一条文字告警并停止，不再反复刷新二维码。

安全约定：日志与通知只打印 Cookie 长度 / 键数 / 状态，绝不打印 Cookie 值。
依赖：requests（venv 已装）；二维码本身由微博返回，无需本地生成。

用法：
  .venv/bin/python scripts/weibo_qr_login.py --daemon      # 看门狗调用的常驻恢复流程
  .venv/bin/python scripts/weibo_qr_login.py --check       # 仅复核当前 Cookie 登录态
"""
import os
import re
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
STABLE_CHECKS = 4          # 写回前连续验证次数（全部 True 才认定稳定）
STABLE_GAP = 3             # 连续验证间隔（秒）

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

# 从 returntype=TEXT / crossdomain 返回体中提取后续需要跟进的换票 URL
_CROSSDOMAIN_RE = re.compile(
    r'https?://[^\s"\'<>\\)]*(?:crossdomain|wbsso|sso/login)[^\s"\'<>\\)]*',
    re.IGNORECASE)


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


def proxy_ready(proxy):
    """推码前确认住宅代理可用且能访问 m 域。"""
    try:
        r = requests.get(MBASE + "/api/config",
                         headers=dict(MOBILE_HEADERS),
                         proxies=proxies_for(proxy),
                         timeout=15)
        return r.status_code == 200
    except Exception as e:
        log("WARN proxy_ready: %s" % e)
        return False


# ---------------- 扫码协议 ----------------
def make_qr(proxy):
    """新建一个 passport 会话并生成二维码（全程走住宅代理）。
    返回 (session, qrid, png_bytes)。"""
    s = requests.Session()
    s.headers.update(PASSPORT_HEADERS)
    # 关键：建码会话也必须走住宅代理，使 qrid 与后续换票/验证同一出口 IP
    s.proxies.update(proxies_for(proxy) or {})
    # 1) 取 X-CSRF-TOKEN
    r = s.get(SSO_SIGNIN_URL,
              params={"entry": QR_ENTRY, "source": QR_SOURCE, "url": QR_REDIRECT},
              timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    csrf = s.cookies.get("X-CSRF-TOKEN")
    if not csrf:
        raise RuntimeError("未获取到 X-CSRF-TOKEN（代理出口可能无法访问 passport.weibo.com）")
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
    """在同一会话内轮询扫码状态（继承会话的住宅代理），最长 lifetime 秒。
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


def _follow_crossdomain_text(session, text, depth=0):
    """从 returntype=TEXT / crossdomain 返回体中提取 crossdomain / wbsso URL 并跟进，
    把 SUB 等票据补全到各域（requests 不执行返回体里的脚本，需要手动请求）。"""
    if not text or depth >= 3:
        return
    urls = []
    for raw in _CROSSDOMAIN_RE.findall(text):
        u = raw.replace("\\/", "/").rstrip("',;)}")
        if u not in urls:
            urls.append(u)
    for u in urls[:4]:
        try:
            r = session.get(u, allow_redirects=True, timeout=HTTP_TIMEOUT)
            for c in session.cookies:
                pass
            _follow_crossdomain_text(session, r.text, depth + 1)
        except Exception:
            pass


def collect_passport_cookies(session, cross_url, alt, proxy):
    """扫码成功后收集 passport 票据 + crossdomain + alt 重定向链 Cookie（全程住宅代理）。
    重要：建码会话、crossdomain、alt 换票、后续 m 域必须使用同一住宅出口 IP，
    避免机房直连触发微博异地风控导致 SUB 被踢。"""
    cookies = {}
    for c in session.cookies:
        cookies[c.name] = c.value
    proxies = proxies_for(proxy)
    headers = {"User-Agent": DESKTOP_UA,
               "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}

    def _jar(ss):
        for c in ss.cookies:
            cookies[c.name] = c.value

    if cross_url:
        try:
            with requests.Session() as cs:
                cs.headers.update(headers)
                if proxies:
                    cs.proxies.update(proxies)
                r = cs.get(cross_url, allow_redirects=True, timeout=HTTP_TIMEOUT)
                _jar(cs)
                _follow_crossdomain_text(cs, r.text)
                _jar(cs)
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
                r = as_.get(alt_url, allow_redirects=True, timeout=HTTP_TIMEOUT)
                _jar(as_)
                _follow_crossdomain_text(as_, r.text)
                _jar(as_)
        except Exception as e:
            log("WARN alt exchange: %s" % e)
    return cookies


def _extract_meta_jump(text):
    """从 sinawap returntype=META 返回的 HTML/JS 中提取需手动跟进的跳转 URL。
    requests 只自动跟随 302，不执行页面里的 location.replace / meta refresh。"""
    out = []
    for m in re.finditer(r"replace\(\s*['\"](https?:[^'\"]+)['\"]", text or "", re.I):
        out.append(m.group(1).replace("\\/", "/"))
    for m in re.finditer(r"url\s*=\s*['\"]?(https?://[^'\"\s>]+)", text or "", re.I):
        out.append(m.group(1).replace("\\/", "/"))
    for m in re.finditer(r"['\"](https?:[^'\"]*(?:wbsso|passport\.weibo\.cn)[^'\"]*)['\"]",
                         text or ""):
        out.append(m.group(1).replace("\\/", "/"))
    uniq = []
    for u in out:
        if u not in uniq:
            uniq.append(u)
    return uniq


def sso_sinawap(session, proxy):
    """关键：走 sinawap 移动端 SSO，把全局 SSO 票据（SUB）换成 m.weibo.cn 的
    SSOLoginState。只有拿到 SSOLoginState，m.weibo.cn/api/config 才会 login=true。
    正常情况下 login.php 直接 302 落地（requests 自动跟随）；若返回 META/JS replace
    页面（requests 不执行脚本），则手动解析并跟进 passport.weibo.cn 的换票链。"""
    mparams = {
        "url": MBASE + "/", "_rand": str(time.time()),
        "gateway": "1", "service": "sinawap", "entry": "sinawap",
        "useticket": "1", "returntype": "META", "sudaref": "",
        "_client_version": "0.6.26",
    }
    h = {"User-Agent": MOBILE_UA,
         "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
         "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"}
    r = session.get("https://login.sina.com.cn/sso/login.php",
                    params=mparams, headers=h,
                    timeout=HTTP_TIMEOUT, allow_redirects=True)
    if "m.weibo.cn" in r.url:
        log("sinawap 自动 302 已落地 m.weibo.cn")
    else:
        # 兜底：META / location.replace 手动跟进 passport.weibo.cn 换票链
        seen, cur, depth = set(), None, 0
        candidates = _extract_meta_jump(r.text)
        cur = candidates[0] if candidates else None
        while cur and depth < 5 and cur not in seen:
            seen.add(cur)
            try:
                hh = dict(h)
                host = re.match(r"https?://([^/]+)", cur)
                if host:
                    hh["Host"] = host.group(1)
                rr = session.get(cur, headers=hh, timeout=HTTP_TIMEOUT, allow_redirects=True)
                log("sinawap META follow#%d http=%s" % (depth, rr.status_code))
                nxt = [u for u in _extract_meta_jump(rr.text) if u not in seen]
                cur = nxt[0] if nxt else None
            except Exception as e:
                log("WARN sinawap META follow: %s" % e)
                cur = None
            depth += 1
    return any(c.name == "SSOLoginState" for c in session.cookies
               if (c.domain or "").lstrip(".").endswith("weibo.cn"))


# 写回 m.weibo.cn 时必须携带的核心票据（即使会话未独立下发也兜底补齐）
_M_CORE_KEYS = ("SUB", "SUBP", "SCF", "ALF", "MLOGIN", "SSOLoginState")


def build_mobile_cookies(passport_cookies, proxy):
    """用移动 UA 会话经住宅代理：sinawap 换票 -> 补全 m.weibo.cn 域 Cookie，并验证登录态。
    返回 (cookie_dict, login, uid, cookie_header)。"""
    s = requests.Session()
    s.headers.update(MOBILE_HEADERS)
    s.proxies.update(proxies_for(proxy) or {})
    # 1) 全局 SSO 票据（SUB/SUBP 等）需种到多域：sinawap 在 login.sina.com.cn 校验 SUB，
    #    m.weibo.cn 则需要落地后的 SSOLoginState。
    for k, v in passport_cookies.items():
        for dom in (".weibo.cn", ".weibo.com", ".sina.com.cn"):
            try:
                s.cookies.set(k, v, domain=dom, path="/")
            except Exception:
                pass
    # 2) 关键：sinawap 移动端 SSO，让 m.weibo.cn 签发 SSOLoginState
    has_sso = sso_sinawap(s, proxy)
    log("sinawap 换票结果 SSOLoginState=%s" % has_sso)
    # 3) 落地首页种访客 Cookie，再请求 config 触发/确认登录态
    s.get(MBASE + "/", timeout=HTTP_TIMEOUT)
    r = s.get(MBASE + "/api/config", timeout=HTTP_TIMEOUT)
    j = r.json()
    data = j.get("data") or {}
    login = bool(data.get("login"))
    uid = data.get("uid")
    if not uid:
        u = data.get("user")
        uid = u.get("id") if isinstance(u, dict) else None
    # 4) 只导出 weibo.cn 域 Cookie（不把 login.sina.com.cn 的内部票据塞进 m 域请求）
    final = {}
    for c in s.cookies:
        dom = (c.domain or "").lstrip(".")
        if dom.endswith("weibo.cn"):
            final[c.name] = c.value
    # 兜底：m 域必需、但会话未独立下发的票据用 passport 票据补
    for k in _M_CORE_KEYS:
        if k in passport_cookies:
            final.setdefault(k, passport_cookies[k])
    header = "; ".join("%s=%s" % (k, v) for k, v in final.items())
    return final, login, uid, header


def verify_cookie_header(cookie_header, proxy):
    """用最终 Cookie 串（全新请求、不依赖任何会话）再验证一次，返回 (login, uid)。"""
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


NET_ERRORS = (requests.exceptions.SSLError, requests.exceptions.ConnectionError,
              requests.exceptions.Timeout, requests.exceptions.ProxyError)

# 换票成功后即时落盘的保险票据：网络抖动 / 进程异常时避免已取得的 SSOLoginState 丢失
LAST_GOOD_PATH = "/tmp/weibo_last_good_cookie.txt"


def save_last_good(header, uid):
    try:
        with open(LAST_GOOD_PATH, "w", encoding="utf-8") as f:
            f.write(header)
        os.chmod(LAST_GOOD_PATH, 0o600)
        log("已落盘登录态保险票据（uid=%s，含 SSOLoginState）" % uid)
    except Exception as e:
        log("WARN 保险票据落盘失败: %s" % e)


def load_last_good():
    try:
        v = open(LAST_GOOD_PATH, encoding="utf-8").read().strip()
        return v or None
    except Exception:
        return None


def verify_persistent(cookie_header, proxy, checks=STABLE_CHECKS, gap=STABLE_GAP):
    """用全新请求连续验证；网络抖动（SSL/连接/超时/代理）自动重试，不把瞬时错误当失败，
    也不把已取得的登录态丢掉。连续 checks 次明确 login=True 才判稳定。
    返回 (stable, uid, ever_true, net_failed)。"""
    ok = 0
    uid = None
    ever_true = False
    net_failed = False
    tries = 0
    max_tries = checks + 5
    while ok < checks and tries < max_tries:
        tries += 1
        try:
            login, uid = verify_cookie_header(cookie_header, proxy)
        except NET_ERRORS as e:
            net_failed = True
            log("稳定验证网络抖动（%s），%ds 后重试，不计失败" % (type(e).__name__, gap))
            time.sleep(gap)
            continue
        if login:
            ever_true = True
            ok += 1
            log("稳定验证 %d/%d login=True uid=%s" % (ok, checks, uid))
        else:
            ok = 0
            log("稳定验证服务端返回 login=False uid=%s，连续计数清零" % uid)
        if ok < checks:
            time.sleep(gap)
    return ok >= checks, uid, ever_true, net_failed


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


def finalize_login(token, chat, passport, proxy):
    """扫码成功后的换票 / 补全 / 稳定验证，返回 (header, uid, final) 或 None。"""
    if not passport.get("SUB"):
        log("扫码成功但未取到 SUB 票据")
        return None
    final, login, uid, header = build_mobile_cookies(passport, proxy)
    has_sso = "SSOLoginState" in final
    # 换票成功并即时确认登录后，立刻落盘保险票据，防止后续网络抖动丢票
    if login and has_sso:
        save_last_good(header, uid)

    stable, uid2, ever_true, net_failed = verify_persistent(header, proxy)

    # 明确 login=False（非网络抖动）才冷却后用同一票据重新补全一次；sinawap 对同一 SUB
    # 有短时间频率保护，需冷却，避免连续请求触发「200 不跳转 / m 域 403」降级。
    if not stable and not net_failed:
        log("稳定验证未通过（服务端未确认），等待换票冷却后重新补全一次")
        time.sleep(15)
        final, login, uid, header = build_mobile_cookies(passport, proxy)
        has_sso = "SSOLoginState" in final
        if login and has_sso:
            save_last_good(header, uid)
        stable, uid2, ever_true, net_failed = verify_persistent(header, proxy)

    # 网络抖动：等待网络恢复后用保险票据复核，不重新换票（避免对同一 SUB 反复 sinawap）
    if not stable and net_failed:
        lg = load_last_good() or header
        for _ in range(3):
            time.sleep(8)
            stable, uid2, ever_true, net_failed = verify_persistent(lg, proxy)
            if stable:
                header = lg
                break

    # 兜底：换票已即时确认 login=True 且拿到 SSOLoginState，仅因网络抖动没跑满稳定验证，
    # 凭保险票据写回（写回后还会独立复核），不因瞬时网络问题丢票。
    if not stable and login and has_sso:
        lg = load_last_good()
        header = lg or header
        log("换票已即时确认登录并取得 SSOLoginState，稳定验证受网络抖动未跑满，凭保险票据写回")
        stable = True

    if not stable:
        log("登录态未稳定（服务端未确认），停止刷码，等待人工介入")
        return None
    return header, uid2 or uid, final


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

    # 0.5) 住宅代理预检：不可用则不推码，避免发码后换票必失败、反复刷码
    if not proxy_ready(proxy):
        log("住宅代理不可用，本次不推码，退出（避免打扰）")
        feishu_send_text(
            token, chat,
            "⚠️ 微博登录态待恢复，但住宅代理隧道当前不可用，已暂停推送二维码（避免反复打扰）。"
            "请先确认小米 12 与隧道在线，恢复后再触发一次扫码。")
        return 5

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
            session, qrid, png = make_qr(proxy)
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

        # 扫码成功：收集票据（全程代理）-> 稳定验证；失败不再无限刷码
        try:
            passport = collect_passport_cookies(session, cross_url, alt, proxy)
            result = finalize_login(token, chat, passport, proxy)
            if result is None:
                log("扫码成功但登录态多次验证不稳定（疑似换票出口/风控），停止刷码")
                feishu_send_text(
                    token, chat,
                    "⚠️ 已检测到你扫码成功，但新登录态在多次验证下仍不稳定。\n"
                    "为避免反复打扰，已停止自动刷新二维码。\n"
                    "建议：让扫码手机与小米 12 住宅代理处于同一网络后，再触发一次扫码。")
                return 6
            header, uid, final = result

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

            # 重启后再独立复核：确认写回的 Cookie 持续有效，没有被快速回收。
            # 网络抖动（SSL/连接/超时）重试，避免把瞬时网络错误误判为登录态被回收。
            time.sleep(8)
            post_login, post_uid, post_net = False, None, False
            for attempt in range(1, 6):
                try:
                    post_login, post_uid = verify_cookie_header(header, proxy)
                    post_net = False
                    if post_login:
                        break
                except NET_ERRORS as e:
                    post_net = True
                    log("写回后复核网络抖动（%s），%ds 后重试 %d/5" % (type(e).__name__, 8, attempt))
                    time.sleep(8)
            log("写回后复核 login=%s uid=%s net=%s" % (post_login, post_uid, post_net))
            if not post_login and not post_net:
                log("ERROR 写回后登录态再次失效（疑似被风控快速回收）")
                feishu_send_text(
                    token, chat,
                    "⚠️ 扫码 Cookie 已写回，但服务重启后复核登录态又失效（可能被微博风控快速回收）。"
                    "已停止刷码，请人工排查住宅代理出口稳定性后再试。")
                return 7
            if not post_login and post_net:
                # 换票阶段已稳定验证，写回后复核仅因网络抖动没确认：不刷码、不回收，记成功
                log("WARN 写回后复核因网络抖动暂未确认，但换票阶段已验证，Cookie 已写回，不刷码")
                feishu_send_text(
                    token, chat,
                    "✅ 微博扫码登录已完成、Cookie 已写回（uid=%s，换票阶段已验证 login=True）。\n"
                    "服务重启后复核恰逢住宅代理短暂抖动，已不反复刷码，稍后自动再次确认。"
                    % (uid,))
                log("DONE 登录态已写回（复核受网络抖动，稍后自动确认）uid=%s" % uid)
                return 0

            feishu_send_text(
                token, chat,
                "✅ 微博登录态已自动恢复：扫码成功，新 Cookie 已稳定生效（uid=%s），"
                "采集服务已重启，自动采集可继续。\n恢复时间：%s"
                % (post_uid or uid, now_bj().strftime("%Y-%m-%d %H:%M:%S")))
            log("DONE 登录态恢复 uid=%s" % (post_uid or uid))
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
