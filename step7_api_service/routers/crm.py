#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CRM 商机管理 API
数据来源：飞书多维表「商机管理」同步表 customer_opportunities（feishu_crm_detail_sync 同步）

性能说明：商机数据每天 07:45 由定时同步刷新一次，读多写少且体量小（百级）。
本模块对全量商机做进程内短 TTL（120s）快照缓存：
- 缓存未命中时建立一次 TiDB SSL 连接、取全量数据；
- 命中时所有筛选/汇总均在内存完成，避免每请求新建到 TiDB Cloud 的公网 SSL 连接，
  消除并发下的建连排队（此前单次 ~0.8s、并发 P95 8s+）。
"""
import os
import time
import logging
import threading
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

import pymysql
from urllib.parse import urlparse
from dotenv import load_dotenv
from fastapi import APIRouter, HTTPException, Query

load_dotenv('/opt/Weibo-Analyst/.env')
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(prefix='/api/crm', tags=['CRM商机'])

# 全量商机快照缓存：(ts, rows, summary_map, total_count, total_amount, product_lines, owners)
_CACHE_TTL = 120.0
_cache_lock = threading.Lock()
_snapshot = None

# 全量查询字段（含客户名，用于关键词内存匹配）
_ALL_COLS = '''
    SELECT o.id, o.feishu_record_id, o.customer_id, cu.company_name,
           o.opp_name, o.product_line, o.stage, o.amount, o.win_rate,
           o.expected_close_date, o.won_date, o.is_won, o.is_lost, o.owner
    FROM customer_opportunities o
    LEFT JOIN customers cu ON cu.id = o.customer_id
    ORDER BY FIELD(o.stage, '进行中', '已成交', '已丢单'), o.amount DESC
'''


def get_db():
    # 统一复用 database.py 的进程级 TiDB 连接池，避免每请求新建公网 SSL 连接
    try:
        from ..database import get_connection as _gc
    except Exception:
        from database import get_connection as _gc
    return _gc()



def _v(value):
    """JSON 安全转换：Decimal -> float，date/datetime -> ISO 字符串"""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _row(row):
    return {k: _v(v) for k, v in row.items()}


def _load_snapshot(force: bool = False):
    """获取（必要时刷新）全量商机快照。双重检查锁，保证并发下只建一次连接。"""
    global _snapshot
    now = time.time()
    if not force and _snapshot and now - _snapshot[0] < _CACHE_TTL:
        return _snapshot
    with _cache_lock:
        now = time.time()
        if not force and _snapshot and now - _snapshot[0] < _CACHE_TTL:
            return _snapshot
        conn = get_db()
        try:
            cur = conn.cursor()

            # 分阶段汇总（全量口径，不随筛选变化）
            cur.execute('''
                SELECT stage, COUNT(*) AS cnt, COALESCE(SUM(amount), 0) AS amount
                FROM customer_opportunities GROUP BY stage
            ''')
            summary_map = {}
            total_count = 0
            total_amount = 0.0
            for r in cur.fetchall():
                key = r['stage'] or '未知'
                cnt = int(r['cnt'])
                amt = float(r['amount'] or 0)
                summary_map[key] = {'count': cnt, 'amount': amt}
                total_count += cnt
                total_amount += amt

            # 全量商机（已按阶段优先级 + 金额排序）
            cur.execute(_ALL_COLS)
            rows = cur.fetchall()

            cur.execute('SELECT DISTINCT product_line FROM customer_opportunities WHERE product_line IS NOT NULL')
            product_lines = [r['product_line'] for r in cur.fetchall()]
            cur.execute('SELECT DISTINCT owner FROM customer_opportunities WHERE owner IS NOT NULL ORDER BY owner')
            owners = [r['owner'] for r in cur.fetchall()]
            cur.close()
        finally:
            conn.close()

        _snapshot = (time.time(), rows, summary_map, total_count, total_amount, product_lines, owners)
        logger.info('CRM 商机快照已刷新，共 %d 条', len(rows))
        return _snapshot


@router.get('/opportunities')
async def list_opportunities(
    stage: Optional[str] = None,
    product_line: Optional[str] = None,
    owner: Optional[str] = None,
    keyword: Optional[str] = None,
    customer_id: Optional[int] = None,
    limit: int = Query(200, ge=1, le=500)
):
    """获取商机列表（含分阶段汇总）。stage 取值：进行中 / 已成交 / 已丢单。"""
    try:
        _, rows, summary_map, total_count, total_amount, product_lines, owners = _load_snapshot()

        kw = keyword.strip().lower() if keyword and keyword.strip() else None

        def _match(r):
            if stage and r.get('stage') != stage:
                return False
            if product_line and r.get('product_line') != product_line:
                return False
            if owner and r.get('owner') != owner:
                return False
            if customer_id is not None and r.get('customer_id') != customer_id:
                return False
            if kw:
                hay = (str(r.get('opp_name') or '') + ' ' + str(r.get('company_name') or '')).lower()
                if kw not in hay:
                    return False
            return True

        # 全量快照已按规定顺序排序，filter 保序，最后截断 limit
        opportunities = [_row(r) for r in rows if _match(r)][:limit]

        def _sm(name):
            return summary_map.get(name, {'count': 0, 'amount': 0.0})

        return {
            'status': 'success',
            'count': len(opportunities),
            'summary': {
                'total_count': total_count,
                'total_amount': total_amount,
                'open': _sm('进行中'),
                'won': _sm('已成交'),
                'lost': _sm('已丢单'),
            },
            'filters': {
                'product_lines': product_lines,
                'owners': owners,
            },
            'opportunities': opportunities
        }
    except Exception as e:
        logger.error(f'获取商机列表失败: {e}')
        raise HTTPException(status_code=500, detail=str(e))
