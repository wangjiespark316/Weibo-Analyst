#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""关键词趋势接口"""
from typing import Optional
from fastapi import APIRouter, Query, Depends
from .. import services
from ..auth import verify_api_key, resolve_dataset_type
from ..models import KeywordTrendResponse

router = APIRouter(prefix="/api/keyword-trend", tags=["关键词趋势"])


@router.get("", response_model=KeywordTrendResponse, summary="关键词提及趋势")
def keyword_trend(
    keyword: str = Query(..., min_length=1, max_length=64, description="关键词"),
    days: int = Query(30, ge=1, le=365, description="统计天数"),
    dataset_type: Optional[str] = Query(None, pattern="^(ai_industry|brand_monitor|general_hotspot)$",
                                         description="数据集过滤（未鉴权时生效；鉴权后由租户强制指定）"),
    tenant: Optional[dict] = Depends(verify_api_key),
):
    effective_dataset = resolve_dataset_type(tenant, dataset_type)
    return services.get_keyword_trend(keyword=keyword, days=days, dataset_type=effective_dataset)
