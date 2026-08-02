"""MCP 管理路由 - CRUD + 连接/断开 + 工具发现"""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from common.schemas import (
    ApiResponse,
    PageData,
    MCPServiceCreate,
    MCPServiceUpdate,
    MCPServiceOut,
    MCPToolOut,
)
from infrastructure.db import get_db
from services.mcp_service import mcp_service

mcp_router = APIRouter()


class ToggleToolRequest(BaseModel):
    enabled: bool


@mcp_router.get("/mcp-services", response_model=ApiResponse)
async def list_mcp_services(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    keyword: Optional[str] = None,
    mode: Optional[str] = None,
    status: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """MCP 服务列表查询（支持 name/description 关键词过滤、mode/status 过滤）"""
    items, total = await mcp_service.list(
        db,
        page=page,
        page_size=page_size,
        keyword=keyword,
        mode=mode,
        status=status,
    )
    page_data = PageData(
        items=[i.model_dump() for i in items],
        total=total,
        page=page,
        page_size=page_size,
    )
    return ApiResponse(data=page_data.model_dump())


@mcp_router.post("/mcp-services", response_model=ApiResponse)
async def create_mcp_service(
    payload: MCPServiceCreate,
    db: AsyncSession = Depends(get_db),
):
    """创建 MCP 服务（支持 sse/stdio 两种模式）"""
    mcp = await mcp_service.create(db, payload)
    return ApiResponse(data=mcp.model_dump())


@mcp_router.get("/mcp-services/{mcp_id}", response_model=ApiResponse)
async def get_mcp_service(
    mcp_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取 MCP 服务详情"""
    mcp = await mcp_service.get(db, mcp_id)
    return ApiResponse(data=mcp.model_dump())


@mcp_router.put("/mcp-services/{mcp_id}", response_model=ApiResponse)
async def update_mcp_service(
    mcp_id: str,
    payload: MCPServiceUpdate,
    db: AsyncSession = Depends(get_db),
):
    """更新 MCP 服务"""
    mcp = await mcp_service.update(db, mcp_id, payload)
    return ApiResponse(data=mcp.model_dump())


@mcp_router.delete("/mcp-services/{mcp_id}", response_model=ApiResponse)
async def delete_mcp_service(
    mcp_id: str,
    db: AsyncSession = Depends(get_db),
):
    """删除 MCP 服务（先断开连接）"""
    await mcp_service.delete(db, mcp_id)
    return ApiResponse(message="删除成功")


@mcp_router.post("/mcp-services/{mcp_id}/connect", response_model=ApiResponse)
async def connect_mcp_service(
    mcp_id: str,
    db: AsyncSession = Depends(get_db),
):
    """连接 MCP 服务"""
    result = await mcp_service.connect(db, mcp_id)
    return ApiResponse(data=result)


@mcp_router.post("/mcp-services/{mcp_id}/disconnect", response_model=ApiResponse)
async def disconnect_mcp_service(
    mcp_id: str,
    db: AsyncSession = Depends(get_db),
):
    """断开 MCP 服务"""
    await mcp_service.disconnect(db, mcp_id)
    return ApiResponse(message="断开成功")


@mcp_router.post("/mcp-services/{mcp_id}/discover", response_model=ApiResponse)
async def discover_mcp_tools(
    mcp_id: str,
    db: AsyncSession = Depends(get_db),
):
    """发现工具：调用 adapter.list_tools()，批量 upsert 到 mcp_tools 表"""
    tools = await mcp_service.discover_tools(db, mcp_id)
    return ApiResponse(data=tools)


@mcp_router.get("/mcp-services/{mcp_id}/tools", response_model=ApiResponse)
async def list_mcp_tools(
    mcp_id: str,
    enabled: Optional[bool] = None,
    db: AsyncSession = Depends(get_db),
):
    """列出该 MCP 下的工具（支持 enabled 过滤）"""
    tools = await mcp_service.list_tools(db, mcp_id, enabled=enabled)
    return ApiResponse(data=[t.model_dump() for t in tools])


@mcp_router.post("/mcp-services/{mcp_id}/tools/{tool_name}/toggle", response_model=ApiResponse)
async def toggle_mcp_tool(
    mcp_id: str,
    tool_name: str,
    payload: ToggleToolRequest,
    db: AsyncSession = Depends(get_db),
):
    """启用/禁用工具"""
    tool = await mcp_service.toggle_tool(db, mcp_id, tool_name, payload.enabled)
    return ApiResponse(data=tool.model_dump())
