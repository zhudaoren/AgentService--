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
import asyncio
import json
import re
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
            self._tool_http_client = httpx.AsyncClient(timeout=10.0)
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
    ) -> AsyncIterator[str]:
        """流式对话核心 (P2: ReAct + Tool Calling) - SSE 事件流生成器

        输出 SSE 事件（每条以 \n\n 分隔）:
            event: message\ndata: {"role": "...", "content": "..."}\n\n
            event: tool_call\ndata: {"index":i,"tool_name","status","result","error"}\n\n
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

        # 11. 注册停止事件
        stop_event = asyncio.Event()
        self._stop_events[conversation_id] = stop_event

        # 12. (P2) ReAct 主循环
        react_messages_for_persist: list[Message] = []
        final_assistant_text = ""
        final_assistant_tool_calls: list[dict] = []
        fallback_used = False
        iteration_took = 0

        try:
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
                try:
                    if enable_react and llm_tool_defs and adapter.provider in ("openai", "deepseek", "moonshot", "kimi", "zhipu", "siliconflow", "glm"):
                        # Function calling 模式：尝试 with tools（失败降级为纯文本）
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
                                    elif typ == "tool_call":
                                        detected_tool_calls.append(val)
                                elif isinstance(chunk, str):
                                    if chunk:
                                        full_text_parts.append(chunk)
                        except Exception:
                            # 降级：纯文本流
                            async for chunk in adapter.stream(llm_messages):
                                if stop_event.is_set():
                                    break
                                if chunk:
                                    full_text_parts.append(chunk)
                    else:
                        # 纯文本 ReAct Prompt 模式
                        async for chunk in adapter.stream(llm_messages):
                            if stop_event.is_set():
                                break
                            if chunk:
                                full_text_parts.append(chunk)
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
                # 若是第一轮，将最终文本暂存（纯答案时用）
                if iteration == 0 or not final_assistant_text:
                    final_assistant_text = assistant_text

                # Step2: 判断是否需要工具调用
                has_tool_calls = bool(detected_tool_calls)
                if not has_tool_calls:
                    # 纯文本最终答案 → break 主循环
                    # 若是第一轮没有工具（P1兼容）直接流文本
                    if iteration == 0:
                        # 为了 P1 兼容：只流式推一次 message 事件（按块推？这里一次性，简单处理）
                        # 更好：按字符分片推模拟流（简单处理）
                        for i in range(0, len(assistant_text), 2):
                            if stop_event.is_set():
                                break
                            chunk_str = assistant_text[i:i + 2]
                            yield self._sse_event("message", {
                                "role": "assistant", "content": chunk_str,
                            })
                            await asyncio.sleep(0)
                    break

                # 有工具调用 → 执行工具 + SSE 推送 tool_call 事件
                # 将本轮 assistant 消息记入（附带 tool_calls 信息）
                final_assistant_tool_calls.extend(detected_tool_calls)
                if iteration == 0:
                    final_assistant_text = assistant_text

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
                    # SSE 推送 tool_call 事件
                    yield self._sse_event("tool_call", {
                        "index": idx,
                        "tool_name": tool_name,
                        "status": status,
                        "result": result_val,
                        "error": error_val,
                    })
                    tool_results_list.append(call_result)

                    # 持久化：tool_result 消息
                    tr_msg_content = (
                        f"[Tool Result] {tool_name}: {status}\n"
                        f"{result_val if result_val is not None else ''}\n"
                        f"{error_val if error_val else ''}".strip()
                    )
                    async with AsyncSessionLocal() as s3:
                        tr_msg = await self._persist_message(
                            s3,
                            conversation_id=conversation_id,
                            message_type="tool_result",
                            content=tr_msg_content,
                            tool_results={"results": tool_results_list},
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
                try:
                    async for chunk in adapter.stream(llm_messages):
                        if stop_event.is_set():
                            break
                        if chunk:
                            summary_parts.append(chunk)
                except Exception as e:
                    logger.warning(f"ReAct超限总结LLM调用失败: {e}")
                    summary_parts.append(final_assistant_text)
                final_assistant_text = "".join(summary_parts)
                # 按分片推送到前端
                for i in range(0, len(final_assistant_text), 2):
                    if stop_event.is_set():
                        break
                    yield self._sse_event("message", {
                        "role": "assistant",
                        "content": final_assistant_text[i:i + 2],
                    })
                    await asyncio.sleep(0)

        finally:
            self._stop_events.pop(conversation_id, None)

        # 13. 持久化最终 AI 回复
        tool_calls_for_save = None
        if final_assistant_tool_calls:
            tool_calls_for_save = {"calls": final_assistant_tool_calls}
        ai_msg = await self._persist_with_session(
            conversation_id,
            message_type="assistant",
            content=final_assistant_text,
            tool_calls=tool_calls_for_save,
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
        """尝试使用 bind_tools 流式输出，返回 ('content', str) 或 ('tool_call', dict) 或 str

        由于 langchain ChatOpenAI 的 astream with tools 会返回 AIMessageChunk，
        这里尝试用 invoke 一次+ 伪流式（简单实现）避免复杂解析。
        实际生产中建议用LangChain的完整streaming events。这里采用折中：
        - 先 invoke（带tools）拿完整 AIMessage
        - 再将内容按字符分片 yield 成 ('content', chunk)
        - 最后将 tool_calls 以 ('tool_call', {...}) yield
        """
        llm = adapter._create_llm()
        lc_messages = adapter._convert_messages(llm_messages)
        try:
            # bind tools (LangChain)
            try:
                bound = llm.bind_tools(tool_defs)
            except Exception:
                # 部分模型不支持 bind_tools → 降级为不带 tools 的流式
                async for chunk in adapter.stream(llm_messages):
                    yield chunk
                return
            response = await bound.ainvoke(lc_messages)
            # 分片 content
            content = getattr(response, "content", "") or ""
            if isinstance(content, str):
                for i in range(0, len(content), 2):
                    yield ("content", content[i:i + 2])
            # tool_calls
            resp_tcs = getattr(response, "tool_calls", None) or []
            for tc in resp_tcs:
                tc_name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)
                tc_args = tc.get("args") if isinstance(tc, dict) else getattr(tc, "args", {})
                if tc_name:
                    yield ("tool_call", {
                        "tool_name": tc_name,
                        "arguments": tc_args or {},
                    })
        except Exception:
            # 降级为纯流式
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

        # 去重（按 tool_name 合并优先级）
        return results[:4]

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
            tool_lines.append("说明：当你认为需要调用工具时，请使用 function calling 或按以下 ReAct 格式输出：")
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
            sections.append("\n".join(tool_lines))

        result = "\n\n".join(s for s in sections if s.strip())
        return result

    # ── (P2) 通过 HTTP 调用 tool-svc ─────────────────

    async def _call_tool_via_http(
        self, tool_call: dict, agent_id: str, conversation_id: str,
    ) -> dict:
        """调用 tool-svc POST /api/v1/tools/call

        失败或httpx不可用时，返回降级错误结构，不会抛异常。
        """
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
            "mcp_service_name": tool_call.get("mcp_service_name", ""),
            "tool_name": tool_name,
            "arguments": tool_call.get("arguments", {}) or {},
            "timeout": 60,
        }
        try:
            resp = await client.post(
                f"{self.TOOL_SVC_BASE}/api/v1/tools/call",
                json=payload,
                timeout=60.0,
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
                if isinstance(inner, dict):
                    return {
                        "tool_name": inner.get("tool_name", tool_name),
                        "status": inner.get("status", data.get("code", 0) == 0 and "success" or "failed"),
                        "result": inner.get("result"),
                        "error": inner.get("error_message", "") or inner.get("error", "") or data.get("message", ""),
                        "duration_ms": inner.get("duration_ms", elapsed),
                    }
            # 直接 ToolCallResponse 结构
            return {
                "tool_name": data.get("tool_name", tool_name) if isinstance(data, dict) else tool_name,
                "status": data.get("status", "success") if isinstance(data, dict) else "failed",
                "result": data.get("result") if isinstance(data, dict) else None,
                "error": (data.get("error_message", "") or data.get("error", "")) if isinstance(data, dict) else "",
                "duration_ms": (data.get("duration_ms", 0) if isinstance(data, dict) else 0) or elapsed,
            }
        except Exception as e:
            elapsed = int((time.time() - start) * 1000)
            logger.warning(f"调用tool-svc失败 (tool={tool_name}): {e}")
            return {
                "tool_name": tool_name,
                "status": "failed",
                "result": None,
                "error": "工具服务不可用，已跳过工具调用",
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
    ) -> dict[str, Any]:
        """非流式对话 - 返回完整响应 (P2 封装流式的收集)"""
        if not content or not content.strip():
            raise ValidationException("消息内容不能为空")

        collected_contents: list[str] = []
        last_done: dict = {}
        last_err: Optional[str] = None
        try:
            async for sse in self.chat(conversation_id, content):
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
        except Exception as e:
            raise AppException(f"内部错误: {str(e)}")

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
    ) -> Message:
        """在当前 session 中持久化消息，并更新会话计数"""
        msg = Message(
            id=uuid.uuid4().hex,
            conversation_id=conversation_id,
            message_type=message_type,
            content=content,
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
