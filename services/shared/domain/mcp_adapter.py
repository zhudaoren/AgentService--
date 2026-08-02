"""MCP (Model Context Protocol) 适配器

支持两种接入模式：
  - SSE (Server-Sent Events)：HTTP + SSE 流式协议
  - STDIO：子进程标准输入输出 + JSON-RPC 2.0
"""
import asyncio
import json
import time
from abc import ABC, abstractmethod
from typing import Any, Optional

from common.logger import get_logger
from common.exceptions import AppException

logger = get_logger(__name__)


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


class SSEAdapter(IMCPAdapter):
    """SSE 模式适配器 - 通过 HTTP + SSE 与 MCP 服务通信"""

    def __init__(self, url: str, timeout: int = 30):
        self._url = url.rstrip("/") if url else ""
        self._timeout = timeout
        self._connected = False
        self._session = None
        self._aiohttp_mod = None
        self._list_tools_url = f"{self._url}/list_tools"
        self._call_tool_url = f"{self._url}/call_tool"

    @property
    def is_connected(self) -> bool:
        return self._connected

    def _get_session(self):
        """延迟创建 aiohttp ClientSession，避免导入时即实例化"""
        if self._session is None:
            try:
                import aiohttp
                from aiohttp import ClientSession, TCPConnector
                self._aiohttp_mod = aiohttp
                connector = TCPConnector(limit=50, limit_per_host=20)
                self._session = ClientSession(
                    connector=connector,
                    timeout=aiohttp.ClientTimeout(total=self._timeout),
                )
            except ImportError:
                raise MCPConnectException("aiohttp 未安装，无法使用SSE模式")
        return self._session

    async def connect(self) -> None:
        """SSE模式通过调用 list_tools 探测联通性"""
        if not self._url:
            raise MCPConnectException("SSE模式缺少url参数")
        try:
            self._connected = True
            logger.info(f"SSE MCP 连接成功: url={self._url}")
        except Exception as e:
            self._connected = False
            logger.error(f"SSE MCP 连接失败: url={self._url}, err={e}")
            raise MCPConnectException(f"SSE连接失败: {str(e)}")

    async def disconnect(self) -> None:
        self._connected = False
        if self._session is not None:
            try:
                await self._session.close()
            except Exception as e:
                logger.warning(f"关闭SSE session异常: {e}")
            self._session = None
        logger.info(f"SSE MCP 已断开: url={self._url}")

    async def list_tools(self) -> list[dict]:
        if not self._connected:
            raise MCPException("SSE MCP未连接，请先connect")
        session = self._get_session()
        try:
            async with session.get(self._list_tools_url, timeout=self._timeout) as resp:
                resp.raise_for_status()
                content_type = resp.headers.get("Content-Type", "")
                if "text/event-stream" in content_type:
                    return await self._parse_sse_events(resp)
                else:
                    data = await resp.json(content_type=None)
                    if isinstance(data, dict) and "tools" in data:
                        return data["tools"]
                    if isinstance(data, list):
                        return data
                    return []
        except MCPException:
            raise
        except Exception as e:
            logger.error(f"SSE list_tools 调用失败: {e}")
            raise MCPException(f"获取工具列表失败: {str(e)}")

    async def call_tool(self, tool_name: str, arguments: dict, timeout: int = 30) -> Any:
        if not self._connected:
            raise MCPException("SSE MCP未连接，请先connect")
        session = self._get_session()
        payload = {"name": tool_name, "arguments": arguments or {}}
        try:
            client_timeout = self._aiohttp_mod.ClientTimeout(total=timeout) if self._aiohttp_mod else None
            async with session.post(
                self._call_tool_url,
                json=payload,
                timeout=client_timeout,
            ) as resp:
                resp.raise_for_status()
                content_type = resp.headers.get("Content-Type", "")
                if "text/event-stream" in content_type:
                    events = await self._parse_sse_events(resp)
                    if events and isinstance(events, list) and len(events) > 0:
                        last = events[-1]
                        if isinstance(last, dict):
                            return last.get("result") or last.get("content") or last
                        return last
                    return None
                else:
                    data = await resp.json(content_type=None)
                    if isinstance(data, dict):
                        if "error" in data and data["error"]:
                            raise MCPException(f"工具调用错误: {data['error']}")
                        if "result" in data:
                            return data["result"]
                        if "content" in data:
                            return data["content"]
                    return data
        except MCPException:
            raise
        except Exception as e:
            logger.error(f"SSE call_tool 失败 tool={tool_name}: {e}")
            raise MCPException(f"调用工具 {tool_name} 失败: {str(e)}")

    async def _parse_sse_events(self, resp) -> list:
        """解析 SSE 事件流，返回事件内容列表"""
        events = []
        buffer = ""
        current_event = {}
        async for chunk in resp.content.iter_any():
            if isinstance(chunk, bytes):
                try:
                    chunk = chunk.decode("utf-8")
                except UnicodeDecodeError:
                    chunk = chunk.decode("utf-8", errors="replace")
            buffer += chunk
            while "\n\n" in buffer:
                block, buffer = buffer.split("\n\n", 1)
                for line in block.split("\n"):
                    if not line:
                        continue
                    if line.startswith(":"):
                        continue
                    if ":" in line:
                        key, _, value = line.partition(":")
                        value = value.lstrip()
                    else:
                        key, value = line, ""
                    if key == "event":
                        current_event["event"] = value
                    elif key == "data":
                        if "data" in current_event:
                            current_event["data"] += "\n" + value
                        else:
                            current_event["data"] = value
                    elif key == "id":
                        current_event["id"] = value
                if "data" in current_event:
                    data_str = current_event["data"]
                    try:
                        parsed = json.loads(data_str)
                        events.append(parsed)
                    except json.JSONDecodeError:
                        events.append(data_str)
                current_event = {}
        if buffer.strip():
            pass
        return events


