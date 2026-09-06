#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微博数据分析日报生成器
=====================
读取 MySQL → 运行分析 → 输出 Markdown + Excel
只读数据库，不做任何修改。

用法：
    .venv/bin/python step6_data_analysis/run_analysis.py
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from db import get_posts, get_comments, get_users, get_stats
from analyzers import (
    hotspot_analysis,
    keyword_trend,
    sentiment_analysis,
    user_influence,
)
from report import generate_markdown, generate_excel

# 关键词列表（可扩展）
KEYWORDS = [
    '豆包', '飞书', 'AI办公', 'Agent', '企业AI',
    'ChatGPT', '人工智能', '大模型', 'AIGC', 'Copilot',
]

# 情感分析采样上限（全量 3000+ 条也可全量，采样提速）
SENTIMENT_SAMPLE_SIZE = 3000


def main():
    print('=' * 60)
    print('微博数据分析日报生成器')
    print('=' * 60)

    # 1. 读取数据
    print('\n[1/5] 读取 MySQL 数据...')
    stats = get_stats()
    print(f'  帖子: {stats["posts"]:,} | 评论: {stats["comments"]:,} | 用户: {stats["users"]:,}')

    posts = get_posts()
    comments = get_comments()
    users = get_users()
    print(f'  读取完成: {len(posts)} 帖, {len(comments)} 评论, {len(users)} 用户')

    # 2. 热点分析
    print('\n[2/5] 热点分析（点赞/评论/转发加权）...')
    hotspot = hotspot_analysis(posts, top_n=20)
    if hotspot:
        top = hotspot[0]
        print(f'  TOP1: {top["username"]} - {(top.get("content") or "")[:25]} '
              f'(指数:{top["hotspot_score"]}, 👍{top.get("like_count",0):,})')

    # 3. 关键词趋势
    print('\n[3/5] 关键词趋势分析...')
    keywords = keyword_trend(posts, comments, KEYWORDS)
    for kw in keywords[:5]:
        print(f'  {kw["keyword"]}: 帖子{kw["post_mentions"]} + '
              f'评论{kw["comment_mentions"]} = {kw["total_mentions"]}')

    # 4. 情感分析
    print(f'\n[4/5] 评论情感分析（SnowNLP，采样{SENTIMENT_SAMPLE_SIZE}）...')
    sentiment = sentiment_analysis(comments, sample_size=SENTIMENT_SAMPLE_SIZE)
    print(f'  正面: {sentiment["positive_ratio"]}% | '
          f'中性: {sentiment["neutral_ratio"]}% | '
          f'负面: {sentiment["negative_ratio"]}%')
    neg_words = ', '.join(w for w, c in sentiment['top_negative_viewpoints'][:8])
    print(f'  高频负面词: {neg_words}')

    # 5. 用户影响力
    print('\n[5/5] 用户影响力分析...')
    users_result = user_influence(users, posts, top_n=20)
    if users_result['top_followers']:
        tf = users_result['top_followers'][0]
        print(f'  最高粉丝: {tf["username"]} ({tf.get("followers_count",0):,})')
    if users_result['top_engagement']:
        te = users_result['top_engagement'][0]
        print(f'  最高互动: {te["username"]} (总互动{te["total_engagement"]:,})')

    # 汇总
    results = {
        'stats': stats,
        'hotspot': hotspot,
        'keywords': keywords,
        'sentiment': sentiment,
        'users': users_result,
    }

    # 6. 生成报告
    print('\n' + '=' * 60)
    print('生成报告文件...')
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'reports')
    os.makedirs(output_dir, exist_ok=True)
    date_str = datetime.now().strftime('%Y%m%d_%H%M%S')

    md_path = os.path.join(output_dir, f'daily_report_{date_str}.md')
    xlsx_path = os.path.join(output_dir, f'daily_report_{date_str}.xlsx')

    generate_markdown(results, md_path)
    print(f'  ✅ Markdown: {md_path}')

    generate_excel(results, xlsx_path)
    print(f'  ✅ Excel:    {xlsx_path}')

    print('\n' + '=' * 60)
    print('分析完成！报告已生成。')
    print('=' * 60)


if __name__ == '__main__':
    main()
