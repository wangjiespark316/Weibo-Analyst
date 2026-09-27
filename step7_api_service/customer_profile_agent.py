"""
AI客户画像Agent
"""
import os, json, requests
from dotenv import load_dotenv
from industries import get_industry_by_name

load_dotenv("/opt/Weibo-Analyst/.env")
LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_API_BASE = os.getenv("LLM_API_BASE", "https://api.deepseek.com/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")

def call_llm(messages, max_tokens=1500):
    try:
        resp = requests.post(f"{LLM_API_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {LLM_API_KEY}", "Content-Type": "application/json"},
            json={"model": LLM_MODEL, "messages": messages, "temperature": 0.7, "max_tokens": max_tokens}, timeout=45)
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"LLM error: {e}")
        return None

def generate_customer_profile(customer, follow_records=None, ai_trends=None):
    industry_info = get_industry_by_name(customer.get("industry", ""))
    follow_summary = ""
    if follow_records:
        follow_summary = "\n历史跟进：\n" + "\n".join([f"{i+1}. [{r.get('follow_type','')}] {r.get('content','')[:80]}" for i, r in enumerate(follow_records[-3:])])
    
    system_prompt = """你是资深B2B销售顾问。根据客户信息生成客户画像。输出JSON：
{"company_profile":"","industry_analysis":"","possible_needs":[],"recommended_scenarios":[],"sales_strategy":"","risk_points":[],"key_person_analysis":"","budget_estimate":""}"""
    
    user_prompt = f"""客户：{customer.get('company_name','')}
行业：{customer.get('industry','')}，规模：{customer.get('company_size','')}
联系人：{customer.get('contact_name','')}（{customer.get('contact_role','')}）
销售阶段：{customer.get('sales_stage','')}
{follow_summary}
请生成客户画像。"""
    
    result = call_llm([{"role":"system","content":system_prompt},{"role":"user","content":user_prompt}])
    if result:
        try:
            s, e = result.find('{'), result.rfind('}')+1
            if s >= 0 and e > s:
                return json.loads(result[s:e])
        except: pass
        return {"company_profile": result, "possible_needs":[], "recommended_scenarios":[], "sales_strategy":"", "risk_points":[]}
    
    scenarios = industry_info.get("scenarios", [])[:3] if industry_info else []
    pains = industry_info.get("pain_points", [])[:3] if industry_info else []
    return {
        "company_profile": f"{customer.get('company_name','')}是{customer.get('company_size','')}的{customer.get('industry','')}企业。",
        "industry_analysis": f"{customer.get('industry','')}行业AI应用快速发展，痛点：{', '.join(pains)}。",
        "possible_needs": pains,
        "recommended_scenarios": scenarios,
        "sales_strategy": f"建议从{scenarios[0] if scenarios else 'AI办公'}场景切入。",
        "risk_points": ["预算不确定", "决策链较长"],
        "key_person_analysis": f"{customer.get('contact_name','')}是关键决策人。",
        "budget_estimate": "预算约10-50万/年。"
    }
