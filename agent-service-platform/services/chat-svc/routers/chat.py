"""对话路由 - 会话 CRUD + 流式/非流式对话 + 停止生成

所有响应用 ApiResponse 包装。
路径顺序: /conversations 列表 / /chat / /chat/stop 必须在 /conversations/{conv_id} 之前。
"""
from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from common.schemas import (
    ApiResponse,
    ChatRequest,
    ConversationCreate,
    ConversationOut,
    MessageOut,
    PageData,
)
from common.exceptions import BadRequestException
from infrastructure.db import get_db
from services.chat_service import chat_service

chat_router = APIRouter()


# ── 会话 CRUD ────────────────────────────────────────
@chat_router.post("/conversations", response_model=ApiResponse)
async def create_conversation(
    payload: ConversationCreate,
    db: AsyncSession = Depends(get_db),
):
    """创建会话"""
    conv = await chat_service.create_conversation(db, payload)
    return ApiResponse(data=conv.model_dump())


@chat_router.get("/conversations", response_model=ApiResponse)
async def list_conversations(
    agent_id: str | None = None,
    user_id: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """获取会话列表（支持 agent_id 筛选 + 分页）"""
    items, total = await chat_service.get_conversations(
        db,
        agent_id=agent_id,
        user_id=user_id,
        page=page,
        page_size=page_size,
    )
    page_data = PageData(
        items=[i.model_dump() for i in items],
        total=total,
        page=page,
        page_size=page_size,
    )
    return ApiResponse(data=page_data.model_dump())


@chat_router.get("/conversations/{conv_id}", response_model=ApiResponse)
async def get_conversation(
    conv_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取会话详情"""
    conv = await chat_service.get_conversation(db, conv_id)
    return ApiResponse(data=conv.model_dump())


@chat_router.delete("/conversations/{conv_id}", response_model=ApiResponse)
async def delete_conversation(
    conv_id: str,
    db: AsyncSession = Depends(get_db),
):
    """删除会话（软删除）"""
    await chat_service.delete_conversation(db, conv_id)
    return ApiResponse(message="删除成功")


@chat_router.get(
    "/conversations/{conv_id}/messages", response_model=ApiResponse
)
async def get_messages(
    conv_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """获取会话消息历史（按时间升序分页）"""
    items, total = await chat_service.get_messages(
        db, conv_id, page=page, page_size=page_size
    )
    page_data = PageData(
        items=[i.model_dump() for i in items],
        total=total,
        page=page,
        page_size=page_size,
    )
    return ApiResponse(data=page_data.model_dump())


# ── 对话 ──────────────────────────────────────────────
@chat_router.post("/chat")
async def chat(payload: ChatRequest):
    """发送消息

    - stream=True: 返回 SSE 流（text/event-stream）
    - stream=False: 返回完整响应（ApiResponse）
    """
    if payload.stream:
        return StreamingResponse(
            chat_service.chat(payload.conversation_id, payload.content),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    result = await chat_service.chat_non_stream(
        payload.conversation_id, payload.content
    )
    return ApiResponse(data=result)


@chat_router.post("/chat/stop", response_model=ApiResponse)
async def stop_chat(payload: ChatRequest):
    """停止指定会话正在进行的流式生成

    复用 ChatRequest 结构（仅使用 conversation_id）。
    """
    stopped = chat_service.stop_generation(payload.conversation_id)
    if not stopped:
        raise BadRequestException(
            f"该会话当前无运行中的流式生成: {payload.conversation_id}"
        )
    return ApiResponse(message="已停止生成")
