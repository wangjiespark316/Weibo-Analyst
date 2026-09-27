#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
飞书 CRM 明细数据同步：跟进记录 + 商机管理
=========================================
数据源（飞书多维表「客户关系管理系统」app_token=JQ7cbRlTRaulPmsJu8rcLLPCnIh）:
  - 跟进记录表 tblVsyv1oqbKjs2M  -> 本地 follow_records
  - 商机管理表 tblm4jgDOfbRfSXK  -> 本地 customer_opportunities(新建)
同步后回填 customers:
  - amount            在途商机金额合计(未赢单且未丢单)
  - follow_count      跟进次数
  - last_follow_time  最近跟进时间
  - next_action       最新一条跟进的下一步

关联: 飞书关联字段 -> customers.feishu_record_id; 关联缺失时用客户名称文本兜底。
幂等: 按 feishu_record_id 唯一键 upsert，只增改、不删除。
手动执行: .venv/bin/python feishu_crm_detail_sync.py
"""
import os
import re
import sys
import json
from pathlib import Path
from datetime import datetime, timedelta, date
from urllib.parse import urlparse

import requests
import pymysql
from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
load_dotenv('/opt/Weibo-Analyst/.env')

APP_TOKEN = 'JQ7cbRlTRaulPmsJu8rcLLPCnIh'
T_CUSTOMER = 'tblN8oXexr64xBNo'
T_FOLLOW = 'tblVsyv1oqbKjs2M'
T_OPP = 'tblm4jgDOfbRfSXK'
FB = 'https://open.feishu.cn/open-apis'


def log(m):
    print(f'[{datetime.now():%Y-%m-%d %H:%M:%S}] {m}', flush=True)


def db():
    p = urlparse(os.getenv('DATABASE_URL'))
    return pymysql.connect(
        host=p.hostname, port=p.port or 4000, user=p.username, password=p.password,
        database=p.path.lstrip('/'), ssl={'ssl_disabled': False}, charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor, autocommit=False)


def get_token():
    r = requests.post(
        FB + '/auth/v3/tenant_access_token/internal',
        json={'app_id': os.getenv('FEISHU_APP_ID'), 'app_secret': os.getenv('FEISHU_APP_SECRET')},
        timeout=15)
    return r.json()['tenant_access_token']


# ---------- 飞书字段值解析 ----------
def _text(v):
    if v is None:
        return None
    if isinstance(v, str):
        return v.strip() or None
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, dict):
        if 'value' in v:
            return _text(v['value'])
        if 'text' in v:
            return _text(v['text'])
    if isinstance(v, list):
        parts = []
        for it in v:
            if isinstance(it, dict):
                if it.get('text') is not None:
                    parts.append(str(it['text']))
                elif it.get('name'):
                    parts.append(str(it['name']))
            else:
                parts.append(str(it))
        s = ' '.join(x for x in parts if x).strip()
        return s or None
    return None


def _link(v):
    """返回关联到的第一条客户记录 record_id，兼容 GET(record_ids) 与 search(link_record_ids)。"""
    if not v:
        return None
    if isinstance(v, dict):
        ids = v.get('link_record_ids') or v.get('record_ids')
        if ids:
            return ids[0]
    if isinstance(v, list):
        for it in v:
            if isinstance(it, dict):
                ids = it.get('record_ids') or it.get('link_record_ids')
                if ids:
                    return ids[0]
    return None


def _persons(v):
    if isinstance(v, list):
        names = [it.get('name', '') for it in v if isinstance(it, dict) and it.get('name')]
        return ', '.join(names) or None
    return None


def _date(v):
    """毫秒时间戳(->北京时间) 或 飞书/Excel 序列号日期，返回 datetime/date。"""
    if v in (None, '', []):
        return None
    if isinstance(v, dict):
        v = v.get('value')
    if isinstance(v, list):
        if not v:
            return None
        v = v[0]
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None
    if n > 1e12:  # epoch 毫秒，转北京时区 UTC+8
        return datetime.utcfromtimestamp(n / 1000) + timedelta(hours=8)
    if 20000 < n < 80000:  # Excel/飞书序列号，基准 1899-12-30
        return date(1899, 12, 30) + timedelta(days=int(n))
    return None


def _d(v):
    # 幂等：入参可能已是 _date() 的结果(date/datetime)，不可再次走数值解析
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    d = _date(v)
    return d.date() if isinstance(d, datetime) else d


# ---------- 飞书记录拉取 ----------
def _paged(url, headers, post=False):
    out, pt = [], None
    while True:
        u = url + ('&page_token=' + pt if pt else '')
        if post:
            r = requests.post(u, headers=headers, json={}, timeout=25).json()
        else:
            r = requests.get(u, headers=headers, timeout=25).json()
        d = r.get('data', {})
        out += d.get('items', [])
        if d.get('has_more'):
            pt = d.get('page_token')
        else:
            break
    return out


def get_records(H, tid):
    return _paged(f'{FB}/bitable/v1/apps/{APP_TOKEN}/tables/{tid}/records?page_size=100', H)


def search_records(H, tid):
    return _paged(f'{FB}/bitable/v1/apps/{APP_TOKEN}/tables/{tid}/records/search?page_size=100',
                  {**H, 'Content-Type': 'application/json'}, post=True)


# ---------- 结构准备 ----------
def ensure_schema(cur):
    cur.execute("SHOW COLUMNS FROM follow_records LIKE 'feishu_record_id'")
    if not cur.fetchone():
        cur.execute("ALTER TABLE follow_records ADD COLUMN feishu_record_id VARCHAR(64) NULL")
    cur.execute("SHOW INDEX FROM follow_records WHERE Key_name='uk_follow_feishu'")
    if not cur.fetchone():
        cur.execute("ALTER TABLE follow_records ADD UNIQUE KEY uk_follow_feishu(feishu_record_id)")
    cur.execute("SHOW TABLES LIKE 'customer_opportunities'")
    if not cur.fetchone():
        cur.execute('''CREATE TABLE customer_opportunities (
            id BIGINT NOT NULL AUTO_INCREMENT PRIMARY KEY,
            feishu_record_id VARCHAR(64) NOT NULL,
            customer_id BIGINT NULL,
            opp_name VARCHAR(256) NULL,
            product_line VARCHAR(64) NULL,
            stage VARCHAR(32) NULL,
            amount DECIMAL(14,2) DEFAULT 0,
            win_rate VARCHAR(16) NULL,
            expected_close_date DATE NULL,
            won_date DATE NULL,
            is_won TINYINT DEFAULT 0,
            is_lost TINYINT DEFAULT 0,
            owner VARCHAR(64) NULL,
            created_time DATETIME DEFAULT CURRENT_TIMESTAMP,
            updated_time DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            UNIQUE KEY uk_opp_feishu(feishu_record_id),
            KEY idx_opp_customer(customer_id),
            KEY idx_opp_stage(stage)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin COMMENT='飞书商机管理同步表' ''')


def customer_maps(cur):
    cur.execute("SELECT id, company_name, feishu_record_id FROM customers")
    rows = cur.fetchall()

    def norm(s):
        return re.sub(r'[\s（）()｜|·\-_、,，.]', '', (s or '')).lower()

    by_feishu = {r['feishu_record_id']: r['id'] for r in rows if r['feishu_record_id']}
    by_name = {norm(r['company_name']): r['id'] for r in rows}

    def resolve(link_rec, cust_text):
        if link_rec and link_rec in by_feishu:
            return by_feishu[link_rec]
        k = norm(cust_text)
        if k and k in by_name:
            return by_name[k]
        if k:
            for nk, cid in by_name.items():
                if len(k) >= 4 and (k in nk or nk in k):
                    return cid
        return None

    return resolve


# ---------- 跟进同步 ----------
def sync_follow(cur, H, resolve):
    recs = search_records(H, T_FOLLOW)
    unmatched = 0
    for r in recs:
        f = r.get('fields', {})
        rid = r.get('record_id')
        cid = resolve(_link(f.get('跟进客户')), _text(f.get('跟进客户')))
        if cid is None:
            unmatched += 1
        ft = _date(f.get('记录日期'))
        progress = _text(f.get('🌟 一句话进展'))
        needs = _text(f.get('客户需求'))
        concern = _text(f.get('需要帮助'))
        risk = _text(f.get('🌟风险等级'))
        nxt = _text(f.get('下一步'))
        contact = _text(f.get('沟通对象'))
        owner = _persons(f.get('记录人'))
        product = _text(f.get('跟进产品'))
        meta = '  '.join(x for x in [
            f'沟通对象:{contact}' if contact else None,
            f'记录人:{owner}' if owner else None,
            f'风险:{risk}' if risk else None,
            f'产品:{product}' if product else None] if x) or None
        cur.execute('''INSERT INTO follow_records
            (feishu_record_id,customer_id,follow_type,content,ai_summary,customer_needs,
             customer_concerns,next_action,follow_time)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE customer_id=VALUES(customer_id),follow_type=VALUES(follow_type),
              content=VALUES(content),ai_summary=VALUES(ai_summary),customer_needs=VALUES(customer_needs),
              customer_concerns=VALUES(customer_concerns),next_action=VALUES(next_action),
              follow_time=VALUES(follow_time)''',
                    (rid, cid, product, progress, meta, needs, concern, nxt, ft))
    return len(recs), unmatched


# ---------- 商机同步 ----------
def sync_opp(cur, H, resolve):
    # GET 接口的关联字段可靠(search 下该双向关联为 null)，先建 record_id -> 客户 映射
    link_map = {}
    for r in get_records(H, T_OPP):
        f = r.get('fields', {})
        link_map[r['record_id']] = (_link(f.get('👩‍❤️‍💋‍👨｜客户管理')),
                                    _text(f.get('客户名称')))
    recs = search_records(H, T_OPP)
    unmatched = 0
    for r in recs:
        f = r.get('fields', {})
        rid = r.get('record_id')
        link, get_text = link_map.get(rid, (None, None))
        ctext = get_text or _text(f.get('客户名称'))
        cid = resolve(link, ctext)
        if cid is None:
            unmatched += 1
        raw_amt = f.get('金额(CNY)')
        try:
            amt = float(raw_amt) if raw_amt not in (None, '', []) else 0.0
        except (TypeError, ValueError):
            amt = 0.0
        won = _date(f.get('赢单日期'))
        lost = _text(f.get('丢单原因'))
        exp = _date(f.get('预计关单日期'))
        winrate = _text(f.get('赢单率'))
        pl = _text(f.get('产品线'))
        name = _text(f.get('商机名称')) or f'{ctext or "未知客户"}｜{pl or "商机"}'
        owner = _persons(f.get('销售（人员）'))
        is_won = 1 if won else 0
        is_lost = 1 if lost else 0
        stage = '已成交' if is_won else ('已丢单' if is_lost else '进行中')
        cur.execute('''INSERT INTO customer_opportunities
            (feishu_record_id,customer_id,opp_name,product_line,stage,amount,win_rate,
             expected_close_date,won_date,is_won,is_lost,owner)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE customer_id=VALUES(customer_id),opp_name=VALUES(opp_name),
              product_line=VALUES(product_line),stage=VALUES(stage),amount=VALUES(amount),
              win_rate=VALUES(win_rate),expected_close_date=VALUES(expected_close_date),
              won_date=VALUES(won_date),is_won=VALUES(is_won),is_lost=VALUES(is_lost),
              owner=VALUES(owner)''',
                    (rid, cid, name, pl, stage, amt, winrate, _d(exp), _d(won),
                     is_won, is_lost, owner))
    return len(recs), unmatched


# ---------- 回填客户汇总字段 ----------
def backfill(cur):
    cur.execute('''UPDATE customers c SET amount = COALESCE((
        SELECT SUM(o.amount) FROM customer_opportunities o
        WHERE o.customer_id = c.id AND o.is_won=0 AND o.is_lost=0), 0)''')
    # last_follow_time/follow_count 以跟进记录表为唯一权威：有记录取真实 MAX，
    # 无记录置 0/NULL（LEFT JOIN），顺带清除客户主表带入的历史脏日期
    cur.execute('''UPDATE customers c LEFT JOIN (
        SELECT customer_id, COUNT(*) cnt, MAX(follow_time) last_t
        FROM follow_records WHERE customer_id IS NOT NULL GROUP BY customer_id
    ) x ON x.customer_id = c.id
    SET c.follow_count = COALESCE(x.cnt, 0), c.last_follow_time = x.last_t''')
    cur.execute('''SELECT customer_id, next_action FROM follow_records WHERE id IN (
        SELECT MAX(id) FROM follow_records
        WHERE next_action IS NOT NULL AND next_action <> ''
        GROUP BY customer_id)''')
    for r in cur.fetchall():
        cur.execute('UPDATE customers SET next_action=%s WHERE id=%s',
                    (r['next_action'], r['customer_id']))


def main():
    log('===== 飞书 CRM 明细(跟进+商机)同步开始 =====')
    conn = db()
    cur = conn.cursor()
    try:
        H = {'Authorization': 'Bearer ' + get_token()}
        ensure_schema(cur)
        resolve = customer_maps(cur)
        f_total, f_bad = sync_follow(cur, H, resolve)
        log(f'跟进记录同步: {f_total} 条, 未匹配客户 {f_bad} 条')
        o_total, o_bad = sync_opp(cur, H, resolve)
        log(f'商机同步: {o_total} 条, 未匹配客户 {o_bad} 条')
        backfill(cur)
        conn.commit()
        cur.execute("SELECT COUNT(*) c FROM follow_records")
        f_cnt = cur.fetchone()['c']
        cur.execute("SELECT COUNT(*) c, COALESCE(SUM(amount),0) s FROM customer_opportunities WHERE is_won=0 AND is_lost=0")
        row = cur.fetchone()
        cur.execute("SELECT COUNT(*) c FROM customers WHERE amount>0")
        amt_cust = cur.fetchone()['c']
        cur.execute("SELECT COUNT(*) c FROM customers WHERE follow_count>0")
        fol_cust = cur.fetchone()['c']
        log(f'本地跟进总数 {f_cnt} | 在途商机 {row["c"]} 条 / 在途金额 {float(row["s"]):,.0f} '
            f'| 有在途金额客户 {amt_cust} | 有跟进客户 {fol_cust}')
        log('===== 明细同步完成 =====')
        return {'follow': f_total, 'follow_unmatched': f_bad,
                'opportunity': o_total, 'opp_unmatched': o_bad,
                'pipeline_amount': float(row['s'])}
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == '__main__':
    print(json.dumps(main(), ensure_ascii=False, indent=2))
