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
from datetime import datetime, timezone, timedelta
from urllib.parse import quote

# 北京时区（微博 m 站搜索结果按北京时间倒序）
BJ_TZ = timezone(timedelta(hours=8))

# 统一数据库连接层：生产 DATABASE_URL（TiDB Cloud）/ 开发本地 MySQL
from db_conn import get_connection, get_db_config, db_mode, table_counts

# ===== 日志（stdout + 文件双通道） =====
_LOGGER = logging.getLogger('weibo_post_collector')
if not _LOGGER.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    _handler.setFormatter(_formatter)
    _LOGGER.addHandler(_handler)
    _LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
    os.makedirs(_LOG_DIR, exist_ok=True)
    _file_handler = logging.FileHandler(
        os.path.join(_LOG_DIR, f'crawl_{datetime.now().strftime("%Y%m%d")}.log'),
        encoding='utf-8')
    _file_handler.setFormatter(_formatter)
    _LOGGER.addHandler(_file_handler)
_LOGGER.setLevel(logging.INFO)

# 兼容导出：db_conn 连接函数（供 weibo_comment_batch_collector 等模块使用）

# ===== 微博 Cookie（从环境变量读取，GitHub Actions 用 WEIBO_COOKIE secret）=====
WEIBO_COOKIE = os.getenv('WEIBO_COOKIE', '')

# ===== 代理配置（可选，用于住宅 IP 绕过微博机房风控）=====
# 格式：socks5://127.0.0.1:18888 或 http://127.0.0.1:18888
# 不设置则直连
WEIBO_PROXY = os.getenv('WEIBO_PROXY', '')
_PROXIES = {"http": WEIBO_PROXY, "https": WEIBO_PROXY} if WEIBO_PROXY else None

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
            response = requests.get(url, headers=headers, timeout=15, proxies=_PROXIES)
            if response.status_code == 418:
                _LOGGER.warning("🚫 418 封禁，等待 30 秒")
                time.sleep(30)
                continue
            response.raise_for_status()
            if not response.text.strip():
                raise ValueError("Empty response")
            data = response.json()
            if data.get("ok") != 1:
                msg = data.get("msg", "unknown")
                _LOGGER.warning(f"⚠️ API ok!=1: {msg}")
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
            _LOGGER.warning(f"⚠️ 请求失败 (尝试 {attempt}/{max_retries}): {e}，等待 {backoff:.1f}s")
            time.sleep(backoff)
            headers["User-Agent"] = BAIDU_SPIDER_UA if headers["User-Agent"] == MOBILE_UA else MOBILE_UA
    _LOGGER.error("❌ 多次重试失败")
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
            _LOGGER.warning(f"⚠️ 无法解析 created_at: {created_at_str}")
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
    _LOGGER.info(f"📅 [用户时间线] uid={user_id} page={page}")
    data = fetch_json(url, referer)
    if not data:
        return []
    cards = data.get("data", {}).get("cards", [])
    mblogs = extract_mblogs_from_cards(cards)
    _LOGGER.info(f"   → 解析到 {len(mblogs)} 条 mblog")
    return mblogs


def fetch_keyword_search(keyword, page=1):
    """关键词搜索采集（综合排序 type=1，会混入历史热门帖）：返回 mblog 原始列表"""
    q = quote(keyword)
    url = (
        f"https://m.weibo.cn/api/container/getIndex?"
        f"containerid=100103type%3D1%26q%3D{q}&page_type=searchall&page={page}"
    )
    referer = f"https://m.weibo.cn/search?containerid=100103type%3D1%26q%3D{q}"
    _LOGGER.info(f"🔍 [关键词搜索] kw={keyword} page={page}")
    data = fetch_json(url, referer)
    if not data:
        return []
    cards = data.get("data", {}).get("cards", [])
    mblogs = extract_mblogs_from_cards(cards)
    _LOGGER.info(f"   → 解析到 {len(mblogs)} 条 mblog")
    return mblogs


def fetch_realtime_search(keyword, page=1):
    """
    关键词【实时流】采集：containerid=100103type=61&q={kw}
    结果按发布时间倒序（最新在前），适合按自然日做增量采集、翻到目标日之前即停。
    返回 mblog 原始列表。
    """
    cid = f"100103type=61&q={keyword}"
    cid_enc = quote(cid, safe='')
    url = (
        "https://m.weibo.cn/api/container/getIndex?"
        f"containerid={cid_enc}&page_type=searchall&page={page}"
    )
    referer = f"https://m.weibo.cn/search?containerid={cid_enc}"
    _LOGGER.info(f"⚡ [实时流搜索] kw={keyword} page={page}")
    data = fetch_json(url, referer)
    if not data:
        return []
    cards = data.get("data", {}).get("cards", [])
    mblogs = extract_mblogs_from_cards(cards)
    _LOGGER.info(f"   → 解析到 {len(mblogs)} 条 mblog")
    return mblogs


