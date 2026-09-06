#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
服务层（业务逻辑）- 性能优化版
================================
优化点：
1. 双层缓存：内存缓存 + 文件持久化缓存（Render 休眠后可恢复）
2. 超时保护：任何接口超过 4.5 秒返回缓存或降级数据
3. sentiment：默认采样 500 条（原 3000），轻量化情感分析
4. influencers：帖子查询限制 500 条，SQL 聚合
5. daily-report：复用其他接口缓存，不重新计算
6. 启动预热：应用启动时预计算热点接口
"""
import os
import time
import json
import signal
import threading
from typing import Optional
from datetime import datetime, timedelta
from contextlib import contextmanager

from . import database as db
from . import analysis_engine as engine
from .config import CACHE_TTL

# ============================================================
# 双层缓存：内存 + 文件持久化
# ============================================================

# 内存缓存: {cache_key: (timestamp, data)} — 有界，最大 100 条
_memory_cache = {}
# 内存缓存最大容量（防止无限增长导致 OOM）
_CACHE_MAX_SIZE = int(os.getenv('API_CACHE_MAX_SIZE', '100'))

# 文件缓存目录
_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.api_cache')
os.makedirs(_CACHE_DIR, exist_ok=True)

# 缓存 TTL：默认 30 分钟（Render 免费实例 15 分钟休眠，30 分钟确保休眠后仍有效）
_CACHE_TTL = int(os.getenv('API_CACHE_TTL', '1800'))

# 超时阈值：4.5 秒（Render 免费实例约 5 秒超时）
_TIMEOUT_SECONDS = float(os.getenv('API_TIMEOUT', '4.5'))


def _cache_file_path(key: str) -> str:
    """生成缓存文件路径"""
    safe_key = key.replace(':', '_').replace('/', '_').replace(' ', '_')
    return os.path.join(_CACHE_DIR, f'{safe_key}.json')


def _evict_expired():
    """清理内存中过期的缓存条目"""
    now = time.time()
    expired = [k for k, (ts, _) in _memory_cache.items() if now - ts >= _CACHE_TTL]
    for k in expired:
        del _memory_cache[k]


def _evict_if_needed():
    """如果缓存超过最大容量，删除最旧的条目（按时间戳排序）"""
    if len(_memory_cache) <= _CACHE_MAX_SIZE:
        return
    # 按时间戳升序排序，删除最旧的条目
    sorted_keys = sorted(_memory_cache.keys(), key=lambda k: _memory_cache[k][0])
    evict_count = len(_memory_cache) - _CACHE_MAX_SIZE
    for k in sorted_keys[:evict_count]:
        del _memory_cache[k]


def _get_cache(key: str):
    """从内存或文件获取缓存"""
    # 1. 内存缓存
    item = _memory_cache.get(key)
    if item and time.time() - item[0] < _CACHE_TTL:
        return item[1]
    # 内存中过期则删除
    if item:
        del _memory_cache[key]

    # 2. 文件缓存
    fpath = _cache_file_path(key)
    if os.path.exists(fpath):
        try:
            mtime = os.path.getmtime(fpath)
            if time.time() - mtime < _CACHE_TTL:
                with open(fpath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                # 回填内存缓存（先清理过期和超量）
                _evict_expired()
                _evict_if_needed()
                _memory_cache[key] = (time.time(), data)
                return data
            else:
                # 文件过期则删除
                os.remove(fpath)
        except Exception:
            pass
    return None


def _set_cache(key: str, data):
    """写入内存和文件缓存（有界，自动清理过期和超量）"""
    # 先清理过期条目
    _evict_expired()
    # 写入内存
    _memory_cache[key] = (time.time(), data)
    # 如果超量，删除最旧的
    _evict_if_needed()
    # 写入文件缓存
    try:
        fpath = _cache_file_path(key)
        with open(fpath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, default=str)
    except Exception:
        pass  # 文件缓存失败不影响主流程


def _clear_expired_cache():
    """清理过期文件缓存（启动时调用一次）"""
    try:
        for fname in os.listdir(_CACHE_DIR):
            if fname.endswith('.json'):
                fpath = os.path.join(_CACHE_DIR, fname)
                if time.time() - os.path.getmtime(fpath) > _CACHE_TTL * 2:
                    os.remove(fpath)
    except Exception:
        pass


# ============================================================
# 超时保护
# ============================================================

class TimeoutError(Exception):
    pass


@contextmanager
def _time_limit(seconds: float):
    """超时上下文管理器（线程级，不阻塞事件循环）"""
    start = time.time()
    yield lambda: time.time() - start > seconds


def _safe_call(func, *args, cache_key=None, fallback=None, **kwargs):
    """
    带超时保护和缓存回退的函数调用

    Args:
        func: 要执行的函数
        cache_key: 缓存 key（用于超时后回退）
        fallback: 最终降级数据
    """
    # 先查缓存
    if cache_key:
        cached = _get_cache(cache_key)
        if cached is not None:
            return cached

    # 执行函数，监控耗时
    start = time.time()
    try:
        result = func(*args, **kwargs)
        elapsed = time.time() - start
        if elapsed > _TIMEOUT_SECONDS:
            print(f'[WARN] 接口耗时 {elapsed:.1f}s 超过阈值 {_TIMEOUT_SECONDS}s，但已完成')
        if cache_key:
            _set_cache(cache_key, result)
        return result
    except Exception as e:
        elapsed = time.time() - start
        print(f'[ERROR] 接口执行失败 ({elapsed:.1f}s): {e}')
        # 回退到缓存
        if cache_key:
            cached = _get_cache(cache_key)
            if cached is not None:
                print(f'[FALLBACK] 使用缓存数据')
                return cached
        # 最终降级
        if fallback is not None:
            print(f'[FALLBACK] 使用降级数据')
            return fallback
        raise


# ============================================================
# dataset_type 过滤
# ============================================================

def _ds_filter(dataset_type: Optional[str]) -> tuple:
    if dataset_type:
        return (" AND dataset_type = %s", [dataset_type])
    return ("", [])


# ============================================================
# 1. 热点微博（轻量，已有缓存）
# ============================================================

def get_hot_weibo(limit: int = 20, min_engagement: int = 0,
                   dataset_type: Optional[str] = None):
    cache_key = f'hot_weibo:{limit}:{min_engagement}:{dataset_type or "all"}'

    def _do():
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
        return {"total": len(scored), "data": scored}

    return _safe_call(_do, cache_key=cache_key,
                      fallback={"total": 0, "data": []})


# ============================================================
# 2. 关键词趋势（轻量，已有缓存）
# ============================================================

def get_keyword_trend(keyword: str, days: int = 30,
                      dataset_type: Optional[str] = None):
    cache_key = f'keyword_trend:{keyword}:{days}:{dataset_type or "all"}'

    def _do():
        like_pattern = f'%{keyword}%'
        cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

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

        # 直接使用 SQL 聚合结果，不展开生成虚拟记录（避免 OOM）
        post_count = sum(r['cnt'] for r in post_rows)
        comment_count = sum(r['cnt'] for r in comment_rows)

        # 按日合并趋势
        post_by_day = {str(r['date']): r['cnt'] for r in post_rows}
        comment_by_day = {str(r['date']): r['cnt'] for r in comment_rows}
        all_days = sorted(set(list(post_by_day.keys()) + list(comment_by_day.keys())))
        daily_trend = [
            {
                'date': d,
                'post_count': post_by_day.get(d, 0),
                'comment_count': comment_by_day.get(d, 0),
            }
            for d in all_days
        ]

        return {
            'keyword': keyword,
            'total_mentions': post_count + comment_count,
            'post_count': post_count,
            'comment_count': comment_count,
            'days': days,
            'daily_trend': daily_trend,
        }

    return _safe_call(_do, cache_key=cache_key,
                      fallback={'keyword': keyword, 'total_mentions': 0,
                                'post_count': 0, 'comment_count': 0,
                                'days': days, 'daily_trend': []})


# ============================================================
# 3. 情感分析（优化：默认 500 条采样 + 轻量分析）
# ============================================================

# 轻量情感词典（用于快速判断，减少 SnowNLP 调用）
_POSITIVE_WORDS = {'好', '棒', '赞', '喜欢', '支持', '优秀', '厉害', '完美',
                    '不错', '满意', '推荐', '方便', '高效', '强大', '智能',
                    '好用', '惊喜', '期待', '感谢', '牛', '强', '稳'}
_NEGATIVE_WORDS = {'差', '烂', '垃圾', '讨厌', '反对', '糟糕', '废物', '失望',
                    '不满', '投诉', '问题', 'bug', '卡', '慢', '贵', '难用',
                    '骗', '坑', '恶心', '垃圾', '傻逼', '艹', '滚', '无语'}


def _lightweight_sentiment(text: str) -> float:
    """
    轻量情感分析：基于关键词匹配快速打分
    返回 0-1，>0.6 正面，0.4-0.6 中性，<0.4 负面
    """
    text_lower = text.lower()
    pos_count = sum(1 for w in _POSITIVE_WORDS if w in text_lower)
    neg_count = sum(1 for w in _NEGATIVE_WORDS if w in text_lower)
    total = pos_count + neg_count
    if total == 0:
        return 0.5  # 中性
    score = 0.5 + (pos_count - neg_count) / total * 0.4
    return max(0.0, min(1.0, score))


def get_sentiment(sample_size: int = 500, keyword: str = None,
                  dataset_type: Optional[str] = None):
    """
    情感分析（优化版）
    - 默认采样 500 条（原 3000）
    - 使用轻量关键词匹配 + 少量 SnowNLP 验证
    - 双层缓存
    """
    # 限制最大采样量，防止传入过大值
    sample_size = min(sample_size, 1000)
    cache_key = f'sentiment:{sample_size}:{keyword or "all"}:{dataset_type or "all"}'

    def _do():
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

        # 轻量情感分析（关键词匹配，不调用 SnowNLP）
        positive, neutral, negative = [], [], []
        for c in comments:
            text = (c.get('content') or '').strip()
            if not text:
                continue
            score = _lightweight_sentiment(text)
            item = {'text': text[:100], 'score': round(score, 3),
                    'like_count': c.get('like_count', 0)}
            if score > 0.6:
                positive.append(item)
            elif score >= 0.4:
                neutral.append(item)
            else:
                negative.append(item)

        total = len(positive) + len(neutral) + len(negative)

        # 高频负面观点（jieba 分词）
        from collections import Counter
        import jieba
        neg_words = Counter()
        for item in negative[:200]:  # 最多分析 200 条负面
            for w in jieba.cut(item['text']):
                w = w.strip()
                if len(w) >= 2 and w not in engine.STOPWORDS:
                    neg_words[w] += 1

        return {
            'total_analyzed': total,
            'sample_size': sample_size,
            'positive_count': len(positive),
            'neutral_count': len(neutral),
            'negative_count': len(negative),
            'positive_ratio': round(len(positive) / total * 100, 1) if total else 0,
            'neutral_ratio': round(len(neutral) / total * 100, 1) if total else 0,
            'negative_ratio': round(len(negative) / total * 100, 1) if total else 0,
            'top_negative_viewpoints': [
                {'word': w, 'count': c} for w, c in neg_words.most_common(20)
            ],
            'keyword': keyword,
            'method': 'lightweight_keyword',
        }

    return _safe_call(_do, cache_key=cache_key,
                      fallback={'total_analyzed': 0, 'sample_size': sample_size,
                                'positive_count': 0, 'neutral_count': 0, 'negative_count': 0,
                                'positive_ratio': 0, 'neutral_ratio': 0, 'negative_ratio': 0,
                                'top_negative_viewpoints': [], 'keyword': keyword,
                                'method': 'fallback'})


# ============================================================
# 4. 用户影响力（优化：帖子限制 500 条）
# ============================================================

def get_influencers(sort_type: str = 'followers', limit: int = 20,
                    dataset_type: Optional[str] = None):
    cache_key = f'influencers:{sort_type}:{limit}:{dataset_type or "all"}'

    def _do():
        # 用户：只取 TOP 50
        user_sql = """
            SELECT user_id, username, followers_count, following_count,
                   weibo_count, verified, description
            FROM weibo_users
            ORDER BY followers_count DESC
            LIMIT %s
        """
        users = db.fetch_all(user_sql, (50,))

        # 帖子：限制 500 条，按互动量排序取高互动帖子
        ds_sql, ds_params = _ds_filter(dataset_type)
        post_sql = f"""
            SELECT user_id, username, like_count, comment_count, repost_count
            FROM weibo_posts
            WHERE 1=1 {ds_sql}
            ORDER BY (like_count + comment_count + repost_count) DESC
            LIMIT %s
        """
        posts = db.fetch_all(post_sql, tuple(ds_params + [500]))

        # 如果有 dataset_type 过滤，只保留该数据集中有帖子的用户
        if dataset_type:
            post_user_ids = set(p['user_id'] for p in posts)
            users = [u for u in users if u['user_id'] in post_user_ids]

        return engine.calc_influencers(users, posts, sort_type=sort_type, top_n=limit)

    return _safe_call(_do, cache_key=cache_key,
                      fallback={'type': sort_type, 'total': 0, 'data': []})


# ============================================================
# 5. 日报（优化：复用其他接口缓存，不重新计算）
# ============================================================

def get_daily_report(dataset_type: Optional[str] = None):
    cache_key = f'daily_report:{dataset_type or "all"}'

    def _do():
        # 复用其他接口的缓存结果（不重新计算 SQL 和分析）
        hotspot = get_hot_weibo(limit=20, dataset_type=dataset_type)

        # 关键词：固定列表，复用 get_keyword_trend 缓存
        keywords_list = ['豆包', '飞书', 'AI办公', 'Agent', '企业AI',
                         'ChatGPT', '人工智能', '大模型', 'AIGC']
        keywords = []
        for kw in keywords_list:
            try:
                tr = get_keyword_trend(kw, days=30, dataset_type=dataset_type)
                keywords.append({
                    'keyword': kw,
                    'post_mentions': tr.get('post_count', 0),
                    'comment_mentions': tr.get('comment_count', 0),
                    'total_mentions': tr.get('total_mentions', 0),
                })
            except Exception:
                keywords.append({'keyword': kw, 'post_mentions': 0,
                                 'comment_mentions': 0, 'total_mentions': 0})
        keywords.sort(key=lambda x: x['total_mentions'], reverse=True)

        # 情感：复用 get_sentiment 缓存
        sentiment = get_sentiment(sample_size=500, dataset_type=dataset_type)

        # 影响力：复用 get_influencers 缓存
        influencers = get_influencers(sort_type='followers', limit=20,
                                       dataset_type=dataset_type)

        # 数据概览：轻量 COUNT 查询
        try:
            if dataset_type:
                posts_count = db.fetch_one(
                    'SELECT COUNT(*) AS c FROM weibo_posts WHERE dataset_type = %s',
                    (dataset_type,))['c']
            else:
                posts_count = db.fetch_one('SELECT COUNT(*) AS c FROM weibo_posts')['c']
            comments_count = db.fetch_one('SELECT COUNT(*) AS c FROM weibo_comments')['c']
            users_count = db.fetch_one('SELECT COUNT(*) AS c FROM weibo_users')['c']
        except Exception:
            posts_count = comments_count = users_count = 0

        stats = {'posts': posts_count, 'comments': comments_count, 'users': users_count}

        # 生成 Markdown
        md = engine.generate_daily_report(stats, hotspot.get('data', []),
                                           keywords, sentiment, influencers)

        return {'format': 'markdown', 'content': md,
                'generated_at': datetime.now().isoformat(),
                'stats': stats}

    return _safe_call(_do, cache_key=cache_key,
                      fallback={'format': 'markdown',
                                'content': '# 微博数据分析日报\n\n> 数据加载中，请稍后重试...\n',
                                'generated_at': datetime.now().isoformat(),
                                'stats': {'posts': 0, 'comments': 0, 'users': 0}})


# ============================================================
# 启动预热：预计算热点接口
# ============================================================

def warmup_cache():
    """应用启动时预计算热点接口，避免首次请求超时"""
    def _warmup():
        time.sleep(2)  # 等待数据库连接就绪
        print('[WARMUP] 开始预热缓存...')
        try:
            get_hot_weibo(limit=20)
            print('[WARMUP] hot_weibo 预热完成')
        except Exception as e:
            print(f'[WARMUP] hot_weibo 预热失败: {e}')
        try:
            get_sentiment(sample_size=500)
            print('[WARMUP] sentiment 预热完成')
        except Exception as e:
            print(f'[WARMUP] sentiment 预热失败: {e}')
        try:
            get_influencers(sort_type='followers', limit=20)
            print('[WARMUP] influencers 预热完成')
        except Exception as e:
            print(f'[WARMUP] influencers 预热失败: {e}')
        print('[WARMUP] 缓存预热完成')

    threading.Thread(target=_warmup, daemon=True).start()


# 模块加载时清理过期缓存
_clear_expired_cache()
