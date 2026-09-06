#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""日报生成接口"""
from typing import Optional
from fastapi import APIRouter, Query, Depends
from .. import services
from ..auth import verify_api_key, resolve_dataset_type
from ..models import DailyReportResponse

router = APIRouter(prefix="/api/daily-report", tags=["日报"])


@router.get("", response_model=DailyReportResponse, summary="生成完整 Markdown 日报")
def daily_report(
    dataset_type: Optional[str] = Query(None, pattern="^(ai_industry|brand_monitor|general_hotspot)$",
                                         description="数据集过滤（未鉴权时生效；鉴权后由租户强制指定）"),
    tenant: Optional[dict] = Depends(verify_api_key),
):
    effective_dataset = resolve_dataset_type(tenant, dataset_type)
    return services.get_daily_report(dataset_type=effective_dataset)
