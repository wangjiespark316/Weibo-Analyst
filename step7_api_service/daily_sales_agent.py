"""
AI每日销售任务生成Agent
"""
import pymysql, os, json, time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import urlparse
from dotenv import load_dotenv
from customer_scoring import calculate_score, get_score

load_dotenv("/opt/Weibo-Analyst/.env")

# 今日任务结果进程内缓存TTL（秒），避免每次打开页面都串行查库
TASKS_CACHE_TTL = 60
_tasks_cache = {}  # date_str -> (timestamp, result)

def get_db():
    db_url = os.getenv("DATABASE_URL")
    p = urlparse(db_url)
    return pymysql.connect(host=p.hostname, port=p.port or 3306,
        user=p.username if isinstance(p.username, str) else p.username.decode(),
        password=p.password if isinstance(p.password, str) else p.password.decode(),
        database=p.path.lstrip("/"), ssl={"ssl_disabled": False},
        cursorclass=pymysql.cursors.DictCursor)

def get_need_follow():
    conn = get_db(); cur = conn.cursor()
    cur.execute("""SELECT c.*, DATEDIFF(CURDATE(),c.last_follow_time) days_since
        FROM customers c WHERE c.sales_stage NOT IN ('closed','lost')
        AND (c.last_follow_time IS NULL OR DATEDIFF(CURDATE(),c.last_follow_time)>=3 OR c.next_action IS NOT NULL)
        ORDER BY CASE WHEN c.customer_level='A' THEN 1 WHEN c.customer_level='B' THEN 2 ELSE 3 END,
        days_since DESC LIMIT 10""")
    rs = cur.fetchall(); conn.close()
    return rs

def _get_score_with_fallback(cid):
    """获取客户评分，无记录则实时计算（每个调用独立DB连接，可安全并行）"""
    return get_score(cid) or calculate_score(cid)


def gen_tasks(date_str=None, use_cache=True):
    if not date_str: date_str = datetime.now().strftime("%Y-%m-%d")

    # 命中缓存直接返回
    if use_cache and date_str in _tasks_cache:
        ts, cached = _tasks_cache[date_str]
        if time.time() - ts < TASKS_CACHE_TTL:
            return cached

    customers = get_need_follow()
    tasks = []

    # 5个客户的评分查询相互独立，并行获取（原为串行5次远程DB往返）
    top_customers = customers[:5]
    score_map = {}
    if top_customers:
        with ThreadPoolExecutor(max_workers=min(5, len(top_customers))) as ex:
            futures = {ex.submit(_get_score_with_fallback, c["id"]): c["id"] for c in top_customers}
            for fut in futures:
                cid = futures[fut]
                try:
                    score_map[cid] = fut.result()
                except Exception:
                    score_map[cid] = None

    for c in top_customers:
        cid = c["id"]
        si = score_map.get(cid)
        stage = c.get("sales_stage","new")
        na = c.get("next_action","")
        
        stage_actions = {
            "new": ("首次触达：电话或微信联系，介绍AI解决方案", "first_contact"),
            "contacted": (na or "深度需求沟通：了解业务痛点和AI需求", "follow_up"),
            "requirement": (na or "安排产品演示：展示相关AI功能和案例", "meeting_invite"),
            "solution": (na or "方案沟通：发送详细落地方案和报价", "solution_discussion"),
            "negotiation": (na or "商务谈判：确认合同条款和实施计划", "solution_discussion"),
        }
        action, stype = stage_actions.get(stage, (na or "继续跟进", "follow_up"))
        
        tasks.append({
            "customer_id": cid, "company_name": c.get("company_name",""),
            "industry": c.get("industry",""), "customer_level": c.get("customer_level",""),
            "sales_stage": stage, "ai_score": si.get("score",0) if si else 0,
            "recommended_scenarios": si.get("recommended_scenarios",[]) if si else [],
            "last_follow_time": c.get("last_follow_time").isoformat() if c.get("last_follow_time") else None,
            "days_since_follow": c.get("days_since",0),
            "suggested_action": action, "script_type": stype,
            "contact_name": c.get("contact_name",""), "contact_role": c.get("contact_role",""),
            "phone": c.get("phone",""), "email": c.get("email","")
        })
    
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT * FROM ai_sales_opportunities WHERE date=%s ORDER BY FIELD(priority,'high','medium','low') LIMIT 3", (date_str,))
    opps = cur.fetchall(); conn.close()
    
    a_count = len([t for t in tasks if t["customer_level"]=="A"])
    result = {
        "date": date_str, "total_customers_needing_follow": len(customers),
        "high_priority_customers": a_count, "top5_tasks": tasks,
        "today_opportunities": opps,
        "daily_advice": f"今日有{len(customers)}个客户需跟进，其中{a_count}个A级客户。优先处理高AI机会评分客户，重点推进方案沟通阶段项目。"
    }
    _tasks_cache[date_str] = (time.time(), result)
    return result
