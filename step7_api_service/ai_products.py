#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI产品库配置
维护需要监控的AI产品列表，用于产品声量分析
"""

# AI产品列表
AI_PRODUCTS = [
    # 国内产品
    {
        "name": "豆包",
        "company": "字节跳动",
        "country": "CN",
        "category": "通用大模型",
        "aliases": ["豆包AI", "ByteDance AI", "Doubao", "豆包大模型"]
    },
    {
        "name": "DeepSeek",
        "company": "深度求索",
        "country": "CN",
        "category": "通用大模型",
        "aliases": ["深度求索", "DeepSeek AI", "DeepSeek-V3", "DeepSeek-R1"]
    },
    {
        "name": "通义千问",
        "company": "阿里巴巴",
        "country": "CN",
        "category": "通用大模型",
        "aliases": ["通义", "Qwen", "千问", "通义大模型", "Qwen2"]
    },
    {
        "name": "Kimi",
        "company": "月之暗面",
        "country": "CN",
        "category": "通用大模型",
        "aliases": ["Kimi智能助手", "Moonshot", "月之暗面", "Kimi AI"]
    },
    {
        "name": "文心一言",
        "company": "百度",
        "country": "CN",
        "category": "通用大模型",
        "aliases": ["文心", "ERNIE", "百度文心", "文心大模型"]
    },
    {
        "name": "腾讯元宝",
        "company": "腾讯",
        "country": "CN",
        "category": "通用大模型",
        "aliases": ["元宝", "腾讯混元", "混元大模型", "Tencent Yuanbao"]
    },
    {
        "name": "智谱清言",
        "company": "智谱AI",
        "country": "CN",
        "category": "通用大模型",
        "aliases": ["智谱", "GLM", "ChatGLM", "智谱大模型", "Zhipu"]
    },
    # 国外产品
    {
        "name": "ChatGPT",
        "company": "OpenAI",
        "country": "US",
        "category": "通用大模型",
        "aliases": ["GPT", "OpenAI", "GPT-4", "GPT-4o", "ChatGPT-4"]
    },
    {
        "name": "Claude",
        "company": "Anthropic",
        "country": "US",
        "category": "通用大模型",
        "aliases": ["Claude AI", "Anthropic", "Claude 3", "Claude Sonnet", "Claude Opus"]
    },
    {
        "name": "Gemini",
        "company": "Google",
        "country": "US",
        "category": "通用大模型",
        "aliases": ["Google Gemini", "Gemini AI", "Bard", "Gemini Ultra", "Gemini Pro"]
    },
    {
        "name": "Copilot",
        "company": "Microsoft",
        "country": "US",
        "category": "AI助手",
        "aliases": ["GitHub Copilot", "Microsoft Copilot", "Copilot AI", "Windows Copilot"]
    },
    {
        "name": "Perplexity",
        "company": "Perplexity AI",
        "country": "US",
        "category": "AI搜索",
        "aliases": ["Perplexity AI", "Perplexity搜索", "AI搜索"]
    }
]


def get_all_products():
    """获取所有AI产品"""
    return AI_PRODUCTS


def get_product_by_name(name):
    """根据名称获取产品信息"""
    for product in AI_PRODUCTS:
        if product["name"] == name or name in product["aliases"]:
            return product
    return None


def get_product_names():
    """获取所有产品名称列表"""
    return [p["name"] for p in AI_PRODUCTS]


def get_products_by_country(country):
    """按国家筛选产品"""
    return [p for p in AI_PRODUCTS if p["country"] == country]


def match_product(text):
    """
    从文本中匹配AI产品
    返回匹配到的产品名称列表
    """
    matched = []
    if not text:
        return matched
    
    for product in AI_PRODUCTS:
        # 检查产品名称
        if product["name"] in text:
            matched.append(product["name"])
            continue
        # 检查别名
        for alias in product["aliases"]:
            if alias in text:
                matched.append(product["name"])
                break
    
    return list(set(matched))
