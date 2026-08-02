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


# 6 个官方 Agent 定义
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
    {
        "name": "提示词工程专家",
        "description": "官方提示词工程专家 - 系统提示词润色、优化、专业化",
        "system_prompt": (
            "你是一位世界级的提示词工程专家（Prompt Engineering Expert），"
            "精通大语言模型的行为机制和提示词优化技术。\n\n"
            "你的职责是：接收用户提供的原始系统提示词草案，将其润色为"
            "专业、结构化、高效的系统提示词。\n\n"
            "润色原则：\n"
            "1. **角色定义清晰**：明确 Agent 的身份、专业领域和核心能力\n"
            "2. **行为约束精确**：规定 Agent 应该做什么、不应该做什么\n"
            "3. **输出格式规范**：指定输出的结构、格式和风格\n"
            "4. **边界条件明确**：处理边缘情况和异常输入的策略\n"
            "5. **语言简洁有力**：避免冗余，使用祈使句和肯定表述\n"
            "6. **保留用户意图**：不改变用户的核心需求，仅做专业化提升\n\n"
            "输出要求：直接输出润色后的系统提示词，不要附加解释说明。"
        ),
        "memory_strategy": "standard",
        "config": {"category": "prompt_engineering", "icon": "bulb", "is_prompt_polisher": True},
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
        # 重新查询以确保关系正确加载
        agent = await self._get_by_id(db, agent_id)
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
        # 重新查询以确保关系正确加载（特别是 llm_config_id 变更时）
        agent = await self._get_by_id(db, agent_id)
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
        # 重新查询以确保关系正确加载
        agent = await self._get_by_id(db, agent_id)
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
        # 重新查询以确保关系正确加载
        cloned = await self._get_by_id(db, new_id)
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

    async def polish_system_prompt(
        self, db: AsyncSession, raw_prompt: str
    ) -> dict[str, Any]:
        """使用提示词工程专家 Agent 润色系统提示词

        查找 config 中标记了 is_prompt_polisher 的官方 Agent，
        使用其 LLM 配置调用大模型进行润色。
        """
        # 查找提示词工程专家 Agent
        result = await db.execute(
            select(Agent)
            .options(selectinload(Agent.llm_config))
            .where(Agent.is_official == True)  # noqa: E712
        )
        agents = result.scalars().all()
        polisher = None
        for a in agents:
            if a.config and a.config.get("is_prompt_polisher"):
                polisher = a
                break

        if not polisher:
            raise NotFoundException("未找到提示词工程专家 Agent")

        if not polisher.llm_config:
            raise ValidationException("提示词工程专家 Agent 未关联 LLM 配置")

        # 构建 LLM 配置并调用
        from domain.llm_adapter import create_llm_from_config
        from common.utils.crypto import crypto_service

        cfg = polisher.llm_config
        config_dict = {
            "provider": cfg.provider,
            "model_name": cfg.model_name,
            "api_key": cfg.api_key or "",
            "api_base_url": cfg.api_base_url or "",
            "temperature": 0.3,  # 低温度保证输出稳定
            "max_tokens": 2048,
            "top_p": 0.9,
        }
        adapter = await create_llm_from_config(
            config_dict, decrypt_fn=crypto_service.decrypt
        )

        messages = [
            {"role": "system", "content": polisher.system_prompt},
            {"role": "user", "content": f"请润色以下系统提示词草案：\n\n{raw_prompt}"},
        ]
        polished = await adapter.invoke(messages)
        logger.info(
            f"提示词润色完成: polisher_agent={polisher.id}, "
            f"raw_len={len(raw_prompt)}, polished_len={len(polished)}"
        )
        return {
            "polished_prompt": polished.strip(),
            "fallback": adapter.is_fallback_used,
        }

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
        # 查询已存在的官方 Agent 名称集合
        existing_result = await db.execute(
            select(Agent.name).where(
                Agent.is_official == True  # noqa: E712
            )
        )
        existing_names = set(existing_result.scalars().all())

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

        created_count = 0
        skipped_count = 0

        # 增量创建：已存在的跳过，不存在的创建
        for agent_def in OFFICIAL_AGENTS:
            if agent_def["name"] in existing_names:
                skipped_count += 1
                continue

            # 提示词工程专家尝试匹配 deepseek 的 LLM 配置
            agent_cfg = default_cfg
            if agent_def["config"].get("is_prompt_polisher"):
                ds_result = await db.execute(
                    select(LLMConfig).where(
                        LLMConfig.model_name.like("%deepseek%")
                    ).limit(1)
                )
                ds_cfg = ds_result.scalar_one_or_none()
                if ds_cfg:
                    agent_cfg = ds_cfg

            agent_id = uuid.uuid4().hex
            agent = Agent(
                id=agent_id,
                name=agent_def["name"],
                description=agent_def["description"],
                system_prompt=agent_def["system_prompt"],
                llm_config_id=agent_cfg.id,
                status="created",
                is_official=True,
                temperature=0.7,
                max_tokens=4096,
                top_p=0.9,
                memory_strategy=agent_def["memory_strategy"],
                config=agent_def["config"],
            )
            db.add(agent)
            created_count += 1

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
            f"官方Agent初始化: 新增 {created_count} 个, 跳过 {skipped_count} 个"
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
