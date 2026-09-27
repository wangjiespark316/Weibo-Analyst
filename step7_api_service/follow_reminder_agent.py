#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
客户跟进提醒Agent
每天检查客户跟进状态，生成提醒并推送到飞书
规则：
- 7天未跟进 → 提醒
- 高价值客户未跟进 → 提醒
- 销售阶段停滞 → 提醒
"""
import os
import sys
import json
import logging
import pymysql
from datetime import datetime, timedelta

sys.path.insert(0, "/opt/Weibo-Analyst/step7_api_service")

from feishu_notification import get_feishu_notification

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class FollowReminderAgent:
    """客户跟进提醒Agent"""
    
    def __init__(self):
        self.notifier = get_feishu_notification()
        self.stage_map = {
            "new": "新客户", "contacted": "已接触", "requirement": "需求确认",
            "solution": "方案沟通", "negotiation": "商务谈判", "closed": "已成交", "lost": "已流失"
        }
    
    def get_db_connection(self):
        """获取数据库连接"""
        from urllib.parse import urlparse
        from dotenv import load_dotenv
        load_dotenv("/opt/Weibo-Analyst/.env")
        
        url = urlparse(os.getenv("DATABASE_URL"))
        return pymysql.connect(
            host=url.hostname,
            port=url.port or 4000,
            user=url.username,
            password=url.password,
            database=url.path.lstrip("/"),
            ssl={"ssl_disabled": False}
        )
    
    def check_no_follow_7d(self):
        """检查7天未跟进的客户"""
        try:
            conn = self.get_db_connection()
            cursor = conn.cursor(pymysql.cursors.DictCursor)
            
            seven_days_ago = datetime.now() - timedelta(days=7)
            
            cursor.execute("""
                SELECT c.id, c.company_name, c.industry, c.sales_stage, 
                       c.customer_level, c.last_follow_time, c.next_action,
                       s.score as ai_score
                FROM customers c
                LEFT JOIN customer_ai_scores s ON c.id = s.customer_id
                WHERE c.sales_stage NOT IN ('closed', 'lost')
                  AND (c.last_follow_time IS NULL OR c.last_follow_time < %s)
                ORDER BY s.score DESC
            """, (seven_days_ago,))
            
            customers = cursor.fetchall()
            cursor.close()
            conn.close()
            
            return customers
        except Exception as e:
            logger.error(f"检查7天未跟进客户失败: {e}")
            return []
    
    def check_high_value_no_follow(self):
        """检查高价值客户未跟进（A级客户3天未跟进）"""
        try:
            conn = self.get_db_connection()
            cursor = conn.cursor(pymysql.cursors.DictCursor)
            
            three_days_ago = datetime.now() - timedelta(days=3)
            
            cursor.execute("""
                SELECT c.id, c.company_name, c.industry, c.sales_stage,
                       c.customer_level, c.last_follow_time, c.next_action,
                       s.score as ai_score
                FROM customers c
                LEFT JOIN customer_ai_scores s ON c.id = s.customer_id
                WHERE c.customer_level = 'A'
                  AND c.sales_stage NOT IN ('closed', 'lost')
                  AND (c.last_follow_time IS NULL OR c.last_follow_time < %s)
                ORDER BY s.score DESC
            """, (three_days_ago,))
            
            customers = cursor.fetchall()
            cursor.close()
            conn.close()
            
            return customers
        except Exception as e:
            logger.error(f"检查高价值客户未跟进失败: {e}")
            return []
    
    def check_stage_stalled(self):
        """检查销售阶段停滞（同一阶段超过14天）"""
        try:
            conn = self.get_db_connection()
            cursor = conn.cursor(pymysql.cursors.DictCursor)
            
            fourteen_days_ago = datetime.now() - timedelta(days=14)
            
            cursor.execute("""
                SELECT c.id, c.company_name, c.industry, c.sales_stage,
                       c.customer_level, c.last_follow_time, c.next_action,
                       c.updated_time, s.score as ai_score
                FROM customers c
                LEFT JOIN customer_ai_scores s ON c.id = s.customer_id
                WHERE c.sales_stage NOT IN ('closed', 'lost', 'new')
                  AND c.updated_time < %s
                ORDER BY s.score DESC
            """, (fourteen_days_ago,))
            
            customers = cursor.fetchall()
            cursor.close()
            conn.close()
            
            return customers
        except Exception as e:
            logger.error(f"检查销售阶段停滞失败: {e}")
            return []
    
    def save_reminder(self, customer_id, customer_name, reminder_type, content, priority="medium"):
        """保存提醒到数据库"""
        try:
            conn = self.get_db_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO sales_reminders 
                (customer_id, customer_name, reminder_type, content, priority, status, created_time)
                VALUES (%s, %s, %s, %s, %s, 'pending', NOW())
            """, (customer_id, customer_name, reminder_type, content, priority))
            
            conn.commit()
            reminder_id = cursor.lastrowid
            cursor.close()
            conn.close()
            
            return reminder_id
        except Exception as e:
            logger.error(f"保存提醒失败: {e}")
            return None
    
    def generate_reminders(self):
        """生成所有提醒"""
        reminders = []
        
        # 7天未跟进
        no_follow_7d = self.check_no_follow_7d()
        for customer in no_follow_7d:
            days = 7
            if customer.get("last_follow_time"):
                days = (datetime.now() - customer["last_follow_time"]).days
            
            content = f"{customer.get('company_name')}已{days}天未跟进，当前阶段：{self.stage_map.get(customer.get('sales_stage', ''), customer.get('sales_stage', ''))}，建议今天联系负责人确认进展。"
            
            priority = "high" if customer.get("customer_level") == "A" else "medium"
            
            reminder_id = self.save_reminder(
                customer.get("id"), customer.get("company_name"),
                "no_follow_7d", content, priority
            )
            
            reminders.append({
                "id": reminder_id,
                "customer": customer.get("company_name"),
                "type": "7天未跟进",
                "content": content,
                "priority": priority,
                "days": days
            })
        
        # 高价值客户未跟进
        high_value = self.check_high_value_no_follow()
        high_value_ids = {r.get("customer") for r in reminders}
        
        for customer in high_value:
            if customer.get("company_name") in high_value_ids:
                continue
            
            days = 3
            if customer.get("last_follow_time"):
                days = (datetime.now() - customer["last_follow_time"]).days
            
            content = f"高价值客户{customer.get('company_name')}已{days}天未跟进，AI评分{customer.get('ai_score', 0)}分，建议优先跟进。"
            
            reminder_id = self.save_reminder(
                customer.get("id"), customer.get("company_name"),
                "high_value_no_follow", content, "high"
            )
            
            reminders.append({
                "id": reminder_id,
                "customer": customer.get("company_name"),
                "type": "高价值客户未跟进",
                "content": content,
                "priority": "high",
                "days": days
            })
        
        # 销售阶段停滞
        stalled = self.check_stage_stalled()
        stalled_ids = {r.get("customer") for r in reminders}
        
        for customer in stalled:
            if customer.get("company_name") in stalled_ids:
                continue
            
            days = 14
            if customer.get("updated_time"):
                days = (datetime.now() - customer["updated_time"]).days
            
            content = f"{customer.get('company_name')}在{self.stage_map.get(customer.get('sales_stage', ''), customer.get('sales_stage', ''))}阶段已停滞{days}天，建议推进或评估是否继续跟进。"
            
            priority = "high" if customer.get("customer_level") == "A" else "medium"
            
            reminder_id = self.save_reminder(
                customer.get("id"), customer.get("company_name"),
                "stage_stalled", content, priority
            )
            
            reminders.append({
                "id": reminder_id,
                "customer": customer.get("company_name"),
                "type": "销售阶段停滞",
                "content": content,
                "priority": priority,
                "days": days
            })
        
        return reminders
    
    def push_reminders(self, reminders=None):
        """推送提醒到飞书"""
        if reminders is None:
            reminders = self.generate_reminders()
        
        if not reminders:
            logger.info("暂无需要提醒的客户")
            return {"status": "skipped", "reason": "暂无提醒", "count": 0}
        
        today = datetime.now().strftime("%Y-%m-%d")
        title = f"⚠️ 客户跟进提醒 | {today} | 共{len(reminders)}条"
        
        # 构建卡片内容
        elements = []
        
        # 按优先级分组
        high_priority = [r for r in reminders if r.get("priority") == "high"]
        medium_priority = [r for r in reminders if r.get("priority") == "medium"]
        
        if high_priority:
            elements.append({
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"**🔴 高优先级提醒 ({len(high_priority)}条)**"}
            })
            
            for reminder in high_priority:
                elements.append({
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": f"**{reminder.get('customer')}** - {reminder.get('type')}\n{reminder.get('content')}"}
                })
            
            elements.append({"tag": "hr"})
        
        if medium_priority:
            elements.append({
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"**🟡 中优先级提醒 ({len(medium_priority)}条)**"}
            })
            
            for reminder in medium_priority:
                elements.append({
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": f"**{reminder.get('customer')}** - {reminder.get('type')}\n{reminder.get('content')}"}
                })
            
            elements.append({"tag": "hr"})
        
        elements.append({
            "tag": "note",
            "elements": [{"tag": "plain_text", "content": f"AI销售助手自动生成 | {today} | 请及时跟进客户"}]
        })
        
        result = self.notifier.send_card(
            title=title,
            content_elements=elements,
            header_color="orange"
        )
        
        if result.get("status") == "success":
            logger.info(f"客户跟进提醒推送成功: {len(reminders)}条")
            return {"status": "success", "count": len(reminders), "message_id": result.get("message_id")}
        else:
            logger.error(f"客户跟进提醒推送失败: {result}")
            return {"status": "failed", "error": result.get("error", str(result))}
    
    def get_pending_reminders(self, limit=20):
        """获取待处理提醒"""
        try:
            conn = self.get_db_connection()
            cursor = conn.cursor(pymysql.cursors.DictCursor)
            
            cursor.execute("""
                SELECT * FROM sales_reminders 
                WHERE status = 'pending'
                ORDER BY priority DESC, created_time DESC
                LIMIT %s
            """, (limit,))
            
            reminders = cursor.fetchall()
            cursor.close()
            conn.close()
            
            return reminders
        except Exception as e:
            logger.error(f"获取待处理提醒失败: {e}")
            return []


# 单例
_follow_reminder_agent = None

def get_follow_reminder_agent():
    """获取客户跟进提醒Agent单例"""
    global _follow_reminder_agent
    if _follow_reminder_agent is None:
        _follow_reminder_agent = FollowReminderAgent()
    return _follow_reminder_agent


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv("/opt/Weibo-Analyst/.env")
    
    agent = FollowReminderAgent()
    reminders = agent.generate_reminders()
    print(f"生成 {len(reminders)} 条提醒")
    for r in reminders:
        print(f"  - [{r.get('priority')}] {r.get('customer')}: {r.get('type')}")
    
    if reminders:
        result = agent.push_reminders(reminders)
        print(json.dumps(result, ensure_ascii=False, indent=2))
