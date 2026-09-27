#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每日多维表格落表核对 + 飞书群汇报（云端，不依赖本地电脑）。
由 weibo-bitable-verify.timer 每天 09:20(北京) 触发，核对 09:05 定时工作流
是否已把"前一天(T-1) AI 行业热点 TOP10"写入多维表格，并把结论发到飞书群。
仅用标准库；凭据从 /opt/Weibo-Analyst/.env 读取。
DRY_RUN=1 时只打印不发群。
"""
import os, sys, json, datetime, urllib.request, urllib.error, traceback

ENV_PATH = "/opt/Weibo-Analyst/.env"
BASE = "NRS9bfc2dabZvJsM133csK8Inee"
TABLE = "tblBL0YqGzZlvFon"
EXPECT = int(os.environ.get("EXPECT_COUNT", "10"))
PREFIX = os.environ.get("MSG_PREFIX", "")
LOG = "/opt/Weibo-Analyst/logs/verify_bitable.log"
BJ = datetime.timezone(datetime.timedelta(hours=8))


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
    line = "[%s] %s" % (datetime.datetime.now(BJ).strftime("%Y-%m-%d %H:%M:%S"), s)
    print(line)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def http(method, url, token=None, body=None):
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if token:
        headers["Authorization"] = "Bearer " + token
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def get_token(app, sec):
    r = http("POST",
             "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
             body={"app_id": app, "app_secret": sec})
    if r.get("code") != 0:
        raise RuntimeError("tenant_token failed: %s" % r)
    return r["tenant_access_token"]


def fetch_all(token):
    items, ptoken = [], None
    while True:
        url = ("https://open.feishu.cn/open-apis/bitable/v1/apps/%s/tables/%s/records"
               "?page_size=100" % (BASE, TABLE))
        if ptoken:
            url += "&page_token=" + ptoken
        r = http("GET", url, token=token)
        if r.get("code") != 0:
            raise RuntimeError("list records failed: %s" % r)
        d = r["data"]
        items.extend(d.get("items", []))
        if d.get("has_more"):
            ptoken = d.get("page_token")
        else:
            break
    return items


def as_text(v):
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, dict):
        return str(v.get("text") or v.get("name") or v.get("link") or "").strip()
    if isinstance(v, list):
        parts = []
        for x in v:
            if isinstance(x, dict):
                parts.append(str(x.get("text") or x.get("name") or x.get("link") or ""))
            else:
                parts.append(str(x))
        return "".join(parts).strip()
    return str(v).strip()


def as_url(v):
    if isinstance(v, dict):
        return v.get("link") or v.get("text") or ""
    if isinstance(v, list) and v:
        x = v[0]
        return x.get("link") or x.get("text") or "" if isinstance(x, dict) else str(x)
    return as_text(v)


def as_day(v):
    if isinstance(v, (int, float)):
        ts = v / 1000.0 if v > 1e12 else float(v)
        return datetime.datetime.fromtimestamp(ts, BJ).strftime("%Y-%m-%d")
    s = as_text(v)
    return s[:10] if len(s) >= 10 else s


def send(token, chat, text):
    if os.environ.get("DRY_RUN") == "1":
        log("=== DRY_RUN，不发群。以下为消息内容 ===")
        print(text)
        return {"code": -1, "msg": "dry_run"}
    body = {"receive_id": chat, "msg_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False)}
    return http("POST",
                "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
                token=token, body=body)


def main():
    env = load_env()
    app, sec = env.get("FEISHU_APP_ID"), env.get("FEISHU_APP_SECRET")
    chat = os.environ.get("FEISHU_CHAT_ID") or env.get("FEISHU_CHAT_ID")
    token = get_token(app, sec)

    now = datetime.datetime.now(BJ)
    target = (now - datetime.timedelta(days=1)).strftime("%Y-%m-%d")
    items = fetch_all(token)

    rows = []
    for it in items:
        f = it.get("fields", {})
        rows.append({
            "date": as_day(f.get("日期")),
            "title": as_text(f.get("标题")),
            "author": as_text(f.get("作者")),
            "link": as_url(f.get("微博链接")),
            "hot": f.get("热度"),
            "content": as_text(f.get("原始内容")),
            "ai": as_text(f.get("AI摘要")),
            "imp": as_text(f.get("影响分析")),
            "biz": as_text(f.get("商业机会分析")),
            "tag": as_text(f.get("标签")),
        })

    total = len(rows)
    dist = {}
    for r in rows:
        dist[r["date"]] = dist.get(r["date"], 0) + 1
    t = [r for r in rows if r["date"] == target]
    n = len(t)
    links = [r["link"] for r in t if r["link"]]
    uniq = len(set(links))
    base_ok = sum(1 for r in t if r["title"] and r["author"] and r["link"]
                  and r["hot"] is not None and r["content"])
    ai_ok = sum(1 for r in t if r["ai"] and r["imp"] and r["biz"] and r["tag"])

    problems = []
    if n == 0:
        problems.append("目标日 %s 无任何记录，09:05 定时工作流可能未执行/端点异常" % target)
    elif n < EXPECT:
        problems.append("目标日仅 %d 条（期望 %d），数据可能未就绪或被截断" % (n, EXPECT))
    elif n > EXPECT:
        problems.append("目标日 %d 条（期望 %d），疑似手动按钮重复写入，需去重" % (n, EXPECT))
    if n and uniq != n:
        problems.append("目标日链接重复：%d 条记录仅 %d 个唯一链接" % (n, uniq))
    if n and base_ok != n:
        problems.append("基础字段缺失：仅 %d/%d 条齐全" % (base_ok, n))

    ai_warn = (n == EXPECT and ai_ok < n)
    if ai_warn:
        problems.append("AI 字段仍在生成：%d/%d 条完成（异步，可稍后复查）" % (ai_ok, n))

    # 硬失败：没跑 / 条数不对 / 重复 / 基础字段缺失；AI 异步延迟仅警告
    hard_fail = any("AI 字段仍在生成" not in p for p in problems) and bool(problems) and not ai_warn
    if ai_warn and not [p for p in problems if "AI 字段仍在生成" not in p]:
        hard_fail = False
    success = (n == EXPECT and uniq == n and base_ok == n)

    icon = "✅" if success and not ai_warn else ("⚠️" if success and ai_warn else "❌")
    if not success:
        verdict = "FAILED"
    elif ai_warn:
        verdict = "WARNING"
    else:
        verdict = "SUCCESS"

    dist_str = " ".join("%s:%d" % (k, v) for k, v in sorted(dist.items()))
    lines = [
        "%s %s微博多维表格·每日自动核对" % (icon, PREFIX),
        "核对目标日：%s（T-1 TOP%d）" % (target, EXPECT),
        "运行时间：%s" % now.strftime("%Y-%m-%d %H:%M"),
        "表内总记录：%d 条（%s）" % (total, dist_str),
        "目标日新增：%d 条 %s" % (n, "✅" if n == EXPECT else "❌"),
        "链接去重：%d/%d 唯一 %s" % (uniq, n, "✅" if uniq == n else "❌"),
        "基础字段：%d/%d 齐全 %s" % (base_ok, n, "✅" if base_ok == n else "❌"),
        "AI分析字段：%d/%d 已生成 %s" % (ai_ok, n, "✅" if ai_ok == n else "⚠️"),
        "结论：%s" % verdict,
    ]
    if problems:
        lines.append("问题/建议：")
        for p in problems:
            lines.append("· " + p)
    if success and not ai_warn:
        lines.append("09:05 定时工作流落表正常，多维表格已是当天 T-1 TOP%d。" % EXPECT)
    msg = "\n".join(lines)

    r = send(token, chat, msg)
    log("target=%s total=%d n=%d uniq=%d base=%d ai=%d verdict=%s send_code=%s"
        % (target, total, n, uniq, base_ok, ai_ok, verdict, r.get("code")))
    if r.get("code") not in (0, -1):
        log("send error: %s" % r)
    print("VERDICT=%s" % verdict)
    return 0 if success else 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        tb = traceback.format_exc()
        log("FATAL: %s\n%s" % (e, tb))
        try:
            env = load_env()
            tok = get_token(env.get("FEISHU_APP_ID"), env.get("FEISHU_APP_SECRET"))
            chat = env.get("FEISHU_CHAT_ID")
            send(tok, chat, "❌ 微博多维表格每日核对脚本异常：\n%s" % str(e)[:600])
        except Exception:
            pass
        sys.exit(1)
