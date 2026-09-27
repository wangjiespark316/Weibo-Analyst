#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
销售漏斗分析
分析销售整体状态，计算阶段转化率
"""
import os
import sys
import json
import logging
from datetime import datetime

sys.path.insert(0, "/opt/Weibo-Analyst/step7_api_service")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

STAGES = ["new", "contacted", "requirement", "solution", "negotiation", "closed"]
STAGE_NAMES = {
    "new": "线索", "contacted": "接触", "requirement": "需求",
    "solution": "方案", "negotiation": "商务", "closed": "成交"
}


class SalesFunnelAnalyzer:
    def __init__(self):
        self.db_config = self._load_db_config()

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

    def analyze_funnel(self):
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT sales_stage, COUNT(*) as cnt, COALESCE(SUM(amount),0) as total_amount
            FROM customers 
            WHERE sales_stage != 'lost'
            GROUP BY sales_stage
        """)
        raw_data = cursor.fetchall()
        cursor.close()
        conn.close()

        stage_map = {r["sales_stage"]: r for r in raw_data}
        funnel = []
        prev_count = None

        for stage in STAGES:
            data = stage_map.get(stage, {"cnt": 0, "total_amount": 0})
            count = data["cnt"]
            amount = float(data["total_amount"])
            conversion = 0
            if prev_count and prev_count > 0:
                conversion = round(count / prev_count * 100, 1)

            funnel.append({
                "stage": stage,
                "stage_name": STAGE_NAMES.get(stage, stage),
                "customer_count": count,
                "total_amount": amount,
                "conversion_rate": conversion
            })
            prev_count = count

        return funnel

    def save_snapshot(self):
        funnel = self.analyze_funnel()
        today = datetime.now().strftime("%Y-%m-%d")
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sales_funnel_snapshots WHERE snapshot_date = %s", (today,))
        for item in funnel:
            cursor.execute("""
                INSERT INTO sales_funnel_snapshots 
                (snapshot_date, stage, customer_count, total_amount, conversion_rate)
                VALUES (%s, %s, %s, %s, %s)
            """, (today, item["stage"], item["customer_count"], item["total_amount"], item["conversion_rate"]))
        conn.commit()
        cursor.close()
        conn.close()
        return funnel


_instance = None
def get_sales_funnel_analyzer():
    global _instance
    if _instance is None:
        _instance = SalesFunnelAnalyzer()
    return _instance


if __name__ == "__main__":
    analyzer = get_sales_funnel_analyzer()
    funnel = analyzer.analyze_funnel()
    for f in funnel:
        print(f"{f['stage_name']}: {f['customer_count']}家, {f['total_amount']/10000:.1f}万, 转化率{f['conversion_rate']}%")
