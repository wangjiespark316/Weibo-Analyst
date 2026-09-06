#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI Agent 调用 FastAPI 数据服务 — 多租户版
============================================
根据客户 API Key 自动获取对应数据范围，生成客户专属日报。

工作流：
  tenant_name → 读取 api_key → 调用 FastAPI（Authorization Header）
  → 获取对应数据 → 生成日报

租户配置：config/tenants.json

用法：
    .venv/bin/python step8_agent_verification/agent_client.py
    .venv/bin/python step8_agent_verification/agent_client.py --tenant hotspot_test
    .venv/bin/python step8_agent_verification/agent_client.py --list
"""
import os
import sys
import json
import argparse
import requests
from datetime import datetime

# ============================================================
# 配置
# ============================================================
API_BASE = os.getenv('WEIBO_API_BASE', 'https://weibo-analyst-api.onrender.com')
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
TENANTS_CONFIG = os.path.join(BASE_DIR, "config", "tenants.json")

# Agent 关注的关键词列表（用于多关键词趋势查询）
KEYWORDS = ['豆包', '飞书', 'AI办公', 'Agent', '企业AI', 'ChatGPT', '大模型']

# 报告类型元数据（用于选择日报模板，与 API 端 dataset_type 解耦）
REPORT_META = {
    'ai_industry': {
        'name': 'AI行业舆情分析',
        'role': '资深AI行业分析师，擅长从社交媒体数据中洞察AI技术趋势、产品竞争格局和企业机会',
    },
    'brand_monitor': {
        'name': '企业品牌监测',
        'role': '资深品牌舆情分析师，擅长监测品牌声量、正负面舆情、竞品对比和风险预警',
    },
    'general_hotspot': {
        'name': '全网热点分析',
        'role': '资深全网舆情分析师，擅长追踪热点事件、舆论趋势、公众情绪和热点预测',
    },
}


def load_tenants() -> dict:
    """加载租户配置文件"""
    with open(TENANTS_CONFIG, 'r', encoding='utf-8') as f:
        return json.load(f)


def get_tenant(tenant_key: str) -> dict:
    """根据租户 key 获取租户配置，不存在则退出"""
    tenants = load_tenants()
    if tenant_key not in tenants:
        print(f"错误：租户 '{tenant_key}' 不存在")
        print(f"可用租户：{', '.join(tenants.keys())}")
        sys.exit(1)
    return tenants[tenant_key]


# ============================================================
# 第一步：API 获取数据（带 Authorization Header）
# ============================================================

def call_api(endpoint: str, params: dict = None, api_key: str = None) -> dict:
    """调用 FastAPI 接口，自动添加 Authorization Header"""
    url = f"{API_BASE}{endpoint}"
    headers = {}
    if api_key:
        headers['Authorization'] = f"Bearer {api_key}"
    resp = requests.get(url, params=params, headers=headers, timeout=120)
    resp.raise_for_status()
    return resp.json()


def collect_all_data(tenant_key: str) -> dict:
    """Agent 工作流第一步：调用全部 API 收集数据（带租户 API Key）"""
    tenant = get_tenant(tenant_key)
    api_key = tenant['api_key']
    print(f"[Agent] 第一步：调用 FastAPI 收集数据（客户：{tenant['name']}）...")
    data = {'tenant_key': tenant_key, 'tenant_name': tenant['name']}

    # 1. 热点微博 TOP10（dataset_type 由服务端根据 API Key 决定，不再手动传）
    print("  → GET /api/hot-weibo?limit=10 (Authorization: Bearer ***)")
    data['hot_weibo'] = call_api("/api/hot-weibo", {"limit": 10}, api_key=api_key)

    # 2. 多关键词趋势
    print(f"  → GET /api/keyword-trend ({len(KEYWORDS)}个关键词)")
    data['keyword_trends'] = {}
    for kw in KEYWORDS:
        data['keyword_trends'][kw] = call_api(
            "/api/keyword-trend", {"keyword": kw, "days": 30}, api_key=api_key
        )

    # 3. 情感分析
    print("  → GET /api/sentiment?sample_size=3000")
    data['sentiment'] = call_api("/api/sentiment", {"sample_size": 3000}, api_key=api_key)

    # 4. 用户影响力（粉丝 + 互动）
    print("  → GET /api/influencers (followers + engagement)")
    data['influencers_followers'] = call_api(
        "/api/influencers", {"type": "followers", "limit": 10}, api_key=api_key
    )
    data['influencers_engagement'] = call_api(
        "/api/influencers", {"type": "engagement", "limit": 10}, api_key=api_key
    )

    # 5. 数据概览（从日报接口取）
    print("  → GET /api/daily-report")
    daily = call_api("/api/daily-report", api_key=api_key)
    data['daily_report_raw'] = daily

    print(f"[Agent] 数据收集完成：{len(data)} 个数据源")
    return data


# ============================================================
# 第二步：整理上下文
# ============================================================

def build_context(data: dict, tenant_key: str) -> str:
    """Agent 工作流第二步：将结构化数据整理为 LLM 可读的文本上下文"""
    tenant = get_tenant(tenant_key)
    print("[Agent] 第二步：整理上下文...")
    lines = []

    # --- 当前客户 ---
    lines.append("## 当前客户")
    lines.append(f"- 客户名称：{tenant['name']}")
    lines.append(f"- 数据范围：由 API 权限控制（租户绑定）")
    lines.append("")

    # --- 数据概览 ---
    lines.append("## 数据概览")
    lines.append(f"- 微博帖子数：{data['hot_weibo'].get('total', 'N/A')} 条")
    lines.append(f"- 情感分析样本：{data['sentiment']['total_analyzed']} 条评论")
    lines.append("")

    # --- 热点微博 TOP5 ---
    lines.append("## 热点微博 TOP5")
    for i, p in enumerate(data['hot_weibo']['data'][:5], 1):
        content = (p.get('content') or '')[:60].replace('\n', ' ')
        lines.append(
            f"{i}. **{p['username']}**（热度 {p['hotspot_score']}）"
            f"  👍{p['like_count']:,} 💬{p['comment_count']:,} 🔄{p['repost_count']:,}"
        )
        lines.append(f"   内容：{content}")
    lines.append("")

    # --- 关键词趋势 ---
    lines.append("## 关键词趋势（近30天）")
    lines.append("| 关键词 | 帖子提及 | 评论提及 | 总提及 |")
    lines.append("|---|---|---|---|")
    kw_list = []
    for kw, tr in data['keyword_trends'].items():
        kw_list.append((kw, tr['post_count'], tr['comment_count'], tr['total_mentions']))
    kw_list.sort(key=lambda x: x[3], reverse=True)
    for kw, pc, cc, tc in kw_list:
        lines.append(f"| {kw} | {pc} | {cc} | {tc} |")
    lines.append("")

    # --- 情感分析 ---
    s = data['sentiment']
    lines.append("## 用户情绪分析")
    lines.append(f"- 正面：{s['positive_count']} 条（{s['positive_ratio']}%）")
    lines.append(f"- 中性：{s['neutral_count']} 条（{s['neutral_ratio']}%）")
    lines.append(f"- 负面：{s['negative_count']} 条（{s['negative_ratio']}%）")
    if s['top_negative_viewpoints']:
        neg_words = ', '.join(f"{v['word']}({v['count']})"
                               for v in s['top_negative_viewpoints'][:8])
        lines.append(f"- 高频负面观点词：{neg_words}")
    lines.append("")

    # --- 高影响力账号 ---
    lines.append("## 高影响力账号")
    lines.append("### 粉丝量 TOP5")
    for i, u in enumerate(data['influencers_followers']['data'][:5], 1):
        lines.append(f"{i}. **{u['username']}** — 粉丝 {u['followers_count']:,}")
    lines.append("")
    lines.append("### 互动量 TOP5")
    for i, u in enumerate(data['influencers_engagement']['data'][:5], 1):
        lines.append(
            f"{i}. **{u['username']}** — 总互动 {u['total_engagement']:,}"
            f"（帖子 {u['post_count']} 条）"
        )
    lines.append("")

    context = '\n'.join(lines)
    print(f"[Agent] 上下文整理完成：{len(context)} 字符")
    return context


# ============================================================
# 第三步：构建 Agent Prompt 模板（含当前客户信息）
# ============================================================

def build_prompt(context: str, tenant_key: str) -> str:
    """Agent 工作流第三步：根据客户配置构建 Prompt"""
    tenant = get_tenant(tenant_key)
    report_type = tenant.get('report_type', 'ai_industry')
    meta = REPORT_META.get(report_type, REPORT_META['ai_industry'])

    print(f"[Agent] 第三步：构建 Agent Prompt（客户：{tenant['name']}）...")

    # 差异化输出要求
    if report_type == 'ai_industry':
        output_req = """### 一、AI行业热点
