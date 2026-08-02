"""记忆管理路由 - 长期/短期记忆 + 摘要

所有响应用 ApiResponse 包装。
路径顺序: /agents/{agent_id}/long-term/summary 在 /agents/{agent_id}/long-term
之前注册，避免被识别为相同前缀（虽然 FastAPI 精确匹配，但保持与 agent-svc 一致风格）。
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from common.schemas import (
    ApiResponse,
    LongTermMemoryOut,
    LongTermMemoryUpdate,
    PageData,
)
from infrastructure.db import get_db
from services.memory_service import memory_service

memory_router = APIRouter()


@memory_router.get(
    "/agents/{agent_id}/long-term/summary", response_model=ApiResponse
)
async def get_memory_summary(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取记忆摘要（汇总 user_profile/experience 关键字段）"""
    summary = await memory_service.get_memory_summary(db, agent_id)
    return ApiResponse(data=summary)


@memory_router.get(
    "/agents/{agent_id}/long-term", response_model=ApiResponse
)
async def get_long_term_memory(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取 Agent 的长期记忆（不存在则返回空结构，不自动创建）"""
    memory = await memory_service.get_long_term_memory(db, agent_id)
    return ApiResponse(data=memory.model_dump())


@memory_router.put(
    "/agents/{agent_id}/long-term", response_model=ApiResponse
)
async def update_long_term_memory(
    agent_id: str,
    payload: LongTermMemoryUpdate,
    db: AsyncSession = Depends(get_db),
):
    """更新长期记忆 (version+1，不存在则兜底创建)"""
    memory = await memory_service.update_long_term_memory(
        db, agent_id, payload
    )
    return ApiResponse(data=memory.model_dump())


@memory_router.get(
    "/agents/{agent_id}/short-term/{conversation_id}",
    response_model=ApiResponse,
)
async def get_short_term_memory(
    agent_id: str,
    conversation_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """获取会话短期记忆（消息历史，按时间升序）"""
    items, total = await memory_service.get_short_term_memory(
        db, agent_id, conversation_id, page=page, page_size=page_size
    )
    page_data = PageData(
        items=[i.model_dump() for i in items],
        total=total,
        page=page,
        page_size=page_size,
    )
    return ApiResponse(data=page_data.model_dump())


@memory_router.delete(
    "/agents/{agent_id}/short-term/{conversation_id}",
    response_model=ApiResponse,
)
async def clear_short_term_memory(
    agent_id: str,
    conversation_id: str,
    db: AsyncSession = Depends(get_db),
):
    """清空会话短期记忆（删除所有消息，并清除 Redis 缓存）"""
    count = await memory_service.clear_short_term_memory(
        db, agent_id, conversation_id
    )
    return ApiResponse(message=f"已清空 {count} 条消息")
