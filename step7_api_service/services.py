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
import hashlib
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
_CACHE_MAX_SIZE = int(os.getenv('API_CACHE_MAX_SIZE', '50'))

# 文件缓存目录
_CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.api_cache')
os.makedirs(_CACHE_DIR, exist_ok=True)

# 缓存 TTL：默认 30 分钟（Render 免费实例 15 分钟休眠，30 分钟确保休眠后仍有效）
_CACHE_TTL = int(os.getenv('API_CACHE_TTL', '900'))

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


# ---- 稳定结论缓存（长 TTL，按数据指纹复用，跳过 calc/enrich/LLM 重算）----
# 独立子目录，避免被启动时的 _clear_expired_cache（只清顶层 .json）误删。
_STABLE_DIR = os.path.join(_CACHE_DIR, 'stable')
os.makedirs(_STABLE_DIR, exist_ok=True)
# 稳定缓存 TTL：默认 7 天，仅作结论结构升级后的兜底失效；是否命中仍以数据指纹为准。
_STABLE_CACHE_TTL = int(os.getenv('STABLE_CACHE_TTL', str(7 * 24 * 3600)))


def _stable_file_path(key: str) -> str:
    safe_key = key.replace(':', '_').replace('/', '_').replace(' ', '_')
    return os.path.join(_STABLE_DIR, f'{safe_key}.json')


def _get_stable(key: str):
    """读取稳定结论缓存，返回 {fingerprint, result, ts} 或 None。"""
    fpath = _stable_file_path(key)
    if not os.path.exists(fpath):
        return None
    try:
        if time.time() - os.path.getmtime(fpath) >= _STABLE_CACHE_TTL:
            os.remove(fpath)
            return None
        with open(fpath, 'r', encoding='utf-8') as f:
            payload = json.load(f)
        if isinstance(payload, dict) and payload.get('fingerprint') and 'result' in payload:
            return payload
    except Exception:
        pass
    return None


def _set_stable(key: str, fingerprint: str, result):
    """写入稳定结论缓存（数据指纹 + 结论）。"""
    try:
        fpath = _stable_file_path(key)
        with open(fpath, 'w', encoding='utf-8') as f:
            json.dump({'fingerprint': fingerprint, 'result': result,
                       'ts': time.time()}, f, ensure_ascii=False, default=str)
    except Exception:
        pass


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


# ============================================================
# 重计算并发护栏（防止客户端超时后线程堆积、内存触顶卡死）
# ============================================================
# 背景：本服务端点为同步 def，运行在 anyio 线程池；客户端（scheduler）
# 120s 超时断开后，服务端正在重计算的线程【不会被取消】，仍继续持有全天
# 帖子全文 / jieba / SnowNLP / LLM 等大对象。若此时重跑，多个重计算线程
# 并发、内存叠加，会突破 MemoryHigh 触发内核节流、公开端点挂起。两道护栏：
#   1) 信号量：同时进行的 cache-miss 重计算总数有上限（默认 2）；
#   2) Single-flight：相同 cache_key 的并发 miss 只计算一次，其余共享结果。
_HEAVY_MAX_CONCURRENCY = max(1, int(os.getenv('HEAVY_MAX_CONCURRENCY', '2')))
_heavy_semaphore = threading.BoundedSemaphore(_HEAVY_MAX_CONCURRENCY)
_inflight_lock = threading.Lock()
_inflight_event = {}   # cache_key -> Event（计算结束标志，不分成功/失败）
# 等待 / 抢信号量的上限（秒）：略小于客户端 120s，让等待者能在客户端超时前降级
_WAIT_SECONDS = float(os.getenv('HEAVY_WAIT_SECONDS', '110'))


def _cache_or_fallback(cache_key, fallback, tag):
    """计算未就绪/失败时的统一降级：先缓存、再 fallback，都没有则抛超时。"""
    cached = _get_cache(cache_key)
    if cached is not None:
        print(f'[FALLBACK] {tag}：使用缓存数据')
        return cached, True
    if fallback is not None:
        print(f'[FALLBACK] {tag}：使用降级数据')
        return fallback, True
    return None, False


