#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微博爬虫统一数据库连接层
========================
支持两种环境，自动切换：

1. 生产（TiDB Cloud，推荐）：
   环境变量 DATABASE_URL，格式：
     mysql://<user>:<password>@<host>:4000/<dbname>?ssl-mode=VERIFY_IDENTITY
   TiDB Serverless 强制 TLS，自动启用；如配置 TIDB_CA_PATH 则校验证书，
   否则使用系统 CA（pymysql 默认 TLS 协商）。

2. 开发（本地 MySQL）：
   优先读取 MYSQL_HOST / MYSQL_PORT / MYSQL_USER / MYSQL_PASSWORD / MYSQL_DATABASE
   环境变量；未设置时回退 step2_comment_segmentation/db_config.ini。

.env 文件加载：
   自动读取项目根目录 .env（也兼容 step1_comments_spider/.env、cloud_deploy/.env），
   不覆盖系统已存在的环境变量（与 python-dotenv 默认行为一致），无需额外依赖。

用法：
    from db_conn import get_connection, get_db_config, test_connection

    conn = get_connection()
    config = get_db_config()   # 用于 pymysql.connect(**config)
    report = test_connection() # 返回 模式/版本/表/行数，便于自检
"""
import os
import sys
from urllib.parse import urlparse, parse_qs

import pymysql

# ============================================================
# .env 文件加载（轻量实现，零依赖）
# ============================================================

# 候选 .env 路径：项目根优先，其次 step1 目录，最后 cloud_deploy
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ENV_CANDIDATES = [
    os.path.join(_PROJECT_ROOT, '.env'),
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'),
    os.path.join(_PROJECT_ROOT, 'cloud_deploy', '.env'),
]


def load_env_file(env_paths=None):
    """
    加载 .env 文件到环境变量。
    - 不覆盖已存在的环境变量（与 python-dotenv 默认一致）
    - 支持 KEY=VALUE、引号包裹的值、# 注释、空行
    """
    for path in env_paths or _ENV_CANDIDATES:
        if not path or not os.path.exists(path):
            continue
        try:
            with open(path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#') or '=' not in line:
                        continue
                    key, _, value = line.partition('=')
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    if key and os.getenv(key) is None:
                        os.environ[key] = value
        except OSError as e:
            print(f'[db_conn] 读取 .env 失败（{path}）: {e}')


# 模块加载时即尝试加载 .env（幂等）
load_env_file()


# ============================================================
# 连接配置解析
# ============================================================

def _parse_database_url(url: str) -> dict:
    """解析 mysql://user:pass@host:port/dbname 连接串（MySQL / TiDB 通用）"""
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
    # TiDB Cloud 强制 TLS；ssl-mode 显式要求 TLS 时同样启用
    is_tidb = 'tidb' in (p.hostname or '').lower()
    ssl_mode = query.get('ssl-mode', [''])[0].upper()
    if is_tidb or ssl_mode in ('VERIFY_IDENTITY', 'VERIFY_CA', 'REQUIRED'):
        ca_path = os.getenv('TIDB_CA_PATH')
        if ca_path and os.path.exists(ca_path):
            config['ssl'] = {'ca': ca_path}
        else:
            # 未提供 CA 时启用 TLS 但不做证书校验（与线上 API 行为一致）
            config['ssl'] = {}
    return config


def _load_local_config() -> dict:
    """本地 MySQL：优先 MYSQL_* 环境变量，回退 db_config.ini"""
    ini_path = os.path.join(_PROJECT_ROOT, 'step2_comment_segmentation', 'db_config.ini')
    if os.path.exists(ini_path):
        import configparser
        cp = configparser.ConfigParser()
        cp.read(ini_path, encoding='utf-8')
        ini_cfg = cp['database'] if cp.has_section('database') else {}
    else:
        ini_cfg = {}

    return {
        'host': os.getenv('MYSQL_HOST', ini_cfg.get('host', '127.0.0.1')),
        'port': int(os.getenv('MYSQL_PORT', ini_cfg.get('port', '3306'))),
        'user': os.getenv('MYSQL_USER', ini_cfg.get('user', 'root')),
        'password': os.getenv('MYSQL_PASSWORD', ini_cfg.get('password', '')),
        'database': os.getenv('MYSQL_DATABASE', ini_cfg.get('database', 'weibo_comments')),
        'charset': 'utf8mb4',
        'autocommit': True,
    }


def get_db_config() -> dict:
    """
    获取数据库配置字典（pymysql.connect(**config) 可用）。

    优先级：
      1. DATABASE_URL（生产：TiDB Cloud）
      2. MYSQL_* 环境变量 / db_config.ini（开发：本地 MySQL）
    """
    database_url = os.getenv('DATABASE_URL')
    if database_url:
        return _parse_database_url(database_url)
    return _load_local_config()


def get_connection():
    """获取数据库连接（自动识别生产 TiDB / 本地 MySQL）"""
    return pymysql.connect(**get_db_config())


def db_mode() -> str:
    """当前数据库模式：cloud（TiDB）/ local（MySQL）"""
    return 'cloud' if os.getenv('DATABASE_URL') else 'local'


# ============================================================
# 自检与统计（只读）
# ============================================================

def test_connection() -> dict:
    """连接自检：返回模式、数据库版本、表列表与行数（只读，失败抛异常）"""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT VERSION()")
            version = cur.fetchone()[0]
            cur.execute("SHOW TABLES")
            tables = [row[0] for row in cur.fetchall()]
            counts = {}
            for t in tables:
                cur.execute(f"SELECT COUNT(*) FROM `{t}`")
                counts[t] = cur.fetchone()[0]
        return {
            'mode': db_mode(),
            'version': version,
            'tables': tables,
            'counts': counts,
        }
    finally:
        conn.close()


def table_counts() -> dict:
    """三张核心表行数（用于采集后验证写入）"""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            counts = {}
            for t in ('weibo_posts', 'weibo_comments', 'weibo_users'):
                cur.execute(f"SELECT COUNT(*) FROM `{t}`")
                counts[t] = cur.fetchone()[0]
            return counts
    finally:
        conn.close()


if __name__ == '__main__':
    print('=== 微博爬虫数据库连接自检 ===')
    print(f'模式: {"云端 TiDB (DATABASE_URL)" if db_mode() == "cloud" else "本地 MySQL"}')
    config = get_db_config()
    print(f"主机: {config['host']}:{config['port']}")
    print(f"数据库: {config['database']}")
    print(f"TLS: {'启用' if 'ssl' in config else '未启用'}")
    print()
    try:
        report = test_connection()
        print(f'连接成功! 数据库版本: {report["version"]}')
        print(f'表数量: {len(report["tables"])}')
        for t in report['tables']:
            print(f'  {t}: {report["counts"][t]} 行')
    except Exception as e:
        print(f'连接失败: {type(e).__name__}: {e}')
        sys.exit(1)
