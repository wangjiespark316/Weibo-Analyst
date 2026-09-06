#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
租户日报运行器
- 调用 Agent 工作流为单个租户生成日报
- 一个租户失败不影响其他租户（异常隔离）
- 复用 step8_agent_verification/agent_client.py 的核心函数
"""
import os
import sys
import time
import json
from datetime import datetime

from .config import TENANTS_CONFIG, AGENT_CLIENT_DIR
from .report_sender import save_report

# 将 Agent 客户端目录加入 path，复用其核心函数
if AGENT_CLIENT_DIR not in sys.path:
    sys.path.insert(0, AGENT_CLIENT_DIR)

from agent_client import (
    collect_all_data,
    build_context,
    build_prompt,
    simulate_llm_report,
)


def load_tenants() -> dict:
    """加载租户配置"""
    with open(TENANTS_CONFIG, 'r', encoding='utf-8') as f:
        return json.load(f)


def get_tenant_name(tenant_key: str) -> str:
    """获取租户名称"""
    tenants = load_tenants()
    return tenants.get(tenant_key, {}).get('name', tenant_key)


def run_tenant(tenant_key: str) -> dict:
    """
    运行单个租户的日报生成全流程。

    流程:
      tenant_key → collect_all_data → build_context
      → build_prompt → simulate_llm_report → save_report

    返回结果元数据:
      {
        'tenant_key': str,
        'tenant_name': str,
        'success': bool,
        'report_path': str|None,
        'duration': float (秒),
        'error': str|None,
        'generated_at': str (ISO)
      }
    """
    start = time.time()
    result = {
        'tenant_key': tenant_key,
        'tenant_name': get_tenant_name(tenant_key),
        'success': False,
        'report_path': None,
        'duration': 0,
        'error': None,
        'generated_at': datetime.now().isoformat(),
    }

    try:
        # 第一步: API 获取数据（带 API Key）
        data = collect_all_data(tenant_key)

        # 第二步: 整理上下文
        context = build_context(data, tenant_key)

        # 第三步: 构建 Prompt
        prompt = build_prompt(context, tenant_key)

        # 第四步: 生成日报内容
        report_content = simulate_llm_report(data, context, tenant_key)

        # 第五步: 保存日报到文件系统
        report_path = save_report(tenant_key, report_content)
        result['report_path'] = report_path
        result['success'] = True

    except Exception as e:
        result['error'] = f"{type(e).__name__}: {str(e)}"
    finally:
        result['duration'] = round(time.time() - start, 2)

    return result