class STDIOAdapter(IMCPAdapter):
    """STDIO 模式适配器 - 通过子进程 stdin/stdout 执行 JSON-RPC 2.0"""

    def __init__(self, command: str, args: Optional[list] = None, env: Optional[dict] = None, timeout: int = 30):
        self._command = command
        self._args = args or []
        self._env = env or None
        self._timeout = timeout
        self._process: Optional[asyncio.subprocess.Process] = None
        self._connected = False
        self._request_id = 0
        self._write_lock = asyncio.Lock()

    @property
    def is_connected(self) -> bool:
        return self._connected and self._process is not None and self._process.returncode is None

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    async def connect(self) -> None:
        if self._connected:
            return
        if not self._command:
            raise MCPConnectException("STDIO模式缺少command参数")
        try:
            import os
            exec_env = None
            if self._env:
                exec_env = os.environ.copy()
                exec_env.update(self._env)
            self._process = await asyncio.create_subprocess_exec(
                self._command,
                *self._args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=exec_env,
            )
            self._connected = True
            self._request_id = 0
            logger.info(
                f"STDIO MCP 启动成功: command={self._command}, "
                f"args={self._args}, pid={self._process.pid}"
            )
        except Exception as e:
            self._connected = False
            self._process = None
            logger.error(f"STDIO MCP 启动失败: command={self._command}, err={e}")
            raise MCPConnectException(f"STDIO进程启动失败: {str(e)}")

    async def disconnect(self) -> None:
        self._connected = False
        if self._process is not None:
            try:
                if self._process.stdin:
                    try:
                        self._process.stdin.close()
                    except Exception:
                        pass
                if self._process.returncode is None:
                    self._process.terminate()
                    try:
                        await asyncio.wait_for(self._process.wait(), timeout=5)
                    except asyncio.TimeoutError:
                        self._process.kill()
                        try:
                            await self._process.wait()
                        except Exception:
                            pass
                stderr_output = b""
                if self._process.stderr:
                    try:
                        stderr_output, _ = await self._process.communicate()
                    except Exception:
                        pass
                if stderr_output:
                    try:
                        stderr_text = stderr_output.decode("utf-8", errors="replace").strip()
                        if stderr_text:
                            logger.warning(f"STDIO MCP stderr: {stderr_text}")
                    except Exception:
                        pass
            except Exception as e:
                logger.warning(f"关闭STDIO进程异常: {e}")
            finally:
                self._process = None
        logger.info(f"STDIO MCP 已断开: command={self._command}")

    async def _send_jsonrpc(self, method: str, params: Optional[dict] = None, timeout: int = 30) -> Any:
        """发送 JSON-RPC 2.0 请求并等待响应"""
        if not self.is_connected:
            raise MCPException("STDIO MCP未连接，请先connect")
        request_id = self._next_id()
        request_obj = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
        }
        if params is not None:
            request_obj["params"] = params
        request_line = json.dumps(request_obj, ensure_ascii=False) + "\n"
        request_bytes = request_line.encode("utf-8")
        async with self._write_lock:
            try:
                self._process.stdin.write(request_bytes)
                await self._process.stdin.drain()
            except (BrokenPipeError, ConnectionResetError) as e:
                self._connected = False
                logger.error(f"STDIO写入失败 (进程可能已退出): {e}")
                raise MCPException(f"STDIO进程通信失败: {str(e)}")
            except Exception as e:
                logger.error(f"STDIO写入异常: {e}")
                raise MCPException(f"STDIO写入失败: {str(e)}")
        start_time = time.time()
        stdout_buffer = b""
        stderr_tail = b""
        while True:
            elapsed = time.time() - start_time
            if elapsed >= timeout:
                raise MCPException(f"JSON-RPC调用超时 ({timeout}s): method={method}")
            remaining = timeout - elapsed
            try:
                done, pending = await asyncio.wait(
                    [self._read_stdout_line(), self._read_stderr_some()],
                    timeout=min(remaining, 0.1),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in done:
                    res = task.result()
                    if res is None:
                        continue
                    tag, data = res
                    if tag == "stdout" and data:
                        stdout_buffer += data
                        while b"\n" in stdout_buffer:
                            line_bytes, stdout_buffer = stdout_buffer.split(b"\n", 1)
                            if not line_bytes.strip():
                                continue
                            try:
                                line_text = line_bytes.decode("utf-8", errors="replace")
                                resp_obj = json.loads(line_text)
                            except Exception:
                                continue
                            if isinstance(resp_obj, dict) and resp_obj.get("id") == request_id:
                                if "error" in resp_obj and resp_obj["error"]:
                                    err = resp_obj["error"]
                                    msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
                                    raise MCPException(f"JSON-RPC错误: {msg}")
                                return resp_obj.get("result")
                    elif tag == "stderr" and data:
                        stderr_tail = (stderr_tail + data)[-4096:]
                if pending:
                    for task in pending:
                        task.cancel()
            except MCPException:
                raise
            except Exception as e:
                logger.warning(f"等待STDIO响应异常: {e}")
            if self._process.returncode is not None:
                stderr_msg = ""
                if stderr_tail:
                    try:
                        stderr_msg = stderr_tail.decode("utf-8", errors="replace").strip()
                    except Exception:
                        stderr_msg = str(stderr_tail)
                self._connected = False
                raise MCPException(
                    f"STDIO进程已退出 (code={self._process.returncode}). "
                    f"stderr: {stderr_msg}"
                )

    async def _read_stdout_line(self):
        try:
            data = await self._process.stdout.read(4096)
            return ("stdout", data) if data else None
        except Exception:
            return None

    async def _read_stderr_some(self):
        try:
            if self._process.stderr.at_eof():
                return None
            data = await self._process.stderr.read(4096)
            if data:
                try:
                    text = data.decode("utf-8", errors="replace").strip()
                    if text:
                        logger.debug(f"STDIO stderr: {text[:500]}")
                except Exception:
                    pass
            return ("stderr", data) if data else None
        except Exception:
            return None

    async def list_tools(self) -> list[dict]:
        try:
            result = await self._send_jsonrpc("tools/list", timeout=self._timeout)
            if result is None:
                return []
            if isinstance(result, list):
                return result
            if isinstance(result, dict):
                if "tools" in result and isinstance(result["tools"], list):
                    return result["tools"]
                return [result]
            return []
        except MCPException:
            raise
        except Exception as e:
            logger.error(f"STDIO list_tools 调用失败: {e}")
            raise MCPException(f"获取工具列表失败: {str(e)}")

    async def call_tool(self, tool_name: str, arguments: dict, timeout: int = 30) -> Any:
        params = {"name": tool_name, "arguments": arguments or {}}
        try:
            result = await self._send_jsonrpc("tools/call", params=params, timeout=timeout)
            return result
        except MCPException:
            raise
        except Exception as e:
            logger.error(f"STDIO call_tool 失败 tool={tool_name}: {e}")
            raise MCPException(f"调用工具 {tool_name} 失败: {str(e)}")


def create_mcp_adapter(mode: str, **kwargs) -> IMCPAdapter:
    """MCP 适配器工厂函数

    Args:
        mode: "sse" 或 "stdio"
        **kwargs:
            - SSE 模式: url(str), timeout(int, optional)
            - STDIO 模式: command(str), args(list, optional), env(dict, optional), timeout(int, optional)

    Returns:
        IMCPAdapter 实例

    Raises:
        MCPException: mode 不支持时抛出
    """
    mode_lower = (mode or "").lower()
    if mode_lower == "sse":
        url = kwargs.get("url", "")
        timeout = kwargs.get("timeout", 30)
        return SSEAdapter(url=url, timeout=timeout)
    elif mode_lower == "stdio":
        command = kwargs.get("command", "")
        args = kwargs.get("args", None)
        env = kwargs.get("env", None)
        timeout = kwargs.get("timeout", 30)
        return STDIOAdapter(command=command, args=args, env=env, timeout=timeout)
    else:
        raise MCPException(f"不支持的MCP模式: {mode}. 仅支持 sse / stdio")
