#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
飞书通知模块
支持文本消息、卡片消息、Markdown消息
使用飞书开放平台API发送消息
"""
import os
import sys
import json
import requests
import logging
from datetime import datetime

sys.path.insert(0, "/opt/Weibo-Analyst")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class FeishuNotification:
    """飞书通知服务"""
    
    def __init__(self):
        self.app_id = os.getenv("FEISHU_APP_ID", "")
        self.app_secret = os.getenv("FEISHU_APP_SECRET", "")
        self.chat_id = os.getenv("FEISHU_CHAT_ID", "")
        self.webhook_url = os.getenv("FEISHU_WEBHOOK_URL", "")
        self._tenant_access_token = None
        self._token_expire_time = None
        
        # 判断是否可用
        self.api_enabled = bool(self.app_id and self.app_secret and self.chat_id)
        self.webhook_enabled = bool(self.webhook_url)
        self.enabled = self.api_enabled or self.webhook_enabled
        
        logger.info(f"飞书通知初始化: API={'启用' if self.api_enabled else '未启用'}, Webhook={'启用' if self.webhook_enabled else '未启用'}")
    
    def _get_tenant_access_token(self):
        """获取tenant_access_token"""
        if self._tenant_access_token and self._token_expire_time and datetime.now().timestamp() < self._token_expire_time:
            return self._tenant_access_token
        
        try:
            url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
            payload = {
                "app_id": self.app_id,
                "app_secret": self.app_secret
            }
            response = requests.post(url, json=payload, timeout=10)
            data = response.json()
            
            if data.get("code") == 0:
                self._tenant_access_token = data["tenant_access_token"]
                self._token_expire_time = datetime.now().timestamp() + data.get("expire", 7200) - 300
                logger.info("获取tenant_access_token成功")
                return self._tenant_access_token
            else:
                logger.error(f"获取tenant_access_token失败: {data}")
                return None
        except Exception as e:
            logger.error(f"获取tenant_access_token异常: {e}")
            return None
    
    def send_text(self, content, chat_id=None):
        """
        发送文本消息
        
        Args:
            content: 文本内容
            chat_id: 会话ID，默认使用配置的chat_id
        
        Returns:
            发送结果
        """
        if not self.enabled:
            return {"status": "skipped", "reason": "飞书未配置"}
        
        target_chat = chat_id or self.chat_id
        
        if self.api_enabled:
            return self._send_text_api(content, target_chat)
        elif self.webhook_enabled:
            return self._send_text_webhook(content)
        else:
            return {"status": "failed", "reason": "无可用发送方式"}
    
    def _send_text_api(self, content, chat_id):
        """通过API发送文本消息"""
        try:
            token = self._get_tenant_access_token()
            if not token:
                return {"status": "failed", "reason": "获取token失败"}
            
            url = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }
            payload = {
                "receive_id": chat_id,
                "msg_type": "text",
                "content": json.dumps({"text": content})
            }
            
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            data = response.json()
            
            if data.get("code") == 0:
                logger.info("文本消息发送成功")
                return {"status": "success", "message_id": data.get("data", {}).get("message_id")}
            else:
                logger.error(f"文本消息发送失败: {data}")
                return {"status": "failed", "error": data.get("msg", str(data))}
        except Exception as e:
            logger.error(f"文本消息发送异常: {e}")
            return {"status": "failed", "error": str(e)}
    
    def _send_text_webhook(self, content):
        """通过Webhook发送文本消息"""
        try:
            payload = {
                "msg_type": "text",
                "content": {"text": content}
            }
            response = requests.post(self.webhook_url, json=payload, timeout=10)
            data = response.json()
            
            if data.get("code") == 0 or data.get("StatusCode") == 0:
                logger.info("Webhook文本消息发送成功")
                return {"status": "success"}
            else:
                logger.error(f"Webhook文本消息发送失败: {data}")
                return {"status": "failed", "error": str(data)}
        except Exception as e:
            logger.error(f"Webhook文本消息发送异常: {e}")
            return {"status": "failed", "error": str(e)}
    
    def send_card(self, title, content_elements, chat_id=None, header_color="blue"):
        """
        发送卡片消息
        
        Args:
            title: 卡片标题
            content_elements: 内容元素列表
            chat_id: 会话ID
            header_color: 标题颜色 (blue/green/orange/red/purple)
        
        Returns:
            发送结果
        """
        if not self.enabled:
            return {"status": "skipped", "reason": "飞书未配置"}
        
        target_chat = chat_id or self.chat_id
        
        # 构建卡片
        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": header_color
            },
            "elements": content_elements
        }
        
        if self.api_enabled:
            return self._send_card_api(card, target_chat)
        elif self.webhook_enabled:
            return self._send_card_webhook(card)
        else:
            return {"status": "failed", "reason": "无可用发送方式"}
    
    def _send_card_api(self, card, chat_id):
        """通过API发送卡片消息"""
        try:
            token = self._get_tenant_access_token()
            if not token:
                return {"status": "failed", "reason": "获取token失败"}
            
            url = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id"
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json"
            }
            payload = {
                "receive_id": chat_id,
                "msg_type": "interactive",
                "content": json.dumps(card)
            }
            
            response = requests.post(url, headers=headers, json=payload, timeout=10)
            data = response.json()
            
            if data.get("code") == 0:
                logger.info("卡片消息发送成功")
                return {"status": "success", "message_id": data.get("data", {}).get("message_id")}
            else:
                logger.error(f"卡片消息发送失败: {data}")
                return {"status": "failed", "error": data.get("msg", str(data))}
        except Exception as e:
            logger.error(f"卡片消息发送异常: {e}")
            return {"status": "failed", "error": str(e)}
    
    def _send_card_webhook(self, card):
        """通过Webhook发送卡片消息"""
        try:
            payload = {
                "msg_type": "interactive",
                "card": card
            }
            response = requests.post(self.webhook_url, json=payload, timeout=10)
            data = response.json()
            
            if data.get("code") == 0 or data.get("StatusCode") == 0:
                logger.info("Webhook卡片消息发送成功")
                return {"status": "success"}
            else:
                logger.error(f"Webhook卡片消息发送失败: {data}")
                return {"status": "failed", "error": str(data)}
        except Exception as e:
            logger.error(f"Webhook卡片消息发送异常: {e}")
            return {"status": "failed", "error": str(e)}
    
    def send_markdown(self, title, markdown_content, chat_id=None):
        """
        发送Markdown消息（转换为卡片）
        
        Args:
            title: 标题
            markdown_content: Markdown内容
            chat_id: 会话ID
        
        Returns:
            发送结果
        """
        # 将Markdown转换为飞书卡片元素
        elements = []
        
        # 分割内容为段落
        paragraphs = markdown_content.split("\n\n")
        
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            
            # 处理标题
            if para.startswith("### "):
                elements.append({
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": f"**{para[4:]}**"}
                })
            elif para.startswith("## "):
                elements.append({
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": f"**{para[3:]}**"}
                })
            elif para.startswith("# "):
                elements.append({
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": f"**{para[2:]}**"}
                })
            else:
                elements.append({
                    "tag": "div",
                    "text": {"tag": "lark_md", "content": para}
                })
            
            elements.append({"tag": "hr"})
        
        # 移除最后一个分隔线
        if elements and elements[-1].get("tag") == "hr":
            elements.pop()
        
        return self.send_card(title, elements, chat_id)
    
    def test_connection(self):
        """测试飞书连接"""
        if not self.enabled:
            return {"status": "skipped", "reason": "飞书未配置", "enabled": False}
        
        try:
            if self.api_enabled:
                token = self._get_tenant_access_token()
                if token:
                    return {
                        "status": "success",
                        "enabled": True,
                        "method": "api",
                        "app_id": self.app_id,
                        "chat_id": self.chat_id,
                        "message": "飞书API连接成功"
                    }
                else:
                    return {"status": "failed", "enabled": True, "error": "获取token失败"}
            elif self.webhook_enabled:
                return {
                    "status": "success",
                    "enabled": True,
                    "method": "webhook",
                    "message": "飞书Webhook已配置"
                }
        except Exception as e:
            return {"status": "failed", "enabled": True, "error": str(e)}


# 单例
_feishu_notification = None

def get_feishu_notification():
    """获取飞书通知单例"""
    global _feishu_notification
    if _feishu_notification is None:
        _feishu_notification = FeishuNotification()
    return _feishu_notification


if __name__ == "__main__":
    # 测试
    from dotenv import load_dotenv
    load_dotenv("/opt/Weibo-Analyst/.env")
    
    notifier = FeishuNotification()
    result = notifier.test_connection()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    
    if result.get("status") == "success":
        # 发送测试消息
        test_result = notifier.send_text("🤖 飞书销售助手测试消息\n\n这是一条测试消息，飞书通知模块工作正常。")
        print("测试消息发送结果:", json.dumps(test_result, ensure_ascii=False, indent=2))
