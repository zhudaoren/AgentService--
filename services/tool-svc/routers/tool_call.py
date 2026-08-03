"""工具调用代理路由 + 调用日志查询"""
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from common.schemas import (
    ApiResponse,
    PageData,
    ToolCallResponse,
    ToolCallLogOut,
)
from infrastructure.db import get_db
from services.mcp_service import mcp_service

tool_call_router = APIRouter()


class ToolCallProxyRequest(BaseModel):
    """工具调用代理请求（扩展 ToolCallRequest，加上定位 MCP 与日志所需字段）"""
    agent_id: Optional[str] = None
    conversation_id: Optional[str] = None
    mcp_service_id: Optional[str] = None
    mcp_service_name: Optional[str] = None
    tool_name: str
    arguments: dict = {}
    timeout: int = 30


@tool_call_router.post("/tools/call", response_model=ApiResponse)
async def call_tool(
    payload: ToolCallProxyRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    工具调用代理：
    - 根据 mcp_service_id 或 mcp_service_name 查找 MCP 服务
    - 如未连接则自动 connect
    - 调用 adapter.call_tool 并记录日志与 usage_count
    """
    result_obj, duration_ms = await mcp_service.call_tool(
        db,
        tool_name=payload.tool_name,
        arguments=payload.arguments,
        timeout=payload.timeout,
        mcp_service_id=payload.mcp_service_id,
        mcp_service_name=payload.mcp_service_name,
        agent_id=payload.agent_id,
        conversation_id=payload.conversation_id,
    )
    resp = ToolCallResponse(
        tool_name=payload.tool_name,
        status="success",
        result=result_obj,
        error_message="",
        duration_ms=duration_ms,
    )
    return ApiResponse(data=resp.model_dump())


@tool_call_router.get("/tool-call-logs", response_model=ApiResponse)
async def list_tool_call_logs(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    agent_id: Optional[str] = None,
    conversation_id: Optional[str] = None,
    mcp_service_id: Optional[str] = None,
    status: Optional[str] = None,
    tool_name: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """工具调用日志分页查询（支持多条件过滤）"""
    items, total = await mcp_service.list_tool_call_logs(
        db,
        page=page,
        page_size=page_size,
        agent_id=agent_id,
        conversation_id=conversation_id,
        mcp_service_id=mcp_service_id,
        status=status,
        tool_name=tool_name,
    )
    page_data = PageData(
        items=[i.model_dump() for i in items],
        total=total,
        page=page,
        page_size=page_size,
    )
    return ApiResponse(data=page_data.model_dump())
