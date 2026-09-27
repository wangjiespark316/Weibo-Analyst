#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI行业日报生成模块
整合事件、产品、趋势数据，使用LLM生成AI行业日报
"""
import os
import sys
import json
import time
import pymysql
import pymysql.cursors
from datetime import datetime
from urllib.parse import urlparse

sys.path.insert(0, "/opt/Weibo-Analyst")
from step7_api_service.event_analyzer import get_events
from step7_api_service.product_analyzer import get_product_metrics
from step7_api_service.trend_analyzer import get_trends

# 缓存目录
CACHE_DIR = "/opt/Weibo-Analyst/step7_api_service/.report_cache"
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


def call_llm(messages, max_tokens=2000):
    """调用LLM"""
    import requests
    from dotenv import load_dotenv
    load_dotenv("/opt/Weibo-Analyst/.env")
    
    api_key = os.getenv("LLM_API_KEY")
    api_base = os.getenv("LLM_API_BASE", "https://api.deepseek.com/v1")
    model = os.getenv("LLM_MODEL", "deepseek-chat")
    
    try:
        response = requests.post(
            f"{api_base}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json={
                "model": model,
                "messages": messages,
                "temperature": 0.3,
                "max_tokens": max_tokens
            },
            timeout=60
        )
        result = response.json()
        return result["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"LLM调用失败: {e}")
        return None


def collect_daily_data(date_str):
    """收集当日数据：事件、产品、趋势"""
    print(f"收集 {date_str} 的数据...")
    
    # 1. 获取事件（取前5个）
    try:
        events = get_events(date_str, limit=5)
        print(f"  获取到 {len(events)} 个事件")
    except Exception as e:
        print(f"  获取事件失败: {e}")
        events = []
    
    # 2. 获取产品（取前5个）
    try:
        products = get_product_metrics(date_str, limit=5)
        print(f"  获取到 {len(products)} 个产品")
    except Exception as e:
        print(f"  获取产品失败: {e}")
        products = []
    
    # 3. 获取趋势（取前5个，排除quiet）
    try:
        trends = get_trends(date_str, limit=10)
        trends = [t for t in trends if t.get("trend_level") != "quiet"][:5]
        print(f"  获取到 {len(trends)} 个技术趋势")
    except Exception as e:
        print(f"  获取趋势失败: {e}")
        trends = []
    
    return {
        "date": date_str,
        "events": events,
        "products": products,
        "trends": trends
    }


def generate_report_with_llm(data):
    """使用LLM生成日报内容"""
    date_str = data["date"]
    events = data["events"]
    products = data["products"]
    trends = data["trends"]
    
    # 构建事件摘要
    events_text = ""
    for i, event in enumerate(events[:3], 1):
        events_text += f"""
### {i}. {event.get('title', '未知事件')}
- 摘要：{event.get('summary', '')[:200]}
- 分类：{event.get('category', '')}
- 热度：{event.get('heat_score', 0)} | 可信度：{event.get('event_confidence', 0)}%
- 涉及公司：{', '.join(event.get('companies', [])[:3])}
- 涉及技术：{', '.join(event.get('technologies', [])[:3])}
- 行业影响：{event.get('impact_analysis', '')[:150]}
- 企业机会：{event.get('business_opportunity', '')[:150]}
"""
    
    # 构建产品摘要
    products_text = ""
    for product in products[:3]:
        trend = product.get("trend_rate", 0)
        trend_icon = "↑" if trend > 0 else "↓" if trend < 0 else "→"
        products_text += f"""
- **{product.get('name', '')}**（{product.get('company', '')}）
  热度：{product.get('heat_score', 0)} | 提及：{product.get('mention_count', 0)}次 | 趋势：{trend_icon}{abs(trend)}%
  原因：{product.get('trend_reason', '产品讨论热度变化')[:100]}
"""
    
    # 构建趋势摘要
    trends_text = ""
    for trend in trends[:3]:
        level = trend.get("trend_level", "stable")
        level_icon = {"rising": "🔥", "stable": "➡️", "declining": "📉", "emerging": "🌱"}.get(level, "➡️")
        trends_text += f"""
