#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""调度器配置"""
import os

# 基础路径
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)

# 日报存储目录: reports/{tenant_key}/{YYYY-MM-DD}.md
REPORTS_DIR = os.path.join(BASE_DIR, 'reports')

# 租户配置文件路径（复用 step8 的配置）
TENANTS_CONFIG = os.path.join(PROJECT_ROOT, 'step8_agent_verification', 'config', 'tenants.json')

# Agent 客户端路径
AGENT_CLIENT_DIR = os.path.join(PROJECT_ROOT, 'step8_agent_verification')

# 定时执行时间
SCHEDULE_HOUR = 8
SCHEDULE_MINUTE = 0
