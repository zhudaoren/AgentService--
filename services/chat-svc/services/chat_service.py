"""对话编排核心服务

职责:
  - create_conversation: 创建会话
  - get_conversations: 列表查询（支持 agent_id 筛选 + 分页）
  - get_conversation: 获取会话详情
  - delete_conversation: 删除会话（软删除：标记 deleted）
  - get_messages: 获取消息历史
  - chat: 流式编排核心 (P2: ReAct 集成工具调用)
      1. 根据 conversation_id 找到会话和关联 Agent
      2. 加载 Agent 的 system_prompt
      3. 加载历史消息（短期记忆）
      4. 加载 Agent 的长期记忆，注入 system_prompt
      5. (P2) 调用 agent-svc 获取 tools-summary: MCP tools + Skill Level0
      6. (P2) ReAct 主循环：LLM → tool_calls? → 调用tool-svc → observation → LLM
      7. 调用 LLMAdapter.stream() 流式生成
      8. 用户消息和 AI 回复持久化到 messages 表
      9. 更新 conversation.message_count
  - chat_non_stream: 非流式版本
  - stop_generation: 停止正在进行的流式生成
  - (P2) regenerate_last_message: 重新生成最后一条 assistant 消息
"""
from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from typing import Any, AsyncIterator, Optional

from sqlalchemy import select, func, update, and_
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
from domain.skill_manager import SkillManager
from infrastructure.db import AsyncSessionLocal

from services.memory_service import memory_service

try:
    import httpx  # type: ignore
    _HTTPX_AVAILABLE = True
except Exception:  # pragma: no cover - httpx 缺失的降级
    httpx = None  # type: ignore
    _HTTPX_AVAILABLE = False

logger = get_logger(__name__)


