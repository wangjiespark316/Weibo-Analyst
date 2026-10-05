#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""整机内存 + weibo-api cgroup 看门狗。
检查: 整机可用内存过低 / weibo-api 发生 OOM 杀进程 / 被 MemoryHigh 大量节流。
仅状态变化时发飞书群; 持续异常每6小时再提醒。"""
import os, sys, json, subprocess, datetime, traceback

ENV_PATH="/opt/Weibo-Analyst/.env"
LOG="/opt/Weibo-Analyst/logs/mem_guard.log"
STATE="/opt/Weibo-Analyst/logs/mem_guard.state"
CG="/sys/fs/cgroup/system.slice/weibo-api.service"
WARN_AVAIL_MB=260
HIGH_DELTA_ALERT=3000
REMIND_AFTER=6*3600
BJ=datetime.timezone(datetime.timedelta(hours=8))

def now_bj(): return datetime.datetime.now(BJ)
def log(s):
    line="[%s] %s"%(now_bj().strftime("%Y-%m-%d %H:%M:%S"),s)
    print(line)
    try: open(LOG,"a",encoding="utf-8").write(line+"\n")
    except Exception: pass

def load_env():
    env={}
    try:
        for line in open(ENV_PATH,encoding="utf-8"):
            line=line.strip()
            if not line or line.startswith("#") or "=" not in line: continue
            k,v=line.split("=",1); env[k.strip()]=v.strip().strip(chr(34)).strip(chr(39))
    except Exception as e: log("WARN load_env %s"%e)
    return env

def curl_json(url,extra_headers=None,body=None,timeout=20):
    cmd=["curl","-s","-X","POST" if body is not None else "GET",url,"-H","Content-Type: application/json; charset=utf-8"]
    for h in (extra_headers or []): cmd+=["-H",h]
    if body is not None: cmd+=["-d",json.dumps(body,ensure_ascii=False)]
    p=subprocess.run(cmd,capture_output=True,text=True,timeout=timeout)
    out=(p.stdout or "").strip()
    try: return p.returncode,json.loads(out),out
    except Exception: return p.returncode,None,out

def get_token(app,sec):
    rc,r,raw=curl_json("https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        body={"app_id":app,"app_secret":sec})
    if not r or r.get("code")!=0: raise RuntimeError("token fail %s"%raw[:150])
    return r["tenant_access_token"]

def send(token,chat,text):
    body={"receive_id":chat,"msg_type":"text","content":json.dumps({"text":text},ensure_ascii=False)}
    rc,r,raw=curl_json("https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
        extra_headers=["Authorization: Bearer "+token],body=body)
    return r if r else {"code":-99,"msg":raw[:150]}

def avail_mb():
    for line in open("/proc/meminfo"):
        if line.startswith("MemAvailable"): return int(line.split()[1])//1024
    return -1

def cg_events():
    ev={}
    try:
        for line in open(CG+"/memory.events"):
            k,v=line.split(); ev[k]=int(v)
    except Exception as e: log("WARN cg events %s"%e)
    return ev

def load_state():
    try: return json.load(open(STATE,encoding="utf-8"))
    except Exception: return None
def save_state(st):
    try: json.dump(st,open(STATE,"w",encoding="utf-8"),ensure_ascii=False)
    except Exception as e: log("WARN save %s"%e)

def main():
    env=load_env()
    app,sec,chat=env.get("FEISHU_APP_ID"),env.get("FEISHU_APP_SECRET"),env.get("FEISHU_CHAT_ID")
    avail=avail_mb(); ev=cg_events()
    oom=ev.get("oom_kill",0); high=ev.get("high",0)
    prev=load_state() or {}
    high_delta=high-prev.get("high",0)
    problems=[]
    if avail < WARN_AVAIL_MB: problems.append("整机可用内存仅 %dMB（阈值%d）"%(avail,WARN_AVAIL_MB))
    if oom > prev.get("oom_kill",0): problems.append("weibo-api 发生 OOM 杀进程（oom_kill %s->%d）"%(prev.get("oom_kill",0),oom))
    if high_delta > HIGH_DELTA_ALERT: problems.append("weibo-api 被 MemoryHigh 节流 %d 次（疑似又触顶卡死）"%high_delta)
    status="ALARM" if problems else "OK"
    ts=now_bj().timestamp(); prev_status=prev.get("status","OK")
    last_alert=float(prev.get("last_alert",0))
    became_bad=status=="ALARM" and prev_status!="ALARM"
    still_remind=status=="ALARM" and (ts-last_alert)>=REMIND_AFTER
    recovered=status=="OK" and prev_status=="ALARM"
    log("status=%s avail=%dMB oom=%d high_delta=%d problems=%s"%(status,avail,oom,high_delta,problems))
    if became_bad or still_remind or recovered:
        try:
            token=get_token(app,sec)
            if recovered:
                text="✅ 服务器内存已恢复正常：可用 %dMB，无 OOM/节流。\n恢复时间：%s"%(avail,now_bj().strftime("%H:%M:%S"))
            else:
                text="⚠️ 服务器内存告警\n· "+"\n· ".join(problems)+"\n当前可用 %dMB；请关注微博服务是否卡顿，必要时重启或升配。\n时间：%s"%(avail,now_bj().strftime("%Y-%m-%d %H:%M"))
            r=send(token,chat,text); log("feishu code=%s"%r.get("code"))
            if status=="ALARM": last_alert=ts
        except Exception as e: log("WARN send %s"%e)
    st={"status":status,"avail":avail,"oom_kill":oom,"high":high,
        "last_alert":last_alert if status=="ALARM" else prev.get("last_alert",0)}
    save_state(st); print("MEMSTATUS=%s"%status); return 0

if __name__=="__main__":
    try: sys.exit(main())
    except Exception as e:
        log("FATAL %s\n%s"%(e,traceback.format_exc())); sys.exit(1)
