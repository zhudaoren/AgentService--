"""Agent 业务服务

职责:
  - Agent CRUD (创建时自动创建 1:1 LongTermMemory)
  - Agent 状态机: created → deployed → running ↔ paused → stopped → (可重新 deploy)
      deploy: created/stopped → deployed
      start:  deployed → running
      pause:  running → paused
      resume: paused → running
      stop:   running/paused/deployed → stopped
  - clone_agent: 复制配置, cloned_from_id 记录来源, is_official=False
  - init_official_agents: 启动时检查并创建 5 个官方 Agent (编程/绘图/文档/RAG/ChatBI)
"""
import uuid
from typing import Any, Optional

from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from common.exceptions import (
    NotFoundException,
    ValidationException,
    BadRequestException,
)
from common.logger import get_logger
from common.schemas import AgentCreate, AgentUpdate, AgentOut
from domain.models import Agent, LongTermMemory, LLMConfig
from infrastructure.db import AsyncSessionLocal

logger = get_logger(__name__)


# Agent 状态机定义: action → (允许的源状态集合, 目标状态)
# created → deployed → running ↔ paused → stopped → (可重新 deploy)
VALID_TRANSITIONS: dict[str, tuple[set[str], str]] = {
    "deploy": ({"created", "stopped"}, "deployed"),
    "start": ({"deployed"}, "running"),
    "pause": ({"running"}, "paused"),
    "resume": ({"paused"}, "running"),
    "stop": ({"running", "paused", "deployed"}, "stopped"),
}


# 5 个官方 Agent 定义
OFFICIAL_AGENTS: list[dict[str, Any]] = [
    {
        "name": "编程助手",
        "description": "官方编程助手 - 代码生成、调试、重构、解释",
        "system_prompt": (
            "你是一个专业的编程助手，擅长多种编程语言的代码编写、调试、"
            "重构和解释。请提供清晰、高效、可维护的代码解决方案，"
            "并附上必要的说明和最佳实践建议。"
        ),
        "memory_strategy": "standard",
        "config": {"category": "programming", "icon": "code"},
    },
    {
        "name": "绘图助手",
        "description": "官方绘图助手 - 图像生成、设计建议",
        "system_prompt": (
            "你是一个专业的绘图助手，能够帮助用户生成图像描述、"
            "提供设计建议、创建视觉创意方案，并指导图像生成的提示词编写。"
        ),
        "memory_strategy": "standard",
        "config": {"category": "drawing", "icon": "image"},
    },
    {
        "name": "文档助手",
        "description": "官方文档助手 - 文档撰写、格式化、摘要",
        "system_prompt": (
            "你是一个专业的文档助手，擅长撰写、整理、格式化和摘要各类文档，"
            "包括技术文档、报告、邮件、README 等，输出结构清晰、语言规范。"
        ),
        "memory_strategy": "standard",
        "config": {"category": "document", "icon": "file-text"},
    },
    {
        "name": "RAG助手",
        "description": "官方RAG助手 - 基于知识库的检索增强问答",
        "system_prompt": (
            "你是一个基于检索增强生成(RAG)的智能助手，能够基于知识库内容"
            "回答问题，提供准确、可溯源的信息。当知识库无相关内容时，"
            "应明确告知用户并避免编造。"
        ),
        "memory_strategy": "rag_enhanced",
        "config": {"category": "rag", "icon": "database"},
    },
    {
        "name": "ChatBI助手",
        "description": "官方ChatBI助手 - 自然语言转SQL、数据分析",
        "system_prompt": (
            "你是一个 ChatBI 智能助手，能够将自然语言转换为 SQL 查询，"
            "进行数据分析和可视化建议。请确保生成的 SQL 安全、高效，"
            "并解释查询逻辑。"
        ),
        "memory_strategy": "standard",
        "config": {"category": "chatbi", "icon": "chart"},
    },
]


