"""MCP (Model Context Protocol) 适配器

基于 mcp SDK 的 ClientSession 实现，支持三种接入模式：
  - SSE (Server-Sent Events)：HTTP + SSE 流式协议 (Legacy)
  - Streamable HTTP：HTTP 流式协议 (推荐)
  - STDIO：子进程标准输入输出 + JSON-RPC 2.0
"""
from __future__ import annotations

import os
import shlex
from abc import ABC, abstractmethod
from contextlib import AsyncExitStack
from typing import Any, Optional

from mcp.client.session import ClientSession
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client
from mcp.client.stdio import stdio_client, StdioServerParameters

from common.logger import get_logger
from common.exceptions import AppException

logger = get_logger(__name__)


def _extract_error(e: Exception) -> str:
    """从 ExceptionGroup / TaskGroup 中提取真实异常信息"""
    if hasattr(e, "exceptions"):
        sub_msgs = [_extract_error(sub) for sub in e.exceptions]
        return "; ".join(sub_msgs) if sub_msgs else str(e) or type(e).__name__
    msg = str(e)
    if msg:
        return msg
    # str(e) 为空时，使用异常类型和 repr 作为备选
    return f"{type(e).__name__}: {repr(e)}"


class MCPException(AppException):
    """MCP 调用异常"""
    code = 9101
    message = "MCP调用失败"
    status_code = 500


class MCPConnectException(MCPException):
    """MCP 连接异常"""
    code = 9102
    message = "MCP连接失败"


class IMCPAdapter(ABC):
    """MCP 适配器抽象基类"""

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """是否已连接"""
        ...

    @abstractmethod
    async def connect(self) -> None:
        """建立连接"""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """断开连接"""
        ...

    @abstractmethod
    async def list_tools(self) -> list[dict]:
        """列出所有工具

        Returns:
            工具列表，每个工具为 dict，包含 name/description/input_schema 等
        """
        ...

    @abstractmethod
    async def call_tool(self, tool_name: str, arguments: dict, timeout: int = 30) -> Any:
        """调用工具

        Args:
            tool_name: 工具名称
            arguments: 工具参数字典
            timeout: 超时时间(秒)

        Returns:
            工具调用结果
        """
        ...


