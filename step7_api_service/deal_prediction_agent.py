#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI成交概率预测Agent
分析客户成交可能性，输出概率、风险因素和建议动作
"""
import os
import sys
import json
import logging
from datetime import datetime, timedelta

sys.path.insert(0, "/opt/Weibo-Analyst/step7_api_service")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DealPredictionAgent:
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

    def get_customer_data(self, customer_id):
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM customers WHERE id = %s", (customer_id,))
        customer = cursor.fetchone()
        cursor.execute("SELECT COUNT(*) as cnt FROM follow_records WHERE customer_id = %s", (customer_id,))
        follow_count = cursor.fetchone()["cnt"]
        cursor.execute("SELECT * FROM customer_ai_scores WHERE customer_id = %s ORDER BY created_time DESC LIMIT 1", (customer_id,))
        ai_score = cursor.fetchone()
        cursor.close()
        conn.close()
        return customer, follow_count, ai_score

    def calculate_deal_probability(self, customer, follow_count, ai_score):
        score = 50  # 基础分
        positive = []
        risks = []

        # 客户等级
        level = customer.get("customer_level", "B")
        if level == "A":
            score += 15
            positive.append("A级高价值客户")
        elif level == "B":
            score += 5
            positive.append("B级客户")
        else:
            risks.append("C级客户，价值较低")

        # 销售阶段
        stage = customer.get("sales_stage", "new")
        stage_scores = {"new": 0, "contacted": 10, "requirement": 20, "solution": 30, "negotiation": 40, "closed": 50, "lost": -50}
        stage_names = {"new": "新客户", "contacted": "已接触", "requirement": "需求确认", "solution": "方案沟通", "negotiation": "商务谈判", "closed": "已成交", "lost": "已流失"}
        score += stage_scores.get(stage, 0)
        if stage in ["solution", "negotiation"]:
            positive.append(f"已进入{stage_names.get(stage)}阶段")
        elif stage == "new":
            risks.append("尚未建立联系")

        # 跟进频率
        if follow_count >= 3:
            score += 10
            positive.append(f"已跟进{follow_count}次，沟通充分")
        elif follow_count >= 1:
            score += 5
            positive.append(f"已跟进{follow_count}次")
        else:
            risks.append("尚无跟进记录")

        # 最近跟进时间
        last_follow = customer.get("last_follow_time")
        if last_follow:
            days_since = (datetime.now() - last_follow).days
            if days_since <= 3:
                score += 5
                positive.append("近期有跟进")
            elif days_since > 14:
                score -= 10
                risks.append(f"已{days_since}天未跟进")
        else:
            risks.append("从未跟进")

        # AI评分
        if ai_score and ai_score.get("score", 0) >= 70:
            score += 10
            positive.append("AI机会评分高")
        elif ai_score and ai_score.get("score", 0) < 50:
            score -= 5
            risks.append("AI机会评分较低")

        # 预计金额
        amount = customer.get("amount", 0) or 0
        if amount > 100000:
            positive.append(f"预计金额{amount/10000:.0f}万，大单")
        elif amount > 0:
            positive.append(f"有明确预算{amount/10000:.0f}万")
        else:
            risks.append("未确认预算")

        # 阶段停滞
        stage_changed = customer.get("stage_changed_time")
        if stage_changed:
            days_stagnant = (datetime.now() - stage_changed).days
            if days_stagnant > 14 and stage not in ["closed", "lost"]:
                score -= 15
                risks.append(f"阶段停滞{days_stagnant}天")

        score = max(0, min(100, score))

        if score >= 70:
            level = "high"
            action = "加快推进，确认采购流程和预算，争取尽快签约"
        elif score >= 40:
            level = "medium"
            action = "持续跟进，挖掘明确需求，安排方案演示"
        else:
            level = "low"
            action = "重新激活，发送行业案例，寻找新的切入点"

        return {
            "deal_probability": score,
            "prediction_level": level,
            "positive_factors": positive,
            "risk_factors": risks,
            "recommended_action": action
        }

    def predict_customer(self, customer_id):
        customer, follow_count, ai_score = self.get_customer_data(customer_id)
        if not customer:
            return None
        result = self.calculate_deal_probability(customer, follow_count, ai_score)
        result["customer_id"] = customer_id
        result["customer_name"] = customer.get("company_name", "")
        self._save_prediction(customer_id, result)
        return result

    def _save_prediction(self, customer_id, result):
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM customer_deal_predictions WHERE customer_id = %s ORDER BY created_time DESC LIMIT 1", (customer_id,))
        existing = cursor.fetchone()
        if existing:
            cursor.execute("""
                UPDATE customer_deal_predictions 
                SET deal_probability=%s, prediction_level=%s, positive_factors=%s, 
                    risk_factors=%s, recommended_action=%s, updated_time=NOW()
                WHERE id=%s
            """, (
                result["deal_probability"], result["prediction_level"],
                json.dumps(result["positive_factors"], ensure_ascii=False),
                json.dumps(result["risk_factors"], ensure_ascii=False),
                result["recommended_action"], existing["id"]
            ))
        else:
            cursor.execute("""
                INSERT INTO customer_deal_predictions 
                (customer_id, deal_probability, prediction_level, positive_factors, risk_factors, recommended_action)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (
                customer_id, result["deal_probability"], result["prediction_level"],
                json.dumps(result["positive_factors"], ensure_ascii=False),
                json.dumps(result["risk_factors"], ensure_ascii=False),
                result["recommended_action"]
            ))
        conn.commit()
        cursor.close()
        conn.close()

    def predict_all(self):
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM customers WHERE sales_stage NOT IN ('closed','lost')")
        customers = cursor.fetchall()
        cursor.close()
        conn.close()
        results = []
        for c in customers:
            r = self.predict_customer(c["id"])
            if r:
                results.append(r)
        return results

    @staticmethod
    def _parse_json_field(value):
        """安全解析数据库中的JSON字段，兼容list/str/bytes/None"""
        if value is None:
            return []
        if isinstance(value, (list, dict)):
            return value
        if isinstance(value, (bytes, bytearray)):
            value = value.decode("utf-8")
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return []
            try:
                return json.loads(value)
            except (ValueError, TypeError):
                return [value]
        return []

    def _row_to_result(self, row):
        """把数据库行转换为predict接口统一返回结构"""
        return {
            "customer_id": row["customer_id"],
            "customer_name": row.get("company_name", row.get("customer_name", "")) or "",
            "deal_probability": row["deal_probability"],
            "prediction_level": row["prediction_level"],
            "positive_factors": self._parse_json_field(row.get("positive_factors")),
            "risk_factors": self._parse_json_field(row.get("risk_factors")),
            "recommended_action": row.get("recommended_action", "") or "",
        }

    def get_latest_predictions(self):
        """读取所有客户最近一次已持久化的预测（单条SQL，毫秒级）。
        GET接口优先调用，避免每次请求都对全部客户实时重算（远程DB多次往返耗时数秒）。"""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT p.customer_id, c.company_name, p.deal_probability, p.prediction_level,
                   p.positive_factors, p.risk_factors, p.recommended_action, p.updated_time
            FROM customer_deal_predictions p
            JOIN customers c ON c.id = p.customer_id
            WHERE p.id IN (SELECT MAX(id) FROM customer_deal_predictions GROUP BY customer_id)
            ORDER BY p.deal_probability DESC
        """)
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return [self._row_to_result(r) for r in rows]

    def get_stored_prediction(self, customer_id):
        """读取单个客户最近一次已持久化的预测，无记录返回None"""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT p.customer_id, c.company_name, p.deal_probability, p.prediction_level,
                   p.positive_factors, p.risk_factors, p.recommended_action
            FROM customer_deal_predictions p
            JOIN customers c ON c.id = p.customer_id
            WHERE p.customer_id = %s
            ORDER BY p.id DESC LIMIT 1
        """, (customer_id,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        return self._row_to_result(row) if row else None


_instance = None
def get_deal_prediction_agent():
    global _instance
    if _instance is None:
        _instance = DealPredictionAgent()
    return _instance


if __name__ == "__main__":
    agent = get_deal_prediction_agent()
    results = agent.predict_all()
    for r in results:
        print(f"{r['customer_name']}: {r['deal_probability']}% ({r['prediction_level']})")
