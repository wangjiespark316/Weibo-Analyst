#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一数据库连接模块（本地 MySQL + TiDB Cloud 通用）
=====================================================
支持两种连接方式：
1. 环境变量 DATABASE_URL（优先，云上部署用）
   格式: mysql://user:pass@host:port/dbname?ssl-mode=VERIFY_IDENTITY
2. 本地 db_config.ini（回退，本地开发用）

TiDB Cloud Serverless 强制 TLS，连接时自动启用 ssl。

用法:
    from cloud_db import get_connection, get_db_config

    # 获取连接（自动判断本地/云端）
    conn = get_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT 1")

    # 获取配置字典（用于 pymysql.connect(**config)）
    config = get_db_config()
"""
import os
import sys
import pymysql
from urllib.parse import urlparse, parse_qs


def _parse_database_url(url: str) -> dict:
    """
    解析 mysql://user:pass@host:port/dbname 格式连接串。
    返回 pymysql.connect() 可用的参数字典。
    """
    p = urlparse(url)
    query = parse_qs(p.query)

    config = {
        'host': p.hostname,
        'port': p.port or 4000,  # TiDB 默认 4000，MySQL 默认 3306
        'user': p.username,
        'password': p.password or '',
        'database': p.path.lstrip('/'),
        'charset': 'utf8mb4',
        'autocommit': True,
    }

    # TiDB Serverless 强制 TLS
    ssl_mode = query.get('ssl-mode', [''])[0].upper()
    is_tidb = 'tidbcloud' in (p.hostname or '') or 'tidb' in (p.hostname or '') or ssl_mode

    if is_tidb or ssl_mode in ('VERIFY_IDENTITY', 'VERIFY_CA', 'REQUIRED'):
        ca_path = os.getenv('TIDB_CA_PATH')
        if ca_path and os.path.exists(ca_path):
            config['ssl'] = {'ca': ca_path}
        else:
            # TiDB Serverless 使用系统 CA 即可，pymysql 会自动验证
            config['ssl'] = {'ssl_disabled': False}

    return config


def _load_local_config() -> dict:
    """
    从本地 db_config.ini 加载配置（回退方案）。
    """
    import configparser
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config_path = os.path.join(project_root, 'step2_comment_segmentation', 'db_config.ini')

    if not os.path.exists(config_path):
        raise FileNotFoundError(f"本地配置文件不存在: {config_path}")

    cp = configparser.ConfigParser()
    cp.read(config_path, encoding='utf-8')

    # 本地开发用 127.0.0.1 而非 host.docker.internal
    host = '127.0.0.1'

    return {
        'host': host,
        'port': int(cp.get('database', 'port', fallback='3306')),
        'user': cp.get('database', 'user'),
        'password': cp.get('database', 'password'),
        'database': cp.get('database', 'database', fallback='weibo_comments'),
        'charset': 'utf8mb4',
        'autocommit': True,
    }


def get_db_config() -> dict:
    """
    获取数据库配置字典。
    优先使用环境变量 DATABASE_URL，回退到本地 db_config.ini。
    """
    database_url = os.getenv('DATABASE_URL')
    if database_url:
        return _parse_database_url(database_url)
    return _load_local_config()


def get_connection():
    """
    获取数据库连接（pymysql Connection）。
    自动判断本地/云端，自动启用 TLS（TiDB）。
    """
    config = get_db_config()
    return pymysql.connect(**config)


def is_cloud() -> bool:
    """判断当前是否使用云端数据库（DATABASE_URL 已设置）"""
    return bool(os.getenv('DATABASE_URL'))


if __name__ == '__main__':
    # 自测：连接测试
    print("=== 数据库连接测试 ===")
    print(f"模式: {'云端 (DATABASE_URL)' if is_cloud() else '本地 (db_config.ini)'}")
    config = get_db_config()
    print(f"主机: {config['host']}:{config['port']}")
    print(f"数据库: {config['database']}")
    print(f"TLS: {'是' if 'ssl' in config else '否'}")
    print()

    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT VERSION()")
            version = cur.fetchone()[0]
            print(f"连接成功! 数据库版本: {version}")

            cur.execute("SHOW TABLES")
            tables = [row[0] for row in cur.fetchall()]
            print(f"表数量: {len(tables)}")
            for t in tables:
                cur.execute(f"SELECT COUNT(*) FROM `{t}`")
                count = cur.fetchone()[0]
                print(f"  {t}: {count} 行")
        conn.close()
    except Exception as e:
        print(f"连接失败: {type(e).__name__}: {e}")
        sys.exit(1)
