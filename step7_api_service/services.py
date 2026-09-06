#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
服务层（业务逻辑）
- 调用 database 层取数
- 调用 analysis_engine 做分析
- 提供内存缓存（TTL）
- 支持 dataset_type 数据集过滤（ai_industry / brand_monitor / general_hotspot）
"""
import time
from typing import Optional
from datetime import datetime, timedelta

from . import database as db
from . import analysis_engine as engine
from .config import CACHE_TTL

# 简单内存缓存: {cache_key: (timestamp, data)}
_cache = {}


def _get_cache(key):
    item = _cache.get(key)
    if item and time.time() - item[0] < CACHE_TTL:
        return item[1]
    return None


def _set_cache(key, data):
    _cache[key] = (time.time(), data)


def _ds_filter(dataset_type: Optional[str]) -> tuple:
    """生成 dataset_type 的 SQL 片段和参数
    返回 (sql_fragment, params_list)
    """
    if dataset_type:
        return (" AND dataset_type = %s", [dataset_type])
    return ("", [])


# ============================================================
# 1. 热点微博
# ============================================================

def get_hot_weibo(limit: int = 20, min_engagement: int = 0,
                   dataset_type: Optional[str] = None):
    cache_key = f'hot_weibo:{limit}:{min_engagement}:{dataset_type or "all"}'
    cached = _get_cache(cache_key)
    if cached:
        return cached

    ds_sql, ds_params = _ds_filter(dataset_type)
    sql = f"""
        SELECT weibo_id, user_id, username, content, publish_time,
               like_count, comment_count, repost_count, url
        FROM weibo_posts
        WHERE (like_count + comment_count + repost_count) >= %s
        {ds_sql}
        ORDER BY (like_count + comment_count + repost_count) DESC
        LIMIT %s
    """
    params = [min_engagement] + ds_params + [limit * 3]
    posts = db.fetch_all(sql, tuple(params))
    scored = engine.calc_hotspot(posts, top_n=limit)
    result = {"total": len(scored), "data": scored}
    _set_cache(cache_key, result)
    return result


# ============================================================
# 2. 关键词趋势
# ============================================================

def get_keyword_trend(keyword: str, days: int = 30,
                      dataset_type: Optional[str] = None):
    cache_key = f'keyword_trend:{keyword}:{days}:{dataset_type or "all"}'
    cached = _get_cache(cache_key)
    if cached:
        return cached

    like_pattern = f'%{keyword}%'
    cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

    # 帖子按日
    ds_sql, ds_params = _ds_filter(dataset_type)
    post_sql = f"""
        SELECT DATE(publish_time) AS date, COUNT(*) AS cnt
        FROM weibo_posts
        WHERE content LIKE %s AND publish_time >= %s
        {ds_sql}
        GROUP BY DATE(publish_time) ORDER BY date
    """
    post_params = [like_pattern, cutoff] + ds_params
    post_rows = db.fetch_all(post_sql, tuple(post_params))

    # 评论按日（需 JOIN weibo_posts 过滤 dataset_type）
    if dataset_type:
        comment_sql = """
            SELECT DATE(c.created_time) AS date, COUNT(*) AS cnt
            FROM weibo_comments c
            INNER JOIN weibo_posts p ON c.weibo_id = p.weibo_id
            WHERE c.content LIKE %s AND c.created_time >= %s
              AND p.dataset_type = %s
            GROUP BY DATE(c.created_time) ORDER BY date
        """
        comment_params = (like_pattern, cutoff, dataset_type)
    else:
        comment_sql = """
            SELECT DATE(created_time) AS date, COUNT(*) AS cnt
            FROM weibo_comments
            WHERE content LIKE %s AND created_time >= %s
            GROUP BY DATE(created_time) ORDER BY date
        """
        comment_params = (like_pattern, cutoff)
    comment_rows = db.fetch_all(comment_sql, comment_params)

    # 构造 posts/comments 列表供引擎处理
    posts = [{'publish_time': r['date'], 'content': keyword} for r in post_rows
             for _ in range(r['cnt'])]
    comments = [{'created_time': r['date'], 'content': keyword} for r in comment_rows
                for _ in range(r['cnt'])]

    result = engine.calc_keyword_trend(posts, comments, keyword, days)
    _set_cache(cache_key, result)
    return result


# ============================================================
# 3. 情感分析
# ============================================================

def get_sentiment(sample_size: int = 3000, keyword: str = None,
                  dataset_type: Optional[str] = None):
    cache_key = f'sentiment:{sample_size}:{keyword or "all"}:{dataset_type or "all"}'
    cached = _get_cache(cache_key)
    if cached:
        return cached

    # 评论需 JOIN weibo_posts 过滤 dataset_type
    if dataset_type:
        base_from = """
            FROM weibo_comments c
            INNER JOIN weibo_posts p ON c.weibo_id = p.weibo_id
            WHERE c.content IS NOT NULL AND c.content != ''
              AND p.dataset_type = %s
        """
        base_params = [dataset_type]
    else:
        base_from = """
            FROM weibo_comments c
            WHERE c.content IS NOT NULL AND c.content != ''
        """
        base_params = []

    if keyword:
        sql = f"""
            SELECT c.content, c.username, c.like_count, c.created_time
            {base_from}
              AND c.content LIKE %s
            ORDER BY c.created_time DESC
            LIMIT %s
        """
        params = tuple(base_params + [f'%{keyword}%', sample_size])
    else:
        sql = f"""
            SELECT c.content, c.username, c.like_count, c.created_time
            {base_from}
            ORDER BY c.created_time DESC
            LIMIT %s
        """
        params = tuple(base_params + [sample_size])

    comments = db.fetch_all(sql, params)

    result = engine.calc_sentiment(comments, sample_size=sample_size, keyword=keyword)
    _set_cache(cache_key, result)
    return result


# ============================================================
# 4. 用户影响力
# ============================================================

def get_influencers(sort_type: str = 'followers', limit: int = 20,
                    dataset_type: Optional[str] = None):
    cache_key = f'influencers:{sort_type}:{limit}:{dataset_type or "all"}'
    cached = _get_cache(cache_key)
    if cached:
        return cached

    # 取用户（粉丝排序不受 dataset_type 影响，因为 weibo_users 无 dataset_type）
    user_sql = """
        SELECT user_id, username, followers_count, following_count,
               weibo_count, verified, description
        FROM weibo_users
        ORDER BY followers_count DESC
        LIMIT %s
    """
    users = db.fetch_all(user_sql, (limit * 3,))

    # 取帖子用于互动聚合（按 dataset_type 过滤）
    ds_sql, ds_params = _ds_filter(dataset_type)
    if ds_sql:
        post_sql = f"""
            SELECT user_id, username, like_count, comment_count, repost_count
            FROM weibo_posts
            WHERE 1=1 {ds_sql}
        """
        posts = db.fetch_all(post_sql, tuple(ds_params))
        # 过滤 users：仅保留在该数据集中有帖子的用户
        post_user_ids = set(p['user_id'] for p in posts)
        users = [u for u in users if u['user_id'] in post_user_ids]
    else:
        post_sql = """
            SELECT user_id, username, like_count, comment_count, repost_count
            FROM weibo_posts
        """
        posts = db.fetch_all(post_sql)

    result = engine.calc_influencers(users, posts, sort_type=sort_type, top_n=limit)
    _set_cache(cache_key, result)
    return result


# ============================================================
# 5. 日报
# ============================================================

def get_daily_report(dataset_type: Optional[str] = None):
    cache_key = f'daily_report:{dataset_type or "all"}'
    cached = _get_cache(cache_key)
    if cached:
        return cached

    ds_sql, ds_params = _ds_filter(dataset_type)

    # 数据概览
    if dataset_type:
        posts_count = db.fetch_one(
            'SELECT COUNT(*) AS c FROM weibo_posts WHERE dataset_type = %s',
            (dataset_type,))['c']
    else:
        posts_count = db.fetch_one('SELECT COUNT(*) AS c FROM weibo_posts')['c']
    stats = {
        'posts': posts_count,
        'comments': db.fetch_one('SELECT COUNT(*) AS c FROM weibo_comments')['c'],
        'users': db.fetch_one('SELECT COUNT(*) AS c FROM weibo_users')['c'],
    }

    # 热点
    if dataset_type:
        hot_sql = f"""
            SELECT weibo_id, user_id, username, content, publish_time,
                   like_count, comment_count, repost_count, url
            FROM weibo_posts
            WHERE dataset_type = %s
            ORDER BY (like_count + comment_count + repost_count) DESC
            LIMIT 100
        """
        hot_posts = db.fetch_all(hot_sql, (dataset_type,))
    else:
        hot_posts = db.fetch_all("""
            SELECT weibo_id, user_id, username, content, publish_time,
                   like_count, comment_count, repost_count, url
            FROM weibo_posts
            ORDER BY (like_count + comment_count + repost_count) DESC
            LIMIT 100
        """)
    hotspot = engine.calc_hotspot(hot_posts, top_n=20)

    # 关键词（固定列表）
    keywords_list = ['豆包', '飞书', 'AI办公', 'Agent', '企业AI',
                     'ChatGPT', '人工智能', '大模型', 'AIGC']
    keywords = []
    for kw in keywords_list:
        if dataset_type:
            p = db.fetch_one(
                'SELECT COUNT(*) AS c FROM weibo_posts WHERE content LIKE %s AND dataset_type = %s',
                (f'%{kw}%', dataset_type))['c']
        else:
            p = db.fetch_one('SELECT COUNT(*) AS c FROM weibo_posts WHERE content LIKE %s',
                             (f'%{kw}%',))['c']
        c = db.fetch_one('SELECT COUNT(*) AS c FROM weibo_comments WHERE content LIKE %s',
                         (f'%{kw}%',))['c']
        keywords.append({'keyword': kw, 'post_mentions': p,
                         'comment_mentions': c, 'total_mentions': p + c})
    keywords.sort(key=lambda x: x['total_mentions'], reverse=True)

    # 情感（评论 JOIN 过滤 dataset_type）
    if dataset_type:
        comments = db.fetch_all("""
            SELECT c.content, c.username, c.like_count, c.created_time
            FROM weibo_comments c
            INNER JOIN weibo_posts p ON c.weibo_id = p.weibo_id
            WHERE c.content IS NOT NULL AND c.content != ''
              AND p.dataset_type = %s
            ORDER BY c.created_time DESC LIMIT 3000
        """, (dataset_type,))
    else:
        comments = db.fetch_all("""
            SELECT content, username, like_count, created_time
            FROM weibo_comments
            WHERE content IS NOT NULL AND content != ''
            ORDER BY created_time DESC LIMIT 3000
        """)
    sentiment = engine.calc_sentiment(comments, sample_size=3000)

    # 用户
    users = db.fetch_all("""
        SELECT user_id, username, followers_count, following_count,
               weibo_count, verified, description
        FROM weibo_users ORDER BY followers_count DESC LIMIT 100
    """)
    if dataset_type:
        all_posts = db.fetch_all(
            'SELECT user_id, username, like_count, comment_count, repost_count '
            'FROM weibo_posts WHERE dataset_type = %s',
            (dataset_type,))
        # 过滤 users：仅保留在该数据集中有帖子的用户
        post_user_ids = set(p['user_id'] for p in all_posts)
        users = [u for u in users if u['user_id'] in post_user_ids]
    else:
        all_posts = db.fetch_all("""
            SELECT user_id, username, like_count, comment_count, repost_count
            FROM weibo_posts
        """)
    influencers = engine.calc_influencers(users, all_posts, sort_type='followers', top_n=20)

    # 生成 Markdown
    md = engine.generate_daily_report(stats, hotspot, keywords, sentiment, influencers)

    result = {'format': 'markdown', 'content': md, 'generated_at': datetime.now()}
    _set_cache(cache_key, result)
    return result
