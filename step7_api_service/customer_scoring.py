"""
客户AI机会评分模块
"""
import pymysql, os, json
from urllib.parse import urlparse
from dotenv import load_dotenv
from industries import get_industry_by_name

load_dotenv("/opt/Weibo-Analyst/.env")

def get_db():
    db_url = os.getenv("DATABASE_URL")
    p = urlparse(db_url)
    return pymysql.connect(host=p.hostname, port=p.port or 3306,
        user=p.username if isinstance(p.username, str) else p.username.decode(),
        password=p.password if isinstance(p.password, str) else p.password.decode(),
        database=p.path.lstrip("/"), ssl={"ssl_disabled": False},
        cursorclass=pymysql.cursors.DictCursor)

def calculate_score(customer_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM customers WHERE id=%s", (customer_id,))
    c = cur.fetchone()
    if not c:
        conn.close()
        return None
    
    score = 0
    reasons = []
    industry_info = get_industry_by_name(c.get("industry",""))
    
    # 行业匹配25分
    cur.execute("SELECT AVG(growth_rate) avg_g FROM ai_trends WHERE date>=DATE_SUB(CURDATE(),INTERVAL 7 DAY)")
    avg_g = (cur.fetchone() or {}).get("avg_g",0) or 0
    if avg_g > 50: score += 25; reasons.append(f"行业AI趋势热度高(+{avg_g:.0f}%)")
    elif avg_g > 20: score += 18; reasons.append(f"行业AI趋势热度中等(+{avg_g:.0f}%)")
    else: score += 10; reasons.append("行业AI趋势一般")
    
    scenarios = industry_info.get("scenarios",[])[:3] if industry_info else []
    risks = industry_info.get("pain_points",[])[:2] if industry_info else []
    
    # 规模15分（兼容飞书人员规模口径 1-99/100-999/1000-9999/10000-99999/100000+ 与旧口径）
    size_scores = {
        # 飞书 CRM 口径
        "100000+": 15, "10000-99999": 15, "1000-9999": 13, "100-999": 10, "1-99": 5,
        # 旧口径
        "1000人以上": 15, "200-1000人": 12, "50-200人": 9, "10-50人": 6, "10人以下": 3,
    }
    ss = size_scores.get((c.get("company_size") or "").strip(), 6)
    score += ss; reasons.append(f"公司规模({ss}分)")
    
    # 等级15分
    ls = {"A":15,"B":10,"C":5}.get(c.get("customer_level","C"),5)
    score += ls; reasons.append(f"客户等级{ls}分")
    
    # 阶段20分
    sts = {"new":5,"contacted":10,"requirement":14,"solution":17,"negotiation":19,"closed":20,"lost":0}
    st = sts.get(c.get("sales_stage","new"),5)
    score += st; reasons.append(f"销售阶段({st}分)")
    
    # 跟进15分
    cur.execute("SELECT COUNT(*) cnt FROM follow_records WHERE customer_id=%s AND follow_time>=DATE_SUB(CURDATE(),INTERVAL 30 DAY)", (customer_id,))
    fc = (cur.fetchone() or {}).get("cnt",0) or 0
    if fc >= 5: score += 15; reasons.append(f"跟进活跃({fc}次)")
    elif fc >= 3: score += 12; reasons.append(f"跟进较活跃({fc}次)")
    elif fc >= 1: score += 8; reasons.append(f"有跟进({fc}次)")
    else: score += 3; reasons.append("近期无跟进")
    
    # 趋势匹配10分
    if industry_info and avg_g > 30: score += 10; reasons.append("AI趋势高度匹配")
    elif industry_info: score += 6; reasons.append("AI趋势有匹配")
    else: score += 3
    
    score = min(100, score)
    
    cur.execute("""INSERT INTO customer_ai_scores(customer_id,score,reason,recommended_scenarios,risk_points)
        VALUES(%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE score=VALUES(score),reason=VALUES(reason),
        recommended_scenarios=VALUES(recommended_scenarios),risk_points=VALUES(risk_points)""",
        (customer_id, score, json.dumps(reasons,ensure_ascii=False),
         json.dumps(scenarios,ensure_ascii=False), json.dumps(risks,ensure_ascii=False)))
    conn.commit(); conn.close()
    
    return {"customer_id":customer_id,"customer_name":c.get("company_name",""),"score":score,
            "reasons":reasons,"recommended_scenarios":scenarios,"risk_points":risks}

def get_score(customer_id):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT * FROM customer_ai_scores WHERE customer_id=%s ORDER BY created_time DESC LIMIT 1", (customer_id,))
    r = cur.fetchone(); conn.close()
    if r:
        return {"score":r.get("score",0),
                "reasons":json.loads(r.get("reason","[]")) if r.get("reason") else [],
                "recommended_scenarios":json.loads(r.get("recommended_scenarios","[]")) if r.get("recommended_scenarios") else [],
                "risk_points":json.loads(r.get("risk_points","[]")) if r.get("risk_points") else []}
    return None

def calc_all():
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT id FROM customers ORDER BY id")
    ids = [r["id"] for r in cur.fetchall()]
    conn.close()
    return [calculate_score(i) for i in ids]
