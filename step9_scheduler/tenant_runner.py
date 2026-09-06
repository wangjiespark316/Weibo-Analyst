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

from .config import TENANTS_CONFIG, AGENT_CLIENT_DIR, FEISHU_ENABLED, REPORT_URL_TEMPLATE
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

# 飞书推送器（延迟导入，避免未安装 requests 时报错）
_feishu_sender = None


def _get_feishu_sender():
    """获取飞书推送器实例（懒加载）"""
    global _feishu_sender
    if _feishu_sender is None:
        try:
            from step10_agent_app.feishu_sender import FeishuSender
            _feishu_sender = FeishuSender()
        except Exception as e:
            print(f'[Feishu] 初始化失败: {e}')
            _feishu_sender = False
    return _feishu_sender if _feishu_sender else None


def _extract_report_info(report_content: str, data: dict) -> dict:
    """
    从日报内容和 API 数据中提取飞书消息所需信息

    Returns:
        {
            'hot_topics': [...],
            'ai_trend': '...',
            'risk_alert': '...',
            'sentiment_summary': '...',
        }
    """
    info = {
        'hot_topics': [],
        'ai_trend': '',
        'risk_alert': '',
        'sentiment_summary': '',
    }

    # 从 API 数据提取热点 TOP3
    hot_data = data.get('hot_weibo', {}).get('data', [])
    for p in hot_data[:3]:
        content = (p.get('content') or '')[:40].replace('\n', ' ')
        username = p.get('username', '未知')
        info['hot_topics'].append(f'**{username}**：{content}')

    # 从 API 数据提取关键词趋势
    kw_trends = data.get('keyword_trends', {})
    kw_list = []
    for kw, tr in kw_trends.items():
        if tr:
            kw_list.append((kw, tr.get('total_mentions', 0)))
    kw_list.sort(key=lambda x: x[1], reverse=True)
    if kw_list:
        top3 = '、'.join(f'{kw}({cnt}次)' for kw, cnt in kw_list[:3])
        info['ai_trend'] = f'关键词热度：{top3}。'
        if len(kw_list) > 3:
            info['ai_trend'] += f' 其他：{"、".join(kw for kw, _ in kw_list[3:6])}。'

    # 从 API 数据提取情绪分析
    sentiment = data.get('sentiment', {})
    if sentiment and sentiment.get('total_analyzed', 0) > 0:
        info['sentiment_summary'] = (
            f'正面{sentiment.get("positive_ratio", 0)}% / '
            f'中性{sentiment.get("neutral_ratio", 0)}% / '
            f'负面{sentiment.get("negative_ratio", 0)}%'
            f'（共{sentiment.get("total_analyzed", 0)}条评论）'
        )

    # 从日报内容提取风险提醒（搜索负面/风险相关内容）
    neg_ratio = sentiment.get('negative_ratio', 0)
    if neg_ratio > 20:
        info['risk_alert'] = f'负面评论占比{neg_ratio}%，需关注用户反馈。'
    elif neg_ratio > 10:
        info['risk_alert'] = f'负面评论占比{neg_ratio}%，建议持续监控。'
    else:
        info['risk_alert'] = '负面评论占比较低，舆情整体平稳。'

    # 从日报内容提取更多风险信息
    for line in report_content.split('\n'):
        line_lower = line.lower()
        if any(kw in line_lower for kw in ['风险', '问题', '投诉', '不满', 'bug', '故障']):
            if len(line) < 100 and not line.startswith('#'):
                info['risk_alert'] = line.strip().lstrip('- ').lstrip('* ')
                break

    return info


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

        # 第六步: 推送飞书机器人（如果启用）
        if FEISHU_ENABLED:
            try:
                sender = _get_feishu_sender()
                if sender:
                    report_info = _extract_report_info(report_content, data)
                    date_str = datetime.now().strftime('%Y-%m-%d')
                    report_url = REPORT_URL_TEMPLATE
                    feishu_success = sender.send_daily_report(
                        date_str=date_str,
                        hot_topics=report_info['hot_topics'],
                        ai_trend=report_info['ai_trend'],
                        risk_alert=report_info['risk_alert'],
                        report_url=report_url,
                        tenant_name=result['tenant_name'],
                        sentiment_summary=report_info['sentiment_summary'],
                    )
                    result['feishu_pushed'] = feishu_success
                    if feishu_success:
                        print(f'  📨 飞书推送成功')
                    else:
                        print(f'  ⚠️  飞书推送失败（不影响日报生成）')
                else:
                    print(f'  ⚠️  飞书推送器未初始化（不影响日报生成）')
                    result['feishu_pushed'] = False
            except Exception as fe:
                print(f'  ⚠️  飞书推送异常: {type(fe).__name__}: {fe}（不影响日报生成）')
                result['feishu_pushed'] = False
        else:
            result['feishu_pushed'] = None  # 未启用

    except Exception as e:
        result['error'] = f"{type(e).__name__}: {str(e)}"
    finally:
        result['duration'] = round(time.time() - start, 2)

    return result
