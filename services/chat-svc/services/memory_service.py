"""记忆加载服务

P1阶段直接读取数据库，不做远程调用。后续Phase可改造为远程调用 mem-svc。

职责:
  - load_short_term_memory: 从 messages 表加载最近 N 条历史消息（短期记忆）
  - load_long_term_memory: 从 long_term_memories 表加载 Agent 的长期记忆
  - build_system_prompt: 组合 system_prompt + 长期记忆 + 上下文压缩提示
  - 上下文压缩 (T1-027): 历史消息 token 总和 > 阈值时，只取最近 10 条
"""
from __future__ import annotations

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
        user_attachments: Optional[list] = None,
    ) -> list[dict[str, Any]]:
        """组装 LLM 调用所需的 messages 列表

        结构: [system] + history(user/assistant) + [user]
        多模态规则:
          - 仅最新 user 消息（本轮 user_content + user_attachments 或历史最后一条 user）
            在有附件时使用数组 content: [{type:'text',...}, {type:'image_url',...}]
          - 历史 user 消息的附件降级为纯文本（附加一段提醒说明）
          - 音频附件在本轮做文本 fallback；视觉附件生成 image_url 项
        """
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt}
        ]

        # 找到历史中最后一条 user 的索引，用于决定是否对历史附件降级
        last_user_idx_in_history = -1
        for idx, m in enumerate(history):
            role = "assistant" if m.message_type == "assistant" else "user"
            if role == "user":
                last_user_idx_in_history = idx

        for idx, m in enumerate(history):
            role = "assistant" if m.message_type == "assistant" else "user"
            hist_attachments = getattr(m, "attachments", None)
            if role == "user" and hist_attachments:
                # 历史 user 的附件：仅最后一条历史 user 若未被本轮覆盖（实际不会，因为本轮是新 user）
                # 但为了安全，按规则统一降级纯文本（历史图片不注入），附加 fallback 说明
                text_content = m.content or ""
                note = self._attachments_fallback_note(hist_attachments)
                if note:
                    text_content = (text_content + "\n\n" + note).strip()
                messages.append({"role": role, "content": text_content})
            else:
                messages.append({"role": role, "content": m.content or ""})

        # 本轮最新 user 消息 → 可能使用数组内容
        if user_attachments:
            messages.append(self._build_user_message_with_attachments(
                user_content, user_attachments
            ))
        else:
            messages.append({"role": "user", "content": user_content})
        return messages

    # ── 多模态附件内部助手 ────────────────────────────

    @staticmethod
    def _attachments_fallback_note(attachments: list) -> str:
        """历史附件的纯文本 fallback 提醒（用于历史 user 消息降级）"""
        if not attachments:
            return ""
        image_names: list[str] = []
        audio_names: list[str] = []
        for a in attachments:
            if not isinstance(a, dict):
                continue
            t = str(a.get("type") or "").lower()
            name = a.get("name") or "(未命名)"
            if t.startswith("image") or t == "img":
                image_names.append(name)
            elif t.startswith("audio"):
                audio_names.append(name)
        parts: list[str] = []
        if image_names:
            parts.append(f"[用户当时还发送了图片附件：{', '.join(image_names)}，当前仅文本回顾]")
        if audio_names:
            parts.append(f"[用户当时还发送了音频附件：{', '.join(audio_names)}，当前仅文本回顾]")
        return "\n".join(parts)

    @staticmethod
    def _build_user_message_with_attachments(
        text_content: str, attachments: list
    ) -> dict[str, Any]:
        """构造最新 user 消息：附件数组注入 + 音频文本 fallback"""
        parts: list[dict[str, Any]] = []
        # 追加 text（含音频 fallback 说明）
        audio_fallbacks: list[str] = []
        image_items: list[dict[str, Any]] = []
        for a in attachments or []:
            if not isinstance(a, dict):
                continue
            t = str(a.get("type") or "").lower()
            name = a.get("name") or "(未命名)"
            if t.startswith("image") or t == "img":
                url = a.get("data_url") or a.get("url") or ""
                if not url:
                    continue
                image_items.append({
                    "type": "image_url",
                    "image_url": {"url": url, "detail": "auto"},
                })
            elif t.startswith("audio"):
                # 音频：文本 fallback（预留后续 input_audio 扩展点）
                audio_fallbacks.append(name)
            else:
                # 未知类型：追加一行说明
                audio_fallbacks.append(f"{name}(type={t or 'unknown'})")
        text = text_content or ""
        if audio_fallbacks:
            note = (
                f"\n\n[用户还发送了音频附件："
                f"\"{', '.join(audio_fallbacks)}\"]，当前会话音频支持取决于模型。"
            )
            text = (text + note).strip()
        parts.append({"type": "text", "text": text})
        parts.extend(image_items)
        return {"role": "user", "content": parts}

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
