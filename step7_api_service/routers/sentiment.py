#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""情感分析接口"""
from typing import Optional
from fastapi import APIRouter, Query, Depends
from .. import services
from ..auth import verify_api_key, resolve_dataset_type
from ..models import SentimentResponse

router = APIRouter(prefix="/api/sentiment", tags=["情感分析"])


@router.get("", response_model=SentimentResponse, summary="评论情感分析")
def sentiment(
    sample_size: int = Query(1000, ge=100, le=10000, description="抽样评论数"),
    dataset_type: Optional[str] = Query(None, pattern="^(ai_industry|brand_monitor|general_hotspot)$",
                                         description="数据集过滤（未鉴权时生效；鉴权后由租户强制指定）"),
    tenant: Optional[dict] = Depends(verify_api_key),
):
    effective_dataset = resolve_dataset_type(tenant, dataset_type)
    return services.get_sentiment(sample_size=sample_size, dataset_type=effective_dataset)
