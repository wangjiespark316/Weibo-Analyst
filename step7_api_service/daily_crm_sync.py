#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
每日飞书 CRM 客户同步 + 销售 AI 结果重算
=====================================
流程:
  飞书多维表客户主表 -> 本地 customers
       -> AI 客户评分 / 成交概率预测 / 销售漏斗快照
       -> 销售分析(高价值/风险/未跟进/机会) / 今日销售任务 / 销售日报复盘

设计:
  - 每一步独立异常捕获，单步失败不阻断后续步骤
  - 同步只增改、不删除本地数据
  - 供 systemd timer 每日调度，也可手动执行:
      .venv/bin/python daily_crm_sync.py
"""
import sys
import traceback
from pathlib import Path
from datetime import datetime

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

from dotenv import load_dotenv
load_dotenv('/opt/Weibo-Analyst/.env')


def log(msg):
    print(f'[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}', flush=True)


def step(name, fn):
    log(f'==> 开始: {name}')
    try:
        info = fn()
        log(f'    完成: {name}' + (f' -> {info}' if info is not None else ''))
        return True
    except Exception as e:
        log(f'    失败: {name}: {e}')
        traceback.print_exc()
        return False


def main():
    log('===== 每日 CRM 同步与销售重算开始 =====')
    results = {}

    # 1. 飞书多维表客户同步（全量拉取、本地 upsert，只增改不删除）
    def s1():
        from feishu_bitable_sync import get_feishu_bitable_sync
        r = get_feishu_bitable_sync().sync_all()
        return r.get('message')
    results['crm_sync'] = step('飞书CRM客户同步', s1)

    # 1b. 飞书跟进记录 + 商机明细同步，并回填客户金额/跟进次数/最近跟进/下一步
    def s1b():
        from feishu_crm_detail_sync import main as detail_main
        r = detail_main()
        return (f"跟进{r.get('follow')} 商机{r.get('opportunity')} "
                f"在途金额{r.get('pipeline_amount'):,.0f}")
    results['crm_detail'] = step('飞书跟进与商机明细同步', s1b)

    # 2. AI 客户机会评分（全量重算，按客户唯一键覆盖）
    def s2():
        import customer_scoring
        n = customer_scoring.calc_all()
        return f'评分客户 {n} 个' if n is not None else None
    results['scoring'] = step('AI客户评分重算', s2)

    # 3. 成交概率预测（排除已成交/已流失客户）
    def s3():
        from deal_prediction_agent import get_deal_prediction_agent
        r = get_deal_prediction_agent().predict_all()
        try:
            return f'预测 {len(r)} 个客户'
        except TypeError:
            return None
    results['prediction'] = step('成交概率预测重算', s3)

    # 4. 销售漏斗当日快照（先删当日再插入）
    def s4():
        from sales_funnel_analyzer import get_sales_funnel_analyzer
        get_sales_funnel_analyzer().save_snapshot()
        return None
    results['funnel'] = step('销售漏斗快照', s4)

    # 5. 销售分析（高价值 / 风险 / 长期未跟进 / 成交机会）
    def s5():
        from sales_analysis_agent import get_sales_analysis_agent
        r = get_sales_analysis_agent().analyze_all(use_cache=False)
        s = r.get('summary', {})
        return (f"高价值{s.get('high_value_count')} 风险{s.get('risk_count')} "
                f"未跟进{s.get('stale_count')} 机会{s.get('opportunity_count')}")
    results['analysis'] = step('销售分析重算', s5)

    # 6. 今日销售任务（重点跟进客户 TOP5）
    def s6():
        from daily_sales_agent import gen_tasks
        r = gen_tasks(use_cache=False)
        return f"重点任务 {len(r.get('top5_tasks') or [])} 个"
    results['tasks'] = step('今日销售任务生成', s6)

    # 7. 销售日报复盘（覆盖当日同类型复盘）
    def s7():
        from sales_review_agent import get_sales_review_agent
        get_sales_review_agent().generate_daily_review()
        return None
    results['review'] = step('销售日报复盘生成', s7)

    ok = sum(1 for v in results.values() if v)
    log(f'===== 结束: 成功 {ok}/{len(results)} 步 | {results} =====')
    return 0 if ok == len(results) else 1


if __name__ == '__main__':
    sys.exit(main())
