#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI产品声量分析模块
统计每个AI产品在微博中的表现：出现次数、互动热度、增长率、情绪、关联事件
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
from step7_api_service.ai_products import AI_PRODUCTS, match_product, get_product_by_name

# 缓存目录
CACHE_DIR = "/opt/Weibo-Analyst/step7_api_service/.product_cache"
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


def get_weibo_by_date(date_str, limit=500):
    """获取指定日期的微博数据"""
    conn = get_db_connection()
    cursor = conn.cursor(pymysql.cursors.DictCursor)
    
    query = """
    SELECT id, weibo_id, username, content, publish_time, 
           like_count, comment_count, repost_count
    FROM weibo_posts 
    WHERE DATE(publish_time) = %s
    ORDER BY (like_count + comment_count + repost_count) DESC
    LIMIT %s
    """
    cursor.execute(query, (date_str, limit))
    posts = cursor.fetchall()
    conn.close()
    return posts


def calculate_product_metrics(posts, date_str):
    """
    计算每个AI产品的声量指标
    返回产品指标列表
    """
    # 初始化每个产品的统计
    product_stats = {}
    for product in AI_PRODUCTS:
        product_stats[product["name"]] = {
            "name": product["name"],
            "company": product["company"],
            "country": product["country"],
            "category": product["category"],
            "mention_count": 0,
            "interaction_score": 0,
            "like_count": 0,
            "comment_count": 0,
            "repost_count": 0,
            "positive_count": 0,
            "negative_count": 0,
            "neutral_count": 0,
            "related_post_ids": [],
            "sample_posts": []
        }
    
    # 遍历微博，匹配产品
    for post in posts:
        content = post.get("content", "") or ""
        username = post.get("username", "") or ""
        
        # 匹配产品（内容+用户名）
        matched_products = match_product(content)
        if not matched_products:
            matched_products = match_product(username)
        
        if not matched_products:
            continue
        
        like = post.get("like_count", 0) or 0
        comment = post.get("comment_count", 0) or 0
        repost = post.get("repost_count", 0) or 0
        interaction = like + comment + repost
        
        for product_name in matched_products:
            if product_name not in product_stats:
                continue
            
            stats = product_stats[product_name]
            stats["mention_count"] += 1
            stats["interaction_score"] += interaction
            stats["like_count"] += like
            stats["comment_count"] += comment
            stats["repost_count"] += repost
            stats["related_post_ids"].append(str(post.get("weibo_id", "")))
            
            # 简单情绪判断（基于关键词）
            content_lower = content.lower()
            positive_words = ["好", "棒", "强", "牛", "喜欢", "支持", "优秀", "厉害", "突破", "领先"]
            negative_words = ["差", "烂", "垃圾", "失望", "问题", "bug", "失败", "落后", "争议"]
            
            pos_score = sum(1 for w in positive_words if w in content)
            neg_score = sum(1 for w in negative_words if w in content)
            
            if pos_score > neg_score:
                stats["positive_count"] += 1
            elif neg_score > pos_score:
                stats["negative_count"] += 1
            else:
                stats["neutral_count"] += 1
            
            # 保存样本微博（最多3条）
            if len(stats["sample_posts"]) < 3 and interaction > 10:
                stats["sample_posts"].append({
                    "username": username,
                    "content": content[:150],
                    "interaction": interaction
                })
    
    # 计算情绪比例和热度评分
    result = []
    for name, stats in product_stats.items():
        if stats["mention_count"] == 0:
            continue
        
        total = stats["positive_count"] + stats["negative_count"] + stats["neutral_count"]
        if total > 0:
            sentiment = {
                "positive": round(stats["positive_count"] / total * 100, 1),
                "neutral": round(stats["neutral_count"] / total * 100, 1),
                "negative": round(stats["negative_count"] / total * 100, 1)
            }
            # 主导情绪
            if sentiment["positive"] >= sentiment["negative"] and sentiment["positive"] >= sentiment["neutral"]:
                main_sentiment = "positive"
            elif sentiment["negative"] >= sentiment["positive"] and sentiment["negative"] >= sentiment["neutral"]:
                main_sentiment = "negative"
            else:
                main_sentiment = "neutral"
        else:
            sentiment = {"positive": 0, "neutral": 0, "negative": 0}
            main_sentiment = "neutral"
        
        # 热度评分（0-100）：基于提及量和互动量
        mention_score = min(stats["mention_count"] * 5, 50)  # 最多50分
        interaction_score = min(stats["interaction_score"] / 100, 50)  # 最多50分
        heat_score = min(round(mention_score + interaction_score, 1), 100)
        
        result.append({
            "name": name,
            "company": stats["company"],
            "country": stats["country"],
            "category": stats["category"],
            "mention_count": stats["mention_count"],
            "interaction_score": stats["interaction_score"],
            "like_count": stats["like_count"],
            "comment_count": stats["comment_count"],
            "repost_count": stats["repost_count"],
            "heat_score": heat_score,
            "sentiment": sentiment,
            "main_sentiment": main_sentiment,
            "related_post_ids": stats["related_post_ids"][:20],
            "sample_posts": stats["sample_posts"]
        })
    
    # 按热度排序
    result.sort(key=lambda x: x["heat_score"], reverse=True)
    
    # 添加排名
    for i, item in enumerate(result, 1):
        item["rank"] = i
    
    return result


