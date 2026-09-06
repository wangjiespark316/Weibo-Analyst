#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
飞书群机器人日报推送模块
"""
from .feishu_sender import FeishuSender, send_daily_report, send_alert

__all__ = ['FeishuSender', 'send_daily_report', 'send_alert']
__version__ = '1.0.0'
