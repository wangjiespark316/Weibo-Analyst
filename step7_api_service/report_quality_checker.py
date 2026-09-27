#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日报质量检查模块
检查日报内容质量、数据真实性、完整性
"""
import os
import sys
import json
from datetime import datetime
from urllib.parse import urlparse

sys.path.insert(0, "/opt/Weibo-Analyst")


def get_db_connection():
    from dotenv import load_dotenv
    load_dotenv("/opt/Weibo-Analyst/.env")
    import pymysql
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


def check_report_quality(date_str):
    """检查日报质量"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 获取日报
    cursor.execute("""
        SELECT id, title, content, top_events, top_products, top_trends 
        FROM ai_daily_reports WHERE report_date = %s
    """, (date_str,))
    report = cursor.fetchone()
    
    if not report:
        conn.close()
        return {"score": 0, "status": "not_found", "issues": ["日报不存在"], "suggestion": "请先生成日报"}
    
    report_id, title, content, top_events, top_products, top_trends = report
    
    result = {
        "date": date_str,
        "report_id": report_id,
        "title": title,
        "score": 100,
        "issues": [],
        "checks": {},
        "suggestion": ""
    }
    
    # 1. 内容检查
    content_check = {"passed": True, "details": {}}
    
    if not content or len(content) < 100:
        content_check["passed"] = False
        content_check["details"]["length"] = f"内容过短 ({len(content) if content else 0}字符)"
        result["score"] -= 20
        result["issues"].append("日报内容过短")
    else:
        content_check["details"]["length"] = f"{len(content)}字符"
    
    # 检查是否包含主要章节
    required_sections = ["今日AI三大事件", "AI产品变化", "AI技术趋势", "企业应用建议", "今日总结"]
    missing_sections = [s for s in required_sections if s not in content]
    if missing_sections:
        content_check["passed"] = False
        content_check["details"]["missing_sections"] = missing_sections
        result["score"] -= len(missing_sections) * 5
        result["issues"].append(f"缺少章节: {', '.join(missing_sections)}")
    else:
        content_check["details"]["sections"] = "全部包含"
    
    result["checks"]["content"] = content_check
    
    # 2. 数据检查
    data_check = {"passed": True, "details": {}}
    
    # 检查事件是否存在
    if top_events:
        try:
            events = json.loads(top_events)
            data_check["details"]["events_count"] = len(events)
            # 验证事件标题是否在内容中
            for event in events[:3]:
                if event.get("title") and event["title"][:10] not in content:
                    data_check["passed"] = False
                    result["score"] -= 3
                    result["issues"].append(f"事件未在内容中引用: {event['title'][:20]}")
        except:
            pass
    
    # 检查产品数据
    if top_products:
        try:
            products = json.loads(top_products)
            data_check["details"]["products_count"] = len(products)
        except:
            pass
    
    result["checks"]["data"] = data_check
    
    # 3. 真实性检查（简单检查是否有明显编造）
    authenticity_check = {"passed": True, "details": {}}
    
    # 检查是否有"暂无数据"过多
    no_data_count = content.count("暂无") + content.count("无显著")
    if no_data_count > 5:
        authenticity_check["passed"] = False
        authenticity_check["details"]["no_data_count"] = no_data_count
        result["score"] -= 10
        result["issues"].append("过多'暂无数据'，内容不够充实")
    
    result["checks"]["authenticity"] = authenticity_check
    
    # 4. 价值检查
    value_check = {"passed": True, "details": {}}
    
    # 检查是否有企业应用建议
    if "企业应用建议" in content or "企业机会" in content:
        value_check["details"]["has_business_advice"] = True
    else:
        value_check["passed"] = False
        value_check["details"]["has_business_advice"] = False
        result["score"] -= 10
        result["issues"].append("缺少企业应用建议")
    
    result["checks"]["value"] = value_check
    
    # 确保分数在0-100之间
    result["score"] = max(0, min(100, result["score"]))
    
    # 生成建议
    if result["score"] >= 90:
        result["suggestion"] = "日报质量优秀，内容完整，数据准确"
    elif result["score"] >= 70:
        result["suggestion"] = "日报质量良好，建议补充缺失章节和企业建议"
    elif result["score"] >= 50:
        result["suggestion"] = "日报质量一般，需要大幅补充内容"
    else:
        result["suggestion"] = "日报质量较差，建议重新生成"
    
    result["status"] = "excellent" if result["score"] >= 90 else "good" if result["score"] >= 70 else "fair" if result["score"] >= 50 else "poor"
    
    # 保存质量评分到数据库
    cursor.execute("""
        UPDATE ai_daily_reports 
        SET quality_score = %s, quality_check_result = %s
        WHERE id = %s
    """, (result["score"], json.dumps(result, ensure_ascii=False), report_id))
    conn.commit()
    conn.close()
    
    return result


if __name__ == "__main__":
    import sys
    date_str = sys.argv[1] if len(sys.argv) > 1 else datetime.now().strftime("%Y-%m-%d")
    result = check_report_quality(date_str)
    print(f"日报质量检查 - {date_str}")
    print(f"评分: {result['score']}/100 ({result['status']})")
    print(f"问题: {result['issues']}")
    print(f"建议: {result['suggestion']}")
