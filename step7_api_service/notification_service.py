#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通知服务模块（预留接口）
支持飞书机器人Webhook推送，未来可扩展微信、邮件等
"""
import os
import sys
import json
import requests
from datetime import datetime

sys.path.insert(0, "/opt/Weibo-Analyst")


class NotificationService:
    """通知服务"""
    
    def __init__(self):
        self.feishu_webhook = os.getenv("FEISHU_WEBHOOK_URL", "")
        self.enabled = bool(self.feishu_webhook)
    
    def send_feishu_notification(self, title, content, msg_type="text"):
        """
        发送飞书通知
        
        Args:
            title: 通知标题
            content: 通知内容
            msg_type: 消息类型 (text/interactive)
        
        Returns:
            发送结果
        """
        if not self.enabled:
            return {"status": "skipped", "reason": "飞书Webhook未配置"}
        
        try:
            if msg_type == "interactive":
                # 卡片消息
                payload = {
                    "msg_type": "interactive",
                    "card": {
                        "header": {
                            "title": {"tag": "plain_text", "content": title},
                            "template": "blue"
                        },
                        "elements": [
                            {"tag": "markdown", "content": content}
                        ]
                    }
                }
            else:
                # 文本消息
                payload = {
                    "msg_type": "text",
                    "content": {"text": f"{title}\n\n{content}"}
                }
            
            response = requests.post(
                self.feishu_webhook,
                json=payload,
                timeout=10
            )
            
            result = response.json()
            if result.get("code") == 0 or result.get("StatusCode") == 0:
                return {"status": "success", "message": "通知发送成功"}
            else:
                return {"status": "failed", "error": str(result)}
                
        except Exception as e:
            return {"status": "failed", "error": str(e)}
    
    def send_daily_report_notification(self, date_str, report_summary):
        """发送日报生成完成通知"""
        title = f"🤖 AI行业日报已生成 - {date_str}"
        content = f"""
**日期**: {date_str}
**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

{report_summary}

---
*由AI行业情报系统自动推送*
"""
        return self.send_feishu_notification(title, content, msg_type="interactive")
    
    def send_pipeline_failure_notification(self, date_str, step, error):
        """发送流水线失败通知"""
        title = f"⚠️ AI情报流水线失败 - {date_str}"
        content = f"""
**日期**: {date_str}
**失败步骤**: {step}
**错误信息**: {error[:200]}

请及时检查系统状态。
"""
        return self.send_feishu_notification(title, content, msg_type="interactive")
    
    def send_health_check_notification(self, health):
        """发送健康检查通知"""
        if health["overall_status"] == "healthy":
            return {"status": "skipped", "reason": "系统健康，无需通知"}
        
        title = f"🏥 AI情报系统健康检查 - {health['overall_status'].upper()}"
        content = f"""
**日期**: {health['date']}
**整体状态**: {health['overall_status'].upper()}

**警告项**: {', '.join(health['summary']['warning_checks']) or '无'}
**失败项**: {', '.join(health['summary']['failed_checks']) or '无'}

请及时检查系统状态。
"""
        return self.send_feishu_notification(title, content, msg_type="interactive")


# 全局实例
notification_service = NotificationService()


def send_notification(title, content, msg_type="text"):
    """便捷函数：发送通知"""
    return notification_service.send_feishu_notification(title, content, msg_type)


if __name__ == "__main__":
    # 测试通知服务
    print("通知服务测试")
    print(f"飞书Webhook已配置: {notification_service.enabled}")
    
    if notification_service.enabled:
        result = send_notification("测试通知", "这是一条测试消息，来自AI行业情报系统。")
        print(f"发送结果: {result}")
    else:
        print("未配置飞书Webhook，跳过发送测试")
        print("如需启用，请设置环境变量 FEISHU_WEBHOOK_URL")
