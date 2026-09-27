"""
AI销售机会分析模块
分析AI事件、产品变化、技术趋势，自动发现销售机会
"""

import pymysql
import json
import os
from datetime import datetime, timedelta
from urllib.parse import urlparse
from dotenv import load_dotenv
try:
    from step7_api_service.industries import get_all_industries, get_industry_by_name, match_industry_by_technology
except ImportError:
    from industries import get_all_industries, get_industry_by_name, match_industry_by_technology

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


def get_recent_events(date_str, limit=20):
    """获取近期AI事件"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM ai_events 
        WHERE event_date >= %s 
        ORDER BY heat_score DESC 
        LIMIT %s
    """, (date_str, limit))
    events = cursor.fetchall()
    conn.close()
    return events


def get_recent_trends(date_str, limit=20):
    """获取近期技术趋势"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM ai_trends 
        WHERE date = %s 
        ORDER BY growth_rate DESC 
        LIMIT %s
    """, (date_str, limit))
    trends = cursor.fetchall()
    conn.close()
    return trends


def get_recent_products(date_str, limit=20):
    """获取近期产品数据"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM ai_product_metrics 
        WHERE date = %s 
        ORDER BY heat_score DESC 
        LIMIT %s
    """, (date_str, limit))
    products = cursor.fetchall()
    conn.close()
    return products


def analyze_opportunities_from_events(events, date_str):
    """从AI事件分析销售机会"""
    opportunities = []
    
    for event in events:
        technologies = event.get("technologies", "")
        if isinstance(technologies, str):
            tech_list = [t.strip() for t in technologies.split(",") if t.strip()]
        else:
            tech_list = technologies or []
        
        companies = event.get("companies", "")
        if isinstance(companies, str):
            company_list = [c.strip() for c in companies.split(",") if c.strip()]
        else:
            company_list = companies or []
        
        # 根据技术匹配行业
        matched_industries = set()
        for tech in tech_list:
            industries = match_industry_by_technology(tech)
            matched_industries.update(industries)
        
        # 如果没有匹配到，根据事件标题关键词匹配
        if not matched_industries:
            title = event.get("title", "")
            summary = event.get("summary", "")
            for industry in get_all_industries():
                for pain in industry.get("pain_points", []):
                    if pain[:2] in title or pain[:2] in summary:
                        matched_industries.add(industry["name"])
                        break
        
        # 为每个匹配的行业生成机会
        for industry_name in list(matched_industries)[:3]:
            industry = get_industry_by_name(industry_name)
            if not industry:
                continue
            
            # 确定优先级
            heat = event.get("heat_score", 0) or 0
            confidence = event.get("event_confidence", 0) or 0
            if heat >= 80 and confidence >= 70:
                priority = "high"
            elif heat >= 60:
                priority = "medium"
            else:
                priority = "low"
            
            # 选择推荐场景
            scenario = industry["scenarios"][0] if industry["scenarios"] else "AI应用"
            
            # 生成销售切入点
            sales_angle = f"近期{event.get('title', 'AI行业')}引发关注，{industry_name}企业可关注{scenario}场景，提升业务效率。"
            
            opportunity = {
                "date": date_str,
                "industry": industry_name,
                "scenario": scenario,
                "trigger_type": "event",
                "trigger_content": event.get("title", ""),
                "technology": ",".join(tech_list[:3]),
                "product": ",".join(industry["recommended_products"][:2]),
                "customer_type": industry["customer_type"],
                "sales_angle": sales_angle,
                "priority": priority
            }
            opportunities.append(opportunity)
    
    return opportunities


def analyze_opportunities_from_trends(trends, date_str):
    """从技术趋势分析销售机会"""
    opportunities = []
    
    for trend in trends:
        tech_name = trend.get("technology_name", "")
        growth_rate = trend.get("growth_rate", 0) or 0
        trend_level = trend.get("trend_level", "")
        
        # 只分析增长趋势
        if growth_rate <= 10 and trend_level not in ["rising", "emerging"]:
            continue
        
        # 匹配行业
        matched_industries = match_industry_by_technology(tech_name)
        
        for industry_name in matched_industries[:2]:
            industry = get_industry_by_name(industry_name)
            if not industry:
                continue
            
            # 优先级
            if growth_rate >= 50 or trend_level == "rising":
                priority = "high"
            elif growth_rate >= 20:
                priority = "medium"
            else:
                priority = "low"
            
            scenario = industry["scenarios"][0] if industry["scenarios"] else "AI应用"
            
            sales_angle = f"{tech_name}技术近期增长{growth_rate:.0f}%，{industry_name}企业可提前布局{scenario}场景。"
            
            opportunity = {
                "date": date_str,
                "industry": industry_name,
                "scenario": scenario,
                "trigger_type": "trend",
                "trigger_content": f"{tech_name}增长{growth_rate:.0f}%",
                "technology": tech_name,
                "product": ",".join(industry["recommended_products"][:2]),
                "customer_type": industry["customer_type"],
                "sales_angle": sales_angle,
                "priority": priority
            }
            opportunities.append(opportunity)
    
    return opportunities


