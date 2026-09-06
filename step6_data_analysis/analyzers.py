#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分析引擎
- 热点分析：点赞/评论/转发加权排行
- 关键词趋势：关键词出现频率
- 情感分析：SnowNLP 正面/中性/负面 + 高频负面观点
- 用户影响力：高粉丝用户 + 高互动用户
"""
import math
import random
from collections import Counter

from snownlp import SnowNLP
import jieba

# 停用词表（用于负面观点提取）
STOPWORDS = set('''
的 了 是 在 我 有 和 就 不 人 都 一 上 也 很 到 说 要 去 你 会 着 没 有 看 好 自己 这 那 他 她 它 们 什么 怎么 这个 那个 因为 所以 如果 但是 然后 还是 或者 就是 这样 那样 吧 呢 啊 哦 嗯 啦 呀 嘛 哈 呵 的话 一些 一下 一样 一直 一般 一定 一个 没有 不是 不会 不能 不要 真的 觉得 知道 现在 今天 昨天 明天 可以 可能 应该 已经 还是 还有 还是 还是 这个 那个 这些 那些 这样 那样 怎么 什么 为什么 怎么样 哪 哪里 哪个 谁 多少 几 啊 呀 吧 呢 嘛 哦 哈 嗯 啦 哎 唉 哇 噢 唔 嗯
'''.split())


# ============================================================
# 1. 热点分析
# ============================================================

def hotspot_analysis(posts, top_n=20):
    """
    热点分析：log 归一化后加权点赞(0.4)/评论(0.3)/转发(0.3)
    返回 top_n 条热点微博，含 hotspot_score 字段
    """
    if not posts:
        return []

    scored = []
    for p in posts:
        log_like = math.log1p(p.get('like_count', 0) or 0)
        log_comment = math.log1p(p.get('comment_count', 0) or 0)
        log_repost = math.log1p(p.get('repost_count', 0) or 0)
        item = dict(p)
        item['_log_like'] = log_like
        item['_log_comment'] = log_comment
        item['_log_repost'] = log_repost
        scored.append(item)

    max_like = max(p['_log_like'] for p in scored) or 1
    max_comment = max(p['_log_comment'] for p in scored) or 1
    max_repost = max(p['_log_repost'] for p in scored) or 1

    for p in scored:
        score = (
            0.4 * (p['_log_like'] / max_like) +
            0.3 * (p['_log_comment'] / max_comment) +
            0.3 * (p['_log_repost'] / max_repost)
        )
        p['hotspot_score'] = round(score * 100, 2)
        del p['_log_like'], p['_log_comment'], p['_log_repost']

    ranked = sorted(scored, key=lambda x: x['hotspot_score'], reverse=True)
    return ranked[:top_n]


# ============================================================
# 2. 关键词趋势分析
# ============================================================

def keyword_trend(posts, comments, keywords):
    """
    统计关键词在帖子和评论中的出现频率
    返回按总提及数降序排列的列表
    """
    results = []
    for kw in keywords:
        post_mentions = sum(1 for p in posts if kw in (p.get('content') or ''))
        comment_mentions = sum(1 for c in comments if kw in (c.get('content') or ''))
        results.append({
            'keyword': kw,
            'post_mentions': post_mentions,
            'comment_mentions': comment_mentions,
            'total_mentions': post_mentions + comment_mentions,
        })
    return sorted(results, key=lambda x: x['total_mentions'], reverse=True)


# ============================================================
# 3. 评论情感分析
# ============================================================

def sentiment_analysis(comments, sample_size=3000):
    """
    SnowNLP 情感分析
    - 正面: score > 0.6
    - 中性: 0.4 <= score <= 0.6
    - 负面: score < 0.4
    - 高频负面观点: jieba 分词 + 词频
    """
    # 采样（避免全量太慢）
    if sample_size and len(comments) > sample_size:
        sample = random.sample(comments, sample_size)
    else:
        sample = comments

    positive = []
    neutral = []
    negative = []

    for c in sample:
        text = (c.get('content') or '').strip()
        if not text:
            continue
        try:
            score = SnowNLP(text).sentiments
        except Exception:
            score = 0.5

        item = {
            'text': text,
            'score': round(score, 3),
            'like_count': c.get('like_count', 0),
            'username': c.get('username', ''),
        }
        if score > 0.6:
            positive.append(item)
        elif score >= 0.4:
            neutral.append(item)
        else:
            negative.append(item)

    total = len(positive) + len(neutral) + len(negative)

    # 高频负面观点：jieba 分词 + 词频统计
    negative_words = Counter()
    for item in negative:
        for w in jieba.cut(item['text']):
            w = w.strip()
            if len(w) >= 2 and w not in STOPWORDS:
                negative_words[w] += 1

    top_negative = negative_words.most_common(20)

    # 高赞负面评论（有参考价值）
    top_negative_by_likes = sorted(negative, key=lambda x: x['like_count'], reverse=True)[:10]

    return {
        'total_analyzed': total,
        'sample_size': sample_size,
        'positive_count': len(positive),
        'neutral_count': len(neutral),
        'negative_count': len(negative),
        'positive_ratio': round(len(positive) / total * 100, 1) if total else 0,
        'neutral_ratio': round(len(neutral) / total * 100, 1) if total else 0,
        'negative_ratio': round(len(negative) / total * 100, 1) if total else 0,
        'top_negative_viewpoints': top_negative,
        'top_negative_comments': [
            {'text': n['text'][:100], 'like_count': n['like_count'], 'username': n['username']}
            for n in top_negative_by_likes
        ],
    }


# ============================================================
# 4. 用户影响力分析
# ============================================================

def user_influence(users, posts, top_n=20):
    """
    用户影响力：高粉丝用户 + 高互动用户
    高互动 = 该用户所有帖子的点赞+评论+转发总和
    """
    # 高粉丝用户
    top_followers = sorted(
        users, key=lambda x: x.get('followers_count', 0) or 0, reverse=True
    )[:top_n]

    # 按用户聚合互动量
    engagement = {}
    for p in posts:
        uid = p.get('user_id')
        if not uid:
            continue
        if uid not in engagement:
            engagement[uid] = {
                'user_id': uid,
                'username': p.get('username', ''),
                'post_count': 0,
                'total_likes': 0,
                'total_comments': 0,
                'total_reposts': 0,
                'total_engagement': 0,
            }
        e = engagement[uid]
        e['post_count'] += 1
        e['total_likes'] += p.get('like_count', 0) or 0
        e['total_comments'] += p.get('comment_count', 0) or 0
        e['total_reposts'] += p.get('repost_count', 0) or 0
        e['total_engagement'] = e['total_likes'] + e['total_comments'] + e['total_reposts']

    top_engagement = sorted(
        engagement.values(), key=lambda x: x['total_engagement'], reverse=True
    )[:top_n]

    return {
        'top_followers': top_followers,
        'top_engagement': top_engagement,
    }