def _safe_call(func, *args, cache_key=None, fallback=None, **kwargs):
    """
    带缓存、重计算并发护栏（信号量 + single-flight）和降级回退的统一调用。

    Args:
        func: 要执行的重计算函数
        cache_key: 缓存 key（同时用作 single-flight 去重键）
        fallback: 最终降级数据
    """
    # 先查缓存
    if cache_key:
        cached = _get_cache(cache_key)
        if cached is not None:
            return cached

    # 无 cache_key 的调用不纳入护栏，直接执行（保持原行为）
    if not cache_key:
        try:
            return func(*args, **kwargs)
        except Exception:
            if fallback is not None:
                return fallback
            raise

    # ---- Single-flight 协调：相同 key 只允许一个 owner 计算 ----
    is_owner = False
    with _inflight_lock:
        ev = _inflight_event.get(cache_key)
        if ev is None:
            ev = threading.Event()
            _inflight_event[cache_key] = ev
            is_owner = True

    if not is_owner:
        # 等待者：阻塞等同一结果，不重复加载数据（owner 成功会先写缓存再置位）
        if ev.wait(timeout=_WAIT_SECONDS):
            data, ok = _cache_or_fallback(cache_key, fallback, '同key计算已结束')
            if ok:
                return data
            raise RuntimeError(f'heavy compute for {cache_key} failed with no cache')
        # 等待超时：owner 仍在算（结束后会写缓存）；本请求不叠加并发，直接降级
        data, ok = _cache_or_fallback(cache_key, fallback, f'同key计算超过{_WAIT_SECONDS:.0f}s')
        if ok:
            return data
        raise TimeoutError(f'heavy compute for {cache_key} still running')

    # ---- Owner：先抢信号量（限总并发），再执行重计算 ----
    if not _heavy_semaphore.acquire(timeout=_WAIT_SECONDS):
        # 重计算并发已满且长时间不释放：放弃本次重计算（不新增内存压力），降级
        with _inflight_lock:
            ev.set()
            _inflight_event.pop(cache_key, None)
        data, ok = _cache_or_fallback(cache_key, fallback,
                                      f'重计算并发已满({_HEAVY_MAX_CONCURRENCY})')
        if ok:
            return data
        raise TimeoutError('heavy compute concurrency limit reached')

    start = time.time()
    try:
        result = func(*args, **kwargs)
        elapsed = time.time() - start
        if elapsed > _TIMEOUT_SECONDS:
            print(f'[WARN] 接口耗时 {elapsed:.1f}s 超过阈值 {_TIMEOUT_SECONDS}s，但已完成')
        _set_cache(cache_key, result)   # 先写缓存（等待者随后即可命中）
        return result
    except Exception as e:
        elapsed = time.time() - start
        print(f'[ERROR] 接口执行失败 ({elapsed:.1f}s): {e}')
        data, ok = _cache_or_fallback(cache_key, fallback, '计算异常')
        if ok:
            return data
        raise
    finally:
        # 再通知等待者（此时成功路径的缓存已就绪），清理 inflight，释放信号量
        with _inflight_lock:
            ev.set()
            _inflight_event.pop(cache_key, None)
        try:
            _heavy_semaphore.release()
        except ValueError:
            pass


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


# ---------- 评论级轻量情感（替代 SnowNLP） ----------
# SnowNLP 在 import 时一次性加载全套模型（POS HMM 等）常驻约 410MB，小机会被
# MemoryHigh 节流拖垮；改用词典 + 否定反转，内存近乎为 0。按最长词挖空，避免
# “很好用”被“好用/好”重复计数。
_CMT_NEGATORS = ('没有', '不是', '不会', '不能', '没法', '难以',
                  '没', '不', '无', '别', '未', '莫', '甭')
_CMT_POS_WORDS = (
    '强烈推荐', '值得推荐', '值得买', '非常满意', '很满意', '好评如潮', '好评',
    '很好用', '太好用', '真好用', '挺好用', '非常好', '特别好', '很好',
    '太棒了', '太好了', '厉害了', '真香', '绝绝子', 'yyds', '黑科技',
    '爱了爱了', '爱了', '牛批', '牛逼', '好用', '实用', '流畅', '清晰',
    '稳定', '给力', '惊艳', '惊喜', '优秀', '完美', '值得', '推荐', '满意', '方便',
    '高效', '强大', '智能', '喜欢', '期待', '感谢', '支持', '不错', '舒服',
    '顺手', '省心', '先进', '创新', '提升', '棒', '赞', '牛', '强', '稳',
)
_CMT_NEG_WORDS = (
    '不好用', '很难用', '不能用', '没法用', '用不了', '打不开', '闪退',
    '崩溃', '报错', '卡死了', '卡死', '卡顿', '智商税', '割韭菜', '虚假宣传',
    '上当受骗', '上当', '被骗', '后悔买', '后悔', '人工智障', '拉胯', '拉跨',
    '差评如潮', '差评', '垃圾', '糟糕', '失望', '投诉', '难用', '讨厌',
    '反对', '废物', '不满', '问题', '恶心', '无语', '智障', '骗人', '坑人',
    'bug', '烂', '差', '慢', '贵', '坑', '烦', '假', '弱',
)