- {level_icon} **{trend.get('name', '')}**（{trend.get('category', '')}）
  增长率：{trend.get('growth_rate', 0):+.1f}% | 热度：{trend.get('heat_score', 0)}
  摘要：{trend.get('summary', '')[:100]}
  企业机会：{trend.get('business_opportunity', '')[:100]}
"""
    
    system_prompt = """你是一位资深的AI行业分析师，擅长从海量信息中提炼关键洞察。
你的任务是基于提供的事件、产品和技术趋势数据，生成一份专业的AI行业日报。

要求：
1. 语言专业、简洁，避免空话套话
2. 重点突出对企业有价值的信息
3. 不要编造数据，只使用提供的信息
4. 日报结构清晰，便于快速阅读
5. 企业应用建议要具体，有可操作性
"""
    
    user_prompt = f"""请基于以下数据，生成一份{date_str}的AI行业日报。

## 今日AI事件（前3个）
{events_text if events_text else '今日无重大事件'}

## AI产品变化（前3个）
{products_text if products_text else '今日无显著产品变化'}

## AI技术趋势（前3个）
{trends_text if trends_text else '今日无显著技术趋势变化'}

请生成以下结构的日报（Markdown格式）：

# AI行业日报 - {date_str}

## 一、今日AI三大事件
（每个事件包含：标题、摘要、行业影响、企业机会）

## 二、AI产品变化
（上涨最快的产品、下降的产品、变化原因）

## 三、AI技术趋势
（正在升温的技术、增长原因、企业应用方向）

## 四、企业应用建议
（分行业给出具体建议：制造业、办公、销售、研发等）

## 五、今日总结
（100字以内总结今天AI行业的核心变化）

注意：如果某个部分没有数据，请写"今日无显著变化"，不要编造。"""
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]
    
    print("调用LLM生成日报...")
    content = call_llm(messages, max_tokens=2500)
    
    if not content:
        print("LLM生成失败，使用模板生成")
        content = generate_template_report(data)
    
    return content


def generate_template_report(data):
    """模板生成日报（LLM失败时的兜底）"""
    date_str = data["date"]
    events = data["events"]
    products = data["products"]
    trends = data["trends"]
    
    content = f"# AI行业日报 - {date_str}\n\n"
    
    # 事件
    content += "## 一、今日AI三大事件\n\n"
    if events:
        for i, event in enumerate(events[:3], 1):
            content += f"### {i}. {event.get('title', '未知事件')}\n"
            content += f"- **摘要**：{event.get('summary', '')}\n"
            content += f"- **行业影响**：{event.get('impact_analysis', '')}\n"
            content += f"- **企业机会**：{event.get('business_opportunity', '')}\n\n"
    else:
        content += "今日无重大事件。\n\n"
    
    # 产品
    content += "## 二、AI产品变化\n\n"
    if products:
        for product in products[:3]:
            trend = product.get("trend_rate", 0)
            content += f"- **{product.get('name', '')}**：热度{product.get('heat_score', 0)}，趋势{trend:+.1f}%，{product.get('trend_reason', '')}\n"
    else:
        content += "今日无显著产品变化。\n\n"
    
    # 趋势
    content += "## 三、AI技术趋势\n\n"
    if trends:
        for trend in trends[:3]:
            content += f"- **{trend.get('name', '')}**：增长{trend.get('growth_rate', 0):+.1f}%，{trend.get('summary', '')}\n"
            content += f"  企业机会：{trend.get('business_opportunity', '')}\n"
    else:
        content += "今日无显著技术趋势变化。\n\n"
    
    # 企业建议
    content += "## 四、企业应用建议\n\n"
    content += "- **制造业**：关注AI质检、设备预测性维护、生产流程优化\n"
    content += "- **办公**：部署AI办公助手，提升文档处理和会议效率\n"
    content += "- **销售**：使用AI客户分析和销售助手，提升转化效率\n"
    content += "- **研发**：引入AI编程助手，提升开发效率\n\n"
    
    # 总结
    content += "## 五、今日总结\n\n"
    content += f"今日AI行业整体保持活跃，{len(events)}个重要事件、{len(products)}个产品变化、{len(trends)}个技术趋势值得关注。建议企业持续关注AI技术发展，积极探索落地场景。\n"
    
    return content


def save_report(date_str, content, data):
    """保存日报到数据库"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 提取top数据
        top_events = json.dumps([
            {"title": e.get("title", ""), "heat_score": e.get("heat_score", 0)}
            for e in data["events"][:3]
        ], ensure_ascii=False)
        
        top_products = json.dumps([
            {"name": p.get("name", ""), "heat_score": p.get("heat_score", 0), "trend_rate": p.get("trend_rate", 0)}
            for p in data["products"][:3]
        ], ensure_ascii=False)
        
        top_trends = json.dumps([
            {"name": t.get("name", ""), "growth_rate": t.get("growth_rate", 0), "trend_level": t.get("trend_level", "")}
            for t in data["trends"][:3]
        ], ensure_ascii=False)
        
        # 提取总结
        summary = ""
        if "## 五、今日总结" in content:
            parts = content.split("## 五、今日总结")
            if len(parts) > 1:
                summary = parts[1].strip()[:500]
        
        title = f"AI行业日报 - {date_str}"
        
        # 插入或更新
        cursor.execute("""
            INSERT INTO ai_daily_reports 
            (report_date, title, content, top_events, top_products, top_trends, summary)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE 
            content = VALUES(content),
            top_events = VALUES(top_events),
            top_products = VALUES(top_products),
            top_trends = VALUES(top_trends),
            summary = VALUES(summary),
            updated_time = NOW()
        """, (date_str, title, content, top_events, top_products, top_trends, summary))
        
        conn.commit()
        conn.close()
        print(f"日报已保存到数据库: {title}")
        return True
    except Exception as e:
        print(f"保存日报失败: {e}")
        return False


