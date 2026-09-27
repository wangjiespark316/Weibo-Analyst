#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI热点事件自动发现模块
- 从微博数据中自动识别AI行业热点事件
- 使用LLM进行内容聚类和事件提取
- 支持缓存和历史查询
"""
import os
import json
import time
import pymysql
import pymysql.cursors
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from dotenv import load_dotenv

load_dotenv("/opt/Weibo-Analyst/.env")

# LLM配置
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_API_BASE = os.getenv("LLM_API_BASE", "https://api.deepseek.com/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")

# 缓存目录
CACHE_DIR = "/opt/Weibo-Analyst/step7_api_service/.event_cache"
os.makedirs(CACHE_DIR, exist_ok=True)


# 分类枚举映射（兼容旧数据的中文分类）
CATEGORY_MAPPING = {
    "产品发布": "product_launch",
    "技术突破": "technology_breakthrough",
    "融资并购": "financing",
    "政策监管": "policy",
    "行业动态": "industry_trend",
    "公司动态": "company_news",
    "模型发布": "model_release",
    "企业应用案例": "application_case",
}

def normalize_category(category: str) -> str:
    """规范化分类为枚举值"""
    if not category:
        return "industry_trend"
    # 如果已经是英文枚举，直接返回
    valid_categories = [
        "model_release", "product_launch", "company_news", 
        "financing", "policy", "technology_breakthrough",
        "application_case", "industry_trend"
    ]
    if category in valid_categories:
        return category
    # 中文映射
    return CATEGORY_MAPPING.get(category, "industry_trend")



def get_db_connection():
    """获取数据库连接"""
    from urllib.parse import urlparse
    
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


def get_hot_weibo(date_str: str, limit: int = 30) -> List[Dict]:
    """获取指定日期的热门微博"""
    conn = get_db_connection()
    cursor = conn.cursor(pymysql.cursors.DictCursor)
    
    query = """
    SELECT weibo_id, username, content, publish_time, 
           like_count, comment_count, repost_count
    FROM weibo_posts
    WHERE DATE(publish_time) = %s
    ORDER BY (like_count + comment_count * 2 + repost_count * 3) DESC
    LIMIT %s
    """
    cursor.execute(query, (date_str, limit))
    posts = cursor.fetchall()
    conn.close()
    return posts


def call_llm(messages: List[Dict], max_tokens: int = 2000) -> Optional[str]:
    """调用LLM API"""
    try:
        import requests
        headers = {
            "Authorization": f"Bearer {LLM_API_KEY}",
            "Content-Type": "application/json"
        }
        data = {
            "model": LLM_MODEL,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0.3
        }
        response = requests.post(
            f"{LLM_API_BASE}/chat/completions",
            headers=headers, json=data, timeout=60
        )
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"]
        else:
            print(f"LLM API error: {response.status_code} - {response.text}")
            return None
    except Exception as e:
        print(f"LLM call failed: {e}")
        return None


def analyze_events(posts: List[Dict], date_str: str) -> List[Dict]:
    """使用LLM分析微博数据，提取热点事件"""
    if not posts:
        return []
    
    # 准备微博数据
    weibo_text = ""
    for i, p in enumerate(posts[:20], 1):
        content = p.get("content", "")[:200]
        username = p.get("username", "未知")
        likes = p.get("like_count", 0)
        comments = p.get("comment_count", 0)
        reposts = p.get("repost_count", 0)
        weibo_text += f"{i}. @{username} (赞{likes}/评{comments}/转{reposts}): {content}\n\n"
    
    system_prompt = """你是一个资深AI行业情报分析师。请分析以下微博数据，识别出今天AI行业真正重要的变化和事件。

核心目标：不是简单总结微博，而是发现AI行业真正有价值的情报。

分析要求：
1. 区分"新闻事件"和"普通讨论"：只提取具有行业影响力的真实事件
2. 判断事件重要性：这个事件是否会影响行业格局、技术方向或企业决策
3. 评估可信度：根据相关微博数量、高影响力账号参与度、互动数据综合判断
4. 分析企业价值：这个事件对企业有什么影响，哪些行业可以落地应用