class MCPSDKAdapter(IMCPAdapter):
    """基于 mcp SDK ClientSession 的适配器基类

    使用 AsyncExitStack 管理 transport 与 ClientSession 的异步上下文生命周期。
    子类只需实现 ``_create_transport`` 与 ``_log_target``。

    Mcp-Session-Id 会话管理:
      - Streamable HTTP 模式下, 连接成功后通过 ``get_session_id`` 回调获取会话 ID
      - 会话 ID 由服务器在 initialize 握手时通过响应头返回
      - 后续请求由 SDK 自动携带 Mcp-Session-Id 头
      - 通过 ``session_id`` 属性可获取当前会话 ID (用于监控/日志)
      - ``is_session_invalidated()`` 检测会话是否因服务器端失效需要重建
    """

    def __init__(self, timeout: int = 30):
        self._timeout = timeout
        self._connected = False
        self._stack: Optional[AsyncExitStack] = None
        self._session: Optional[ClientSession] = None
        # Mcp-Session-Id 会话管理
        self._get_session_id: Optional[Any] = None  # streamable_http 返回的回调
        self._session_invalidated: bool = False  # 标记会话是否已失效

    @property
    def is_connected(self) -> bool:
        return self._connected and self._session is not None

    @property
    def session_id(self) -> Optional[str]:
        """获取当前 Mcp-Session-Id (仅 Streamable HTTP 模式有效)"""
        if self._get_session_id is not None:
            try:
                return self._get_session_id()
            except Exception:
                return None
        return None

    @property
    def is_session_invalidated(self) -> bool:
        """会话是否已失效, 需要重建连接"""
        return self._session_invalidated

    def mark_session_invalidated(self) -> None:
        """标记当前会话已失效 (由上层在检测到 404/Session Not Found 时调用)"""
        self._session_invalidated = True

    @abstractmethod
    def _create_transport(self):
        """创建并返回 transport 异步上下文管理器

        由子类实现，返回 sse_client / streamable_http_client / stdio_client 的调用结果。
        该上下文 yield ``(read_stream, write_stream[, ...])``。
        """
        ...

    @abstractmethod
    def _log_target(self) -> str:
        """返回用于日志标识的连接目标描述"""
        ...

    async def connect(self) -> None:
        if self._connected and not self._session_invalidated:
            return
        # 会话失效时先清理旧连接再重建
        if self._session_invalidated:
            logger.info(f"MCP 会话已失效, 重建连接: {self._log_target()}")
            await self._close_stack()
            self._connected = False
            self._session_invalidated = False
            self._get_session_id = None
        if self._connected:
            return
        try:
            self._stack = AsyncExitStack()
            transport = self._create_transport()
            transport_result = await self._stack.enter_async_context(transport)
            # sse/stdio yield (read, write); streamable_http yield (read, write, get_session_id)
            read_stream, write_stream = transport_result[0], transport_result[1]
            # Streamable HTTP 模式: 提取 get_session_id 回调用于 Mcp-Session-Id 管理
            if len(transport_result) >= 3:
                self._get_session_id = transport_result[2]
            self._session = await self._stack.enter_async_context(
                ClientSession(read_stream, write_stream)
            )
            await self._session.initialize()
            self._connected = True
            sid = self.session_id
            if sid:
                logger.info(f"MCP 连接成功: {self._log_target()}, session_id={sid}")
            else:
                logger.info(f"MCP 连接成功: {self._log_target()}")
        except MCPConnectException:
            await self._close_stack()
            self._connected = False
            self._get_session_id = None
            raise
        except Exception as e:
            await self._close_stack()
            self._connected = False
            self._get_session_id = None
            error_msg = _extract_error(e)
            logger.error(f"MCP 连接失败: {self._log_target()}, err={error_msg}")
            raise MCPConnectException(f"MCP连接失败: {error_msg}")

    async def _close_stack(self) -> None:
        if self._stack is not None:
            try:
                await self._stack.aclose()
            except Exception as e:
                logger.warning(f"关闭MCP上下文栈异常(忽略): {e}")
            self._stack = None
        self._session = None
        self._get_session_id = None

    async def disconnect(self) -> None:
        await self._close_stack()
        self._connected = False
        self._session_invalidated = False
        logger.info(f"MCP 已断开: {self._log_target()}")

    @staticmethod
    def _is_session_error(e: Exception) -> bool:
        """检测异常是否表示 Mcp-Session-Id 会话已失效 (需重建)

        常见场景:
          - HTTP 404 Session Not Found
          - HTTP 400 with "session" in message
          - 服务器主动终止会话
        """
        err_msg = str(e).lower()
        keywords = (
            "session not found",
            "session expired",
            "session invalid",
            "invalid session",
            "session id",
            "mcp-session-id",
        )
        if any(kw in err_msg for kw in keywords):
            return True
        # 404 通常表示 session 不存在
        if "404" in err_msg and "session" in err_msg:
            return True
        # ExceptionGroup 中递归检测
        if hasattr(e, "exceptions"):
            return any(MCPSDKAdapter._is_session_error(sub) for sub in e.exceptions)
        return False

    async def list_tools(self) -> list[dict]:
        if not self.is_connected:
            raise MCPException("MCP未连接，请先connect")
        try:
            result = await self._session.list_tools()
            tools: list[dict] = []
            for tool in result.tools:
                tool_dict = tool.model_dump() if hasattr(tool, "model_dump") else dict(tool)
                # mcp SDK Tool 字段为 inputSchema (camelCase)，统一转为 input_schema
                if "inputSchema" in tool_dict:
                    tool_dict["input_schema"] = tool_dict.pop("inputSchema")
                tools.append(tool_dict)
            return tools
        except MCPException:
            raise
        except Exception as e:
            # 检测 Mcp-Session-Id 会话失效
            if self._is_session_error(e):
                self._session_invalidated = True
                logger.warning(f"MCP 会话已失效 (list_tools): {self._log_target()}")
            error_msg = _extract_error(e)
            logger.error(f"MCP list_tools 调用失败: {self._log_target()}, err={error_msg}")
            raise MCPException(f"获取工具列表失败: {error_msg}")

    async def call_tool(self, tool_name: str, arguments: dict, timeout: int = 30) -> Any:
        if not self.is_connected:
            raise MCPException("MCP未连接，请先connect")
        try:
            result = await self._session.call_tool(tool_name, arguments or {})
            return result.model_dump()
        except MCPException:
            raise
        except Exception as e:
            # 检测 Mcp-Session-Id 会话失效
            if self._is_session_error(e):
                self._session_invalidated = True
                logger.warning(
                    f"MCP 会话已失效 (call_tool={tool_name}): {self._log_target()}"
                )
            error_msg = _extract_error(e)
            logger.error(
                f"MCP call_tool 失败 tool={tool_name}: {self._log_target()}, err={error_msg}, "
                f"exc_type={type(e).__name__}",
                exc_info=True,
            )
            raise MCPException(f"调用工具 {tool_name} 失败: {error_msg}")


