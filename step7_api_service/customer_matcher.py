"""
客户匹配模块
根据客户行业、规模等信息匹配AI销售机会
"""

import pymysql
import os
from datetime import datetime
from urllib.parse import urlparse
from dotenv import load_dotenv
from industries import get_industry_by_name
from sales_opportunity_analyzer import get_opportunities

load_dotenv("/opt/Weibo-Analyst/.env")


def get_db_connection():
    """获取数据库连接"""
    db_url = os.getenv("DATABASE_URL")
    parsed = urlparse(db_url)
    return pymysql.connect(
        host=parsed.hostname,
        port=parsed.port or 3306,
        user=parsed.username if isinstance(parsed.username, str) else parsed.username.decode(),
        password=parsed.password if isinstance(parsed.password, str) else parsed.password.decode(),
        database=parsed.path.lstrip("/"),
        ssl={"ssl_disabled": False},
        cursorclass=pymysql.cursors.DictCursor
    )


def match_customer_opportunities(customer_name, industry, date_str=None, customer_id=None):
    """
    匹配客户的AI机会
    根据客户行业匹配相关销售机会，计算匹配度
    """
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")
    
    # 获取当天的销售机会
    opportunities = get_opportunities(date_str=date_str, limit=50)
    
    # 如果当天没有，获取最近7天的
    if not opportunities:
        from datetime import timedelta
        week_ago = (datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
        opportunities = get_opportunities(date_str=None, limit=50)
    
    matched = []
    
    for opp in opportunities:
        match_score = 0
        reasons = []
        
        # 行业匹配（权重60%）
        if opp.get("industry") == industry:
            match_score += 60
            reasons.append(f"行业匹配：{industry}")
        else:
            # 相关行业部分匹配
            industry_info = get_industry_by_name(industry)
            if industry_info:
                opp_industry_info = get_industry_by_name(opp.get("industry", ""))
                if opp_industry_info:
                    # 检查是否有共同关注的技术
                    common_techs = set(industry_info.get("key_technologies", [])) & set(opp_industry_info.get("key_technologies", []))
                    if common_techs:
                        match_score += 30
                        reasons.append(f"相关行业，共同关注：{', '.join(list(common_techs)[:2])}")
        
        # 优先级匹配（权重20%）
        priority = opp.get("priority", "medium")
        if priority == "high":
            match_score += 20
            reasons.append("高优先级机会")
        elif priority == "medium":
            match_score += 10
        
        # 触发类型（权重20%）
        trigger_type = opp.get("trigger_type", "")
        if trigger_type == "event":
            match_score += 15
            reasons.append(f"事件驱动：{opp.get('trigger_content', '')[:30]}")
        elif trigger_type == "trend":
            match_score += 10
            reasons.append(f"趋势驱动：{opp.get('trigger_content', '')[:30]}")
        
        if match_score >= 40:
            matched.append({
                "customer_name": customer_name,
                "customer_id": customer_id,
                "industry": industry,
                "opportunity": opp,
                "match_score": min(100, match_score),
                "reason": "；".join(reasons),
                "recommended_scene": opp.get("scenario", ""),
                "suggestion": f"建议向{customer_name}介绍{opp.get('scenario', '')}场景，切入点：{opp.get('sales_angle', '')[:50]}"
            })
    
    # 按匹配度排序
    matched.sort(key=lambda x: x["match_score"], reverse=True)
    
    return matched[:5]


def save_customer_opportunity(customer_name, industry, match_score, recommended_scene, reason, suggestion, customer_id=None, status="new"):
    """保存客户机会到数据库"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO customer_ai_opportunities 
        (customer_id, customer_name, industry, match_score, recommended_scene, reason, suggestion, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """, (customer_id, customer_name, industry, match_score, recommended_scene, reason, suggestion, status))
    
    conn.commit()
    opp_id = cursor.lastrowid
    conn.close()
    return opp_id


def get_customer_opportunities(customer_id=None, status=None, limit=50):
    """获取客户机会列表"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = "SELECT * FROM customer_ai_opportunities WHERE 1=1"
    params = []
    
    if customer_id:
        query += " AND customer_id = %s"
        params.append(customer_id)
    if status:
        query += " AND status = %s"
        params.append(status)
    
    query += " ORDER BY match_score DESC, created_time DESC LIMIT %s"
    params.append(limit)
    
    cursor.execute(query, params)
    results = cursor.fetchall()
    conn.close()
    return results


def update_customer_opportunity_status(opp_id, status):
    """更新客户机会状态"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE customer_ai_opportunities 
        SET status = %s 
        WHERE id = %s
    """, (status, opp_id))
    conn.commit()
    conn.close()
    return True
