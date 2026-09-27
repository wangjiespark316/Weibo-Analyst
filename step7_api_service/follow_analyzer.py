"""
AI跟进分析Agent
"""
import os, json, requests
from dotenv import load_dotenv

load_dotenv("/opt/Weibo-Analyst/.env")
LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_API_BASE = os.getenv("LLM_API_BASE", "https://api.deepseek.com/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")

def call_llm(messages, max_tokens=1200):
    try:
        resp = requests.post(f"{LLM_API_BASE}/chat/completions",
            headers={"Authorization": f"Bearer {LLM_API_KEY}", "Content-Type": "application/json"},
            json={"model": LLM_MODEL, "messages": messages, "temperature": 0.5, "max_tokens": max_tokens}, timeout=45)
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"LLM error: {e}")
        return None

def analyze_follow_record(content, follow_type="电话", customer_info=None):
    system_prompt = """你是资深销售分析师。分析跟进记录，输出JSON：
{"summary":"","customer_needs":[],"customer_concerns":[],"intent_score":80,"customer_status":"","next_actions":[],"urgency":""}"""
    user_prompt = f"跟进类型：{follow_type}\n沟通内容：{content}\n请分析。"
    result = call_llm([{"role":"system","content":system_prompt},{"role":"user","content":user_prompt}])
    if result:
        try:
            s, e = result.find('{'), result.rfind('}')+1
            if s >= 0 and e > s:
                return json.loads(result[s:e])
        except: pass
    return {"summary": result or "待分析", "customer_needs":[], "customer_concerns":[], "intent_score":50, "customer_status":"待分析", "next_actions":[], "urgency":"中"}
