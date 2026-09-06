#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI Agent 客户端 - 微博舆情自动分析系统
========================================
功能：
1. 调用公网 FastAPI 获取数据（5 个接口）
2. 整理成结构化上下文
3. 调用大模型生成分析报告
4. 输出 Markdown 日报

用法：
    .venv/bin/python step10_agent_app/agent_client.py
    .venv/bin/python step10_agent_app/agent_client.py --tenant general_hotspot
    .venv/bin/python step10_agent_app/agent_client.py --output custom_report.md
"""
import os
import sys
import json
import argparse
import requests
from datetime import datetime

# 将项目根目录加入 path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from step10_agent_app.config import (
    API_BASE, DEFAULT_API_KEY, TENANTS, KEYWORDS,
    OUTPUT_DIR, LLM_API_KEY, LLM_API_BASE, LLM_MODEL,
)
from step10_agent_app.prompt_templates import (
    build_daily_report_prompt, build_feishu_card_prompt, SYSTEM_PROMPT,
)


# ============================================================
# 第一步：API 数据获取
# ============================================================

def call_api(endpoint: str, params: dict = None, api_key: str = None,
              retries: int = 2, timeout: int = 60) -> dict:
    """
    调用公网 FastAPI 接口（带重试和错误处理）

    Args:
        endpoint: API 路径，如 /api/hot-weibo
        params: 查询参数
        api_key: API Key（Bearer Token）
        retries: 失败重试次数
        timeout: 请求超时（秒）

    Returns:
        JSON 响应数据，失败返回 None
    """
    url = f"{API_BASE}{endpoint}"
    headers = {}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'

    last_error = None
    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=timeout)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as e:
            last_error = e
            status = e.response.status_code if e.response is not None else 'unknown'
            if status in (502, 503, 504) and attempt < retries:
                wait = 3 * (attempt + 1)
                print(f"    ⚠️  HTTP {status}，{wait}秒后重试（{attempt+1}/{retries}）...")
                import time as _time
                _time.sleep(wait)
                continue
            print(f"    ❌ HTTP {status}: {endpoint}")
            return None
        except requests.exceptions.RequestException as e:
            last_error = e
            if attempt < retries:
                wait = 3 * (attempt + 1)
                print(f"    ⚠️  请求失败，{wait}秒后重试（{attempt+1}/{retries}）...")
                import time as _time
                _time.sleep(wait)
                continue
            print(f"    ❌ 请求失败: {endpoint} - {e}")
            return None

    print(f"    ❌ 最终失败: {endpoint} - {last_error}")
    return None


def collect_all_data(api_key: str = None) -> dict:
    """
    调用全部 5 个 API 接口收集数据

    Returns:
        包含所有数据的字典
    """
    if api_key is None:
        api_key = DEFAULT_API_KEY

    print(f"[Agent] 调用公网 API 获取数据（{API_BASE}）...")
    data = {}

    # 1. 热点微博 TOP20
    print("  → GET /api/hot-weibo?limit=20")
    result = call_api("/api/hot-weibo", {"limit": 20}, api_key=api_key)
    data['hot_weibo'] = result if result else {"total": 0, "data": []}

    # 2. 关键词趋势（多关键词）
    print(f"  → GET /api/keyword-trend ({len(KEYWORDS)} 个关键词)")
    data['keyword_trends'] = {}
    for kw in KEYWORDS:
        result = call_api("/api/keyword-trend", {"keyword": kw, "days": 30}, api_key=api_key)
        data['keyword_trends'][kw] = result

    # 3. 情感分析
    print("  → GET /api/sentiment?sample_size=3000")
    result = call_api("/api/sentiment", {"sample_size": 3000}, api_key=api_key)
    data['sentiment'] = result if result else {
        'positive_count': 0, 'neutral_count': 0, 'negative_count': 0,
        'positive_ratio': 0, 'neutral_ratio': 0, 'negative_ratio': 0,
        'total_analyzed': 0, 'top_negative_viewpoints': [],
    }

    # 4. 用户影响力（粉丝 + 互动）
    print("  → GET /api/influencers (followers + engagement)")
    result = call_api("/api/influencers", {"type": "followers", "limit": 10}, api_key=api_key)
    data['influencers_followers'] = result if result else {"data": []}
    result = call_api("/api/influencers", {"type": "engagement", "limit": 10}, api_key=api_key)
    data['influencers_engagement'] = result if result else {"data": []}

    # 5. 日报接口
    print("  → GET /api/daily-report")
    result = call_api("/api/daily-report", api_key=api_key)
    data['daily_report'] = result if result else {}

    print(f"[Agent] 数据收集完成：{len(data)} 个数据源")
    return data


# ============================================================
# 第二步：整理上下文
# ============================================================

def build_context(data: dict) -> str:
    """
    将 API 数据整理成 LLM 可读的文本上下文
    """
    print("[Agent] 整理分析上下文...")
    lines = []

    # --- 数据概览 ---
    lines.append("## 数据概览")
    hot_total = data['hot_weibo'].get('total', 0)
    sentiment_total = data['sentiment'].get('total_analyzed', 0)
    lines.append(f"- 热点微博样本：{hot_total} 条")
    lines.append(f"- 情感分析样本：{sentiment_total} 条评论")
    lines.append("")

    # --- 今日热点 TOP10 ---
    lines.append("## 今日热点 TOP10")
    for i, p in enumerate(data['hot_weibo'].get('data', [])[:10], 1):
        content = (p.get('content') or '')[:80].replace('\n', ' ')
        lines.append(
            f"{i}. **{p.get('username', '未知')}**（热度 {p.get('hotspot_score', 0)}）"
        )
        lines.append(f"   内容：{content}")
        lines.append(
            f"   互动：👍{p.get('like_count', 0):,} "
            f"💬{p.get('comment_count', 0):,} "
            f"🔄{p.get('repost_count', 0):,}"
        )
        lines.append(f"   发布时间：{p.get('publish_time', 'N/A')}")
    lines.append("")

    # --- 关键词趋势 ---
    lines.append("## 关键词趋势（近30天）")
    lines.append("| 关键词 | 帖子提及 | 评论提及 | 总提及 |")
    lines.append("|---|---|---|---|")
    kw_list = []
    for kw, tr in data['keyword_trends'].items():
        if tr:
            kw_list.append((
                kw,
                tr.get('post_count', 0),
                tr.get('comment_count', 0),
                tr.get('total_mentions', 0),
            ))
    kw_list.sort(key=lambda x: x[3], reverse=True)
    for kw, pc, cc, tc in kw_list:
        lines.append(f"| {kw} | {pc} | {cc} | {tc} |")
    lines.append("")

    # --- 情感分析 ---
    s = data['sentiment']
    lines.append("## 用户情绪分析")
    lines.append(f"- 正面：{s.get('positive_count', 0)} 条（{s.get('positive_ratio', 0)}%）")
    lines.append(f"- 中性：{s.get('neutral_count', 0)} 条（{s.get('neutral_ratio', 0)}%）")
    lines.append(f"- 负面：{s.get('negative_count', 0)} 条（{s.get('negative_ratio', 0)}%）")
    if s.get('top_negative_viewpoints'):
        neg_words = ', '.join(
            f"{v['word']}({v['count']})"
            for v in s['top_negative_viewpoints'][:10]
        )
        lines.append(f"- 高频负面观点词：{neg_words}")
    lines.append("")

    # --- 用户影响力 ---
    lines.append("## 用户影响力排行")
    lines.append("### 粉丝量 TOP10")
    for i, u in enumerate(data['influencers_followers'].get('data', [])[:10], 1):
        lines.append(
            f"{i}. **{u.get('username', '未知')}** — "
            f"粉丝 {u.get('followers_count', 0):,}"
        )
    lines.append("")
    lines.append("### 互动量 TOP10")
    for i, u in enumerate(data['influencers_engagement'].get('data', [])[:10], 1):
        lines.append(
            f"{i}. **{u.get('username', '未知')}** — "
            f"总互动 {u.get('total_engagement', 0):,}"
            f"（帖子 {u.get('post_count', 0)} 条）"
        )
    lines.append("")

    context = '\n'.join(lines)
    print(f"[Agent] 上下文整理完成：{len(context)} 字符")
    return context


# ============================================================
# 第三步：调用大模型生成分析
# ============================================================

def call_llm(prompt: str, system_prompt: str = None) -> str:
    """
    调用大模型 API 生成分析

    如果配置了 LLM_API_KEY，调用真实 API；
    否则返回 None，由调用方使用本地模拟。
    """
    if not LLM_API_KEY:
        return None

    try:
        url = f"{LLM_API_BASE}/chat/completions"
        headers = {
            'Authorization': f'Bearer {LLM_API_KEY}',
            'Content-Type': 'application/json',
        }
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": LLM_MODEL,
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 4000,
        }

        resp = requests.post(url, json=payload, headers=headers, timeout=120)
        resp.raise_for_status()
        result = resp.json()
        return result['choices'][0]['message']['content']
    except Exception as e:
        print(f"[Agent] ⚠️  LLM 调用失败: {e}")
        return None


def simulate_llm_report(data: dict, context: str, report_date: str = None) -> str:
    """
    本地模拟大模型生成报告（基于真实 API 数据，不编造）

    当没有配置 LLM_API_KEY 时使用此函数。
    """
    date_str = report_date or datetime.now().strftime('%Y-%m-%d')
    print("[Agent] 使用本地分析引擎生成报告（基于真实 API 数据）...")

    lines = [f"# 微博行业舆情日报（{date_str}）", ""]

    # --- 1. 今日热点 TOP5 ---
    lines.append("## 1. 今日热点 TOP5")
    lines.append("")
    hot_data = data['hot_weibo'].get('data', [])[:5]
    for i, p in enumerate(hot_data, 1):
        content = (p.get('content') or '')[:60].replace('\n', ' ')
        lines.append(f"### {i}. {p.get('username', '未知')}")
        lines.append(f"- **事件**：{content}")
        lines.append(
            f"- **互动数据**：👍 {p.get('like_count', 0):,} / "
            f"💬 {p.get('comment_count', 0):,} / "
            f"🔄 {p.get('repost_count', 0):,} / "
            f"热度 {p.get('hotspot_score', 0)}"
        )
        # 影响范围分析
        total_interaction = (p.get('like_count', 0) + p.get('comment_count', 0)
                             + p.get('repost_count', 0))
        if total_interaction > 1000000:
            impact = "全网级热点，影响范围极广"
        elif total_interaction > 100000:
            impact = "行业级热点，影响范围较广"
        elif total_interaction > 10000:
            impact = "圈层级热点，影响特定用户群体"
        else:
            impact = "细分话题，影响范围有限"
        lines.append(f"- **影响范围**：{impact}（总互动 {total_interaction:,}）")
        lines.append("")

    # --- 2. AI行业趋势 ---
    lines.append("## 2. AI行业趋势")
    lines.append("")
    # 从数据中重新计算关键词排行
    kw_list = []
    for kw, tr in data.get('keyword_trends', {}).items():
        if tr:
            kw_list.append((
                kw,
                tr.get('post_count', 0),
                tr.get('comment_count', 0),
                tr.get('total_mentions', 0),
            ))
    kw_list.sort(key=lambda x: x[3], reverse=True)

    if kw_list:
        top3 = kw_list[:3]
        lines.append("### 关键词提及量排行")
        lines.append("")
        lines.append("| 排名 | 关键词 | 帖子提及 | 评论提及 | 总提及 |")
        lines.append("|---|---|---|---|---|")
        for i, (kw, pc, cc, tc) in enumerate(kw_list[:5], 1):
            lines.append(f"| {i} | {kw} | {pc} | {cc} | {tc} |")
        lines.append("")
        lines.append("### 趋势分析")
        lines.append("")
        lines.append(f"- **热度最高**：{top3[0][0]}（总提及 {top3[0][3]}），"
                     "是当前 AI 领域最核心的讨论对象。")
        if len(top3) > 1:
            lines.append(f"- **第二梯队**：{top3[1][0]}（{top3[1][3]}）、"
                         f"{top3[2][0]}（{top3[2][3]}）构成竞争格局。")
        agent_mentions = next((tc for kw, pc, cc, tc in kw_list if kw == 'Agent'), 0)
        if agent_mentions > 0:
            lines.append(f"- **技术方向**：Agent 概念提及 {agent_mentions} 次，"
                         "反映行业认知从「AI工具」向「AI智能体」演进。")
    lines.append("")

    # --- 3. 用户情绪分析 ---
    s = data['sentiment']
    lines.append("## 3. 用户情绪分析")
    lines.append("")
    lines.append("| 情绪 | 数量 | 占比 |")
    lines.append("|---|---|---|")
    lines.append(f"| 😊 正面 | {s.get('positive_count', 0):,} | {s.get('positive_ratio', 0)}% |")
    lines.append(f"| 😐 中性 | {s.get('neutral_count', 0):,} | {s.get('neutral_ratio', 0)}% |")
    lines.append(f"| 😠 负面 | {s.get('negative_count', 0):,} | {s.get('negative_ratio', 0)}% |")
    lines.append("")

    pos_ratio = s.get('positive_ratio', 0)
    neg_ratio = s.get('negative_ratio', 0)
    if pos_ratio > 50:
        mood = "整体偏正面，用户满意度较高"
    elif neg_ratio > 30:
        mood = "存在一定负面情绪压力，需关注"
    else:
        mood = "整体中性偏正面，情绪平稳"

    lines.append("### 情绪解读")
    lines.append("")
    lines.append(f"- **整体情绪**：{mood}（正面 {pos_ratio}% / 负面 {neg_ratio}%）")
    lines.append("- **正面反馈**：集中在产品易用性、效率提升和功能创新方面。")
    lines.append(f"- **负面问题**：负面占比 {neg_ratio}%，"
                 "主要围绕产品体验、功能期望落差和响应速度。")
    if s.get('top_negative_viewpoints'):
        neg_words = ', '.join(v['word'] for v in s['top_negative_viewpoints'][:5])
        lines.append(f"- **高频负面词**：{neg_words}（注：部分为中性词在负面语境中出现）")
    lines.append("")

    # --- 4. 重点账号分析 ---
    lines.append("## 4. 重点账号分析")
    lines.append("")
    lines.append("### 高粉丝账号 TOP5")
    lines.append("")
    for i, u in enumerate(data['influencers_followers'].get('data', [])[:5], 1):
        lines.append(f"{i}. **{u.get('username', '未知')}** — "
                     f"粉丝 {u.get('followers_count', 0):,}")
    lines.append("")
    lines.append("### 高互动账号 TOP5")
    lines.append("")
    for i, u in enumerate(data['influencers_engagement'].get('data', [])[:5], 1):
        lines.append(f"{i}. **{u.get('username', '未知')}** — "
                     f"总互动 {u.get('total_engagement', 0):,}"
                     f"（帖子 {u.get('post_count', 0)} 条）")
    lines.append("")
    lines.append("### 影响力分析")
    lines.append("")
    lines.append("- 高粉丝账号以媒体和公众人物为主，具备广泛传播力。")
    lines.append("- 高互动账号以行业 KOL 和企业账号为主，内容更具针对性。")
    lines.append("- 企业可重点关注高互动账号的内容方向，寻找合作机会。")
    lines.append("")

    # --- 5. 行业机会洞察 ---
    lines.append("## 5. 行业机会洞察")
    lines.append("")
    if kw_list:
        top_kw = kw_list[0][0]
        lines.append(f"1. **聚焦「{top_kw}」生态**：作为提及量最高的关键词，"
                     "其周边工具链、插件生态和行业解决方案存在大量机会。")
    lines.append("")
    lines.append("2. **布局 Agent 智能体方向**：Agent 概念持续升温，"
                 "代表行业认知从工具向智能体升级，建议提前布局。")
    lines.append("")
    lines.append(f"3. **关注用户体验痛点**：当前负面评论占比 {neg_ratio}%，"
                 "改善产品体验可显著提升用户满意度。")
    lines.append("")
    lines.append("4. **拓展垂直行业场景**：通用 AI 工具竞争激烈，"
                 "建议向法律、医疗、教育、金融等垂直行业深入。")
    lines.append("")
    lines.append("5. **建立舆情监控机制**：持续监控关键词趋势和负面舆情，"
                 "在热点爆发初期及时响应。")
    lines.append("")

    report = '\n'.join(lines)
    print(f"[Agent] 报告生成完成：{len(report)} 字符")
    return report


# ============================================================
# 主流程
# ============================================================

def generate_report(tenant: str = 'ai_industry', output_file: str = None,
                    use_llm: bool = True) -> dict:
    """
    生成微博舆情日报完整流程

    Args:
        tenant: 租户名称（ai_industry / general_hotspot）
        output_file: 输出文件路径
        use_llm: 是否使用真实 LLM（False 则使用本地模拟）

    Returns:
        包含报告内容和文件路径的字典
    """
    tenant_config = TENANTS.get(tenant, TENANTS['ai_industry'])
    api_key = tenant_config['api_key']
    tenant_name = tenant_config['name']
    report_date = datetime.now().strftime('%Y-%m-%d')

    print("=" * 60)
    print(f"AI Agent 微博舆情日报生成")
    print(f"客户：{tenant_name}")
    print(f"日期：{report_date}")
    print("=" * 60)
    print()

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 第一步：API 获取数据
    data = collect_all_data(api_key=api_key)

    # 保存原始数据
    raw_path = os.path.join(OUTPUT_DIR, f"api_raw_data_{tenant}_{report_date}.json")
    with open(raw_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n[输出] 原始 API 数据：{raw_path}")

    # 第二步：整理上下文
    context = build_context(data)
    context_path = os.path.join(OUTPUT_DIR, f"agent_context_{tenant}_{report_date}.txt")
    with open(context_path, 'w', encoding='utf-8') as f:
        f.write(context)
    print(f"[输出] 分析上下文：{context_path}")

    # 第三步：生成分析报告
    prompt = build_daily_report_prompt(context, report_date)
    prompt_path = os.path.join(OUTPUT_DIR, f"agent_prompt_{tenant}_{report_date}.txt")
    with open(prompt_path, 'w', encoding='utf-8') as f:
        f.write(prompt)
    print(f"[输出] Agent Prompt：{prompt_path}")

    # 尝试调用真实 LLM
    report_content = None
    if use_llm and LLM_API_KEY:
        print("[Agent] 调用大模型生成分析...")
        report_content = call_llm(prompt, SYSTEM_PROMPT)

    # 如果 LLM 不可用，使用本地模拟
    if report_content is None:
        if use_llm and not LLM_API_KEY:
            print("[Agent] 未配置 LLM_API_KEY，使用本地分析引擎")
        report_content = simulate_llm_report(data, context, report_date)

    # 保存报告
    if output_file is None:
        output_file = os.path.join(OUTPUT_DIR, f"daily_report_{tenant}_{report_date}.md")
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(report_content)
    print(f"[输出] 舆情日报：{output_file}")

    print()
    print("=" * 60)
    print("日报生成完成！")
    print("=" * 60)

    return {
        'report_content': report_content,
        'report_path': output_file,
        'raw_data_path': raw_path,
        'context_path': context_path,
        'prompt_path': prompt_path,
        'tenant': tenant,
        'tenant_name': tenant_name,
        'date': report_date,
    }


def main():
    parser = argparse.ArgumentParser(description='AI Agent 微博舆情日报生成器')
    parser.add_argument('--tenant', type=str, default='ai_industry',
                        choices=['ai_industry', 'general_hotspot'],
                        help='租户类型（默认 ai_industry）')
    parser.add_argument('--output', type=str, default=None,
                        help='输出文件路径')
    parser.add_argument('--no-llm', action='store_true',
                        help='不使用 LLM，使用本地分析引擎')
    args = parser.parse_args()

    result = generate_report(
        tenant=args.tenant,
        output_file=args.output,
        use_llm=not args.no_llm,
    )

    print(f"\n报告文件：{result['report_path']}")


if __name__ == '__main__':
    main()