class ChatService:
    """对话编排核心服务 (P2: ReAct + Tool Calling + Regenerate)"""

    TOOL_SVC_BASE = "http://localhost:8003"
    AGENT_SVC_BASE = "http://localhost:8001"
    DEFAULT_MAX_REACT_ITERATIONS = 8

    def __init__(self) -> None:
        # 全局流式生成控制：{conversation_id: asyncio.Event}
        # set event → 流循环检测到后中断
        self._stop_events: dict[str, asyncio.Event] = {}
        # HTTP 客户端（懒创建）
        self._tool_http_client: Any = None
        self._agent_http_client: Any = None
        # ReAct 最大迭代轮数
        self._max_react_iterations: int = self.DEFAULT_MAX_REACT_ITERATIONS

    # ── HTTP 客户端懒加载 ────────────────────────────

    def _get_tool_http_client(self) -> Any:
        if not _HTTPX_AVAILABLE:
            return None
        if self._tool_http_client is None:
            self._tool_http_client = httpx.AsyncClient(timeout=120.0)
        return self._tool_http_client

    def _get_agent_http_client(self) -> Any:
        if not _HTTPX_AVAILABLE:
            return None
        if self._agent_http_client is None:
            self._agent_http_client = httpx.AsyncClient(timeout=10.0)
        return self._agent_http_client

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
        return await self._conv_to_out(conv, agent.name or "")

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

        # 批量查询关联的 Agent 名称（避免 N+1 查询）
        agent_ids = {r.agent_id for r in rows if r.agent_id}
        agent_name_map: dict[str, str] = {}
        if agent_ids:
            agent_stmt = select(Agent.id, Agent.name).where(Agent.id.in_(agent_ids))
            agent_result = await db.execute(agent_stmt)
            for aid, aname in agent_result.all():
                agent_name_map[aid] = aname or ""

        items = [await self._conv_to_out(c, agent_name_map.get(c.agent_id, "")) for c in rows]
        return items, total

    async def get_conversation(
        self, db: AsyncSession, conv_id: str
    ) -> ConversationOut:
        conv = await self._get_conversation(db, conv_id)
        # 查询关联的 Agent 名称
        agent_name = ""
        if conv.agent_id:
            agent = await self._get_agent(db, conv.agent_id)
            agent_name = agent.name if agent else ""
        return await self._conv_to_out(conv, agent_name)

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

    # ── 查询某条消息下的工具调用 ──────────────────────

    async def get_message_tool_calls(
        self, db: AsyncSession, conv_id: str, message_id: str
    ) -> list[dict]:
        """查询某条消息下的工具调用（从 tool_calls / tool_results 字段返回 list）"""
        await self._get_conversation(db, conv_id)
        stmt = select(Message).where(
            Message.id == message_id,
            Message.conversation_id == conv_id,
        )
        result = await db.execute(stmt)
        msg = result.scalar_one_or_none()
        if not msg:
            raise NotFoundException(f"消息不存在: {message_id}")
        calls = []
        if msg.tool_calls and isinstance(msg.tool_calls, dict):
            # 兼容：tool_calls 可能是 {"calls": [...]} 或直接 list
            if "calls" in msg.tool_calls and isinstance(msg.tool_calls["calls"], list):
                calls = msg.tool_calls["calls"]
            elif isinstance(msg.tool_calls, list):
                calls = msg.tool_calls
        elif msg.tool_calls and isinstance(msg.tool_calls, list):
            calls = msg.tool_calls
        # 如果是 assistant 消息且 tool_calls 空，则查其后 tool_call/tool_result 消息作为补充
        if not calls and msg.message_type in ("assistant", "tool_call", "tool_result"):
            # 查同一 conversation 下，created_at >= 当前消息且按时间排序的 tool_* 消息
            sub_stmt = (
                select(Message)
                .where(
                    Message.conversation_id == conv_id,
                    Message.created_at >= msg.created_at,
                    Message.message_type.in_(["tool_call", "tool_result"]),
                )
                .order_by(Message.created_at.asc())
            )
            sub_rows = (await db.execute(sub_stmt)).scalars().all()
            for sm in sub_rows:
                entry = {
                    "message_id": sm.id,
                    "message_type": sm.message_type,
                    "content": sm.content or "",
                    "tool_calls": sm.tool_calls,
                    "tool_results": sm.tool_results,
                    "created_at": sm.created_at.isoformat() if sm.created_at else None,
                }
                calls.append(entry)
        return calls

    # ── 对话编排（流式 + ReAct） ─────────────────────

    async def chat(
        self,
        conversation_id: str,
        content: str,
        workflow_mode: Optional[str] = None,
    ) -> AsyncIterator[str]:
        """流式对话核心 (P2: ReAct + Plan-and-Execute + Tool Calling) - SSE 事件流生成器

        输出 SSE 事件（每条以 \n\n 分隔）:
            event: message\ndata: {"role": "...", "content": "..."}\n\n
            event: tool_call\ndata: {"index":i,"tool_name","status","result","error"}\n\n
            event: skills_available\ndata: {"skills": [...], "total": N}
            event: plan_generated\ndata: {"plan": [...], "strategy": "..."}
            event: done\ndata: {"message_id":"...","fallback":...}\n\n
        """
        if not content or not content.strip():
            raise ValidationException("消息内容不能为空")

        # 1. 加载会话与 Agent + LLM 配置
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

            # 工作模式优先级：请求参数 > Agent 设置 > 默认 hybrid
            agent_workflow = getattr(agent, "workflow_mode", None)
            effective_mode = (
                workflow_mode
                or agent_workflow
                or "hybrid"
            )
            if effective_mode not in {"react", "plan_and_execute", "hybrid"}:
                effective_mode = "hybrid"
            # 若无工具/技能绑定，则强制 react（因为 plan 阶段无工具可执行，无意义）
            has_tools_or_skills = bool(True)  # 默认先设，后面覆盖

            # 2. 持久化用户消息
            user_msg = await self._persist_message(
                session,
                conversation_id=conversation_id,
                message_type="user",
                content=content,
            )
            await session.commit()

            agent_id = agent.id

            # 3. 加载短期记忆（不含刚保存的用户消息）
            history = await memory_service.load_short_term_memory(
                session, conversation_id, limit=20
            )
            history = [m for m in history if m.id != user_msg.id]

            # 4. 加载长期记忆
            long_term = await memory_service.load_long_term_memory(
                session, agent.id
            )

            # 5. (P2) 加载 Agent 工具汇总 (MCP + Skills) - HTTP 调用 agent-svc，失败降级为空
            tools_summary = await self._fetch_tools_summary_http(agent_id)
            mcp_services = tools_summary.get("mcp_services", []) if tools_summary else []
            skills = tools_summary.get("skills", []) if tools_summary else []
            enable_react = bool(mcp_services or skills)
            has_tools_or_skills = enable_react

            # 5.1 根据工作模式决定策略：Hybrid 时做轻量「任务复杂度评估」
            #  - 简单查询 + 无工具 → react（实际上就是纯对话）
            #  - 多步骤 + 有工具 + 关键词:调研/分析/方案/对比/规划 → plan_and_execute
            #  - 其余 → react
            strategy_mode = effective_mode
            if strategy_mode == "hybrid":
                strategy_mode = self._select_workflow_strategy(content, mcp_services, skills)
            if strategy_mode == "plan_and_execute" and not has_tools_or_skills:
                strategy_mode = "react"
            # 发送工作模式事件供前端显示（可选的轻量事件）
            yield self._sse_event("workflow_mode", {
                "mode": strategy_mode,
                "effective_from": effective_mode,
                "description": {
                    "react": "边思考边行动（ReAct）",
                    "plan_and_execute": "先计划后执行（Plan-and-Execute）",
                    "hybrid": "混合模式（自适应）",
                }.get(strategy_mode, strategy_mode),
            })

            # 6. 上下文压缩
            compressed_summary: Optional[str] = None
            if memory_service.should_compress(history, agent.max_tokens or 4096):
                history, compressed_summary = (
                    memory_service.compress_messages(history)
                )

            # 7. 组装 system_prompt（含 Skills Level0 + MCP 工具列表）
            system_prompt = self._build_system_prompt_with_tools(
                base_prompt=agent.system_prompt or "",
                long_term_memory=long_term,
                compressed_summary=compressed_summary,
                mcp_services=mcp_services,
                skills=skills,
            )

            # 8. 构建 LLM 适配器
            config_dict = self._build_llm_config_dict(llm_config, agent)
            adapter = await create_llm_from_config(
                config_dict, decrypt_fn=crypto_service.decrypt
            )

            # 9. 组装初始 LLM messages（P2 ReAct 模式下会包含 tool_call/tool_result）
            llm_messages: list[dict] = memory_service.to_llm_messages(
                system_prompt=system_prompt,
                history=history,
                user_content=content,
            )

            # 10. 构建 LLM 可用的 tool_defs（从 MCP tools 生成）
            llm_tool_defs = self._build_llm_tool_definitions(mcp_services)

            # 10.1 发送可用 Skills 列表事件（前端可展示"使用了哪些技能"）
            if skills:
                skills_summary = [
                    {
                        "name": s.get("name", ""),
                        "description": s.get("description", ""),
                        "category": s.get("category", ""),
                    }
                    for s in skills
                ]
                yield self._sse_event("skills_available", {
                    "skills": skills_summary,
                    "total": len(skills_summary),
                })

        # 11. 注册停止事件
        stop_event = asyncio.Event()
        self._stop_events[conversation_id] = stop_event

        # 12. (P2) ReAct 主循环
        react_messages_for_persist: list[Message] = []
        final_assistant_text = ""
        final_assistant_tool_calls: list[dict] = []
        fallback_used = False
        iteration_took = 0
        # 累积所有中间轮的思考内容（推理过程），最终轮的 assistant_text 作为最终回答
        final_thinking_content: str = ""

        try:
            # ── Plan-and-Execute：在进入 ReAct 主循环前，先产出一份执行计划 ──
            plan_steps: list[dict] = []
            plan_for_context: str = ""  # 在外层初始化，避免未定义变量引用
            if strategy_mode == "plan_and_execute" and has_tools_or_skills:
                import time as _time
                plan_start = _time.time()
                plan_raw = await self._generate_initial_plan(
                    adapter=adapter,
                    user_content=content,
                    history=history,
                    system_prompt=system_prompt,
                    mcp_services=mcp_services,
                    skills=skills,
                )
                plan_steps = plan_raw.get("steps", []) or []
                plan_duration = int((_time.time() - plan_start) * 1000)
                logger.info(
                    f"[DEBUG] Plan-and-Execute 生成计划: {len(plan_steps)} steps, "
                    f"duration_ms={plan_duration}, summary={plan_raw.get('summary','')[:80]}"
                )
                yield self._sse_event("plan_generated", {
                    "summary": plan_raw.get("summary", ""),
                    "steps": plan_steps,
                    "mode": "plan_and_execute",
                    "duration_ms": plan_duration,
                })
                # 将计划注入 system_prompt 的上下文里，供后续 ReAct 循环参考
                if plan_steps:
                    plan_for_context = "\n".join(
                        f"- 步骤 {i+1}: {s.get('title','')} - {s.get('description','')}"
                        for i, s in enumerate(plan_steps)
                    )
                    plan_ctx_msg = (
                        f"[任务执行计划（Plan）]\n{plan_for_context}\n"
                        f"请你按照上面的步骤依次执行，执行时通过工具调用获取信息，最终输出完整回答。"
                        f"如果某个步骤执行失败或信息不足，可灵活调整，但总体要围绕计划完成。"
                    )
                    # 以 assistant 上下文提示的方式插入到最后一条消息前（作为系统附带的用户提示）
                    llm_messages.append({
                        "role": "user",
                        "content": plan_ctx_msg,
                    })

            for iteration in range(self._max_react_iterations):
                iteration_took = iteration + 1
                # 检查中断
                if stop_event.is_set():
                    logger.info(f"流式生成被用户中断(ReAct#{iteration}): conv={conversation_id}")
                    yield self._sse_event("message", {
                        "role": "assistant", "content": "",
                    })
                    yield self._sse_event("done", {
                        "content": "", "stopped": True,
                    })
                    return

                # Step1: 调用 LLM（流式），收集完整文本和 tool_calls
                full_text_parts: list[str] = []
                detected_tool_calls: list[dict] = []
                # 判断本轮是否可能涉及工具调用（决定流式内容是推送为 thinking 还是 message）
                use_function_calling = (
                    enable_react and llm_tool_defs
                    and adapter.provider in ("openai", "deepseek", "moonshot", "kimi", "zhipu", "siliconflow", "glm")
                )
                use_text_react = enable_react and llm_tool_defs and not use_function_calling
                # 只有当有MCP工具绑定时才展示思考过程
                # 无工具绑定时（仅Skills），直接流式输出为最终回答
                stream_as_thinking = bool(llm_tool_defs)
                logger.info(f"[DEBUG] ReAct#{iteration} setup: enable_react={enable_react}, llm_tool_defs={len(llm_tool_defs) if llm_tool_defs else 0}, provider={adapter.provider}, use_function_calling={use_function_calling}, use_text_react={use_text_react}, stream_as_thinking={stream_as_thinking}")
                thinking_start_ts: Optional[float] = None
                try:
                    if use_function_calling:
                        # Function calling 模式：真正流式 + 实时推送
                        if stream_as_thinking:
                            thinking_start_ts = time.time()
                            yield self._sse_event("thinking_start", {
                                "iteration": iteration,
                            })
                        try:
                            async for chunk in self._stream_llm_with_tools(
                                adapter, llm_messages, llm_tool_defs,
                            ):
                                if stop_event.is_set():
                                    break
                                if isinstance(chunk, tuple) and len(chunk) == 2:
                                    typ, val = chunk
                                    if typ == "content":
                                        if val:
                                            full_text_parts.append(val)
                                            # 实时推送流式内容（thinking 或 message）
                                            if stream_as_thinking:
                                                yield self._sse_event("thinking", {
                                                    "content": val,
                                                    "iteration": iteration,
                                                    "streaming": True,
                                                })
                                            else:
                                                yield self._sse_event("message", {
                                                    "role": "assistant", "content": val,
                                                })
                                    elif typ == "tool_call":
                                        detected_tool_calls.append(val)
                                elif isinstance(chunk, str):
                                    if chunk:
                                        full_text_parts.append(chunk)
                                        if stream_as_thinking:
                                            yield self._sse_event("thinking", {
                                                "content": chunk,
                                                "iteration": iteration,
                                                "streaming": True,
                                            })
                                        else:
                                            yield self._sse_event("message", {
                                                "role": "assistant", "content": chunk,
                                            })
                        except Exception:
                            # 降级：纯文本流
                            async for chunk in adapter.stream(llm_messages):
                                if stop_event.is_set():
                                    break
                                if chunk:
                                    full_text_parts.append(chunk)
                                    if stream_as_thinking:
                                        yield self._sse_event("thinking", {
                                            "content": chunk,
                                            "iteration": iteration,
                                            "streaming": True,
                                        })
                                    else:
                                        yield self._sse_event("message", {
                                            "role": "assistant", "content": chunk,
                                        })
                    else:
                        # 纯文本 ReAct Prompt 模式 或 无工具纯对话
                        if stream_as_thinking:
                            thinking_start_ts = time.time()
                            yield self._sse_event("thinking_start", {
                                "iteration": iteration,
                            })
                        async for chunk in adapter.stream(llm_messages):
                            if stop_event.is_set():
                                break
                            if chunk:
                                full_text_parts.append(chunk)
                                if stream_as_thinking:
                                    yield self._sse_event("thinking", {
                                        "content": chunk,
                                        "iteration": iteration,
                                        "streaming": True,
                                    })
                                else:
                                    yield self._sse_event("message", {
                                        "role": "assistant", "content": chunk,
                                    })
                        # 尝试从文本中解析 ACTION/THOUGHT/OBSERVATION 格式的工具调用
                        detected_tool_calls = self._parse_react_tool_calls_from_text(
                            "".join(full_text_parts), mcp_services
                        )
                except LLMException as e:
                    logger.error(f"LLM 流式调用失败(ReAct#{iteration}): {e.message}")
                    yield self._sse_event("message", {
                        "role": "error", "content": f"[LLM 调用失败] {e.message}",
                    })
                    yield self._sse_event("done", {"error": e.message})
                    # 持久化错误消息
                    await self._persist_with_session(
                        conversation_id,
                        message_type="error",
                        content=f"[LLM 调用失败] {e.message}",
                    )
                    return
                except Exception as e:
                    logger.error(f"流式生成异常(ReAct#{iteration}): {e}", exc_info=True)
                    yield self._sse_event("done", {"error": f"内部错误: {str(e)}"})
                    return

                if adapter.is_fallback_used:
                    fallback_used = True

                assistant_text = "".join(full_text_parts)
                # 如果 function calling 没有产生有效 tool_calls，尝试文本 ReAct 解析作为兜底
                if not detected_tool_calls and use_function_calling and mcp_services:
                    logger.info(f"[DEBUG] function calling 未产生 tool_calls，尝试文本 ReAct 解析兜底")
                    text_tool_calls = self._parse_react_tool_calls_from_text(
                        assistant_text, mcp_services
                    )
                    if text_tool_calls:
                        detected_tool_calls = text_tool_calls
                        logger.info(f"[DEBUG] 文本 ReAct 解析找到 {len(detected_tool_calls)} 个工具调用")
                print(f"[DEBUG] ReAct#{iteration}: assistant_text={len(assistant_text)}chars, tool_calls={len(detected_tool_calls)}")

                # Step2: 判断是否需要工具调用
                has_tool_calls = bool(detected_tool_calls)
                looks_like_thinking = False
                if not has_tool_calls and (enable_react or llm_tool_defs):
                    looks_like_thinking = ChatService._looks_like_intermediate_thinking(assistant_text)
                    if looks_like_thinking and iteration < self._max_react_iterations - 1:
                        logger.info(
                            f"[DEBUG] ReAct#{iteration}: 本轮没有解析到 tool_calls，但内容看起来是中间推理"
                            f"（含下一步计划），强制当作中间轮处理，继续下一轮循环。"
                        )

                # 计算本轮思考时长
                thinking_duration_ms = 0
                if thinking_start_ts is not None:
                    thinking_duration_ms = int((time.time() - thinking_start_ts) * 1000)

                if not has_tool_calls and not looks_like_thinking:
                    # 纯文本最终答案 → break 主循环
                    final_assistant_tool_calls.extend(detected_tool_calls)
                    logger.info(f"[DEBUG] ReAct#{iteration}: 最终回复确定阶段, raw_assistant_length={len(assistant_text)}, final_thinking_content_len={len(final_thinking_content)}, strategy_mode={strategy_mode}, plan_steps_count={len(plan_steps)}, tools_executed={len(final_assistant_tool_calls)}")

                    if stream_as_thinking:
                        # 最终轮：发送 thinking_done（标记最后一轮思考结束）
                        yield self._sse_event("thinking_done", {
                            "iteration": iteration,
                            "duration_ms": thinking_duration_ms,
                        })
                        # 发送 thinking_to_answer，携带 thinking_content（仅中间轮推理）
                        # answer_text 改为通过 message 事件流式推送，让前端在回答区块中展示流式效果
                        yield self._sse_event("thinking_to_answer", {
                            "iteration": iteration,
                            "duration_ms": thinking_duration_ms,
                            "thinking_content": final_thinking_content if final_thinking_content else None,
                        })

                        # ── P&E 模式增强：有计划+有工具执行 → 额外做一次显式综合总结 LLM 调用 ──
                        is_pe_with_execution = (
                            strategy_mode == "plan_and_execute"
                            and len(plan_steps) > 0
                            and (len(final_assistant_tool_calls) > 0 or iteration > 0)
                        )
                        # 另外：若 assistant_text 过短(<200字)但执行了多轮工具/或中间推理不为空，也触发显式总结（兼容 ReAct 边界情况）
                        needs_explicit_summary = (
                            is_pe_with_execution
                            or (
                                len(assistant_text.strip()) < 200
                                and (len(final_assistant_tool_calls) > 0 or bool(final_thinking_content))
                            )
                        )

                        summary_parts: list[str] = []
                        if needs_explicit_summary:
                            logger.info(f"[DEBUG] 触发显式综合总结: is_pe={is_pe_with_execution}, assistant_len={len(assistant_text.strip())}, tools_called={len(final_assistant_tool_calls)}")
                            # 把 LLM 上一轮输出的短文本当作 assistant 消息，再追加一条"请综合总结"的用户消息
                            llm_messages.append({
                                "role": "assistant",
                                "content": assistant_text or "",
                            })
                            if is_pe_with_execution and plan_for_context:
                                pe_summary_instruction = (
                                    f"请你基于以上【任务执行计划】及每一步工具调用的结果，为用户整理一份完整、结构化、内容详实的最终回答。\n"
                                    f"【执行计划回顾】\n{plan_for_context}\n"
                                    f"要求：\n"
                                    f"1. 严格基于已获取的工具结果作答，不要编造未给出的信息\n"
                                    f"2. 回答结构完整，分点/分章节论述，必要时包含小标题\n"
                                    f"3. 覆盖计划中的主要步骤，说明每个步骤得到的关键结论或数据\n"
                                    f"4. 语言通顺、信息密度高，必要时可使用 Markdown 表格/列表/加粗等格式\n"
                                    f"5. 如遇数据缺失或工具调用失败，诚实说明，不臆测\n"
                                    f"6. 最终回答至少 300 字，信息充分的情况下可更长。"
                                )
                                llm_messages.append({
                                    "role": "user",
                                    "content": pe_summary_instruction,
                                })
                            else:
                                generic_summary_instruction = (
                                    "请你基于上面多轮工具调用的结果与推理过程，为用户整理一份完整的最终回答。\n"
                                    "要求：结构清晰，分点论述，信息详实，严格只基于已获取的结果，不编造内容。\n"
                                    "尽量使用 Markdown 格式（标题、列表、加粗、表格）让回答更易读。"
                                )
                                llm_messages.append({
                                    "role": "user",
                                    "content": generic_summary_instruction,
                                })
                            try:
                                async for chunk in adapter.stream(llm_messages):
                                    if stop_event.is_set():
                                        break
                                    if chunk:
                                        summary_parts.append(chunk)
                                        yield self._sse_event("message", {
                                            "role": "assistant",
                                            "content": chunk,
                                        })
                            except Exception as e:
                                logger.warning(f"[DEBUG] 显式综合总结 LLM 调用失败，回退到原文本: {e}")
                                summary_parts = []  # 清空，走回退路径
                        # 回退：未触发显式总结、或显式总结无输出 → 用原 assistant_text 模拟流式推送
                        if not summary_parts:
                            async for msg_chunk in self._stream_text_chunks(assistant_text, chunk_size=8):
                                yield self._sse_event("message", {
                                    "role": "assistant",
                                    "content": msg_chunk,
                                })
                            final_assistant_text = assistant_text
                        else:
                            final_assistant_text = "".join(summary_parts)
                        logger.info(f"[DEBUG] 最终回答长度: final_assistant_text_len={len(final_assistant_text)}")
                    else:
                        # 无工具绑定的纯对话场景：流式期间已作为 message 实时推送
                        final_assistant_text = assistant_text
                    break

                # 有工具调用 → 这是中间轮，把本轮的 assistant_text 累积到思考内容中
                if final_thinking_content:
                    final_thinking_content += f"\n\n---\n\n**第 {iteration + 1} 轮推理**\n\n{assistant_text}"
                else:
                    final_thinking_content = f"**第 {iteration + 1} 轮推理**\n\n{assistant_text}" if iteration > 0 else assistant_text

                # thinking 已在流式期间推送，发送 thinking_done（带时长）
                # 无论 content 是否为空，都应该发送 thinking_done
                yield self._sse_event("thinking_done", {
                    "iteration": iteration,
                    "duration_ms": thinking_duration_ms,
                })
                # 先补全 mcp_service_name（基于 mcp_services 构建 tool_name → mcp_name 映射）
                tool_to_mcp_name: dict[str, str] = {}
                tool_to_mcp_id: dict[str, str] = {}
                for mcp in mcp_services or []:
                    mcp_id = mcp.get("id") or mcp.get("mcp_service_id") or ""
                    mcp_name = mcp.get("name") or ""
                    for t in mcp.get("tools", []) or []:
                        tname = t.get("name", "")
                        if not tname:
                            continue
                        # 若同名工具来自多个 MCP，后续会用 tool-svc 再次兜底
                        tool_to_mcp_name.setdefault(tname, mcp_name)
                        tool_to_mcp_id.setdefault(tname, mcp_id)
                for tc in detected_tool_calls:
                    if not tc.get("mcp_service_name") and not tc.get("mcp_service_id"):
                        tname = tc.get("tool_name", "")
                        tc["mcp_service_name"] = tool_to_mcp_name.get(tname, "")
                        tc["mcp_service_id"] = tool_to_mcp_id.get(tname, "")

                # 将本轮 assistant 消息记入（附带 tool_calls 信息）
                final_assistant_tool_calls.extend(detected_tool_calls)

                # 持久化：tool_call 消息（记录调用参数）
                tool_call_msg_content = f"[Tool Calls] {json.dumps(detected_tool_calls, ensure_ascii=False, default=str)}"
                async with AsyncSessionLocal() as s2:
                    tc_msg = await self._persist_message(
                        s2,
                        conversation_id=conversation_id,
                        message_type="tool_call",
                        content=tool_call_msg_content,
                        tool_calls={"calls": detected_tool_calls},
                    )
                    await s2.commit()
                    react_messages_for_persist.append(tc_msg)

                # LLM messages 中追加 assistant（含 tool_calls），等所有工具完成后追加 tool_result
                # LangChain function calling 兼容格式：assistant 消息 content + tool_calls
                assistant_llm_msg: dict[str, Any] = {
                    "role": "assistant",
                    "content": assistant_text or "",
                }
                if detected_tool_calls:
                    assistant_llm_msg["tool_calls"] = [
                        {
                            "id": f"call_{idx}_{uuid.uuid4().hex[:6]}",
                            "type": "function",
                            "function": {
                                "name": tc.get("tool_name", ""),
                                "arguments": json.dumps(tc.get("arguments", {}), ensure_ascii=False),
                            },
                        }
                        for idx, tc in enumerate(detected_tool_calls)
                    ]
                llm_messages.append(assistant_llm_msg)

                # 逐个调用工具（串行，简单实现），每个都推 tool_call 事件
                tool_results_list: list[dict] = []
                for idx, tool_call in enumerate(detected_tool_calls):
                    if stop_event.is_set():
                        break
                    tool_name = tool_call.get("tool_name", "")
                    arguments = tool_call.get("arguments", {}) or {}
                    # SSE 推送 tool_call 事件（执行前，带参数）
                    yield self._sse_event("tool_call", {
                        "index": idx,
                        "tool_name": tool_name,
                        "name": tool_name,
                        "arguments": arguments,
                        "args": arguments,
                        "status": "pending",
                    })
                    # 通过 HTTP 调用 tool-svc
                    call_result = await self._call_tool_via_http(
                        tool_call={
                            "tool_name": tool_name,
                            "arguments": arguments,
                            "mcp_service_name": tool_call.get("mcp_service_name", ""),
                        },
                        agent_id=agent_id,
                        conversation_id=conversation_id,
                    )
                    status = call_result.get("status", "failed")
                    result_val = call_result.get("result")
                    error_val = call_result.get("error", "")
                    # SSE 推送 tool_result 事件（执行后，带结果）
                    yield self._sse_event("tool_result", {
                        "index": idx,
                        "tool_name": tool_name,
                        "name": tool_name,
                        "status": status,
                        "result": result_val,
                        "error": error_val,
                    })
                    tool_results_list.append(call_result)

                    # 持久化：tool_result 消息（简化存储，避免过大）
                    result_summary = ""
                    if result_val is not None:
                        if isinstance(result_val, (dict, list)):
                            result_summary = json.dumps(result_val, ensure_ascii=False, default=str)[:2000]
                        else:
                            result_summary = str(result_val)[:2000]
                    tr_msg_content = (
                        f"[Tool Result] {tool_name}: {status}\n"
                        f"{result_summary}\n"
                        f"{error_val if error_val else ''}".strip()
                    )
                    # 简化的 tool_results（只保存关键信息）
                    simplified_results = []
                    for tr in tool_results_list:
                        tr_result = tr.get("result")
                        if tr_result is not None:
                            if isinstance(tr_result, (dict, list)):
                                tr_result = json.dumps(tr_result, ensure_ascii=False, default=str)[:2000]
                            else:
                                tr_result = str(tr_result)[:2000]
                        simplified_results.append({
                            "tool_name": tr.get("tool_name", ""),
                            "status": tr.get("status", "failed"),
                            "duration_ms": tr.get("duration_ms", 0),
                            "result": tr_result,
                            "error": tr.get("error", "")[:500] if tr.get("error") else "",
                        })
                    async with AsyncSessionLocal() as s3:
                        tr_msg = await self._persist_message(
                            s3,
                            conversation_id=conversation_id,
                            message_type="tool_result",
                            content=tr_msg_content,
                            tool_results={"results": simplified_results},
                        )
                        await s3.commit()
                        react_messages_for_persist.append(tr_msg)

                    # LLM messages 追加 tool role 消息（兼容 LangChain function calling）
                    tool_call_id = assistant_llm_msg.get("tool_calls", [{}])[idx].get("id", f"tool_{idx}") if idx < len(assistant_llm_msg.get("tool_calls", [])) else f"tool_{idx}"
                    observation_text = ""
                    if status == "success" and result_val is not None:
                        if isinstance(result_val, (dict, list)):
                            observation_text = json.dumps(result_val, ensure_ascii=False, default=str)
                        else:
                            observation_text = str(result_val)
                        # 截断过长的 observation，保留前 5000 字符供 LLM 参考
                        if len(observation_text) > 5000:
                            observation_text = observation_text[:5000] + "\n... (结果已截断)"
                    else:
                        observation_text = f"工具调用失败: {error_val or status}"
                    llm_messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": observation_text,
                    })

                # continue 下一轮 ReAct
            else:
                # 超过 max_iterations → 让 LLM 给出最终总结
                exceed_msg = (
                    f"\n\n[注意] 已达到最大 ReAct 迭代轮数({self._max_react_iterations})，"
                    "请直接基于以上 observation 给出最终总结，不要再调用任何工具。"
                )
                # 构造一条最终用户消息强制总结
                llm_messages.append({
                    "role": "user",
                    "content": exceed_msg,
                })
                summary_parts: list[str] = []
                # 发送 thinking_done 标记最后一轮思考结束
                if stream_as_thinking:
                    yield self._sse_event("thinking_done", {
                        "iteration": self._max_react_iterations - 1,
                        "duration_ms": 0,
                    })
                # 先发送 thinking_to_answer（清理思考区块状态）
                if stream_as_thinking:
                    yield self._sse_event("thinking_to_answer", {
                        "iteration": self._max_react_iterations - 1,
                        "duration_ms": 0,
                        "thinking_content": final_thinking_content if final_thinking_content else None,
                    })
                try:
                    async for chunk in adapter.stream(llm_messages):
                        if stop_event.is_set():
                            break
                        if chunk:
                            summary_parts.append(chunk)
                            # 超限总结 KNOWN 是最终回答，直接作为 message 事件流式推送
                            # 不再先推 thinking → thinking_to_answer → message 的三步走
                            # 避免回答内容先出现在思考区块导致的界面抖动和错位
                            yield self._sse_event("message", {
                                "role": "assistant",
                                "content": chunk,
                            })
                except Exception as e:
                    logger.warning(f"ReAct超限总结LLM调用失败: {e}")
                    summary_parts.append(final_assistant_text)
                final_assistant_text = "".join(summary_parts)

        finally:
            self._stop_events.pop(conversation_id, None)

        # 13. 持久化最终 AI 回复（附带思考内容）
        tool_calls_for_save = None
        if final_assistant_tool_calls:
            tool_calls_for_save = {"calls": final_assistant_tool_calls}
        # 思考内容落库策略：
        # - 有多轮中间推理（final_thinking_content 非空）：保存中间轮推理过程
        # - 无中间推理（单轮直接输出最终回答）：保存 None，前端显示迁移提示
        thinking_to_save = final_thinking_content if final_thinking_content else None
        ai_msg = await self._persist_with_session(
            conversation_id,
            message_type="assistant",
            content=final_assistant_text,
            tool_calls=tool_calls_for_save,
            thinking=thinking_to_save if thinking_to_save else None,
        )

        # 14. event: done
        done_payload: dict[str, Any] = {
            "content": "",
            "message_id": ai_msg.id,
            "react_iterations": iteration_took,
        }
        if fallback_used:
            done_payload["fallback"] = True
            done_payload["fallback_message"] = "已自动降级为模型默认参数"
        yield self._sse_event("done", done_payload)

    # ── 辅助：stream LLM 并尝试捕获 tool_calls ──────

    async def _stream_llm_with_tools(
        self, adapter: LLMAdapter, llm_messages: list[dict], tool_defs: list[dict],
    ) -> AsyncIterator[Any]:
        """流式调用 LLM（带 tools），实时 yield content chunks，流结束后 yield tool_calls

        使用 LangChain 的 astream 真正流式接收，同时累积 tool_call_chunks，
        流式结束后解析出完整的 tool_calls。
        返回: ('content', str) 或 ('tool_call', dict) 或 str（降级纯文本）
        """
        llm = adapter._create_llm()
        lc_messages = adapter._convert_messages(llm_messages)
        try:
            # bind tools (LangChain)
            try:
                bound = llm.bind_tools(tool_defs)
            except Exception:
                # 部分模型不支持 bind_tools → 降级为不带 tools 的流式
                logger.info("[DEBUG] bind_tools 失败，降级为纯文本流式")
                async for chunk in adapter.stream(llm_messages):
                    yield chunk
                return

            # 真正流式：用 astream 实时推送 content，同时累积 tool_call_chunks
            accumulated_tool_calls: dict[int, dict] = {}  # index → {name, args_str}
            streamed_content_parts: list[str] = []  # 跟踪已流式输出的内容，避免非流式回退时重复推送
            logger.info(f"[DEBUG] 开始 astream 调用，tools_count={len(tool_defs)}")
            chunk_count = 0
            tool_call_chunk_count = 0
            try:
                async for chunk_msg in bound.astream(lc_messages):
                    chunk_count += 1
                    # 实时 yield content（不等待全部完成）
                    content = getattr(chunk_msg, "content", "") or ""
                    if isinstance(content, list):
                        content = "".join(str(c) for c in content if isinstance(c, str))
                    if content:
                        yield ("content", content)
                        streamed_content_parts.append(content)
                    # 累积 tool_call chunks（流式分块返回，需拼接）
                    tc_chunks = getattr(chunk_msg, "tool_call_chunks", None) or []
                    if tc_chunks:
                        tool_call_chunk_count += len(tc_chunks)
                    for tc_chunk in tc_chunks:
                        idx = getattr(tc_chunk, "index", None)
                        name = getattr(tc_chunk, "name", None)
                        args = getattr(tc_chunk, "args", None)
                        # 过滤掉所有属性都为 None 的空 placeholder chunks
                        if idx is None and name is None and args is None:
                            continue
                        if idx is None:
                            idx = len(accumulated_tool_calls)
                        if idx not in accumulated_tool_calls:
                            accumulated_tool_calls[idx] = {"name": "", "args_str": ""}
                        if name:
                            accumulated_tool_calls[idx]["name"] = name
                        if args:
                            accumulated_tool_calls[idx]["args_str"] += args
                        # 调试：打印第一个有效的 tool_call_chunk 的完整属性
                        if tool_call_chunk_count <= 3 and (name or args):
                            tc_dict = {
                                "index": idx,
                                "name": name,
                                "args": args[:100] if args else None,
                                "id": getattr(tc_chunk, "id", None),
                                "type": getattr(tc_chunk, "type", None),
                            }
                            logger.info(f"[DEBUG] valid tc_chunk#{tool_call_chunk_count}: {tc_dict}")
                    # 调试：打印每个 chunk 的结构
                    if chunk_count <= 3:
                        logger.info(
                            f"[DEBUG] chunk#{chunk_count}: "
                            f"has_content={bool(content)}, "
                            f"tc_chunks_count={len(tc_chunks)}, "
                            f"chunk_type={type(chunk_msg).__name__}"
                        )
            except Exception as e:
                # 流式中途失败 → 降级为纯文本流式
                logger.warning(f"astream with tools 失败: {e}，降级为纯流式")
                async for chunk in adapter.stream(llm_messages):
                    yield chunk
                return

            # 流式结束后，解析累积的 tool_calls 并 yield
            tc_count = sum(1 for v in accumulated_tool_calls.values() if v["name"])
            logger.info(
                f"[DEBUG] astream完成: total_chunks={chunk_count}, "
                f"tool_call_chunks_found={tool_call_chunk_count}, "
                f"accumulated_tool_calls={len(accumulated_tool_calls)}, "
                f"valid={tc_count}"
            )
            # 调试：打印所有累积的 tool_calls 详情
            for idx in sorted(accumulated_tool_calls.keys()):
                info = accumulated_tool_calls[idx]
                logger.info(
                    f"[DEBUG] accumulated_tc#{idx}: name='{info['name']}', "
                    f"args_len={len(info['args_str'])}, args_preview='{info['args_str'][:100]}'"
                )
            # 如果有 args_str 但 name 为空，尝试从 args 中解析工具名
            # （某些模型如 DeepSeek 将完整调用 JSON 放在 args 中）
            if tc_count == 0 and any(v["args_str"] for v in accumulated_tool_calls.values()):
                logger.info("[DEBUG] name 为空但有 args_str，尝试从 args 解析工具名")
                for idx in sorted(accumulated_tool_calls.keys()):
                    info = accumulated_tool_calls[idx]
                    if not info["name"] and info["args_str"]:
                        try:
                            parsed = json.loads(info["args_str"])
                            # 尝试从解析后的 JSON 中获取 name
                            if isinstance(parsed, dict):
                                if "name" in parsed:
                                    info["name"] = parsed["name"]
                                    info["args_str"] = json.dumps(parsed.get("arguments", parsed.get("args", {})))
                                    logger.info(f"[DEBUG] 从 args 解析出 name: {info['name']}")
                                elif "tool_name" in parsed:
                                    info["name"] = parsed["tool_name"]
                                    info["args_str"] = json.dumps(parsed.get("arguments", parsed.get("args", {})))
                                    logger.info(f"[DEBUG] 从 args 解析出 tool_name: {info['name']}")
                        except Exception as e:
                            logger.info(f"[DEBUG] 从 args 解析 name 失败: {e}")
                tc_count = sum(1 for v in accumulated_tool_calls.values() if v["name"])
                logger.info(f"[DEBUG] 解析后 valid={tc_count}")

            # 如果流式 function calling 没有产生有效 tool_calls，
            # 但检测到了 tool_call_chunks（说明模型尝试调用工具），
            # 则用非流式方式重新调用获取完整的 tool_calls
            if tc_count == 0 and tool_call_chunk_count > 0:
                logger.info(
                    f"[DEBUG] 流式 tool_call 解析失败(chunk_count={tool_call_chunk_count})，"
                    f"用非流式 ainvoke 重新获取 tool_calls"
                )
                try:
                    # 用非流式方式重新调用（能正确获取完整 tool_calls）
                    response = await bound.ainvoke(lc_messages)
                    # 从完整响应中提取 tool_calls
                    resp_tool_calls = getattr(response, "tool_calls", None) or []
                    if resp_tool_calls:
                        logger.info(f"[DEBUG] 非流式获取到 {len(resp_tool_calls)} 个 tool_calls")
                        for tc in resp_tool_calls:
                            tc_name = tc.get("name", "") if isinstance(tc, dict) else getattr(tc, "name", "")
                            tc_args = tc.get("args", {}) if isinstance(tc, dict) else getattr(tc, "args", {})
                            if tc_name:
                                yield ("tool_call", {
                                    "tool_name": tc_name,
                                    "arguments": tc_args or {},
                                })
                                logger.info(f"[DEBUG] yield tool_call (非流式): {tc_name}")
                        return
                    # 如果非流式也没有 tool_calls，输出完整响应的 content
                    resp_content = getattr(response, "content", "") or ""
                    if resp_content and not any(streamed_content_parts):
                        yield ("content", resp_content)
                except Exception as e:
                    logger.warning(f"[DEBUG] 非流式重新调用失败: {e}")

            for idx in sorted(accumulated_tool_calls.keys()):
                info = accumulated_tool_calls[idx]
                tc_name = info["name"]
                if not tc_name:
                    continue
                try:
                    tc_args = json.loads(info["args_str"]) if info["args_str"] else {}
                except Exception:
                    tc_args = {"_raw": info["args_str"]} if info["args_str"] else {}
                yield ("tool_call", {
                    "tool_name": tc_name,
                    "arguments": tc_args,
                })
                logger.info(f"[DEBUG] yield tool_call: {tc_name}")

        except Exception as e:
            logger.warning(f"_stream_llm_with_tools 异常: {e}，降级为纯流式")
            async for chunk in adapter.stream(llm_messages):
                yield chunk

    # ── 辅助：从文本中解析纯文本 ReAct 工具调用 ──────

    def _parse_react_tool_calls_from_text(
        self, text: str, mcp_services: list[dict],
    ) -> list[dict]:
        """从 ReAct 风格文本中解析工具调用（兜底）

        支持格式:
            ACTION: tool_name
            ARGS: {json}
        或
            <|FunctionCallBegin|>[{"name":"..","arguments":{}}]<|FunctionCallEnd|>
        或
            调用工具名: xxx / 执行: tool_name / tool: xxx 等变体
        """
        if not text:
            return []
        results: list[dict] = []
        # 所有可用 tool_name
        available_tools: set[str] = set()
        for mcp in mcp_services:
            for t in mcp.get("tools", []) or []:
                available_tools.add(t.get("name", ""))
        if not available_tools:
            return []

        # 格式1: ACTION / ARGS
        pattern1 = re.compile(
            r"ACTION\s*[:：]\s*(\w+)[\s\S]*?ARGS\s*[:：]\s*(\{[\s\S]*?\})",
            re.IGNORECASE,
        )
        for m in pattern1.finditer(text):
            tname = m.group(1).strip()
            if tname not in available_tools:
                continue
            try:
                args = json.loads(m.group(2))
            except Exception:
                args = {}
            results.append({"tool_name": tname, "arguments": args})

        # 格式2: <|FunctionCallBegin|> ... <|FunctionCallEnd|>
        pattern2 = re.compile(
            r"<\|FunctionCallBegin\|>([\s\S]*?)<\|FunctionCallEnd\|>",
        )
        for m in pattern2.finditer(text):
            try:
                arr = json.loads(m.group(1))
                if isinstance(arr, list):
                    for item in arr:
                        tname = item.get("name", "")
                        if tname in available_tools:
                            results.append({
                                "tool_name": tname,
                                "arguments": item.get("arguments", {}) or {},
                            })
                elif isinstance(arr, dict):
                    tname = arr.get("name", "")
                    if tname in available_tools:
                        results.append({
                            "tool_name": tname,
                            "arguments": arr.get("arguments", {}) or {},
                        })
            except Exception:
                pass

        # 格式3：检测文本中对已知 tool_name 的显式提及（宽松匹配）
        # 例如："我将调用web_search"、"使用mcp_search工具"、"执行search"
        if not results:
            # 先看是否有类似「调用工具」「执行」「使用」「进行」的动词
            call_verbs = (
                "调用", "执行", "使用", "发起", "运行", "查询", "检索", "搜索",
                "call", "invoke", "run", "execute", "use", "search",
            )
            # 优先抽取紧邻动词的工具名
            loose_pattern = re.compile(
                r"(?:" + "|".join(call_verbs) + r")\s*[:：]?\s*[「\"'`]?\s*([A-Za-z_][A-Za-z0-9_\-]*)\s*[」\"'`]?",
                re.IGNORECASE,
            )
            seen_tool_names = {r["tool_name"] for r in results}
            for m in loose_pattern.finditer(text):
                candidate = m.group(1).strip()
                # 去掉可能的前后缀：例如 web_search_query → web_search 也算匹配
                if candidate in available_tools and candidate not in seen_tool_names:
                    results.append({"tool_name": candidate, "arguments": {}})
                    seen_tool_names.add(candidate)

        # 去重（按 tool_name 合并优先级）
        return results[:4]

    @staticmethod
    def _looks_like_intermediate_thinking(text: str) -> bool:
        """判断文本是否属于「中间推理/计划执行」而非「最终回答」

        当有工具绑定的多轮 ReAct 场景，如果最后一轮 LLM 生成的文本明显是在
        「说我要调用工具/继续执行下一轮」，但 function calling 或文本解析
        都没成功捕获 tool_calls，那么它仍然应该被当作「中间轮」累积到
        thinking_content，而不是作为最终回答输出。

        优化策略：
        - 优先检测「最终回答强信号」，直接排除误判
        - 中间推理检测必须同时满足：有继续执行意图 + 有工具/检索相关关键词
        - 报告类文本（长篇、结构化、含报告关键词）一律视为最终回答
        """
        if not text:
            return False
        sample = text[:800].lower()

        # ── 0. 最终回答强信号：直接排除，不要再做中间推理检测 ──
        final_answer_strong_signals = (
            "最终回答", "最终答案", "综合回答", "总结回答", "综上", "总而言之",
            "报告完毕", "分析完毕", "调研完毕", "研究完毕",
            "final answer", "final response", "in summary", "to summarize",
            "in conclusion", "finally", "conclusion", "to conclude",
        )
        if any(sig in sample for sig in final_answer_strong_signals):
            return False

        # ── 0.1 报告类信号：含"报告"关键词或多章节结构 → 视为最终回答 ──
        report_signals = (
            "报告", "摘要", "引言", "结语", "结论", "参考文献", "致谢",
            "一、", "二、", "三、", "四、", "五、", "六、", "七、", "八、",
            "第一部分", "第二部分", "第三部分",
            "section", "introduction", "conclusion", "report",
        )
        has_report_signal = any(k in sample for k in report_signals)
        if has_report_signal:
            # 短文本（<500字）含报告信号 → 直接视为最终回答
            if len(text) < 500:
                return False
            # 长文本（>=500字）含报告信号 → 检查是否有中间推理意图
            # 如果没有继续执行的明确意图，视为最终回答
            intermediate_intent_signals = (
                "下一步", "下一轮", "继续调用", "继续检索", "继续查询",
                "接下来调用", "接下来检索", "接下来查询",
                "再调用", "再查询", "再搜索", "补充检索", "补充验证",
                "next step", "continue to", "proceed to",
            )
            has_intermediate_intent = any(
                re.search(rf"{re.escape(sig)}.*?(工具|检索|查询|搜索|tool|search|query)", sample)
                or re.search(rf"(工具|检索|查询|搜索|tool|search|query).*?{re.escape(sig)}", sample)
                for sig in intermediate_intent_signals
            )
            if not has_intermediate_intent:
                return False
            # 有中间意图 → 检查是否有足够强的报告结构（>2000字+多章节）
            if len(text) > 2000 and len(re.findall(
                r"[一二三四五六七八九十]+[、.）)]", text[:1500]
            )) >= 2:
                return False
            # 有中间意图但报告结构不强 → 可能是中间推理
            return True

        # ── 0.2 文本很长（>1500字）且有分节结构 → 大概率是最终回答 ──
        if len(text) > 1500:
            section_markers = re.findall(
                r"(^|\n)\s*[一二三四五六七八九十]+[、.）)]\s*\S+", text[:2000], re.MULTILINE
            )
            if len(section_markers) >= 2:
                # 有分节结构 → 检查是否有继续执行意图
                next_step_intent = any(
                    sig in sample for sig in (
                        "下一步", "下一轮", "继续", "接着", "随后", "然后",
                        "接下来", "即将", "准备",
                    )
                )
                tool_keywords_present = any(
                    k in sample for k in (
                        "检索", "查询", "工具", "调用", "搜索", "search", "tool", "query",
                    )
                )
                # 只有同时有继续意图 + 工具关键词才视为中间推理
                if not (next_step_intent and tool_keywords_present):
                    return False

        # ── 1. 中间推理检测：必须同时满足「继续意图」+「工具/检索关键词」──
        next_step_intent_signals = (
            "下一步", "下一轮", "继续", "接着", "随后", "然后", "即将", "准备",
            "开始第", "执行第", "进行第",
            "现在进行", "现在执行", "正在进行",
            "规划", "方案", "多路并行", "并行执行",
            "再调用", "再查询", "再搜索", "再次", "额外", "进一步",
            "需要补充", "还需要", "需补充", "还需",
            "next step", "continue", "proceed", "then", "round", "iteration",
        )
        has_next_intent = any(sig in sample for sig in next_step_intent_signals)
        if not has_next_intent:
            return False

        # 有继续意图 → 必须同时有工具/检索相关关键词才判定为中间推理
        tool_keywords = (
            "检索", "查询", "工具", "调用", "搜索", "整理",
            "search", "query", "tool", "call",
            "数据", "信息", "销量", "预测",
        )
        has_tool_context = any(k in sample for k in tool_keywords)
        if not has_tool_context:
            return False

        # ── 1.1 中文正则：第N轮/步 → 强中间推理信号 ──
        if re.search(r"第\s*\d+\s*[轮步骤检索]", text[:1500]):
            return True

        # ── 1.1a 极强中间信号：「继续搜索」「继续查询」「继续检索」「补充...数据」──
        strong_intermediate = (
            r"继续(搜索|查询|检索|调用|执行)",
            r"补充[\s\S]{0,30}?(数据|信息|内容|资料|验证)",
            r"还需要[\s\S]{0,30}?(搜索|查询|检索|数据|信息)",
            r"需要(进一步|更多|额外)[\s\S]{0,30}?(搜索|查询|检索|数据|信息)",
        )
        for pat in strong_intermediate:
            if re.search(pat, text[:1500]):
                return True

        # ── 1.2 结构化迹象：已完成 + 接下来（需工具上下文）──
        done_patterns = (
            r"(完成|已完成|已获取|已验证|done|finished|completed)\s*[，,。;；]?"
            r"[\s\S]{0,500}?"
            r"(现在|接下来|继续|然后|开始|执行|进行|准备)",
        )
        for p in done_patterns:
            if re.search(p, text[:1500]):
                # done pattern + 有继续意图 + 有工具上下文 → 中间推理
                return True

        # ── 1.3 明确的「计划结构」分点：需结合工具关键词 ──
        plan_markers = re.findall(r"(^|\n)\s*[\d一二三四五六七八九十]+[.、)）]\s*\S+", text[:1500], re.MULTILINE)
        if len(plan_markers) >= 2 and has_tool_context and has_next_intent:
            return True

        return False

    # ── 辅助：构建 LangChain tool definitions ─────────

    def _build_llm_tool_definitions(self, mcp_services: list[dict]) -> list[dict]:
        """将 MCP tools 转成 OpenAI function calling 格式"""
        tools: list[dict] = []
        for mcp in mcp_services:
            mcp_name = mcp.get("name", "")
            for t in mcp.get("tools", []) or []:
                tname = t.get("name", "")
                if not tname:
                    continue
                schema = t.get("input_schema", {}) or {}
                # 确保是标准 JSON Schema
                if "type" not in schema:
                    schema = {"type": "object", "properties": schema}
                tools.append({
                    "type": "function",
                    "function": {
                        "name": tname,
                        "description": t.get("description", "") or "",
                        "parameters": schema,
                    },
                    "_mcp_service_name": mcp_name,
                })
        return tools

    # ── (P2) 构造 system_prompt，含 MCP 工具 + Skills Level0 ─

    def _build_system_prompt_with_tools(
        self,
        base_prompt: str,
        long_term_memory: Any,
        compressed_summary: Optional[str],
        mcp_services: list[dict],
        skills: list[dict],
    ) -> str:
        """组装最终 system_prompt：基础 + 长期记忆 + 压缩摘要 + MCP工具 + Skills概要"""
        # 先调用 memory_service.build_system_prompt 处理基础部分
        base = memory_service.build_system_prompt(
            base_prompt=base_prompt,
            long_term_memory=long_term_memory,
            compressed_summary=compressed_summary,
        )
        sections: list[str] = [base.strip()]

        # Skills Level0 概要
        if skills:
            skill_simple_list = [
                {
                    "name": s.get("name", ""),
                    "description": s.get("description", ""),
                    "category": s.get("category", ""),
                    "tags": [],
                    "version": "",
                }
                for s in skills
            ]
            skills_prompt = SkillManager.build_skill_prompt_level0(skill_simple_list)
            sections.append(skills_prompt)

        # MCP 工具列表注入 Prompt（纯文本模式下 LLM 能知道）
        if mcp_services:
            tool_lines: list[str] = []
            tool_lines.append("【你可用的MCP工具列表】")
            tool_lines.append("重要说明：当用户的请求需要使用以下工具时，你 MUST 调用工具而不是直接回答。")
            tool_lines.append("例如：用户要求搜索、查询、获取信息时，必须调用对应的工具。")
            tool_lines.append("调用方式：使用 function calling（系统已为你绑定工具）。")
            tool_lines.append("如果 function calling 不可用，请使用以下 ReAct 文本格式：")
            tool_lines.append("  ACTION: tool_name")
            tool_lines.append("  ARGS: {\"arg1\": \"value1\"}")
            tool_lines.append("  ... (最多一次调用多个工具，每个独立 ACTION/ARGS)")
            tool_lines.append("")
            total_count = 0
            for mcp in mcp_services:
                name = mcp.get("name", "")
                mode = mcp.get("mode", "")
                status = mcp.get("status", "")
                tool_lines.append(f"■ MCP服务: {name} (mode={mode}, status={status})")
                for t in mcp.get("tools", []) or []:
                    total_count += 1
                    tname = t.get("name", "")
                    tdesc = t.get("description", "") or ""
                    if len(tdesc) > 120:
                        tdesc = tdesc[:117] + "..."
                    tool_lines.append(f"  - {tname}: {tdesc}")
                tool_lines.append("")
            tool_lines.append(f"（共计 {total_count} 个可用工具）")
            tool_lines.append("切记：不要说'我来帮你搜索'然后不调用工具，必须实际调用工具来获取信息！")
            sections.append("\n".join(tool_lines))

        result = "\n\n".join(s for s in sections if s.strip())
        return result

    # ── (P2) 通过 HTTP 调用 tool-svc ─────────────────

    async def _call_tool_via_http(
        self, tool_call: dict, agent_id: str, conversation_id: str,
    ) -> dict:
        """调用 tool-svc POST /api/v1/tools/call（带超时保护，防止卡死）

        失败或httpx不可用时，返回降级错误结构，不会抛异常。
        """
        import asyncio
        tool_name = tool_call.get("tool_name", "")
        if not tool_name:
            return {
                "tool_name": tool_name,
                "status": "failed",
                "result": None,
                "error": "tool_name 为空",
                "duration_ms": 0,
            }
        client = self._get_tool_http_client()
        if client is None:
            return {
                "tool_name": tool_name,
                "status": "failed",
                "result": None,
                "error": "工具服务不可用，已跳过工具调用（httpx未安装）",
                "duration_ms": 0,
            }
        import time
        start = time.time()
        payload = {
            "agent_id": agent_id,
            "conversation_id": conversation_id,
            "mcp_service_id": tool_call.get("mcp_service_id") or tool_call.get("mcpServiceId") or "",
            "mcp_service_name": tool_call.get("mcp_service_name") or tool_call.get("mcpServiceName") or "",
            "tool_name": tool_name,
            "arguments": tool_call.get("arguments", {}) or {},
            "timeout": 90,
        }

        async def _do_call() -> dict:
            resp = await client.post(
                f"{self.TOOL_SVC_BASE}/api/v1/tools/call",
                json=payload,
                timeout=90.0,
            )
            elapsed = int((time.time() - start) * 1000)
            if resp.status_code != 200:
                return {
                    "tool_name": tool_name,
                    "status": "failed",
                    "result": None,
                    "error": f"tool-svc 返回 HTTP {resp.status_code}: {resp.text[:200]}",
                    "duration_ms": elapsed,
                }
            data = resp.json()
            # 兼容 ApiResponse 包装 {code, data, message}
            if isinstance(data, dict) and "code" in data and "data" in data:
                inner = data["data"] or {}
                resp_code = data.get("code", 0)
                fallback_error = ""
                if resp_code != 0:
                    fallback_error = data.get("message", "")
                if isinstance(inner, dict):
                    return {
                        "tool_name": inner.get("tool_name", tool_name),
                        "status": inner.get("status", "success" if resp_code == 0 else "failed"),
                        "result": inner.get("result"),
                        "error": (
                            inner.get("error_message", "")
                            or inner.get("error", "")
                            or fallback_error
                        ),
                        "duration_ms": elapsed,
                    }
            # 直接结构 {status, result, tool_name, error_message}
            return {
                "tool_name": data.get("tool_name", tool_name) if isinstance(data, dict) else tool_name,
                "status": data.get("status", "success") if isinstance(data, dict) else "success",
                "result": data.get("result") if isinstance(data, dict) else data,
                "error": data.get("error_message", "") or data.get("error", "") if isinstance(data, dict) else "",
                "duration_ms": elapsed,
            }

        try:
            # 外层加 asyncio.wait_for，确保任何情况下 95 秒必然返回，避免整链路卡死
            return await asyncio.wait_for(_do_call(), timeout=95.0)
        except asyncio.TimeoutError:
            elapsed = int((time.time() - start) * 1000)
            logger.warning(f"工具调用超时（>{elapsed}ms）: tool={tool_name}")
            return {
                "tool_name": tool_name,
                "status": "failed",
                "result": None,
                "error": f"工具调用超时（>{elapsed}ms），已自动跳过。请稍后重试或降低调用频率。",
                "duration_ms": elapsed,
            }
        except Exception as e:
            elapsed = int((time.time() - start) * 1000)
            error_detail = str(e) or type(e).__name__
            logger.warning(f"调用tool-svc失败 (tool={tool_name}): {error_detail}")
            return {
                "tool_name": tool_name,
                "status": "failed",
                "result": None,
                "error": f"工具服务调用失败: {error_detail}",
                "duration_ms": elapsed,
            }

    # ── (P2) HTTP 调用 agent-svc tools-summary ───────

    async def _fetch_tools_summary_http(self, agent_id: str) -> Optional[dict]:
        """调用 agent-svc GET /api/v1/agents/{id}/tools-summary

        连接失败或 httpx 不可用时返回 None（降级：无工具，走P1纯聊天）
        """
        client = self._get_agent_http_client()
        if client is None:
            return None
        try:
            resp = await client.get(
                f"{self.AGENT_SVC_BASE}/api/v1/agents/{agent_id}/tools-summary",
                timeout=5.0,
            )
            if resp.status_code != 200:
                logger.warning(f"agent-svc tools-summary 返回 HTTP {resp.status_code}")
                return None
            data = resp.json()
            if isinstance(data, dict) and "code" in data and "data" in data:
                return data.get("data") or {}
            if isinstance(data, dict):
                return data
            return None
        except Exception as e:
            logger.warning(f"调用agent-svc tools-summary失败: {e}")
            return None

    # ── (P2) 重新生成最后一条 assistant 消息 ─────────

    async def regenerate_last_message(
        self, conversation_id: str,
    ) -> AsyncIterator[str]:
        """重新生成最后一条 assistant 消息

        1. 找到最后一条 assistant 消息
        2. 删除该条消息及其后所有 tool_call / tool_result 消息
        3. 重新以该 assistant 之前最后一条用户消息的 content 调用 chat (即 send_message)
        """
        async with AsyncSessionLocal() as session:
            conv = await self._get_conversation(session, conversation_id)
            # 找最后一条 assistant
            stmt = (
                select(Message)
                .where(
                    Message.conversation_id == conversation_id,
                    Message.message_type == "assistant",
                )
                .order_by(Message.created_at.desc())
                .limit(1)
            )
            result = await session.execute(stmt)
            last_assistant = result.scalar_one_or_none()
            if not last_assistant:
                raise NotFoundException(f"会话无可重新生成的 assistant 消息")

            assistant_time = last_assistant.created_at

            # 找该 assistant 之前的最后一条 user 消息
            user_stmt = (
                select(Message)
                .where(
                    Message.conversation_id == conversation_id,
                    Message.message_type == "user",
                    Message.created_at < assistant_time,
                )
                .order_by(Message.created_at.desc())
                .limit(1)
            )
            user_result = await session.execute(user_stmt)
            last_user = user_result.scalar_one_or_none()
            if not last_user:
                # 如果该 assistant 是第一轮（之前没有 user）无法重生成
                raise BadRequestException("无法重新生成：找不到对应的用户输入消息")

            # 删除: assistant 消息 + 其后的 tool_call / tool_result 消息
            del_stmt = select(Message).where(
                Message.conversation_id == conversation_id,
                Message.created_at >= assistant_time,
            )
            to_delete = (await session.execute(del_stmt)).scalars().all()
            deleted_count = 0
            for m in to_delete:
                await session.delete(m)
                deleted_count += 1
            # 同步更新会话计数
            if deleted_count:
                await session.execute(
                    update(Conversation)
                    .where(Conversation.id == conversation_id)
                    .values(message_count=Conversation.message_count - deleted_count)
                )
            regenerate_content = last_user.content or ""
            agent_id = conv.agent_id
            logger.info(
                f"重新生成: conversation_id={conversation_id}, "
                f"deleted_messages={deleted_count}, "
                f"agent_id={agent_id}, content_len={len(regenerate_content)}"
            )
            await session.commit()

        # 委托给 chat() 进行流式重新生成
        async for event in self.chat(conversation_id, regenerate_content):
            yield event

    # ── 对话编排（非流式） ───────────────────────────

    async def chat_non_stream(
        self,
        conversation_id: str,
        content: str,
        workflow_mode: Optional[str] = None,
    ) -> dict[str, Any]:
        """非流式对话 - 返回完整响应 (P2 封装流式的收集)"""
        if not content or not content.strip():
            raise ValidationException("消息内容不能为空")

        collected_contents: list[str] = []
        last_done: dict = {}
        last_err: Optional[str] = None
        event_count = 0
        try:
            async for sse in self.chat(conversation_id, content, workflow_mode=workflow_mode):
                event_count += 1
                # 解析 SSE：简单按 event: xxx / data: {...} 拆分
                parsed = self._parse_sse_event(sse)
                if not parsed:
                    continue
                evt, data = parsed
                if evt == "message":
                    if isinstance(data, dict):
                        c = data.get("content", "")
                        if c and (not data.get("role") or data.get("role") == "assistant"):
                            collected_contents.append(c)
                elif evt == "done":
                    last_done = data if isinstance(data, dict) else {}
                    if isinstance(data, dict) and data.get("error"):
                        last_err = data["error"]
                elif evt == "error":
                    last_err = str(data) if data else "unknown error"
        except Exception as e:
            raise AppException(f"内部错误: {str(e)}")

        print(f"[DEBUG] chat_non_stream: events={event_count}, collected={len(collected_contents)} chunks, total_len={sum(len(c) for c in collected_contents)}")

        if last_err:
            raise AppException(last_err)

        full_text = "".join(collected_contents)
        return {
            "message_id": last_done.get("message_id", ""),
            "conversation_id": conversation_id,
            "content": full_text,
            "role": "assistant",
            "react_iterations": last_done.get("react_iterations", 0),
            "fallback": last_done.get("fallback", False),
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

    # ── SSE 构造与解析 ────────────────────────────────

    @staticmethod
    def _select_workflow_strategy(
        content: str,
        mcp_services: list[dict],
        skills: list[dict],
    ) -> str:
        """Hybrid 模式下：根据任务复杂度自动选择 ReAct 或 Plan-and-Execute

        返回:
            - "react"：简单/直接型任务，边想边做
            - "plan_and_execute"：复杂多步骤任务，先计划后执行
        """
        if not mcp_services and not skills:
            return "react"

        text = content.strip()

        # 1. 强触发词：明确的「调研/报告/方案/对比/选型/规划」类任务
        plan_keywords = (
            "调研", "调研报告", "深度调研", "市场调研", "用户调研",
            "分析", "深度分析", "根因分析", "竞品分析", "行业分析",
            "方案", "解决方案", "实施方案", "规划方案",
            "对比", "对比分析", "对比评测", "横向对比",
            "选型", "技术选型", "产品选型",
            "规划", "路线图", "roadmap", "计划", "策划",
            "综述", "研究", "可行性分析",
            "多轮检索", "系统化", "结构化", "专业报告",
            "撰写", "写一篇", "报告",
        )
        for kw in plan_keywords:
            if kw in text:
                return "plan_and_execute"

        # 2. 英文关键词
        en_plan_keywords = (
            "research", "deep research", "investigate", "analysis",
            "report", "comparison", "feasibility", "proposal",
            "solution", "roadmap", "plan", "strategy",
            "survey", "benchmark", "evaluation",
        )
        lower_text = text.lower()
        for kw in en_plan_keywords:
            if kw in lower_text:
                return "plan_and_execute"

        # 3. 结构信号：数字编号任务、长度较长、多子问题
        multi_step_markers = re.findall(r"^\s*[\d一二三四五六七八九十]+[.、)）]", text, re.MULTILINE)
        if len(multi_step_markers) >= 3:
            return "plan_and_execute"
        if len(text) >= 120 and any(k in text for k in ("分别", "依次", "分别是", "多个", "方面", "维度", "阶段")):
            return "plan_and_execute"

        # 4. 其余：走 ReAct（更灵活、响应更快）
        return "react"

    async def _generate_initial_plan(
        self,
        adapter,
        user_content: str,
        history: list,
        system_prompt: str,
        mcp_services: list[dict],
        skills: list[dict],
    ) -> dict[str, Any]:
        """Plan 阶段：让 LLM 基于用户任务和可用工具生成结构化执行计划。

        返回结构:
            {"summary": str, "steps": [{"id": int, "title": str, "description": str, "tools_needed": list[str]}]}
        """
        # 收集可用工具简介
        tool_intros: list[str] = []
        for mcp in mcp_services:
            mcp_name = mcp.get("name", "")
            for t in mcp.get("tools", []) or []:
                tname = t.get("name", "")
                tdesc = t.get("description", "") or ""
                tool_intros.append(f"- {tname} (来自 {mcp_name}): {tdesc[:80]}")
        for s in skills:
            sname = s.get("name", "")
            sdesc = s.get("description", "") or ""
            tool_intros.append(f"- Skill: {sname}: {sdesc[:80]}")

        plan_prompt = (
            "你是一个任务规划专家。请根据用户的问题与可用工具，生成一份结构化的执行计划。\n"
            "要求：\n"
            "1. 步骤总数控制在 3~7 步之间，每一步必须可执行；\n"
            "2. 每一步明确写出调用哪类工具/Skill；\n"
            "3. 最后一步必须是「综合并输出最终答案」。\n"
            f"可用工具/Skill: \n{chr(10).join(tool_intros[-24:]) if tool_intros else '(无)'}\n\n"
            f"用户问题:\n{user_content}\n\n"
            "请以 JSON 格式返回，不要输出多余内容：\n"
            "{\n"
            '  "summary": "一句话概述整体策略",\n'
            '  "steps": [\n'
            '    {"id": 1, "title": "步骤标题", "description": "要做什么（1-2句话）", "tools_needed": ["tool_name_1"]}\n'
            "  ]\n"
            "}"
        )

        try:
            messages = [
                {"role": "system", "content": "你是一个任务规划专家，仅输出 JSON，不要输出任何解释。"},
                {"role": "user", "content": plan_prompt},
            ]
            llm = adapter._create_llm()
            try:
                resp = await llm.ainvoke(messages)
            except Exception:
                resp = ""
                async for chunk in adapter.stream(messages):
                    if isinstance(chunk, str):
                        resp += chunk
                    elif isinstance(chunk, tuple) and len(chunk) == 2:
                        _, c = chunk
                        if isinstance(c, str):
                            resp += c

            raw_text = ""
            if isinstance(resp, str):
                raw_text = resp
            else:
                raw_text = getattr(resp, "content", "") or ""
                if isinstance(raw_text, list):
                    raw_text = "".join(str(x) for x in raw_text if isinstance(x, str))

            json_str = ChatService._extract_json_block(raw_text)
            if json_str:
                parsed = json.loads(json_str)
                if isinstance(parsed, dict) and isinstance(parsed.get("steps"), list):
                    normalized_steps: list[dict] = []
                    for idx, s in enumerate(parsed["steps"][:8], start=1):
                        if not isinstance(s, dict):
                            continue
                        normalized_steps.append({
                            "id": int(s.get("id", idx) or idx),
                            "title": str(s.get("title", f"步骤 {idx}")).strip()[:80],
                            "description": str(s.get("description", "")).strip()[:300],
                            "tools_needed": list(s.get("tools_needed", []) or [])[:5],
                        })
                    summary = str(parsed.get("summary", "")).strip()[:300]
                    if normalized_steps and normalized_steps[-1].get("title", ""):
                        last_title = normalized_steps[-1]["title"]
                        if not any(k in last_title for k in ("总结", "综合", "最终", "输出", "回答", "报告")):
                            normalized_steps.append({
                                "id": len(normalized_steps) + 1,
                                "title": "综合并输出最终回答",
                                "description": "根据前面步骤收集的信息，整理成结构化、完整的最终答案。",
                                "tools_needed": [],
                            })
                    return {
                        "summary": summary or f"执行 {len(normalized_steps)} 个步骤完成任务",
                        "steps": normalized_steps,
                    }
        except Exception as e:
            logger.warning(f"[DEBUG] 生成 Plan 失败，降级为 ReAct: {e}")

        fallback_steps = [
            {"id": 1, "title": "理解问题并收集初始信息", "description": "通过搜索和查阅工具收集用户问题相关的基础资料。", "tools_needed": []},
            {"id": 2, "title": "补充细节与交叉验证", "description": "针对初步资料缺失的细节进行补充检索和交叉验证。", "tools_needed": []},
            {"id": 3, "title": "综合并输出最终回答", "description": "基于已收集信息，整理输出结构化的完整回答。", "tools_needed": []},
        ]
        return {
            "summary": "Plan 生成阶段失败，使用通用兜底计划；执行中以 ReAct 灵活调整。",
            "steps": fallback_steps,
        }

    @staticmethod
    def _extract_json_block(text: str) -> Optional[str]:
        """从模型输出中抽取最外层 {...} JSON 块"""
        if not text:
            return None
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
            if m:
                inner = m.group(1).strip()
                s = inner.find("{")
                e = inner.rfind("}")
                if s != -1 and e != -1:
                    return inner[s:e+1]
            return None
        return text[start:end+1]

    @staticmethod
    async def _stream_text_chunks(text: str, chunk_size: int = 8) -> AsyncIterator[str]:
        """将长文本拆分为小块，模拟流式输出"""
        if not text:
            return
        # 按字符数拆分，支持中文字符
        for i in range(0, len(text), chunk_size):
            chunk = text[i:i + chunk_size]
            if chunk:
                yield chunk
                # 模拟微小延迟，实现流式效果（实际部署时可去掉）
                await asyncio.sleep(0.005)

    @staticmethod
    def _sse_event(event: str, payload: dict) -> str:
        """构造带 event: 前缀的 SSE 事件 (P2 标准格式)"""
        return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    @staticmethod
    def _sse(payload: dict) -> str:
        """兼容 P1 的 SSE 格式（无 event 前缀），不再在 chat 中使用但保留给外部"""
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    @staticmethod
    def _parse_sse_event(raw: str) -> Optional[tuple[str, Any]]:
        """简单解析单条 SSE 事件 → (event_name, data_obj)"""
        event_name = "data"
        data_str: Optional[str] = None
        for line in raw.splitlines():
            line = line.rstrip("\r")
            if line.startswith("event:"):
                event_name = line[len("event:"):].strip()
            elif line.startswith("data:"):
                data_str = line[len("data:"):].strip()
        if data_str is None:
            return None
        try:
            data_obj = json.loads(data_str)
        except Exception:
            data_obj = data_str
        return event_name, data_obj

    # ── 内部工具 ──────────────────────────────────────

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
        tool_calls: Any = None,
        tool_results: Any = None,
        thinking: str = None,
    ) -> Message:
        """在当前 session 中持久化消息，并更新会话计数"""
        # 截断过大的内容（MEDIUMTEXT 最大 16MB，保险起见限制 500KB）
        MAX_CONTENT_LEN = 500 * 1024  # 500KB
        if content and len(content) > MAX_CONTENT_LEN:
            content = content[:MAX_CONTENT_LEN] + "\n\n... (内容已截断)"
        if thinking and len(thinking) > MAX_CONTENT_LEN:
            thinking = thinking[:MAX_CONTENT_LEN] + "\n\n... (思考内容已截断)"
        # 截断 tool_calls / tool_results JSON
        if tool_calls:
            tc_json = json.dumps(tool_calls, ensure_ascii=False, default=str)
            if len(tc_json) > MAX_CONTENT_LEN:
                tool_calls = {"_truncated": True, "note": "tool_calls 数据已截断", "preview": tc_json[:1000]}
        if tool_results:
            # 只保留关键信息，不存储完整结果
            if isinstance(tool_results, dict) and "results" in tool_results:
                simplified = []
                for tr in tool_results.get("results", []):
                    simplified.append({
                        "tool_name": tr.get("tool_name", ""),
                        "status": tr.get("status", "failed"),
                        "duration_ms": tr.get("duration_ms", 0),
                        "error": (tr.get("error", "") or "")[:500],
                    })
                tool_results = {"results": simplified}
            tr_json = json.dumps(tool_results, ensure_ascii=False, default=str)
            if len(tr_json) > MAX_CONTENT_LEN:
                tool_results = {"_truncated": True, "note": "tool_results 数据已截断"}

        msg = Message(
            id=uuid.uuid4().hex,
            conversation_id=conversation_id,
            message_type=message_type,
            content=content,
            thinking=thinking,
            tool_calls=tool_calls,
            tool_results=tool_results,
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
        tool_calls: Any = None,
        tool_results: Any = None,
        thinking: str = None,
    ) -> Message:
        """使用独立 session 持久化消息（用于流式生成完成后）"""
        async with AsyncSessionLocal() as session:
            try:
                msg = await self._persist_message(
                    session,
                    conversation_id=conversation_id,
                    message_type=message_type,
                    content=content,
                    tool_calls=tool_calls,
                    tool_results=tool_results,
                    thinking=thinking,
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
    async def _conv_to_out(conv: Conversation, agent_name: str = "") -> ConversationOut:
        return ConversationOut(
            id=conv.id,
            agent_id=conv.agent_id,
            agent_name=agent_name,
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
            thinking=msg.thinking,
            tool_calls=msg.tool_calls,
            tool_results=msg.tool_results,
            token_count=msg.token_count or 0,
            created_at=msg.created_at,
        )


chat_service = ChatService()
