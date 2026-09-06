#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微博评论批量采集模块
=====================
- 从 weibo_posts 读取待抓取评论的微博（按状态自动筛选）
- 每条微博抓取 hotflow 热门评论（最多 N 条）
- 幂等写入 weibo_comments（comment_id 唯一键去重）
- 更新 weibo_posts.comment_crawl_status / time / count
- 状态管理：已完成的微博 7 天内不重复抓取，失败的可重试

依赖：weibo_post_collector.py（同目录，复用请求/解析/upsert 函数）
"""

import sys
import os
import logging
import pymysql

# 确保同目录模块可导入
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from weibo_post_collector import (
    DB_CONFIG,
    fetch_comments,
    parse_comment,
    upsert_comment,
    get_db_connection,
)

# ===== 日志 =====
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)


# ============================================================
# 状态管理：读取待采集微博
# ============================================================

def get_pending_posts(conn, limit=100, re_crawl_days=7):
    """
    从 weibo_posts 获取待抓取评论的微博：
      - status=0（从未采集）
      - status=2（上次失败，可重试）
      - status=1 但 crawl_time 超过 re_crawl_days 天（定期更新）
    按互动度倒序（评论数→点赞数→发布时间），返回 limit 条
    """
    sql = """
    SELECT weibo_id, id AS post_id, username,
           LEFT(content, 60) AS content_preview,
           comment_crawl_status, comment_crawl_time,
           comment_count, like_count
    FROM weibo_posts
    WHERE comment_crawl_status = 0
       OR comment_crawl_status = 2
       OR (comment_crawl_status = 1
           AND comment_crawl_time < DATE_SUB(NOW(), INTERVAL %s DAY))
    ORDER BY comment_count DESC, like_count DESC, publish_time DESC
    LIMIT %s
    """
    with conn.cursor(pymysql.cursors.DictCursor) as cursor:
        cursor.execute(sql, (re_crawl_days, limit))
        return cursor.fetchall()


def update_post_comment_status(conn, weibo_id, status, comment_count):
    """
    更新微博的评论采集状态
    status: 1=已完成, 2=失败
    """
    sql = """
    UPDATE weibo_posts
    SET comment_crawl_status = %s,
        comment_crawl_time   = NOW(),
        comment_crawl_count  = %s
    WHERE weibo_id = %s
    """
    with conn.cursor() as cursor:
        cursor.execute(sql, (status, comment_count, weibo_id))
    conn.commit()


# ============================================================
# 批量采集主流程
# ============================================================

def batch_collect_comments(limit=100, max_comments_per_post=50, re_crawl_days=7):
    """
    批量采集微博评论
    返回 (success_count, fail_count, total_comments)
    """
    conn = get_db_connection()

    # 1. 读取待采集微博
    posts = get_pending_posts(conn, limit, re_crawl_days)
    logging.info("=" * 60)
    logging.info(f"评论批量采集启动")
    logging.info(f"待采集微博: {len(posts)} 条 | 每条最多 {max_comments_per_post} 评论")
    logging.info(f"重抓周期: {re_crawl_days} 天")
    logging.info("=" * 60)

    if not posts:
        logging.info("没有待采集的微博（全部已完成且在重抓周期内）")
        conn.close()
        return 0, 0, 0

    total_comments = 0
    success_count = 0
    fail_count = 0

    for i, post in enumerate(posts, 1):
        weibo_id = post["weibo_id"]
        post_id = post["post_id"]
        username = post.get("username", "unknown")
        prev_status = post.get("comment_crawl_status", 0)

        logging.info(f"[{i}/{len(posts)}] 微博 {weibo_id} (@{username}) "
                     f"[原状态:{prev_status}]")

        try:
            # 2. 抓取评论（hotflow，分页，最多 max_comments_per_post）
            comments = fetch_comments(weibo_id, max_comments_per_post)

            # 3. 逐条 upsert 到 weibo_comments
            for c in comments:
                c_dict = parse_comment(c, weibo_id, post_id, is_hot=1)
                upsert_comment(conn, c_dict)

            # 4. 更新微博采集状态
            update_post_comment_status(conn, weibo_id, 1, len(comments))
            total_comments += len(comments)
            success_count += 1
            logging.info(f"   ✅ 完成，采集 {len(comments)} 条评论")

        except Exception as e:
            logging.error(f"   ❌ 失败: {e}")
            update_post_comment_status(conn, weibo_id, 2, 0)
            fail_count += 1

        # 每 10 条打印一次进度
        if i % 10 == 0:
            logging.info(f"--- 进度 {i}/{len(posts)} | "
                         f"成功 {success_count} | 失败 {fail_count} | "
                         f"评论 {total_comments} ---")

    conn.close()

    logging.info("=" * 60)
    logging.info(f"批量采集完成")
    logging.info(f"成功: {success_count} | 失败: {fail_count} | 评论总数: {total_comments}")
    logging.info("=" * 60)

    return success_count, fail_count, total_comments


# ============================================================
# 入口
# ============================================================

def main():
    # 第一阶段测试：100 条微博，每条最多 50 评论，目标 3000+ 评论
    LIMIT = 100
    MAX_COMMENTS = 50
    RE_CRAWL_DAYS = 7

    success, fail, total = batch_collect_comments(
        limit=LIMIT,
        max_comments_per_post=MAX_COMMENTS,
        re_crawl_days=RE_CRAWL_DAYS
    )

    # 结果摘要
    print("\n" + "=" * 60)
    print("采集结果摘要")
    print(f"  成功微博: {success}")
    print(f"  失败微博: {fail}")
    print(f"  评论总数: {total}")
    if total >= 3000:
        print(f"  目标达成: ✅ 超过 3000 条")
    else:
        print(f"  目标差距: 还需 {3000 - total} 条")
    print("=" * 60)


if __name__ == "__main__":
    main()
