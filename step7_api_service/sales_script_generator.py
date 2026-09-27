"""
销售话术生成模块
根据机会、行业、客户信息生成销售沟通话术
"""

import os
import requests
import json
from dotenv import load_dotenv

load_dotenv("/opt/Weibo-Analyst/.env")

LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_API_BASE = os.getenv("LLM_API_BASE", "https://api.deepseek.com/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")


def call_llm(messages, max_tokens=1000):
    """调用LLM"""
    try:
        response = requests.post(
            f"{LLM_API_BASE}/chat/completions",
            headers={
                "Authorization": f"Bearer {LLM_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": LLM_MODEL,
                "messages": messages,
                "temperature": 0.7,
                "max_tokens": max_tokens
            },
            timeout=30
        )
        result = response.json()
        return result["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"LLM调用失败: {e}")
        return None


def generate_sales_script(customer_name, industry, scenario, script_type="first_contact", context=None):
    """
    生成销售话术
    script_type: first_contact(首次触达), follow_up(老客户跟进), meeting_invite(会议邀约), solution_discussion(方案沟通)
    """
    type_names = {
        "first_contact": "首次触达",
        "follow_up": "老客户跟进",
        "meeting_invite": "会议邀约",
        "solution_discussion": "方案沟通"
    }
    
    type_name = type_names.get(script_type, "首次触达")
    
    system_prompt = f"""你是一位资深的B2B销售专家，擅长AI产品销售。
请根据以下信息生成一段{type_name}话术。

要求：
1. 语气专业、自然、不生硬
2. 突出客户价值，不是产品功能
3. 控制在150-250字
4. 结尾要有明确的下一步行动建议
5. 不要用"您好，我是..."这种生硬开头
6. 结合行业痛点和AI趋势

输出格式：
话术内容：
[具体话术]

关键要点：
- [要点1]
- [要点2]

下一步建议：
[具体行动]"""

    user_prompt = f"""客户信息：
- 客户名称：{customer_name}
- 所属行业：{industry}
- 推荐场景：{scenario}
- 话术类型：{type_name}

{f'额外背景：{context}' if context else ''}

请生成销售话术。"""

    result = call_llm([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ], max_tokens=800)
    
    if result:
        return {
            "type": script_type,
            "type_name": type_name,
            "customer": customer_name,
            "industry": industry,
            "scenario": scenario,
            "content": result
        }
    else:
        # 兜底模板
        fallback = f"""话术内容：
{customer_name}的{industry}业务近期可以关注{scenario}方向，很多同行已经开始用AI提升效率。我们结合一些实际案例整理了落地思路，想约个时间简单交流下，看看有没有适合贵司的场景。

关键要点：
- 结合行业趋势切入
- 强调同行案例
- 提出具体交流邀约

下一步建议：
发送话术后，跟进客户回复，预约15分钟线上交流。"""
        return {
            "type": script_type,
            "type_name": type_name,
            "customer": customer_name,
            "industry": industry,
            "scenario": scenario,
            "content": fallback
        }


def generate_daily_sales_brief(date_str=None):
    """生成每日销售情报简报"""
    from datetime import datetime
    from sales_opportunity_analyzer import get_opportunities
    
    if not date_str:
        date_str = datetime.now().strftime("%Y-%m-%d")
    
    opportunities = get_opportunities(date_str=date_str, limit=10)
    
    high_opps = [o for o in opportunities if o.get("priority") == "high"]
    medium_opps = [o for o in opportunities if o.get("priority") == "medium"]
    
    brief = f"""# AI销售情报日报 - {date_str}

## 今日概览
- 销售机会总数：{len(opportunities)}个
- 高优先级：{len(high_opps)}个
- 中优先级：{len(medium_opps)}个

## 今日重点关注
"""
    
    for i, opp in enumerate(high_opps[:3], 1):
        brief += f"""
### {i}. {opp.get('industry')} - {opp.get('scenario')}
- **优先级**：高
- **触发**：{opp.get('trigger_content', '')}
- **推荐产品**：{opp.get('product', '')}
- **目标客户**：{opp.get('customer_type', '')}
- **销售切入点**：{opp.get('sales_angle', '')}
"""
    
    if medium_opps:
        brief += """
## 其他机会
"""
        for opp in medium_opps[:5]:
            brief += f"- {opp.get('industry')}：{opp.get('scenario')}（{opp.get('trigger_content', '')[:20]}）\n"
    
    brief += """
## 行动建议
1. 优先联系高优先级机会对应的行业客户
2. 准备相关行业案例和方案材料
3. 本周内完成首次触达
"""
    
    return brief
