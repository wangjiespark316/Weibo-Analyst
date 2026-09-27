#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
飞书多维表客户同步模块

职责：把飞书多维表中的客户数据同步到本地 customers 表（只增/改，不删除本地数据）。
设计原则：
  1. 不伪造任何业务数据，飞书没有的字段（如金额、电话）在本地留空/NULL；
  2. 字段解析兼容飞书多种返回形态——GET /records 与 POST /records/search 对同一字段
     的返回结构可能不同：
       * 文本：[{"text": "..."}] 或纯字符串；
       * 单选/多选：中文字符串，或选项 ID（如 "optXXXX"，lookup 字段在 GET 下常返回 ID）；
       * 人员：[{"name": "..."}]；
       * 查找引用(lookup, type=19)：裸数组 ["optXXXX"] / [45781]，或 {"type": x, "value": ...}；
       * 日期：毫秒时间戳，或飞书/Excel 日期序列号（自 1899-12-30 起的天数）。
  3. 选项 ID -> 中文名称的映射同时从“本表单选/多选字段”和“lookup 引用表的目标字段”获取；
  4. 飞书客户分层 / 客户阶段映射到本地统一枚举（A/B/C 与 new/contacted/.../closed/lost）。

配置（环境变量，.env，禁止入库）：
  FEISHU_APP_ID, FEISHU_APP_SECRET
  FEISHU_BITABLE_APP_TOKEN, FEISHU_BITABLE_TABLE_ID