def resolve_day_window(target='today'):
    """
    解析目标自然日窗口（北京时间），返回 (day_start_str, day_end_str, date_str)。
    target 支持：today / yesterday / YYYY-MM-DD。
    窗口为 [day_start 00:00:00, day_end 次日00:00:00)。
    today 的 day_end 取当前时刻（不采未来，也不会有未来数据）。
    """
    now_bj = datetime.now(BJ_TZ)
    today_start = now_bj.replace(hour=0, minute=0, second=0, microsecond=0)
    if target == 'today':
        day_start = today_start
        date_str = day_start.strftime('%Y-%m-%d')
        day_end = now_bj + timedelta(minutes=1)  # 含当前时刻
    elif target == 'yesterday':
        day_start = today_start - timedelta(days=1)
        date_str = day_start.strftime('%Y-%m-%d')
        day_end = today_start
    else:
        day = datetime.strptime(target, '%Y-%m-%d').replace(tzinfo=BJ_TZ)
        date_str = target
        day_start = day
        day_end = day + timedelta(days=1)
    return (
        day_start.strftime('%Y-%m-%d %H:%M:%S'),
        day_end.strftime('%Y-%m-%d %H:%M:%S'),
        date_str,
    )


# ============================================================
# MySQL 存储（幂等 upsert）
# ============================================================

def get_db_connection():
    """获取数据库连接（统一走 db_conn：生产 TiDB / 本地 MySQL）"""
    return get_connection()