每个事件必须包含：
- title: 事件标题（简洁有力，突出核心变化）
- summary: 事件摘要（100字以内，说明发生了什么）
- category: 分类（只能是以下枚举）
  - model_release: 模型发布
  - product_launch: 产品发布
  - company_news: 公司动态
  - financing: 融资投资
  - policy: 政策监管
  - technology_breakthrough: 技术突破
  - application_case: 企业应用案例
  - industry_trend: 行业趋势
- companies: 涉及公司（数组）
- technologies: 涉及技术方向（数组）
- heat_score: 热度评分(0-100)，基于微博讨论量和互动数据
- event_confidence: 事件可信度(0-100)，综合判断：
  - 相关微博数量（越多越可信）
  - 高影响力账号参与（大V/官方账号参与提升可信度）
  - 多来源交叉验证（多个独立来源讨论提升可信度）
  - 数据充分性（有具体数据/事实支撑提升可信度）
- sentiment: 情感倾向（positive/neutral/negative）
- impact_analysis: 行业影响分析（100字以内，说明对AI行业的影响）
- business_opportunity: 企业应用机会（100字以内，说明企业可以关注哪些落地场景，按行业举例）
- related_keywords: 相关关键词（数组）

输出要求：
- 只输出JSON格式，不要其他文字
- 提取3-5个最重要的事件
- 优先选择有具体事实、数据、公司参与的真实事件
- 避免普通吐槽、个人观点、无实质内容的讨论

输出格式：
{
  "events": [
    {
      "title": "事件标题",
      "summary": "事件摘要",
      "category": "product_launch",
      "companies": ["公司1"],
      "technologies": ["技术1"],
      "heat_score": 85,
      "event_confidence": 90,
      "sentiment": "positive",
      "impact_analysis": "行业影响分析",
      "business_opportunity": "企业可以关注...",
      "related_keywords": ["关键词1"]
    }
  ]
}"""
    
    user_prompt = f"分析日期：{date_str}\n\n微博数据：\n{weibo_text}"
    
    result = call_llm([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ], max_tokens=2500)
    
    if not result:
        return []
    
    # 解析JSON
    try:
        # 清理可能的markdown标记
        result = result.strip()
        if result.startswith("```json"):
            result = result[7:]
        if result.startswith("```"):
            result = result[3:]
        if result.endswith("```"):
            result = result[:-3]
        result = result.strip()
        
        data = json.loads(result)
        events = data.get("events", [])
        
        # 规范化分类
        for event in events:
            event["category"] = normalize_category(event.get("category", ""))
        
        # 添加相关微博ID
        for event in events:
            event["related_posts"] = [p.get("weibo_id", "") for p in posts[:5]]
        
        return events
    except Exception as e:
        print(f"Failed to parse LLM result: {e}")
        print(f"Raw result: {result[:500]}")
        return []


def save_events(events: List[Dict], date_str: str):
    """保存事件到数据库"""
    if not events:
        return
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 先删除当天的旧事件
    cursor.execute("DELETE FROM ai_events WHERE event_date = %s", (date_str,))
    
    for event in events:
        insert_sql = """
        INSERT INTO ai_events 
        (event_date, title, summary, category, companies, technologies, 
         heat_score, sentiment, related_posts, related_keywords, impact_analysis, 
         event_confidence, business_opportunity, source)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'weibo')
        """
        cursor.execute(insert_sql, (
            date_str,
            event.get("title", ""),
            event.get("summary", ""),
            event.get("category", ""),
            ",".join(event.get("companies", [])),
            ",".join(event.get("technologies", [])),
            event.get("heat_score", 0),
            event.get("sentiment", "neutral"),
            json.dumps(event.get("related_posts", []), ensure_ascii=False),
            ",".join(event.get("related_keywords", [])),
            event.get("impact_analysis", ""),
            event.get("event_confidence", 0),
            event.get("business_opportunity", "")
        ))
    
    conn.commit()
    conn.close()
    print(f"Saved {len(events)} events for {date_str}")


def get_events(date_str: str = None, limit: int = 10) -> List[Dict]:
    """获取事件列表"""
    conn = get_db_connection()
    cursor = conn.cursor(pymysql.cursors.DictCursor)
    
    if date_str:
        cursor.execute("""
            SELECT * FROM ai_events 
            WHERE event_date = %s 
            ORDER BY heat_score DESC 
            LIMIT %s
        """, (date_str, limit))
    else:
        cursor.execute("""
            SELECT * FROM ai_events 
            ORDER BY event_date DESC, heat_score DESC 
            LIMIT %s
        """, (limit,))
    
    events = list(cursor.fetchall())
    conn.close()
    
    # 处理JSON字段和日期时间转换
    for event in events:
        # 转换日期时间对象为字符串
        if event.get("event_date") and hasattr(event["event_date"], "isoformat"):
            event["event_date"] = event["event_date"].isoformat()
        if event.get("created_time") and hasattr(event["created_time"], "isoformat"):
            event["created_time"] = event["created_time"].isoformat()
        if event.get("updated_time") and hasattr(event["updated_time"], "isoformat"):
            event["updated_time"] = event["updated_time"].isoformat()
        
        if event.get("related_posts"):
            try:
                event["related_posts"] = json.loads(event["related_posts"])
            except:
                event["related_posts"] = []
        if event.get("companies"):
            event["companies"] = event["companies"].split(",") if event["companies"] else []
        if event.get("technologies"):
            event["technologies"] = event["technologies"].split(",") if event["technologies"] else []
        if event.get("related_keywords"):
            event["related_keywords"] = event["related_keywords"].split(",") if event["related_keywords"] else []
        
        # 计算综合排名分数：热度*0.6 + 可信度*0.4
        heat = event.get("heat_score", 0) or 0
        conf = event.get("event_confidence", 0) or 0
        event["event_rank_score"] = round(heat * 0.6 + conf * 0.4, 1)
    
    # 按综合排名分数排序
    events.sort(key=lambda x: x.get("event_rank_score", 0), reverse=True)
    return events


def get_latest_event_date():
    """返回有事件数据的最新日期(YYYY-MM-DD)，无数据返回None"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT MAX(event_date) FROM ai_events")
        row = cursor.fetchone()
        conn.close()
        if row and row[0]:
            d = row[0]
            return d.isoformat() if hasattr(d, "isoformat") else str(d)
    except Exception as e:
        print(f"获取最新事件日期失败: {e}")
    return None


