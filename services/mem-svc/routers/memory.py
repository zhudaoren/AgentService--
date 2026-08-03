"""记忆管理路由 - 长期/短期记忆 + 摘要 + 记忆深化 + 语义搜索

所有响应用 ApiResponse 包装。
路径顺序: /agents/{agent_id}/long-term/summary 在 /agents/{agent_id}/long-term
之前注册，避免被识别为相同前缀（虽然 FastAPI 精确匹配，但保持与 agent-svc 一致风格）。
"""
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from common.schemas import (
    ApiResponse,
    LongTermMemoryOut,
    LongTermMemoryUpdate,
    PageData,
)
from infrastructure.db import get_db
from services.memory_service import memory_service
from services.short_term_cache import short_term_cache

memory_router = APIRouter()


# ── P2 新增请求体 ──────────────────────────────────────
class MemoryEvaluateRequest(BaseModel):
    agent_id: str = Field(..., description="Agent ID")
    conversation_id: Optional[str] = Field(default=None, description="会话ID(可选，用于缓存关联)")
    messages: list[dict[str, Any]] = Field(default_factory=list, description="对话历史消息列表")


class MemorySemanticSearchRequest(BaseModel):
    agent_id: str = Field(..., description="Agent ID")
    query: str = Field(..., description="搜索关键词")
    top_k: int = Field(default=5, ge=1, le=50, description="返回条数上限")


# ── 现有路由（保持不变） ──────────────────────────────

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


# ── P2 新增路由 ──────────────────────────────────────

@memory_router.post(
    "/evaluate",
    response_model=ApiResponse,
)
async def evaluate_memory(
    payload: MemoryEvaluateRequest,
    db: AsyncSession = Depends(get_db),
):
    """对话历史记忆深化评估 -> 判断是否有值得持久化的信息并更新长期记忆

    当前 P2 阶段: llm_adapter 未注入，会直接返回 skipped=True
    """
    result = await memory_service.evaluate_and_update_long_term(
        db=db,
        agent_id=payload.agent_id,
        conversation_messages=payload.messages or [],
        llm_adapter=None,
    )
    # 如果传了 conversation_id，best-effort 同步刷新短期缓存
    if payload.conversation_id and (payload.messages or []):
        try:
            await short_term_cache.set_messages(
                payload.conversation_id, payload.messages or []
            )
        except Exception:
            pass
    return ApiResponse(data=result)


@memory_router.post(
    "/semantic-search",
    response_model=ApiResponse,
)
async def semantic_search(
    payload: MemorySemanticSearchRequest,
    db: AsyncSession = Depends(get_db),
):
    """语义搜索记忆（P2 关键词匹配占位实现，Milvus 集成为 Phase3）"""
    items = await memory_service.semantic_search_memory(
        db=db,
        agent_id=payload.agent_id,
        query=payload.query,
        top_k=payload.top_k,
    )
    return ApiResponse(
        data={
            "items": items,
            "total": len(items),
            "top_k": payload.top_k,
            "search_mode": "keyword_fallback(milvus_not_available)",
        }
    )


@memory_router.delete(
    "/short-term/{conversation_id}",
    response_model=ApiResponse,
)
async def invalidate_short_term_cache(
    conversation_id: str,
):
    """失效短期记忆缓存（仅清 Redis/内存 缓存，不删 messages 表）"""
    await short_term_cache.invalidate(conversation_id)
    return ApiResponse(
        data={"conversation_id": conversation_id, "invalidated": True},
        message=f"短期记忆缓存已失效: {conversation_id}",
    )
