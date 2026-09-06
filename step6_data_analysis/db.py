#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数据库读取层
- 读取 weibo_posts / weibo_comments / weibo_users
- 只读，不修改数据库
"""
import os
import configparser
import pymysql


def get_db_config():
    """读取数据库配置，本地运行时覆盖 host 为 127.0.0.1"""
    config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'step2_comment_segmentation', 'db_config.ini'
    )
    cfg = configparser.ConfigParser()
    cfg.read(config_path)
    return {
        'host': '127.0.0.1',
        'port': int(cfg['database']['port']),
        'user': cfg['database']['user'],
        'password': cfg['database']['password'],
        'database': cfg['database']['database'],
        'charset': cfg['database']['charset'],
    }


def get_connection():
    return pymysql.connect(**get_db_config())


def fetch_all(sql, args=None):
    """执行查询并返回全部结果（DictCursor）"""
    conn = get_connection()
    try:
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute(sql, args)
            return cursor.fetchall()
    finally:
        conn.close()


def get_posts():
    """读取全部微博帖子"""
    return fetch_all("SELECT * FROM weibo_posts ORDER BY publish_time DESC")


def get_comments():
    """读取全部微博评论"""
    return fetch_all("SELECT * FROM weibo_comments ORDER BY created_time DESC")


def get_users():
    """读取全部用户"""
    return fetch_all("SELECT * FROM weibo_users ORDER BY followers_count DESC")


def get_stats():
    """获取数据库统计"""
    return {
        'posts': fetch_all("SELECT COUNT(*) AS cnt FROM weibo_posts")[0]['cnt'],
        'comments': fetch_all("SELECT COUNT(*) AS cnt FROM weibo_comments")[0]['cnt'],
        'users': fetch_all("SELECT COUNT(*) AS cnt FROM weibo_users")[0]['cnt'],
    }
