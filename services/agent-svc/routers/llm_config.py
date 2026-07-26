"""LLM 配置路由 - CRUD + 连通性测试

所有响应用 ApiResponse 包装。
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from common.schemas import (
    ApiResponse,
    PageData,
    LLMConfigCreate,
    LLMConfigUpdate,
    LLMConfigOut,
)
from infrastructure.db import get_db
from services.llm_service import llm_service

llm_router = APIRouter()


@llm_router.post("/", response_model=ApiResponse)
async def create_config(
    payload: LLMConfigCreate,
    db: AsyncSession = Depends(get_db),
):
    """创建LLM配置 (api_key 加密存储)"""
    config = await llm_service.create_config(db, payload)
    return ApiResponse(data=config.model_dump())


@llm_router.get("/", response_model=ApiResponse)
async def list_configs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """获取LLM配置列表 (分页, api_key 掩码显示)"""
    items, total = await llm_service.get_configs(db, page, page_size)
    page_data = PageData(items=[i.model_dump() for i in items], total=total,
                         page=page, page_size=page_size)
    return ApiResponse(data=page_data.model_dump())


@llm_router.get("/{config_id}", response_model=ApiResponse)
async def get_config(
    config_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取LLM配置详情"""
    config = await llm_service.get_config(db, config_id)
    return ApiResponse(data=config.model_dump())


@llm_router.put("/{config_id}", response_model=ApiResponse)
async def update_config(
    config_id: str,
    payload: LLMConfigUpdate,
    db: AsyncSession = Depends(get_db),
):
    """更新LLM配置"""
    config = await llm_service.update_config(db, config_id, payload)
    return ApiResponse(data=config.model_dump())


@llm_router.delete("/{config_id}", response_model=ApiResponse)
async def delete_config(
    config_id: str,
    db: AsyncSession = Depends(get_db),
):
    """删除LLM配置"""
    await llm_service.delete_config(db, config_id)
    return ApiResponse(message="删除成功")


@llm_router.post("/{config_id}/test", response_model=ApiResponse)
async def test_connection(
    config_id: str,
    db: AsyncSession = Depends(get_db),
):
    """测试LLM连通性 (发送测试消息)"""
    result = await llm_service.test_connection(db, config_id)
    return ApiResponse(data=result)