# 否定检测：从情感词向前，穿过副词/虚词（是、很、什么、特别、有…）找否定字；
# 遇分句标点或其它实词即停（避免把上一分句的否定误套到本词）。
_NEG_CHARS = set('不没无未莫甭')
_NEG_FILLERS = set('是很太什么怎那这么大算够再已还真特别十分非常如何点的有别')


def _negated_before(t, idx):
    j = idx - 1
    while j >= 0:
        ch = t[j]
        if ch in '，。；！？、,.!?;:':
            return False
        if ch in _NEG_CHARS:
            return True
        if ch not in _NEG_FILLERS:
            return False
        j -= 1
    return False


def _comment_sentiment_label(text):
    """单条评论三分类（positive/neutral/negative）：轻量词典 + 否定反转。"""
    if not text:
        return 'neutral'
    t = text.lower()
    work = t
    pos = neg = 0
    words = [(w, 1) for w in _CMT_POS_WORDS] + [(w, -1) for w in _CMT_NEG_WORDS]
    for w, base in sorted(words, key=lambda x: -len(x[0])):
        idx = work.find(w)
        while idx != -1:
            cur = -base if _negated_before(t, idx) else base
            if cur > 0:
                pos += 1
            else:
                neg += 1
            work = work[:idx] + '\u0000' * len(w) + work[idx + len(w):]
            idx = work.find(w)
    if pos > neg:
        return 'positive'
    if neg > pos:
        return 'negative'
    return 'neutral'


