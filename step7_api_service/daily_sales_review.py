#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
销售日报复盘模块
每天晚上生成《销售日报复盘》
内容：今日跟进、客户反馈、新增机会、明日建议
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


class DailySalesReview:
    """销售日报复盘"""
    
    def __init__(self):
        self.notifier = get_feishu_notification()
    
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
    
    def get_today_follows(self):
        """获取今日跟进记录"""
        try:
            conn = self.get_db_connection()
            cursor = conn.cursor(pymysql.cursors.DictCursor)
            
            today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            
            cursor.execute("""
                SELECT f.*, c.company_name
                FROM follow_records f
                LEFT JOIN customers c ON f.customer_id = c.id
                WHERE f.follow_time >= %s
                ORDER BY f.follow_time DESC
            """, (today_start,))
            
            follows = cursor.fetchall()
            cursor.close()
            conn.close()
            
            return follows
        except Exception as e:
            logger.error(f"获取今日跟进记录失败: {e}")
            return []
    
    def get_today_new_opportunities(self):
        """获取今日新增机会"""
        try:
            conn = self.get_db_connection()
            cursor = conn.cursor(pymysql.cursors.DictCursor)
            
            today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
            
            cursor.execute("""
                SELECT * FROM ai_sales_opportunities
                WHERE created_time >= %s
                ORDER BY priority DESC
            """, (today_start,))
            
            opportunities = cursor.fetchall()
            cursor.close()
            conn.close()
            
            return opportunities
        except Exception as e:
            logger.error(f"获取今日新增机会失败: {e}")
            return []
    
    def get_customer_summary(self):
        """获取客户统计"""
        try:
            conn = self.get_db_connection()
            cursor = conn.cursor(pymysql.cursors.DictCursor)
            
            # 各阶段客户数量
            cursor.execute("""
                SELECT sales_stage, COUNT(*) as count
                FROM customers
                WHERE sales_stage NOT IN ('closed', 'lost')
                GROUP BY sales_stage
            """)
            stages = cursor.fetchall()
            
            # 总客户数
            cursor.execute("SELECT COUNT(*) as total FROM customers")
            total = cursor.fetchone()
            
            cursor.close()
            conn.close()
            
            return {"total": total.get("total", 0), "stages": stages}
        except Exception as e:
            logger.error(f"获取客户统计失败: {e}")
            return {"total": 0, "stages": []}
    
    def generate_review(self):
        """生成销售复盘报告"""
        today = datetime.now().strftime("%Y-%m-%d")
        
        # 获取数据
        follows = self.get_today_follows()
        opportunities = self.get_today_new_opportunities()
        summary = self.get_customer_summary()
        
        # 构建卡片内容
        elements = []
        
        # 今日概览
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": f"**📊 今日概览**\n跟进记录: {len(follows)}条 | 新增机会: {len(opportunities)}个 | 活跃客户: {summary.get('total', 0)}个"}
        })
        
        elements.append({"tag": "hr"})
        
        # 今日跟进
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": "**📝 今日跟进记录**"}
        })
        
        if follows:
            for follow in follows[:5]:
                follow_type = follow.get("follow_type", "")
                company = follow.get("company_name", "未知客户")
                content = follow.get("content", "")[:80]
                next_action = follow.get("next_action", "")
                
                text = f"**{company}** ({follow_type})\n{content}"
                if next_action:
                    text += f"\n→ 下一步: {next_action}"
                
                elements.append({
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": text}
                })
        else:
            elements.append({
                "tag": "div",
                "text": {"tag": "lark_md", "content": "今日暂无跟进记录，建议明天积极跟进客户"}
            })
        
        elements.append({"tag": "hr"})
        
        # 新增机会
        if opportunities:
            elements.append({
                "tag": "div",
                "text": {"tag": "lark_md", "content": "**🔥 今日新增机会**"}
            })
            
            for opp in opportunities[:3]:
                industry = opp.get("industry", "")
                scenario = opp.get("scenario", "")
                priority = opp.get("priority", "medium")
                priority_text = "高" if priority == "high" else "中" if priority == "medium" else "低"
                
                elements.append({
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": f"**{industry} - {scenario}** (优先级: {priority_text})\n{opp.get('sales_angle', '')[:80]}"}
                })
            
            elements.append({"tag": "hr"})
        
        # 明日建议
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": "**💡 明日建议**"}
        })
        
        suggestions = []
        if len(follows) == 0:
            suggestions.append("明天优先跟进A级客户，保持客户热度")
        if len(follows) < 3:
            suggestions.append("建议每天至少跟进3个客户，保持销售节奏")
        
        # 检查是否有未跟进的A级客户
        try:
            conn = self.get_db_connection()
            cursor = conn.cursor(pymysql.cursors.DictCursor)
            three_days_ago = datetime.now() - timedelta(days=3)
            cursor.execute("""
                SELECT COUNT(*) as count FROM customers
                WHERE customer_level = 'A'
                  AND sales_stage NOT IN ('closed', 'lost')
                  AND (last_follow_time IS NULL OR last_follow_time < %s)
            """, (three_days_ago,))
            a_no_follow = cursor.fetchone()
            cursor.close()
            conn.close()
            
            if a_no_follow.get("count", 0) > 0:
                suggestions.append(f"有{a_no_follow.get('count', 0)}个A级客户超过3天未跟进，建议优先联系")
        except:
            pass
        
        if not suggestions:
            suggestions.append("继续保持当前跟进节奏，重点推进方案沟通阶段的客户")
        
        for i, suggestion in enumerate(suggestions, 1):
            elements.append({
                "tag": "div",
                "text": {"tag": "lark_md", "content": f"{i}. {suggestion}"}
            })
        
        # 底部
        elements.append({"tag": "hr"})
        elements.append({
            "tag": "note",
            "elements": [{"tag": "plain_text", "content": f"AI销售助手自动生成 | {today} | 销售日报复盘"}]
        })
        
        return elements
    
    def push_review(self):
        """推送销售复盘报告"""
        today = datetime.now().strftime("%Y-%m-%d")
        title = f"📋 销售日报复盘 | {today}"
        
        try:
            elements = self.generate_review()
            
            result = self.notifier.send_card(
                title=title,
                content_elements=elements,
                header_color="green"
            )
            
            if result.get("status") == "success":
                logger.info(f"销售复盘报告推送成功: {result.get('message_id')}")
                return {"status": "success", "message_id": result.get("message_id"), "title": title}
            else:
                logger.error(f"销售复盘报告推送失败: {result}")
                return {"status": "failed", "error": result.get("error", str(result))}
        except Exception as e:
            logger.error(f"销售复盘报告推送异常: {e}")
            return {"status": "failed", "error": str(e)}


# 单例
_daily_sales_review = None

def get_daily_sales_review():
    """获取销售复盘单例"""
    global _daily_sales_review
    if _daily_sales_review is None:
        _daily_sales_review = DailySalesReview()
    return _daily_sales_review


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv("/opt/Weibo-Analyst/.env")
    
    review = DailySalesReview()
    result = review.push_review()
    print(json.dumps(result, ensure_ascii=False, indent=2))
