"""
销售情报API路由
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sales_opportunity_analyzer import get_opportunities, analyze_and_save, get_latest_date
from customer_matcher import match_customer_opportunities, get_customer_opportunities, save_customer_opportunity, update_customer_opportunity_status
from sales_script_generator import generate_sales_script, generate_daily_sales_brief
from industries import get_all_industries, get_industry_names

router = APIRouter(prefix="/api/sales", tags=["销售情报"])


class SalesScriptRequest(BaseModel):
    customer: str
    industry: str
    scenario: str
    type: str = "first_contact"
    context: Optional[str] = None


class CustomerMatchRequest(BaseModel):
    customer_name: str
    industry: str
    customer_id: Optional[str] = None
    date: Optional[str] = None


class CustomerOpportunityStatusRequest(BaseModel):
    status: str


@router.get("/opportunities")
async def get_sales_opportunities(
    date: Optional[str] = None,
    priority: Optional[str] = None,
    industry: Optional[str] = None,
    limit: int = 50
):
    """获取销售机会列表"""
    try:
        # 未指定日期时默认返回最新一个分析日（与前端“今日机会”口径一致）
        if not date:
            date = get_latest_date()
        opportunities = get_opportunities(
            date_str=date,
            priority=priority,
            industry=industry,
            limit=limit
        )
        
        # 转换日期格式
        for opp in opportunities:
            if opp.get("date") and hasattr(opp["date"], "isoformat"):
                opp["date"] = opp["date"].isoformat()
            if opp.get("created_time") and hasattr(opp["created_time"], "isoformat"):
                opp["created_time"] = opp["created_time"].isoformat()
        
        return {
            "date": date or datetime.now().strftime("%Y-%m-%d"),
            "count": len(opportunities),
            "opportunities": opportunities
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/opportunities/analyze")
async def analyze_sales_opportunities(date: Optional[str] = None, force: bool = False):
    """手动触发销售机会分析"""
    try:
        result = analyze_and_save(date_str=date, force=force)
        return {
            "status": "success",
            "count": len(result),
            "message": f"成功生成 {len(result)} 个销售机会"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/industries")
async def get_industries_list():
    """获取行业列表"""
    return {
        "count": len(get_all_industries()),
        "industries": get_all_industries()
    }


@router.get("/customer-match/{customer_id}")
async def get_customer_match(
    customer_id: str,
    customer_name: Optional[str] = None,
    industry: Optional[str] = None,
    date: Optional[str] = None
):
    """获取客户匹配的AI机会"""
    try:
        if not customer_name:
            customer_name = customer_id
        if not industry:
            industry = "制造业"  # 默认
        
        matched = match_customer_opportunities(
            customer_name=customer_name,
            industry=industry,
            date_str=date,
            customer_id=customer_id
        )
        
        return {
            "customer_id": customer_id,
            "customer_name": customer_name,
            "industry": industry,
            "match_count": len(matched),
            "opportunities": matched
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/customer-match")
async def create_customer_match(request: CustomerMatchRequest):
    """创建客户匹配并保存"""
    try:
        matched = match_customer_opportunities(
            customer_name=request.customer_name,
            industry=request.industry,
            date_str=request.date,
            customer_id=request.customer_id
        )
        
        # 保存最佳匹配
        saved_ids = []
        for match in matched[:3]:
            opp_id = save_customer_opportunity(
                customer_name=match["customer_name"],
                industry=match["industry"],
                match_score=match["match_score"],
                recommended_scene=match["recommended_scene"],
                reason=match["reason"],
                suggestion=match["suggestion"],
                customer_id=match.get("customer_id"),
                status="new"
            )
            saved_ids.append(opp_id)
        
        return {
            "status": "success",
            "match_count": len(matched),
            "saved_count": len(saved_ids),
            "opportunities": matched
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/customer-opportunities")
async def list_customer_opportunities(
    customer_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50
):
    """获取客户机会列表"""
    try:
        results = get_customer_opportunities(
            customer_id=customer_id,
            status=status,
            limit=limit
        )
        
        # 转换日期格式
        for r in results:
            if r.get("created_time") and hasattr(r["created_time"], "isoformat"):
                r["created_time"] = r["created_time"].isoformat()
            if r.get("updated_time") and hasattr(r["updated_time"], "isoformat"):
                r["updated_time"] = r["updated_time"].isoformat()
        
        return {
            "count": len(results),
            "opportunities": results
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/customer-opportunities/{opp_id}")
async def update_customer_opp_status(opp_id: int, request: CustomerOpportunityStatusRequest):
    """更新客户机会状态"""
    try:
        valid_statuses = ["new", "contacted", "following", "closed"]
        if request.status not in valid_statuses:
            raise HTTPException(status_code=400, detail=f"状态必须是: {', '.join(valid_statuses)}")
        
        update_customer_opportunity_status(opp_id, request.status)
        return {"status": "success", "id": opp_id, "new_status": request.status}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/script")
async def generate_script(request: SalesScriptRequest):
    """生成销售话术"""
    try:
        valid_types = ["first_contact", "follow_up", "meeting_invite", "solution_discussion"]
        if request.type not in valid_types:
            raise HTTPException(status_code=400, detail=f"话术类型必须是: {', '.join(valid_types)}")
        
        result = generate_sales_script(
            customer_name=request.customer,
            industry=request.industry,
            scenario=request.scenario,
            script_type=request.type,
            context=request.context
        )
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/daily")
async def get_sales_daily(date: Optional[str] = None):
    """获取销售情报日报"""
    try:
        brief = generate_daily_sales_brief(date_str=date)
        return {
            "date": date or datetime.now().strftime("%Y-%m-%d"),
            "content": brief
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
