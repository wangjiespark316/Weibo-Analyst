#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
飞书销售助手API路由
"""
import sys
import os
import json
import logging
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional

sys.path.insert(0, "/opt/Weibo-Analyst/step7_api_service")

from feishu_notification import get_feishu_notification
from daily_sales_push import get_daily_sales_push
from follow_reminder_agent import get_follow_reminder_agent
from daily_sales_review import get_daily_sales_review

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/feishu", tags=["飞书销售助手"])


class SendReminderRequest(BaseModel):
    reminder_id: Optional[int] = None
    customer_id: Optional[int] = None


@router.get("/test")
async def test_feishu_connection():
    """测试飞书连接"""
    try:
        notifier = get_feishu_notification()
        result = notifier.test_connection()
        return result
    except Exception as e:
        logger.error(f"测试飞书连接失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/send-daily")
async def send_daily_report():
    """推送销售日报"""
    try:
        pusher = get_daily_sales_push()
        result = pusher.push_daily_report()
        
        if result.get("status") == "success":
            return {"status": "success", "message": "销售日报推送成功", "message_id": result.get("message_id")}
        elif result.get("status") == "skipped":
            return {"status": "skipped", "message": result.get("reason", "飞书未配置")}
        else:
            raise HTTPException(status_code=500, detail=result.get("error", "推送失败"))
    except Exception as e:
        logger.error(f"推送销售日报失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/send-review")
async def send_sales_review():
    """推送销售复盘报告"""
    try:
        review = get_daily_sales_review()
        result = review.push_review()
        
        if result.get("status") == "success":
            return {"status": "success", "message": "销售复盘报告推送成功", "message_id": result.get("message_id")}
        else:
            raise HTTPException(status_code=500, detail=result.get("error", "推送失败"))
    except Exception as e:
        logger.error(f"推送销售复盘报告失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/reminders")
async def get_reminders(
    status: Optional[str] = Query("pending", description="提醒状态: pending/sent/read"),
    limit: int = Query(20, ge=1, le=100)
):
    """获取客户提醒列表"""
    try:
        agent = get_follow_reminder_agent()
        reminders = agent.get_pending_reminders(limit=limit)
        
        return {
            "status": "success",
            "count": len(reminders),
            "reminders": reminders
        }
    except Exception as e:
        logger.error(f"获取提醒列表失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generate-reminders")
async def generate_reminders():
    """生成客户跟进提醒"""
    try:
        agent = get_follow_reminder_agent()
        reminders = agent.generate_reminders()
        
        return {
            "status": "success",
            "count": len(reminders),
            "reminders": reminders
        }
    except Exception as e:
        logger.error(f"生成提醒失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/send-reminders")
async def send_reminders():
    """推送所有待处理提醒"""
    try:
        agent = get_follow_reminder_agent()
        reminders = agent.generate_reminders()
        
        if not reminders:
            return {"status": "skipped", "message": "暂无需要提醒的客户", "count": 0}
        
        result = agent.push_reminders(reminders)
        
        if result.get("status") == "success":
            return {"status": "success", "message": "提醒推送成功", "count": result.get("count"), "message_id": result.get("message_id")}
        else:
            raise HTTPException(status_code=500, detail=result.get("error", "推送失败"))
    except Exception as e:
        logger.error(f"推送提醒失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/sync-customers")
async def sync_customers():
    """同步客户到飞书多维表格（预留接口）"""
    try:
        # 预留接口，后续实现飞书多维表格同步
        return {
            "status": "success",
            "message": "客户同步功能开发中",
            "note": "飞书多维表格同步功能将在后续版本中实现"
        }
    except Exception as e:
        logger.error(f"同步客户失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
async def get_feishu_status():
    """获取飞书集成状态"""
    try:
        notifier = get_feishu_notification()
        
        return {
            "status": "success",
            "enabled": notifier.enabled,
            "api_enabled": notifier.api_enabled,
            "webhook_enabled": notifier.webhook_enabled,
            "app_id": notifier.app_id,
            "chat_id": notifier.chat_id,
            "features": {
                "daily_push": "已启用",
                "reminders": "已启用",
                "sales_review": "已启用",
                "bitable_sync": "开发中",
                "message_analyzer": "开发中"
            }
        }
    except Exception as e:
        logger.error(f"获取飞书状态失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))
