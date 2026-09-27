#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
流水线管理API路由
- 查看状态
- 手动执行
- 查看日志
- 健康检查
- 日报质量检查
"""
from fastapi import APIRouter, Query, HTTPException
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime
import sys
import os

sys.path.insert(0, "/opt/Weibo-Analyst")
from step7_api_service.daily_ai_pipeline import run_daily_pipeline, get_pipeline_status, default_analysis_date
from step7_api_service.pipeline_monitor import check_pipeline_health
from step7_api_service.report_quality_checker import check_report_quality

router = APIRouter(prefix="/api/pipeline", tags=["流水线管理"])


class PipelineRunRequest(BaseModel):
    date: Optional[str] = None
    skip_steps: Optional[List[str]] = None


class PipelineStatusResponse(BaseModel):
    date: str
    latest_status: str
    lock: Optional[dict] = None
    logs: list


class HealthCheckResponse(BaseModel):
    date: str
    check_time: str
    overall_status: str
    checks: dict
    summary: dict


class QualityCheckResponse(BaseModel):
    date: str
    score: int
    status: str
    issues: list
    suggestion: str


@router.get("/status", response_model=PipelineStatusResponse, summary="获取流水线状态")
async def pipeline_status(
    date: Optional[str] = Query(None, description="日期，默认今天")
):
    """获取指定日期的流水线运行状态"""
    if not date:
        date = default_analysis_date()
    
    status = get_pipeline_status(date)
    return status


@router.post("/run", summary="手动执行流水线")
async def run_pipeline(request: PipelineRunRequest):
    """
    手动执行AI情报流水线
    
    步骤顺序：collect → events → products → trends → report
    """
    date_str = request.date or default_analysis_date()
    skip_steps = request.skip_steps or []
    
    result = run_daily_pipeline(date_str, skip_steps=skip_steps)
    
    return {
        "date": result["date"],
        "status": result["status"],
        "total_duration": result["total_duration"],
        "success_count": result["success_count"],
        "failed_count": result["failed_count"],
        "results": result["results"]
    }


@router.get("/logs", summary="获取流水线日志")
async def pipeline_logs(
    date: Optional[str] = Query(None, description="日期"),
    step: Optional[str] = Query(None, description="步骤名称"),
    status: Optional[str] = Query(None, description="状态: success/failed/running"),
    limit: int = Query(50, ge=1, le=200, description="返回数量")
):
    """获取流水线运行日志"""
    from step7_api_service.daily_ai_pipeline import get_db_connection
    import pymysql.cursors
    
    if not date:
        date = default_analysis_date()
    
    conn = get_db_connection()
    cursor = conn.cursor(pymysql.cursors.DictCursor)
    
    query = "SELECT * FROM pipeline_logs WHERE run_date = %s"
    params = [date]
    
    if step:
        query += " AND step = %s"
        params.append(step)
    if status:
        query += " AND status = %s"
        params.append(status)
    
    query += " ORDER BY created_time DESC LIMIT %s"
    params.append(limit)
    
    cursor.execute(query, params)
    logs = cursor.fetchall()
    conn.close()
    
    # 转换时间格式
    for log in logs:
        for key in ["start_time", "end_time", "created_time"]:
            if log.get(key) and hasattr(log[key], "isoformat"):
                log[key] = log[key].isoformat()
    
    return {
        "date": date,
        "count": len(logs),
        "logs": logs
    }


@router.get("/health", response_model=HealthCheckResponse, summary="健康检查")
async def health_check(
    date: Optional[str] = Query(None, description="日期，默认今天")
):
    """检查流水线和数据健康状态"""
    if not date:
        date = default_analysis_date()
    
    health = check_pipeline_health(date)
    return health


@router.get("/report-quality", response_model=QualityCheckResponse, summary="日报质量检查")
async def report_quality(
    date: Optional[str] = Query(None, description="日期，默认今天")
):
    """检查指定日期日报的质量"""
    if not date:
        date = default_analysis_date()
    
    result = check_report_quality(date)
    
    if result.get("status") == "not_found":
        raise HTTPException(status_code=404, detail=f"未找到 {date} 的日报")
    
    return {
        "date": result["date"],
        "score": result["score"],
        "status": result["status"],
        "issues": result["issues"],
        "suggestion": result["suggestion"]
    }
