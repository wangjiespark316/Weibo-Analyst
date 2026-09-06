#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FastAPI 微博数据服务入口
- 本地：127.0.0.1:8000，只读账号 weibo_api_reader
- 云端（Render）：0.0.0.0:$PORT，DATABASE_URL 连接 TiDB
- 5 个接口：热点/关键词/情感/影响力/日报

本地启动：
    .venv/bin/uvicorn step7_api_service.main:app --host 127.0.0.1 --port 8000 --reload

云端启动（Render 自动）：
    uvicorn step7_api_service.main:app --host 0.0.0.0 --port $PORT

Swagger 文档：/docs
"""
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import hot_weibo, keyword_trend, sentiment, influencers, daily_report
from .services import warmup_cache

app = FastAPI(
    title="微博数据分析 API",
    description="基于 MySQL 只读数据的微博分析服务（热点/关键词/情感/影响力/日报）",
    version="1.2.0",
)

# CORS：云端允许所有来源（Render 动态域名），本地限制 localhost
_is_cloud = bool(os.getenv('DATABASE_URL'))
if _is_cloud:
    _allow_origins = ["*"]
else:
    _allow_origins = [
        "http://127.0.0.1:3000", "http://localhost:3000",
        "http://127.0.0.1:5173", "http://localhost:5173",
        "http://127.0.0.1:8080", "http://localhost:8080",
    ]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)

# 注册路由
app.include_router(hot_weibo.router)
app.include_router(keyword_trend.router)
app.include_router(sentiment.router)
app.include_router(influencers.router)
app.include_router(daily_report.router)


@app.on_event("startup")
async def startup_event():
    """应用启动时预热缓存，避免首次请求超时"""
    warmup_cache()


@app.get("/", tags=["健康检查"])
def root():
    return {
        "service": "微博数据分析 API",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
        "endpoints": [
            "/api/hot-weibo",
            "/api/keyword-trend",
            "/api/sentiment",
            "/api/influencers",
            "/api/daily-report",
        ],
    }


@app.get("/health", tags=["健康检查"])
def health():
    return {"status": "ok"}
