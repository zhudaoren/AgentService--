"""记忆加载服务

P1阶段直接读取数据库，不做远程调用。后续Phase可改造为远程调用 mem-svc。

职责:
  - load_short_term_memory: 从 messages 表加载最近 N 条历史消息（短期记忆）
  - load_long_term_memory: 从 long_term_memories 表加载 Agent 的长期记忆
  - build_system_prompt: 组合 system_prompt + 长期记忆 + 上下文压缩提示
  - 上下文压缩 (T1-027): 历史消息 token 总和 > 阈值时，只取最近 10 条
"""
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from common.logger import get_logger
from domain.models import Agent, LongTermMemory, Message

logger = get_logger(__name__)


# ── 配置常量 ──────────────────────────────────────────
DEFAULT_SHORT_TERM_LIMIT = 20        # 默认加载最近 20 条历史消息
CONTEXT_TOKEN_THRESHOLD = 4000       # 上下文 token 阈值（粗略估算）
COMPRESSED_KEEP_RECENT = 10          # 压缩后保留最近 N 条
CHARS_PER_TOKEN = 1.6                # 中文场景粗略：1 token ≈ 1.6 字符


class MemoryService:
    """记忆加载与系统提示组装"""

    # ── 短期记忆 ──────────────────────────────────────

    async def load_short_term_memory(
        self,
        db: AsyncSession,
        conversation_id: str,
        limit: int = DEFAULT_SHORT_TERM_LIMIT,
    ) -> list[Message]:
        """加载短期记忆：最近 N 条历史消息（按时间升序返回）

        Args:
            db: 数据库会话
            conversation_id: 会话 ID
            limit: 最多加载条数（取最近 limit 条）
        """
        # 先按时间倒序取最近 limit 条，再正序返回给 LLM
        stmt = (
            select(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.message_type.in_(["user", "assistant"]),
            )
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        result = await db.execute(stmt)
        rows = result.scalars().all()
        rows = list(reversed(rows))  # 时间升序
        logger.debug(
            f"加载短期记忆: conversation_id={conversation_id}, count={len(rows)}"
        )
        return rows

    # ── 长期记忆 ──────────────────────────────────────

    async def load_long_term_memory(
        self,
        db: AsyncSession,
        agent_id: str,
    ) -> Optional[LongTermMemory]:
        """加载 Agent 的长期记忆 (1:1 关系)"""
        stmt = select(LongTermMemory).where(
            LongTermMemory.agent_id == agent_id
        )
        result = await db.execute(stmt)
        memory = result.scalar_one_or_none()
        if memory is None:
            logger.debug(f"Agent 无长期记忆: agent_id={agent_id}")
        return memory

    # ── 系统提示组装 ──────────────────────────────────

    def build_system_prompt(
        self,
        base_prompt: str,
        long_term_memory: Optional[LongTermMemory] = None,
        compressed_summary: Optional[str] = None,
    ) -> str:
        """组合最终 system_prompt:
            base_prompt
              + 长期记忆（user_profile / environment_facts / experience）
              + 上下文压缩摘要提示（若有）
        """
        sections: list[str] = [base_prompt.strip()]

        if long_term_memory is not None:
            mem_parts: list[str] = []

            user_profile = long_term_memory.user_profile or {}
            if user_profile:
                mem_parts.append(
                    "【用户画像】\n" + self._format_dict(user_profile)
                )

            env_facts = long_term_memory.environment_facts or {}
            if env_facts:
                mem_parts.append(
                    "【环境事实】\n" + self._format_dict(env_facts)
                )

            experience = long_term_memory.experience or {}
            if experience:
                mem_parts.append(
                    "【历史经验】\n" + self._format_dict(experience)
                )

            if mem_parts:
                sections.append(
                    "以下是关于该用户的长期记忆，请在回答时参考：\n"
                    + "\n\n".join(mem_parts)
                )

        if compressed_summary:
            sections.append(
                "【近期对话摘要】\n" + compressed_summary.strip()
                + "\n（请基于以上摘要和后续对话继续与用户交流）"
            )

        return "\n\n".join(s for s in sections if s.strip())

    # ── 上下文压缩 (T1-027) ───────────────────────────

    def should_compress(
        self, messages: list[Message], max_tokens: int
    ) -> bool:
        """判断是否需要压缩：历史消息 token 总和 > max_tokens 的 80%"""
        total_chars = sum(len(m.content or "") for m in messages)
        approx_tokens = total_chars / CHARS_PER_TOKEN
        threshold = max_tokens * 0.8
        return approx_tokens > threshold

    def compress_messages(
        self, messages: list[Message]
    ) -> tuple[list[Message], Optional[str]]:
        """简单压缩：保留最近 N 条，并对前面部分生成摘要提示

        P1 简化实现：直接丢弃较早消息，附加提示词。
        高级 LLM 摘要压缩留待后续 Phase 实现。
        """
        if len(messages) <= COMPRESSED_KEEP_RECENT:
            return messages, None

        kept = messages[-COMPRESSED_KEEP_RECENT:]
        dropped = messages[:-COMPRESSED_KEEP_RECENT]
        summary = (
            f"（已省略较早的 {len(dropped)} 条对话历史，"
            "请基于以下最近消息继续与用户交流）"
        )
        logger.debug(
            f"上下文压缩: 丢弃 {len(dropped)} 条, 保留 {len(kept)} 条"
        )
        return kept, summary

    # ── 历史消息 → LLM 消息格式 ───────────────────────

    def to_llm_messages(
        self,
        system_prompt: str,
        history: list[Message],
        user_content: str,
    ) -> list[dict[str, str]]:
        """组装 LLM 调用所需的 messages 列表

        结构: [system] + history(user/assistant) + [user]
        """
        messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt}
        ]
        for m in history:
            role = "assistant" if m.message_type == "assistant" else "user"
            messages.append({"role": role, "content": m.content or ""})
        messages.append({"role": "user", "content": user_content})
        return messages

    # ── 内部工具 ──────────────────────────────────────

    @staticmethod
    def _format_dict(d: dict) -> str:
        """将字典格式化为 key: value 多行文本"""
        if not d:
            return ""
        lines = []
        for k, v in d.items():
            if isinstance(v, (dict, list)):
                import json
                v = json.dumps(v, ensure_ascii=False)
            lines.append(f"- {k}: {v}")
        return "\n".join(lines)


memory_service = MemoryService()
