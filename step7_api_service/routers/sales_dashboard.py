#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
销售驾驶舱API路由
"""
import sys
import os
import json
import logging
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from fastapi import APIRouter, HTTPException, Query
from typing import Optional
import pymysql
from urllib.parse import urlparse
from dotenv import load_dotenv

sys.path.insert(0, '/opt/Weibo-Analyst/step7_api_service')
from sales_analysis_agent import get_sales_analysis_agent

try:
    from daily_sales_agent import gen_tasks as _gen_sales_tasks
except Exception as _ie:
    _gen_sales_tasks = None
    logging.getLogger(__name__).warning(f'daily_sales_agent 导入失败，今日任务数将返回0: {_ie}')

load_dotenv('/opt/Weibo-Analyst/.env')
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

router = APIRouter(prefix='/api/sales-dashboard', tags=['销售驾驶舱'])


def get_db():
    # 统一复用 database.py 的进程级 TiDB 连接池，避免每请求新建公网 SSL 连接
    try:
        from ..database import get_connection as _gc
    except Exception:
        from database import get_connection as _gc
    return _gc()



@router.get('/overview')
async def get_overview():
    """获取销售驾驶舱总览数据"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        # 客户总数
        cursor.execute('SELECT COUNT(*) as total FROM customers')
        total_customers = cursor.fetchone()['total']
        
        # 本月新增客户
        cursor.execute('''SELECT COUNT(*) as new_count FROM customers 
            WHERE created_time >= DATE_FORMAT(NOW(), '%Y-%m-01')''')
        new_customers = cursor.fetchone()['new_count']
        
        # 今日跟进客户数
        cursor.execute('''SELECT COUNT(DISTINCT customer_id) as follow_count 
            FROM follow_records WHERE DATE(follow_time) = CURDATE()''')
        today_follow = cursor.fetchone()['follow_count']
        
        # 风险客户数（SQL兜底口径：未成交且超过14天未跟进；下方再用AI分析的权威口径覆盖）
        cursor.execute('''SELECT COUNT(*) as risk_count FROM customers
            WHERE sales_stage NOT IN ('closed', 'lost')
            AND (last_follow_time IS NULL
                 OR last_follow_time < DATE_SUB(NOW(), INTERVAL 14 DAY))''')
        risk_count = cursor.fetchone()['risk_count']

        # 在途商机总金额（所有未成交阶段；已成交/已丢单不计入在途）
        cursor.execute('''SELECT COALESCE(SUM(amount), 0) as total_amount
            FROM customers WHERE sales_stage NOT IN ('closed', 'lost')''')
        total_amount = cursor.fetchone()['total_amount']
        
        # 销售阶段分布
        cursor.execute('''SELECT sales_stage, COUNT(*) as count, COALESCE(SUM(amount), 0) as amount
            FROM customers GROUP BY sales_stage ORDER BY count DESC''')
        stage_distribution = cursor.fetchall()
        
        # 行业分布
        cursor.execute('''SELECT industry, COUNT(*) as count 
            FROM customers WHERE industry IS NOT NULL 
            GROUP BY industry ORDER BY count DESC LIMIT 10''')
        industry_distribution = cursor.fetchall()
        
        cursor.close()
        conn.close()

        # 今日任务数：来自 AI 每日销售任务（重点跟进客户 TOP5），而非空的提醒表
        today_tasks = 0
        try:
            if _gen_sales_tasks is not None:
                _tasks = _gen_sales_tasks()
                if isinstance(_tasks, dict):
                    today_tasks = len(_tasks.get('top5_tasks') or [])
        except Exception as _te:
            logger.warning(f'今日任务统计失败，返回0: {_te}')

        # 风险客户数：以AI销售分析口径为准（与"风险客户"页面 /risk 完全一致），失败则沿用上面的SQL兜底
        try:
            _an = get_sales_analysis_agent().analyze_all()
            if isinstance(_an, dict):
                _rc = (_an.get('summary') or {}).get('risk_count')
                if _rc is None:
                    _rc = len(_an.get('risk_customers') or [])
                risk_count = _rc
        except Exception as _re:
            logger.warning(f'AI风险客户统计失败，使用SQL兜底口径: {_re}')

        return {
            'status': 'success',
            'data': {
                'total_customers': total_customers,
                'new_customers': new_customers,
                'today_follow': today_follow,
                'risk_customers': risk_count,
                'total_pipeline_amount': float(total_amount),
                'today_tasks': today_tasks,
                'stage_distribution': stage_distribution,
                'industry_distribution': industry_distribution,
            }
        }
    except Exception as e:
        logger.error(f'获取总览数据失败: {e}')
        raise HTTPException(status_code=500, detail=str(e))


