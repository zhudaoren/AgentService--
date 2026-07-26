"""对话编排核心服务

职责:
  - create_conversation: 创建会话
  - get_conversations: 列表查询（支持 agent_id 筛选 + 分页）
  - get_conversation: 获取会话详情
  - delete_conversation: 删除会话（软删除：标记 deleted）
  - get_messages: 获取消息历史
  - chat: 流式编排核心
      1. 根据 conversation_id 找到会话和关联 Agent
      2. 加载 Agent 的 system_prompt
      3. 加载历史消息（短期记忆）
      4. 加载 Agent 的长期记忆，注入 system_prompt
      5. 调用 LLMAdapter.stream() 流式生成
      6. 用户消息和 AI 回复持久化到 messages 表
      7. 更新 conversation.message_count
  - chat_non_stream: 非流式版本
  - stop_generation: 停止正在进行的流式生成
"""
import asyncio
import json
import uuid
from typing import Any, AsyncIterator, Optional

from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from common.exceptions import (
    AppException,
    BadRequestException,
    LLMException,
    NotFoundException,
    ValidationException,
)
from common.logger import get_logger
from common.schemas import (
    ConversationCreate,
    ConversationOut,
    MessageOut,
)
from common.utils.crypto import crypto_service
from domain.models import Agent, Conversation, LLMConfig, Message
from domain.llm_adapter import LLMAdapter, create_llm_from_config
from infrastructure.db import AsyncSessionLocal

from services.memory_service import memory_service

logger = get_logger(__name__)


