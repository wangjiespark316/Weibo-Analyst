#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI销售策略Agent
针对不同客户状态生成推进策略
"""
import os
import sys
import json
import logging
from datetime import datetime

sys.path.insert(0, "/opt/Weibo-Analyst/step7_api_service")
from deal_prediction_agent import get_deal_prediction_agent

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class SalesStrategyAgent:
    def __init__(self):
        self.prediction_agent = get_deal_prediction_agent()

    def generate_strategy(self, customer_id):
        prediction = self.prediction_agent.predict_customer(customer_id)
        if not prediction:
            return None

        level = prediction["prediction_level"]
        customer, follow_count, ai_score = self.prediction_agent.get_customer_data(customer_id)
        stage = customer.get("sales_stage", "new")

        if level == "high":
            strategy = self._high_probability_strategy(customer, prediction)
        elif level == "medium":
            strategy = self._medium_probability_strategy(customer, prediction)
        else:
            strategy = self._low_probability_strategy(customer, prediction)

        strategy["customer_id"] = customer_id
        strategy["customer_name"] = customer.get("company_name", "")
        strategy["deal_probability"] = prediction["deal_probability"]
        return strategy

    def _high_probability_strategy(self, customer, prediction):
        stage = customer.get("sales_stage", "new")
        if stage == "solution":
            problem = "客户已认可方案，需要推进到商务阶段"
            next_steps = ["确认预算和采购流程", "安排商务谈判会议", "准备合同初稿"]
            script = "XX总，方案我们已经沟通得比较充分了，接下来想跟您确认一下采购流程和预算情况，看看什么时候可以进入合同阶段。"
        elif stage == "negotiation":
            problem = "进入商务谈判，需要促成签约"
            next_steps = ["确认最终报价", "处理客户异议", "推动合同签署"]
            script = "XX总，报价方面我们已经给到了最优惠的条件，您看还有哪些方面需要我们调整的，争取这周把合同定下来。"
        else:
            problem = "高意向客户，需要加快推进节奏"
            next_steps = ["安排深度需求调研", "准备定制化方案", "约见决策人"]
            script = "XX总，根据我们的沟通，您这边对产品很感兴趣，我想安排一次深度需求调研，给您出一份定制化方案。"

        return {
            "current_problem": problem,
            "strategy": "推进成交策略：加快节奏，确认关键决策因素",
            "next_steps": next_steps,
            "recommended_script": script
        }

    def _medium_probability_strategy(self, customer, prediction):
        risks = prediction.get("risk_factors", [])
        if any("未跟进" in r for r in risks):
            problem = "客户跟进不及时，热度可能下降"
            next_steps = ["立即联系客户", "发送有价值的行业资料", "重新确认需求"]
            script = "XX总，好久没联系了，最近我们整理了一些同行业的AI落地案例，想发给您参考一下，看看有没有新的想法。"
        elif any("预算" in r for r in risks):
            problem = "预算未确认，影响推进"
            next_steps = ["了解客户预算范围", "提供灵活的报价方案", "展示ROI分析"]
            script = "XX总，关于预算方面，我们可以根据您的实际情况提供不同档位的方案，也可以先做一个ROI分析给您参考。"
        else:
            problem = "客户意向中等，需要培育"
            next_steps = ["定期发送行业资讯", "邀请参加线上分享", "保持轻量沟通"]
            script = "XX总，最近AI行业有一些新的动态，我整理了一份简报，想跟您简单分享一下，看看对您有没有参考价值。"

        return {
            "current_problem": problem,
            "strategy": "持续培育策略：建立信任，挖掘明确需求",
            "next_steps": next_steps,
            "recommended_script": script
        }

    def _low_probability_strategy(self, customer, prediction):
        risks = prediction.get("risk_factors", [])
        if any("停滞" in r for r in risks):
            problem = "客户长期停滞，可能已流失"
            next_steps = ["寻找新的联系人", "重新挖掘需求", "发送唤醒邮件"]
            script = "XX总，之前我们沟通的方案可能有些地方没有完全匹配您的需求，最近我们产品有了一些更新，想重新了解一下您这边的情况。"
        else:
            problem = "客户意向较低，需要重新激活"
            next_steps = ["分析客户真实需求", "寻找新的切入点", "降低沟通频率，保持存在感"]
            script = "XX总，了解到您最近可能比较忙，我先不打扰您，有新的行业案例我会及时分享，您有需要随时联系我。"

        return {
            "current_problem": problem,
            "strategy": "重新激活策略：寻找新切入点，降低流失风险",
            "next_steps": next_steps,
            "recommended_script": script
        }


_instance = None
def get_sales_strategy_agent():
    global _instance
    if _instance is None:
        _instance = SalesStrategyAgent()
    return _instance


if __name__ == "__main__":
    agent = get_sales_strategy_agent()
    result = agent.generate_strategy(1)
    print(json.dumps(result, ensure_ascii=False, indent=2))
