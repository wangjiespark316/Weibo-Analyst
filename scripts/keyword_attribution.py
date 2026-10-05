#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
关键词产出归因（只读统计）
=========================
统计每个搜索关键词在 weibo_posts 中实际召回 / 覆盖的帖子数、近期活跃度与
互动量，用于发现长期 0 产出 / 纯语义重叠的关键词，以便精简（10 → 7~8），
从源头减少搜索 + 翻页请求数（请求量随关键词数近似线性下降）。

口径说明（重要，勿过度解读）：
- weibo_posts.topic 只保留该帖「最后一次命中它的关键词」：多关键词命中的帖
  在 ON DUPLICATE KEY UPDATE 时 topic 会被后来的词覆盖。因此这里统计的是每个
  词「最终名下」的帖子，属于近似归因，不是多对多净贡献；但足以识别长期
  0 / 低产出词。
- 仅统计 source='keyword' 且非 archived 历史隔离区的数据。
- 时间按 crawl_time（入库 / 命中时刻），反映该词最近是否还在召回新帖。

用法：
  python scripts/keyword_attribution.py
  python scripts/keyword_attribution.py --low-threshold 8
"""
import argparse
import json
import os
import sys

# 复用统一连接层（自动加载项目根 .env、处理 TiDB TLS）
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(_ROOT, 'step1_comments_spider'))
import db_conn  # noqa: E402


def _load_keywords():
    cfg_path = os.path.join(_ROOT, 'config', 'crawl_config.json')
    try:
        with open(cfg_path, 'r', encoding='utf-8') as f:
            return json.load(f).get('keywords', [])
    except Exception:
        return []


def _fetch_attribution(conn):
    # LEFT(dataset_type,8)<>'archived' 写法避开 LIKE 百分号转义；execute 无参数。
    sql = """
        SELECT topic,
               COUNT(*) AS n,
               SUM(CASE WHEN crawl_time >= DATE_SUB(NOW(), INTERVAL 7 DAY)  THEN 1 ELSE 0 END) AS n7,
               SUM(CASE WHEN crawl_time >= DATE_SUB(NOW(), INTERVAL 30 DAY) THEN 1 ELSE 0 END) AS n30,
               COALESCE(SUM(like_count + comment_count + repost_count), 0) AS eng,
               MAX(crawl_time) AS last_seen
        FROM weibo_posts
        WHERE source = 'keyword'
          AND topic IS NOT NULL AND topic <> ''
          AND (dataset_type IS NULL OR LEFT(dataset_type, 8) <> 'archived')
        GROUP BY topic
        ORDER BY n DESC
    """
    with conn.cursor() as cur:
        cur.execute(sql)
        cols = [d[0] for d in cur.description]
        return [dict(zip(cols, row)) for row in cur.fetchall()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--low-threshold', type=int, default=5,
                    help='近30天帖子数低于该值判为低产出（默认 5）')
    args = ap.parse_args()

    keywords = _load_keywords()
    conn = db_conn.get_connection()
    try:
        rows = _fetch_attribution(conn)
    finally:
        conn.close()

    by_topic = {r['topic']: r for r in rows}

    print('=' * 72)
    print('关键词产出归因（source=keyword，非 archived；topic=最后命中词，近似口径）')
    print('=' * 72)
    print(f"{'关键词':<12}{'总帖':>6}{'近7天':>7}{'近30天':>7}{'总互动':>9}  最近命中")
    print('-' * 72)

    low, zero = [], []
    listed = set()
    # 以配置关键词为主序，确保 0 产出词也出现
    for kw in keywords:
        r = by_topic.get(kw)
        listed.add(kw)
        if r is None:
            print(f"{kw:<12}{0:>6}{0:>7}{0:>7}{0:>9}  —（从未命中/已被覆盖）")
            zero.append(kw)
            continue
        last = r['last_seen']
        last_s = last.strftime('%Y-%m-%d %H:%M') if hasattr(last, 'strftime') else str(last)
        print(f"{kw:<12}{r['n']:>6}{r['n7']:>7}{r['n30']:>7}{r['eng']:>9}  {last_s}")
        if (r['n30'] or 0) < args.low_threshold:
            low.append(kw)
    # 库里有、但配置里已不存在的 topic（历史残留词）
    for t in (t for t in by_topic if t not in listed):
        r = by_topic[t]
        print(f"{('[' + t + ']'):<12}{r['n']:>6}{r['n7']:>7}{r['n30']:>7}{r['eng']:>9}  (配置已无此词)")

    print('-' * 72)
    print(f'配置关键词 {len(keywords)} 个；近30天低产出（<{args.low_threshold}条）：'
          f'{("、".join(low) if low else "无")}')
    print(f'完全 0 产出：{("、".join(zero) if zero else "无")}')
    print()
    print('建议（需结合语义重叠人工确认，勿仅凭计数删词）：')
    print('  · 0 产出 / 近30天极低、且与宽词（如「大模型」「智能体」）语义重叠的，')
    print('    可删除或合并；')
    print('  · 拿不准的词先保留，并周期性跑一次「宽词扫描」兜底新词召回；')
    print('  · 确定精简后改 config/crawl_config.json 的 keywords，采集请求随之下降。')


if __name__ == '__main__':
    main()
