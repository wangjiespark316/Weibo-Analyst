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
import re
import time
import json
import signal
import threading
from typing import Optional
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager

# 北京时区（自然日口径统一用北京时间）
_BJ_TZ = timezone(timedelta(hours=8))
from concurrent.futures import ThreadPoolExecutor

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

# 归档数据集（dataset_type 以 archived 开头）为历史隔离区，不参与任何默认/全库
# 查询；仅在显式指定该数据集时才可追溯（如早期账号通道抓取的娱乐内容）。
_ACTIVE_DS_SQL = " AND (dataset_type IS NULL OR dataset_type NOT LIKE 'archived%%')"


def _ds_filter(dataset_type: Optional[str]) -> tuple:
    if dataset_type:
        return (" AND dataset_type = %s", [dataset_type])
    return (_ACTIVE_DS_SQL, [])


# ============================================================
# 1. 热点微博（轻量，已有缓存）
# ============================================================

# AI 垂类确定性分类（基于真实话题/正文关键词，非随机哈希）
_AI_CATEGORY_RULES = [
    ('coding', ['编程', '代码', '程序员', '开发者', '开发工具', 'copilot', 'cursor', 'codex', 'github', 'ai编程', '开发助手']),
    ('agent', ['agent', '智能体', 'agents', '多智能体']),
    ('hardware', ['手机', '芯片', '硬件', '机器人', '眼镜', '穿戴', '汽车', '车型', '算力', '英伟达', '昇腾', '骁龙', '终端', '设备', 'ai手机']),
    ('office', ['办公', '飞书', '豆包', 'workbuddy', '文档', '会议', '协同', '助手', '表格', 'im']),
    ('llm', ['大模型', '大语言模型', '模型', 'deepseek', '千问', 'gpt', 'chatgpt', 'claude', 'gemini', 'llm', '多模态', '推理模型', '开源模型']),
    ('enterprise', ['企业', '落地', '数字化', '转型', '私有化', '部署', '客服', '销售', '客户', '解决方案']),
    ('product', ['app', '应用', '产品', '上线', '发布', '推出', '功能', '新版本']),
]

# AI 垂类"正文相关性"词表：微博实时搜索会误返回无关帖（如搜"飞书"返回社会新闻），
# 只有正文（含话题标签，不含采集 topic 标记）真正命中 AI 词才算 AI 舆情。
# 英文词用 (?<![a-z])..(?![a-z]) 边界保护，避免 said/email/available 等含 ai 的普通词误判，
# 中文字符不算字母，保证"医疗影像AI""AI写作"等中文紧贴场景能命中。
_AI_RELEVANT_KW = [
    '飞书', '豆包', 'workbuddy', 'copilot', 'chatgpt', 'claude', 'openai', 'deepseek',
    '千问', '通义', '文心', '星火', 'gemini', 'cursor', 'codex', 'midjourney', 'kimi',
    '秘塔', '英伟达', '可灵', '即梦', 'sora', 'grok', 'llama',
    '人工智能', '大模型', '大语言模型', '智能体', '多智能体', '智能助手', 'ai助手', 'ai办公',
    'ai原生', 'ai手机', 'ai眼镜', 'ai硬件', 'ai玩车', 'ai工作站', 'ai赛道', 'ai写作',
    'ai编程', 'ai工具', 'ai应用', 'ai产品', 'ai技术', 'ai大模型', '生成式', '机器学习',
    '深度学习', '神经网络', '算力', '多模态', '智能客服', '智能硬件', '自动驾驶', '机器人',
    '智能标书', '智能写作', 'aigc',
]
_AI_RELEVANT_RE = re.compile(
    r'(?<![a-z])(' + '|'.join(re.escape(k) for k in _AI_RELEVANT_KW)
    + r'|ai|gpt|llm|agent|rag|mcp|nlp|ocr)(?![a-z])',
    re.IGNORECASE)

# Keep the SQL filter aligned with _is_ai_relevant so LIMIT and total_count
# describe the same set of posts. TiDB REGEXP was checked against the Python
# predicate on the 2026-09-19 ai_industry sample before deployment.
_AI_RELEVANT_SQL_RE = (
    r'(^|[^a-z])(' + '|'.join(re.escape(k.lower()) for k in _AI_RELEVANT_KW)
    + r'|ai|gpt|llm|agent|rag|mcp|nlp|ocr)([^a-z]|$)'
)


