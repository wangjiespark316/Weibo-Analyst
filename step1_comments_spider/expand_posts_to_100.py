#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
扩充微博帖子到约 100 条
- 多关键词搜索采集
- 不抓评论（评论由 weibo_comment_batch_collector.py 统一处理）
- 新帖子 comment_crawl_status 默认为 0（待采集评论）
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from weibo_post_collector import collect_and_store

# 关键词列表（AI/办公/企业相关）
KEYWORDS = [
    "飞书",
    "豆包",
    "AI办公",
    "企业AI",
    "ChatGPT",
    "人工智能",
    "大模型",
]
MAX_POSTS_PER_KEYWORD = 15  # 每个关键词最多 15 条

print("=" * 60)
print("帖子扩充采集（不抓评论）")
print(f"关键词: {', '.join(KEYWORDS)}")
print(f"每关键词最多: {MAX_POSTS_PER_KEYWORD} 条")
print("=" * 60)

total_posts = 0
total_users = 0

for kw in KEYWORDS:
    print(f"\n--- 关键词 [{kw}] ---")
    p, u, c = collect_and_store(
        keyword=kw,
        max_posts=MAX_POSTS_PER_KEYWORD,
        fetch_comments_flag=False  # 不抓评论，由批量采集器统一处理
    )
    total_posts += p
    total_users += u
    print(f"  → {p} 帖, {u} 用户")

print("\n" + "=" * 60)
print(f"扩充完成")
print(f"  新增帖子: {total_posts}")
print(f"  新增用户: {total_users}")
print(f"  (含去重，实际入库数以 MySQL 为准)")
print("=" * 60)
