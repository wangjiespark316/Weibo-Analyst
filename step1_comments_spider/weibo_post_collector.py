#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
微博帖子正式采集模块
- 用户时间线采集 + 关键词搜索采集
- 幂等写入 weibo_posts / weibo_users（INSERT ... ON DUPLICATE KEY UPDATE）
- 复用 weibo_post_test.py 的请求/解析/重试逻辑
- 小批量测试入口：1 账号 × 10 条 + 1 关键词 × 10 条
"""

import time
import random
import requests
import re
import html
import logging
import sys
import os
import pymysql
from datetime import datetime
from urllib.parse import quote, urlparse, parse_qs

# ===== 日志 =====
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    stream=sys.stdout
)

# ===== 数据库配置（优先 DATABASE_URL 环境变量，回退本地 MySQL）=====
def get_db_config():
    """获取数据库配置：云端用 DATABASE_URL，本地用默认配置"""
    database_url = os.getenv('DATABASE_URL')
    if database_url:
        p = urlparse(database_url)
        query = parse_qs(p.query)
        config = {
            'host': p.hostname,
            'port': p.port or 4000,
            'user': p.username,
            'password': p.password or '',
            'database': p.path.lstrip('/'),
            'charset': 'utf8mb4',
        }
        # TiDB Cloud 强制 TLS
        is_tidb = 'tidb' in (p.hostname or '').lower()
        ssl_mode = query.get('ssl-mode', [''])[0].upper()
        if is_tidb or ssl_mode in ('VERIFY_IDENTITY', 'VERIFY_CA', 'REQUIRED'):
            config['ssl'] = {'ssl_disabled': False}
        return config
    # 本地开发默认配置（密码从环境变量读取，避免硬编码）
    return {
        'host': os.getenv('MYSQL_HOST', '127.0.0.1'),
        'port': int(os.getenv('MYSQL_PORT', '3306')),
        'user': os.getenv('MYSQL_USER', 'root'),
        'password': os.getenv('MYSQL_PASSWORD', ''),
        'database': os.getenv('MYSQL_DATABASE', 'weibo_comments'),
        'charset': 'utf8mb4',
    }

# ===== 微博 Cookie（从环境变量读取，GitHub Actions 用 WEIBO_COOKIE secret）=====
WEIBO_COOKIE = os.getenv('WEIBO_COOKIE', '')

# 双 UA（80% 百度蜘蛛 / 20% 移动端）
MOBILE_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 13_2_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/13.0.3 Mobile/15E148 Safari/604.1"
BAIDU_SPIDER_UA = "Baiduspider+(+http://www.baidu.com/search/spider.htm)"

# 请求历史状态（智能延迟用）
request_history = {
    "last_request_time": time.time(),
    "consecutive_success": 0,
    "consecutive_error": 0
}


# ============================================================
# 工具函数（复用 weibo_post_test.py）
# ============================================================

def clean_html_tags(text):
    """清除 HTML 标签"""
    if not text:
        return ""
    return re.sub(r'<.*?>', '', text)


def smart_delay():
    """智能请求延迟"""
    base_delay = 1.5
    current_time = time.time()
    if request_history["consecutive_error"] > 0:
        actual_delay = base_delay + (request_history["consecutive_error"] * 2)
    else:
        actual_delay = base_delay
    actual_delay *= random.uniform(0.8, 1.2)
    elapsed = current_time - request_history["last_request_time"]
    if elapsed < actual_delay:
        time.sleep(actual_delay - elapsed)
    request_history["last_request_time"] = time.time()


def get_headers(referer=None):
    """构建请求头（双 UA 轮换）"""
    user_agent = BAIDU_SPIDER_UA if random.random() > 0.2 else MOBILE_UA
    headers = {
        "User-Agent": user_agent,
        "Cookie": WEIBO_COOKIE,
        "X-Requested-With": "XMLHttpRequest",
    }
    if referer:
        headers["Referer"] = referer
    return headers


def fetch_json(url, referer=None, max_retries=4):
    """带重试的 JSON 请求"""
    smart_delay()
    headers = get_headers(referer)
    for attempt in range(1, max_retries + 1):
        try:
            time.sleep(random.uniform(0.5, 1.5))
            response = requests.get(url, headers=headers, timeout=15)
            if response.status_code == 418:
                logging.warning("🚫 418 封禁，等待 30 秒")
                time.sleep(30)
                continue
            response.raise_for_status()
            if not response.text.strip():
                raise ValueError("Empty response")
            data = response.json()
            if data.get("ok") != 1:
                msg = data.get("msg", "unknown")
                logging.warning(f"⚠️ API ok!=1: {msg}")
                if "频繁" in msg or "frequency" in msg.lower():
                    time.sleep(random.uniform(15, 30))
                    continue
            request_history["consecutive_success"] += 1
            request_history["consecutive_error"] = 0
            return data
        except Exception as e:
            request_history["consecutive_success"] = 0
            request_history["consecutive_error"] += 1
            backoff = min(30, 2 ** attempt + random.random())
            logging.warning(f"⚠️ 请求失败 (尝试 {attempt}/{max_retries}): {e}，等待 {backoff:.1f}s")
            time.sleep(backoff)
            headers["User-Agent"] = BAIDU_SPIDER_UA if headers["User-Agent"] == MOBILE_UA else MOBILE_UA
    logging.error("❌ 多次重试失败")
    return None


def parse_count(value):
    """
    解析微博计数字段，支持多种格式：
    - 纯数字: 8239 / 8239.0
    - 带单位: '8251.7万' -> 82517000, '1.2亿' -> 120000000
    - 空值/None -> 0
    """
    if value is None or value == '':
        return 0
    if isinstance(value, (int, float)):
        return int(value)
    s = str(value).strip()
    try:
        if '亿' in s:
            return int(float(s.replace('亿', '')) * 100000000)
        elif '万' in s:
            return int(float(s.replace('万', '')) * 10000)
        else:
            return int(float(s))
    except (ValueError, TypeError):
        return 0


def parse_created_at(created_at_str):
    """
    解析微博 created_at 为 MySQL DATETIME 字符串
    输入格式: "Wed Sep 02 20:18:21 +0800 2026"
    输出格式: "2026-09-02 20:18:21"
    """
    if not created_at_str:
        return None
    try:
        dt = datetime.strptime(created_at_str, "%a %b %d %H:%M:%S %z %Y")
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        # 备用：尝试不带时区
        try:
            dt = datetime.strptime(created_at_str, "%a %b %d %H:%M:%S %Y")
            return dt.strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            logging.warning(f"⚠️ 无法解析 created_at: {created_at_str}")
            return None


def parse_mblog(mblog):
    """
    解析单条 mblog，返回 (post_dict, user_dict)
    post_dict 对应 weibo_posts 表，user_dict 对应 weibo_users 表
    """
    user = mblog.get("user", {}) or {}
    weibo_id = str(mblog.get("id") or mblog.get("mid") or "")
    text_raw = mblog.get("text_raw") or mblog.get("text") or ""
    text_clean = clean_html_tags(html.unescape(text_raw))
    publish_time = parse_created_at(mblog.get("created_at", ""))

    post_dict = {
        "weibo_id": weibo_id,
        "user_id": str(user.get("id", "")),
        "username": user.get("screen_name", ""),
        "content": text_clean,
        "content_raw": text_raw,
        "publish_time": publish_time,
        "like_count": parse_count(mblog.get("attitudes_count")),
        "comment_count": parse_count(mblog.get("comments_count")),
        "repost_count": parse_count(mblog.get("reposts_count")),
        "url": f"https://m.weibo.cn/detail/{weibo_id}" if weibo_id else None,
        "source": "",   # 由调用方设置: account / keyword
        "topic": "",    # 由调用方设置: 命中的关键词
    }

    user_dict = {
        "user_id": str(user.get("id", "")),
        "username": user.get("screen_name", ""),
        "followers_count": parse_count(user.get("followers_count")),
        "following_count": parse_count(user.get("follow_count")),
        "weibo_count": parse_count(user.get("statuses_count")),
        "description": user.get("description", "") or None,
        "gender": user.get("gender", "") or None,
        "verified": 1 if user.get("verified") else 0,
        "verified_reason": user.get("verified_reason", "") or None,
        "avatar": user.get("profile_image_url", "") or None,
    }

    return post_dict, user_dict


def extract_mblogs_from_cards(cards):
    """从 cards 中提取所有 mblog（处理嵌套 card_type=11）"""
    mblogs = []
    for card in cards:
        if card.get("card_type") == 9 and "mblog" in card:
            mblogs.append(card["mblog"])
        elif card.get("card_type") == 11 and "card_group" in card:
            for sub in card["card_group"]:
                if sub.get("card_type") == 9 and "mblog" in sub:
                    mblogs.append(sub["mblog"])
    return mblogs


# ============================================================
# 采集通道
# ============================================================

def fetch_user_timeline(user_id, page=1):
    """用户时间线采集：containerid=107603{uid}，返回 mblog 原始列表"""
    url = f"https://m.weibo.cn/api/container/getIndex?containerid=107603{user_id}&page={page}"
    referer = f"https://m.weibo.cn/u/{user_id}"
    logging.info(f"📅 [用户时间线] uid={user_id} page={page}")
    data = fetch_json(url, referer)
    if not data:
        return []
    cards = data.get("data", {}).get("cards", [])
    mblogs = extract_mblogs_from_cards(cards)
    logging.info(f"   → 解析到 {len(mblogs)} 条 mblog")
    return mblogs


def fetch_keyword_search(keyword, page=1):
    """关键词搜索采集：containerid=100103type=1&q={kw}，返回 mblog 原始列表"""
    q = quote(keyword)
    url = (
        f"https://m.weibo.cn/api/container/getIndex?"
        f"containerid=100103type%3D1%26q%3D{q}&page_type=searchall&page={page}"
    )
    referer = f"https://m.weibo.cn/search?containerid=100103type%3D1%26q%3D{q}"
    logging.info(f"🔍 [关键词搜索] kw={keyword} page={page}")
    data = fetch_json(url, referer)
    if not data:
        return []
    cards = data.get("data", {}).get("cards", [])
    mblogs = extract_mblogs_from_cards(cards)
    logging.info(f"   → 解析到 {len(mblogs)} 条 mblog")
    return mblogs


# ============================================================
# MySQL 存储（幂等 upsert）
# ============================================================

def get_db_connection():
    """获取数据库连接（优先云端 DATABASE_URL，回退本地 MySQL）"""
    return pymysql.connect(**get_db_config())


def upsert_post(conn, post_dict):
    """
    幂等写入 weibo_posts
    weibo_id 唯一键冲突时更新互动数等字段
    """
    sql = """
    INSERT INTO weibo_posts
      (weibo_id, user_id, username, content, content_raw, publish_time,
       like_count, comment_count, repost_count, url, source, topic)
    VALUES
      (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
      user_id=VALUES(user_id),
      username=VALUES(username),
      content=VALUES(content),
      content_raw=VALUES(content_raw),
      publish_time=VALUES(publish_time),
      like_count=VALUES(like_count),
      comment_count=VALUES(comment_count),
      repost_count=VALUES(repost_count),
      url=VALUES(url),
      source=VALUES(source),
      topic=VALUES(topic),
      crawl_time=CURRENT_TIMESTAMP
    """
    with conn.cursor() as cursor:
        cursor.execute(sql, (
            post_dict["weibo_id"], post_dict["user_id"], post_dict["username"],
            post_dict["content"], post_dict["content_raw"], post_dict["publish_time"],
            post_dict["like_count"], post_dict["comment_count"], post_dict["repost_count"],
            post_dict["url"], post_dict["source"], post_dict["topic"]
        ))
    conn.commit()


def upsert_user(conn, user_dict):
    """
    幂等写入 weibo_users
    user_id 唯一键冲突时更新用户画像字段
    """
    if not user_dict["user_id"]:
        return
    sql = """
    INSERT INTO weibo_users
      (user_id, username, followers_count, following_count, weibo_count,
       description, gender, verified, verified_reason, avatar)
    VALUES
      (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
      username=VALUES(username),
      followers_count=VALUES(followers_count),
      following_count=VALUES(following_count),
      weibo_count=VALUES(weibo_count),
      description=VALUES(description),
      gender=VALUES(gender),
      verified=VALUES(verified),
      verified_reason=VALUES(verified_reason),
      avatar=VALUES(avatar),
      crawl_time=CURRENT_TIMESTAMP
    """
    with conn.cursor() as cursor:
        cursor.execute(sql, (
            user_dict["user_id"], user_dict["username"],
            user_dict["followers_count"], user_dict["following_count"],
            user_dict["weibo_count"], user_dict["description"],
            user_dict["gender"], user_dict["verified"],
            user_dict["verified_reason"], user_dict["avatar"]
        ))
    conn.commit()


def get_post_id_by_weibo_id(conn, weibo_id):
    """根据 weibo_id 查询帖子内部 id（用于评论关联 post_id）"""
    with conn.cursor() as cursor:
        cursor.execute("SELECT id FROM weibo_posts WHERE weibo_id = %s", (weibo_id,))
        row = cursor.fetchone()
        return row[0] if row else None


# ============================================================
# 评论采集（复用现有 hotflow 接口逻辑）
# ============================================================

def fetch_comments(weibo_id, max_comments=50):
    """
    抓取微博评论（hotflow 热门评论，分页）
    返回评论原始对象列表，最多 max_comments 条
    """
    comments = []
    max_id = None
    page = 1

    while len(comments) < max_comments:
        smart_delay()
        url = f"https://m.weibo.cn/comments/hotflow?id={weibo_id}&mid={weibo_id}"
        if max_id and str(max_id) not in ("0", ""):
            url += f"&max_id={max_id}"
        if random.random() > 0.5:
            url += "&max_id_type=0"

        headers = get_headers(referer=f"https://m.weibo.cn/detail/{weibo_id}")
        data = None
        for attempt in range(1, 4):
            try:
                time.sleep(random.uniform(0.5, 1.5))
                response = requests.get(url, headers=headers, timeout=15)
                if response.status_code == 418:
                    logging.warning("🚫 评论接口 418，等待 30 秒")
                    time.sleep(30)
                    continue
                response.raise_for_status()
                if not response.text.strip():
                    raise ValueError("Empty response")
                data = response.json()
                if data.get("ok") != 1:
                    msg = data.get("msg", "unknown")
                    if "频繁" in msg or "frequency" in msg.lower():
                        time.sleep(random.uniform(15, 30))
                        continue
                break
            except Exception as e:
                logging.warning(f"⚠️ 评论请求失败 (尝试 {attempt}/3): {e}")
                time.sleep(min(30, 2 ** attempt))
                headers["User-Agent"] = BAIDU_SPIDER_UA if headers["User-Agent"] == MOBILE_UA else MOBILE_UA

        if not data or data.get("ok") != 1:
            break

        comment_list = data.get("data", {}).get("data", [])
        if not comment_list:
            break

        comments.extend(comment_list)

        max_id = data.get("data", {}).get("max_id")
        if not max_id or str(max_id) in ("0", ""):
            break
        page += 1
        if page > 5:  # 安全上限，防止无限翻页
            break

    return comments[:max_comments]


def parse_comment(comment, weibo_id, post_id=None, is_hot=1):
    """解析单条评论，返回 weibo_comments 表字段"""
    user = comment.get("user", {}) or {}
    text_raw = comment.get("text", "")
    text_clean = clean_html_tags(html.unescape(text_raw))
    created_time = parse_created_at(comment.get("created_at", ""))
    return {
        "comment_id": str(comment.get("id", "")),
        "weibo_id": weibo_id,
        "post_id": post_id,
        "user_id": str(user.get("id", "")),
        "username": user.get("screen_name", ""),
        "content": text_clean,
        "like_count": parse_count(comment.get("like_count")),
        "created_time": created_time,
        "is_hot": is_hot,
    }


def upsert_comment(conn, comment_dict):
    """幂等写入 weibo_comments（comment_id 唯一键冲突时更新）"""
    if not comment_dict["comment_id"]:
        return
    sql = """
    INSERT INTO weibo_comments
      (comment_id, weibo_id, post_id, user_id, username, content, like_count, created_time, is_hot)
    VALUES
      (%s, %s, %s, %s, %s, %s, %s, %s, %s)
    ON DUPLICATE KEY UPDATE
      weibo_id=VALUES(weibo_id),
      post_id=VALUES(post_id),
      user_id=VALUES(user_id),
      username=VALUES(username),
      content=VALUES(content),
      like_count=VALUES(like_count),
      created_time=VALUES(created_time),
      is_hot=VALUES(is_hot),
      crawl_time=CURRENT_TIMESTAMP
    """
    with conn.cursor() as cursor:
        cursor.execute(sql, (
            comment_dict["comment_id"], comment_dict["weibo_id"], comment_dict["post_id"],
            comment_dict["user_id"], comment_dict["username"], comment_dict["content"],
            comment_dict["like_count"], comment_dict["created_time"], comment_dict["is_hot"]
        ))
    conn.commit()


# ============================================================
# 采集 + 入库主流程
# ============================================================

def collect_and_store(user_id=None, keyword=None, max_posts=10,
                      max_comments_per_post=50, fetch_comments_flag=True):
    """
    采集并入库微博帖子 + 用户信息 + 评论
    帖子入库后自动抓取评论并关联 weibo_id / post_id
    返回 (post_count, user_count, comment_count)
    """
    conn = get_db_connection()
    post_ids = set()
    user_ids = set()
    total_comments = 0

    try:
        # 通道 1：用户时间线
        if user_id:
            mblogs = fetch_user_timeline(user_id, page=1)
            channel_comments = 0
            for mblog in mblogs[:max_posts]:
                post_dict, user_dict = parse_mblog(mblog)
                post_dict["source"] = "account"
                post_dict["topic"] = ""
                if post_dict["weibo_id"]:
                    upsert_user(conn, user_dict)
                    upsert_post(conn, post_dict)
                    post_ids.add(post_dict["weibo_id"])
                    user_ids.add(user_dict["user_id"])

                    # 抓取评论并关联
                    if fetch_comments_flag:
                        post_id = get_post_id_by_weibo_id(conn, post_dict["weibo_id"])
                        comments = fetch_comments(post_dict["weibo_id"], max_comments_per_post)
                        for c in comments:
                            c_dict = parse_comment(c, post_dict["weibo_id"], post_id, is_hot=1)
                            upsert_comment(conn, c_dict)
                            channel_comments += 1
            total_comments += channel_comments
            logging.info(f"✅ [账号] {user_id}: {min(len(mblogs), max_posts)} 帖, {channel_comments} 评论")

        # 通道 2：关键词搜索
        if keyword:
            mblogs = fetch_keyword_search(keyword, page=1)
            channel_comments = 0
            for mblog in mblogs[:max_posts]:
                post_dict, user_dict = parse_mblog(mblog)
                post_dict["source"] = "keyword"
                post_dict["topic"] = keyword
                if post_dict["weibo_id"]:
                    upsert_user(conn, user_dict)
                    upsert_post(conn, post_dict)
                    post_ids.add(post_dict["weibo_id"])
                    user_ids.add(user_dict["user_id"])

                    # 抓取评论并关联
                    if fetch_comments_flag:
                        post_id = get_post_id_by_weibo_id(conn, post_dict["weibo_id"])
                        comments = fetch_comments(post_dict["weibo_id"], max_comments_per_post)
                        for c in comments:
                            c_dict = parse_comment(c, post_dict["weibo_id"], post_id, is_hot=1)
                            upsert_comment(conn, c_dict)
                            channel_comments += 1
            total_comments += channel_comments
            logging.info(f"✅ [关键词] {keyword}: {min(len(mblogs), max_posts)} 帖, {channel_comments} 评论")

    finally:
        conn.close()

    return len(post_ids), len(user_ids), total_comments


# ============================================================
# 小批量测试入口
# ============================================================

def main():
    # 小批量测试：5 账号帖 + 5 关键词帖 = 10 条帖子，每条最多 50 条评论
    TEST_USER_ID = "1669879400"   # 迪丽热巴（公开账号）
    TEST_KEYWORD = "飞书"
    MAX_POSTS_PER_CHANNEL = 5      # 每通道 5 条，共 10 条
    MAX_COMMENTS_PER_POST = 50     # 每条帖子最多 50 条评论

    logging.info("=" * 60)
    logging.info("微博帖子+评论正式采集模块 - 小批量测试")
    logging.info(f"账号: {TEST_USER_ID} ({MAX_POSTS_PER_CHANNEL}帖) | 关键词: {TEST_KEYWORD} ({MAX_POSTS_PER_CHANNEL}帖)")
    logging.info(f"每条帖子最多 {MAX_COMMENTS_PER_POST} 条评论 | 共 {MAX_POSTS_PER_CHANNEL * 2} 条帖子")
    logging.info("=" * 60)

    # 第一次运行：INSERT
    logging.info("\n----- 第一次运行（INSERT 新数据）-----")
    p1, u1, c1 = collect_and_store(
        user_id=TEST_USER_ID, keyword=TEST_KEYWORD,
        max_posts=MAX_POSTS_PER_CHANNEL,
        max_comments_per_post=MAX_COMMENTS_PER_POST
    )
    logging.info(f"第一次运行结果: {p1} 帖, {u1} 用户, {c1} 评论")

    # 第二次运行：验证 ON DUPLICATE KEY UPDATE（不应新增重复）
    logging.info("\n----- 第二次运行（验证幂等 upsert）-----")
    p2, u2, c2 = collect_and_store(
        user_id=TEST_USER_ID, keyword=TEST_KEYWORD,
        max_posts=MAX_POSTS_PER_CHANNEL,
        max_comments_per_post=MAX_COMMENTS_PER_POST
    )
    logging.info(f"第二次运行结果: {p2} 帖, {u2} 用户, {c2} 评论")

    logging.info("\n" + "=" * 60)
    logging.info("小批量测试完成，请在 MySQL 中验证：")
    logging.info("  SELECT COUNT(*) FROM weibo_posts;      -- 应为 10（非 20）")
    logging.info("  SELECT COUNT(*) FROM weibo_comments;   -- 评论总数")
    logging.info("  SELECT weibo_id, COUNT(*) FROM weibo_comments GROUP BY weibo_id;  -- 按微博关联")
    logging.info("  SELECT comment_id, COUNT(*) AS dup FROM weibo_comments GROUP BY comment_id HAVING dup > 1;  -- 重复检查（应为空）")
    logging.info("两次运行后帖子/评论数应不变（幂等验证）")
    logging.info("=" * 60)


if __name__ == "__main__":
    main()
