#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""调度器配置"""
import os

# 基础路径
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(BASE_DIR)

# ===== 生产化：自动加载项目根目录 .env =====
# 场景：launchd / 开机自启 / 无交互 shell 启动时，不会自动 source .env
# 加载顺序：系统环境变量 > 项目根 .env > 代码默认值
# override=False 保证不覆盖已有的系统环境变量
try:
    from dotenv import load_dotenv
    _env_path = os.path.join(PROJECT_ROOT, '.env')
    if os.path.exists(_env_path):
        load_dotenv(_env_path, override=False)
except ImportError:
    # python-dotenv 未安装时回退到纯系统环境变量（不影响已有功能）
    pass

# 日报存储目录: reports/{tenant_key}/{YYYY-MM-DD}.md
REPORTS_DIR = os.path.join(BASE_DIR, 'reports')

# 租户配置文件路径（复用 step8 的配置）
TENANTS_CONFIG = os.path.join(PROJECT_ROOT, 'step8_agent_verification', 'config', 'tenants.json')

# Agent 客户端路径
AGENT_CLIENT_DIR = os.path.join(PROJECT_ROOT, 'step8_agent_verification')

# 定时执行时间
SCHEDULE_HOUR = int(os.getenv('SCHEDULE_HOUR', '8'))
SCHEDULE_MINUTE = int(os.getenv('SCHEDULE_MINUTE', '0'))

# ===== 飞书推送配置 =====
# 方式一：飞书自建应用（推荐，支持群聊、私聊、富文本卡片）
FEISHU_APP_ID = os.getenv('FEISHU_APP_ID', '')
FEISHU_APP_SECRET = os.getenv('FEISHU_APP_SECRET', '')
FEISHU_CHAT_ID = os.getenv('FEISHU_CHAT_ID', '')

# 方式二：飞书群机器人 Webhook（简单，仅支持群聊）
FEISHU_WEBHOOK_URL = os.getenv('FEISHU_WEBHOOK_URL', '')
# 飞书机器人签名密钥（可选，仅 Webhook 模式）
FEISHU_SECRET = os.getenv('FEISHU_SECRET', '')

# 是否启用飞书推送（有 app 凭证或 Webhook 则自动启用）
FEISHU_ENABLED = bool(FEISHU_APP_ID and FEISHU_APP_SECRET and FEISHU_CHAT_ID) or bool(FEISHU_WEBHOOK_URL)
# 日报 Dashboard 链接模板
REPORT_URL_TEMPLATE = os.getenv('REPORT_URL_TEMPLATE', 'https://weibo-analyst.vercel.app/')

# ===== 数据采集配置（预留） =====
# 是否在日报生成前执行数据采集
ENABLE_CRAWL = os.getenv('ENABLE_CRAWL', 'false').lower() == 'true'
# 采集脚本路径
CRAWL_POST_SCRIPT = os.path.join(PROJECT_ROOT, 'step1_comments_spider', 'weibo_post_collector.py')
CRAWL_COMMENT_SCRIPT = os.path.join(PROJECT_ROOT, 'step1_comments_spider', 'weibo_comment_batch_collector.py')