class ChatService:
    """对话编排核心服务"""

    def __init__(self) -> None:
        # 全局流式生成控制：{conversation_id: asyncio.Event}
        # set event → 流循环检测到后中断
        self._stop_events: dict[str, asyncio.Event] = {}

    # ── 会话 CRUD ────────────────────────────────────

    async def create_conversation(
        self, db: AsyncSession, payload: ConversationCreate
    ) -> ConversationOut:
        """创建会话"""
        # 校验 Agent 存在
        agent = await self._get_agent(db, payload.agent_id)
        if agent.status == "stopped":
            raise BadRequestException(
                f"Agent 已停止，无法创建会话: {payload.agent_id}"
            )

        conv_id = uuid.uuid4().hex
        conv = Conversation(
            id=conv_id,
            agent_id=payload.agent_id,
            user_id=payload.user_id or "default",
            title=payload.title or "新对话",
            status="active",
            message_count=0,
        )
        db.add(conv)
        await db.flush()
        logger.info(
            f"创建会话: id={conv_id}, agent_id={payload.agent_id}, "
            f"title={conv.title}"
        )
        return await self._conv_to_out(conv)

    async def get_conversations(
        self,
        db: AsyncSession,
        agent_id: Optional[str] = None,
        user_id: Optional[str] = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[ConversationOut], int]:
        """获取会话列表（支持 agent_id 筛选 + 分页）"""
        conditions = [Conversation.status != "deleted"]
        if agent_id is not None:
            conditions.append(Conversation.agent_id == agent_id)
        if user_id is not None:
            conditions.append(Conversation.user_id == user_id)

        # 总数
        count_stmt = select(func.count(Conversation.id))
        for cond in conditions:
            count_stmt = count_stmt.where(cond)
        total = (await db.execute(count_stmt)).scalar() or 0

        # 分页查询
        list_stmt = (
            select(Conversation)
            .order_by(Conversation.updated_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        for cond in conditions:
            list_stmt = list_stmt.where(cond)
        result = await db.execute(list_stmt)
        rows = result.scalars().all()
        items = [await self._conv_to_out(c) for c in rows]
        return items, total

    async def get_conversation(
        self, db: AsyncSession, conv_id: str
    ) -> ConversationOut:
        conv = await self._get_conversation(db, conv_id)
        return await self._conv_to_out(conv)

    async def delete_conversation(
        self, db: AsyncSession, conv_id: str
    ) -> None:
        """删除会话：软删除（标记为 deleted）

        若有正在进行的流式生成，先停止。
        """
        conv = await self._get_conversation(db, conv_id)
        # 若正在生成则停止
        self._stop_events.pop(conv_id, None)

        conv.status = "deleted"
        await db.flush()
        logger.info(f"删除会话(软删除): id={conv_id}")

    async def get_messages(
        self,
        db: AsyncSession,
        conv_id: str,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[MessageOut], int]:
        """获取会话消息历史（分页，按时间升序）"""
        # 校验会话存在
        await self._get_conversation(db, conv_id)

        # 总数
        total = (
            await db.execute(
                select(func.count(Message.id)).where(
                    Message.conversation_id == conv_id
                )
            )
        ).scalar() or 0

        # 分页（升序）
        stmt = (
            select(Message)
            .where(Message.conversation_id == conv_id)
            .order_by(Message.created_at.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        result = await db.execute(stmt)
        rows = result.scalars().all()
        items = [await self._msg_to_out(m) for m in rows]
        return items, total

    # ── 对话编排（流式） ─────────────────────────────

    async def chat(
        self,
        conversation_id: str,
        content: str,
    ) -> AsyncIterator[str]:
        """流式对话核心 - SSE 事件流生成器

        输出格式（每行以 \n\n 分隔）：
            data: {"content": "你", "done": false}\\n\\n
            data: {"content": "好", "done": false}\\n\\n
            data: {"content": "", "done": true, "message_id": "xxx"}\\n\\n
        """
        if not content or not content.strip():
            raise ValidationException("消息内容不能为空")

        # 1. 加载会话与 Agent
        async with AsyncSessionLocal() as session:
            conv = await self._get_conversation(session, conversation_id)
            agent = await self._get_agent(
                session, conv.agent_id, load_llm=True
            )
            llm_config = agent.llm_config
            if llm_config is None:
                raise NotFoundException(
                    f"Agent 关联的 LLM 配置不存在: agent_id={agent.id}"
                )

            # 2. 持久化用户消息（先保存，确保历史能取到）
            user_msg = await self._persist_message(
                session,
                conversation_id=conversation_id,
                message_type="user",
                content=content,
            )
            await session.commit()

            # 3. 加载短期记忆（不含刚保存的用户消息则需 +1 limit）
            history = await memory_service.load_short_term_memory(
                session, conversation_id, limit=20
            )
            # 排除刚保存的 user 消息（避免重复）
            history = [m for m in history if m.id != user_msg.id]

            # 4. 加载长期记忆
            long_term = await memory_service.load_long_term_memory(
                session, agent.id
            )

            # 5. 上下文压缩
            compressed_summary: Optional[str] = None
            if memory_service.should_compress(history, agent.max_tokens or 4096):
                history, compressed_summary = (
                    memory_service.compress_messages(history)
                )

            # 6. 组装 system_prompt
            system_prompt = memory_service.build_system_prompt(
                base_prompt=agent.system_prompt or "",
                long_term_memory=long_term,
                compressed_summary=compressed_summary,
            )

            # 7. 组装 LLM messages
            llm_messages = memory_service.to_llm_messages(
                system_prompt=system_prompt,
                history=history,
                user_content=content,
            )

            # 8. 构建 LLM 适配器
            config_dict = self._build_llm_config_dict(llm_config, agent)
            adapter = await create_llm_from_config(
                config_dict, decrypt_fn=crypto_service.decrypt
            )

        # 9. 注册停止事件
        stop_event = asyncio.Event()
        self._stop_events[conversation_id] = stop_event

        # 10. 流式生成并逐块 SSE 输出
        full_reply_parts: list[str] = []
        try:
            async for chunk in adapter.stream(llm_messages):
                # 检查是否被停止
                if stop_event.is_set():
                    logger.info(
                        f"流式生成被用户中断: conversation_id={conversation_id}"
                    )
                    yield self._sse({"content": "", "done": True, "stopped": True})
                    return
                if not chunk:
                    continue
                full_reply_parts.append(chunk)
                yield self._sse({"content": chunk, "done": False})
        except LLMException as e:
            logger.error(f"LLM 流式调用失败: {e.message}")
            yield self._sse(
                {"content": "", "done": True, "error": e.message}
            )
            # 持久化一条 error 消息
            await self._persist_with_session(
                conversation_id,
                message_type="error",
                content=f"[LLM 调用失败] {e.message}",
            )
            return
        except Exception as e:
            logger.error(f"流式生成异常: {e}", exc_info=True)
            yield self._sse(
                {"content": "", "done": True, "error": f"内部错误: {str(e)}"}
            )
            return
        finally:
            self._stop_events.pop(conversation_id, None)

        # 11. 持久化 AI 回复（一次保存完整内容）
        full_reply = "".join(full_reply_parts)
        ai_msg = await self._persist_with_session(
            conversation_id,
            message_type="assistant",
            content=full_reply,
        )

        # 12. 返回结束事件（带 message_id）
        yield self._sse(
            {"content": "", "done": True, "message_id": ai_msg.id}
        )

    # ── 对话编排（非流式） ───────────────────────────

    async def chat_non_stream(
        self,
        conversation_id: str,
        content: str,
    ) -> dict[str, Any]:
        """非流式对话 - 返回完整响应"""
        if not content or not content.strip():
            raise ValidationException("消息内容不能为空")

        async with AsyncSessionLocal() as session:
            conv = await self._get_conversation(session, conversation_id)
            agent = await self._get_agent(
                session, conv.agent_id, load_llm=True
            )
            llm_config = agent.llm_config
            if llm_config is None:
                raise NotFoundException(
                    f"Agent 关联的 LLM 配置不存在: agent_id={agent.id}"
                )

            # 用户消息持久化
            user_msg = await self._persist_message(
                session,
                conversation_id=conversation_id,
                message_type="user",
                content=content,
            )
            await session.commit()

            history = await memory_service.load_short_term_memory(
                session, conversation_id, limit=20
            )
            history = [m for m in history if m.id != user_msg.id]

            long_term = await memory_service.load_long_term_memory(
                session, agent.id
            )

            compressed_summary: Optional[str] = None
            if memory_service.should_compress(history, agent.max_tokens or 4096):
                history, compressed_summary = (
                    memory_service.compress_messages(history)
                )

            system_prompt = memory_service.build_system_prompt(
                base_prompt=agent.system_prompt or "",
                long_term_memory=long_term,
                compressed_summary=compressed_summary,
            )

            llm_messages = memory_service.to_llm_messages(
                system_prompt=system_prompt,
                history=history,
                user_content=content,
            )

            config_dict = self._build_llm_config_dict(llm_config, agent)
            adapter = await create_llm_from_config(
                config_dict, decrypt_fn=crypto_service.decrypt
            )

        # 调用 LLM（非流式）
        try:
            reply = await adapter.invoke(llm_messages)
            reply_text = reply if isinstance(reply, str) else str(reply)
        except LLMException as e:
            logger.error(f"LLM 非流式调用失败: {e.message}")
            await self._persist_with_session(
                conversation_id,
                message_type="error",
                content=f"[LLM 调用失败] {e.message}",
            )
            raise
        except Exception as e:
            logger.error(f"非流式生成异常: {e}", exc_info=True)
            raise AppException(f"内部错误: {str(e)}")

        # 持久化 AI 回复
        ai_msg = await self._persist_with_session(
            conversation_id,
            message_type="assistant",
            content=reply_text,
        )

        return {
            "message_id": ai_msg.id,
            "conversation_id": conversation_id,
            "content": reply_text,
            "role": "assistant",
        }

    # ── 停止生成 ──────────────────────────────────────

    def stop_generation(self, conversation_id: str) -> bool:
        """停止指定会话正在进行的流式生成

        Returns:
            True 表示已发出停止信号；False 表示该会话当前无运行中的流。
        """
        event = self._stop_events.get(conversation_id)
        if event is None:
            return False
        event.set()
        logger.info(f"已发送停止信号: conversation_id={conversation_id}")
        return True

    # ── 内部工具 ──────────────────────────────────────

    @staticmethod
    def _sse(payload: dict) -> str:
        """构造一条 SSE 事件"""
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    @staticmethod
    def _build_llm_config_dict(
        llm_config: LLMConfig, agent: Agent
    ) -> dict[str, Any]:
        """从 ORM 构建 LLMAdapter 所需 config dict

        Agent 上的 temperature/max_tokens/top_p 优先于 LLM 配置默认值。
        api_key 为加密后的密文，由 create_llm_from_config 解密。
        """
        default_params = llm_config.default_params or {}
        return {
            "provider": llm_config.provider,
            "model_name": llm_config.model_name,
            "api_key": llm_config.api_key or "",
            "api_base_url": llm_config.api_base_url or "",
            "temperature": agent.temperature
            if agent.temperature is not None
            else default_params.get("temperature", 0.7),
            "max_tokens": agent.max_tokens
            if agent.max_tokens
            else default_params.get("max_tokens", 4096),
            "top_p": agent.top_p
            if agent.top_p is not None
            else default_params.get("top_p", 0.9),
        }

    async def _get_conversation(
        self, db: AsyncSession, conv_id: str
    ) -> Conversation:
        stmt = select(Conversation).where(Conversation.id == conv_id)
        result = await db.execute(stmt)
        conv = result.scalar_one_or_none()
        if conv is None:
            raise NotFoundException(f"会话不存在: {conv_id}")
        if conv.status == "deleted":
            raise NotFoundException(f"会话已删除: {conv_id}")
        return conv

    async def _get_agent(
        self,
        db: AsyncSession,
        agent_id: str,
        load_llm: bool = False,
    ) -> Agent:
        stmt = select(Agent).where(Agent.id == agent_id)
        if load_llm:
            stmt = stmt.options(selectinload(Agent.llm_config))
        result = await db.execute(stmt)
        agent = result.scalar_one_or_none()
        if agent is None:
            raise NotFoundException(f"Agent 不存在: {agent_id}")
        return agent

    async def _persist_message(
        self,
        db: AsyncSession,
        conversation_id: str,
        message_type: str,
        content: str,
        token_count: int = 0,
    ) -> Message:
        """在当前 session 中持久化消息，并更新会话计数"""
        msg = Message(
            id=uuid.uuid4().hex,
            conversation_id=conversation_id,
            message_type=message_type,
            content=content,
            token_count=token_count or self._estimate_tokens(content),
        )
        db.add(msg)
        # 更新会话计数
        await db.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(message_count=Conversation.message_count + 1)
        )
        await db.flush()
        return msg

    async def _persist_with_session(
        self,
        conversation_id: str,
        message_type: str,
        content: str,
    ) -> Message:
        """使用独立 session 持久化消息（用于流式生成完成后）"""
        async with AsyncSessionLocal() as session:
            try:
                msg = await self._persist_message(
                    session,
                    conversation_id=conversation_id,
                    message_type=message_type,
                    content=content,
                )
                await session.commit()
                return msg
            except Exception:
                await session.rollback()
                raise

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """粗略估算 token 数：1 token ≈ 1.6 字符（中文场景）"""
        if not text:
            return 0
        return max(1, int(len(text) / 1.6))

    @staticmethod
    async def _conv_to_out(conv: Conversation) -> ConversationOut:
        return ConversationOut(
            id=conv.id,
            agent_id=conv.agent_id,
            user_id=conv.user_id or "",
            title=conv.title or "",
            status=conv.status,
            message_count=conv.message_count or 0,
            created_at=conv.created_at,
            updated_at=conv.updated_at,
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


chat_service = ChatService()