def get_yesterday_metrics(date_str):
    """获取前一天的产品指标（用于计算增长率）"""
    try:
        date = datetime.strptime(date_str, "%Y-%m-%d")
        yesterday = (date - timedelta(days=1)).strftime("%Y-%m-%d")
    except:
        return {}
    
    cache_file = os.path.join(CACHE_DIR, f"products_{yesterday}.json")
    if os.path.exists(cache_file):
        with open(cache_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {item["name"]: item for item in data.get("products", [])}
    
    # 如果缓存不存在，尝试从数据库读取
    try:
        conn = get_db_connection()
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        cursor.execute("""
            SELECT product_name, mention_count, interaction_score, heat_score
            FROM ai_product_metrics 
            WHERE date = %s
        """, (yesterday,))
        rows = cursor.fetchall()
        conn.close()
        return {row["product_name"]: row for row in rows}
    except:
        return {}


def calculate_trend_rate(today_heat, yesterday_heat):
    """计算增长率"""
    if yesterday_heat == 0:
        if today_heat > 0:
            return 100.0  # 新出现
        return 0.0
    return round((today_heat - yesterday_heat) / yesterday_heat * 100, 1)


def relate_events(products, date_str):
    """
    关联第一阶段的AI事件
    根据事件涉及的公司匹配产品
    """
    try:
        from step7_api_service.event_analyzer import get_events
        events = get_events(date_str, limit=20)
    except:
        events = []
    
    event_map = {}
    for event in events:
        companies = event.get("companies", []) or []
        for company in companies:
            if company not in event_map:
                event_map[company] = []
            event_map[company].append(event.get("title", ""))
    
    # 为每个产品匹配关联事件
    for product in products:
        company = product.get("company", "")
        related = event_map.get(company, [])
        product["related_events"] = related[:3]
        
        # 生成增长原因
        if related and product.get("trend_rate", 0) > 0:
            product["trend_reason"] = f"由于「{related[0]}」事件，今日讨论量上涨"
        elif product.get("trend_rate", 0) > 20:
            product["trend_reason"] = "产品讨论热度持续上升"
        elif product.get("trend_rate", 0) < -20:
            product["trend_reason"] = "讨论热度有所回落"
        else:
            product["trend_reason"] = "热度保持稳定"
    
    return products


def get_latest_metrics_date():
    """返回有产品声量数据的最新日期(YYYY-MM-DD)，无数据返回None"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(`date`) FROM ai_product_metrics")
        row = cursor.fetchone()
        conn.close()
        if row and row[0]:
            d = row[0]
            return d.isoformat() if hasattr(d, "isoformat") else str(d)
    except Exception as e:
        print(f"获取最新产品数据日期失败: {e}")
    return None


def analyze_and_save(date_str, force=False):
    """
    分析并保存产品声量数据
    带缓存机制
    """
    cache_file = os.path.join(CACHE_DIR, f"products_{date_str}.json")
    
    # 检查缓存
    if not force and os.path.exists(cache_file):
        with open(cache_file, "r", encoding="utf-8") as f:
            return json.load(f)
    
    print(f"Analyzing product metrics for {date_str}...")
    
    # 获取微博数据
    posts = get_weibo_by_date(date_str, limit=500)
    print(f"Found {len(posts)} weibo posts for {date_str}")
    
    # 计算产品指标
    products = calculate_product_metrics(posts, date_str)
    print(f"Matched {len(products)} AI products")
    
    # 获取昨日数据，计算增长率
    yesterday_data = get_yesterday_metrics(date_str)
    for product in products:
        name = product["name"]
        yesterday_heat = yesterday_data.get(name, {}).get("heat_score", 0)
        product["trend_rate"] = calculate_trend_rate(product["heat_score"], yesterday_heat)
        product["yesterday_heat"] = yesterday_heat
    
    # 关联事件
    products = relate_events(products, date_str)
    
    # 保存到数据库
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 删除旧数据
        cursor.execute("DELETE FROM ai_product_metrics WHERE date = %s", (date_str,))
        
        # 插入新数据
        for product in products:
            cursor.execute("""
                INSERT INTO ai_product_metrics 
                (product_name, company, date, mention_count, interaction_score, 
                 heat_score, trend_rate, sentiment, related_events, created_time)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            """, (
                product["name"],
                product["company"],
                date_str,
                product["mention_count"],
                product["interaction_score"],
                product["heat_score"],
                product.get("trend_rate", 0),
                json.dumps(product["sentiment"], ensure_ascii=False),
                json.dumps(product.get("related_events", []), ensure_ascii=False)
            ))
        
        conn.commit()
        conn.close()
        print(f"Saved {len(products)} product metrics to database")
    except Exception as e:
        print(f"Database save error: {e}")
    
    # 保存缓存
    result = {
        "date": date_str,
        "count": len(products),
        "products": products,
        "analyzed_at": datetime.now().isoformat()
    }
    
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    
    return result


def get_product_metrics(date_str, limit=20, country=None):
    """获取指定日期的产品声量数据"""
    cache_file = os.path.join(CACHE_DIR, f"products_{date_str}.json")
    
    if os.path.exists(cache_file):
        with open(cache_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        products = data.get("products", [])
    else:
        # 如果没有缓存，尝试分析
        data = analyze_and_save(date_str)
        products = data.get("products", [])
    
    # 按国家筛选
    if country:
        products = [p for p in products if p.get("country") == country]
    
    return products[:limit]


def get_product_trend(product_name, days=30):
    """获取产品的历史趋势数据"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        
        cursor.execute("""
            SELECT date, mention_count, interaction_score, heat_score, trend_rate
            FROM ai_product_metrics 
            WHERE product_name = %s
            ORDER BY date DESC
            LIMIT %s
        """, (product_name, days))
        
        rows = cursor.fetchall()
        conn.close()
        
        # 转换日期格式
        trend_data = []
        for row in reversed(rows):
            trend_data.append({
                "date": row["date"].isoformat() if hasattr(row["date"], "isoformat") else str(row["date"]),
                "mention_count": row["mention_count"],
                "interaction_score": row["interaction_score"],
                "heat_score": row["heat_score"],
                "trend_rate": row["trend_rate"]
            })
        
        return trend_data
    except Exception as e:
        print(f"Trend query error: {e}")
        return []