从热点微博中提炼AI行业核心事件，每条包含：排名、博主、事件、互动数据、行业影响点评。

### 二、产品竞争趋势
分析各AI产品关键词的提及量变化，指出热度最高的3个产品、竞争格局变化、新兴技术方向。

### 三、用户反馈分析
基于情感分析数据，分析用户对AI产品的整体满意度、正面反馈集中点、负面痛点。

### 四、技术方向变化
结合热点内容和关键词趋势，分析当前AI技术热点方向、技术叙事变化、未来可能爆发的方向。

### 五、企业机会建议
列出3-5条具体建议，包括产品机会点、技术布局方向、市场进入策略、需要规避的风险。"""

    elif report_type == 'brand_monitor':
        output_req = """### 一、品牌声量
统计品牌相关内容的提及量、互动量，评估品牌曝光度和影响力。

### 二、正负面舆情
基于情感分析数据，分析正面/中性/负面比例、正面舆情内容、负面舆情集中点。

### 三、用户反馈
从评论中提取用户对品牌/产品的真实反馈，包括最认可的方面、最不满意的方面、核心诉求。

### 四、竞品比较
对比品牌与竞品在声量、情感、互动量上的差异，分析竞争优劣势。

### 五、风险预警
列出3-5条需要关注的风险，包括正在发酵的负面话题、可能引发危机的信号、需要立即响应的事项。"""

    else:  # general_hotspot
        output_req = """### 一、全网热点