class AgentService:
    """Agent 业务服务"""

    # ── CRUD ──────────────────────────────────────────

    async def create_agent(
        self, db: AsyncSession, payload: AgentCreate
    ) -> AgentOut:
        # 验证 LLM 配置存在
        llm_result = await db.execute(
            select(LLMConfig).where(LLMConfig.id == payload.llm_config_id)
        )
        if not llm_result.scalar_one_or_none():
            raise ValidationException(
                f"LLM配置不存在: {payload.llm_config_id}"
            )

        agent_id = uuid.uuid4().hex
        agent = Agent(
            id=agent_id,
            name=payload.name,
            description=payload.description,
            system_prompt=payload.system_prompt,
            llm_config_id=payload.llm_config_id,
            status="created",
            is_official=False,
            temperature=payload.temperature,
            max_tokens=payload.max_tokens,
            top_p=payload.top_p,
            memory_strategy=payload.memory_strategy,
            config=payload.config or {},
        )
        db.add(agent)

        # 自动创建 1:1 长期记忆
        memory = LongTermMemory(
            id=uuid.uuid4().hex,
            agent_id=agent_id,
            user_profile={},
            environment_facts={},
            experience={},
            shared_items={},
            version=1,
        )
        db.add(memory)

        await db.flush()
        logger.info(f"创建Agent: id={agent_id}, name={payload.name}")
        return await self._to_out(agent)

    async def list_agents(
        self,
        db: AsyncSession,
        status: Optional[str] = None,
        is_official: Optional[bool] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[AgentOut], int]:
        # 构建条件
        conditions = []
        if status is not None:
            conditions.append(Agent.status == status)
        if is_official is not None:
            conditions.append(Agent.is_official == is_official)

        # 总数
        count_stmt = select(func.count(Agent.id))
        for cond in conditions:
            count_stmt = count_stmt.where(cond)
        total = (await db.execute(count_stmt)).scalar() or 0

        # 分页 + 预加载 LLMConfig
        list_stmt = (
            select(Agent)
            .options(selectinload(Agent.llm_config))
            .order_by(Agent.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        for cond in conditions:
            list_stmt = list_stmt.where(cond)
        result = await db.execute(list_stmt)
        agents = result.scalars().all()
        items = [await self._to_out(a) for a in agents]
        return items, total

    async def get_agent(
        self, db: AsyncSession, agent_id: str
    ) -> AgentOut:
        agent = await self._get_by_id(db, agent_id)
        return await self._to_out(agent)

    async def update_agent(
        self, db: AsyncSession, agent_id: str, payload: AgentUpdate
    ) -> AgentOut:
        agent = await self._get_by_id(db, agent_id)
        data = payload.model_dump(exclude_unset=True)

        # 修改 llm_config_id 时需验证
        if data.get("llm_config_id"):
            llm_result = await db.execute(
                select(LLMConfig).where(LLMConfig.id == data["llm_config_id"])
            )
            if not llm_result.scalar_one_or_none():
                raise ValidationException(
                    f"LLM配置不存在: {data['llm_config_id']}"
                )

        for k, v in data.items():
            setattr(agent, k, v)

        await db.flush()
        logger.info(f"更新Agent: id={agent_id}")
        return await self._to_out(agent)

    async def delete_agent(
        self, db: AsyncSession, agent_id: str
    ) -> None:
        agent = await self._get_by_id(db, agent_id)
        # CASCADE 由数据库外键 ON DELETE CASCADE 保证 (记忆 + 会话)
        await db.delete(agent)
        await db.flush()
        logger.info(f"删除Agent: id={agent_id} (级联删除记忆和会话)")

    # ── 状态管理 ──────────────────────────────────────

    async def change_status(
        self, db: AsyncSession, agent_id: str, action: str
    ) -> AgentOut:
        if action not in VALID_TRANSITIONS:
            raise BadRequestException(
                f"不支持的状态变更动作: {action}, "
                f"可选: {sorted(VALID_TRANSITIONS.keys())}"
            )

        agent = await self._get_by_id(db, agent_id)
        allowed_from, to_state = VALID_TRANSITIONS[action]

        if agent.status not in allowed_from:
            raise BadRequestException(
                f"状态变更失败: 当前状态={agent.status}, 动作={action} "
                f"要求源状态∈{sorted(allowed_from)}"
            )

        old_status = agent.status
        agent.status = to_state
        await db.flush()
        logger.info(
            f"Agent状态变更: id={agent_id}, {action}: {old_status} → {to_state}"
        )
        return await self._to_out(agent)

    # ── 克隆 ──────────────────────────────────────────

    async def clone_agent(
        self, db: AsyncSession, agent_id: str
    ) -> AgentOut:
        source = await self._get_by_id(db, agent_id)

        new_id = uuid.uuid4().hex
        cloned = Agent(
            id=new_id,
            name=f"{source.name} (副本)",
            description=source.description,
            system_prompt=source.system_prompt,
            llm_config_id=source.llm_config_id,
            status="created",
            is_official=False,  # 克隆出来的强制为非官方
            cloned_from_id=source.id,
            temperature=source.temperature,
            max_tokens=source.max_tokens,
            top_p=source.top_p,
            memory_strategy=source.memory_strategy,
            config=source.config,
        )
        db.add(cloned)

        # 为克隆的 Agent 创建新的空长期记忆
        memory = LongTermMemory(
            id=uuid.uuid4().hex,
            agent_id=new_id,
            user_profile={},
            environment_facts={},
            experience={},
            shared_items={},
            version=1,
        )
        db.add(memory)

        await db.flush()
        logger.info(
            f"克隆Agent: source={agent_id}, new={new_id}, name={cloned.name}"
        )
        return await self._to_out(cloned)

    # ── 官方 Agent ────────────────────────────────────

    async def list_official_agents(
        self, db: AsyncSession
    ) -> list[AgentOut]:
        result = await db.execute(
            select(Agent)
            .options(selectinload(Agent.llm_config))
            .where(Agent.is_official == True)  # noqa: E712
            .order_by(Agent.created_at.asc())
        )
        agents = result.scalars().all()
        return [await self._to_out(a) for a in agents]

    async def init_official_agents(self) -> None:
        """启动时检查并创建 5 个官方 Agent (只在表为空时创建)

        使用独立 session, 自行 commit。
        """
        async with AsyncSessionLocal() as session:
            try:
                await self._init_official_agents_impl(session)
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def _init_official_agents_impl(
        self, db: AsyncSession
    ) -> None:
        # 只在表为空(无官方Agent)时创建
        count_result = await db.execute(
            select(func.count(Agent.id)).where(
                Agent.is_official == True  # noqa: E712
            )
        )
        existing_count = count_result.scalar() or 0
        if existing_count > 0:
            logger.info(
                f"已存在 {existing_count} 个官方Agent, 跳过初始化"
            )
            return

        # 获取默认 LLM 配置
        default_cfg_result = await db.execute(
            select(LLMConfig).where(LLMConfig.is_default == True).limit(1)  # noqa: E712
        )
        default_cfg = default_cfg_result.scalar_one_or_none()

        # 没有默认则取任意一个
        if default_cfg is None:
            any_cfg_result = await db.execute(select(LLMConfig).limit(1))
            default_cfg = any_cfg_result.scalar_one_or_none()

        # 仍然没有则创建占位默认 LLM 配置
        if default_cfg is None:
            default_cfg = LLMConfig(
                id=uuid.uuid4().hex,
                name="默认LLM配置",
                provider="openai",
                model_name="gpt-4o",
                api_key="",
                api_base_url="",
                default_params={
                    "temperature": 0.7,
                    "max_tokens": 4096,
                    "top_p": 0.9,
                },
                is_default=True,
            )
            db.add(default_cfg)
            await db.flush()
            logger.info("初始化时创建默认LLM配置 (占位, 请补充 api_key)")

        # 创建 5 个官方 Agent
        for agent_def in OFFICIAL_AGENTS:
            agent_id = uuid.uuid4().hex
            agent = Agent(
                id=agent_id,
                name=agent_def["name"],
                description=agent_def["description"],
                system_prompt=agent_def["system_prompt"],
                llm_config_id=default_cfg.id,
                status="created",
                is_official=True,
                temperature=0.7,
                max_tokens=4096,
                top_p=0.9,
                memory_strategy=agent_def["memory_strategy"],
                config=agent_def["config"],
            )
            db.add(agent)

            # 1:1 长期记忆
            memory = LongTermMemory(
                id=uuid.uuid4().hex,
                agent_id=agent_id,
                user_profile={},
                environment_facts={},
                experience={},
                shared_items={},
                version=1,
            )
            db.add(memory)

        await db.flush()
        logger.info(
            f"初始化完成: 创建 {len(OFFICIAL_AGENTS)} 个官方Agent "
            f"(编程/绘图/文档/RAG/ChatBI)"
        )

    # ── 内部工具 ──────────────────────────────────────

    async def _get_by_id(
        self, db: AsyncSession, agent_id: str
    ) -> Agent:
        result = await db.execute(
            select(Agent)
            .options(selectinload(Agent.llm_config))
            .where(Agent.id == agent_id)
        )
        agent = result.scalar_one_or_none()
        if not agent:
            raise NotFoundException(f"Agent不存在: {agent_id}")
        return agent

    async def _to_out(self, agent: Agent) -> AgentOut:
        # join LLMConfig 返回 llm_config_name
        llm_config_name = ""
        if agent.llm_config is not None:
            llm_config_name = agent.llm_config.name or ""

        return AgentOut(
            id=agent.id,
            name=agent.name,
            description=agent.description or "",
            system_prompt=agent.system_prompt,
            llm_config_id=agent.llm_config_id,
            llm_config_name=llm_config_name,
            status=agent.status,
            is_official=bool(agent.is_official),
            cloned_from_id=agent.cloned_from_id,
            temperature=agent.temperature,
            max_tokens=agent.max_tokens,
            top_p=agent.top_p,
            memory_strategy=agent.memory_strategy,
            config=agent.config or {},
            created_at=agent.created_at,
            updated_at=agent.updated_at,
        )


agent_service = AgentService()
