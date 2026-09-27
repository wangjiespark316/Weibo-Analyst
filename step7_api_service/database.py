#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库连接层（只读）
- 本地：使用 weibo_api_reader 只读账号
- 云端：优先使用 DATABASE_URL 环境变量（TiDB Cloud，自动 TLS）
- 只提供 SELECT 查询，不提供任何写操作
- 进程级连接池（DBUtils.PooledDB）：复用 TiDB 公网 TLS 连接，
  避免“每个请求都重新做一次公网 TLS 握手”的高延迟。
"""
import os
import threading
import pymysql
from pymysql.cursors import DictCursor
from urllib.parse import urlparse, parse_qs
from .config import DB_CONFIG

try:
    from DBUtils.PooledDB import PooledDB
    _HAS_POOL = True
except Exception:  # 环境缺少 DBUtils 时安全回退为直连
    PooledDB = None
    _HAS_POOL = False

# 进程级连接池单例（uvicorn 单 worker 多线程，模块全局池即可）
_pool = None
_pool_lock = threading.Lock()


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


def _build_pool():
    """构建进程级连接池。

    - mincached/maxcached：常驻与空闲连接数，省掉首请求握手
    - maxshared=0：不使用共享连接，保证多线程/会话安全
    - maxconnections + blocking=True：池满时排队等待而非报错
    - ping=1：连接借出前先 ping，TiDB Serverless 空闲断连可自动重建
    - reset=True：连接归还时回滚未提交事务（本层只读，属防御性措施）
    """
    cfg = dict(get_db_config())
    # 在线路由统一按字典游标取数；fetch_all/fetch_one 仍显式指定 DictCursor。
    cfg['cursorclass'] = DictCursor
    return PooledDB(
        pymysql,
        mincached=2,
        maxcached=10,
        maxshared=0,
        maxconnections=32,
        blocking=True,
        reset=True,
        ping=1,
        **cfg,
    )


def _get_pool():
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = _build_pool()
    return _pool


def get_connection():
    """获取数据库连接（只读）。

    有连接池时借出一条池化连接，调用 close() 会归还连接池而非真正断开；
    无 DBUtils 时回退为每次新建直连。
    """
    if _HAS_POOL:
        return _get_pool().connection()
    return pymysql.connect(**get_db_config())


def fetch_all(sql, args=None):
    """执行 SELECT 查询，返回全部结果（DictCursor）

    注意：DBUtils 1.2 的池化游标不支持 ``with`` 上下文协议，这里显式管理
    游标生命周期；``conn.close()`` 在池化模式下是归还连接而非断开。
    """
    conn = get_connection()
    try:
        cursor = conn.cursor(DictCursor)
        try:
            cursor.execute(sql, args)
            return cursor.fetchall()
        finally:
            cursor.close()
    finally:
        conn.close()


def fetch_one(sql, args=None):
    """执行 SELECT 查询，返回单条结果"""
    conn = get_connection()
    try:
        cursor = conn.cursor(DictCursor)
        try:
            cursor.execute(sql, args)
            return cursor.fetchone()
        finally:
            cursor.close()
    finally:
        conn.close()
