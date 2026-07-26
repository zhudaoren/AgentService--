"""记忆业务服务

职责:
  - get_long_term_memory: 查询 Agent 的长期记忆，不存在返回空结构（不自动创建）
  - update_long_term_memory: 更新长期记忆，version+1（不存在则兜底创建，version=1）
  - get_short_term_memory: 从 messages 表查询会话历史消息（按时间升序）
  - clear_short_term_memory: 删除会话的所有消息（同步清除 Redis 缓存）
  - get_memory_summary: 返回记忆摘要（user_profile 关键偏好、experience 经验数量等）

长期记忆默认结构:
  {
      "user_profile": {},        # 用户偏好画像
      "environment_facts": {},   # 环境事实
      "experience": [],          # 经验教训列表
      "shared_items": []         # 共享记忆项
  }
"""
import uuid
from typing import Any, Optional

from sqlalchemy import select, func, delete
from sqlalchemy.ext.asyncio import AsyncSession

from common.exceptions import NotFoundException, ValidationException
from common.logger import get_logger
from common.schemas import (
    LongTermMemoryOut,
    LongTermMemoryUpdate,
    MessageOut,
)
from domain.models import Agent, Conversation, LongTermMemory, Message
from services.short_term_cache import short_term_cache

logger = get_logger(__name__)


# 长期记忆默认结构
DEFAULT_LONG_TERM_MEMORY: dict[str, Any] = {
    "user_profile": {},
    "environment_facts": {},
    "experience": [],
    "shared_items": [],
}


