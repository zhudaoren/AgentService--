"""Agent 管理路由 - CRUD + 状态机 + 克隆 + 官方列表

所有响应用 ApiResponse 包装。
注意: /official/list 必须在 /{agent_id} 之前注册，避免 "official" 被识别为 agent_id。
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from common.schemas import (
    ApiResponse,
    PageData,
    AgentCreate,
    AgentUpdate,
    AgentOut,
    AgentStatusChange,
)
from infrastructure.db import get_db
from services.agent_service import agent_service

agent_router = APIRouter()


@agent_router.get("/official/list", response_model=ApiResponse)
async def list_official(
    db: AsyncSession = Depends(get_db),
):
    """获取官方 Agent 列表"""
    items = await agent_service.list_official_agents(db)
    return ApiResponse(data=[a.model_dump() for a in items])


@agent_router.post("/", response_model=ApiResponse)
async def create_agent(
    payload: AgentCreate,
    db: AsyncSession = Depends(get_db),
):
    """创建 Agent (同时自动创建 1:1 LongTermMemory)"""
    agent = await agent_service.create_agent(db, payload)
    return ApiResponse(data=agent.model_dump())


@agent_router.get("/", response_model=ApiResponse)
async def list_agents(
    status: str | None = None,
    is_official: bool | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """获取 Agent 列表 (支持 status / is_official 筛选, join 返回 llm_config_name)"""
    items, total = await agent_service.list_agents(
        db, status=status, is_official=is_official,
        page=page, page_size=page_size,
    )
    page_data = PageData(items=[i.model_dump() for i in items], total=total,
                         page=page, page_size=page_size)
    return ApiResponse(data=page_data.model_dump())


@agent_router.get("/{agent_id}", response_model=ApiResponse)
async def get_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
):
    """获取 Agent 详情"""
    agent = await agent_service.get_agent(db, agent_id)
    return ApiResponse(data=agent.model_dump())


@agent_router.put("/{agent_id}", response_model=ApiResponse)
async def update_agent(
    agent_id: str,
    payload: AgentUpdate,
    db: AsyncSession = Depends(get_db),
):
    """更新 Agent"""
    agent = await agent_service.update_agent(db, agent_id, payload)
    return ApiResponse(data=agent.model_dump())


@agent_router.delete("/{agent_id}", response_model=ApiResponse)
async def delete_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
):
    """删除 Agent (CASCADE 级联删除记忆和会话)"""
    await agent_service.delete_agent(db, agent_id)
    return ApiResponse(message="删除成功")


@agent_router.post("/{agent_id}/status", response_model=ApiResponse)
async def change_status(
    agent_id: str,
    payload: AgentStatusChange,
    db: AsyncSession = Depends(get_db),
):
    """Agent 状态变更 (deploy/start/pause/resume/stop, 按状态机规则)"""
    agent = await agent_service.change_status(db, agent_id, payload.action)
    return ApiResponse(data=agent.model_dump())


@agent_router.post("/{agent_id}/clone", response_model=ApiResponse)
async def clone_agent(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
):
    """克隆 Agent (复制配置, is_official=False, cloned_from_id 记录来源)"""
    agent = await agent_service.clone_agent(db, agent_id)
    return ApiResponse(data=agent.model_dump())