class SSEAdapter(MCPSDKAdapter):
    """SSE 模式适配器 (Legacy) - 通过 HTTP + SSE 与 MCP 服务通信"""

    def __init__(self, url: str, headers: Optional[dict] = None, timeout: int = 30):
        super().__init__(timeout=timeout)
        self._url = url.rstrip("/") if url else ""
        self._headers = headers or {}

    def _create_transport(self):
        if not self._url:
            raise MCPConnectException("SSE模式缺少url参数")
        return sse_client(self._url, headers=self._headers, timeout=30.0, sse_read_timeout=300.0)

    def _log_target(self) -> str:
        return f"url={self._url}"


class StreamableHTTPAdapter(MCPSDKAdapter):
    """Streamable HTTP 模式适配器 (推荐) - 通过 HTTP 流式协议与 MCP 服务通信"""

    def __init__(self, url: str, headers: Optional[dict] = None, timeout: int = 30):
        super().__init__(timeout=timeout)
        self._url = url.rstrip("/") if url else ""
        self._headers = headers or {}
        self._http_client = None  # 自定义 httpx client（用于传递 headers/auth）

    def _create_transport(self):
        if not self._url:
            raise MCPConnectException("Streamable HTTP模式缺少url参数")
        # streamable_http_client 不直接支持 headers 参数，
        # 需通过 http_client 参数传入预配置的 httpx.AsyncClient
        if self._headers:
            import httpx
            self._http_client = httpx.AsyncClient(
                headers=self._headers,
                timeout=httpx.Timeout(connect=30.0, read=180.0, write=30.0, pool=30.0),
            )
            return streamable_http_client(self._url, http_client=self._http_client)
        return streamable_http_client(self._url)

    async def disconnect(self) -> None:
        await self._close_stack()
        self._connected = False
        self._session_invalidated = False
        logger.info(f"MCP 已断开: {self._log_target()}")

    async def _close_stack(self) -> None:
        # 先关闭 MCP 上下文栈，再关闭自定义 httpx client
        await super()._close_stack()
        # streamable_http_client 不会关闭外部传入的 http_client，需手动关闭
        if self._http_client is not None:
            try:
                await self._http_client.aclose()
            except Exception as e:
                logger.warning(f"关闭 httpx client 异常(忽略): {e}")
            self._http_client = None

    def _log_target(self) -> str:
        return f"url={self._url}"


class STDIOAdapter(MCPSDKAdapter):
    """STDIO 模式适配器 - 通过子进程 stdin/stdout 通信"""

    def __init__(self, command: str, args: Optional[list] = None, env: Optional[dict] = None, timeout: int = 30):
        super().__init__(timeout=timeout)
        # 若 command 含空格且不是已存在的文件路径，用 shlex 拆分为 command + args (Windows 兼容)
        if command and " " in command and not os.path.exists(command):
            parts = shlex.split(command, posix=False)
            if parts:
                command = parts[0]
                extra_args = parts[1:]
                args = list(extra_args) + list(args or [])
        self._command = command or ""
        self._args = list(args or [])
        self._env = env or None

    def _create_transport(self):
        if not self._command:
            raise MCPConnectException("STDIO模式缺少command参数")
        params = StdioServerParameters(
            command=self._command,
            args=self._args,
            env=self._env,
        )
        return stdio_client(params)

    def _log_target(self) -> str:
        return f"command={self._command}, args={self._args}"


def create_mcp_adapter(mode: str, **kwargs) -> IMCPAdapter:
    """MCP 适配器工厂函数

    Args:
        mode: "sse" / "streamable_http" / "stdio"
        **kwargs:
            - SSE 模式: url(str), headers(dict, optional), timeout(int, optional)
            - Streamable HTTP 模式: url(str), headers(dict, optional), timeout(int, optional)
            - STDIO 模式: command(str), args(list, optional), env(dict, optional), timeout(int, optional)

    Returns:
        IMCPAdapter 实例

    Raises:
        MCPException: mode 不支持时抛出
    """
    mode_lower = (mode or "").lower()
    if mode_lower == "sse":
        url = kwargs.get("url", "")
        headers = kwargs.get("headers")
        timeout = kwargs.get("timeout", 30)
        return SSEAdapter(url=url, headers=headers, timeout=timeout)
    elif mode_lower == "streamable_http":
        url = kwargs.get("url", "")
        headers = kwargs.get("headers")
        timeout = kwargs.get("timeout", 30)
        return StreamableHTTPAdapter(url=url, headers=headers, timeout=timeout)
    elif mode_lower == "stdio":
        command = kwargs.get("command", "")
        args = kwargs.get("args", None)
        env = kwargs.get("env", None)
        timeout = kwargs.get("timeout", 30)
        return STDIOAdapter(command=command, args=args, env=env, timeout=timeout)
    else:
        raise MCPException(f"不支持的MCP模式: {mode}. 仅支持 sse / streamable_http / stdio")
