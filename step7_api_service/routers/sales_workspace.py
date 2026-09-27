"""
销售工作台API路由
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import pymysql, os, json
from datetime import datetime
from urllib.parse import urlparse
from dotenv import load_dotenv

load_dotenv("/opt/Weibo-Analyst/.env")
router = APIRouter(prefix="/api/workspace", tags=["销售工作台"])

def get_db():
    # 统一复用 database.py 的进程级 TiDB 连接池，避免每请求新建公网 SSL 连接
    try:
        from ..database import get_connection as _gc
    except Exception:
        from database import get_connection as _gc
    return _gc()


class FollowCreate(BaseModel):
    customer_id: int
    follow_type: str = "电话"
    content: str
    next_action: Optional[str] = None

# 1. 客户列表
@router.get("/customers")
def list_customers(industry: Optional[str] = None, stage: Optional[str] = None, level: Optional[str] = None):
    conn = get_db(); cur = conn.cursor()
    where = " WHERE 1=1"
    params = []
    if industry: where += " AND c.industry=%s"; params.append(industry)
    if stage: where += " AND c.sales_stage=%s"; params.append(stage)
    if level: where += " AND c.customer_level=%s"; params.append(level)
    # 一条 SQL 带出每个客户的最新 AI 评分（窗口函数取 rn=1），消除 N+1 次公网往返
    sql = (
        "SELECT c.*, s.score AS ai_score FROM customers c "
        "LEFT JOIN (SELECT customer_id, score, ROW_NUMBER() OVER "
        "(PARTITION BY customer_id ORDER BY created_time DESC) AS rn "
        "FROM customer_ai_scores) s ON s.customer_id=c.id AND s.rn=1"
        + where + " ORDER BY c.customer_level, c.id"
    )
    cur.execute(sql, params)
    customers = cur.fetchall()
    conn.close()
    return {"count": len(customers), "customers": customers}

# 2. 客户详情
@router.get("/customers/{customer_id}")
def get_customer(customer_id: int):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT * FROM customers WHERE id=%s", (customer_id,))
    customer = cur.fetchone()
    if not customer:
        conn.close(); raise HTTPException(404, "客户不存在")
    
    # 跟进记录
    cur.execute("SELECT * FROM follow_records WHERE customer_id=%s ORDER BY follow_time DESC LIMIT 20", (customer_id,))
    follows = cur.fetchall()
    
    # AI评分
    cur.execute("SELECT * FROM customer_ai_scores WHERE customer_id=%s ORDER BY created_time DESC LIMIT 1", (customer_id,))
    score = cur.fetchone()
    
    # 匹配的销售机会
    cur.execute("""SELECT o.* FROM ai_sales_opportunities o 
        WHERE o.industry=%s OR o.industry LIKE %s ORDER BY o.priority LIMIT 5""",
        (customer.get("industry",""), f"%{customer.get('industry','')}%"))
    opportunities = cur.fetchall()
    
    conn.close()
    return {
        "customer": customer,
        "follows": follows,
        "ai_score": score,
        "opportunities": opportunities,
        "follow_count": len(follows)
    }

# 3. 新增跟进记录
@router.post("/follow")
def create_follow(data: FollowCreate):
    conn = get_db(); cur = conn.cursor()
    now = datetime.now()
    cur.execute("""INSERT INTO follow_records(customer_id,follow_type,content,next_action,follow_time)
        VALUES(%s,%s,%s,%s,%s)""",
        (data.customer_id, data.follow_type, data.content, data.next_action, now))
    
    # 更新客户最近跟进时间和下一步
    cur.execute("UPDATE customers SET last_follow_time=%s, next_action=%s WHERE id=%s",
        (now, data.next_action, data.customer_id))
    
    follow_id = cur.lastrowid
    conn.commit(); conn.close()
    return {"success": True, "follow_id": follow_id, "message": "跟进记录已创建"}

# 4. AI生成客户画像
@router.post("/profile/{customer_id}")
def generate_profile(customer_id: int):
    try:
        from customer_profile_agent import generate_customer_profile
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT * FROM customers WHERE id=%s", (customer_id,))
        customer = cur.fetchone()
        cur.execute("SELECT * FROM follow_records WHERE customer_id=%s ORDER BY follow_time DESC LIMIT 5", (customer_id,))
        follows = cur.fetchall()
        conn.close()
        
        if not customer:
            raise HTTPException(404, "客户不存在")
        
        profile = generate_customer_profile(customer, follows)
        return {"success": True, "profile": profile}
    except Exception as e:
        raise HTTPException(500, f"生成画像失败: {str(e)}")

# 5. AI分析跟进
@router.post("/follow-analyze/{customer_id}")
def analyze_follows(customer_id: int):
    try:
        from follow_analyzer import analyze_customer_follows
        conn = get_db(); cur = conn.cursor()
        cur.execute("SELECT * FROM follow_records WHERE customer_id=%s ORDER BY follow_time DESC LIMIT 10", (customer_id,))
        follows = cur.fetchall()
        conn.close()
        
        analysis = analyze_customer_follows(follows)
        return {"success": True, "analysis": analysis}
    except Exception as e:
        raise HTTPException(500, f"分析失败: {str(e)}")

# 6. 获取今日销售任务
@router.get("/today-tasks")
def get_today_tasks():
    try:
        from daily_sales_agent import gen_tasks
        result = gen_tasks()
        return result
    except Exception as e:
        raise HTTPException(500, f"生成任务失败: {str(e)}")

# 7. 重新计算客户评分
@router.post("/score/{customer_id}")
def recalc_score(customer_id: int):
    try:
        from customer_scoring import calculate_score
        result = calculate_score(customer_id)
        return {"success": True, "score": result}
    except Exception as e:
        raise HTTPException(500, f"计算评分失败: {str(e)}")
