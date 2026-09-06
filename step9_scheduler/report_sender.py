#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日报存储与发送模块
- 保存日报到文件系统: reports/{tenant_key}/{YYYY-MM-DD}.md
- 列出生成的日报
- 预留: 后续可扩展邮件/飞书/企微发送
"""
import os
from datetime import datetime
from .config import REPORTS_DIR


def save_report(tenant_key: str, content: str, date_str: str = None) -> str:
    """
    保存日报到文件系统
    返回: 日报文件绝对路径
    """
    if date_str is None:
        date_str = datetime.now().strftime('%Y-%m-%d')

    tenant_dir = os.path.join(REPORTS_DIR, tenant_key)
    os.makedirs(tenant_dir, exist_ok=True)

    report_path = os.path.join(tenant_dir, f'{date_str}.md')
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(content)

    return report_path


def list_reports(tenant_key: str = None) -> list:
    """
    列出生成的日报
    返回: [{'tenant':..., 'date':..., 'path':...}, ...]
    """
    results = []
    if not os.path.exists(REPORTS_DIR):
        return results

    tenants = [tenant_key] if tenant_key else sorted(os.listdir(REPORTS_DIR))
    for t in tenants:
        tenant_dir = os.path.join(REPORTS_DIR, t)
        if not os.path.isdir(tenant_dir):
            continue
        for f in sorted(os.listdir(tenant_dir)):
            if f.endswith('.md'):
                results.append({
                    'tenant': t,
                    'date': f.replace('.md', ''),
                    'path': os.path.join(tenant_dir, f),
                    'size': os.path.getsize(os.path.join(tenant_dir, f)),
                })
    return results


def get_report_path(tenant_key: str, date_str: str = None) -> str:
    """获取指定租户指定日期的日报路径（不检查是否存在）"""
    if date_str is None:
        date_str = datetime.now().strftime('%Y-%m-%d')
    return os.path.join(REPORTS_DIR, tenant_key, f'{date_str}.md')