def _is_ai_relevant(content):
    """正文（不含采集 topic）是否真正与 AI 相关，用于剔除实时搜索误返回的无关帖。"""
    if not content:
        return False
    return bool(_AI_RELEVANT_RE.search(content.lower()))


def _classify_ai_category(topic, content):
    text = ((topic or '') + ' ' + (content or '')).lower()
    for key, kws in _AI_CATEGORY_RULES:
        for kw in kws:
            if kw in text:
                return key
    return 'news'


def _enrich_post_ai_fields(posts, comments_per_post=6):
    """为热点帖子补真实 AI 字段（不改表结构，结果随热点接口缓存）：
    - category: 基于真实话题/正文的确定性 AI 类目
    - sentiment: 基于该帖高赞评论的 SnowNLP 情感多数标签（positive/neutral/negative；无有效评论为 None）
    - ai_status: 评论是否已完成采集（done/pending，来自 comment_crawl_status）
    """
    if not posts:
        return posts
    ids = [p.get('weibo_id') for p in posts if p.get('weibo_id')]
    if not ids:
        return posts
    ph = ','.join(['%s'] * len(ids))
    try:
        meta_rows = db.fetch_all(
            f"SELECT weibo_id, topic, comment_crawl_status FROM weibo_posts WHERE weibo_id IN ({ph})",
            tuple(ids)) or []
        comment_rows = db.fetch_all(
            f"""SELECT weibo_id, content FROM (
                  SELECT weibo_id, content,
                         ROW_NUMBER() OVER (PARTITION BY weibo_id ORDER BY like_count DESC) AS rn
                  FROM weibo_comments WHERE weibo_id IN ({ph})
                ) t WHERE rn <= %s""",
            tuple(ids) + (comments_per_post,)) or []
    except Exception:
        for p in posts:
            p.setdefault('category', 'news'); p.setdefault('sentiment', None); p.setdefault('ai_status', 'pending')
        return posts
    meta = {r['weibo_id']: r for r in meta_rows}
    grouped = {}
    for r in comment_rows:
        t = (r.get('content') or '').strip()
        if t:
            grouped.setdefault(r['weibo_id'], []).append(t)
    try:
        from snownlp import SnowNLP
    except Exception:
        SnowNLP = None
    for p in posts:
        wid = p.get('weibo_id')
        m = meta.get(wid, {})
        p['category'] = _classify_ai_category(m.get('topic'), p.get('content'))
        label = None
        comments = grouped.get(wid, [])
        if SnowNLP and comments:
            pos = neu = neg = 0
            for text in comments:
                try:
                    sc = SnowNLP(text).sentiments
                except Exception:
                    continue
                if sc > 0.6:
                    pos += 1
                elif sc >= 0.4:
                    neu += 1
                else:
                    neg += 1
            if pos + neu + neg:
                label = max((('positive', pos), ('neutral', neu), ('negative', neg)),
                            key=lambda x: x[1])[0]
        p['sentiment'] = label
        p['ai_status'] = 'done' if m.get('comment_crawl_status') == 1 else 'pending'
    return posts




# ---------- 热点清洗（2026-09-24 加）：去广告/低信息量/同主题重复 ----------
import difflib as _difflib

_AD_BLACKLIST = [
    # 营销/带货话术
    "体验官", "先锋体验", "都在戴", "一直被", "被安利", "种草", "好物",
    "下单", "优惠券", "点击链接", "直播间", "拼单", "同款", "入手",
    "AI大厂", "工位上最伟大的单品", "跨语言对话", "翻译功能可以协助",
    "数码好物", "强烈推荐", "赶紧冲", "链接在",
    # 情绪吐槽/脏话短帖
    "你他妈", "什么意思", "什么鬼", "我真服", "离谱", "傻逼", "卧槽", "什么玩意", "气死我",
]

def _is_ad_or_spam(content):
    if not content:
        return False
    for kw in _AD_BLACKLIST:
        if kw in content:
            return True
    return False

def _is_low_info(content):
    if not content:
        return True
    plain = content.replace("#", "").replace("@", "").strip()
    if len(plain) < 25:
        # 短内容必须有实质信息（英文术语/数字/公司动作词）
        if not re.search(r"[A-Za-z]{2,}|[0-9]{2,}|发布|开源|融资|模型|芯片|汽车|收购|估值", plain):
            return True
    # 纯情绪发泄、无英文无数字无专业词的短帖
    if len(plain) < 45 and not re.search(r"[A-Za-z0-9]", plain):
        return True
    return False

