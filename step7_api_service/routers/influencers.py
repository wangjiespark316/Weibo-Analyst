#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用户影响力接口"""
from typing import Optional
from fastapi import APIRouter, Query, Depends
from .. import services
from ..auth import verify_api_key, resolve_dataset_type
from ..models import InfluencersResponse

router = APIRouter(prefix="/api/influencers", tags=["用户影响力"])


@router.get("", response_model=InfluencersResponse, summary="高粉丝/高互动用户排行")
def influencers(
    type: str = Query("followers", pattern="^(followers|engagement)$",
                      description="排序方式：followers 粉丝数 / engagement 互动量"),
    limit: int = Query(20, ge=1, le=100, description="返回条数"),
    dataset_type: Optional[str] = Query(None, pattern="^(ai_industry|brand_monitor|general_hotspot)$",
                                         description="数据集过滤（未鉴权时生效；鉴权后由租户强制指定）"),
    tenant: Optional[dict] = Depends(verify_api_key),
):
    effective_dataset = resolve_dataset_type(tenant, dataset_type)
    return services.get_influencers(sort_type=type, limit=limit, dataset_type=effective_dataset)
