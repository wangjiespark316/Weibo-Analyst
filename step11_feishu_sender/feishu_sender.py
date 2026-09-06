#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
飞书群机器人日报推送模块
========================
支持：
- 飞书群机器人 Webhook 发送
- Markdown 交互式卡片消息
- 签名校验（可选）
- 重试机制
- 租户独立 Webhook 配置
- 环境变量全局配置

用法：
    from step11_feishu_sender.feishu_sender import FeishuSender, send_daily_report

    sender = FeishuSender(webhook_url="https://open.feishu.cn/open-apis/bot/v2/hook/xxx")
    sender.send_daily_report(
        date_str="2026-09-06",
        tenant_name="AI测试客户",
        hot_topics=["热点1", "热点2"],
        ai_trend="AI行业趋势...",
        keyword_changes="关键词变化...",
        sentiment_summary="正面23%/中性75%/负面2%",
        risk_alert="风险提醒...",
        report_url="https://weibo-analyst.vercel.app/",
    )
"""
import os
import json
import time
import hmac
import hashlib
import base64
import requests
from datetime import datetime
from typing import Optional, List, Dict, Any


class FeishuSender:
    """飞书群机器人发送器"""

    def __init__(
        self,
        webhook_url: Optional[str] = None,
        secret: Optional[str] = None,
        timeout: int = 15,
        max_retries: int = 2,
    ):
        """
        初始化飞书发送器

        Args:
            webhook_url: 飞书群机器人 Webhook 地址（优先使用此参数，否则读环境变量）
            secret: 签名校验密钥（可选）
            timeout: 请求超时时间（秒）
            max_retries: 最大重试次数
        """
        self.webhook_url = webhook_url or os.getenv('FEISHU_WEBHOOK_URL', '')
        self.secret = secret or os.getenv('FEISHU_SECRET', '')
        self.timeout = timeout
        self.max_retries = max_retries
        self.enabled = bool(self.webhook_url)

    def _gen_sign(self, timestamp: int) -> str:
        """生成飞书机器人签名"""
        string_to_sign = f"{timestamp}\n{self.secret}"
        hmac_code = hmac.new(
            string_to_sign.encode("utf-8"),
            digestmod=hashlib.sha256
        ).digest()
        return base64.b64encode(hmac_code).decode('utf-8')

    def _send(self, payload: Dict[str, Any]) -> bool:
        """
        发送消息到飞书（带重试）

        Args:
            payload: 消息体

        Returns:
            是否发送成功
        """
        if not self.enabled:
            print('[Feishu] Webhook 未配置，跳过发送')
            return False

        # 如果配置了签名，添加签名
        if self.secret:
            timestamp = int(time.time())
            payload['timestamp'] = str(timestamp)
            payload['sign'] = self._gen_sign(timestamp)

        for attempt in range(self.max_retries + 1):
            try:
                resp = requests.post(
                    self.webhook_url,
                    json=payload,
                    headers={'Content-Type': 'application/json'},
                    timeout=self.timeout,
                )
                result = resp.json()
                if result.get('code') == 0 or result.get('StatusCode') == 0:
                    return True
                else:
                    print(f'[Feishu] 推送失败: {result}')
                    if attempt < self.max_retries:
                        time.sleep(2)
            except Exception as e:
                print(f'[Feishu] 推送异常: {type(e).__name__}: {e}')
                if attempt < self.max_retries:
                    time.sleep(2)

        print(f'[Feishu] 推送最终失败（已重试{self.max_retries}次）')
        return False

    def send_text(self, text: str) -> bool:
        """发送纯文本消息"""
        payload = {
            "msg_type": "text",
            "content": {"text": text},
        }
        return self._send(payload)

    def send_markdown(self, title: str, content: str) -> bool:
        """
        发送 Markdown 富文本消息（交互式卡片）

        Args:
            title: 消息标题
            content: Markdown 内容

        Returns:
            是否发送成功
        """
        payload = {
            "msg_type": "interactive",
            "card": {
                "config": {"wide_screen_mode": True},
                "header": {
                    "title": {"tag": "plain_text", "content": title},
                    "template": "blue",
                },
                "elements": [
                    {
                        "tag": "markdown",
                        "content": content,
                    }
                ],
            },
        }
        return self._send(payload)

    def send_daily_report(
        self,
        date_str: str,
        tenant_name: str = "",
        hot_topics: Optional[List[str]] = None,
        ai_trend: str = "",
        keyword_changes: str = "",
        sentiment_summary: str = "",
        risk_alert: str = "",
        report_url: str = "",
    ) -> bool:
        """
        发送微博舆情日报（交互式卡片）

        Args:
            date_str: 日期字符串，如 "2026-09-06"
            tenant_name: 租户名称
            hot_topics: 热点话题列表（TOP5）
            ai_trend: AI行业趋势
            keyword_changes: 关键词变化
            sentiment_summary: 用户情绪摘要
            risk_alert: 风险提醒
            report_url: 完整日报链接

        Returns:
            是否发送成功
        """
        hot_topics = hot_topics or []

        # 构建 Markdown 内容
        lines = []
        lines.append(f"**日期**：{date_str}")
        if tenant_name:
            lines.append(f"**客户**：{tenant_name}")
        lines.append("")

        # 一、今日热点TOP5
        lines.append("**一、今日热点 TOP5**")
        if hot_topics:
            for i, topic in enumerate(hot_topics[:5], 1):
                lines.append(f"{i}. {topic}")
        else:
            lines.append("暂无热点数据")
        lines.append("")

        # 二、AI行业趋势
        if ai_trend:
            lines.append("**二、AI行业趋势**")
            lines.append(ai_trend)
            lines.append("")

        # 三、关键词变化
        if keyword_changes:
            lines.append("**三、关键词变化**")
            lines.append(keyword_changes)
            lines.append("")

        # 四、用户情绪
        if sentiment_summary:
            lines.append("**四、用户情绪**")
            lines.append(sentiment_summary)
            lines.append("")

        # 五、风险提醒
        if risk_alert:
            lines.append("**五、风险提醒**")
            lines.append(f"⚠️ {risk_alert}")
            lines.append("")

        # 完整日报链接
        if report_url:
            lines.append(f"[📄 查看完整日报]({report_url})")

        content = "\n".join(lines)
        title = f"【微博舆情日报】{date_str}"

        return self.send_markdown(title=title, content=content)

    def send_alert(
        self,
        title: str,
        message: str,
        level: str = "warning",
    ) -> bool:
        """
        发送告警消息

        Args:
            title: 告警标题
            message: 告警内容
            level: 告警级别 (warning / error / info)

        Returns:
            是否发送成功
        """
        color_map = {
            "warning": "orange",
            "error": "red",
            "info": "blue",
        }
        template = color_map.get(level, "blue")

        payload = {
            "msg_type": "interactive",
            "card": {
                "config": {"wide_screen_mode": True},
                "header": {
                    "title": {"tag": "plain_text", "content": f"⚠️ {title}"},
                    "template": template,
                },
                "elements": [
                    {"tag": "markdown", "content": message},
                ],
            },
        }
        return self._send(payload)


# ============================================================
# 飞书自建应用发送器（app_id + app_secret + chat_id）
# ============================================================

class FeishuAppSender:
    """
    飞书自建应用发送器
    通过 app_id + app_secret 获取 tenant_access_token，调用消息 API 发送到指定群

    环境变量：
        FEISHU_APP_ID: 应用 app_id（cli_xxx）
        FEISHU_APP_SECRET: 应用 app_secret
        FEISHU_CHAT_ID: 目标群 chat_id（oc_xxx）
    """

    TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
    MSG_URL = "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id"

    def __init__(
        self,
        app_id: Optional[str] = None,
        app_secret: Optional[str] = None,
        chat_id: Optional[str] = None,
        timeout: int = 15,
        max_retries: int = 2,
    ):
        self.app_id = app_id or os.getenv('FEISHU_APP_ID', '')
        self.app_secret = app_secret or os.getenv('FEISHU_APP_SECRET', '')
        self.chat_id = chat_id or os.getenv('FEISHU_CHAT_ID', '')
        self.timeout = timeout
        self.max_retries = max_retries
        self._token = None
        self._token_expire_at = 0
        self.enabled = bool(self.app_id and self.app_secret and self.chat_id)

    def _get_token(self) -> Optional[str]:
        """获取 tenant_access_token（带缓存，提前5分钟刷新）"""
        now = time.time()
        if self._token and now < self._token_expire_at - 300:
            return self._token

        try:
            resp = requests.post(
                self.TOKEN_URL,
                json={"app_id": self.app_id, "app_secret": self.app_secret},
                timeout=self.timeout,
            )
            result = resp.json()
            if result.get('code') == 0:
                self._token = result.get('tenant_access_token', '')
                self._token_expire_at = now + result.get('expire', 7200)
                return self._token
            else:
                print(f'[FeishuApp] 获取 token 失败: {result}')
                return None
        except Exception as e:
            print(f'[FeishuApp] 获取 token 异常: {type(e).__name__}: {e}')
            return None

    def _send(self, msg_type: str, content: Dict[str, Any]) -> bool:
        """发送消息（带重试）"""
        if not self.enabled:
            print('[FeishuApp] 未配置 app_id/app_secret/chat_id，跳过发送')
            return False

        token = self._get_token()
        if not token:
            return False

        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
        }
        payload = {
            'receive_id': self.chat_id,
            'msg_type': msg_type,
            'content': json.dumps(content, ensure_ascii=False),
        }

        for attempt in range(self.max_retries + 1):
            try:
                resp = requests.post(
                    self.MSG_URL,
                    headers=headers,
                    json=payload,
                    timeout=self.timeout,
                )
                result = resp.json()
                if result.get('code') == 0:
                    return True
                else:
                    print(f'[FeishuApp] 推送失败: {result}')
                    if attempt < self.max_retries:
                        time.sleep(2)
            except Exception as e:
                print(f'[FeishuApp] 推送异常: {type(e).__name__}: {e}')
                if attempt < self.max_retries:
                    time.sleep(2)

        print(f'[FeishuApp] 推送最终失败（已重试{self.max_retries}次）')
        return False

    def send_text(self, text: str) -> bool:
        """发送纯文本消息"""
        return self._send('text', {'text': text})

    def send_interactive(self, card: Dict[str, Any]) -> bool:
        """发送交互式卡片消息"""
        return self._send('interactive', card)

    def send_daily_report(
        self,
        date_str: str,
        tenant_name: str = "",
        hot_topics: Optional[List[str]] = None,
        ai_trend: str = "",
        keyword_changes: str = "",
        sentiment_summary: str = "",
        risk_alert: str = "",
        report_url: str = "",
    ) -> bool:
        """发送微博舆情日报（交互式卡片）"""
        hot_topics = hot_topics or []

        # 构建 Markdown 内容
        lines = []
        lines.append(f"**日期**：{date_str}")
        if tenant_name:
            lines.append(f"**客户**：{tenant_name}")
        lines.append("")

        lines.append("**一、今日热点 TOP5**")
        if hot_topics:
            for i, topic in enumerate(hot_topics[:5], 1):
                lines.append(f"{i}. {topic}")
        else:
            lines.append("暂无热点数据")
        lines.append("")

        if ai_trend:
            lines.append("**二、AI行业趋势**")
            lines.append(ai_trend)
            lines.append("")

        if keyword_changes:
            lines.append("**三、关键词变化**")
            lines.append(keyword_changes)
            lines.append("")

        if sentiment_summary:
            lines.append("**四、用户情绪**")
            lines.append(sentiment_summary)
            lines.append("")

        if risk_alert:
            lines.append("**五、风险提醒**")
            lines.append(f"⚠️ {risk_alert}")
            lines.append("")

        if report_url:
            lines.append(f"[📄 查看完整日报]({report_url})")

        content = "\n".join(lines)

        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": f"【微博舆情日报】{date_str}"},
                "template": "blue",
            },
            "elements": [
                {"tag": "markdown", "content": content},
            ],
        }
        return self.send_interactive(card)

    def send_alert(
        self,
        title: str,
        message: str,
        level: str = "warning",
    ) -> bool:
        """发送告警消息"""
        color_map = {"warning": "orange", "error": "red", "info": "blue"}
        template = color_map.get(level, "blue")

        card = {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": f"⚠️ {title}"},
                "template": template,
            },
            "elements": [
                {"tag": "markdown", "content": message},
            ],
        }
        return self.send_interactive(card)


# ============================================================
# 便捷函数
# ============================================================

def send_daily_report(
    webhook_url: Optional[str] = None,
    **kwargs,
) -> bool:
    """
    便捷函数：发送日报

    Args:
        webhook_url: Webhook 地址（不传则用环境变量）
        **kwargs: 传递给 FeishuSender.send_daily_report 的参数

    Returns:
        是否发送成功
    """
    sender = FeishuSender(webhook_url=webhook_url)
    return sender.send_daily_report(**kwargs)


def send_alert(
    title: str,
    message: str,
    level: str = "warning",
    webhook_url: Optional[str] = None,
) -> bool:
    """
    便捷函数：发送告警

    Args:
        title: 告警标题
        message: 告警内容
        level: 告警级别
        webhook_url: Webhook 地址

    Returns:
        是否发送成功
    """
    sender = FeishuSender(webhook_url=webhook_url)
    return sender.send_alert(title=title, message=message, level=level)


if __name__ == "__main__":
    # 测试
    print("飞书发送模块测试")
    print(f"Webhook 已配置: {bool(os.getenv('FEISHU_WEBHOOK_URL'))}")

    sender = FeishuSender()
    if sender.enabled:
        success = sender.send_daily_report(
            date_str=datetime.now().strftime('%Y-%m-%d'),
            tenant_name="测试客户",
            hot_topics=[
                "**楼斌Robin**：大折叠终于开始有自己不可替代的使用体验了",
                "**华商韬略官方微博**：西工大、北京城建带头选择华为擎云",
                "**人民网**：中国AI站上IFA展C位",
            ],
            ai_trend="豆包(337次)、大模型(99次)、飞书(92次) 为当前最热关键词。",
            keyword_changes="豆包提及量环比上升，Agent 和 智能体 讨论度增加。",
            sentiment_summary="正面23% / 中性75% / 负面2%（共1000条评论）",
            risk_alert="负面评论占比较低，舆情整体平稳。",
            report_url="https://weibo-analyst.vercel.app/",
        )
        print(f"发送结果: {'成功' if success else '失败'}")
    else:
        print("未配置 FEISHU_WEBHOOK_URL，跳过实际发送")
        print("模块导入和初始化正常")