def analyze_and_save(date_str: str = None, force: bool = False) -> List[Dict]:
    """分析并保存当天事件（带缓存）"""
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")
    
    cache_file = os.path.join(CACHE_DIR, f"events_{date_str}.json")
    
    # 检查缓存
    if not force and os.path.exists(cache_file):
        cache_age = time.time() - os.path.getmtime(cache_file)
        if cache_age < 86400:  # 24小时缓存
            with open(cache_file, "r") as f:
                return json.load(f)
    
    # 检查数据库是否已有数据
    existing = get_events(date_str, limit=10)
    if existing and not force:
        # 保存到缓存
        with open(cache_file, "w") as f:
            json.dump(existing, f, ensure_ascii=False, indent=2)
        return existing
    
    # 获取热门微博
    posts = get_hot_weibo(date_str, limit=30)
    print(f"Found {len(posts)} hot weibo posts for {date_str}")
    
    if not posts:
        return []
    
    # LLM分析
    events = analyze_events(posts, date_str)
    print(f"Analyzed {len(events)} events")
    
    if events:
        # 保存到数据库
        save_events(events, date_str)
        # 保存到缓存
        with open(cache_file, "w") as f:
            json.dump(events, f, ensure_ascii=False, indent=2)
    
    return events


if __name__ == "__main__":
    # 测试：分析今天的事件
    today = datetime.now().strftime("%Y-%m-%d")
    print(f"Analyzing events for {today}...")
    events = analyze_and_save(today, force=True)
    print(f"\nFound {len(events)} events:")
    for i, e in enumerate(events, 1):
        print(f"{i}. [{e.get('heat_score', 0)}分] {e.get('title', '')}")
        print(f"   分类: {e.get('category', '')} | 情感: {e.get('sentiment', '')}")
        print(f"   公司: {e.get('companies', [])}")
        print(f"   技术: {e.get('technologies', [])}")
        print()
