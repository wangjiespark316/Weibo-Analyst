#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
分析引擎（独立模块，不依赖 step6）
- 热点分析：log 归一化 + 加权点赞/评论/转发
- 关键词趋势：出现频率 + 按日统计
- 情感分析：SnowNLP 正面/中性/负面 + 高频负面观点
- 用户影响力：高粉丝 + 高互动
- 日报生成：Markdown

输入：数据库查询结果（list[dict]）
输出：分析结果（dict / list[dict]）
"""
import math
import random
from collections import Counter
from datetime import datetime

from snownlp import SnowNLP
import jieba

# 停用词
STOPWORDS = set('''
的 了 是 在 我 有 和 就 不 人 都 一 上 也 很 到 说 要 去 你 会 着 没 有 看 好 自己 这 那 他 她 它 们 什么 怎么 这个 那个 因为 所以 如果 但是 然后 还是 或者 就是 这样 那样 吧 呢 啊 哦 嗯 啦 呀 嘛 哈 呵 的话 一些 一下 一样 一直 一般 一定 一个 没有 不是 不会 不能 不要 真的 觉得 知道 现在 今天 昨天 明天 可以 可能 应该 已经 这些 那些 怎么 什么 为什么 怎么样 哪 哪里 哪个 谁 多少 几
'''.split())


# ============================================================
# 1. 热点分析
# ============================================================

def calc_hotspot(posts: list, top_n: int = 20) -> list:
    """
    热点指数：log 归一化后加权 0.4×点赞 + 0.3×评论 + 0.3×转发
    """
    if not posts:
        return []

    scored = []
    for p in posts:
        item = dict(p)
        item['_ll'] = math.log1p(p.get('like_count', 0) or 0)
        item['_lc'] = math.log1p(p.get('comment_count', 0) or 0)
        item['_lr'] = math.log1p(p.get('repost_count', 0) or 0)
        scored.append(item)

    max_ll = max(p['_ll'] for p in scored) or 1
    max_lc = max(p['_lc'] for p in scored) or 1
    max_lr = max(p['_lr'] for p in scored) or 1

    for p in scored:
        score = (0.4 * p['_ll'] / max_ll +
                 0.3 * p['_lc'] / max_lc +
                 0.3 * p['_lr'] / max_lr)
        p['hotspot_score'] = round(score * 100, 2)
        for k in ('_ll', '_lc', '_lr'):
            del p[k]

    return sorted(scored, key=lambda x: x['hotspot_score'], reverse=True)[:top_n]


# ============================================================
# 2. 关键词趋势
# ============================================================

def calc_keyword_trend(posts: list, comments: list,
                       keyword: str, days: int = 30) -> dict:
    """
    关键词趋势：总提及 + 按日统计
    posts/comments 应已按关键词过滤
    """
    post_count = len(posts)
    comment_count = len(comments)

    # 按日统计帖子
    post_by_day = Counter()
    for p in posts:
        pt = p.get('publish_time')
        if pt:
            day = pt.strftime('%Y-%m-%d') if isinstance(pt, datetime) else str(pt)[:10]
            post_by_day[day] += 1

    # 按日统计评论
    comment_by_day = Counter()
    for c in comments:
        ct = c.get('created_time')
        if ct:
            day = ct.strftime('%Y-%m-%d') if isinstance(ct, datetime) else str(ct)[:10]
            comment_by_day[day] += 1

    # 合并日期
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


# ============================================================
# 3. 情感分析
# ============================================================

def calc_sentiment(comments: list, sample_size: int = 3000,
                   keyword: str = None) -> dict:
    """
    SnowNLP 情感分析
    正面 >0.6 / 中性 0.4-0.6 / 负面 <0.4
    """
    if sample_size and len(comments) > sample_size:
        sample = random.sample(comments, sample_size)
    else:
        sample = comments

    positive, neutral, negative = [], [], []

    for c in sample:
        text = (c.get('content') or '').strip()
        if not text:
            continue
        try:
            score = SnowNLP(text).sentiments
        except Exception:
            score = 0.5

        item = {'text': text, 'score': round(score, 3),
                'like_count': c.get('like_count', 0)}
        if score > 0.6:
            positive.append(item)
        elif score >= 0.4:
            neutral.append(item)
        else:
            negative.append(item)

    total = len(positive) + len(neutral) + len(negative)

    # 高频负面观点
    neg_words = Counter()
    for item in negative:
        for w in jieba.cut(item['text']):
            w = w.strip()
            if len(w) >= 2 and w not in STOPWORDS:
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
    }


# ============================================================
# 4. 用户影响力
# ============================================================

def calc_influencers(users: list, posts: list,
                     sort_type: str = 'followers', top_n: int = 20) -> dict:
    """
    用户影响力：高粉丝 / 高互动
    """
    # 按用户聚合帖子互动量
    engagement = {}
    for p in posts:
        uid = p.get('user_id')
        if not uid:
            continue
        if uid not in engagement:
            engagement[uid] = {
                'user_id': uid, 'username': p.get('username', ''),
                'post_count': 0, 'total_likes': 0,
                'total_comments': 0, 'total_reposts': 0,
                'total_engagement': 0,
            }
        e = engagement[uid]
        e['post_count'] += 1
        e['total_likes'] += p.get('like_count', 0) or 0
        e['total_comments'] += p.get('comment_count', 0) or 0
        e['total_reposts'] += p.get('repost_count', 0) or 0
        e['total_engagement'] = (e['total_likes'] + e['total_comments']
                                 + e['total_reposts'])

    if sort_type == 'engagement':
        data = sorted(engagement.values(),
                      key=lambda x: x['total_engagement'], reverse=True)[:top_n]
        # 补充粉丝信息
        user_map = {u['user_id']: u for u in users}
        for d in data:
            u = user_map.get(d['user_id'], {})
            d['followers_count'] = u.get('followers_count', 0)
            d['following_count'] = u.get('following_count', 0)
            d['weibo_count'] = u.get('weibo_count', 0)
            d['verified'] = u.get('verified')
            d['description'] = u.get('description')
    else:
        # followers 排序
        top_users = sorted(users, key=lambda x: x.get('followers_count', 0) or 0,
                           reverse=True)[:top_n]
        data = []
        for u in top_users:
            e = engagement.get(u['user_id'], {
                'post_count': 0, 'total_likes': 0,
                'total_comments': 0, 'total_reposts': 0,
                'total_engagement': 0,
            })
            data.append({
                'user_id': u['user_id'],
                'username': u.get('username', ''),
                'followers_count': u.get('followers_count', 0),
                'following_count': u.get('following_count', 0),
                'weibo_count': u.get('weibo_count', 0),
                'verified': u.get('verified'),
                'description': u.get('description'),
                'post_count': e['post_count'],
                'total_likes': e['total_likes'],
                'total_comments': e['total_comments'],
                'total_reposts': e['total_reposts'],
                'total_engagement': e['total_engagement'],
            })

    return {'type': sort_type, 'total': len(data), 'data': data}


# ============================================================
# 5. 日报生成
# ============================================================

def generate_daily_report(stats: dict, hotspot: list, keywords: list,
                          sentiment: dict, influencers: dict) -> str:
    """生成 Markdown 日报"""
    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    lines = [
        '# 微博数据分析日报', '',
        f'> 生成时间：{now}', '',
        '## 一、数据概览', '',
        '| 指标 | 数量 |', '|---|---|',
        f'| 微博帖子 | {stats["posts"]:,} |',
        f'| 微博评论 | {stats["comments"]:,} |',
        f'| 用户数 | {stats["users"]:,} |', '',
        '## 二、热点微博 TOP10', '',
        '| 排名 | 作者 | 内容摘要 | 点赞 | 评论 | 转发 | 热度 |',
        '|---|---|---|---|---|---|---|',
    ]
    for i, p in enumerate(hotspot[:10], 1):
        content = (p.get('content') or '')[:30].replace('\n', ' ').replace('|', '/')
        lines.append(
            f'| {i} | {p.get("username","")} | {content} | '
            f'{p.get("like_count",0):,} | {p.get("comment_count",0):,} | '
            f'{p.get("repost_count",0):,} | {p.get("hotspot_score",0)} |'
        )

    lines += ['', '## 三、关键词趋势', '',
              '| 关键词 | 帖子提及 | 评论提及 | 总提及 |',
              '|---|---|---|---|']
    for kw in keywords[:10]:
        lines.append(f'| {kw["keyword"]} | {kw["post_mentions"]} | '
                     f'{kw["comment_mentions"]} | {kw["total_mentions"]} |')

    lines += [
        '', '## 四、情感分析', '',
        f'- 分析评论：{sentiment["total_analyzed"]:,}',
        f'- 正面：{sentiment["positive_count"]:,}（{sentiment["positive_ratio"]}%）',
        f'- 中性：{sentiment["neutral_count"]:,}（{sentiment["neutral_ratio"]}%）',
        f'- 负面：{sentiment["negative_count"]:,}（{sentiment["negative_ratio"]}%）',
        '', '### 高频负面观点', '',
        '| 排名 | 关键词 | 次数 |', '|---|---|---|',
    ]
    for i, v in enumerate(sentiment['top_negative_viewpoints'][:10], 1):
        lines.append(f'| {i} | {v["word"]} | {v["count"]} |')

    ui = influencers
    lines += ['', '## 五、用户影响力 TOP5', '',
              '| 排名 | 用户 | 粉丝 | 总互动 |',
              '|---|---|---|---|']
    for i, u in enumerate(ui['data'][:5], 1):
        lines.append(f'| {i} | {u["username"]} | '
                     f'{u.get("followers_count",0):,} | '
                     f'{u.get("total_engagement",0):,} |')

    return '\n'.join(lines)