def upsert_post(conn, post_dict):
    """
    幂等写入 weibo_posts
    weibo_id 唯一键冲突时更新互动数等字段

    返回去重结果：1=新增, 2=更新（唯一键冲突且内容有变化）, 0=重复且无变化
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
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, (
                post_dict["weibo_id"], post_dict["user_id"], post_dict["username"],
                post_dict["content"], post_dict["content_raw"], post_dict["publish_time"],
                post_dict["like_count"], post_dict["comment_count"], post_dict["repost_count"],
                post_dict["url"], post_dict["source"], post_dict["topic"]
            ))
        conn.commit()
        return cursor.rowcount
    except Exception as e:
        conn.rollback()
        _LOGGER.error(f"❌ upsert_post 失败 weibo_id={post_dict.get('weibo_id')}: {type(e).__name__}: {e}")
        raise


def upsert_user(conn, user_dict):
    """
    幂等写入 weibo_users
    user_id 唯一键冲突时更新用户画像字段

    返回去重结果：1=新增, 2=更新, 0=重复且无变化；user_id 为空返回 None
    """
    if not user_dict["user_id"]:
        return None
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
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, (
                user_dict["user_id"], user_dict["username"],
                user_dict["followers_count"], user_dict["following_count"],
                user_dict["weibo_count"], user_dict["description"],
                user_dict["gender"], user_dict["verified"],
                user_dict["verified_reason"], user_dict["avatar"]
            ))
        conn.commit()
        return cursor.rowcount
    except Exception as e:
        conn.rollback()
        _LOGGER.error(f"❌ upsert_user 失败 user_id={user_dict.get('user_id')}: {type(e).__name__}: {e}")
        raise


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
                response = requests.get(url, headers=headers, timeout=15, proxies=_PROXIES)
                if response.status_code == 418:
                    _LOGGER.warning("🚫 评论接口 418，等待 30 秒")
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
                _LOGGER.warning(f"⚠️ 评论请求失败 (尝试 {attempt}/3): {e}")
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
    """
    幂等写入 weibo_comments（comment_id 唯一键冲突时更新）

    返回去重结果：1=新增, 2=更新, 0=重复且无变化；comment_id 为空返回 None
    """
    if not comment_dict["comment_id"]:
        return None
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
    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, (
                comment_dict["comment_id"], comment_dict["weibo_id"], comment_dict["post_id"],
                comment_dict["user_id"], comment_dict["username"], comment_dict["content"],
                comment_dict["like_count"], comment_dict["created_time"], comment_dict["is_hot"]
            ))
        conn.commit()
        return cursor.rowcount
    except Exception as e:
        conn.rollback()
        _LOGGER.error(f"❌ upsert_comment 失败 comment_id={comment_dict.get('comment_id')}: {type(e).__name__}: {e}")
        raise


# ============================================================
# 采集 + 入库主流程
# ============================================================

def collect_and_store(user_id=None, keyword=None, max_posts=10,
                      max_comments_per_post=50, fetch_comments_flag=True):
    """
    采集并入库微博帖子 + 用户信息 + 评论
    帖子入库后自动抓取评论并关联 weibo_id / post_id
    单条失败不影响整体（异常隔离），写入结果通过日志输出去重统计
    返回 (post_count, user_count, comment_count)
    """
    conn = get_db_connection()
    post_ids = set()
    user_ids = set()
    total_comments = 0
    # 去重统计：1=新增, 2=更新, 0=重复无变化
    stats = {'insert': 0, 'update': 0, 'duplicate': 0, 'fail': 0}

    def _track(rowcount):
        """按 upsert 返回值累计去重统计（MySQL/TiDB rowcount：1=insert, 2=update, 0=no-change）"""
        if rowcount is None:
            return
        if rowcount == 1:
            stats['insert'] += 1
        elif rowcount >= 2:
            stats['update'] += 1
        else:
            stats['duplicate'] += 1

    def _store_one(mblog, source, topic):
        """处理单条微博：解析 → 入库用户/帖子 → 抓评论入库；失败仅记录，不中断"""
        try:
            post_dict, user_dict = parse_mblog(mblog)
            post_dict["source"] = source
            post_dict["topic"] = topic
            if not post_dict["weibo_id"]:
                return
            _track(upsert_user(conn, user_dict))
            _track(upsert_post(conn, post_dict))
            post_ids.add(post_dict["weibo_id"])
            user_ids.add(user_dict["user_id"])

            if fetch_comments_flag:
                post_id = get_post_id_by_weibo_id(conn, post_dict["weibo_id"])
                comments = fetch_comments(post_dict["weibo_id"], max_comments_per_post)
                for c in comments:
                    try:
                        c_dict = parse_comment(c, post_dict["weibo_id"], post_id, is_hot=1)
                        _track(upsert_comment(conn, c_dict))
                        total_comments_ref[0] += 1
                    except Exception as ce:
                        stats['fail'] += 1
                        _LOGGER.error(f"  ⚠️ 评论写入失败: {type(ce).__name__}: {ce}")
        except Exception as e:
            stats['fail'] += 1
            _LOGGER.error(f"⚠️ 微博处理失败: {type(e).__name__}: {e}")

    total_comments_ref = [0]

    try:
        # 通道 1：用户时间线
        if user_id:
            try:
                mblogs = fetch_user_timeline(user_id, page=1)
            except Exception as e:
                mblogs = []
                stats['fail'] += 1
                _LOGGER.error(f"⚠️ 用户时间线采集失败: {type(e).__name__}: {e}")
            for mblog in mblogs[:max_posts]:
                _store_one(mblog, "account", "")
            _LOGGER.info(f"✅ [账号] {user_id}: 处理 {min(len(mblogs), max_posts)} 帖, "
                         f"评论 {total_comments_ref[0]} 条")

        # 通道 2：关键词搜索
        if keyword:
            try:
                mblogs = fetch_keyword_search(keyword, page=1)
            except Exception as e:
                mblogs = []
                stats['fail'] += 1
                _LOGGER.error(f"⚠️ 关键词搜索采集失败: {type(e).__name__}: {e}")
            for mblog in mblogs[:max_posts]:
                _store_one(mblog, "keyword", keyword)
            _LOGGER.info(f"✅ [关键词] {keyword}: 处理 {min(len(mblogs), max_posts)} 帖, "
                         f"评论 {total_comments_ref[0]} 条")

    finally:
        conn.close()

    total_comments = total_comments_ref[0]
    _LOGGER.info("─" * 60)
    _LOGGER.info(f"📊 写入统计: 新增 {stats['insert']} | 更新 {stats['update']} | "
                 f"重复去重 {stats['duplicate']} | 失败 {stats['fail']}")
    return len(post_ids), len(user_ids), total_comments


def collect_realtime_window(keywords, target='today', per_keyword=15, max_pages=6,
                            max_comments=50, comment_post_limit=30,
                            fetch_comments_flag=True):
    """
    实时流（type=61）自然日增量采集 + 窗口内帖子评论补采。

    - 只保留发布时间落在目标自然日窗口 [day_start, day_end) 的帖子；
    - 实时流按时间倒序，翻页一旦遇到早于窗口的帖子即停止翻页；
    - 跨关键词按 weibo_id 去重；upsert 幂等，可重复执行不产生重复；
    - 评论只补采窗口内、评论数最高的 comment_post_limit 条帖子，不扫历史积压。

    返回统计 dict：候选数 / 新增 / 更新 / 去重 / 失败 / 评论写入动作 / 前后表行数。
    """
    day_start, day_end, date_str = resolve_day_window(target)
    _LOGGER.info("=" * 60)
    _LOGGER.info(f"⚡ 实时流自然日采集：目标日 {date_str}，窗口 [{day_start}, {day_end})")
    _LOGGER.info(f"   关键词 {len(keywords)} 个 | 每词≤{per_keyword} 帖 | 最多翻 {max_pages} 页"
                 f" | 评论帖≤{comment_post_limit} | 每帖≤{max_comments} 评论")
    _LOGGER.info("=" * 60)

    try:
        before = table_counts()
        _LOGGER.info(f"📡 数据库模式: {db_mode()} | 采集前 posts={before.get('weibo_posts', 0)}, "
                     f"comments={before.get('weibo_comments', 0)}, users={before.get('weibo_users', 0)}")
    except Exception as e:
        _LOGGER.error(f"❌ 数据库连接自检失败: {type(e).__name__}: {e}")
        return {'ok': False, 'error': str(e)}

    # 评论状态回写（复用批量评论采集器，失败则降级为不回写状态）
    try:
        import weibo_comment_batch_collector as C
        update_status = C.update_post_comment_status
    except Exception:
        def update_status(conn, wid, status, n):
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE weibo_posts SET comment_crawl_status=%s WHERE weibo_id=%s",
                        (status, wid))
                conn.commit()
            except Exception:
                conn.rollback()

    stats = {'insert': 0, 'update': 0, 'dup': 0, 'fail': 0}

    def _track(rc):
        if rc is None:
            return
        if rc == 1:
            stats['insert'] += 1
        elif rc >= 2:
            stats['update'] += 1
        else:
            stats['dup'] += 1

    # 1) 实时流搜索，跨词去重收集窗口内 mblog
    seen, window_posts = set(), []
    conn = get_db_connection()
    try:
        for kw in keywords:
            got = 0
            for page in range(1, max_pages + 1):
                try:
                    mbs = fetch_realtime_search(kw, page=page)
                except Exception as e:
                    stats['fail'] += 1
                    _LOGGER.warning(f"  ⚠️ 「{kw}」第{page}页请求异常: {type(e).__name__}: {e}")
                    break
                if not mbs:
                    break
                stop = False
                for mb in mbs:
                    try:
                        pd, _ud = parse_mblog(mb)
                    except Exception:
                        continue
                    pt = pd.get('publish_time') or ''
                    if not pt:
                        continue
                    if day_start <= pt < day_end:
                        wid = pd['weibo_id']
                        if wid and wid not in seen and got < per_keyword:
                            seen.add(wid)
                            window_posts.append((mb, kw))
                            got += 1
                    elif pt < day_start:
                        # 实时流倒序，遇到窗口之前的帖子即可停止翻页
                        stop = True
                if stop or got >= per_keyword:
                    break
                smart_delay()
            _LOGGER.info(f"  关键词「{kw}」窗口内选取 {got} 帖")

        # 2) 入库 用户 + 帖子
        stored = []
        for mb, kw in window_posts:
            try:
                pd, ud = parse_mblog(mb)
                pd['source'], pd['topic'] = 'keyword', kw
                if not pd['weibo_id']:
                    continue
                _track(upsert_user(conn, ud))
                _track(upsert_post(conn, pd))
                stored.append(pd)
            except Exception as e:
                stats['fail'] += 1
                _LOGGER.error(f"  ⚠️ 帖子入库失败: {type(e).__name__}: {e}")
        _LOGGER.info(f"窗口候选 {len(window_posts)} 条 | 写入统计 {stats}")

        # 3) 窗口内评论补采（仅评论数最高的若干帖）
        new_comments = 0
        if fetch_comments_flag:
            cand = sorted([p for p in stored if (p.get('comment_count') or 0) > 0],
                          key=lambda x: x['comment_count'], reverse=True)[:comment_post_limit]
            _LOGGER.info(f"💬 窗口内有评论的帖子 {sum(1 for p in stored if (p.get('comment_count') or 0) > 0)} 条，"
                         f"本次补采 Top{len(cand)}")
            for i, pd in enumerate(cand, 1):
                wid = pd['weibo_id']
                try:
                    cs = fetch_comments(wid, max_comments)
                    post_id = get_post_id_by_weibo_id(conn, wid)
                    for c in cs:
                        try:
                            cd = parse_comment(c, wid, post_id, 1)
                            if upsert_comment(conn, cd) == 1:
                                new_comments += 1
                        except Exception as ce:
                            stats['fail'] += 1
                            _LOGGER.error(f"  ⚠️ 评论写入失败: {type(ce).__name__}: {ce}")
                    update_status(conn, wid, 1, len(cs))
                    _LOGGER.info(f"  评论 {i}/{len(cand)} {wid[:12]} 评{pd['comment_count']} 抓{len(cs)}")
                except Exception as e:
                    update_status(conn, wid, 2, 0)
                    stats['fail'] += 1
                    _LOGGER.warning(f"  ⚠️ 抓评论失败 {wid[:12]}: {type(e).__name__}: {e}")
    finally:
        conn.close()

    try:
        after = table_counts()
        _LOGGER.info("📈 采集后行数对比:")
        for t in ('weibo_posts', 'weibo_comments', 'weibo_users'):
            b = before.get(t, 0); a = after.get(t, 0)
            _LOGGER.info(f"  {t}: {b} → {a} （净增 {a - b}）")
    except Exception as e:
        after = {}
        _LOGGER.warning(f"⚠️ 采集后行数统计失败: {type(e).__name__}: {e}")

    result = {
        'ok': True, 'date': date_str, 'candidates': len(window_posts),
        'new_comments': new_comments, 'before': before, 'after': after, **stats,
    }
    _LOGGER.info("=" * 60)
    _LOGGER.info(f"✅ 实时流采集完成：{date_str} 候选 {len(window_posts)}，"
                 f"新增 {stats['insert']} / 更新 {stats['update']} / 去重 {stats['dup']} / "
                 f"失败 {stats['fail']}，评论写入动作 {new_comments}")
    _LOGGER.info("=" * 60)
    return result


# ============================================================
# 采集入口（配置驱动）
# ============================================================

def main():
    import argparse
    from crawl_config import load_crawl_config

    parser = argparse.ArgumentParser(
        description='微博帖子+评论采集（配置驱动：config/crawl_config.json）',
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument('--config', help='采集配置文件路径（默认 config/crawl_config.json，可用 CRAWL_CONFIG 环境变量覆盖）')
    parser.add_argument('--keyword', action='append', default=None, help='追加采集关键词（可多次传，如 --keyword 豆包 --keyword AI办公）')
    parser.add_argument('--user-id', action='append', default=None, help='追加采集用户 uid（可多次传）')
    parser.add_argument('--max-posts', type=int, default=None, help='mixed 模式每通道最多帖子数 / realtime 模式每词上限（覆盖配置）')
    parser.add_argument('--max-comments', type=int, default=None, help='每帖最多评论数（覆盖配置文件）')
    parser.add_argument('--no-comments', action='store_true', help='跳过评论采集（只采帖子+用户）')
    parser.add_argument('--mode', choices=['realtime', 'mixed'], default=None,
                        help='采集模式：realtime=实时流按自然日增量（默认）；mixed=旧综合排序')
    parser.add_argument('--target', default=None,
                        help="采集目标自然日：today（默认）/ yesterday / YYYY-MM-DD（仅 realtime 生效）")
    parser.add_argument('--max-pages', type=int, default=None, help='实时流每关键词最多翻页数（覆盖配置）')
    args = parser.parse_args()

    # 1. 读取配置（命令行 > 环境变量 > 默认配置文件）
    cfg = load_crawl_config(args.config)
    keywords = list(cfg['keywords']) + (args.keyword or [])
    users = list(cfg['users']) + (args.user_id or [])
    max_posts = args.max_posts if args.max_posts is not None else cfg['max_posts']
    max_comments = args.max_comments if args.max_comments is not None else cfg['max_comments']
    fetch_comments_flag = not args.no_comments
    mode = args.mode or cfg.get('search_mode', 'realtime')
    target = args.target or cfg.get('collect_target', 'today')
    max_pages = args.max_pages if args.max_pages is not None else cfg.get('max_pages', 6)
    per_keyword = args.max_posts if args.max_posts is not None else cfg.get('per_keyword', max_posts)
    comment_post_limit = cfg.get('comment_post_limit', 30)

    _LOGGER.info("=" * 60)
    _LOGGER.info("微博帖子+评论采集（配置驱动）")
    _LOGGER.info(f"配置文件: {cfg['source']} | 模式: {mode} | 目标日: {target}")
    _LOGGER.info(f"关键词 ({len(keywords)}): {keywords if keywords else '无'}")
    _LOGGER.info(f"用户   ({len(users)}): {users if users else '无'}")
    _LOGGER.info(f"每词≤{per_keyword} 帖 | 翻页≤{max_pages} | 每帖≤{max_comments} 评论 | 抓评论: {fetch_comments_flag}")
    _LOGGER.info("=" * 60)

    if not keywords and not users:
        _LOGGER.warning("⚠️ 配置中没有关键词也没有用户，本次采集跳过（请编辑 config/crawl_config.json）")
        return

    # 2. 实时流自然日增量采集（默认，每日无人值守主链路）
    if mode == 'realtime' and keywords:
        result = collect_realtime_window(
            keywords, target=target, per_keyword=per_keyword, max_pages=max_pages,
            max_comments=max_comments, comment_post_limit=comment_post_limit,
            fetch_comments_flag=fetch_comments_flag,
        )
        # 用户时间线（配置了 users 时仍走旧通道，与自然日窗口独立）
        for uid in users:
            try:
                collect_and_store(user_id=uid, keyword=None, max_posts=max_posts,
                                  max_comments_per_post=max_comments,
                                  fetch_comments_flag=fetch_comments_flag)
            except Exception as e:
                _LOGGER.error(f"⚠️ 用户时间线 {uid} 采集失败: {type(e).__name__}: {e}")
        if not result.get('ok'):
            sys.exit(1)
        if result.get('fail', 0):
            _LOGGER.error('❌ 实时流采集有失败项，本次以非零状态退出，避免调度器发布不完整日报')
            sys.exit(1)
        return

    # 3. mixed 旧模式：按配置逐通道采集（用户时间线 + 每关键词综合排序第 1 页）
    try:
        before = table_counts()
        _LOGGER.info(f"📡 数据库模式: {db_mode()}（生产 TiDB / 开发本地 MySQL）")
        _LOGGER.info(f"📡 采集前行数: posts={before.get('weibo_posts', 0)}, "
                     f"comments={before.get('weibo_comments', 0)}, "
                     f"users={before.get('weibo_users', 0)}")
    except Exception as e:
        _LOGGER.error(f"❌ 数据库连接自检失败: {type(e).__name__}: {e}")
        _LOGGER.error("请检查 DATABASE_URL（生产 TiDB）或 MYSQL_*（本地 MySQL）配置")
        return

    total_posts = total_users = total_comments = 0
    for uid in users:
        p, u, c = collect_and_store(
            user_id=uid, keyword=None,
            max_posts=max_posts, max_comments_per_post=max_comments,
            fetch_comments_flag=fetch_comments_flag,
        )
        total_posts += p; total_users += u; total_comments += c
    for kw in keywords:
        p, u, c = collect_and_store(
            user_id=None, keyword=kw,
            max_posts=max_posts, max_comments_per_post=max_comments,
            fetch_comments_flag=fetch_comments_flag,
        )
        total_posts += p; total_users += u; total_comments += c

    _LOGGER.info(f"\n汇总: {total_posts} 帖, {total_users} 用户, {total_comments} 评论")

    try:
        after = table_counts()
        _LOGGER.info("\n" + "─" * 60)
        _LOGGER.info("📈 采集后行数对比:")
        for t in ('weibo_posts', 'weibo_comments', 'weibo_users'):
            b = before.get(t, 0)
            a = after.get(t, 0)
            _LOGGER.info(f"  {t}: {b} → {a} （净增 {a - b}）")
    except Exception as e:
        _LOGGER.warning(f"⚠️ 采集后行数统计失败: {type(e).__name__}: {e}")

    _LOGGER.info("\n" + "=" * 60)
    _LOGGER.info("采集完成，请在 MySQL/TiDB 中验证：")
    _LOGGER.info("  SELECT topic, COUNT(*) FROM weibo_posts GROUP BY topic;   -- 按关键词统计")
    _LOGGER.info("  SELECT COUNT(*) FROM weibo_comments;   -- 评论总数")
    _LOGGER.info("  SELECT comment_id, COUNT(*) AS dup FROM weibo_comments GROUP BY comment_id HAVING dup > 1;  -- 重复检查（应为空）")
    _LOGGER.info("=" * 60)


if __name__ == "__main__":
    main()
