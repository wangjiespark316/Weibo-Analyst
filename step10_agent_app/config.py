#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Agent 应用层配置
- 公网 API 地址
- API Key（多租户）
- 关键词列表
- 输出目录
"""
import os

# 公网 API 地址
API_BASE = os.getenv('WEIBO_API_BASE', 'https://weibo-analyst-api.onrender.com')

# 默认 API Key（AI 行业客户）
DEFAULT_API_KEY = os.getenv('WEIBO_API_KEY', 'wk_test_ai_001')

# 多租户 API Key 配置
TENANTS = {
    'ai_industry': {
        'name': 'AI行业客户',
        'api_key': 'wk_test_ai_001',
    },
    'general_hotspot': {
        'name': '全网热点客户',
        'api_key': 'wk_test_hotspot_001',
    },
}

# 关键词趋势分析列表
KEYWORDS = ['豆包', '飞书', 'Agent', '大模型', 'AI办公', 'ChatGPT', '企业AI', '智能体']

# 输出目录
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.getenv('AGENT_OUTPUT_DIR', os.path.join(BASE_DIR, 'output'))

# 大模型 API 配置（可选，用于真实 LLM 调用）
LLM_API_KEY = os.getenv('LLM_API_KEY', '')
LLM_API_BASE = os.getenv('LLM_API_BASE', 'https://api.openai.com/v1')
LLM_MODEL = os.getenv('LLM_MODEL', 'gpt-4o-mini')

# 飞书机器人 Webhook（可选）
FEISHU_WEBHOOK = os.getenv('FEISHU_WEBHOOK', '')
