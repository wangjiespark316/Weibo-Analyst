#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每日销售晨报推送模块
每天08:30自动生成《今日销售AI助手》并推送到飞书
"""
import os
import sys
import json
import logging
from datetime import datetime, timedelta

sys.path.insert(0, "/opt/Weibo-Analyst/step7_api_service")

from feishu_notification import get_feishu_notification
from sales_analysis_agent import get_sales_analysis_agent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DailySalesPush:
    def __init__(self):
        self.notifier = get_feishu_notification()
        self.agent = get_sales_analysis_agent()

    def get_sales_overview(self):
        """获取今日销售概况"""
        try:
            import pymysql
            from urllib.parse import urlparse
            from dotenv import load_dotenv
            load_dotenv("/opt/Weibo-Analyst/.env")

            url = urlparse(os.getenv("DATABASE_URL"))
            conn = pymysql.connect(
                host=url.hostname, port=url.port or 4000,
                user=url.username, password=url.password,
                database=url.path.lstrip("/"), ssl={"ssl_disabled": False},
                cursorclass=pymysql.cursors.DictCursor
            )
            cursor = conn.cursor()

            # 客户总数
            cursor.execute("SELECT COUNT(*) as total FROM customers")
            total = cursor.fetchone()["total"]

            # 本月新增
            cursor.execute("SELECT COUNT(*) as new_count FROM customers WHERE created_time >= DATE_FORMAT(NOW(), '%Y-%m-01')")
            new_count = cursor.fetchone()["new_count"]

            # 今日跟进
            cursor.execute("SELECT COUNT(DISTINCT customer_id) as follow_count FROM follow_records WHERE DATE(follow_time) = CURDATE()")
            today_follow = cursor.fetchone()["follow_count"]

            # 风险客户
            cursor.execute("SELECT COUNT(*) as risk_count FROM customers WHERE sales_stage NOT IN ('closed','lost') AND (stage_changed_time IS NULL OR stage_changed_time < DATE_SUB(NOW(), INTERVAL 14 DAY))")
            risk_count = cursor.fetchone()["risk_count"]

            # 商机金额
            cursor.execute("SELECT COALESCE(SUM(amount),0) as amount FROM customers WHERE sales_stage IN ('requirement','solution','negotiation')")
            pipeline_amount = cursor.fetchone()["amount"]

            cursor.close()
            conn.close()

            return {
                "total_customers": total,
                "new_customers": new_count,
                "today_follow": today_follow,
                "risk_customers": risk_count,
                "pipeline_amount": float(pipeline_amount),
            }
        except Exception as e:
            logger.error(f"获取销售概况失败: {e}")
            return {}

    def get_top_customers(self, limit=3):
        """获取重点客户"""
        try:
            return self.agent.analyze_high_value_customers(limit=limit)
        except Exception as e:
            logger.error(f"获取重点客户失败: {e}")
            return []

    def get_risk_alerts(self, limit=3):
        """获取风险提醒"""
        try:
            risks = self.agent.analyze_risk_customers()
            return risks[:limit]
        except Exception as e:
            logger.error(f"获取风险提醒失败: {e}")
            return []

    def get_today_tasks(self):
        """获取今日任务"""
        try:
            import pymysql
            from urllib.parse import urlparse
            from dotenv import load_dotenv
            load_dotenv("/opt/Weibo-Analyst/.env")

            url = urlparse(os.getenv("DATABASE_URL"))
            conn = pymysql.connect(
                host=url.hostname, port=url.port or 4000,
                user=url.username, password=url.password,
                database=url.path.lstrip("/"), ssl={"ssl_disabled": False},
                cursorclass=pymysql.cursors.DictCursor
            )
            cursor = conn.cursor()

            cursor.execute("SELECT * FROM sales_reminders WHERE status='pending' ORDER BY priority, created_time LIMIT 5")
            tasks = cursor.fetchall()
            cursor.close()
            conn.close()
            return tasks
        except Exception as e:
            logger.error(f"获取今日任务失败: {e}")
            return []

    def generate_daily_report(self):
        """生成每日销售晨报内容"""
        today = datetime.now().strftime("%Y-%m-%d")
        weekday = ["周一","周二","周三","周四","周五","周六","周日"][datetime.now().weekday()]

        overview = self.get_sales_overview()
        top_customers = self.get_top_customers(3)
        risk_alerts = self.get_risk_alerts(3)
        tasks = self.get_today_tasks()
        suggestions = self.agent.generate_today_suggestions()

        # 构建Markdown内容
        content = f"## 今日销售AI助手\n"
        content += f"**日期**: {today} {weekday}\n\n"

        # 销售概况
        content += "### 销售概况\n"
        content += f"- 客户总数: **{overview.get('total_customers', 0)}**\n"
        content += f"- 本月新增: **{overview.get('new_customers', 0)}**\n"
        content += f"- 今日跟进: **{overview.get('today_follow', 0)}**\n"
        content += f"- 风险客户: **{overview.get('risk_customers', 0)}**\n"
        amount = overview.get('pipeline_amount', 0)
        content += f"- 商机金额: **{amount/10000:.1f}万**\n\n"

        # 重点客户
        if top_customers:
            content += "### 重点客户\n"
            for i, c in enumerate(top_customers[:3], 1):
                content += f"**TOP{i}: {c['name']}**\n"
                content += f"- 行业: {c.get('industry','-')}\n"
                content += f"- 阶段: {c.get('stage','-')}\n"
                content += f"- 金额: {c.get('amount',0)/10000:.1f}万\n"
                if c.get('next_action'):
                    content += f"- 建议: {c['next_action']}\n"
                content += "\n"

        # 风险提醒
        if risk_alerts:
            content += "### 风险提醒\n"
            for r in risk_alerts[:3]:
                content += f"⚠️ **{r['name']}**\n"
                content += f"- {r.get('risk_reason','')}\n"
                content += f"- 建议: {r.get('suggestion','')}\n\n"

        # 今日任务
        if tasks:
            content += "### 今日任务\n"
            for t in tasks[:5]:
                content += f"- [ ] {t.get('customer_name','')}: {t.get('content','')[:50]}\n"
            content += "\n"

        # AI建议
        if suggestions:
            content += "### AI建议\n"
            for s in suggestions[:3]:
                content += f"- {s}\n"

        return content

    def push_daily_report(self):
        """推送每日销售晨报"""
        try:
            if not self.notifier.enabled:
                return {"status": "skipped", "reason": "飞书未配置"}

            content = self.generate_daily_report()
            today = datetime.now().strftime("%Y-%m-%d")

            result = self.notifier.send_markdown(
                title=f"今日销售AI助手 {today}",
                markdown_content=content
            )

            if result.get("status") == "success":
                logger.info("销售晨报推送成功")
                return {
                    "status": "success",
                    "message_id": result.get("message_id"),
                    "date": today
                }
            else:
                logger.error(f"销售晨报推送失败: {result}")
                return {"status": "failed", "error": result.get("error", "未知错误")}

        except Exception as e:
            logger.error(f"推送销售晨报异常: {e}")
            return {"status": "failed", "error": str(e)}


_instance = None
def get_daily_sales_push():
    global _instance
    if _instance is None:
        _instance = DailySalesPush()
    return _instance


if __name__ == "__main__":
    pusher = get_daily_sales_push()
    result = pusher.push_daily_report()
    print(json.dumps(result, ensure_ascii=False, indent=2))
