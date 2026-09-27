#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
流水线健康检查模块
检查每天流水线是否成功运行，数据是否正常
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


def check_pipeline_health(date_str=None):
    """检查流水线健康状态"""
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    health = {
        "date": date_str,
        "check_time": datetime.now().isoformat(),
        "overall_status": "healthy",
        "checks": {}
    }
    
    # 1. 检查流水线锁状态
    cursor.execute("""
        SELECT status, started_time, finished_time 
        FROM pipeline_lock 
        WHERE task_name = 'ai_intelligence_pipeline' AND lock_date = %s
        ORDER BY started_time DESC LIMIT 1
    """, (date_str,))
    lock = cursor.fetchone()
    
    if lock:
        status, started, finished = lock
        health["checks"]["pipeline"] = {
            "status": "success" if status == "success" else "warning" if status == "partial_failed" else "failed",
            "lock_status": status,
            "started_time": started.isoformat() if started else None,
            "finished_time": finished.isoformat() if finished else None
        }
        if status != "success":
            health["overall_status"] = "warning"
    else:
        health["checks"]["pipeline"] = {"status": "not_run", "message": "今日未运行"}
        health["overall_status"] = "warning"
    
    # 2. 检查事件数量
    cursor.execute("SELECT COUNT(*) FROM ai_events WHERE event_date = %s", (date_str,))
    event_count = cursor.fetchone()[0]
    health["checks"]["events"] = {
        "status": "success" if event_count > 0 else "warning",
        "count": event_count,
        "expected": ">=1"
    }
    
    # 3. 检查产品数据
    cursor.execute("SELECT COUNT(*) FROM ai_product_metrics WHERE date = %s", (date_str,))
    product_count = cursor.fetchone()[0]
    health["checks"]["products"] = {
        "status": "success" if product_count > 0 else "warning",
        "count": product_count,
        "expected": ">=1"
    }
    
    # 4. 检查趋势数据
    cursor.execute("SELECT COUNT(*) FROM ai_trends WHERE date = %s", (date_str,))
    trend_count = cursor.fetchone()[0]
    health["checks"]["trends"] = {
        "status": "success" if trend_count > 0 else "warning",
        "count": trend_count,
        "expected": ">=1"
    }
    
    # 5. 检查日报
    cursor.execute("SELECT id, title, quality_score FROM ai_daily_reports WHERE report_date = %s", (date_str,))
    report = cursor.fetchone()
    if report:
        report_id, title, quality_score = report
        health["checks"]["report"] = {
            "status": "success",
            "generated": True,
            "title": title,
            "quality_score": quality_score or 0
        }
    else:
        health["checks"]["report"] = {"status": "failed", "generated": False}
        health["overall_status"] = "failed"
    
    # 6. 检查微博数据
    cursor.execute("SELECT COUNT(*) FROM weibo_posts WHERE DATE(publish_time) = %s", (date_str,))
    weibo_count = cursor.fetchone()[0]
    health["checks"]["weibo_data"] = {
        "status": "success" if weibo_count > 0 else "warning",
        "count": weibo_count
    }
    
    conn.close()
    
    # 汇总
    failed_checks = [k for k, v in health["checks"].items() if v["status"] == "failed"]
    warning_checks = [k for k, v in health["checks"].items() if v["status"] == "warning"]
    
    if failed_checks:
        health["overall_status"] = "failed"
    elif warning_checks:
        health["overall_status"] = "warning"
    
    health["summary"] = {
        "failed_checks": failed_checks,
        "warning_checks": warning_checks,
        "healthy_checks": [k for k, v in health["checks"].items() if v["status"] == "success"]
    }
    
    return health


def print_health_report(health):
    """打印健康检查报告"""
    print("=" * 60)
    print(f"AI情报系统健康检查 - {health['date']}")
    print(f"检查时间: {health['check_time']}")
    print(f"整体状态: {health['overall_status'].upper()}")
    print("=" * 60)
    
    status_icons = {"success": "✅", "warning": "⚠️", "failed": "❌", "not_run": "⏳"}
    
    for check_name, check_data in health["checks"].items():
        icon = status_icons.get(check_data["status"], "❓")
        print(f"\n{icon} {check_name}:")
        for k, v in check_data.items():
            if k != "status":
                print(f"   {k}: {v}")
    
    print("\n" + "=" * 60)
    print(f"健康检查: {len(health['summary']['healthy_checks'])} 项通过")
    print(f"警告: {len(health['summary']['warning_checks'])} 项")
    print(f"失败: {len(health['summary']['failed_checks'])} 项")
    print("=" * 60)


if __name__ == "__main__":
    import sys
    date_str = sys.argv[1] if len(sys.argv) > 1 else None
    health = check_pipeline_health(date_str)
    print_health_report(health)
