#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI销售复盘Agent
自动生成日报、周报、月报
"""
import os
import sys
import json
import logging
from datetime import datetime, timedelta

sys.path.insert(0, "/opt/Weibo-Analyst/step7_api_service")
from sales_funnel_analyzer import get_sales_funnel_analyzer
from deal_prediction_agent import get_deal_prediction_agent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SalesReviewAgent:
    def __init__(self):
        self.db_config = self._load_db_config()
        self.funnel_analyzer = get_sales_funnel_analyzer()
        self.prediction_agent = get_deal_prediction_agent()

    def _load_db_config(self):
        from urllib.parse import urlparse
        from dotenv import load_dotenv
        load_dotenv("/opt/Weibo-Analyst/.env")
        url = urlparse(os.getenv("DATABASE_URL"))
        return {
            "host": url.hostname, "port": url.port or 4000,
            "user": url.username, "password": url.password,
            "database": url.path.lstrip("/")
        }

    def _get_conn(self):
        import pymysql
        return pymysql.connect(
            host=self.db_config["host"], port=self.db_config["port"],
            user=self.db_config["user"], password=self.db_config["password"],
            database=self.db_config["database"], ssl={"ssl_disabled": False},
            cursorclass=pymysql.cursors.DictCursor
        )

    def generate_daily_review(self):
        today = datetime.now().strftime("%Y-%m-%d")
        conn = self._get_conn()
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) as cnt FROM customers WHERE DATE(created_time) = %s", (today,))
        new_customers = cursor.fetchone()["cnt"]

        cursor.execute("SELECT COUNT(*) as cnt FROM follow_records WHERE DATE(follow_time) = %s", (today,))
        follow_count = cursor.fetchone()["cnt"]

        cursor.execute("SELECT COUNT(*) as cnt FROM customers WHERE sales_stage NOT IN ('closed','lost') AND (stage_changed_time IS NULL OR stage_changed_time < DATE_SUB(NOW(), INTERVAL 14 DAY))")
        stagnant_count = cursor.fetchone()["cnt"]

        cursor.close()
        conn.close()

        predictions = self.prediction_agent.predict_all()
        high_prob = [p for p in predictions if p["prediction_level"] == "high"]

        content = f"# AI销售日报 {today}\n\n"
        content += "## 一、今日概况\n"
        content += f"- 新增客户: {new_customers}家\n"
        content += f"- 跟进记录: {follow_count}条\n"
        content += f"- 高概率客户: {len(high_prob)}家\n"
        content += f"- 停滞客户: {stagnant_count}家\n\n"

        content += "## 二、重点客户\n"
        for p in high_prob[:3]:
            content += f"- **{p['customer_name']}**: 成交概率{p['deal_probability']}%，建议: {p['recommended_action']}\n"

        content += "\n## 三、风险提醒\n"
        if stagnant_count > 0:
            content += f"- 有{stagnant_count}家客户超过14天未推进，建议主动联系\n"
        else:
            content += "- 暂无停滞客户\n"

        content += "\n## 四、明日建议\n"
        content += "1. 优先跟进高概率客户，推动成交\n"
        content += "2. 联系停滞客户，了解项目进展\n"
        content += "3. 持续培育中等意向客户\n"

        self._save_review("daily", today, content)
        return content

    def _save_review(self, review_type, review_date, content):
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sales_reviews WHERE review_type = %s AND review_date = %s", (review_type, review_date))
        cursor.execute("INSERT INTO sales_reviews (review_type, review_date, content) VALUES (%s, %s, %s)", (review_type, review_date, content))
        conn.commit()
        cursor.close()
        conn.close()


_instance = None
def get_sales_review_agent():
    global _instance
    if _instance is None:
        _instance = SalesReviewAgent()
    return _instance


if __name__ == "__main__":
    agent = get_sales_review_agent()
    content = agent.generate_daily_review()
    print(content[:500])
