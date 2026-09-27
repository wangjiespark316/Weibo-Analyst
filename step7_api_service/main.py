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
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse

try:
    from dotenv import load_dotenv
    load_dotenv('/opt/Weibo-Analyst/.env')
except Exception:
    pass

from .routers import hot_weibo, keyword_trend, sentiment, influencers, daily_report, events, products, trends, reports, pipeline, sales, sales_workspace, feishu, sales_dashboard, sales_prediction, crm

app = FastAPI(
    title="微博数据分析 API",
    description="基于 MySQL 只读数据的微博分析服务（热点/关键词/情感/影响力/日报）",
    version="1.3.0",
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


# 应用层 API Key 鉴权（纵深防御）：公网由 Nginx 注入/校验 Key，uvicorn 仅监听 127.0.0.1，
# 此处再兜底一道，防止 8000 端口或本机其他通道被绕过。
_EXPECTED_API_KEY = os.getenv('WEIBO_API_KEY')


@app.middleware("http")
async def enforce_api_key(request: Request, call_next):
    """所有 /api/ 业务接口必须携带正确的 X-API-Key；/health、/ 等探针/名片放行。"""
    if request.method == "OPTIONS":  # CORS 预检放行
        return await call_next(request)
    if request.url.path.startswith("/api/"):
        if not _EXPECTED_API_KEY or request.headers.get("X-API-Key") != _EXPECTED_API_KEY:
            return JSONResponse(
                status_code=401,
                content={"detail": "unauthorized: missing or invalid API key"},
            )
    return await call_next(request)


# 注册路由
app.include_router(hot_weibo.router)
app.include_router(keyword_trend.router)
app.include_router(sentiment.router)
app.include_router(influencers.router)
app.include_router(daily_report.router)
app.include_router(events.router)
app.include_router(products.router)
app.include_router(trends.router)
app.include_router(reports.router)
app.include_router(pipeline.router)
app.include_router(sales.router)
app.include_router(sales_workspace.router)
app.include_router(feishu.router)
app.include_router(sales_dashboard.router)
app.include_router(sales_prediction.router)
app.include_router(crm.router)


# 注意：已移除 startup 预热，避免 Render 512MB 内存限制下启动 OOM
# 缓存按需生成，首次请求时计算并缓存


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



@app.get("/api/", tags=["API首页"])
def api_root():
    return {
        "service": "Weibo Analyst API",
        "version": "1.0.0",
        "status": "running",
        "auth": "Authorization: Bearer <API_KEY>",
        "endpoints": {
            "hot_weibo": "GET /api/hot-weibo?limit=10",
            "keyword_trend": "GET /api/keyword-trend?keyword=feishu&days=30",
            "sentiment": "GET /api/sentiment?sample_size=500",
            "influencers": "GET /api/influencers?type=followers&limit=10",
            "daily_report": "GET /api/daily-report",
            "events": "GET /api/events?date=2026-09-16",
            "products": "GET /api/products?date=2026-09-16",
            "product_trend": "GET /api/products/trend?product=DeepSeek&days=30",
            "trends": "GET /api/trends?date=2026-09-16",
            "trend_history": "GET /api/trends/history?technology=Agent&days=30",
            "reports": "GET /api/reports",
            "report_detail": "GET /api/reports/2026-09-16",
            "pipeline_status": "GET /api/reports/pipeline/status",
            "pipeline_run": "POST /api/reports/pipeline/run",
        },
    }


@app.get("/health", tags=["健康检查"])
def health():
    return {"status": "ok"}
