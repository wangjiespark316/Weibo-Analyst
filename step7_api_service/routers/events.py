#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI热点事件API路由（增强版）
- 支持事件可信度评分
- 支持企业应用机会分析
- 支持分类筛选和可信度筛选
- 支持综合排名排序
"""
from fastapi import APIRouter, Query, HTTPException
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime
import sys
import os
import json
import re

sys.path.insert(0, "/opt/Weibo-Analyst")
from step7_api_service.event_analyzer import get_events, analyze_and_save, get_latest_event_date

router = APIRouter(prefix="/api/events", tags=["AI热点事件"])


_LIST_FIELDS = ("companies", "technologies", "related_posts", "related_keywords")


def _as_list(value):
    """将逗号分隔字符串 / JSON 数组字符串 / 空值统一归一化为 list，避免响应模型校验返回 500。"""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        except (ValueError, TypeError):
            pass
        # 兼容库中历史数据的中英文逗号/顿号/分号分隔
        return [item.strip() for item in re.split(r'[,，、;；\n]+', text) if item.strip()]
    return []


class EventItem(BaseModel):
    id: Optional[int] = None
    event_date: Optional[str] = None
    title: str
    summary: Optional[str] = None
    category: Optional[str] = None
    companies: Optional[list] = None
    technologies: Optional[list] = None
    heat_score: Optional[int] = None
    event_confidence: Optional[int] = None
    event_rank_score: Optional[float] = None
    sentiment: Optional[str] = None
    related_posts: Optional[list] = None
    related_keywords: Optional[list] = None
    impact_analysis: Optional[str] = None
    business_opportunity: Optional[str] = None
    source: Optional[str] = None
    created_time: Optional[str] = None


class EventsResponse(BaseModel):
    date: str
    count: int
    events: List[EventItem]


@router.get("", response_model=EventsResponse, summary="获取AI热点事件列表")
async def get_events_list(
    date: Optional[str] = Query(None, description="日期，格式YYYY-MM-DD，默认今天"),
    limit: int = Query(10, ge=1, le=50, description="返回数量"),
    refresh: bool = Query(False, description="是否强制刷新（重新调用LLM分析）"),
    category: Optional[str] = Query(None, description="按分类筛选：model_release/product_launch/company_news/financing/policy/technology_breakthrough/application_case/industry_trend"),
    min_confidence: int = Query(0, ge=0, le=100, description="最低可信度筛选（0-100）")
):
    """获取指定日期的AI热点事件，支持分类和可信度筛选"""
    explicit_date = date
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")

    # 如果要求刷新，重新分析
    if refresh:
        events = analyze_and_save(date, force=True)
    else:
        events = get_events(date, limit=50)  # 获取更多以便筛选
        # 默认未指定日期且当天无事件：回退到最近有数据的日期，保证打开即可见最新真实情报
        if not events and not explicit_date:
            latest = get_latest_event_date()
            if latest and latest != date:
                date = latest
                events = get_events(date, limit=50)
    
    # 按分类筛选
    if category:
        events = [e for e in events if e.get("category") == category]
    
    # 按最低可信度筛选
    if min_confidence > 0:
        events = [e for e in events if (e.get("event_confidence") or 0) >= min_confidence]
    
    # 限制返回数量
    events = events[:limit]

    # 列表字段归一化（库中 companies/technologies/related_keywords 可能为逗号分隔字符串或空串）
    for e in events:
        for field in _LIST_FIELDS:
            e[field] = _as_list(e.get(field))

    return {
        "date": date,
        "count": len(events),
        "events": events
    }


@router.post("/analyze", summary="触发事件分析")
async def trigger_analysis(
    date: Optional[str] = Query(None, description="日期，格式YYYY-MM-DD")
):
    """手动触发指定日期的事件分析"""
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    
    events = analyze_and_save(date, force=True)
    
    return {
        "status": "success",
        "date": date,
        "events_count": len(events),
        "message": f"成功分析{len(events)}个热点事件"
    }


@router.get("/categories", summary="获取事件分类列表")
async def get_categories():
    """获取支持的事件分类枚举"""
    return {
        "categories": [
            {"key": "model_release", "name": "模型发布"},
            {"key": "product_launch", "name": "产品发布"},
            {"key": "company_news", "name": "公司动态"},
            {"key": "financing", "name": "融资投资"},
            {"key": "policy", "name": "政策监管"},
            {"key": "technology_breakthrough", "name": "技术突破"},
            {"key": "application_case", "name": "企业应用案例"},
            {"key": "industry_trend", "name": "行业趋势"}
        ]
    }


# === v1.2 AnyCross 免编排友好端点（只读、限量，增量追加，不改既有接口） ===
_ANYCROSS_CATEGORY_CN = {
    "model_release": "模型发布",
    "product_launch": "产品发布",
    "company_news": "公司动态",
    "financing": "融资投资",
    "policy": "政策监管",
    "technology_breakthrough": "技术突破",
    "application_case": "企业应用案例",
    "industry_trend": "行业趋势",
}


def _collect_events_for_anycross(limit: int = 5):
    """取最新可用日期的事件并完成列表字段归一化，供 array/bitable 两个导出端点复用。"""
    from datetime import datetime as _dt
    date = _dt.now().strftime("%Y-%m-%d")
    evs = get_events(date, limit=50)
    if not evs:
        latest = get_latest_event_date()
        if latest and latest != date:
            date, evs = latest, get_events(latest, limit=50)
    evs = (evs or [])[:limit]
    for e in evs:
        for _f in _LIST_FIELDS:
            e[_f] = _as_list(e.get(_f))
    return date, evs


@router.get("/array", summary="顶层数组输出（供集成平台循环遍历，免JSON解析节点）")
async def events_as_array(
    limit: int = Query(5, ge=1, le=20, description="返回数量")
):
    _, _evs = _collect_events_for_anycross(limit)
    return _evs


@router.get("/bitable", summary="飞书多维表格『新增多条』请求体（records 已按中文列映射）")
async def events_as_bitable(
    limit: int = Query(5, ge=1, le=20, description="返回数量")
):
    _date, _evs = _collect_events_for_anycross(limit)
    records = []
    for e in _evs:
        companies = e.get("companies") or []
        techs = e.get("technologies") or []
        cat_raw = e.get("category") or ""
        cat = _ANYCROSS_CATEGORY_CN.get(cat_raw, cat_raw or "未分类")
        records.append({
            "fields": {
                "事件标题": e.get("title") or "",
                "事件日期": e.get("event_date") or _date,
                "分类": cat,
                "热度": int(e.get("heat_score") or 0),
                "可信度": int(e.get("event_confidence") or 0),
                "涉及公司": "、".join(companies),
                "技术方向": "、".join(techs),
                "事件摘要": e.get("summary") or "",
                "行业影响": e.get("impact_analysis") or "",
                "企业机会": e.get("business_opportunity") or "",
                "情感倾向": e.get("sentiment") or "",
                "来源": e.get("source") or "weibo",
            }
        })
    return {"records": records}


# === v1.2 AnyCross 循环写入用：中文列扁平行数组（增量追加，不改既有接口） ===
@router.get("/rows", summary="中文列扁平行数组（供集成平台『列表循环+新增单条记录』逐列直绑，免表达式）")
async def events_as_rows(
    limit: int = Query(5, ge=1, le=20, description="返回数量")
):
    _date, _evs = _collect_events_for_anycross(limit)
    rows = []
    for e in _evs:
        companies = e.get("companies") or []
        techs = e.get("technologies") or []
        cat_raw = e.get("category") or ""
        cat = _ANYCROSS_CATEGORY_CN.get(cat_raw, cat_raw or "未分类")
        rows.append({
            "事件标题": e.get("title") or "",
            "事件日期": e.get("event_date") or _date,
            "分类": cat,
            "热度": int(e.get("heat_score") or 0),
            "可信度": int(e.get("event_confidence") or 0),
            "涉及公司": "、".join(companies),
            "技术方向": "、".join(techs),
            "事件摘要": e.get("summary") or "",
            "行业影响": e.get("impact_analysis") or "",
            "企业机会": e.get("business_opportunity") or "",
            "情感倾向": e.get("sentiment") or "",
            "来源": e.get("source") or "weibo",
        })
    return rows