def _content_signature(content):
    s = content or ""
    s = re.sub(r"#\S+#", "", s)
    s = re.sub(r"https?://\S+", "", s)
    s = re.sub(r"[@\[\]【】]", "", s)
    s = re.sub(r"[\s，。！？、；：“”‘’（）()…—\-~·,.!?;:]+", "", s)
    return s[:24]

def _dedupe_same_topic(posts, threshold=0.30):
    kept = []
    kept_topics = set()
    for p in posts:
        content = p.get("content", "") or ""
        # 1) 按 #话题# 去重：同话题只留最高分（posts 已按 hotspot 降序）
        topics = re.findall(r"#([^#]{2,30})#", content)
        if topics and any(t in kept_topics for t in topics):
            continue
        # 2) 按内容签名相似度去重
        sig = _content_signature(content)
        if not sig:
            kept.append(p)
            for t in topics: kept_topics.add(t)
            continue
        dup = False
        for k in kept:
            ksig = _content_signature(k.get("content", ""))
            if not ksig:
                continue
            if sig in ksig or ksig in sig:
                dup = True; break
            if _difflib.SequenceMatcher(None, sig, ksig).ratio() >= threshold:
                dup = True; break
        if not dup:
            kept.append(p)
            for t in topics: kept_topics.add(t)
    return kept

def _clean_daily_posts(posts):
    try:
        open('/tmp/cleanup_debug.log','a').write(f'called in={len(posts)}\n')
    except Exception: pass
    out = []
    dropped_ad = dropped_low = 0
    for p in posts:
        c = p.get("content", "") or ""
        if _is_ad_or_spam(c):
            dropped_ad += 1; continue
        if _is_low_info(c):
            dropped_low += 1; continue
        out.append(p)
    before = len(out)
    out = _dedupe_same_topic(out)
    print(f"[cleanup] in={len(posts)} drop_ad={dropped_ad} drop_low={dropped_low} after_dedupe={len(out)}", flush=True)
    return out
# ---------- 清洗 end ----------

