#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI产品声量API路由
- 产品热度排行
- 产品历史趋势
- 产品库列表
"""
from fastapi import APIRouter, Query
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime
import sys
import os

sys.path.insert(0, "/opt/Weibo-Analyst")
from step7_api_service.product_analyzer import (
    get_product_metrics, 
    get_product_trend, 
    analyze_and_save,
    get_latest_metrics_date
)
from step7_api_service.ai_products import AI_PRODUCTS

router = APIRouter(prefix="/api/products", tags=["AI产品声量"])


class ProductItem(BaseModel):
    rank: Optional[int] = None
    name: str
    company: Optional[str] = None
    country: Optional[str] = None
    category: Optional[str] = None
    mention_count: Optional[int] = None
    interaction_score: Optional[int] = None
    heat_score: Optional[float] = None
    trend_rate: Optional[float] = None
    trend_reason: Optional[str] = None
    sentiment: Optional[dict] = None
    main_sentiment: Optional[str] = None
    related_events: Optional[list] = None
    sample_posts: Optional[list] = None


class ProductsResponse(BaseModel):
    date: str
    count: int
    products: List[ProductItem]


class TrendItem(BaseModel):
    date: str
    mention_count: int
    interaction_score: int
    heat_score: float
    trend_rate: float


class TrendResponse(BaseModel):
    product: str
    days: int
    data: List[TrendItem]


@router.get("", response_model=ProductsResponse, summary="获取AI产品热度排行")
async def get_products_ranking(
    date: Optional[str] = Query(None, description="日期，格式YYYY-MM-DD，默认今天"),
    limit: int = Query(20, ge=1, le=50, description="返回数量"),
    country: Optional[str] = Query(None, description="按国家筛选：CN/US"),
    refresh: bool = Query(False, description="是否强制刷新")
):
    """获取指定日期的AI产品热度排行"""
    explicit_date = date
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")

    if refresh:
        analyze_and_save(date, force=True)

    products = get_product_metrics(date, limit=limit, country=country)
    # 默认未指定日期且当天无产品数据：回退到最近有数据的日期，保证打开即可见最新真实情报
    if not products and not explicit_date:
        latest = get_latest_metrics_date()
        if latest and latest != date:
            date = latest
            products = get_product_metrics(date, limit=limit, country=country)
    
    return {
        "date": date,
        "count": len(products),
        "products": products
    }


@router.get("/trend", response_model=TrendResponse, summary="获取产品历史趋势")
async def get_product_trend_api(
    product: str = Query(..., description="产品名称，如：DeepSeek、豆包、ChatGPT"),
    days: int = Query(30, ge=1, le=90, description="天数")
):
    """获取指定产品的历史趋势数据，用于前端折线图"""
    trend_data = get_product_trend(product, days=days)
    
    return {
        "product": product,
        "days": len(trend_data),
        "data": trend_data
    }


@router.get("/list", summary="获取AI产品库列表")
async def get_product_list():
    """获取所有监控的AI产品列表"""
    return {
        "total": len(AI_PRODUCTS),
        "domestic": len([p for p in AI_PRODUCTS if p["country"] == "CN"]),
        "international": len([p for p in AI_PRODUCTS if p["country"] == "US"]),
        "products": AI_PRODUCTS
    }


@router.post("/analyze", summary="触发产品声量分析")
async def trigger_analysis(
    date: Optional[str] = Query(None, description="日期，格式YYYY-MM-DD")
):
    """手动触发指定日期的产品声量分析"""
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    
    result = analyze_and_save(date, force=True)
    
    return {
        "status": "success",
        "date": date,
        "products_count": result.get("count", 0),
        "message": f"成功分析{result.get('count', 0)}个AI产品的声量数据"
    }
