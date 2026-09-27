#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
销售预测API路由
提供客户成交预测、销售策略、漏斗分析、复盘等接口
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
import json
import sys

sys.path.insert(0, "/opt/Weibo-Analyst/step7_api_service")

from deal_prediction_agent import get_deal_prediction_agent
from sales_strategy_agent import get_sales_strategy_agent
from sales_funnel_analyzer import get_sales_funnel_analyzer
from sales_review_agent import get_sales_review_agent

router = APIRouter(prefix="/api/sales-prediction", tags=["销售预测"])


@router.get("/customers")
async def get_customer_predictions(refresh: bool = False):
    """获取所有客户成交预测列表。
    默认读取最近一次已持久化的预测（毫秒级）；
    库中无记录或 refresh=true 时才实时计算并入库。"""
    try:
        agent = get_deal_prediction_agent()
        results = []
        if not refresh:
            try:
                results = agent.get_latest_predictions()
            except Exception:
                results = []  # 读库异常不阻断，回退实时计算
        if not results:
            results = agent.predict_all()
        return {"status": "success", "data": results, "count": len(results)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/customer/{customer_id}")
async def get_customer_prediction_detail(customer_id: int, refresh: bool = False):
    """获取单个客户预测详情。默认读库，无记录或 refresh=true 时实时计算。"""
    try:
        agent = get_deal_prediction_agent()
        result = None
        if not refresh:
            try:
                result = agent.get_stored_prediction(customer_id)
            except Exception:
                result = None
        if not result:
            result = agent.predict_customer(customer_id)
        if not result:
            raise HTTPException(status_code=404, detail="客户不存在")
        return {"status": "success", "data": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/strategy/{customer_id}")
async def generate_sales_strategy(customer_id: int):
    """生成客户销售策略"""
    try:
        agent = get_sales_strategy_agent()
        result = agent.generate_strategy(customer_id)
        if not result:
            raise HTTPException(status_code=404, detail="客户不存在")
        return {"status": "success", "data": result}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/funnel")
async def get_sales_funnel():
    """获取销售漏斗分析"""
    try:
        analyzer = get_sales_funnel_analyzer()
        funnel = analyzer.analyze_funnel()
        total_customers = sum(f["customer_count"] for f in funnel)
        total_amount = sum(f["total_amount"] for f in funnel)
        return {
            "status": "success",
            "data": {
                "funnel": funnel,
                "total_customers": total_customers,
                "total_amount": total_amount
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/reviews")
async def get_sales_reviews(review_type: Optional[str] = "daily", limit: Optional[int] = 10):
    """获取销售复盘列表"""
    try:
        import pymysql
        from urllib.parse import urlparse
        from dotenv import load_dotenv
        import os
        load_dotenv("/opt/Weibo-Analyst/.env")
        url = urlparse(os.getenv("DATABASE_URL"))
        conn = pymysql.connect(
            host=url.hostname, port=url.port or 4000,
            user=url.username, password=url.password,
            database=url.path.lstrip("/"), ssl={"ssl_disabled": False},
            cursorclass=pymysql.cursors.DictCursor
        )
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM sales_reviews WHERE review_type = %s ORDER BY review_date DESC LIMIT %s",
            (review_type, limit)
        )
        reviews = cursor.fetchall()
        cursor.close()
        conn.close()
        return {"status": "success", "data": reviews, "count": len(reviews)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/reviews/generate")
async def generate_review(review_type: Optional[str] = "daily"):
    """手动生成销售复盘"""
    try:
        agent = get_sales_review_agent()
        if review_type == "daily":
            content = agent.generate_daily_review()
        else:
            content = agent.generate_daily_review()
        return {"status": "success", "data": {"content": content}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
