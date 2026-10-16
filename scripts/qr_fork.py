#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fork 式建码：前台父进程 2-3 秒内输出 base64 二维码后退出（供 Mac 一次 ssh 拿码）；
后台子进程继承同一建码会话，独立完成 170s 轮询 -> sinawap -> 写回 .env -> 重启 -> 复核。
规避 ssh 限流导致的 Mac 串行链拖慢（建码本身仅约 1 秒）。"""
import os
import sys
import time
import base64
import traceback

sys.path.insert(0, "/opt/Weibo-Analyst/scripts")
import weibo_qr_login as w  # noqa: E402

STATE = "/tmp/weibo_oneoff_state.txt"
LOG = "/tmp/weibo_oneoff.log"
WAIT = 170


def set_state(s):
    try:
        with open(STATE, "w") as f:
            f.write("%s %s\n" % (time.strftime("%H:%M:%S"), s))
    except Exception:
        pass
    w.log("[oneoff] " + s)


def child_poll(session, qrid, proxy):
    """子进程：轮询 + 换票 + 写回 + 重启 + 复核。"""
    try:
        status, cross_url, alt = w.poll_qr(session, qrid, WAIT)
        set_state("POLL_RESULT " + status)
        if status != "ok":
            set_state("FAIL_" + status.upper())
            os._exit(2)

        passport = w.collect_passport_cookies(session, cross_url, alt, proxy)
        if not passport.get("SUB"):
            set_state("FAIL_NO_SUB")
            os._exit(8)
        result = w.finalize_login(None, None, passport, proxy)
        if result is None:
            set_state("FAIL_UNSTABLE")
            os._exit(6)
        header, uid, final = result

        try:
            backup = w.write_env_cookie(header)
            set_state("ENV_WRITTEN uid=%s keys=%d backup=%s" % (uid, len(final), backup))
        except Exception as e:
            set_state("FAIL_WRITEENV " + str(e))
            os._exit(12)

        rc, err = w.restart_services()
        if rc != 0:
            set_state("FAIL_RESTART rc=%s %s" % (rc, err))
            os._exit(4)
        set_state("SERVICES_RESTARTED")

        time.sleep(8)
        post_login, post_uid, post_net = False, None, False
        for attempt in range(1, 6):
            try:
                post_login, post_uid = w.verify_cookie_header(header, proxy)
                post_net = False
                if post_login:
                    break
            except w.NET_ERRORS as e:
                post_net = True
                w.log("写回后复核网络抖动（%s），%ds 后重试 %d/5" % (type(e).__name__, 8, attempt))
                time.sleep(8)
        if post_login:
            set_state("SUCCESS uid=%s" % (post_uid or uid))
            os._exit(0)
        if post_net:
            set_state("SUCCESS_NETJITTER uid=%s" % uid)
            os._exit(0)
        set_state("FAIL_POSTCHECK_REVOKED")
        os._exit(7)
    except Exception as e:
        set_state("FAIL_EXCEPTION " + str(e))
        traceback.print_exc()
        os._exit(99)


def main():
    set_state("START")
    env = w.load_env()
    proxy = env.get("WEIBO_PROXY", "")
    if not w.proxy_ready(proxy):
        set_state("FAIL_PROXY_DOWN")
        print("PROXY_DOWN")
        return 5
    set_state("PROXY_OK")
    try:
        session, qrid, png = w.make_qr(proxy)
    except Exception as e:
        set_state("FAIL_MAKEQR " + str(e))
        print("MAKEQR_FAILED")
        return 10
    set_state("QR_READY bytes=%d" % len(png))

    # fork：子进程继承建码会话后台轮询；父进程输出 base64 立即退出
    pid = os.fork()
    if pid == 0:
        # 子进程：脱离会话，重定向标准流到日志（避免 ssh 通道被继承而挂住）
        os.setsid()
        try:
            fd = os.open(LOG, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
            os.dup2(fd, 1)
            os.dup2(fd, 2)
            dn = os.open("/dev/null", os.O_RDONLY)
            os.dup2(dn, 0)
        except Exception:
            pass
        child_poll(session, qrid, proxy)
        os._exit(99)
    else:
        # 父进程：输出 base64 给 Mac，立即退出
        print("QRB64_BEGIN")
        print(base64.b64encode(png).decode())
        print("QRB64_END")
        print("CHILD_PID=%d" % pid)
        sys.stdout.flush()
        os._exit(0)


if __name__ == "__main__":
    main()
