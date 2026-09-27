#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI行业日报API路由
- 日报列表
- 指定日期日报
- 手动生成日报
- 流水线状态
"""
from fastapi import APIRouter, Query, HTTPException
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime
import sys
import os

sys.path.insert(0, "/opt/Weibo-Analyst")
from step7_api_service.daily_report_generator import (
    get_report, 
    get_recent_reports, 
    generate_and_save_report
)
from step7_api_service.daily_ai_pipeline import run_daily_pipeline, get_pipeline_status

router = APIRouter(prefix="/api/reports", tags=["AI行业日报"])


class ReportItem(BaseModel):
    id: Optional[int] = None
    report_date: Optional[str] = None
    title: Optional[str] = None
    summary: Optional[str] = None
    created_time: Optional[str] = None


class ReportDetail(ReportItem):
    content: Optional[str] = None
    top_events: Optional[list] = None
    top_products: Optional[list] = None
    top_trends: Optional[list] = None


class ReportsResponse(BaseModel):
    count: int
    reports: List[ReportItem]


class PipelineStatus(BaseModel):
    date: str
    latest_status: str
    logs: list


class PipelineResult(BaseModel):
    date: str
    total_duration: int
    success_count: int
    failed_count: int
    results: dict


@router.get("", response_model=ReportsResponse, summary="获取日报列表")
async def get_reports_list(
    limit: int = Query(10, ge=1, le=50, description="返回数量")
):
    """获取最近的AI行业日报列表"""
    reports = get_recent_reports(limit=limit)
    
    return {
        "count": len(reports),
        "reports": reports
    }


@router.get("/{date}", response_model=ReportDetail, summary="获取指定日期日报")
async def get_report_by_date(date: str):
    """
    获取指定日期的AI行业日报
    
    - date: 日期，格式 YYYY-MM-DD
    """
    # 验证日期格式
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="日期格式错误，请使用 YYYY-MM-DD 格式")
    
    report = get_report(date)
    
    if not report:
        raise HTTPException(status_code=404, detail=f"未找到 {date} 的日报，请先生成")
    
    return report


@router.post("/generate", response_model=ReportDetail, summary="手动生成日报")
async def generate_report(
    date: Optional[str] = Query(None, description="日期，格式 YYYY-MM-DD，默认今天"),
    force: bool = Query(False, description="是否强制重新生成")
):
    """手动生成指定日期的AI行业日报"""
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="日期格式错误，请使用 YYYY-MM-DD 格式")
    
    content = generate_and_save_report(date, force=force)
    report = get_report(date)
    
    if not report:
        raise HTTPException(status_code=500, detail="日报生成失败")
    
    return report


@router.get("/pipeline/status", response_model=PipelineStatus, summary="获取流水线状态")
async def pipeline_status(
    date: Optional[str] = Query(None, description="日期，格式 YYYY-MM-DD，默认今天")
):
    """获取指定日期的流水线运行状态"""
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    
    status = get_pipeline_status(date)
    return status


@router.post("/pipeline/run", response_model=PipelineResult, summary="手动运行流水线")
async def run_pipeline(
    date: Optional[str] = Query(None, description="日期，格式 YYYY-MM-DD，默认今天"),
    skip: Optional[str] = Query(None, description="跳过的步骤，逗号分隔，如: collect,events")
):
    """
    手动运行AI行业情报流水线
    
    步骤顺序：collect → events → products → trends → report
    """
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
    
    skip_steps = skip.split(",") if skip else None
    
    result = run_daily_pipeline(date, skip_steps=skip_steps)
    
    return result
