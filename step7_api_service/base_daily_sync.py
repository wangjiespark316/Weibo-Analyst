"""Idempotent T-1 AI daily Top 10 sync to the Feishu Base table."""

import fcntl
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from .services import get_hot_weibo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
BJ_TZ = timezone(timedelta(hours=8))
KEYWORDS = 'AI,人工智能,大模型,智能体,Agent,飞书,豆包,ChatGPT,Claude,Copilot,WorkBuddy,AI办公,AI助手'
BASE_TOKEN = os.getenv('FEISHU_DAILY_BASE_TOKEN', 'NRS9bfc2dabZvJsM133csK8Inee')
TABLE_ID = os.getenv('FEISHU_DAILY_TABLE_ID', 'tblBL0YqGzZlvFon')
API_ROOT = f'https://open.feishu.cn/open-apis/bitable/v1/apps/{BASE_TOKEN}/tables/{TABLE_ID}'


def _request(method, url, token=None, **kwargs):
    headers = kwargs.pop('headers', {})
    if token:
        headers['Authorization'] = f'Bearer {token}'
    response = requests.request(method, url, headers=headers, timeout=20, **kwargs)
    response.raise_for_status()
    result = response.json()
    if result.get('code') != 0:
        raise RuntimeError(f'Feishu API {result.get("code")}: {result.get("msg")}')
    return result.get('data') or {}


# 仅对网络抖动 / 限流 / 网关错误重试；飞书业务错误（权限、字段、参数）快速失败。
_RETRY_STATUS = {429, 500, 502, 503, 504}


def _request_with_retry(method, url, token=None, max_retries=3, **kwargs):
    headers = kwargs.pop('headers', {})
    if token:
        headers['Authorization'] = f'Bearer {token}'
    last_exc = None
    for attempt in range(max_retries):
        try:
            response = requests.request(method, url, headers=headers, timeout=20, **kwargs)
            response.raise_for_status()
            result = response.json()
            if result.get('code') != 0:
                # 飞书业务错误：重试无益，立即抛出
                raise RuntimeError(
                    f'Feishu API {result.get("code")}: {result.get("msg")}')
            return result.get('data') or {}
        except RuntimeError:
            raise
        except requests.HTTPError as exc:
            last_exc = exc
            status = getattr(exc.response, 'status_code', 0)
            if status in _RETRY_STATUS and attempt < max_retries - 1:
                time.sleep(2 ** attempt)  # 1s, 2s, 4s
                continue
            raise
        except (requests.ConnectionError, requests.Timeout) as exc:
            last_exc = exc
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
                continue
            raise
    raise last_exc


def _token():
    app_id, app_secret = os.getenv('FEISHU_APP_ID'), os.getenv('FEISHU_APP_SECRET')
    if not app_id or not app_secret:
        raise RuntimeError('FEISHU_APP_ID / FEISHU_APP_SECRET missing')
    response = requests.post('https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal',
                             json={'app_id': app_id, 'app_secret': app_secret}, timeout=20)
    response.raise_for_status()
    data = response.json()
    if data.get('code') != 0 or not data.get('tenant_access_token'):
        raise RuntimeError(f'Feishu token error: {data.get("code")} {data.get("msg")}')
    return data['tenant_access_token']


def _plain_text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return ''.join(_plain_text(item) for item in value)
    if isinstance(value, dict):
        return value.get('text') or value.get('link') or ''
    return ''


def _post_id(value):
    match = re.search(r'm\.weibo\.cn/detail/(\d+)', _plain_text(value))
    return match.group(1) if match else None


def _existing_ids(token):
    found = set()
    page_token = None
    while True:
        params = {'page_size': 500}
        if page_token:
            params['page_token'] = page_token
        data = _request_with_retry('GET', f'{API_ROOT}/records', token, params=params)
        for record in data.get('items') or []:
            post_id = _post_id((record.get('fields') or {}).get('微博链接'))
            if post_id:
                found.add(post_id)
        if not data.get('has_more'):
            return found
        page_token = data.get('page_token')
        if not page_token:
            raise RuntimeError('Feishu Base pagination missing page_token')