@router.get('/customers')
async def get_customers(
    industry: Optional[str] = None,
    stage: Optional[str] = None,
    owner: Optional[str] = None,
    level: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200)
):
    """获取客户列表"""
    try:
        conn = get_db()
        cursor = conn.cursor()
        
        sql = '''SELECT c.*, s.score as ai_score FROM customers c
            LEFT JOIN (SELECT customer_id, score, ROW_NUMBER() OVER
                (PARTITION BY customer_id ORDER BY created_time DESC) AS rn
                FROM customer_ai_scores) s ON s.customer_id = c.id AND s.rn = 1
            WHERE 1=1'''
        params = []
        
        if industry:
            sql += ' AND c.industry = %s'
            params.append(industry)
        if stage:
            sql += ' AND c.sales_stage = %s'
            params.append(stage)
        if owner:
            sql += ' AND c.owner = %s'
            params.append(owner)
        if level:
            sql += ' AND c.customer_level = %s'
            params.append(level)
        
        sql += ' ORDER BY c.customer_level, c.amount DESC LIMIT %s'
        params.append(limit)
        
        cursor.execute(sql, params)
        customers = cursor.fetchall()
        cursor.close()
        conn.close()
        
        return {
            'status': 'success',
            'count': len(customers),
            'customers': customers
        }
    except Exception as e:
        logger.error(f'获取客户列表失败: {e}')
        raise HTTPException(status_code=500, detail=str(e))


@router.get('/risk')
async def get_risk_customers():
    """获取风险客户列表"""
    try:
        agent = get_sales_analysis_agent()
        risk_customers = agent.analyze_risk_customers()
        
        return {
            'status': 'success',
            'count': len(risk_customers),
            'risk_customers': risk_customers
        }
    except Exception as e:
        logger.error(f'获取风险客户失败: {e}')
        raise HTTPException(status_code=500, detail=str(e))


@router.get('/opportunities')
async def get_opportunities():
    """获取成交机会列表"""
    try:
        agent = get_sales_analysis_agent()
        opportunities = agent.analyze_opportunities()
        
        return {
            'status': 'success',
            'count': len(opportunities),
            'opportunities': opportunities
        }
    except Exception as e:
        logger.error(f'获取成交机会失败: {e}')
        raise HTTPException(status_code=500, detail=str(e))


@router.get('/trends')
async def get_sales_trends(days: int = Query(7, ge=1, le=30)):
    """获取近7天销售趋势（趋势聚合查询与AI分析并行；AI部分复用analyze_all的并行结果与60秒缓存）"""
    def _query_trends():
        conn = get_db()
        try:
            cursor = conn.cursor()
            # 每日跟进趋势
            cursor.execute('''
                SELECT DATE(follow_time) as date, COUNT(*) as follow_count
                FROM follow_records
                WHERE follow_time >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
                GROUP BY DATE(follow_time)
                ORDER BY date ASC
            ''', (days,))
            follow_trends = cursor.fetchall()
            # 每日新增客户趋势
            cursor.execute('''
                SELECT DATE(created_time) as date, COUNT(*) as new_count
                FROM customers
                WHERE created_time >= DATE_SUB(CURDATE(), INTERVAL %s DAY)
                GROUP BY DATE(created_time)
                ORDER BY date ASC
            ''', (days,))
            new_customer_trends = cursor.fetchall()
            cursor.close()
            return follow_trends, new_customer_trends
        finally:
            conn.close()

    def _agent_data():
        # analyze_all 内部4项分析并行且带60秒缓存，避免此处再串行重复查库
        agent = get_sales_analysis_agent()
        all_res = agent.analyze_all()
        high_value = (all_res.get('high_value_customers') or [])[:5]
        suggestions = all_res.get('today_suggestions') or []
        return high_value, suggestions

    try:
        with ThreadPoolExecutor(max_workers=2) as ex:
            f_trend = ex.submit(_query_trends)
            f_agent = ex.submit(_agent_data)
            follow_trends, new_customer_trends = f_trend.result()
            high_value, suggestions = f_agent.result()

        return {
            'status': 'success',
            'data': {
                'follow_trends': follow_trends,
                'new_customer_trends': new_customer_trends,
                'high_value_customers': high_value,
                'today_suggestions': suggestions,
            }
        }
    except Exception as e:
        logger.error(f'获取销售趋势失败: {e}')
        raise HTTPException(status_code=500, detail=str(e))


@router.get('/analysis')
async def get_full_analysis():
    """获取完整销售分析"""
    try:
        agent = get_sales_analysis_agent()
        result = agent.analyze_all()
        return {'status': 'success', 'data': result}
    except Exception as e:
        logger.error(f'获取销售分析失败: {e}')
        raise HTTPException(status_code=500, detail=str(e))