def get_hot_weibo(limit: int = 20, min_engagement: int = 0,
                   dataset_type: Optional[str] = None,
                   keyword: Optional[str] = None,
                   days: Optional[int] = None,
                   fresh_hours: Optional[int] = None,
                   date: Optional[str] = None,
                   cache_version: Optional[str] = None):
    # 归一化静态关键字：飞书多维表格等无法动态拼日期的调用方直接传 yesterday/today（北京自然日）
    if date in ("yesterday", "today"):
        _today_bj = datetime.now(_BJ_TZ).date()
        _d = _today_bj if date == "today" else _today_bj - timedelta(days=1)
        date = _d.strftime("%Y-%m-%d")
    cache_key = f'hot_weibo:{limit}:{min_engagement}:{dataset_type or "all"}:{keyword or ""}:{days or 0}:{fresh_hours or 0}:{date or ""}:{cache_version or ""}'

    def _do():
        ds_sql, ds_params = _ds_filter(dataset_type)
        relevance_sql = "" if dataset_type == 'general_hotspot' else " AND LOWER(content) REGEXP %s"
        relevance_params = [] if dataset_type == 'general_hotspot' else [_AI_RELEVANT_SQL_RE]

        # 关键词过滤（多个关键词用逗号分隔，OR匹配）
        kw_sql = ""
        kw_params = []
        if keyword:
            keywords = [k.strip() for k in keyword.split(",") if k.strip()]
            if keywords:
                kw_clauses = " OR ".join(["content LIKE %s"] * len(keywords))
                kw_sql = f" AND ({kw_clauses})"
                kw_params = [f"%{k}%" for k in keywords]

        # 自然日过滤（精确北京日期 [YYYY-MM-DD 00:00:00, 次日00:00:00)，日报取数用）
        # date 与 days/fresh_hours 互斥、date 优先；库里 publish_time 存的是北京时刻
        date_sql = ""
        date_params = []
        if date:
            try:
                d0 = datetime.strptime(date, "%Y-%m-%d")
                d1 = d0 + timedelta(days=1)
                date_sql = " AND publish_time >= %s AND publish_time < %s"
                date_params = [d0.strftime("%Y-%m-%d %H:%M:%S"),
                               d1.strftime("%Y-%m-%d %H:%M:%S")]
            except (ValueError, TypeError):
                date_sql = ""
                date_params = []

        # 时间过滤（最近N天）
        time_sql = ""
        time_params = []
        if not date_sql and days and days > 0:
            time_sql = " AND publish_time >= DATE_SUB(NOW(), INTERVAL %s DAY)"
            time_params = [days]

        # 入库时间过滤（最近N小时首次入库，按入库时刻切分每日数据，相邻天天然互斥去重）
        fresh_sql = ""
        fresh_params = []
        if not date_sql and fresh_hours and fresh_hours > 0:
            fresh_sql = " AND crawl_time >= DATE_SUB(NOW(), INTERVAL %s HOUR)"
            fresh_params = [fresh_hours]

        # A natural-day report ranks every eligible post. Ranking only the
        # first limit*5 posts by raw engagement can omit higher hotspot scores.
        query_limit_sql = '' if date_sql else 'LIMIT %s'
        sql = f"""
            SELECT weibo_id, user_id, username, content, publish_time,
                   like_count, comment_count, repost_count, url
            FROM weibo_posts
            WHERE (like_count + comment_count + repost_count) >= %s
            {ds_sql}
            {kw_sql}
            {date_sql}
            {time_sql}
            {fresh_sql}
            {relevance_sql}
            ORDER BY (like_count + comment_count + repost_count) DESC
            {query_limit_sql}
        """
        params = [min_engagement] + ds_params + kw_params + date_params + time_params + fresh_params + relevance_params
        if query_limit_sql:
            params.append(limit * 5)
        posts = db.fetch_all(sql, tuple(params))
        # Count the exact same eligible set; the old count included rejected noise.
        count_sql = f"""
            SELECT COUNT(*) AS c
            FROM weibo_posts
            WHERE (like_count + comment_count + repost_count) >= %s
            {ds_sql}{kw_sql}{date_sql}{time_sql}{fresh_sql}{relevance_sql}
        """
        count_params = [min_engagement] + ds_params + kw_params + date_params + time_params + fresh_params + relevance_params
        try:
            total_count = int((db.fetch_one(count_sql, tuple(count_params)) or {}).get("c", len(posts)))
        except Exception:
            total_count = len(posts)
        scored = engine.calc_hotspot(posts, top_n=limit)
        for item in scored:
            pt = item.get("publish_time")
            if pt:
                if hasattr(pt, "timestamp"):
                    item["publish_timestamp"] = int(pt.timestamp() * 1000)
                elif isinstance(pt, str):
                    try:
                        dt = datetime.fromisoformat(pt.replace("Z", "+00:00"))
                        item["publish_timestamp"] = int(dt.timestamp() * 1000)
                    except Exception:
                        pass
        try:
            _enrich_post_ai_fields(scored)
        except Exception:
            for _it in scored:
                _it.setdefault('category', 'news')
                _it.setdefault('sentiment', None)
                _it.setdefault('ai_status', 'pending')
        scored = _clean_daily_posts(scored)
        return {"total": len(scored), "total_count": total_count, "data": scored}

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
                SELECT DATE(c.created_time) AS date, COUNT(*) AS cnt
                FROM weibo_comments c
                INNER JOIN weibo_posts p ON c.weibo_id = p.weibo_id
                WHERE c.content LIKE %s AND c.created_time >= %s
                  AND (p.dataset_type IS NULL OR p.dataset_type NOT LIKE 'archived%%')
                GROUP BY DATE(c.created_time) ORDER BY date
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
                  dataset_type: Optional[str] = None, date: Optional[str] = None):
    """
    情感分析（优化版）
    - 默认采样 500 条（原 3000）
    - 使用轻量关键词匹配 + 少量 SnowNLP 验证
    - 双层缓存
    """
    # 限制最大采样量，防止传入过大值
    sample_size = min(sample_size, 1000)
    cache_key = f'sentiment:{sample_size}:{keyword or "all"}:{dataset_type or "all"}:{date or "all"}'

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
                INNER JOIN weibo_posts p ON c.weibo_id = p.weibo_id
                WHERE c.content IS NOT NULL AND c.content != ''
                  AND (p.dataset_type IS NULL OR p.dataset_type NOT LIKE 'archived%%')
            """
            base_params = []

        # 可选：限定统计自然日（北京日期，按评论发布时间）
        date_sql = "\n                  AND DATE(c.created_time) = %s" if date else ""
        date_params = [date] if date else []

        if keyword:
            sql = f"""
                SELECT c.content, c.username, c.like_count, c.created_time
                {base_from}{date_sql}
                  AND c.content LIKE %s
                ORDER BY c.created_time DESC
                LIMIT %s
            """
            params = tuple(base_params + date_params + [f'%{keyword}%', sample_size])
        else:
            sql = f"""
                SELECT c.content, c.username, c.like_count, c.created_time
                {base_from}{date_sql}
                ORDER BY c.created_time DESC
                LIMIT %s
            """
            params = tuple(base_params + date_params + [sample_size])

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
        # 统计日（前一天，北京自然日）
        yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
        # AI 行业日报：未显式指定数据集时默认只统计 AI 行业采集库（ai_industry），
        # 排除早期账号/通用通道的 general_hotspot，避免娱乐等无关历史内容进入日报；
        # 品牌租户经 Bearer 鉴权后由 tenant.dataset_type 覆盖本默认值。
        hot_dataset = dataset_type or 'ai_industry'
        # 关键词：固定列表，复用 get_keyword_trend 缓存
        keywords_list = ['豆包', '飞书', 'AI办公', 'Agent', '企业AI',
                         'ChatGPT', '人工智能', '大模型', 'AIGC']

        def _kw_stat(kw):
            try:
                tr = get_keyword_trend(kw, days=30, dataset_type=hot_dataset)
                return {
                    'keyword': kw,
                    'post_mentions': tr.get('post_count', 0),
                    'comment_mentions': tr.get('comment_count', 0),
                    'total_mentions': tr.get('total_mentions', 0),
                }
            except Exception:
                return {'keyword': kw, 'post_mentions': 0,
                        'comment_mentions': 0, 'total_mentions': 0}

        # 数据概览：轻量 COUNT 查询（统计前一天数据）
        def _counts():
            try:
                posts_count = db.fetch_one(
                    'SELECT COUNT(*) AS c FROM weibo_posts WHERE dataset_type = %s AND DATE(publish_time) = %s',
                    (hot_dataset, yesterday))['c']
                comments_count = db.fetch_one(
                    '''SELECT COUNT(*) AS c FROM weibo_comments c
                       INNER JOIN weibo_posts p ON c.weibo_id = p.weibo_id
                       WHERE p.dataset_type = %s AND DATE(c.created_time) = %s''',
                    (hot_dataset, yesterday))['c']
                users_count = db.fetch_one('SELECT COUNT(*) AS c FROM weibo_users')['c']
                return {'posts': posts_count, 'comments': comments_count, 'users': users_count}
            except Exception:
                return {'posts': 0, 'comments': 0, 'users': 0}

        # 所有数据块相互独立、每次查询独立DB连接，一次性并行（热点+9关键词+情感+影响力+统计）
        # 原串行链路（热点→9关键词→情感→影响力→3统计）冷启动约11秒
        with ThreadPoolExecutor(max_workers=14) as ex:
            f_hot = ex.submit(lambda: get_hot_weibo(
                limit=20, dataset_type=hot_dataset, date=yesterday))
            kw_futs = {kw: ex.submit(_kw_stat, kw) for kw in keywords_list}
            f_sent = ex.submit(lambda: get_sentiment(sample_size=500, dataset_type=hot_dataset, date=yesterday))
            f_inf = ex.submit(lambda: get_influencers(sort_type='followers', limit=20,
                                                       dataset_type=hot_dataset))
            f_cnt = ex.submit(_counts)
            hotspot = f_hot.result()
            keywords = [kw_futs[kw].result() for kw in keywords_list]
            sentiment = f_sent.result()
            influencers = f_inf.result()
            stats = f_cnt.result()
        keywords.sort(key=lambda x: x['total_mentions'], reverse=True)

        # 生成 Markdown（传递前一天日期）
        report_date_str = (datetime.now() - timedelta(days=1)).strftime('%Y年%m月%d日')
        md = engine.generate_daily_report(stats, hotspot.get('data', []),
                                           keywords, sentiment, influencers,
                                           report_date=report_date_str)

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
        try:
            get_daily_report()
            print('[WARMUP] daily_report 预热完成')
        except Exception as e:
            print(f'[WARMUP] daily_report 预热失败: {e}')
        print('[WARMUP] 缓存预热完成')

    threading.Thread(target=_warmup, daemon=True).start()


# 模块加载时清理过期缓存
_clear_expired_cache()
