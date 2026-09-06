#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pydantic 响应模型
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


# ============================================================
# 1. 热点微博
# ============================================================

class HotWeiboItem(BaseModel):
    weibo_id: str
    user_id: str
    username: str
    content: str
    publish_time: Optional[datetime] = None
    like_count: int = 0
    comment_count: int = 0
    repost_count: int = 0
    hotspot_score: float = 0.0
    url: Optional[str] = None


class HotWeiboResponse(BaseModel):
    total: int
    data: List[HotWeiboItem]


# ============================================================
# 2. 关键词趋势
# ============================================================

class KeywordTrendItem(BaseModel):
    date: str
    post_count: int = 0
    comment_count: int = 0


class KeywordTrendResponse(BaseModel):
    keyword: str
    total_mentions: int = 0
    post_count: int = 0
    comment_count: int = 0
    days: int = 30
    daily_trend: List[KeywordTrendItem] = []


# ============================================================
# 3. 情感分析
# ============================================================

class NegativeViewpoint(BaseModel):
    word: str
    count: int


class SentimentResponse(BaseModel):
    total_analyzed: int = 0
    sample_size: int = 0
    positive_count: int = 0
    neutral_count: int = 0
    negative_count: int = 0
    positive_ratio: float = 0.0
    neutral_ratio: float = 0.0
    negative_ratio: float = 0.0
    top_negative_viewpoints: List[NegativeViewpoint] = []
    keyword: Optional[str] = None


# ============================================================
# 4. 用户影响力
# ============================================================

class InfluencerItem(BaseModel):
    user_id: str
    username: str
    followers_count: int = 0
    following_count: int = 0
    weibo_count: int = 0
    post_count: int = 0
    total_likes: int = 0
    total_comments: int = 0
    total_reposts: int = 0
    total_engagement: int = 0
    verified: Optional[int] = None
    description: Optional[str] = None


class InfluencersResponse(BaseModel):
    type: str = "followers"  # followers or engagement
    total: int
    data: List[InfluencerItem]


# ============================================================
# 5. 日报
# ============================================================

class DailyReportResponse(BaseModel):
    format: str = "markdown"
    content: str
    generated_at: datetime
