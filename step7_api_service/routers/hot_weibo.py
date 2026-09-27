#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""热点微博接口"""
from typing import Optional
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from fastapi import APIRouter, Query, Depends, HTTPException
from .. import services
from ..auth import verify_api_key, resolve_dataset_type
from ..models import HotWeiboResponse

router = APIRouter(prefix="/api/hot-weibo", tags=["热点微博"])


@router.get("", response_model=HotWeiboResponse, summary="热点微博排行")
def hot_weibo(
    limit: int = Query(20, ge=1, le=100, description="返回条数"),
    keyword: Optional[str] = Query(None, description="关键词过滤，多个用逗号分隔，如 AI,大模型,飞书"),
    days: Optional[int] = Query(None, ge=1, le=30, description="只返回最近N天发布的数据"),
    fresh_hours: Optional[int] = Query(None, ge=1, le=72,
                                       description="只返回最近N小时新入库的数据（按首次入库时间，用于每日去重）"),
    date: Optional[str] = Query(None, pattern=r"^(?:\d{4}-\d{2}-\d{2}|yesterday|today)$",
                                description="只返回指定自然日（北京时间）发布的数据，如 2026-09-18，或 yesterday/today；优先于 days/fresh_hours"),
    dataset_type: Optional[str] = Query(None, pattern="^(ai_industry|brand_monitor|general_hotspot|archived_[a-z_]+)$",
                                         description="数据集过滤（未鉴权时生效；鉴权后由租户强制指定）"),
    require_ready: bool = Query(False, description="日报工作流专用：仅在目标自然日补采成功后返回数据"),
    tenant: Optional[dict] = Depends(verify_api_key),
):
    cache_version = None
    if require_ready:
        if date == 'yesterday':
            ready_date = (datetime.now(ZoneInfo('Asia/Shanghai')).date() - timedelta(days=1)).isoformat()
        elif date and len(date) == 10 and date[4] == '-' and date[7] == '-':
            ready_date = date
        else:
            raise HTTPException(status_code=400, detail='require_ready needs a completed natural day')
        project_root = Path(__file__).resolve().parents[2]
        marker = project_root / 'logs' / 'crawl_ready' / f'{ready_date}.json'
        if not marker.is_file():
            raise HTTPException(status_code=503, detail='daily crawl is not complete')
        cache_version = str(marker.stat().st_mtime_ns)
    effective_dataset = resolve_dataset_type(tenant, dataset_type)
    return services.get_hot_weibo(
        limit=limit,
        dataset_type=effective_dataset,
        keyword=keyword,
        days=days,
        fresh_hours=fresh_hours,
        date=date,
        cache_version=cache_version,
    )