"""
import os
import sys
import json
import logging
import re
import requests
from datetime import datetime, date, time, timezone, timedelta
from dotenv import load_dotenv

load_dotenv('/opt/Weibo-Analyst/.env')
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BJ_TZ = timezone(timedelta(hours=8))
EXCEL_EPOCH = date(1899, 12, 30)  # 飞书/Excel 日期序列号基准

# 飞书客户分层 -> 本地客户等级
LEVEL_MAP = {
    '重要客户': 'A',
    '重点突破': 'A',
    '一般客户': 'B',
}
# 飞书客户阶段 -> 本地销售阶段枚举
STAGE_MAP = {
    '未触达': 'new',
    '已建联': 'contacted',
    '合作中': 'solution',
    '中止合作': 'lost',
    '已完成': 'closed',
}


def _resolve(s, options):
    s = str(s).strip()
    return options.get(s, s) if options else s


def _to_text(val, options=None):
    """把飞书任意字段值转换为纯文本字符串；options 用于把选项 ID 还原为名称。"""
    if val is None:
        return ''
    if isinstance(val, str):
        return _resolve(val, options)
    if isinstance(val, (int, float)):
        return str(val).strip()
    if isinstance(val, dict):
        # 查找引用 / 公式等返回 {"type": x, "value": ...}
        if 'value' in val:
            return _to_text(val['value'], options)
        if isinstance(val.get('text'), str):
            return _resolve(val['text'], options)
        if isinstance(val.get('name'), str):
            return _resolve(val['name'], options)
        return ''
    if isinstance(val, list):
        rich, scalar = [], []
        for item in val:
            if isinstance(item, dict):
                t = item.get('text') if isinstance(item.get('text'), str) else item.get('name')
                if t is not None:
                    rich.append(_resolve(t, options))
            elif item is not None:
                scalar.append(_resolve(item, options))
        if rich:
            # 富文本/人员片段直接拼接
            return ''.join(rich).strip()
        # 纯标量数组（单选/多选项）用顿号连接，lookup 关联多条记录时按顺序去重
        scalar = list(dict.fromkeys(scalar))
        return '、'.join(scalar).strip()
    return str(val).strip()


def _unwrap(val):
    """剥开 lookup 的 {type, value} 包装，返回内部值。"""
    if isinstance(val, dict) and 'value' in val:
        v = val['value']
        if isinstance(v, list):
            return v[0] if v else None
        return v
    if isinstance(val, list):
        return val[0] if val else None
    return val


def _to_date(val):
    """把飞书日期字段转为北京日期的 naive datetime（兼容毫秒戳与日期序列号）。"""
    v = _unwrap(val)
    if v is None:
        return None
    if isinstance(v, str):
        v = v.strip()
        if not v:
            return None
        try:
            v = float(v)
        except ValueError:
            return None
    if not isinstance(v, (int, float)):
        return None
    n = float(v)
    try:
        if n > 1_000_000_000_000:  # 毫秒时间戳
            d = datetime.fromtimestamp(n / 1000, tz=BJ_TZ).date()
            return datetime.combine(d, time(0, 0))
        if 20000 <= n <= 80000:  # 飞书/Excel 日期序列号（约 1954-2119 年）
            d = EXCEL_EPOCH + timedelta(days=int(n))
            return datetime.combine(d, time(0, 0))
    except Exception:
        return None
    return None


class FeishuBitableSync:
    def __init__(self):
        self.app_id = os.getenv('FEISHU_APP_ID', '')
        self.app_secret = os.getenv('FEISHU_APP_SECRET', '')
        self.app_token = os.getenv('FEISHU_BITABLE_APP_TOKEN', '')
        self.table_id = os.getenv('FEISHU_BITABLE_TABLE_ID', '')
        self.base_url = 'https://open.feishu.cn/open-apis'
        self._token = None
        self._token_expire = 0
        self.option_map = {}
        self.enabled = bool(self.app_id and self.app_secret and self.app_token and self.table_id)

    def _get_token(self):
        if self._token and datetime.now().timestamp() < self._token_expire:
            return self._token
        url = f'{self.base_url}/auth/v3/tenant_access_token/internal'
        try:
            resp = requests.post(url, json={'app_id': self.app_id, 'app_secret': self.app_secret}, timeout=10)
            result = resp.json()
            if result.get('code') == 0:
                self._token = result['tenant_access_token']
                self._token_expire = datetime.now().timestamp() + result.get('expire', 7200) - 300
                return self._token
            logger.error(f'获取token失败: {result.get("msg")}')
        except Exception as e:
            logger.error(f'获取token异常: {e}')
        return None

    def _headers(self):
        return {'Authorization': f'Bearer {self._get_token()}', 'Content-Type': 'application/json'}

    def _collect_options(self, table_id):
        """拉取一张表内所有单选/多选字段的 选项ID->名称 映射。"""
        om = {}
        url = f'{self.base_url}/bitable/v1/apps/{self.app_token}/tables/{table_id}/fields?page_size=100'
        try:
            resp = requests.get(url, headers=self._headers(), timeout=15)
            result = resp.json()
            if result.get('code') != 0:
                return om
            for fld in result.get('data', {}).get('items', []):
                for o in (fld.get('property') or {}).get('options', []) or []:
                    if o.get('id') and o.get('name'):
                        om[o['id']] = o['name']
        except Exception as e:
            logger.warning(f'拉取字段选项失败[{table_id}]: {e}')
        return om

    def load_option_map(self):
        """汇总本表 + lookup 引用表的选项映射（职位等 lookup 单选的选项定义在引用表）。"""
        om = {}
        try:
            om.update(self._collect_options(self.table_id))
            # 找本表 lookup(type=19) 字段引用的数据表
            url = f'{self.base_url}/bitable/v1/apps/{self.app_token}/tables/{self.table_id}/fields?page_size=100'
            resp = requests.get(url, headers=self._headers(), timeout=15)
            targets = set()
            if resp.json().get('code') == 0:
                for fld in resp.json().get('data', {}).get('items', []):
                    if fld.get('type') == 19:
                        prop = fld.get('property') or {}
                        tt = prop.get('target_table')
                        if not tt:  # 列表接口不返回 target_table，目标表在 formula 的 $table[xxx] 中
                            mm = re.search(r'\$table\[([A-Za-z0-9]+)\]', prop.get('formula', '') or '')
                            tt = mm.group(1) if mm else None
                        if tt:
                            targets.add(tt)
            for tt in targets:
                for k, v in self._collect_options(tt).items():
                    om.setdefault(k, v)
        except Exception as e:
            logger.warning(f'加载选项映射异常: {e}')
        self.option_map = om
        return om

    def fetch_records(self, page_size=100):
        if not self.enabled:
            return []
        all_records = []
        page_token = None
        while True:
            url = f'{self.base_url}/bitable/v1/apps/{self.app_token}/tables/{self.table_id}/records'
            params = {'page_size': page_size}
            if page_token:
                params['page_token'] = page_token
            try:
                resp = requests.get(url, headers=self._headers(), params=params, timeout=15)
                result = resp.json()
                if result.get('code') != 0:
                    logger.error(f'拉取记录失败: {result.get("msg")}')
                    break
                data = result.get('data', {})
                all_records.extend(data.get('items', []))
                if not data.get('has_more'):
                    break
                page_token = data.get('page_token')
            except Exception as e:
                logger.error(f'拉取记录异常: {e}')
                break
        return all_records

    def _map_record(self, record):
        fields = record.get('fields', {})
        opt = self.option_map

        def pick(*names):
            for n in names:
                v = fields.get(n)
                if v not in (None, '', []):
                    return v
            return None

        company = _to_text(pick('客户名称', '公司名称', '客户'), opt)
        industry = _to_text(pick('行业', '行业信息'), opt) or None
        company_size = _to_text(pick('人员规模', '客户规模', '公司规模'), opt) or None
        location = _to_text(pick('城市', '所在地', '详细地址'), opt) or None
        contact = _to_text(pick('客户对接人姓名', '对接人姓名', '联系人', '客户对接人'), opt) or None
        role = _to_text(pick('职位', '对接人职位'), opt) or None
        # 职位若仍是无法解析的选项ID（opt开头），不展示乱码，留空
        if role and role.startswith('opt'):
            role = None
        owner = _to_text(pick('客户负责人（销售）', '客户所有人', '负责人', '跟进销售人员'), opt) or None
        phone = _to_text(pick('联系电话', '联系方式', '手机号'), opt) or None

        level_raw = _to_text(pick('客户分层', '客户等级'), opt)
        stage_raw = _to_text(pick('客户阶段', '销售阶段', '跟进阶段'), opt)
        customer_level = LEVEL_MAP.get(level_raw) or (level_raw if level_raw in ('A', 'B', 'C') else 'C')
        sales_stage = STAGE_MAP.get(stage_raw) or (stage_raw if stage_raw in
                     ('new', 'contacted', 'requirement', 'solution', 'negotiation', 'closed', 'lost') else 'new')

        last_follow = _to_date(pick('最近跟进日期', '最后跟进时间', '最近联系时间'))

        # 金额：客户主表本身没有金额字段（金额在商机表），不臆造，留 NULL
        amount_raw = pick('预计金额', '金额', '业务价值')
        amount = None
        if amount_raw is not None:
            try:
                amount = float(_to_text(amount_raw, opt) or 0) or None
            except (TypeError, ValueError):
                amount = None

        # 备注：仅拼接飞书里真实存在的辅助信息
        notes_parts = []
        nickname = _to_text(pick('昵称'), opt)
        if nickname:
            notes_parts.append(f'昵称：{nickname}')
        intro = _to_text(pick('企业简介'), opt)
        if intro:
            notes_parts.append(f'简介：{intro}')
        tags = _to_text(pick('企业标签'), opt)
        if tags:
            notes_parts.append(f'标签：{tags}')
        source = _to_text(pick('客户来源'), opt)
        if source:
            notes_parts.append(f'来源：{source}')
        website = _to_text(pick('官网'), opt)
        if website:
            notes_parts.append(f'官网：{website}')
        wechat = _to_text(pick('微信号'), opt)
        if wechat:
            notes_parts.append(f'微信号：{wechat}')
        notes = '；'.join(notes_parts) or None

        return {
            'feishu_record_id': record.get('record_id'),
            'company_name': company,
            'industry': industry,
            'company_size': company_size,
            'location': location,
            'contact_name': contact,
            'contact_role': role,
            'phone': phone,
            'customer_level': customer_level,
            'sales_stage': sales_stage,
            'amount': amount,
            'owner': owner,
            'last_follow_time': last_follow,
            'notes': notes,
        }

    def _connect(self):
        import pymysql
        from urllib.parse import urlparse
        parsed = urlparse(os.getenv('DATABASE_URL'))
        return pymysql.connect(
            host=parsed.hostname, port=parsed.port or 4000,
            user=parsed.username, password=parsed.password,
            database=parsed.path.lstrip('/'), ssl={'ssl_disabled': False},
            cursorclass=pymysql.cursors.DictCursor,
            charset='utf8mb4',
        )

    def sync_to_local(self, records):
        self.load_option_map()
        logger.info(f'已加载选项映射 {len(self.option_map)} 个')
        conn = self._connect()
        cursor = conn.cursor()
        inserted = updated = skipped = errors = 0
        for record in records:
            try:
                c = self._map_record(record)
                if not c['company_name']:
                    skipped += 1
                    continue
                cursor.execute(
                    'SELECT id FROM customers WHERE feishu_record_id=%s OR company_name=%s',
                    (c['feishu_record_id'], c['company_name']))
                existing = cursor.fetchone()
                if existing:
                    # last_follow_time 以跟进记录表为唯一权威来源（detail sync 回填），
                    # 不采信客户主表手填的“最近跟进日期”，避免历史脏值覆盖
                    cursor.execute('''UPDATE customers SET industry=%s, company_size=%s, location=%s,
                        contact_name=%s, contact_role=%s, phone=%s, customer_level=%s, sales_stage=%s,
                        amount=%s, owner=%s, notes=%s,
                        feishu_record_id=COALESCE(feishu_record_id,%s), updated_time=NOW() WHERE id=%s''',
                        (c['industry'], c['company_size'], c['location'], c['contact_name'], c['contact_role'],
                         c['phone'], c['customer_level'], c['sales_stage'], c['amount'], c['owner'],
                         c['notes'], c['feishu_record_id'], existing['id']))
                    updated += 1
                else:
                    # 新客户 last_follow_time 默认 NULL，由跟进明细同步回填
                    cursor.execute('''INSERT INTO customers (feishu_record_id, company_name, industry, company_size,
                        location, contact_name, contact_role, phone, customer_level, sales_stage, amount, owner,
                        notes, created_time, updated_time)
                        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW(),NOW())''',
                        (c['feishu_record_id'], c['company_name'], c['industry'], c['company_size'], c['location'],
                         c['contact_name'], c['contact_role'], c['phone'], c['customer_level'], c['sales_stage'],
                         c['amount'], c['owner'], c['notes']))
                    inserted += 1
                conn.commit()
            except Exception as e:
                logger.error(f'同步失败[{record.get("record_id")}]: {e}')
                errors += 1
                conn.rollback()
        cursor.close()
        conn.close()
        return {'total': len(records), 'inserted': inserted, 'updated': updated,
                'skipped': skipped, 'errors': errors}

    def _log(self, status, message):
        try:
            conn = self._connect()
            cursor = conn.cursor()
            cursor.execute(
                'INSERT INTO feishu_sync_logs (type, object_id, status, error, created_time) VALUES (%s,%s,%s,%s,NOW())',
                ('bitable', 'customers', status, message))
            conn.commit()
            cursor.close()
            conn.close()
        except Exception as e:
            logger.error(f'写同步日志失败: {e}')

    def sync_all(self):
        if not self.enabled:
            msg = '飞书多维表未配置（缺少 FEISHU_BITABLE_APP_TOKEN/TABLE_ID）'
            self._log('skipped', msg)
            return {'status': 'skipped', 'message': msg}
        try:
            records = self.fetch_records()
            if not records:
                msg = '未拉取到任何客户记录'
                self._log('failed', msg)
                return {'status': 'failed', 'message': msg}
            result = self.sync_to_local(records)
            msg = (f'同步完成: 共{result["total"]}条, 新增{result["inserted"]}, '
                   f'更新{result["updated"]}, 跳过{result["skipped"]}, 失败{result["errors"]}')
            self._log('success' if result['errors'] == 0 else 'partial', msg)
            return {'status': 'success', 'message': msg, 'details': result}
        except Exception as e:
            msg = f'同步失败: {e}'
            self._log('failed', msg)
            return {'status': 'failed', 'message': msg}

    def test_connection(self):
        if not self.enabled:
            return {'status': 'skipped', 'message': '飞书多维表未配置'}
        try:
            token = self._get_token()
            if not token:
                return {'status': 'failed', 'message': '获取token失败'}
            # 飞书没有“获取单个数据表”端点，改为列出数据表并校验目标 table_id 是否存在
            url = f'{self.base_url}/bitable/v1/apps/{self.app_token}/tables?page_size=100'
            resp = requests.get(url, headers=self._headers(), timeout=10)
            result = resp.json()
            if result.get('code') == 0:
                ids = [t.get('table_id') for t in result.get('data', {}).get('items', [])]
                if self.table_id in ids:
                    return {'status': 'success', 'message': f'连接成功，共{len(ids)}张数据表，客户表已定位'}
                return {'status': 'failed', 'message': f'未在该多维表中找到 table_id={self.table_id}'}
            return {'status': 'failed', 'message': result.get('msg', '连接失败')}
        except Exception as e:
            return {'status': 'failed', 'message': str(e)}


_instance = None
def get_feishu_bitable_sync():
    global _instance
    if _instance is None:
        _instance = FeishuBitableSync()
    return _instance


if __name__ == '__main__':
    sync = get_feishu_bitable_sync()
    if len(sys.argv) > 1 and sys.argv[1] == 'test':
        print(json.dumps(sync.test_connection(), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(sync.sync_all(), ensure_ascii=False, indent=2))
