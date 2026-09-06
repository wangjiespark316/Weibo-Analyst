#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
API 服务配置
- 云端部署（Render）：通过 DATABASE_URL 环境变量连接 TiDB
- 本地开发：通过 MYSQL_* 环境变量连接本地 MySQL
- 无任何硬编码密码，所有敏感信息从环境变量读取
"""
import os
from urllib.parse import urlparse, parse_qs


def _parse_database_url(url: str) -> dict:
    """解析 mysql://user:pass@host:port/dbname 连接串（TiDB 兼容）"""
    p = urlparse(url)
    query = parse_qs(p.query)
    config = {
        'host': p.hostname,
        'port': p.port or 4000,
        'user': p.username,
        'password': p.password or '',
        'database': p.path.lstrip('/'),
        'charset': 'utf8mb4',
    }
    # TiDB Cloud 强制 TLS
    is_tidb = 'tidb' in (p.hostname or '').lower()
    ssl_mode = query.get('ssl-mode', [''])[0].upper()
    if is_tidb or ssl_mode in ('VERIFY_IDENTITY', 'VERIFY_CA', 'REQUIRED'):
        ca_path = os.getenv('TIDB_CA_PATH')
        if ca_path and os.path.exists(ca_path):
            config['ssl'] = {'ca': ca_path}
        else:
            config['ssl'] = {'ssl_disabled': False}
    return config


# 数据库配置：优先 DATABASE_URL（云端），回退本地环境变量
_database_url = os.getenv('DATABASE_URL')
if _database_url:
    DB_CONFIG = _parse_database_url(_database_url)
else:
    # 本地开发默认配置（密码从环境变量读取，不硬编码）
    DB_CONFIG = {
        'host': os.getenv('MYSQL_HOST', '127.0.0.1'),
        'port': int(os.getenv('MYSQL_PORT', '3306')),
        'user': os.getenv('MYSQL_USER', 'weibo_api_reader'),
        'password': os.getenv('MYSQL_PASSWORD', ''),
        'database': os.getenv('MYSQL_DATABASE', 'weibo_comments'),
        'charset': 'utf8mb4',
    }

# 服务配置
SERVICE_HOST = os.getenv('SERVICE_HOST', '127.0.0.1')
SERVICE_PORT = int(os.getenv('PORT', '8000'))

# 缓存配置（秒）
CACHE_TTL = int(os.getenv('CACHE_TTL', '300'))

# 情感分析采样上限
SENTIMENT_MAX_SAMPLE = int(os.getenv('SENTIMENT_MAX_SAMPLE', '5000'))
