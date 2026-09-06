#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
飞书群机器人日报推送模块
支持两种发送方式：
1. 群自定义机器人 Webhook（FeishuSender）
2. 自建应用 app_id + app_secret + chat_id（FeishuAppSender）
"""
from .feishu_sender import FeishuSender, FeishuAppSender, send_daily_report, send_alert

__all__ = ['FeishuSender', 'FeishuAppSender', 'send_daily_report', 'send_alert']
__version__ = '1.1.0'