def _enrich_post_ai_fields(posts, comments_per_post=6):
    """为热点帖子补真实 AI 字段（不改表结构，结果随热点接口缓存）：
    - category: 基于真实话题/正文的确定性 AI 类目
    - sentiment: 基于该帖高赞评论的轻量情感多数标签（positive/neutral/negative；无有效评论为 None）
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
    from collections import Counter
    for p in posts:
        wid = p.get('weibo_id')
        m = meta.get(wid, {})
        p['category'] = _classify_ai_category(m.get('topic'), p.get('content'))
        comments = grouped.get(wid, [])
        if comments:
            votes = [_comment_sentiment_label(text) for text in comments]
            p['sentiment'] = Counter(votes).most_common(1)[0][0]
        else:
            p['sentiment'] = None
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


# ---------- LLM 事件聚簇 + AI 相关性闸门（2026-09-29 加） ----------
def _parse_json_object(text):
    """从模型输出中解析 JSON 对象；失败返回 None。"""
    if not text:
        return None
    t = text.strip()
    if t.startswith("```json"):
        t = t[7:]
    elif t.startswith("```"):
        t = t[3:]
    if t.endswith("```"):
        t = t[:-3]
    t = t.strip()
    try:
        return json.loads(t)
    except Exception:
        try:
            i, j = t.find("{"), t.rfind("}")
            if i >= 0 and j > i:
                return json.loads(t[i:j + 1])
        except Exception:
            return None
    return None


def _llm_chat_json(system_prompt, user_prompt, max_tokens=1400, timeout=40):
    """调用 OpenAI 兼容接口（默认 DeepSeek），返回解析后的 dict；缺 key 或任何失败返回 None。"""
    api_key = os.getenv("LLM_API_KEY")
    if not api_key:
        return None
    api_base = os.getenv("LLM_API_BASE", "https://api.deepseek.com/v1")
    model = os.getenv("LLM_MODEL", "deepseek-chat")
    try:
        import requests
        resp = requests.post(
            f"{api_base}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "max_tokens": max_tokens,
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
            },
            timeout=timeout,
        )
        if resp.status_code != 200:
            print(f"[llm-clean] api {resp.status_code}: {resp.text[:160]}", flush=True)
            return None
        content = resp.json()["choices"][0]["message"]["content"]
        return _parse_json_object(content)
    except Exception as e:
        print(f"[llm-clean] call failed: {type(e).__name__}: {e}", flush=True)
        return None


def _llm_select_and_cluster(posts):
    """LLM 做 AI 相关性闸门 + 同一事件聚簇。
    输入帖子已按热度降序；返回仅含保留帖（同事件只留 1 条）、并保持原热度顺序的列表。
    LLM 不可用/输出异常返回 None（调用方回退规则）；模型成功但无合格内容返回 []。"""
    if not posts:
        return posts
    cand = posts[:25]
    lines = []
    for i, p in enumerate(cand):
        wid = p.get("weibo_id")
        who = p.get("username") or p.get("author") or ""
        c = (p.get("content") or "").replace("\n", " ").strip()[:220]
        lines.append(f"[{i}] id={wid} @{who}: {c}")
    catalog = "\n".join(lines)

    system_prompt = (
        "你是资深 AI 行业情报编辑，负责为「AI 行业舆情日报」挑选当天真正值得看的微博。严格执行两件事：\n"
        "1) 相关性闸门：只保留与 AI 产业真正相关且有实质信息的内容，例如大模型、Agent、AI 产品、AI 芯片、"
        "AI 编程、AI 办公、企业 AI 应用、AI 公司动态、融资并购、政策监管；剔除娱乐八卦、明星广告、带货种草、"
        "纯情绪吐槽、个人碎碎念及一切与 AI 无关的内容——即使正文出现“AI”字样但本质是广告也要剔除。\n"
        "2) 事件聚簇：多条微博报道同一事件、同一次发布或同一进展时，只保留信息最全或热度最高的 1 条，"
        "其余视为重复，避免同一件事刷屏。\n"
        "只输出 JSON，不要任何解释。"
    )
    user_prompt = (
        "以下是候选微博（[序号] id=微博ID）：\n"
        f"{catalog}\n\n"
        "请输出 {\"keep\":[{\"index\": 序号, \"event\": \"一句话事件名\"}]}；"
        "同一事件只保留一条；宁精勿滥，没有真正 AI 内容时 keep 输出空数组 []。"
    )
    data = _llm_chat_json(system_prompt, user_prompt)
    if not data:
        return None
    keep = data.get("keep")
    if not isinstance(keep, list):
        return None
    keep_indexes = set()
    event_by_index = {}
    for item in keep:
        if not isinstance(item, dict):
            continue
        try:
            idx = int(item.get("index"))
        except (TypeError, ValueError):
            continue
        if 0 <= idx < len(cand):
            keep_indexes.add(idx)
            ev = item.get("event")
            if ev:
                event_by_index[idx] = str(ev)[:60]
    # 按原热度顺序收集（LLM 只做筛选/合并，不负责重排）
    chosen = []
    for idx, post in enumerate(cand):
        if idx in keep_indexes:
            if idx in event_by_index:
                post["event_name"] = event_by_index[idx]
            chosen.append(post)
    print(f"[llm-clean] in={len(cand)} keep={len(chosen)}", flush=True)
    return chosen


def _clean_daily_posts(posts):
    """每日热点清洗：规则（广告/低信息）初筛 → LLM 相关性闸门+事件聚簇；
    LLM 不可用或疑似误判全空时，回退到规则同话题去重，保证不阻塞、不跑空。"""
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

    # 规则兜底（LLM 不可用时的结果，行为与旧版一致）
    rule_out = _dedupe_same_topic(out)

    llm_out = None
    try:
        llm_out = _llm_select_and_cluster(out)
    except Exception as e:
        print(f"[llm-clean] error, fallback to rules: {type(e).__name__}: {e}", flush=True)
        llm_out = None

    if llm_out is None:
        print(f"[cleanup] in={len(posts)} drop_ad={dropped_ad} drop_low={dropped_low} "
              f"after_dedupe(rule)={len(rule_out)} | LLM unavailable, rules used", flush=True)
        return rule_out

    # 护栏：LLM 判空但规则侧仍有多条强 AI 相关帖，疑似误判 → 回退规则
    if not llm_out:
        strong = [p for p in rule_out if _is_ai_relevant(p.get("content", ""))]
        if len(strong) >= 3:
            print(f"[cleanup] LLM keep=0 but {len(strong)} strong-AI rule posts; fallback to rules", flush=True)
            return rule_out

    print(f"[cleanup] in={len(posts)} drop_ad={dropped_ad} drop_low={dropped_low} "
          f"rule={len(rule_out)} llm_event_keep={len(llm_out)}", flush=True)
    return llm_out
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
        # 自然日日报：正常日子加载全部符合帖以保证排名完整；极端日子候选过多时，
        # 只取按总互动量排序的前若干条，避免无界加载全文撑爆小内存（SQL 已按
        # 互动量 DESC，热点分由赞/评/转加权构成，较大候选池足以覆盖 top limit）。
        _date_candidate_cap = max(limit * 6, int(os.getenv('API_DATE_CANDIDATE_CAP', '120')))
        query_limit_sql = 'LIMIT %s'
        query_limit_n = _date_candidate_cap if date_sql else limit * 5

        # —— 数据指纹快速路径（省全文 / 省 calc / 省 enrich / 省 LLM）——
        # 只取候选帖标识与互动量（不取 content 全文），算数据指纹；若与上次结论
        # 指纹一致，说明候选集合一个没变，直接复用结论，跳过后续全部重算。
        _stable_key = f'stable:{cache_key}'
        _fingerprint = None
        try:
            fp_sql = f"""
                SELECT weibo_id, like_count, comment_count, repost_count
                FROM weibo_posts
                WHERE (like_count + comment_count + repost_count) >= %s
                {ds_sql}{kw_sql}{date_sql}{time_sql}{fresh_sql}{relevance_sql}
                ORDER BY (like_count + comment_count + repost_count) DESC
                {query_limit_sql}
            """
            fp_params = [min_engagement] + ds_params + kw_params + date_params + time_params + fresh_params + relevance_params
            fp_params.append(query_limit_n)
            fp_rows = db.fetch_all(fp_sql, tuple(fp_params))
            _fingerprint = hashlib.sha1('|'.join(
                f"{r['weibo_id']}:{r['like_count']}:{r['comment_count']}:{r['repost_count']}"
                for r in fp_rows).encode('utf-8')).hexdigest()
            _stable = _get_stable(_stable_key)
            if _stable and _stable.get('fingerprint') == _fingerprint:
                print(f'[STABLE-CACHE] HIT {cache_key[:48]} keep={_stable["result"].get("total")}')
                return _stable['result']
            print(f'[STABLE-CACHE] MISS fp={_fingerprint[:10]} rows={len(fp_rows)}')
        except Exception as _fe:
            print(f'[STABLE-CACHE] 指纹快速路径跳过: {type(_fe).__name__}: {_fe}')

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
        params.append(query_limit_n)
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
        # 数据截至时间：本批最新一条微博的发布时刻（100%来自数据，供前端展示真实新鲜度）
        def _parse_bj_pt(_pt):
            if _pt is None:
                return None
            if isinstance(_pt, datetime):
                return _pt.replace(tzinfo=_BJ_TZ) if _pt.tzinfo is None else _pt.astimezone(_BJ_TZ)
            if isinstance(_pt, str):
                _s = _pt.strip().replace("Z", "+00:00")
                _d = None
                # Python 3.10 fromisoformat 只认 T 分隔，兼容库里空格分隔的 "YYYY-MM-DD HH:MM:SS"
                for _cand in (_s, _s.replace(" ", "T")):
                    try:
                        _d = datetime.fromisoformat(_cand)
                        break
                    except ValueError:
                        continue
                if _d is None:
                    return None
                return _d.replace(tzinfo=_BJ_TZ) if _d.tzinfo is None else _d.astimezone(_BJ_TZ)
            return None
        _latest = None
        for _it in scored:
            _dpt = _parse_bj_pt(_it.get("publish_time"))
            if _dpt is not None and (_latest is None or _dpt > _latest):
                _latest = _dpt
        _data_as_of = _latest.isoformat() if _latest is not None else None
        result = {"total": len(scored), "total_count": total_count,
                  "data_as_of": _data_as_of, "data": scored}
        if _fingerprint:
            _set_stable(_stable_key, _fingerprint, result)
        return result

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
    - 默认采样 500 条（原 3000，上限 1000）
    - 纯轻量关键词/词典匹配（jieba 按需加载），不依赖 SnowNLP
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
