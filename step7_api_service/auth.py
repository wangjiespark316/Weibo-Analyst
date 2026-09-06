#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多租户 API Key 鉴权模块
========================
- 从 Authorization: Bearer <api_key> 读取密钥
- 查询 weibo_tenants 表获取租户信息
- 自动注入 dataset_type，禁止用户自行传入
- 无 Authorization 头时返回 None（兼容本地调试/旧调用）
"""
from typing import Optional
from fastapi import Header, HTTPException, Depends
from .database import fetch_one


def get_tenant_by_api_key(api_key: str) -> Optional[dict]:
    """根据 api_key 查询租户，返回租户信息或 None"""
    row = fetch_one(
        "SELECT tenant_id, tenant_name, api_key, dataset_type, status "
        "FROM weibo_tenants WHERE api_key = %s LIMIT 1",
        (api_key,)
    )
    if row:
        return {
            'tenant_id': row['tenant_id'],
            'tenant_name': row['tenant_name'],
            'api_key': row['api_key'],
            'dataset_type': row['dataset_type'],
            'status': row['status'],
        }
    return None


async def verify_api_key(
    authorization: Optional[str] = Header(None, description="Bearer <api_key>")
) -> Optional[dict]:
    """
    API Key 鉴权依赖项。

    - 有 Authorization: Bearer xxx → 校验并返回租户（含 dataset_type）
    - 无 Authorization 头 → 返回 None（兼容旧调用，dataset_type 走 Query 参数）
    - 有头但格式错误 / key 无效 / 租户禁用 → 401
    """
    if not authorization:
        return None

    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization 格式错误，应为 Bearer <api_key>")

    api_key = authorization[len("Bearer "):].strip()
    if not api_key:
        raise HTTPException(status_code=401, detail="API Key 不能为空")

    tenant = get_tenant_by_api_key(api_key)
    if not tenant:
        raise HTTPException(status_code=401, detail="无效的 API Key")
    if tenant['status'] != 1:
        raise HTTPException(status_code=403, detail="租户已被禁用")

    return tenant


def resolve_dataset_type(
    tenant: Optional[dict],
    query_dataset_type: Optional[str]
) -> Optional[str]:
    """
    解析最终使用的 dataset_type。

    规则：
    - 有 tenant（已鉴权）→ 强制使用 tenant.dataset_type，忽略用户传入值
    - 无 tenant（未鉴权）→ 使用 Query 参数 dataset_type（兼容旧调用）
    """
    if tenant:
        return tenant['dataset_type']
    return query_dataset_type
