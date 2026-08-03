"""Agent 管理路由 - CRUD + 状态机 + 克隆 + 官方列表 + MCP/Skill绑定 + Tools汇总

所有响应用 ApiResponse 包装。
注意: /official/list 必须在 /{agent_id} 之前注册，避免 "official" 被识别为 agent_id。
绑定相关路由在 /{agent_id} 下，但要注意 GET /{agent_id} 不能挡住子路径（FastAPI 会自动按定义顺序匹配，子路径在前）。
"""
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from common.schemas import (
    ApiResponse,
    PageData,
    AgentCreate,
    AgentUpdate,
    AgentOut,
    AgentStatusChange,
    AgentMCPBindingOut,
    AgentSkillBindingOut,
)
from infrastructure.db import get_db
from services.agent_service import agent_service

agent_router = APIRouter()


class PolishPromptRequest(BaseModel):
    raw_prompt: str


class AgentMCPBindRequest(BaseModel):
    mcp_service_id: str
    config: dict = {}
    enabled: bool = True


class AgentSkillBindRequest(BaseModel):
    skill_id: str
    priority: int = 0
    enabled: bool = True


@agent_router.get("/official/list", response_model=ApiResponse)
async def list_official(
    db: AsyncSession = Depends(get_db),
):
    """获取官方 Agent 列表"""
    items = await agent_service.list_official_agents(db)
    return ApiResponse(data=[a.model_dump() for a in items])


@agent_router.post("", response_model=ApiResponse)
async def create_agent(
    payload: AgentCreate,
    db: AsyncSession = Depends(get_db),
):
    """创建 Agent (同时自动创建 1:1 LongTermMemory)"""
    agent = await agent_service.create_agent(db, payload)
    return ApiResponse(data=agent.model_dump())


@agent_router.get("", response_model=ApiResponse)
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


# ── MCP 绑定路由 ──────────────────────────────────────
@agent_router.get("/{agent_id}/mcp-bindings", response_model=ApiResponse)
async def list_mcp_bindings(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
):
    """列出 Agent 绑定的所有 MCP 服务 (join mcp_services 表拿 name/mode/status)"""
    items = await agent_service.list_mcp_bindings(db, agent_id)
    return ApiResponse(data=[i.model_dump() for i in items])


@agent_router.post("/{agent_id}/mcp-bindings", response_model=ApiResponse)
async def bind_mcp(
    agent_id: str,
    payload: AgentMCPBindRequest,
    db: AsyncSession = Depends(get_db),
):
    """Agent 绑定 MCP 服务 (UNIQUE agent_id+mcp_service_id，重复则抛校验错)"""
    from common.schemas import AgentMCPBindingCreate
    create_payload = AgentMCPBindingCreate(
        agent_id=agent_id,
        mcp_service_id=payload.mcp_service_id,
        config=payload.config,
        enabled=payload.enabled,
    )
    result = await agent_service.bind_mcp(db, agent_id, create_payload)
    return ApiResponse(data=result.model_dump())


@agent_router.delete("/{agent_id}/mcp-bindings/{mcp_service_id}", response_model=ApiResponse)
async def unbind_mcp(
    agent_id: str,
    mcp_service_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Agent 解绑 MCP 服务 (不存在则抛 NotFound)"""
    await agent_service.unbind_mcp(db, agent_id, mcp_service_id)
    return ApiResponse(message="解绑成功")


# ── Skill 绑定路由 ────────────────────────────────────
@agent_router.get("/{agent_id}/skill-bindings", response_model=ApiResponse)
async def list_skill_bindings(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
):
    """列出 Agent 绑定的所有 Skill (join skills 表拿 name/category/source)"""
    items = await agent_service.list_skill_bindings(db, agent_id)
    return ApiResponse(data=[i.model_dump() for i in items])


@agent_router.post("/{agent_id}/skill-bindings", response_model=ApiResponse)
async def bind_skill(
    agent_id: str,
    payload: AgentSkillBindRequest,
    db: AsyncSession = Depends(get_db),
):
    """Agent 绑定 Skill (UNIQUE agent_id+skill_id，重复则抛校验错)"""
    from common.schemas import AgentSkillBindingCreate
    create_payload = AgentSkillBindingCreate(
        agent_id=agent_id,
        skill_id=payload.skill_id,
        priority=payload.priority,
        enabled=payload.enabled,
    )
    result = await agent_service.bind_skill(db, agent_id, create_payload)
    return ApiResponse(data=result.model_dump())


@agent_router.delete("/{agent_id}/skill-bindings/{skill_id}", response_model=ApiResponse)
async def unbind_skill(
    agent_id: str,
    skill_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Agent 解绑 Skill (不存在则抛 NotFound)"""
    await agent_service.unbind_skill(db, agent_id, skill_id)
    return ApiResponse(message="解绑成功")


# ── 工具汇总路由 ──────────────────────────────────────
@agent_router.get("/{agent_id}/tools-summary", response_model=ApiResponse)
async def get_agent_tools_summary(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Agent 对话前工具汇总：返回所有绑定的 MCP（含 tools 列表）和 Skill 概要"""
    result = await agent_service.get_agent_tools_summary(db, agent_id)
    return ApiResponse(data=result)


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


@agent_router.post("/polish-prompt", response_model=ApiResponse)
async def polish_prompt(
    payload: PolishPromptRequest,
    db: AsyncSession = Depends(get_db),
):
    """AI 润色系统提示词 - 调用提示词工程专家 Agent 进行专业化润色"""
    if not payload.raw_prompt or not payload.raw_prompt.strip():
        return ApiResponse(code=400, message="提示词内容不能为空")
    result = await agent_service.polish_system_prompt(db, payload.raw_prompt.strip())
    return ApiResponse(data=result)