从热点微博中提炼当前最受关注的事件，每条包含：排名、博主、事件、互动数据、传播力点评。

### 二、热门事件
分析当前最热门的3-5个事件，包括核心内容、传播路径、热度变化、可能的发展方向。

### 三、舆论趋势
结合关键词和热点内容，分析当前舆论场核心议题、情绪走向、不同圈层关注差异。

### 四、用户情绪
基于情感分析数据，分析全网用户情绪整体分布、正面情绪来源、负面情绪触发点。

### 五、热点预测
基于当前数据趋势，预测未来可能持续发酵的热点、可能突然爆发的潜在话题、需要提前关注的舆论风险。"""

    prompt = f"""你是一位{meta['role']}。

## 当前客户
- 客户名称：{tenant['name']}
- 数据范围：由 API 权限控制（租户绑定，不可自行选择数据集）

## 你的任务
根据以下从微博数据仓库 API 获取的实时数据，为客户「{tenant['name']}」生成一份「{meta['name']}」日报。

## 数据上下文
{context}

## 输出要求
请严格按照以下结构输出 Markdown 格式日报：

{output_req}

## 注意事项
- 所有数据必须来自上方上下文，不得编造
- 数据范围由 API 权限控制，不要自行选择或切换数据集
- 分析要有洞察，不要简单罗列数据
- 语言专业、简洁，适合企业决策者阅读
- 输出纯 Markdown，不要包含代码块标记
- 分析视角必须符合「{meta['name']}」的定位
"""
    print(f"[Agent] Prompt 构建完成：{len(prompt)} 字符")
    return prompt


# ============================================================
# 第四步：模拟大模型生成日报（按 report_type 差异化模板）
# ============================================================

def _get_kw_list(data):
    kw_list = []
    for kw, tr in data['keyword_trends'].items():
        kw_list.append((kw, tr['post_count'], tr['comment_count'], tr['total_mentions']))
    kw_list.sort(key=lambda x: x[3], reverse=True)
    return kw_list


def _hotspot_section(data, lines, report_type):
    title_map = {
        'ai_industry': '## 一、AI行业热点',
        'brand_monitor': '## 一、品牌声量',
        'general_hotspot': '## 一、全网热点',
    }
    lines.append(title_map.get(report_type, '## 一、热点'))
    lines.append("")
    for i, p in enumerate(data['hot_weibo']['data'][:5], 1):
        content = (p.get('content') or '')[:50].replace('\n', ' ')
        lines.append(f"### {i}. {p['username']}")
        lines.append(f"- **核心内容**：{content}")
        lines.append(f"- **互动数据**：👍 {p['like_count']:,} / "
                     f"💬 {p['comment_count']:,} / 🔄 {p['repost_count']:,}")
        lines.append(f"- **热度指数**：{p['hotspot_score']}")
        if p['hotspot_score'] >= 95:
            comment = "超高热度话题，占据舆论场绝对注意力。"
        elif p['hotspot_score'] >= 80:
            comment = "高热度话题，社会关注度高，具备跨圈层传播潜力。"
        else:
            comment = "中等热度话题，在特定圈层内有影响力，值得持续跟踪。"
        lines.append(f"- **点评**：{comment}")
        lines.append("")


def _keyword_section(data, lines, kw_list, report_type):
    if report_type == 'brand_monitor':
        lines.append("## 四、竞品比较")
    elif report_type == 'general_hotspot':
        lines.append("## 三、舆论趋势")
    else:
        lines.append("## 二、产品竞争趋势")
    lines.append("")
    lines.append("### 关键词提及量排行")
    lines.append("")
    lines.append("| 排名 | 关键词 | 帖子提及 | 评论提及 | 总提及 |")
    lines.append("|---|---|---|---|---|")
    for i, (kw, pc, cc, tc) in enumerate(kw_list, 1):
        lines.append(f"| {i} | {kw} | {pc} | {cc} | {tc} |")
    lines.append("")
    top3 = kw_list[:3]
    lines.append("### 趋势洞察")
    lines.append("")
    if report_type == 'ai_industry':
        lines.append(f"- **热度最高**：{top3[0][0]}（总提及 {top3[0][3]}），"
                     "是当前AI领域最核心的讨论对象。")
        if len(top3) > 1:
            lines.append(f"- **竞争格局**：{top3[1][0]}（{top3[1][3]}）、"
                         f"{top3[2][0]}（{top3[2][3]}）构成第二梯队。")
        agent_mentions = next((tc for kw, pc, cc, tc in kw_list if kw == 'Agent'), 0)
        lines.append(f"- **技术方向**：Agent 概念提及 {agent_mentions} 次，"
                     "反映行业认知从「AI工具」向「AI智能体」演进。")
    elif report_type == 'brand_monitor':
        lines.append(f"- **声量最高**：{top3[0][0]}（总提及 {top3[0][3]}）。")
        if len(top3) > 1:
            lines.append(f"- **竞品对比**：{top3[1][0]}（{top3[1][3]}）、"
                         f"{top3[2][0]}（{top3[2][3]}）。")
    else:
        lines.append(f"- **核心议题**：{top3[0][0]}（总提及 {top3[0][3]}）。")
        if len(top3) > 1:
            lines.append(f"- **关注多元**：{top3[1][0]}（{top3[1][3]}）、"
                         f"{top3[2][0]}（{top3[2][3]}）等话题并行。")
    lines.append("")


def _sentiment_section(data, lines, report_type):
    s = data['sentiment']
    if report_type == 'ai_industry':
        lines.append("## 三、用户反馈分析")
    elif report_type == 'brand_monitor':
        lines.append("## 二、正负面舆情")
    else:
        lines.append("## 四、用户情绪")
    lines.append("")
    lines.append(f"基于 {s['total_analyzed']} 条评论的情感分析结果：")
    lines.append("")
    lines.append("| 情绪 | 数量 | 占比 |")
    lines.append("|---|---|---|")
    lines.append(f"| 😊 正面 | {s['positive_count']:,} | {s['positive_ratio']}% |")
    lines.append(f"| 😐 中性 | {s['neutral_count']:,} | {s['neutral_ratio']}% |")
    lines.append(f"| 😠 负面 | {s['negative_count']:,} | {s['negative_ratio']}% |")
    lines.append("")

    if s['positive_ratio'] > 50:
        mood = "整体偏正面"
    elif s['negative_ratio'] > 30:
        mood = "存在一定负面情绪压力"
    else:
        mood = "整体中性偏正面"

    lines.append("### 情绪解读")
    lines.append("")
    if report_type == 'ai_industry':
        lines.append(f"- **整体满意度**：{mood}。正面评论占比 {s['positive_ratio']}%。")
        lines.append("- **正面集中**：产品易用性、效率提升和功能创新。")
        lines.append(f"- **负面痛点**：负面占 {s['negative_ratio']}%，"
                     "主要围绕产品体验、功能期望落差、响应速度。")
    elif report_type == 'brand_monitor':
        lines.append(f"- **品牌健康度**：{mood}。正面占比 {s['positive_ratio']}%。")
        lines.append("- **正面舆情**：产品品质、服务体验和品牌形象。")
        lines.append(f"- **负面舆情**：负面占 {s['negative_ratio']}%，需关注集中性投诉。")
    else:
        lines.append(f"- **整体情绪**：{mood}。正面占比 {s['positive_ratio']}%。")
        lines.append("- **正面来源**：正能量事件赞赏、有趣内容分享、社会进步肯定。")
        lines.append(f"- **负面触发**：负面占 {s['negative_ratio']}%，"
                     "由争议性事件、社会问题讨论触发。")

    if s['top_negative_viewpoints']:
        neg = ', '.join(v['word'] for v in s['top_negative_viewpoints'][:5])
        lines.append(f"- **高频负面词**：{neg}（注：部分词为中性词在负面语境中出现）")
    lines.append("")


def _influencers_section(data, lines, report_type):
    if report_type == 'brand_monitor':
        lines.append("## 三、用户反馈")
    elif report_type == 'general_hotspot':
        return  # general_hotspot 不单独设影响力板块
    else:
        lines.append("## 四、技术方向变化")
    lines.append("")
    if report_type == 'ai_industry':
        lines.append("### AI领域关键账号")
        lines.append("")
        lines.append("### 互动量 TOP5（AI领域KOL）")
        lines.append("")
        for i, u in enumerate(data['influencers_engagement']['data'][:5], 1):
            lines.append(f"{i}. **{u['username']}** — 总互动 {u['total_engagement']:,}"
                         f"（帖子 {u['post_count']} 条）")
        lines.append("")
        lines.append("### 技术方向判断")
        lines.append("")
        lines.append("- 当前AI技术热点集中在大模型应用、Agent智能体和AI办公场景。")
        lines.append("- 技术叙事正从「AI能做什么」向「AI如何融入工作流」转变。")
        lines.append("- 企业级AI应用和垂直场景解决方案是未来可能的爆发方向。")
    elif report_type == 'brand_monitor':
        lines.append("### 品牌相关高互动账号")
        lines.append("")
        for i, u in enumerate(data['influencers_engagement']['data'][:5], 1):
            lines.append(f"{i}. **{u['username']}** — 总互动 {u['total_engagement']:,}"
                         f"（帖子 {u['post_count']} 条）")
        lines.append("")
        lines.append("### 用户核心诉求")
        lines.append("")
        lines.append("- 用户最关注产品品质和使用体验。")
        lines.append("- 服务响应速度和问题解决能力是影响口碑的关键因素。")
        lines.append("- 品牌透明度和社会责任感逐渐成为用户评价的重要维度。")
    lines.append("")


def _summary_and_advice(data, lines, kw_list, report_type):
    s = data['sentiment']
    if report_type == 'ai_industry':
        lines.append("## 五、企业机会建议")
        lines.append("")
        lines.append(f"1. **聚焦「{kw_list[0][0]}」生态**：作为提及量最高的关键词，"
                     "其周边工具链、插件生态和行业解决方案存在大量机会。")
        lines.append("")
        lines.append("2. **布局 Agent 智能体方向**：Agent 概念持续升温，"
                     "代表行业认知从工具向智能体升级，建议提前布局。")
        lines.append("")
        lines.append(f"3. **关注用户体验痛点**：当前负面评论占比 {s['negative_ratio']}%，"
                     "改善产品体验可显著提升用户满意度。")
        lines.append("")
        lines.append("4. **拓展垂直行业场景**：通用AI工具竞争激烈，"
                     "建议向法律、医疗、教育、金融等垂直行业深入。")
        lines.append("")
        lines.append("5. **建立技术趋势监控机制**：AI技术迭代快速，"
                     "建议持续监控新兴技术方向和竞品动态。")

    elif report_type == 'brand_monitor':
        lines.append("## 五、风险预警")
        lines.append("")
        lines.append(f"1. **监控负面舆情变化**：当前负面占比 {s['negative_ratio']}%，"
                     "若突破 35% 需启动危机预警机制。")
        lines.append("")
        lines.append("2. **关注竞品动态**：竞品声量和情感变化是重要市场信号，"
                     "建议每周对比。")
        lines.append("")
        lines.append("3. **快速响应用户投诉**：对高赞负面评论需在24小时内响应。")
        lines.append("")
        lines.append("4. **保护品牌声誉**：监测品牌被冒用、虚假宣传或恶意攻击情况。")
        lines.append("")
        lines.append("5. **建立品牌健康度指标**：将声量、情感、互动量纳入日常监控。")

    else:  # general_hotspot
        lines.append("## 五、热点预测")
        lines.append("")
        lines.append(f"1. **持续发酵热点**：「{kw_list[0][0]}」相关话题"
                     f"（提及 {kw_list[0][3]} 次）预计将持续讨论。")
        lines.append("")
        lines.append("2. **潜在爆发话题**：社会民生、科技突破和娱乐事件"
                     "是最容易突然爆发的话题类型。")
        lines.append("")
        lines.append(f"3. **舆论风险预警**：当前负面情绪占比 {s['negative_ratio']}%，"
                     "若出现触发公众情绪的事件，负面情绪可能快速放大。")
        lines.append("")
        lines.append("4. **可借势正面热点**：高互动量的正能量事件"
                     "是品牌借势营销的良好机会。")
        lines.append("")
        lines.append("5. **建立热点预警机制**：设置关键词监控和热度阈值预警，"
                     "在热点爆发初期及时捕捉。")
    lines.append("")


def simulate_llm_report(data: dict, context: str, tenant_key: str) -> str:
    """模拟大模型输出：基于真实 API 数据生成客户专属日报"""
    tenant = get_tenant(tenant_key)
    report_type = tenant.get('report_type', 'ai_industry')
    meta = REPORT_META.get(report_type, REPORT_META['ai_industry'])

    print(f"[Agent] 第四步：模拟大模型生成舆情日报（客户：{tenant['name']}）...")
    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    kw_list = _get_kw_list(data)

    lines = [f"# {meta['name']}日报", "",
             f"> 客户：{tenant['name']}",
             f"> 生成时间：{now}",
             f"> 数据范围：由 API 权限控制（租户绑定）", ""]

    # 按 report_type 调用差异化板块
    if report_type == 'ai_industry':
        _hotspot_section(data, lines, report_type)
        _keyword_section(data, lines, kw_list, report_type)
        _sentiment_section(data, lines, report_type)
        _influencers_section(data, lines, report_type)
    elif report_type == 'brand_monitor':
        _hotspot_section(data, lines, report_type)
        _sentiment_section(data, lines, report_type)
        _influencers_section(data, lines, report_type)
        _keyword_section(data, lines, kw_list, report_type)
    else:  # general_hotspot
        _hotspot_section(data, lines, report_type)
        _keyword_section(data, lines, kw_list, report_type)
        _sentiment_section(data, lines, report_type)
    _summary_and_advice(data, lines, kw_list, report_type)

    report = '\n'.join(lines)
    print(f"[Agent] 日报生成完成：{len(report)} 字符")
    return report


# ============================================================
# 主流程
# ============================================================

def main(tenant_key: str = 'ai_test'):
    tenants = load_tenants()
    if tenant_key not in tenants:
        print(f"错误：租户 '{tenant_key}' 不存在")
        print(f"可用租户：{', '.join(tenants.keys())}")
        sys.exit(1)

    tenant = tenants[tenant_key]
    print("=" * 60)
    print(f"AI Agent 多租户日报生成 — {tenant['name']}")
    print(f"租户 Key：{tenant_key}")
    print("=" * 60)
    print()

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

    # 第一步：API 获取数据（带 API Key）
    data = collect_all_data(tenant_key)

    # 保存原始 API 数据
    raw_path = os.path.join(OUTPUT_DIR, f"api_raw_data_{tenant_key}_{timestamp}.json")
    with open(raw_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n[输出] 原始 API 数据已保存：{raw_path}")

    # 第二步：整理上下文
    context = build_context(data, tenant_key)
    context_path = os.path.join(OUTPUT_DIR, f"agent_context_{tenant_key}_{timestamp}.txt")
    with open(context_path, 'w', encoding='utf-8') as f:
        f.write(context)
    print(f"[输出] Agent 上下文已保存：{context_path}")

    # 第三步：构建 Prompt
    prompt = build_prompt(context, tenant_key)
    prompt_path = os.path.join(OUTPUT_DIR, f"agent_prompt_{tenant_key}_{timestamp}.txt")
    with open(prompt_path, 'w', encoding='utf-8') as f:
        f.write(prompt)
    print(f"[输出] Agent Prompt 已保存：{prompt_path}")

    # 第四步：模拟大模型生成日报
    report = simulate_llm_report(data, context, tenant_key)
    report_path = os.path.join(OUTPUT_DIR, f"agent_daily_report_{tenant_key}_{timestamp}.md")
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report)
    print(f"[输出] Agent 舆情日报已保存：{report_path}")

    print()
    print("=" * 60)
    print(f"Agent 多租户日报生成完成（{tenant['name']}）！")
    print("=" * 60)
    print(f"\n产出文件：")
    print(f"  1. API 原始数据：{raw_path}")
    print(f"  2. Agent 上下文：{context_path}")
    print(f"  3. Agent Prompt：{prompt_path}")
    print(f"  4. 舆情日报：    {report_path}")

    return {
        'raw_data': raw_path,
        'context': context_path,
        'prompt': prompt_path,
        'report': report_path,
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='AI Agent 多租户微博舆情日报生成器')
    parser.add_argument('--tenant', type=str, default='ai_test',
                        help='租户 key（默认: ai_test）')
    parser.add_argument('--list', action='store_true',
                        help='列出所有可用租户')
    args = parser.parse_args()

    if args.list:
        tenants = load_tenants()
        print("可用租户：")
        for key, t in tenants.items():
            print(f"  {key}: {t['name']} (report_type={t.get('report_type', 'N/A')})")
    else:
        main(tenant_key=args.tenant)
