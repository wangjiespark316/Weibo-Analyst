#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
飞书机器人推送模块
==================
功能：
  - 通过 Webhook 发送 Markdown 消息到飞书群
  - 支持交互式卡片（标题 + Markdown 内容 + 按钮）
  - 环境变量配置：FEISHU_WEBHOOK_URL
  - 异常隔离：推送失败不影响主流程

用法：
  from step10_agent_app.feishu_sender import FeishuSender

  sender = FeishuSender()  # 自动读取 FEISHU_WEBHOOK_URL
  sender.send_daily_report(
      date_str='2026-09-06',
      hot_topics=['热点1', '热点2', '热点3'],
      ai_trend='AI行业趋势摘要...',
      risk_alert='风险提醒...',
      report_url='https://dashboard.example.com/report/2026-09-06',
      tenant_name='AI测试客户',
  )

环境变量：
  FEISHU_WEBHOOK_URL  飞书群机器人 Webhook 地址（必填）
  FEISHU_SECRET       飞书机器人签名校验密钥（可选，未配置则不签名）
"""
import os
import json
import time
import hmac
import hashlib
import base64
import requests
from datetime import datetime
from typing import Optional, List


class FeishuSender:
    """飞书机器人 Webhook 推送器"""

    def __init__(self, webhook_url: str = None, secret: str = None):
        """
        初始化飞书推送器

        Args:
            webhook_url: Webhook 地址（None 则从环境变量 FEISHU_WEBHOOK_URL 读取）
            secret: 签名密钥（None 则从环境变量 FEISHU_SECRET 读取）
        """
        self.webhook_url = webhook_url or os.getenv('FEISHU_WEBHOOK_URL', '')
        self.secret = secret or os.getenv('FEISHU_SECRET', '')
        self.enabled = bool(self.webhook_url)

    def _gen_sign(self, timestamp: int) -> str:
        """生成飞书签名（如果配置了 secret）"""
        if not self.secret:
            return ''
        string_to_sign = f'{timestamp}\n{self.secret}'
        hmac_code = hmac.new(
            string_to_sign.encode('utf-8'),
            digestmod=hashlib.sha256
        ).digest()
        return base64.b64encode(hmac_code).decode('utf-8')

    def _send(self, payload: dict, retries: int = 2) -> bool:
        """
        发送消息到飞书 Webhook

        Args:
            payload: 消息体
            retries: 重试次数

        Returns:
            是否发送成功
        """
        if not self.enabled:
            print('[Feishu] 未配置 FEISHU_WEBHOOK_URL，跳过推送')
            return False

        # 签名
        if self.secret:
            timestamp = int(time.time())
            payload['timestamp'] = str(timestamp)
            payload['sign'] = self._gen_sign(timestamp)

        for attempt in range(retries + 1):
            try:
                resp = requests.post(
                    self.webhook_url,
                    json=payload,
                    headers={'Content-Type': 'application/json'},
                    timeout=15,
                )
                result = resp.json()
                if result.get('code') == 0 or result.get('StatusCode') == 0:
                    print(f'[Feishu] 推送成功')
                    return True
                else:
                    print(f'[Feishu] 推送失败: {result}')
            except Exception as e:
                print(f'[Feishu] 推送异常（第{attempt+1}次）: {type(e).__name__}: {e}')

            if attempt < retries:
                time.sleep(2 * (attempt + 1))

        print(f'[Feishu] 推送最终失败（已重试{retries}次）')
        return False

    def send_text(self, text: str) -> bool:
        """发送纯文本消息"""
        payload = {
            'msg_type': 'text',
            'content': {'text': text},
        }
        return self._send(payload)

    def send_markdown(self, title: str, content: str) -> bool:
        """发送 Markdown 消息（交互式卡片）"""
        payload = {
            'msg_type': 'interactive',
            'card': {
                'config': {'wide_screen_mode': True},
                'header': {
                    'title': {'tag': 'plain_text', 'content': title},
                    'template': 'blue',
                },
                'elements': [
                    {
                        'tag': 'markdown',
                        'content': content,
                    }
                ],
            },
        }
        return self._send(payload)

    def send_daily_report(
        self,
        date_str: str = None,
        hot_topics: List[str] = None,
        ai_trend: str = '',
        risk_alert: str = '',
        report_url: str = '',
        tenant_name: str = '',
        sentiment_summary: str = '',
    ) -> bool:
        """
        发送微博舆情日报到飞书群

        Args:
            date_str: 日期（默认今天）
            hot_topics: 今日热点列表（TOP3）
            ai_trend: AI行业趋势摘要
            risk_alert: 风险提醒
            report_url: 完整日报链接
            tenant_name: 租户名称
            sentiment_summary: 情绪分析摘要

        Returns:
            是否发送成功
        """
        if date_str is None:
            date_str = datetime.now().strftime('%Y-%m-%d')

        # 构建 Markdown 内容
        lines = []

        # 日期和租户
        header_parts = [f'**日期**：{date_str}']
        if tenant_name:
            header_parts.append(f'**客户**：{tenant_name}')
        lines.append(' | '.join(header_parts))
        lines.append('')

        # 今日热点
        lines.append('🔥 **今日热点**')
        if hot_topics:
            for i, topic in enumerate(hot_topics[:3], 1):
                lines.append(f'{i}. {topic}')
        else:
            lines.append('暂无热点数据')
        lines.append('')

        # AI行业趋势
        lines.append('📈 **AI行业趋势**')
        lines.append(ai_trend or '暂无趋势数据')
        lines.append('')

        # 情绪分析
        if sentiment_summary:
            lines.append('😊 **用户情绪**')
            lines.append(sentiment_summary)
            lines.append('')

        # 风险提醒
        lines.append('⚠️ **风险提醒**')
        lines.append(risk_alert or '暂无明显风险')
        lines.append('')

        # 完整日报链接
        if report_url:
            lines.append(f'📄 **完整日报**：[点击查看]({report_url})')

        content = '\n'.join(lines)
        title = f'【微博舆情日报】{date_str}'

        return self.send_markdown(title, content)

    def send_alert(self, title: str, message: str, level: str = 'warning') -> bool:
        """
        发送告警消息

        Args:
            title: 告警标题
            message: 告警内容
            level: 告警级别（warning/error/info）
        """
        template_map = {
            'warning': 'orange',
            'error': 'red',
            'info': 'blue',
        }
        template = template_map.get(level, 'blue')

        payload = {
            'msg_type': 'interactive',
            'card': {
                'config': {'wide_screen_mode': True},
                'header': {
                    'title': {'tag': 'plain_text', 'content': title},
                    'template': template,
                },
                'elements': [
                    {'tag': 'markdown', 'content': message},
                ],
            },
        }
        return self._send(payload)


# ============================================================
# 便捷函数
# ============================================================

def send_daily_report(**kwargs) -> bool:
    """便捷函数：使用默认配置发送日报"""
    sender = FeishuSender()
    return sender.send_daily_report(**kwargs)


def send_alert(title: str, message: str, level: str = 'warning') -> bool:
    """便捷函数：使用默认配置发送告警"""
    sender = FeishuSender()
    return sender.send_alert(title, message, level)


if __name__ == '__main__':
    # 测试：发送一条测试消息
    print('飞书推送模块测试')
    print(f'Webhook 已配置: {bool(os.getenv("FEISHU_WEBHOOK_URL"))}')

    sender = FeishuSender()
    if sender.enabled:
        success = sender.send_daily_report(
            date_str=datetime.now().strftime('%Y-%m-%d'),
            hot_topics=[
                '豆包发布新版本，AI办公能力升级',
                '飞书集成AI Agent，企业协作效率提升',
                '大模型行业竞争加剧，多家厂商发布新品',
            ],
            ai_trend='豆包(337次) > 大模型(99次) > 飞书(92次)，Agent概念持续升温。',
            risk_alert='部分用户反馈产品体验问题，建议关注负面舆情。',
            report_url='https://weibo-analyst-dashboard.vercel.app',
            tenant_name='AI测试客户',
            sentiment_summary='正面23% / 中性75% / 负面2%，整体情绪偏正面。',
        )
        print(f'测试消息发送: {"成功" if success else "失败"}')
    else:
        print('未配置 FEISHU_WEBHOOK_URL，跳过测试')
        print('请设置环境变量：export FEISHU_WEBHOOK_URL="https://open.feishu.cn/open-apis/bot/v2/hook/xxx"')