def generate_and_save_report(date_str, force=False):
    """生成并保存日报"""
    cache_file = os.path.join(CACHE_DIR, f"report_{date_str}.md")
    
    if not force and os.path.exists(cache_file):
        with open(cache_file, "r", encoding="utf-8") as f:
            content = f.read()
        print(f"使用缓存日报: {date_str}")
        return content
    
    # 1. 收集数据
    data = collect_daily_data(date_str)
    
    # 2. 生成日报
    content = generate_report_with_llm(data)
    
    # 3. 保存到数据库
    save_report(date_str, content, data)
    
    # 4. 保存缓存
    with open(cache_file, "w", encoding="utf-8") as f:
        f.write(content)
    
    return content


def get_report(date_str):
    """获取指定日期的日报"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        
        cursor.execute("""
            SELECT id, report_date, title, content, top_events, top_products, top_trends, summary, created_time
            FROM ai_daily_reports 
            WHERE report_date = %s
        """, (date_str,))
        
        report = cursor.fetchone()
        conn.close()
        
        if report:
            # 转换日期格式
            if hasattr(report["report_date"], "isoformat"):
                report["report_date"] = report["report_date"].isoformat()
            if hasattr(report["created_time"], "isoformat"):
                report["created_time"] = report["created_time"].isoformat()
            # 解析JSON
            for key in ["top_events", "top_products", "top_trends"]:
                if report.get(key):
                    try:
                        report[key] = json.loads(report[key])
                    except:
                        pass
        return report
    except Exception as e:
        print(f"获取日报失败: {e}")
        return None


def get_recent_reports(limit=10):
    """获取最近的日报列表"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        
        cursor.execute("""
            SELECT id, report_date, title, summary, created_time
            FROM ai_daily_reports 
            ORDER BY report_date DESC
            LIMIT %s
        """, (limit,))
        
        reports = cursor.fetchall()
        conn.close()
        
        for report in reports:
            if hasattr(report["report_date"], "isoformat"):
                report["report_date"] = report["report_date"].isoformat()
            if hasattr(report["created_time"], "isoformat"):
                report["created_time"] = report["created_time"].isoformat()
        
        return reports
    except Exception as e:
        print(f"获取日报列表失败: {e}")
        return []


if __name__ == "__main__":
    import sys
    date_str = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%Y-%m-%d")
    print(f"生成 {date_str} 的AI行业日报...")
    content = generate_and_save_report(date_str, force=True)
    print("\n" + "=" * 60)
    print(content[:1000])
    print("..." if len(content) > 1000 else "")
