"""记忆业务服务

职责:
  - get_long_term_memory: 查询 Agent 的长期记忆，不存在返回空结构（不自动创建）
  - update_long_term_memory: 更新长期记忆，version+1（不存在则兜底创建，version=1）
  - get_short_term_memory: 从 messages 表查询会话历史消息（按时间升序）
  - clear_short_term_memory: 删除会话的所有消息（同步清除 Redis 缓存）
  - get_memory_summary: 返回记忆摘要（user_profile 关键偏好、experience 经验数量等）
  - evaluate_and_update_long_term: 对话历史 -> LLM 判断 -> 结构化更新长期记忆
  - semantic_search_memory: 语义搜索记忆（P2 关键词匹配占位，Milvus 集成留空）

长期记忆默认结构:
  {
      "user_profile": {},        # 用户偏好画像
      "environment_facts": {},   # 环境事实
      "experience": [],          # 经验教训列表
      "shared_items": []         # 共享记忆项
  }
"""
from __future__ import annotations

import copy
import json
import uuid
from typing import Any, Optional, Union

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


# 记忆深化 Prompt 模板（硬编码，P2 阶段占位）
MEMORY_EVALUATE_PROMPT_TEMPLATE: str = (
    "你是一个记忆抽取助手。请阅读以下对话历史，判断是否有值得持久化到长期记忆的信息。\n"
    "\n"
    "Agent ID: {agent_id}\n"
    "对话历史:\n"
    "{conversation_text}\n"
    "\n"
    "请严格按以下 JSON 格式返回，不要输出任何其他文字：\n"
    "{{\n"
    '  "should_update": true/false,\n'
    '  "updates": [\n'
    "    {{\n"
    '      "segment": "user_profile" | "environment_facts" | "experience",\n'
    '      "action": "add" | "update" | "delete",\n'
    '      "key": "字段名或经验ID",\n'
    '      "value": "具体值(字符串/数字/对象/数组均可)",\n'
    '      "confidence": 0.0~1.0\n'
    "    }}\n"
    "  ]\n"
    "}}\n"
    "\n"
    "说明：\n"
    "- user_profile 存用户画像偏好(如用户喜欢的颜色、语言、工作职位等)，key 为字段名，value 为偏好值\n"
    "- environment_facts 存环境事实(如项目路径、系统版本、常用工具等)，key 为事实名，value 为事实值\n"
    "- experience 存经验教训(如踩过的坑、最佳实践)，key 建议为经验主题，value 为经验对象或字符串\n"
    "- 若没有任何值得持久化的信息，should_update=false, updates=[]\n"
)


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
            # 额外返回实际内容，供前端摘要弹窗直接展示
            "user_profile": user_profile,
            "environment_facts": environment_facts,
            "experience": experience if isinstance(experience, list) else [],
            "shared_items": shared_items if isinstance(shared_items, list) else [],
            "summary": "",  # 预留综合摘要字段，后续可由 LLM 生成
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

    # ── P2: 记忆深化评估 ──────────────────────────────

    async def evaluate_and_update_long_term(
        self,
        db: AsyncSession,
        agent_id: str,
        conversation_messages: list[dict],
        llm_adapter: Any = None,
    ) -> dict[str, Any]:
        """对话历史记忆深化评估。

        流程:
          1. 若 llm_adapter is None，直接跳过并返回 skipped 标记（P2 允许不接真实LLM）。
          2. 构造 Prompt，调用 LLM 返回结构化 JSON：
             {should_update, updates:[{segment,action,key,value,confidence}]}
          3. 解析 updates，按规则更新 long_term_memory 对应 segment，version+1。
          4. 返回更新统计。

        Args:
            db: 数据库会话
            agent_id: Agent ID
            conversation_messages: 对话历史消息 (list[dict])
            llm_adapter: LLM 适配器对象(需支持 .invoke(prompt)->str 或 .complete(prompt)->str)，None 时跳过

        Returns:
            dict: {skipped, reason?, should_update, applied_count, failed_count, updates_applied, version_before, version_after}
        """
        # 1. Agent 存在性校验
        await self._get_agent(db, agent_id)

        # 2. llm_adapter 为空 -> 直接跳过（P2 占位允许）
        if llm_adapter is None:
            logger.info(
                f"evaluate_and_update_long_term 跳过(无llm_adapter): "
                f"agent_id={agent_id}, messages={len(conversation_messages or [])}"
            )
            return {
                "skipped": True,
                "reason": "no_llm_adapter",
                "agent_id": agent_id,
                "messages_count": len(conversation_messages or []),
            }

        # 3. 构造对话文本 & Prompt
        conv_text = self._format_messages_for_llm(conversation_messages or [])
        prompt = MEMORY_EVALUATE_PROMPT_TEMPLATE.format(
            agent_id=agent_id,
            conversation_text=conv_text or "(空对话)",
        )

        # 4. 调用 LLM (兼容多种常见接口: .invoke / .complete / .chat)
        raw_output: Optional[str] = None
        try:
            if hasattr(llm_adapter, "invoke"):
                # invoke 接受 messages: list[dict]，包装成单条 user message
                raw_output = await self._safe_call_str(
                    llm_adapter.invoke,
                    [{"role": "user", "content": prompt}],
                )
            elif hasattr(llm_adapter, "complete"):
                raw_output = await self._safe_call_str(
                    llm_adapter.complete, prompt
                )
            elif hasattr(llm_adapter, "chat"):
                raw_output = await self._safe_call_str(
                    llm_adapter.chat, prompt
                )
            else:
                logger.warning(
                    f"llm_adapter 接口不兼容(未实现 invoke/complete/chat): "
                    f"type={type(llm_adapter).__name__}"
                )
                return {
                    "skipped": True,
                    "reason": "llm_adapter_interface_incompatible",
                    "agent_id": agent_id,
                }
        except Exception as e:
            logger.error(
                f"evaluate_and_update_long_term 调用LLM失败: "
                f"agent_id={agent_id}, error={e}"
            )
            return {
                "skipped": True,
                "reason": f"llm_call_error: {e}",
                "agent_id": agent_id,
            }

        # 5. 解析 JSON 结果（容忍 Markdown code fence）
        parsed = self._parse_llm_json_output(raw_output or "")
        if parsed is None:
            logger.warning(
                f"evaluate_and_update_long_term LLM返回无法解析为JSON: "
                f"agent_id={agent_id}, raw={raw_output[:200] if raw_output else ''}"
            )
            return {
                "skipped": True,
                "reason": "llm_output_not_json",
                "agent_id": agent_id,
                "raw_preview": (raw_output or "")[:500],
            }

        should_update = bool(parsed.get("should_update", False))
        updates_raw = parsed.get("updates") or []
        if not isinstance(updates_raw, list):
            updates_raw = []

        if not should_update or not updates_raw:
            return {
                "skipped": False,
                "should_update": False,
                "agent_id": agent_id,
                "applied_count": 0,
                "failed_count": 0,
                "updates_applied": [],
                "version_before": None,
                "version_after": None,
            }

        # 6. 拿到当前 long_term_memory 记录
        stmt = select(LongTermMemory).where(
            LongTermMemory.agent_id == agent_id
        )
        result = await db.execute(stmt)
        memory = result.scalar_one_or_none()

        created_fallback = False
        if memory is None:
            memory = LongTermMemory(
                id=uuid.uuid4().hex,
                agent_id=agent_id,
                user_profile={},
                environment_facts={},
                experience=[],
                shared_items=[],
                version=1,
            )
            db.add(memory)
            await db.flush()
            created_fallback = True
            logger.info(
                f"evaluate_and_update_long_term 兜底创建长期记忆: "
                f"agent_id={agent_id}"
            )

        version_before = (memory.version or 0) if not created_fallback else 0

        # 7. 应用每个 update
        user_profile = copy.deepcopy(memory.user_profile or {})
        environment_facts = copy.deepcopy(memory.environment_facts or {})
        experience = copy.deepcopy(
            memory.experience if memory.experience is not None else []
        )

        applied: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []

        for idx, upd in enumerate(updates_raw):
            if not isinstance(upd, dict):
                failed.append({"index": idx, "error": "not_dict"})
                continue
            segment = upd.get("segment")
            action = upd.get("action")
            key = upd.get("key")
            value = upd.get("value")
            confidence = upd.get("confidence", 0.0)

            # 基础校验
            if segment not in ("user_profile", "environment_facts", "experience"):
                failed.append(
                    {"index": idx, "key": key, "error": f"invalid_segment:{segment}"}
                )
                continue
            if action not in ("add", "update", "delete"):
                failed.append(
                    {"index": idx, "key": key, "error": f"invalid_action:{action}"}
                )
                continue
            if not isinstance(key, str) or not key:
                failed.append({"index": idx, "error": "invalid_key"})
                continue

            ok = self._apply_segment_update(
                segment, action, key, value,
                user_profile=user_profile,
                environment_facts=environment_facts,
                experience=experience,
            )
            if ok:
                applied.append(
                    {
                        "segment": segment,
                        "action": action,
                        "key": key,
                        "confidence": confidence,
                    }
                )
            else:
                failed.append(
                    {
                        "index": idx,
                        "segment": segment,
                        "action": action,
                        "key": key,
                        "error": "apply_failed",
                    }
                )

        # 8. 写回 DB（只有至少 applied 一个才 +version）
        if applied:
            memory.user_profile = user_profile
            memory.environment_facts = environment_facts
            memory.experience = experience
            if created_fallback:
                memory.version = 1
            else:
                memory.version = (memory.version or 0) + 1
            await db.flush()
            logger.info(
                f"evaluate_and_update_long_term 应用记忆更新: "
                f"agent_id={agent_id}, applied={len(applied)}, "
                f"failed={len(failed)}, version={memory.version}"
            )
        else:
            logger.info(
                f"evaluate_and_update_long_term 无可应用更新: "
                f"agent_id={agent_id}, failed={len(failed)}"
            )

        version_after = memory.version or 0

        return {
            "skipped": False,
            "should_update": should_update,
            "agent_id": agent_id,
            "applied_count": len(applied),
            "failed_count": len(failed),
            "updates_applied": applied,
            "updates_failed": failed,
            "version_before": version_before,
            "version_after": version_after,
            "created_memory": created_fallback,
        }

    # ── P2: 语义搜索记忆 ──────────────────────────────

    async def semantic_search_memory(
        self,
        db: AsyncSession,
        agent_id: str,
        query: str,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """语义搜索相关记忆项。

        P2 占位实现:
          - Milvus 向量库未集成，打印日志 "Milvus not available"
          - 回退实现: 从 long_term_memory 3 个 segment 中做关键词包含匹配，
            返回带 confidence（匹配度 0.0~1.0）打分的前 top_k 项。

        Args:
            db: 数据库会话
            agent_id: Agent ID
            query: 查询关键词
            top_k: 返回条数上限

        Returns:
            list[dict]: 每项 {segment, key, value, confidence, source}
        """
        # Milvus 集成占位（Phase3）
        logger.info(
            f"semantic_search_memory: Milvus not available, "
            f"fallback to keyword match (agent_id={agent_id}, query={query!r})"
        )

        # Agent 存在性校验
        await self._get_agent(db, agent_id)

        # 拿到长期记忆
        stmt = select(LongTermMemory).where(
            LongTermMemory.agent_id == agent_id
        )
        result = await db.execute(stmt)
        memory = result.scalar_one_or_none()

        query_norm = (query or "").strip().lower()
        if not query_norm:
            return []

        if memory is None:
            return []

        user_profile = memory.user_profile or {}
        environment_facts = memory.environment_facts or {}
        experience = memory.experience if memory.experience is not None else []

        candidates: list[dict[str, Any]] = []

        # user_profile: dict -> 每个 key/value 作为候选
        if isinstance(user_profile, dict):
            for k, v in user_profile.items():
                candidates.append(
                    {
                        "segment": "user_profile",
                        "key": k,
                        "value": v,
                        "source": "user_profile",
                    }
                )

        # environment_facts: dict -> 每个 key/value 作为候选
        if isinstance(environment_facts, dict):
            for k, v in environment_facts.items():
                candidates.append(
                    {
                        "segment": "environment_facts",
                        "key": k,
                        "value": v,
                        "source": "environment_facts",
                    }
                )

        # experience: list -> 每项作为候选
        if isinstance(experience, list):
            for i, item in enumerate(experience):
                item_key: str = ""
                item_value: Any = item
                if isinstance(item, dict):
                    item_key = str(item.get("key") or item.get("id") or item.get("title") or f"exp_{i}")
                    item_value = item.get("value", item)
                else:
                    item_key = f"exp_{i}"
                candidates.append(
                    {
                        "segment": "experience",
                        "key": item_key,
                        "value": item_value,
                        "source": "experience",
                    }
                )

        # 关键词匹配打分
        scored: list[tuple[float, int, dict[str, Any]]] = []
        order = 0
        for cand in candidates:
            key_str = str(cand.get("key") or "").lower()
            value_str = self._to_string_for_match(cand.get("value")).lower()
            combined = f"{key_str} {value_str}"
            if query_norm not in combined:
                continue
            # 简单打分: 关键词出现在key -> 高分; 完全匹配 -> 更高
            score = 0.0
            if query_norm == key_str:
                score = 1.0
            elif query_norm in key_str and query_norm in value_str:
                score = 0.9
            elif query_norm in key_str:
                score = 0.8
            elif combined.count(query_norm) >= 3:
                score = 0.7
            elif combined.count(query_norm) >= 2:
                score = 0.6
            else:
                score = 0.4
            scored.append((score, order, cand))
            order += 1

        # 按分数降序、原序保持稳定，取 top_k
        scored.sort(key=lambda x: (-x[0], x[1]))
        if top_k is None or top_k <= 0:
            top_k = 5
        top_items = scored[:top_k]

        result_list: list[dict[str, Any]] = []
        for score, _, cand in top_items:
            result_list.append(
                {
                    "segment": cand["segment"],
                    "key": cand["key"],
                    "value": cand["value"],
                    "confidence": round(score, 4),
                    "source": cand["source"],
                }
            )
        return result_list

    # ── P2: 内部工具（供记忆深化 & 语义搜索使用） ─────

    @staticmethod
    def _format_messages_for_llm(messages: list[dict]) -> str:
        """将对话消息列表格式化为 LLM 可读的文本"""
        if not messages:
            return ""
        lines: list[str] = []
        for i, m in enumerate(messages):
            if not isinstance(m, dict):
                continue
            role = str(m.get("role") or m.get("message_type") or "unknown").strip()
            content = m.get("content")
            if isinstance(content, (dict, list)):
                try:
                    content_str = json.dumps(content, ensure_ascii=False)
                except Exception:
                    content_str = str(content)
            else:
                content_str = "" if content is None else str(content)
            lines.append(f"[{i+1}] {role}: {content_str}")
        return "\n".join(lines)

    @staticmethod
    async def _safe_call_str(fn: Any, *args: Any, **kwargs: Any) -> str:
        """兼容同步/异步调用，强制返回字符串"""
        import inspect

        if inspect.iscoroutinefunction(fn) or inspect.isasyncgenfunction(fn):
            result = await fn(*args, **kwargs)
        else:
            result = fn(*args, **kwargs)
        if result is None:
            return ""
        if isinstance(result, str):
            return result
        # 兼容 {"content": "xxx"} / {"choices": [...]} 等常见结构
        if isinstance(result, dict):
            if isinstance(result.get("content"), str):
                return result["content"]
            choices = result.get("choices")
            if isinstance(choices, list) and choices:
                c0 = choices[0]
                if isinstance(c0, dict):
                    msg = c0.get("message")
                    if isinstance(msg, dict) and isinstance(msg.get("content"), str):
                        return msg["content"]
                    if isinstance(c0.get("text"), str):
                        return c0["text"]
        try:
            return str(result)
        except Exception:
            return ""

    @staticmethod
    def _parse_llm_json_output(raw: str) -> Optional[dict[str, Any]]:
        """从 LLM 输出中提取 JSON 对象。

        容忍: Markdown code fence (```json ... ```), 前后多余文本。
        """
        if not raw:
            return None
        text = raw.strip()

        # 1) 先尝试剥离 code fence
        fence_start = text.find("```")
        if fence_start >= 0:
            # 找到 fence 结束
            rest = text[fence_start + 3 :]
            # 跳过可选的 'json\n' 标识
            if rest.lower().startswith("json"):
                rest = rest[4:]
            fence_end = rest.find("```")
            if fence_end >= 0:
                text = rest[:fence_end].strip()
            else:
                text = rest.strip()

        # 2) 尝试直接 parse
        try:
            return json.loads(text)
        except Exception:
            pass

        # 3) 尝试找第一个 '{' 到最后一个 '}' 区间
        first = text.find("{")
        last = text.rfind("}")
        if first >= 0 and last > first:
            sub = text[first : last + 1]
            try:
                return json.loads(sub)
            except Exception:
                pass

        # 4) 尝试找第一个 '[' 到最后一个 ']'（虽然根应该是 object，兜底用）
        first_arr = text.find("[")
        last_arr = text.rfind("]")
        if first_arr >= 0 and last_arr > first_arr:
            try:
                arr = json.loads(text[first_arr : last_arr + 1])
                return {"updates": arr, "should_update": bool(arr)}
            except Exception:
                pass
        return None

    @staticmethod
    def _apply_segment_update(
        segment: str,
        action: str,
        key: str,
        value: Any,
        user_profile: dict,
        environment_facts: dict,
        experience: list,
    ) -> bool:
        """应用单条 segment 更新。返回 True 表示成功。"""
        # user_profile / environment_facts: 都是 dict 操作
        if segment == "user_profile" or segment == "environment_facts":
            target: dict = (
                user_profile if segment == "user_profile" else environment_facts
            )
            if action == "add" or action == "update":
                target[key] = value
                return True
            elif action == "delete":
                if key in target:
                    del target[key]
                return True
            return False

        # experience: list 操作，按 key 匹配(经验项 id/主题/标题)
        if segment == "experience":
            # 尝试按 key 找到匹配项
            match_index: Optional[int] = None
            matchable: list[tuple[int, Any]] = []
            for i, item in enumerate(experience):
                k_val: Any = None
                if isinstance(item, dict):
                    k_val = (
                        item.get("key")
                        or item.get("id")
                        or item.get("title")
                        or item.get("name")
                    )
                else:
                    k_val = item
                if k_val is not None and str(k_val) == str(key):
                    match_index = i
                    break
                matchable.append((i, k_val))

            if action == "add":
                # add: 如果 key 已存在则 update，否则追加
                if match_index is not None:
                    experience[match_index] = value
                else:
                    if isinstance(value, dict) and "key" not in value and "id" not in value:
                        item_with_key = copy.deepcopy(value) if isinstance(value, dict) else {"value": value}
                        if isinstance(item_with_key, dict):
                            item_with_key.setdefault("key", key)
                        experience.append(item_with_key)
                    else:
                        experience.append(value)
                return True
            elif action == "update":
                if match_index is not None:
                    experience[match_index] = value
                    return True
                # key 不存在 -> 兜底追加
                if isinstance(value, dict) and "key" not in value and "id" not in value:
                    item_with_key = copy.deepcopy(value) if isinstance(value, dict) else {"value": value}
                    if isinstance(item_with_key, dict):
                        item_with_key.setdefault("key", key)
                    experience.append(item_with_key)
                else:
                    experience.append(value)
                return True
            elif action == "delete":
                if match_index is not None:
                    del experience[match_index]
                return True
            return False
        return False

    @staticmethod
    def _to_string_for_match(v: Any) -> str:
        """将任意 value 转成字符串用于关键词匹配"""
        if v is None:
            return ""
        if isinstance(v, str):
            return v
        if isinstance(v, (int, float, bool)):
            return str(v)
        try:
            return json.dumps(v, ensure_ascii=False)
        except Exception:
            try:
                return str(v)
            except Exception:
                return ""


memory_service = MemoryService()
