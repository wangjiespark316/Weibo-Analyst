#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI销售分析Agent
功能：
- 分析高价值客户
- 识别风险客户
- 发现长期未跟进客户
- 识别成交机会
- 生成今日建议
"""
import os
import json
import time
import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import List, Dict
import pymysql
from urllib.parse import urlparse
from dotenv import load_dotenv

# 完整分析结果的进程内缓存TTL（秒）。销售驾驶舱数据允许短延迟，避免每次打开页面都串行查库
ANALYSIS_CACHE_TTL = 60

load_dotenv('/opt/Weibo-Analyst/.env')
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SalesAnalysisAgent:
    def __init__(self):
        self.db_url = os.getenv('DATABASE_URL')
        self._all_cache = None
        self._all_cache_ts = 0.0

    def _get_conn(self):
        parsed = urlparse(self.db_url)
        return pymysql.connect(
            host=parsed.hostname, port=parsed.port or 4000,
            user=parsed.username, password=parsed.password,
            database=parsed.path.lstrip('/'), ssl={'ssl_disabled': False},
            cursorclass=pymysql.cursors.DictCursor
        )

    def _days_since(self, dt):
        if not dt:
            return None
        if isinstance(dt, str):
            dt = datetime.strptime(dt, '%Y-%m-%d %H:%M:%S')
        return (datetime.now() - dt).days

    def analyze_high_value_customers(self, limit=10) -> List[Dict]:
        """分析高价值客户：A级 + 金额>50万"""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT c.*, s.score as ai_score
            FROM customers c
            LEFT JOIN customer_ai_scores s ON s.customer_id = c.id
            WHERE c.customer_level = 'A' OR c.amount >= 500000
            ORDER BY c.amount DESC, c.customer_level
            LIMIT %s
        ''', (limit,))
        customers = cursor.fetchall()
        cursor.close()
        conn.close()
        
        result = []
        for c in customers:
            days = self._days_since(c.get('last_follow_time'))
            result.append({
                'id': c['id'],
                'name': c['company_name'],
                'industry': c.get('industry', ''),
                'level': c.get('customer_level', ''),
                'stage': c.get('sales_stage', ''),
                'amount': float(c.get('amount', 0) or 0),
                'ai_score': c.get('ai_score'),
                'days_since_follow': days,
                'next_action': c.get('next_action', ''),
            })
        return result

    def analyze_risk_customers(self) -> List[Dict]:
        """分析风险客户：阶段14天无变化"""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM customers
            WHERE sales_stage NOT IN ('closed', 'lost')
            AND (stage_changed_time IS NULL 
                 OR stage_changed_time < DATE_SUB(NOW(), INTERVAL 14 DAY))
            ORDER BY customer_level, amount DESC
        ''')
        customers = cursor.fetchall()
        cursor.close()
        conn.close()
        
        result = []
        for c in customers:
            stage_days = self._days_since(c.get('stage_changed_time'))
            stage = c.get('sales_stage', '')
            if stage_days is None:
                risk_reason = f'销售阶段[{stage}]暂无阶段更新记录'
            else:
                risk_reason = f'销售阶段[{stage}]已{stage_days}天无变化'
            result.append({
                'id': c['id'],
                'name': c['company_name'],
                'industry': c.get('industry', ''),
                'stage': stage,
                'amount': float(c.get('amount', 0) or 0),
                'days_in_stage': stage_days,
                'risk_reason': risk_reason,
                'suggestion': '建议主动联系客户，了解项目进展，推动阶段前进',
            })
        return result

    def analyze_stale_customers(self) -> List[Dict]:
        """分析长期未跟进客户：A级>3天，普通>7天"""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM customers
            WHERE sales_stage NOT IN ('closed', 'lost')
            ORDER BY customer_level, last_follow_time ASC
        ''')
        customers = cursor.fetchall()
        cursor.close()
        conn.close()
        
        result = []
        for c in customers:
            days = self._days_since(c.get('last_follow_time'))
            # 无跟进日期时按长期未跟进处理（仅用于阈值判定，不展示具体天数）
            eff_days = days if days is not None else 9999
            is_a = c.get('customer_level') == 'A'

            if (is_a and eff_days > 3) or (not is_a and eff_days > 7):
                priority = 'high' if (is_a and eff_days > 3) else 'medium'
                level = c.get('customer_level', '')
                if days is None:
                    suggestion = f'{level}级客户暂无跟进记录，建议立即联系'
                else:
                    suggestion = f'{level}级客户已{days}天未跟进，建议立即联系'
                result.append({
                    'id': c['id'],
                    'name': c['company_name'],
                    'industry': c.get('industry', ''),
                    'level': level,
                    'stage': c.get('sales_stage', ''),
                    'days_since_follow': days,
                    'priority': priority,
                    'suggestion': suggestion,
                })
        return result

    def analyze_opportunities(self) -> List[Dict]:
        """分析成交机会：方案沟通/谈判阶段"""
        conn = self._get_conn()
        cursor = conn.cursor()
        cursor.execute('''
            SELECT c.*, s.score as ai_score
            FROM customers c
            LEFT JOIN customer_ai_scores s ON s.customer_id = c.id
            WHERE c.sales_stage IN ('solution', 'negotiation', 'requirement')
            ORDER BY c.amount DESC
        ''')
        customers = cursor.fetchall()
        cursor.close()
        conn.close()
        
        result = []
        for c in customers:
            stage_map = {
                'requirement': '需求确认',
                'solution': '方案沟通',
                'negotiation': '商务谈判',
            }
            result.append({
                'id': c['id'],
                'name': c['company_name'],
                'industry': c.get('industry', ''),
                'stage': c.get('sales_stage', ''),
                'stage_name': stage_map.get(c.get('sales_stage', ''), c.get('sales_stage', '')),
                'amount': float(c.get('amount', 0) or 0),
                'ai_score': c.get('ai_score'),
                'next_action': c.get('next_action', ''),
                'close_probability': 0.7 if c.get('sales_stage') == 'negotiation' else 0.5 if c.get('sales_stage') == 'solution' else 0.3,
            })
        return result

    def generate_today_suggestions(self) -> List[str]:
        """生成今日销售建议"""
        suggestions = []
        
        high_value = self.analyze_high_value_customers(limit=5)
        if high_value:
            top = high_value[0]
            suggestions.append(f'重点关注高价值客户[{top["name"]}]，当前阶段[{top["stage"]}]，预计金额{top["amount"]/10000:.1f}万')
        
        stale = self.analyze_stale_customers()
        high_stale = [s for s in stale if s['priority'] == 'high']
        if high_stale:
            suggestions.append(f'有{len(high_stale)}个A级客户超过3天未跟进，请优先联系')
        
        risk = self.analyze_risk_customers()
        if risk:
            suggestions.append(f'发现{len(risk)}个风险客户，销售阶段长期无变化，建议主动推进')
        
        opportunities = self.analyze_opportunities()
        if opportunities:
            total_amount = sum(o['amount'] for o in opportunities)
            suggestions.append(f'当前有{len(opportunities)}个成交机会，预计总金额{total_amount/10000:.1f}万')
        
        if not suggestions:
            suggestions.append('今日暂无紧急事项，建议维护客户关系，拓展新客户')
        
        return suggestions

    def _build_suggestions(self, high_value, stale, risk, opportunities) -> List[str]:
        """基于已查询好的数据生成今日建议，避免再次查库"""
        suggestions = []
        if high_value:
            top = high_value[0]
            suggestions.append(f'重点关注高价值客户[{top["name"]}]，当前阶段[{top["stage"]}]，预计金额{top["amount"]/10000:.1f}万')
        high_stale = [s for s in stale if s['priority'] == 'high']
        if high_stale:
            suggestions.append(f'有{len(high_stale)}个A级客户超过3天未跟进，请优先联系')
        if risk:
            suggestions.append(f'发现{len(risk)}个风险客户，销售阶段长期无变化，建议主动推进')
        if opportunities:
            total_amount = sum(o['amount'] for o in opportunities)
            suggestions.append(f'当前有{len(opportunities)}个成交机会，预计总金额{total_amount/10000:.1f}万')
        if not suggestions:
            suggestions.append('今日暂无紧急事项，建议维护客户关系，拓展新客户')
        return suggestions

    def analyze_all(self, use_cache: bool = True) -> Dict:
        """执行完整分析（4个独立分析并行查询 + 短TTL缓存，避免8次串行远程查库）"""
        # 命中缓存直接返回
        if use_cache and self._all_cache is not None and (time.time() - self._all_cache_ts) < ANALYSIS_CACHE_TTL:
            return self._all_cache

        logger.info('开始销售分析...')
        # 4个分析方法各自建立独立DB连接、无共享状态，可并行
        with ThreadPoolExecutor(max_workers=4) as ex:
            f_high = ex.submit(self.analyze_high_value_customers)
            f_risk = ex.submit(self.analyze_risk_customers)
            f_stale = ex.submit(self.analyze_stale_customers)
            f_opp = ex.submit(self.analyze_opportunities)
            high_value = f_high.result()
            risk = f_risk.result()
            stale = f_stale.result()
            opportunities = f_opp.result()

        result = {
            'analysis_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'high_value_customers': high_value,
            'risk_customers': risk,
            'stale_customers': stale,
            'opportunities': opportunities,
            'today_suggestions': self._build_suggestions(high_value, stale, risk, opportunities),
            'summary': {
                'high_value_count': len(high_value),
                'risk_count': len(risk),
                'stale_count': len(stale),
                'opportunity_count': len(opportunities),
                'total_pipeline_amount': sum(o['amount'] for o in opportunities),
            }
        }

        self._all_cache = result
        self._all_cache_ts = time.time()

        logger.info(f'分析完成: 高价值{result["summary"]["high_value_count"]}个, '
                   f'风险{result["summary"]["risk_count"]}个, '
                   f'未跟进{result["summary"]["stale_count"]}个, '
                   f'机会{result["summary"]["opportunity_count"]}个')

        return result


_instance = None
def get_sales_analysis_agent() -> SalesAnalysisAgent:
    global _instance
    if _instance is None:
        _instance = SalesAnalysisAgent()
    return _instance


if __name__ == '__main__':
    agent = get_sales_analysis_agent()
    result = agent.analyze_all()
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
