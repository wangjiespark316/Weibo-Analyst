#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库连接层（只读）
- 本地：使用 weibo_api_reader 只读账号
- 云端：优先使用 DATABASE_URL 环境变量（TiDB Cloud，自动 TLS）
- 只提供 SELECT 查询，不提供任何写操作
"""
import os
import pymysql
from pymysql.cursors import DictCursor
from urllib.parse import urlparse, parse_qs
from .config import DB_CONFIG


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
        'autocommit': True,
    }
    # TiDB Serverless 强制 TLS
    is_tidb = 'tidb' in (p.hostname or '').lower()
    ssl_mode = query.get('ssl-mode', [''])[0].upper()
    if is_tidb or ssl_mode in ('VERIFY_IDENTITY', 'VERIFY_CA', 'REQUIRED'):
        ca_path = os.getenv('TIDB_CA_PATH')
        if ca_path and os.path.exists(ca_path):
            config['ssl'] = {'ca': ca_path}
        else:
            config['ssl'] = {'ssl_disabled': False}
    return config


def get_db_config() -> dict:
    """获取数据库配置：优先 DATABASE_URL（云端），回退本地只读账号"""
    database_url = os.getenv('DATABASE_URL')
    if database_url:
        return _parse_database_url(database_url)
    return DB_CONFIG


def get_connection():
    """获取数据库连接（只读）"""
    return pymysql.connect(**get_db_config())


def fetch_all(sql, args=None):
    """执行 SELECT 查询，返回全部结果（DictCursor）"""
    conn = get_connection()
    try:
        with conn.cursor(DictCursor) as cursor:
            cursor.execute(sql, args)
            return cursor.fetchall()
    finally:
        conn.close()


def fetch_one(sql, args=None):
    """执行 SELECT 查询，返回单条结果"""
    conn = get_connection()
    try:
        with conn.cursor(DictCursor) as cursor:
            cursor.execute(sql, args)
            return cursor.fetchone()
    finally:
        conn.close()