def _date_text(value):
    # 多维表「日期」是文本字段，历史格式 'YYYY-MM-DDTHH:MM:SS'；
    # publish_time 可能是 datetime 对象，直接放入会导致 JSON 序列化失败。
    if isinstance(value, datetime):
        return value.strftime('%Y-%m-%dT%H:%M:%S')
    if value:
        return str(value)
    return ''


def _fields(post):
    return {
        '标题': post.get('content') or '',
        '日期': _date_text(post.get('publish_time')),
        '来源': '微博',
        '作者': post.get('username') or '',
        '微博链接': post['url'],
        '热度': float(post.get('hotspot_score') or 0),
        '原始内容': post.get('content') or '',
    }


def _freeze_authority(date, posts):
    """落表后冻结当次权威 id 全集，作为每日核对的同源基准 logs/frozen_hot/<date>.json。"""
    frozen_dir = PROJECT_ROOT / 'logs' / 'frozen_hot'
    frozen_dir.mkdir(parents=True, exist_ok=True)
    ids = []
    for post in posts:
        post_id = _post_id(post.get('url'))
        if post_id and post_id not in ids:
            ids.append(post_id)
    payload = {
        'date': date,
        'frozen_at': datetime.now(BJ_TZ).isoformat(),
        'dataset_type': 'ai_industry',
        'review_pool': 25,
        'output_top': 10,
        'keyword': None,
        'count': len(ids),
        'ids': ids,
    }
    target = frozen_dir / f'{date}.json'
    tmp = frozen_dir / f'{date}.json.tmp'
    with open(tmp, 'w', encoding='utf-8') as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, target)
    return str(target)


def sync_yesterday(dry_run=False, date=None):
    if not date:
        date = (datetime.now(BJ_TZ).date() - timedelta(days=1)).isoformat()
    marker = PROJECT_ROOT / 'logs' / 'crawl_ready' / f'{date}.json'
    if not marker.is_file():
        raise RuntimeError(f'{date} daily crawl is not complete')
    lock_path = PROJECT_ROOT / 'logs' / 'base_daily_sync.lock'
    lock_path.parent.mkdir(exist_ok=True)
    with open(lock_path, 'w') as lock_file:
        fcntl.flock(lock_file, fcntl.LOCK_EX)
        # 权威口径=相关性宽召回（无显式关键词硬过滤），由 ai_industry 相关性正则
        # + LLM 清洗把关；marker mtime 作为最终补采后的缓存键。落表与核对同源。
        result = get_hot_weibo(limit=25, dataset_type='ai_industry',
                               keyword=None, date=date,
                               cache_version=str(marker.stat().st_mtime_ns))
        if 'total_count' not in result:
            raise RuntimeError('Hot Weibo query failed; no Base rows written')
        # LLM 在 25 条评审池上做相关性/聚簇（视野足够，不漏热度稍低的核心事件）；
        # 最终确定性封顶 10 条（data 已按热度降序）。
        posts = (result.get('data') or [])[:10]
        token = _token()
        existing = _existing_ids(token)
        created = skipped = 0
        for post in posts:
            post_id = _post_id(post.get('url'))
            if not post_id:
                raise RuntimeError('Hot Weibo item has no canonical detail URL')
            if post_id in existing:
                skipped += 1
                continue
            if not dry_run:
                _request_with_retry('POST', f'{API_ROOT}/records', token,
                                    json={'fields': _fields(post)})
            existing.add(post_id)
            created += 1
        frozen_path = (_freeze_authority(date, posts)
                       if not dry_run else None)
        return {'date': date, 'selected': len(posts),
                'created': created, 'skipped': skipped, 'dry_run': dry_run,
                'frozen': frozen_path}


if __name__ == '__main__':
    from dotenv import load_dotenv
    load_dotenv(str(PROJECT_ROOT / '.env'))
    print(sync_yesterday())
