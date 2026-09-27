#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI技术标签库配置
维护需要监控的AI技术方向，用于技术趋势分析
"""

# AI技术方向列表
AI_TECHNOLOGIES = [
    # Agent与智能体
    {
        "name": "Agent",
        "category": "智能体",
        "aliases": ["AI Agent", "智能体", "AI智能体", "自主智能体", "Agentic AI"]
    },
    # 多模态
    {
        "name": "多模态",
        "category": "模型能力",
        "aliases": ["多模态大模型", "Multimodal", "图文理解", "视频理解", "语音交互"]
    },
    # AI编程
    {
        "name": "AI编程",
        "category": "开发工具",
        "aliases": ["AI代码", "代码生成", "Copilot", "AI编程助手", "代码助手", "AI Coding"]
    },
    # AI视频
    {
        "name": "AI视频",
        "category": "内容生成",
        "aliases": ["视频生成", "AI视频生成", "Sora", "可灵", "即梦", "文生视频", "AI Video"]
    },
    # AI绘画
    {
        "name": "AI绘画",
        "category": "内容生成",
        "aliases": ["AI画图", "图像生成", "文生图", "Midjourney", "Stable Diffusion", "AI绘画"]
    },
    # RAG
    {
        "name": "RAG",
        "category": "模型技术",
        "aliases": ["检索增强生成", "检索增强", "RAG技术", "向量检索", "知识库检索"]
    },
    # 知识库
    {
        "name": "知识库",
        "category": "企业应用",
        "aliases": ["企业知识库", "知识管理", "智能知识库", "Knowledge Base"]
    },
    # 端侧AI
    {
        "name": "端侧AI",
        "category": "部署方式",
        "aliases": ["端侧大模型", "端云协同", "手机AI", "本地大模型", "On-device AI", "端侧智能"]
    },
    # 具身智能
    {
        "name": "具身智能",
        "category": "机器人",
        "aliases": ["Embodied AI", "具身大模型", "人形机器人", "机器人智能"]
    },
    # 机器人
    {
        "name": "机器人",
        "category": "机器人",
        "aliases": ["人形机器人", "工业机器人", "服务机器人", "Robot", "机器人"]
    },
    # AI办公
    {
        "name": "AI办公",
        "category": "企业应用",
        "aliases": ["智能办公", "办公自动化", "AI Office", "智能文档", "会议纪要", "AI助手办公"]
    },
    # 自动驾驶
    {
        "name": "自动驾驶",
        "category": "交通出行",
        "aliases": ["智能驾驶", "无人驾驶", "自动驾驶", "Autonomous Driving", "智驾", "世界模型"]
    },
    # 大模型
    {
        "name": "大模型",
        "category": "基础模型",
        "aliases": ["大语言模型", "LLM", "基础大模型", "通用大模型", "大模型技术"]
    },
    # 小模型
    {
        "name": "小模型",
        "category": "基础模型",
        "aliases": ["轻量模型", "小参数模型", "SLM", "端侧小模型", "高效模型"]
    },
    # 开源模型
    {
        "name": "开源模型",
        "category": "模型生态",
        "aliases": ["开源大模型", "开源AI", "Open Source", "开源生态", "开源LLM"]
    },
    # AI搜索
    {
        "name": "AI搜索",
        "category": "信息获取",
        "aliases": ["智能搜索", "AI搜索引擎", "Perplexity", "搜索增强", "AI Search"]
    }
]


def get_all_technologies():
    """获取所有AI技术方向"""
    return AI_TECHNOLOGIES


def get_technology_by_name(name):
    """根据名称获取技术信息"""
    for tech in AI_TECHNOLOGIES:
        if tech["name"] == name or name in tech["aliases"]:
            return tech
    return None


def get_technology_names():
    """获取所有技术名称列表"""
    return [t["name"] for t in AI_TECHNOLOGIES]


def get_technologies_by_category(category):
    """按分类筛选技术"""
    return [t for t in AI_TECHNOLOGIES if t["category"] == category]


def match_technology(text):
    """
    从文本中匹配AI技术方向
    返回匹配到的技术名称列表
    """
    matched = []
    if not text:
        return matched
    
    for tech in AI_TECHNOLOGIES:
        # 检查技术名称
        if tech["name"] in text:
            matched.append(tech["name"])
            continue
        # 检查别名
        for alias in tech["aliases"]:
            if alias in text:
                matched.append(tech["name"])
                break
    
    return list(set(matched))