class MemoryService:
    """记忆业务服务"""

    # ── 长期记忆 ──────────────────────────────────────

    async def get_long_term_memory(
        self, db: AsyncSession, agent_id: str
    ) -> LongTermMemoryOut:
        """查询 Agent 的长期记忆，不存在则返回空结构（不自动创建）

        创建时机由 agent-svc 在创建 Agent 时负责。
        """
        await self._get_agent(db, agent_id)

        stmt = select(LongTermMemory).where(
            LongTermMemory.agent_id == agent_id
        )
        result = await db.execute(stmt)
        memory = result.scalar_one_or_none()

        if memory is None:
            logger.debug(
                f"Agent 无长期记忆(返回空结构): agent_id={agent_id}"
            )
            return LongTermMemoryOut(
                id=None,
                agent_id=agent_id,
                user_profile={},
                environment_facts={},
                experience=[],
                shared_items=[],
                version=0,
                created_at=None,
                updated_at=None,
            )

        return await self._to_out(memory)

    async def update_long_term_memory(
        self,
        db: AsyncSession,
        agent_id: str,
        payload: LongTermMemoryUpdate,
    ) -> LongTermMemoryOut:
        """更新长期记忆，version+1。若不存在则兜底创建（version=1）。

        正常情况下长期记忆应由 agent-svc 创建，这里兜底是为了应对数据不一致。
        """
        await self._get_agent(db, agent_id)

        stmt = select(LongTermMemory).where(
            LongTermMemory.agent_id == agent_id
        )
        result = await db.execute(stmt)
        memory = result.scalar_one_or_none()

        data = payload.model_dump(exclude_unset=True)

        if memory is None:
            # 兜底创建
            memory = LongTermMemory(
                id=uuid.uuid4().hex,
                agent_id=agent_id,
                user_profile=data.get("user_profile") or {},
                environment_facts=data.get("environment_facts") or {},
                experience=(
                    data.get("experience")
                    if data.get("experience") is not None
                    else []
                ),
                shared_items=(
                    data.get("shared_items")
                    if data.get("shared_items") is not None
                    else []
                ),
                version=1,
            )
            db.add(memory)
            await db.flush()
            logger.info(
                f"兜底创建长期记忆(更新时): agent_id={agent_id}, version=1"
            )
        else:
            for k, v in data.items():
                setattr(memory, k, v)
            memory.version = (memory.version or 0) + 1
            await db.flush()
            logger.info(
                f"更新长期记忆: agent_id={agent_id}, "
                f"version={memory.version}"
            )

        return await self._to_out(memory)

    # ── 短期记忆 ──────────────────────────────────────

    async def get_short_term_memory(
        self,
        db: AsyncSession,
        agent_id: str,
        conversation_id: str,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[MessageOut], int]:
        """获取会话短期记忆（消息历史，按时间升序）"""
        # 校验会话存在且属于该 Agent
        await self._get_conversation(db, conversation_id, agent_id=agent_id)

        # 总数
        total = (
            await db.execute(
                select(func.count(Message.id)).where(
                    Message.conversation_id == conversation_id
                )
            )
        ).scalar() or 0

        # 分页查询（按时间升序）
        stmt = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await db.execute(stmt)
        rows = result.scalars().all()
        items = [await self._msg_to_out(m) for m in rows]
        return items, total

    async def clear_short_term_memory(
        self, db: AsyncSession, agent_id: str, conversation_id: str
    ) -> int:
        """清空会话短期记忆（删除所有消息），返回删除条数。

        同时 best-effort 清除 Redis 短期记忆缓存（Phase2 准备）。
        """
        conv = await self._get_conversation(
            db, conversation_id, agent_id=agent_id
        )

        # 统计待删除条数
        count = (
            await db.execute(
                select(func.count(Message.id)).where(
                    Message.conversation_id == conversation_id
                )
            )
        ).scalar() or 0

        if count > 0:
            # 删除所有消息
            await db.execute(
                delete(Message).where(
                    Message.conversation_id == conversation_id
                )
            )
            # 重置会话消息计数
            conv.message_count = 0
            await db.flush()

        # best-effort 清除 Redis 缓存
        try:
            await short_term_cache.clear_cache(conversation_id)
        except Exception as e:
            logger.warning(
                f"清除短期记忆缓存失败(忽略): conversation_id={conversation_id}, "
                f"error={e}"
            )

        logger.info(
            f"清空短期记忆: agent_id={agent_id}, "
            f"conversation_id={conversation_id}, count={count}"
        )
        return count

    # ── 记忆摘要 ──────────────────────────────────────

    async def get_memory_summary(
        self, db: AsyncSession, agent_id: str
    ) -> dict[str, Any]:
        """返回记忆摘要（user_profile 关键偏好、experience 经验数量等）"""
        await self._get_agent(db, agent_id)

        stmt = select(LongTermMemory).where(
            LongTermMemory.agent_id == agent_id
        )
        result = await db.execute(stmt)
        memory = result.scalar_one_or_none()

        if memory is None:
            return {
                "agent_id": agent_id,
                "has_memory": False,
                "user_profile_keys": [],
                "preference_count": 0,
                "environment_facts_keys": [],
                "experience_count": 0,
                "shared_items_count": 0,
                "version": 0,
                "updated_at": None,
            }

        user_profile = memory.user_profile or {}
        environment_facts = memory.environment_facts or {}
        experience = (
            memory.experience if memory.experience is not None else []
        )
        shared_items = (
            memory.shared_items if memory.shared_items is not None else []
        )

        return {
            "agent_id": agent_id,
            "has_memory": True,
            "user_profile_keys": (
                list(user_profile.keys())
                if isinstance(user_profile, dict)
                else []
            ),
            "preference_count": self._count(user_profile),
            "environment_facts_keys": (
                list(environment_facts.keys())
                if isinstance(environment_facts, dict)
                else []
            ),
            "experience_count": self._count(experience),
            "shared_items_count": self._count(shared_items),
            "version": memory.version or 0,
            "updated_at": (
                memory.updated_at.isoformat()
                if memory.updated_at
                else None
            ),
        }

    # ── 内部工具 ──────────────────────────────────────

    @staticmethod
    def _count(v: Any) -> int:
        """统计 dict/list 的元素数量"""
        if isinstance(v, (list, dict)):
            return len(v)
        return 0

    async def _get_agent(self, db: AsyncSession, agent_id: str) -> Agent:
        result = await db.execute(
            select(Agent).where(Agent.id == agent_id)
        )
        agent = result.scalar_one_or_none()
        if agent is None:
            raise NotFoundException(f"Agent不存在: {agent_id}")
        return agent

    async def _get_conversation(
        self,
        db: AsyncSession,
        conv_id: str,
        agent_id: Optional[str] = None,
    ) -> Conversation:
        result = await db.execute(
            select(Conversation).where(Conversation.id == conv_id)
        )
        conv = result.scalar_one_or_none()
        if conv is None:
            raise NotFoundException(f"会话不存在: {conv_id}")
        if agent_id is not None and conv.agent_id != agent_id:
            raise ValidationException(
                f"会话不属于该Agent: conversation_id={conv_id}, "
                f"agent_id={agent_id}"
            )
        return conv

    async def _to_out(
        self, memory: LongTermMemory
    ) -> LongTermMemoryOut:
        return LongTermMemoryOut(
            id=memory.id,
            agent_id=memory.agent_id,
            user_profile=memory.user_profile or {},
            environment_facts=memory.environment_facts or {},
            experience=(
                memory.experience
                if memory.experience is not None
                else []
            ),
            shared_items=(
                memory.shared_items
                if memory.shared_items is not None
                else []
            ),
            version=memory.version or 0,
            created_at=memory.created_at,
            updated_at=memory.updated_at,
        )

    @staticmethod
    async def _msg_to_out(msg: Message) -> MessageOut:
        return MessageOut(
            id=msg.id,
            conversation_id=msg.conversation_id,
            message_type=msg.message_type,
            content=msg.content or "",
            tool_calls=msg.tool_calls,
            tool_results=msg.tool_results,
            token_count=msg.token_count or 0,
            created_at=msg.created_at,
        )


memory_service = MemoryService()
