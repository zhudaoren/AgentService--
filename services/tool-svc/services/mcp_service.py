"""MCP 业务服务 - 单例类，负责 MCP CRUD + 连接管理 + 工具调用 + 日志"""
import time
import uuid
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.mysql import insert as mysql_insert

from common.exceptions import (
    NotFoundException,
    ValidationException,
    BadRequestException,
)
from common.logger import get_logger
from common.schemas import (
    MCPServiceCreate,
    MCPServiceUpdate,
    MCPServiceOut,
    MCPToolOut,
    ToolCallLogOut,
)
from domain.models import MCPService, MCPTool, ToolCallLog
from domain.mcp_adapter import create_mcp_adapter, IMCPAdapter, MCPException, MCPConnectException

logger = get_logger(__name__)


class MCPServiceMgr:
    """MCP 业务服务（单例）"""

    def __init__(self):
        self._adapters: dict[str, IMCPAdapter] = {}

    # ── CRUD ──────────────────────────────────────────

    async def list(
        self,
        db: AsyncSession,
        page: int = 1,
        page_size: int = 20,
        keyword: Optional[str] = None,
        mode: Optional[str] = None,
        status: Optional[str] = None,
    ) -> tuple[list[MCPServiceOut], int]:
        conditions = []
        if keyword:
            like = f"%{keyword}%"
            conditions.append(or_(MCPService.name.like(like), MCPService.description.like(like)))
        if mode:
            conditions.append(MCPService.mode == mode)
        if status:
            conditions.append(MCPService.status == status)

        count_stmt = select(func.count(MCPService.id))
        for cond in conditions:
            count_stmt = count_stmt.where(cond)
        total = (await db.execute(count_stmt)).scalar() or 0

        list_stmt = (
            select(MCPService)
            .order_by(MCPService.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        for cond in conditions:
            list_stmt = list_stmt.where(cond)
        result = await db.execute(list_stmt)
        items = result.scalars().all()
        outs = [await self._to_out(m) for m in items]
        return outs, total

    async def create(
        self, db: AsyncSession, payload: MCPServiceCreate
    ) -> MCPServiceOut:
        mode = (payload.mode or "").lower()
        if mode not in ("sse", "stdio"):
            raise ValidationException("mode 必须是 sse 或 stdio")
        if mode == "sse":
            if not payload.sse_url:
                raise ValidationException("SSE 模式下 sse_url 必填")
        elif mode == "stdio":
            stdio_cfg = payload.stdio_config or {}
            if not stdio_cfg.get("command"):
                raise ValidationException("STDIO 模式下 stdio_config.command 必填")

        mcp_id = uuid.uuid4().hex
        mcp = MCPService(
            id=mcp_id,
            name=payload.name,
            description=payload.description or "",
            mode=mode,
            sse_url=payload.sse_url if mode == "sse" else None,
            stdio_config=payload.stdio_config if mode == "stdio" else None,
            status="disconnected",
            error_message="",
        )
        db.add(mcp)
        await db.flush()
        logger.info(f"创建MCP服务: id={mcp_id}, name={payload.name}, mode={mode}")
        return await self._to_out(mcp)

    async def get(self, db: AsyncSession, mcp_id: str) -> MCPServiceOut:
        mcp = await self._get_by_id(db, mcp_id)
        return await self._to_out(mcp)

    async def update(
        self, db: AsyncSession, mcp_id: str, payload: MCPServiceUpdate
    ) -> MCPServiceOut:
        mcp = await self._get_by_id(db, mcp_id)
        data = payload.model_dump(exclude_unset=True)
        for k, v in data.items():
            setattr(mcp, k, v)
        await db.flush()
        logger.info(f"更新MCP服务: id={mcp_id}")
        return await self._to_out(mcp)

    async def delete(self, db: AsyncSession, mcp_id: str) -> None:
        mcp = await self._get_by_id(db, mcp_id)
        if mcp_id in self._adapters:
            try:
                await self._adapters[mcp_id].disconnect()
            except Exception as e:
                logger.warning(f"断开MCP连接失败(忽略): {e}")
            del self._adapters[mcp_id]
        await db.delete(mcp)
        await db.flush()
        logger.info(f"删除MCP服务: id={mcp_id}")

    # ── 连接管理 ──────────────────────────────────────

    async def connect(self, db: AsyncSession, mcp_id: str) -> dict:
        mcp = await self._get_by_id(db, mcp_id)
        adapter = self._get_or_create_adapter(mcp)
        try:
            mcp.status = "connecting"
            await db.flush()
            await adapter.connect()
            mcp.status = "connected"
            mcp.error_message = ""
            mcp.last_connected_at = datetime.utcnow()
            await db.flush()
            logger.info(f"MCP连接成功: id={mcp_id}, name={mcp.name}")
            return {"status": "connected", "mcp_id": mcp_id}
        except (MCPConnectException, MCPException, Exception) as e:
            mcp.status = "error"
            mcp.error_message = str(e)
            await db.flush()
            logger.error(f"MCP连接失败: id={mcp_id}, err={e}")
            raise BadRequestException(f"MCP连接失败: {str(e)}")

    async def disconnect(self, db: AsyncSession, mcp_id: str) -> None:
        mcp = await self._get_by_id(db, mcp_id)
        if mcp_id in self._adapters:
            try:
                await self._adapters[mcp_id].disconnect()
            except Exception as e:
                logger.warning(f"断开MCP异常(忽略): {e}")
            del self._adapters[mcp_id]
        mcp.status = "disconnected"
        mcp.error_message = ""
        await db.flush()
        logger.info(f"MCP已断开: id={mcp_id}")

    def _get_or_create_adapter(self, mcp: MCPService) -> IMCPAdapter:
        if mcp.id in self._adapters:
            return self._adapters[mcp.id]
        kwargs = {}
        if mcp.mode == "sse":
            kwargs["url"] = mcp.sse_url or ""
        elif mcp.mode == "stdio":
            cfg = mcp.stdio_config or {}
            kwargs["command"] = cfg.get("command", "")
            kwargs["args"] = cfg.get("args") or []
            kwargs["env"] = cfg.get("env") or None
        adapter = create_mcp_adapter(mcp.mode, **kwargs)
        self._adapters[mcp.id] = adapter
        return adapter

    # ── 工具发现/列表/启用禁用 ─────────────────────────

    async def discover_tools(self, db: AsyncSession, mcp_id: str) -> list[dict]:
        mcp = await self._get_by_id(db, mcp_id)
        adapter = self._get_or_create_adapter(mcp)
        if not adapter.is_connected:
            await adapter.connect()
        raw_tools = await adapter.list_tools()
        normalized = []
        for t in raw_tools:
            if isinstance(t, dict):
                name = t.get("name") or t.get("toolName") or ""
                description = t.get("description") or t.get("desc") or ""
                input_schema = t.get("inputSchema") or t.get("input_schema") or {}
            else:
                continue
            if not name:
                continue
            normalized.append({
                "mcp_service_id": mcp_id,
                "name": name,
                "description": description,
                "input_schema": input_schema if isinstance(input_schema, dict) else {},
            })

        if normalized:
            await self._bulk_upsert_tools(db, normalized)

        logger.info(f"MCP工具发现完成: mcp_id={mcp_id}, count={len(normalized)}")
        return normalized

    async def _bulk_upsert_tools(
        self, db: AsyncSession, tools: list[dict]
    ) -> None:
        for t in tools:
            stmt = mysql_insert(MCPTool).values(
                id=uuid.uuid4().hex,
                mcp_service_id=t["mcp_service_id"],
                name=t["name"],
                description=t.get("description", ""),
                input_schema=t.get("input_schema", {}),
                enabled=True,
                usage_count=0,
            )
            on_update = stmt.on_duplicate_key_update(
                description=stmt.inserted.description,
                input_schema=stmt.inserted.input_schema,
            )
            await db.execute(on_update)
        await db.flush()

    async def list_tools(
        self,
        db: AsyncSession,
        mcp_id: str,
        enabled: Optional[bool] = None,
    ) -> list[MCPToolOut]:
        _ = await self._get_by_id(db, mcp_id)
        stmt = select(MCPTool).where(MCPTool.mcp_service_id == mcp_id)
        if enabled is not None:
            stmt = stmt.where(MCPTool.enabled == enabled)
        stmt = stmt.order_by(MCPTool.created_at.asc())
        result = await db.execute(stmt)
        tools = result.scalars().all()
        return [await self._tool_to_out(t) for t in tools]

    async def toggle_tool(
        self, db: AsyncSession, mcp_id: str, tool_name: str, enabled: bool
    ) -> MCPToolOut:
        stmt = select(MCPTool).where(
            MCPTool.mcp_service_id == mcp_id, MCPTool.name == tool_name
        )
        result = await db.execute(stmt)
        tool = result.scalar_one_or_none()
        if not tool:
            raise NotFoundException(f"工具不存在: mcp={mcp_id}, tool={tool_name}")
        tool.enabled = enabled
        await db.flush()
        logger.info(f"工具启用状态变更: tool={tool_name}, enabled={enabled}")
        return await self._tool_to_out(tool)

    # ── 工具调用 + 日志 ───────────────────────────────

    async def call_tool(
        self,
        db: AsyncSession,
        tool_name: str,
        arguments: Optional[dict] = None,
        timeout: int = 30,
        mcp_service_id: Optional[str] = None,
        mcp_service_name: Optional[str] = None,
        agent_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> tuple[Any, int]:
        mcp = None
        if mcp_service_id:
            mcp = await self._get_by_id(db, mcp_service_id)
        elif mcp_service_name:
            stmt = select(MCPService).where(MCPService.name == mcp_service_name).limit(1)
            result = await db.execute(stmt)
            mcp = result.scalar_one_or_none()
            if not mcp:
                raise NotFoundException(f"MCP服务不存在: name={mcp_service_name}")
        else:
            raise ValidationException("必须提供 mcp_service_id 或 mcp_service_name")

        adapter = self._get_or_create_adapter(mcp)
        if not adapter.is_connected:
            try:
                await adapter.connect()
                mcp.status = "connected"
                mcp.error_message = ""
                mcp.last_connected_at = datetime.utcnow()
                await db.flush()
            except Exception as e:
                mcp.status = "error"
                mcp.error_message = str(e)
                await db.flush()
                raise BadRequestException(f"MCP自动连接失败: {str(e)}")

        tool_stmt = select(MCPTool).where(
            MCPTool.mcp_service_id == mcp.id, MCPTool.name == tool_name
        )
        tool_result = await db.execute(tool_stmt)
        mcp_tool = tool_result.scalar_one_or_none()
        if mcp_tool and not mcp_tool.enabled:
            raise BadRequestException(f"工具已禁用: {tool_name}")

        call_timeout = timeout or 30
        start = time.time()
        status = "success"
        result_obj: Any = None
        error_message = ""
        try:
            result_obj = await adapter.call_tool(
                tool_name, arguments or {}, timeout=call_timeout
            )
            if mcp_tool:
                mcp_tool.usage_count = (mcp_tool.usage_count or 0) + 1
        except Exception as e:
            status = "failed"
            error_message = str(e)
            logger.error(f"工具调用失败: tool={tool_name}, err={e}")
            raise
        finally:
            duration_ms = int((time.time() - start) * 1000)
            try:
                log_id = uuid.uuid4().hex
                result_str = ""
                if result_obj is not None:
                    try:
                        if isinstance(result_obj, (dict, list)):
                            import json as _json
                            result_str = _json.dumps(result_obj, ensure_ascii=False)
                        else:
                            result_str = str(result_obj)
                    except Exception:
                        result_str = str(result_obj)
                log = ToolCallLog(
                    id=log_id,
                    agent_id=agent_id,
                    conversation_id=conversation_id,
                    mcp_service_id=mcp.id,
                    tool_name=tool_name,
                    arguments=arguments or {},
                    result=result_str,
                    status=status,
                    duration_ms=duration_ms,
                    error_message=error_message,
                    created_at=datetime.utcnow(),
                )
                db.add(log)
                await db.flush()
            except Exception as log_e:
                logger.warning(f"写入工具调用日志失败(忽略): {log_e}")
        return result_obj, duration_ms

    async def list_tool_call_logs(
        self,
        db: AsyncSession,
        page: int = 1,
        page_size: int = 20,
        agent_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        mcp_service_id: Optional[str] = None,
        status: Optional[str] = None,
        tool_name: Optional[str] = None,
    ) -> tuple[list[ToolCallLogOut], int]:
        conditions = []
        if agent_id:
            conditions.append(ToolCallLog.agent_id == agent_id)
        if conversation_id:
            conditions.append(ToolCallLog.conversation_id == conversation_id)
        if mcp_service_id:
            conditions.append(ToolCallLog.mcp_service_id == mcp_service_id)
        if status:
            conditions.append(ToolCallLog.status == status)
        if tool_name:
            conditions.append(ToolCallLog.tool_name.like(f"%{tool_name}%"))

        count_stmt = select(func.count(ToolCallLog.id))
        for c in conditions:
            count_stmt = count_stmt.where(c)
        total = (await db.execute(count_stmt)).scalar() or 0

        list_stmt = (
            select(ToolCallLog)
            .order_by(ToolCallLog.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        for c in conditions:
            list_stmt = list_stmt.where(c)
        result = await db.execute(list_stmt)
        logs = result.scalars().all()
        outs = []
        for log in logs:
            outs.append(ToolCallLogOut(
                id=log.id,
                agent_id=log.agent_id,
                conversation_id=log.conversation_id,
                mcp_service_id=log.mcp_service_id,
                tool_name=log.tool_name,
                arguments=log.arguments or {},
                result=log.result or "",
                status=log.status,
                duration_ms=log.duration_ms,
                error_message=log.error_message or "",
                created_at=log.created_at,
            ))
        return outs, total

    # ── 内部工具 ──────────────────────────────────────

    async def _get_by_id(self, db: AsyncSession, mcp_id: str) -> MCPService:
        stmt = select(MCPService).where(MCPService.id == mcp_id)
        result = await db.execute(stmt)
        mcp = result.scalar_one_or_none()
        if not mcp:
            raise NotFoundException(f"MCP服务不存在: {mcp_id}")
        return mcp

    async def _to_out(self, mcp: MCPService) -> MCPServiceOut:
        return MCPServiceOut(
            id=mcp.id,
            name=mcp.name,
            description=mcp.description or "",
            mode=mcp.mode,
            sse_url=mcp.sse_url or "",
            stdio_config=mcp.stdio_config or {},
            status=mcp.status,
            error_message=mcp.error_message or "",
            last_connected_at=mcp.last_connected_at,
            created_at=mcp.created_at,
            updated_at=mcp.updated_at,
        )

    async def _tool_to_out(self, tool: MCPTool) -> MCPToolOut:
        return MCPToolOut(
            id=tool.id,
            mcp_service_id=tool.mcp_service_id,
            name=tool.name,
            description=tool.description or "",
            input_schema=tool.input_schema or {},
            enabled=bool(tool.enabled),
            usage_count=tool.usage_count or 0,
            created_at=tool.created_at,
            updated_at=tool.updated_at,
        )


mcp_service = MCPServiceMgr()
