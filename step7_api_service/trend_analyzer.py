#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI技术趋势分析模块
分析AI行业正在发展的技术方向：近7天vs近30天对比
"""
import os
import sys
import json
import time
import pymysql
import pymysql.cursors
from datetime import datetime, timedelta
from urllib.parse import urlparse

sys.path.insert(0, "/opt/Weibo-Analyst")
from step7_api_service.ai_technologies import AI_TECHNOLOGIES, match_technology

# 缓存目录
CACHE_DIR = "/opt/Weibo-Analyst/step7_api_service/.trend_cache"
os.makedirs(CACHE_DIR, exist_ok=True)


def get_db_connection():
    """获取数据库连接"""
    from dotenv import load_dotenv
    load_dotenv("/opt/Weibo-Analyst/.env")
    
    def to_str(v):
        return v.decode() if isinstance(v, bytes) else v
    
    db_url = os.getenv("DATABASE_URL")
    p = urlparse(db_url)
    return pymysql.connect(
        host=to_str(p.hostname), port=p.port or 4000,
        user=to_str(p.username), password=to_str(p.password),
        database=to_str(p.path).lstrip("/"),
        charset="utf8mb4", ssl={"ssl_disabled": False}
    )


def get_weibo_by_date_range(start_date, end_date, limit=2000):
    """获取指定日期范围的微博数据"""
    conn = get_db_connection()
    cursor = conn.cursor(pymysql.cursors.DictCursor)
    
    query = """
    SELECT id, weibo_id, username, content, publish_time,
           like_count, comment_count, repost_count
    FROM weibo_posts 
    WHERE DATE(publish_time) BETWEEN %s AND %s
    ORDER BY (like_count + comment_count + repost_count) DESC
    LIMIT %s
    """
    cursor.execute(query, (start_date, end_date, limit))
    posts = cursor.fetchall()
    conn.close()
    return posts


def calculate_technology_metrics(posts):
    """
    计算每个AI技术方向的指标
    返回技术指标字典
    """
    tech_stats = {}
    for tech in AI_TECHNOLOGIES:
        tech_stats[tech["name"]] = {
            "name": tech["name"],
            "category": tech["category"],
            "mention_count": 0,
            "interaction_score": 0,
            "like_count": 0,
            "comment_count": 0,
            "repost_count": 0,
            "related_post_ids": [],
            "sample_posts": []
        }
    
    for post in posts:
        content = post.get("content", "") or ""
        matched_techs = match_technology(content)
        
        if not matched_techs:
            continue
        
        like = post.get("like_count", 0) or 0
        comment = post.get("comment_count", 0) or 0
        repost = post.get("repost_count", 0) or 0
        interaction = like + comment + repost
        
        for tech_name in matched_techs:
            if tech_name not in tech_stats:
                continue
            
            stats = tech_stats[tech_name]
            stats["mention_count"] += 1
            stats["interaction_score"] += interaction
            stats["like_count"] += like
            stats["comment_count"] += comment
            stats["repost_count"] += repost
            stats["related_post_ids"].append(str(post.get("weibo_id", "")))
            
            if len(stats["sample_posts"]) < 2 and interaction > 10:
                stats["sample_posts"].append({
                    "username": post.get("username", ""),
                    "content": content[:120],
                    "interaction": interaction
                })
    
    return tech_stats


def determine_trend_level(growth_rate, mention_count):
    """
    判断趋势等级
    rising: 快速增长（增长率>30%且提及数>5）
    stable: 稳定（增长率-20%~30%）
    declining: 下降（增长率<-20%）
    emerging: 新兴（近7天有数据，近30天平均很低）
    """
    if mention_count < 3:
        return "emerging" if mention_count > 0 else "quiet"
    
    if growth_rate > 30:
        return "rising"
    elif growth_rate < -20:
        return "declining"
    else:
        return "stable"


def generate_trend_summary(tech_name, growth_rate, trend_level):
    """生成技术趋势摘要"""
    summaries = {
        "Agent": "AI Agent正在成为企业自动化落地的重要方向，从概念验证走向实际应用",
        "多模态": "多模态大模型能力持续提升，图文视频理解成为竞争焦点",
        "AI编程": "AI编程助手渗透率快速提升，代码生成质量显著改善",
        "AI视频": "AI视频生成技术快速迭代，文生视频质量接近商用水平",
        "AI绘画": "AI绘画工具持续优化，创意设计领域应用广泛",
        "RAG": "检索增强生成成为企业知识库落地的核心技术方案",
        "知识库": "企业知识库与AI结合，智能问答和知识管理需求增长",
        "端侧AI": "端侧大模型部署加速，手机和终端AI能力持续增强",
        "具身智能": "具身智能和人形机器人成为AI投资新热点",
        "机器人": "AI+机器人融合加速，工业和服务机器人应用拓展",
        "AI办公": "AI办公助手普及，文档处理和会议自动化成为标配",
        "自动驾驶": "自动驾驶技术持续进步，世界模型成为新方向",
        "大模型": "大模型能力持续突破，通用人工智能方向稳步推进",
        "小模型": "小模型效率提升，端侧部署和特定场景应用增加",
        "开源模型": "开源大模型生态繁荣，国产开源模型竞争力增强",
        "AI搜索": "AI搜索引擎兴起，传统搜索与生成式AI融合"
    }
    
    base = summaries.get(tech_name, f"{tech_name}技术持续发展")
    
    if trend_level == "rising":
        return f"{base}，近期讨论热度快速上升（增长{growth_rate:.0f}%）"
    elif trend_level == "declining":
        return f"{base}，近期讨论热度有所回落（{growth_rate:.0f}%）"
    elif trend_level == "emerging":
        return f"{base}，作为新兴方向开始受到关注"
    else:
        return f"{base}，发展态势保持稳定"


def generate_business_opportunity(tech_name):
    """生成企业应用机会分析"""
    opportunities = {
        "Agent": "企业可探索流程自动化、知识助手、销售助手、客服自动化等Agent落地场景",
        "多模态": "企业可关注图文理解、视频分析、智能客服等多模态应用",
        "AI编程": "研发团队可引入AI编程助手提升开发效率，降低代码重复工作",
        "AI视频": "营销和内容团队可使用AI视频生成工具降低制作成本",
        "AI绘画": "设计团队可使用AI绘画工具提升创意产出效率",
        "RAG": "企业可基于RAG技术构建智能知识库和问答系统",
        "知识库": "企业可建设AI驱动的知识库，提升知识管理和检索效率",
        "端侧AI": "硬件和终端厂商可关注端侧大模型部署，提升产品智能化水平",
        "具身智能": "制造业和物流企业可关注具身智能在自动化场景的应用",
        "机器人": "企业可探索AI+机器人在生产、服务、物流等场景的应用",
        "AI办公": "企业可全面部署AI办公助手，提升文档处理和会议效率",
        "自动驾驶": "出行和物流企业可关注自动驾驶技术在特定场景的落地",
        "大模型": "企业可基于大模型构建行业应用，提升业务智能化水平",
        "小模型": "企业可在特定场景部署小模型，兼顾效率和成本",
        "开源模型": "企业可基于开源模型构建自主可控的AI应用",
        "AI搜索": "企业可引入AI搜索提升内部信息检索和知识发现效率"
    }
    
    return opportunities.get(tech_name, f"企业可持续关注{tech_name}技术的应用机会")


def relate_events_and_products(tech_name, date_str):
    """关联第一阶段事件和第二阶段产品"""
    related_events = []
    related_products = []
    
    try:
        from step7_api_service.event_analyzer import get_events
        events = get_events(date_str, limit=20)
        for event in events:
            techs = event.get("technologies", []) or []
            if tech_name in techs or any(tech_name in t for t in techs):
                related_events.append(event.get("title", ""))
    except:
        pass
    
    try:
        from step7_api_service.product_analyzer import get_product_metrics
        products = get_product_metrics(date_str, limit=20)
        for product in products:
            # 简单关联：如果产品样本微博包含该技术
            for sample in product.get("sample_posts", []):
                if tech_name in sample.get("content", ""):
                    related_products.append(product.get("name", ""))
                    break
    except:
        pass
    
    return related_events[:3], list(set(related_products))[:5]


def analyze_and_save(date_str, force=False):
    """
    分析并保存技术趋势数据
    带缓存机制
    """
    cache_file = os.path.join(CACHE_DIR, f"trends_{date_str}.json")
    
    if not force and os.path.exists(cache_file):
        with open(cache_file, "r", encoding="utf-8") as f:
            return json.load(f)
    
    print(f"Analyzing technology trends for {date_str}...")
    
    # 计算日期范围
    try:
        end_date = datetime.strptime(date_str, "%Y-%m-%d")
    except:
        end_date = datetime.now()
    
    start_7days = (end_date - timedelta(days=7)).strftime("%Y-%m-%d")
    start_30days = (end_date - timedelta(days=30)).strftime("%Y-%m-%d")
    end_date_str = end_date.strftime("%Y-%m-%d")
    
    # 获取近7天和近30天数据
    print(f"Fetching weibo data: 7 days ({start_7days} to {end_date_str})...")
    posts_7days = get_weibo_by_date_range(start_7days, end_date_str, limit=2000)
    print(f"Found {len(posts_7days)} posts in 7 days")
    
    print(f"Fetching weibo data: 30 days ({start_30days} to {end_date_str})...")
    posts_30days = get_weibo_by_date_range(start_30days, end_date_str, limit=5000)
    print(f"Found {len(posts_30days)} posts in 30 days")
    
    # 计算技术指标
    metrics_7days = calculate_technology_metrics(posts_7days)
    metrics_30days = calculate_technology_metrics(posts_30days)
    
    # 计算增长率和趋势
    trends = []
    for tech_name, stats_7 in metrics_7days.items():
        stats_30 = metrics_30days.get(tech_name, {})
        
        mention_7 = stats_7["mention_count"]
        mention_30_avg = stats_30.get("mention_count", 0) / 4.0  # 30天平均到7天
        
        if mention_30_avg > 0:
            growth_rate = (mention_7 - mention_30_avg) / mention_30_avg * 100
        else:
            growth_rate = 100.0 if mention_7 > 0 else 0.0
        
        # 热度评分
        heat_score = min(mention_7 * 8 + stats_7["interaction_score"] / 50, 100)
        
        # 趋势等级
        trend_level = determine_trend_level(growth_rate, mention_7)
        
        # 摘要和企业机会
        summary = generate_trend_summary(tech_name, growth_rate, trend_level)
        business_opportunity = generate_business_opportunity(tech_name)
        
        # 关联事件和产品
        related_events, related_products = relate_events_and_products(tech_name, date_str)
        
        trends.append({
            "name": tech_name,
            "category": stats_7["category"],
            "mention_count_7days": mention_7,
            "mention_count_30days": stats_30.get("mention_count", 0),
            "interaction_score": stats_7["interaction_score"],
            "growth_rate": round(growth_rate, 1),
            "heat_score": round(heat_score, 1),
            "trend_level": trend_level,
            "summary": summary,
            "business_opportunity": business_opportunity,
            "related_events": related_events,
            "related_products": related_products,
            "sample_posts": stats_7["sample_posts"]
        })
    
    # 按热度排序
    trends.sort(key=lambda x: x["heat_score"], reverse=True)
    
    # 添加排名
    for i, trend in enumerate(trends, 1):
        trend["rank"] = i
    
    # 保存到数据库
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("DELETE FROM ai_trends WHERE date = %s", (date_str,))
        
        for trend in trends:
            cursor.execute("""
                INSERT INTO ai_trends 
                (technology_name, date, mention_count, growth_rate, heat_score, 
                 trend_level, summary, related_events, related_products, 
                 business_opportunity, created_time)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            """, (
                trend["name"],
                date_str,
                trend["mention_count_7days"],
                trend["growth_rate"],
                trend["heat_score"],
                trend["trend_level"],
                trend["summary"],
                json.dumps(trend["related_events"], ensure_ascii=False),
                json.dumps(trend["related_products"], ensure_ascii=False),
                trend["business_opportunity"]
            ))
        
        conn.commit()
        conn.close()
        print(f"Saved {len(trends)} technology trends to database")
    except Exception as e:
        print(f"Database save error: {e}")
    
    # 保存缓存
    result = {
        "date": date_str,
        "count": len(trends),
        "trends": trends,
        "analyzed_at": datetime.now().isoformat()
    }
    
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    return result


def _find_latest_trend_cache(date_str):
    """查找不晚于指定日期的最近趋势缓存文件，返回 (路径, 日期)；无则 (None, None)"""
    try:
        files = [f for f in os.listdir(CACHE_DIR)
                 if f.startswith("trends_") and f.endswith(".json")]
    except FileNotFoundError:
        return None, None
    dates = sorted(f[len("trends_"):-len(".json")] for f in files)
    if not dates:
        return None, None
    older = [d for d in dates if d <= date_str]
    target = older[-1] if older else dates[-1]
    return os.path.join(CACHE_DIR, f"trends_{target}.json"), target


def get_trends(date_str, limit=20, level=None):
    """获取指定日期的技术趋势数据。
    只读已生成结果：当天缓存 → 最近一天缓存（冷启动兜底，避免GET触发扫描数千条微博的重计算）
    → 完全无历史数据（全新部署）时才实时分析一次。"""
    cache_file = os.path.join(CACHE_DIR, f"trends_{date_str}.json")

    if os.path.exists(cache_file):
        with open(cache_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        latest_file, _ = _find_latest_trend_cache(date_str)
        if latest_file:
            with open(latest_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        else:
            data = analyze_and_save(date_str)

    trends = data.get("trends", [])

    if level:
        trends = [t for t in trends if t.get("trend_level") == level]

    return trends[:limit]


def get_trend_history(technology_name, days=30):
    """获取技术的历史趋势数据"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        
        cursor.execute("""
            SELECT date, mention_count, growth_rate, heat_score, trend_level
            FROM ai_trends 
            WHERE technology_name = %s
            ORDER BY date DESC
            LIMIT %s
        """, (technology_name, days))
        
        rows = cursor.fetchall()
        conn.close()
        
        trend_data = []
        for row in reversed(rows):
            trend_data.append({
                "date": row["date"].isoformat() if hasattr(row["date"], "isoformat") else str(row["date"]),
                "mention_count": row["mention_count"],
                "growth_rate": float(row["growth_rate"]) if row["growth_rate"] else 0,
                "heat_score": float(row["heat_score"]) if row["heat_score"] else 0,
                "trend_level": row["trend_level"]
            })
        
        return trend_data
    except Exception as e:
        print(f"Trend history error: {e}")
        return []
