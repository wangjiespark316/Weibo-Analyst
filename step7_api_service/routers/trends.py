#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI技术趋势API路由
- 技术趋势排行
- 技术历史趋势
- 技术标签库
"""
from fastapi import APIRouter, Query
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime
import sys
import os

sys.path.insert(0, "/opt/Weibo-Analyst")
from step7_api_service.trend_analyzer import get_trends, get_trend_history, analyze_and_save
from step7_api_service.ai_technologies import AI_TECHNOLOGIES

router = APIRouter(prefix="/api/trends", tags=["AI技术趋势"])


class TrendItem(BaseModel):
    rank: Optional[int] = None
    name: str
    category: Optional[str] = None
    mention_count_7days: Optional[int] = None
    mention_count_30days: Optional[int] = None
    interaction_score: Optional[int] = None
    growth_rate: Optional[float] = None
    heat_score: Optional[float] = None
    trend_level: Optional[str] = None
    summary: Optional[str] = None
    business_opportunity: Optional[str] = None
    related_events: Optional[list] = None
    related_products: Optional[list] = None
    sample_posts: Optional[list] = None


class TrendsResponse(BaseModel):
    date: str
    count: int
    trends: List[TrendItem]


class TrendHistoryItem(BaseModel):
    date: str
    mention_count: int
    growth_rate: float
    heat_score: float
    trend_level: str


class TrendHistoryResponse(BaseModel):
    technology: str
    days: int
    data: List[TrendHistoryItem]


@router.get("", response_model=TrendsResponse, summary="获取AI技术趋势排行")
async def get_trends_ranking(
    date: Optional[str] = Query(None, description="日期，格式YYYY-MM-DD，默认今天"),
    limit: int = Query(20, ge=1, le=50, description="返回数量"),
    level: Optional[str] = Query(None, description="按趋势等级筛选：rising/stable/declining/emerging"),
    refresh: bool = Query(False, description="是否强制刷新")
):
    """获取指定日期的AI技术趋势排行"""
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    
    if refresh:
        analyze_and_save(date, force=True)
    
    trends = get_trends(date, limit=limit, level=level)
    
    return {
        "date": date,
        "count": len(trends),
        "trends": trends
    }


@router.get("/history", response_model=TrendHistoryResponse, summary="获取技术历史趋势")
async def get_technology_history(
    technology: str = Query(..., description="技术名称，如：Agent、大模型、AI办公"),
    days: int = Query(30, ge=1, le=90, description="天数")
):
    """获取指定技术的历史趋势数据，用于前端折线图"""
    trend_data = get_trend_history(technology, days=days)
    
    return {
        "technology": technology,
        "days": len(trend_data),
        "data": trend_data
    }


@router.get("/technologies", summary="获取AI技术标签库")
async def get_technology_list():
    """获取所有监控的AI技术方向列表"""
    return {
        "total": len(AI_TECHNOLOGIES),
        "technologies": AI_TECHNOLOGIES
    }


@router.post("/analyze", summary="触发技术趋势分析")
async def trigger_analysis(
    date: Optional[str] = Query(None, description="日期，格式YYYY-MM-DD")
):
    """手动触发指定日期的技术趋势分析"""
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    
    result = analyze_and_save(date, force=True)
    
    return {
        "status": "success",
        "date": date,
        "trends_count": result.get("count", 0),
        "message": f"成功分析{result.get('count', 0)}个AI技术方向的趋势数据"
    }