def save_opportunities(opportunities, date_str):
    """保存销售机会到数据库"""
    if not opportunities:
        return 0
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 先删除当天的旧数据
    cursor.execute("DELETE FROM ai_sales_opportunities WHERE date = %s", (date_str,))
    
    # 插入新数据
    inserted = 0
    for opp in opportunities:
        try:
            cursor.execute("""
                INSERT INTO ai_sales_opportunities 
                (date, industry, scenario, trigger_type, trigger_content, 
                 technology, product, customer_type, sales_angle, priority)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                opp["date"], opp["industry"], opp["scenario"], 
                opp["trigger_type"], opp["trigger_content"],
                opp["technology"], opp["product"], opp["customer_type"],
                opp["sales_angle"], opp["priority"]
            ))
            inserted += 1
        except Exception as e:
            print(f"插入失败: {e}")
    
    conn.commit()
    conn.close()
    return inserted


def get_opportunities(date_str=None, priority=None, industry=None, limit=50):
    """获取销售机会列表"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = "SELECT * FROM ai_sales_opportunities WHERE 1=1"
    params = []
    
    if date_str:
        query += " AND date = %s"
        params.append(date_str)
    if priority:
        query += " AND priority = %s"
        params.append(priority)
    if industry:
        query += " AND industry = %s"
        params.append(industry)
    
    query += " ORDER BY FIELD(priority, 'high', 'medium', 'low'), id DESC LIMIT %s"
    params.append(limit)
    
    cursor.execute(query, params)
    opportunities = cursor.fetchall()
    conn.close()
    
    return opportunities


def get_latest_date():
    """获取销售机会表中最新的分析日期；无数据返回 None"""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT MAX(`date`) AS m FROM ai_sales_opportunities")
    row = cursor.fetchone()
    conn.close()
    if not row or not row.get("m"):
        return None
    v = row["m"]
    return v.isoformat() if hasattr(v, "isoformat") else str(v)


def analyze_and_save(date_str=None, force=False):
    """分析并保存当天销售机会"""
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")
    
    # 检查是否已有数据
    existing = get_opportunities(date_str=date_str, limit=1)
    if existing and not force:
        print(f"[销售机会] {date_str} 已有数据，跳过")
        return existing
    
    print(f"[销售机会] 开始分析 {date_str}...")
    
    # 获取数据
    week_ago = (datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=7)).strftime("%Y-%m-%d")
    events = get_recent_events(week_ago, limit=20)
    trends = get_recent_trends(date_str, limit=20)
    
    print(f"[销售机会] 获取到 {len(events)} 个事件, {len(trends)} 个趋势")
    
    # 分析机会
    opp_from_events = analyze_opportunities_from_events(events, date_str)
    opp_from_trends = analyze_opportunities_from_trends(trends, date_str)
    
    all_opportunities = opp_from_events + opp_from_trends
    
    # 去重（按行业+场景）
    seen = set()
    unique_opportunities = []
    for opp in all_opportunities:
        key = f"{opp['industry']}_{opp['scenario']}"
        if key not in seen:
            seen.add(key)
            unique_opportunities.append(opp)
    
    print(f"[销售机会] 生成 {len(unique_opportunities)} 个销售机会")
    
    # 保存
    inserted = save_opportunities(unique_opportunities, date_str)
    print(f"[销售机会] 保存 {inserted} 条记录")
    
    return unique_opportunities


if __name__ == "__main__":
    import sys
    date = sys.argv[1] if len(sys.argv) > 1 else None
    force = "--force" in sys.argv
    result = analyze_and_save(date, force=force)
    print(f"完成，共 {len(result)} 个销售机会")
