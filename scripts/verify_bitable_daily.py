#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每日多维表格落表核对 + 飞书群汇报（云端，不依赖本地电脑）。
由 weibo-bitable-verify.timer 每天 09:20(北京) 触发，核对 09:05 定时工作流
是否已把"前一天(T-1) AI 行业热点 TOP10"写入多维表格，并把结论发到飞书群。
仅用标准库；凭据从 /opt/Weibo-Analyst/.env 读取。
DRY_RUN=1 时只打印不发群。
"""
import os, sys, re, json, datetime, urllib.request, urllib.error, traceback

ENV_PATH = "/opt/Weibo-Analyst/.env"
BASE = "NRS9bfc2dabZvJsM133csK8Inee"
TABLE = "tblBL0YqGzZlvFon"
EXPECT = int(os.environ.get("EXPECT_COUNT", "10"))  # 仅在接口基准不可用时的兜底参考
# 脚本与 API 同机，优先走本地 nginx 门面（免 key、免 Cloudflare UA 拦截、最稳）
API_YESTERDAY = os.environ.get(
    "API_YESTERDAY_URL", "http://127.0.0.1:8082/data/hot-yesterday")
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


def wid(x):
    """从 weibo_id 或微博链接里提取帖子 id（末尾长数字）。"""
    if x is None:
        return ""
    if isinstance(x, (int, float)):
        return str(int(x))
    m = re.findall(r"\d{6,}", str(x))
    return m[-1] if m else ""


def fetch_expect():
    """以 hot-yesterday 接口实际返回为"应写入"基准。
    返回 (expect_n, expect_ids)；接口不可用时返回 (None, set())。"""
    try:
        req = urllib.request.Request(
            API_YESTERDAY, method="GET",
            headers={"User-Agent": "Mozilla/5.0 (weibo-verify/1.0)"})
        with urllib.request.urlopen(req, timeout=30) as r:
            d = json.loads(r.read().decode("utf-8"))
        arr = d.get("data")
        if isinstance(arr, dict):
            arr = arr.get("records") or arr.get("data")
        if not isinstance(arr, list):
            return None, set()
        ids = set()
        for x in arr:
            if isinstance(x, dict):
                w = wid(x.get("weibo_id")) or wid(x.get("url"))
            else:
                w = wid(x)
            if w:
                ids.add(w)
        return len(arr), ids
    except Exception as e:
        log("WARN fetch_expect: %s" % e)
        return None, set()


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

    # 以 hot-yesterday 接口实际返回为"应写入"基准（条数随当天真 AI 事件浮动）
    expect_n, expect_ids = fetch_expect()
    items = fetch_all(token)

    rows = []
    for it in items:
        f = it.get("fields", {})
        link = as_url(f.get("微博链接"))
        rows.append({
            "date": as_day(f.get("日期")),
            "title": as_text(f.get("标题")),
            "author": as_text(f.get("作者")),
            "link": link,
            "wid": wid(link),
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
    got_links = [r["link"] for r in t if r["link"]]
    uniq = len(set(got_links))
    got_ids = set(r["wid"] for r in t if r["wid"])
    base_ok = sum(1 for r in t if r["title"] and r["author"] and r["link"]
                  and r["hot"] is not None and r["content"])
    ai_ok = sum(1 for r in t if r["ai"] and r["imp"] and r["biz"] and r["tag"])

    hard, soft = [], []
    dup = bool(n) and uniq != n
    base_missing = bool(n) and base_ok != n
    count_missing = count_extra = False
    if n == 0:
        hard.append("目标日 %s 无任何记录，09:05 定时工作流可能未执行/端点异常" % target)
    else:
        if dup:
            hard.append("目标日链接重复：%d 条记录仅 %d 个唯一链接" % (n, uniq))
        if base_missing:
            hard.append("基础字段缺失：仅 %d/%d 条齐全" % (base_ok, n))
        if expect_n is not None:
            missing = sorted(expect_ids - got_ids)
            extra = sorted(got_ids - expect_ids)
            count_missing, count_extra = bool(missing), bool(extra)
            if missing:
                hard.append("接口基准 %d 条，表内缺 %d 条（id 尾号 %s），数据可能未就绪/被截断"
                            % (expect_n, len(missing),
                               ",".join(x[-6:] for x in missing[:5])))
            if extra:
                hard.append("表内比接口基准多 %d 条（id 尾号 %s），疑似重复/多写入"
                            % (len(extra), ",".join(x[-6:] for x in extra[:5])))

    ai_warn = bool(n) and ai_ok < n
    if ai_warn:
        soft.append("AI 字段仍在生成：%d/%d 条完成（异步，可稍后复查）" % (ai_ok, n))
    if expect_n is None and n:
        soft.append("无法获取接口基准条数，完整性未能核验，建议人工复查")

    if hard:
        verdict, icon = "FAILED", "❌"
    elif ai_warn or expect_n is None:
        verdict, icon = "WARNING", "⚠️"
    else:
        verdict, icon = "SUCCESS", "✅"
    benchmark = ("接口基准 %d 条" % expect_n) if expect_n is not None \
        else "接口基准不可用（兜底期望 %d）" % EXPECT
    count_icon = ("✅" if (expect_n is not None and n == expect_n)
                  else ("⚠️" if expect_n is None else "❌"))
    base_label = ("%d" % expect_n) if expect_n is not None else "?"

    dist_str = " ".join("%s:%d" % (k, v) for k, v in sorted(dist.items()))
    lines = [
        "%s %s微博多维表格·每日自动核对" % (icon, PREFIX),
        "核对目标日：%s（T-1，%s）" % (target, benchmark),
        "运行时间：%s" % now.strftime("%Y-%m-%d %H:%M"),
        "表内总记录：%d 条（%s）" % (total, dist_str),
        "目标日新增：%d 条（基准 %s）%s" % (n, base_label, count_icon),
        "链接去重：%d/%d 唯一 %s" % (uniq, n, "✅" if (n and uniq == n) else ("—" if n == 0 else "❌")),
        "基础字段：%d/%d 齐全 %s" % (base_ok, n, "✅" if (n and base_ok == n) else ("—" if n == 0 else "❌")),
        "AI分析字段：%d/%d 已生成 %s" % (ai_ok, n, "✅" if (n and ai_ok == n) else ("—" if n == 0 else "⚠️")),
        "结论：%s" % verdict,
    ]
    allp = hard + soft
    if allp:
        lines.append("问题/建议：")
        for p in allp:
            lines.append("· " + p)
    if verdict == "SUCCESS":
        lines.append("09:05 定时工作流落表正常，多维表格已是当天 T-1 热点（%d 条，LLM 相关性闸门清洗，条数随当天真 AI 事件浮动）。" % n)
    msg = "\n".join(lines)

    r = send(token, chat, msg)
    log("target=%s total=%d n=%d uniq=%d base=%d ai=%d verdict=%s send_code=%s"
        % (target, total, n, uniq, base_ok, ai_ok, verdict, r.get("code")))
    if r.get("code") not in (0, -1):
        log("send error: %s" % r)
    print("VERDICT=%s" % verdict)
    return 0 if verdict in ("SUCCESS", "WARNING") else 2


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
