import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))

from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
import httpx

from common.logger import get_logger
from common.config import settings

logger = get_logger("gateway")

# 全局共享的 httpx 客户端（保持连接池，避免频繁创建销毁）
_httpx_client: Optional[httpx.AsyncClient] = None

# 下游服务地址常量
AGENT_SVC = "http://localhost:8001"
CHAT_SVC = "http://localhost:8002"
TOOL_SVC = "http://localhost:8003"
MEM_SVC = "http://localhost:8004"
RAG_SVC = "http://localhost:8005"
CHATBI_SVC = "http://localhost:8006"
COORD_SVC = "http://localhost:8007"
EVO_SVC = "http://localhost:8008"


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _httpx_client
    _httpx_client = httpx.AsyncClient(
        timeout=300,
        limits=httpx.Limits(
            max_connections=100,
            max_keepalive_connections=30,
        ),
    )
    logger.info("httpx 客户端已初始化")
    try:
        yield
    finally:
        if _httpx_client:
            await _httpx_client.aclose()
            logger.info("httpx 客户端已关闭")
            _httpx_client = None


app = FastAPI(
    title="AgentService API Gateway",
    description="API网关 - AgentService平台",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 服务路由表（保留通配 proxy 用）
SERVICE_ROUTES = {
    "/api/v1/agents": AGENT_SVC,
    "/api/v1/llm-configs": AGENT_SVC,
    "/api/v1/chat": CHAT_SVC,
    "/api/v1/conversations": CHAT_SVC,
    "/api/v1/messages": CHAT_SVC,
    "/api/v1/mcp": TOOL_SVC,
    "/api/v1/tools": TOOL_SVC,
    "/api/v1/skills": TOOL_SVC,
    "/api/v1/mcp-services": TOOL_SVC,
    "/api/v1/tool-call-logs": TOOL_SVC,
    "/api/v1/memories": MEM_SVC,
    "/api/v1/memory": MEM_SVC,
    "/api/v1/knowledge-bases": RAG_SVC,
    "/api/v1/rag": RAG_SVC,
    "/api/v1/datasources": CHATBI_SVC,
    "/api/v1/chatbi": CHATBI_SVC,
    "/api/v1/collaborations": COORD_SVC,
    "/api/v1/coord": COORD_SVC,
    "/api/v1/evolution": EVO_SVC,
    "/api/v1/skills/proposals": EVO_SVC,
}


def get_target_service(path: str) -> Optional[str]:
    """根据路径匹配目标服务（最长前缀优先）"""
    best: Optional[str] = None
    best_len: int = 0
    for prefix, target in SERVICE_ROUTES.items():
        if path.startswith(prefix) and len(prefix) > best_len:
            best = target
            best_len = len(prefix)
    return best


@app.middleware("http")
async def request_logger(request: Request, call_next):
    """请求日志中间件"""
    start = time.time()
    response = await call_next(request)
    duration = (time.time() - start) * 1000
    logger.info(f"{request.method} {request.url.path} -> {response.status_code} ({duration:.0f}ms)")
    return response


@app.get("/healthz", tags=["健康检查"])
async def health_check():
    """网关健康检查"""
    return {"status": "ok", "service": "gateway", "version": "1.0.0"}


@app.get("/api/v1/health", tags=["健康检查"])
async def all_services_health():
    """检查所有下游服务健康状态"""
    results = {}
    services = {
        "agent-svc": f"{AGENT_SVC}/healthz",
        "chat-svc": f"{CHAT_SVC}/healthz",
        "tool-svc": f"{TOOL_SVC}/healthz",
        "mem-svc": f"{MEM_SVC}/healthz",
        "rag-svc": f"{RAG_SVC}/healthz",
        "chatbi-svc": f"{CHATBI_SVC}/healthz",
        "coord-svc": f"{COORD_SVC}/healthz",
        "evo-svc": f"{EVO_SVC}/healthz",
    }
    async with httpx.AsyncClient(timeout=5) as client:
        for name, url in services.items():
            try:
                r = await client.get(url)
                results[name] = r.json()
            except Exception as e:
                results[name] = {"status": "error", "message": str(e)}
    return {"gateway": "ok", "services": results}


# ── 公共转发辅助函数 ──────────────────────────────────────

async def _proxy_stream(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    body: bytes,
    headers: dict,
):
    """代理流式响应（SSE），确保 httpx 连接在流结束前不被关闭"""
    request = client.build_request(method, url, content=body, headers=headers)
    response = await client.send(request, stream=True)

    async def stream_gen():
        try:
            async for chunk in response.aiter_bytes():
                yield chunk
        finally:
            await response.aclose()

    return StreamingResponse(
        stream_gen(),
        status_code=response.status_code,
        headers=dict(response.headers),
    )


def _normalize_path(path: str) -> str:
    """去除 path 尾部斜杠（兼容 /foo 和 /foo/ 同时转发到下游 /foo）"""
    while len(path) > 1 and path.endswith("/"):
        path = path[:-1]
    return path


def _build_forward_headers(request: Request) -> dict:
    """构建转发用请求头：去除 host/content-length 等不适用的项"""
    headers = dict(request.headers)
    headers.pop("host", None)
    headers.pop("content-length", None)
    return headers


def _build_url(target_service: str, request_path: str, query_string: Optional[str]) -> str:
    """构造目标 URL，自动处理尾部斜杠和 query string"""
    path = _normalize_path(request_path)
    url = f"{target_service}{path}"
    if query_string:
        url += f"?{query_string}"
    return url


async def _forward(
    request: Request,
    target_service: str,
    stream: bool = False,
) -> Response:
    """通用转发函数：代理单个 Request 到下游服务。

    Args:
        request: FastAPI Request 对象
        target_service: 下游服务根地址 (如 "http://localhost:8003")
        stream: 是否强制走 SSE 流式转发（默认按 query params / 路径关键字判断）
    """
    global _httpx_client
    if _httpx_client is None:
        return JSONResponse(
            status_code=503,
            content={"code": 5030, "message": "网关客户端未初始化"},
        )

    url = _build_url(target_service, request.url.path, request.url.query)
    body = await request.body()
    headers = _build_forward_headers(request)

    # 是否流式：显式 stream=True 或请求参数/路径命中
    use_stream = stream
    if not use_stream:
        full_path = _normalize_path(request.url.path)
        if "stream" in request.query_params or "chat" in full_path or "stream" in full_path:
            use_stream = True
        # 工具调用强制流式
        if "/api/v1/tools/call" in full_path:
            use_stream = True

    try:
        if use_stream:
            return await _proxy_stream(_httpx_client, request.method, url, body, headers)
        else:
            response = await _httpx_client.request(
                method=request.method,
                url=url,
                content=body,
                headers=headers,
            )
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers),
            )
    except httpx.RequestError as e:
        logger.error(f"服务调用失败: {request.method} {url} - {e}")
        return JSONResponse(
            status_code=503,
            content={"code": 5030, "message": f"服务不可用: {str(e)}"},
        )


# ═══════════════════════════════════════════════════════════
# P2 新增路由：MCP Services 管理 → tool-svc
# ═══════════════════════════════════════════════════════════

@app.api_route(
    "/api/v1/mcp-services",
    methods=["GET", "POST"],
    tags=["MCP Services"],
)
async def proxy_mcp_services_list(request: Request):
    """MCP 服务列表 / 创建 → tool-svc"""
    return await _forward(request, TOOL_SVC)


@app.api_route(
    "/api/v1/mcp-services/{mcp_id}",
    methods=["GET", "PUT", "DELETE"],
    tags=["MCP Services"],
)
async def proxy_mcp_services_detail(request: Request, mcp_id: str):
    """MCP 服务详情 / 更新 / 删除 → tool-svc"""
    return await _forward(request, TOOL_SVC)


@app.api_route(
    "/api/v1/mcp-services/{mcp_id}/connect",
    methods=["POST"],
    tags=["MCP Services"],
)
async def proxy_mcp_services_connect(request: Request, mcp_id: str):
    """MCP 服务建立连接 → tool-svc"""
    return await _forward(request, TOOL_SVC)


@app.api_route(
    "/api/v1/mcp-services/{mcp_id}/disconnect",
    methods=["POST"],
    tags=["MCP Services"],
)
async def proxy_mcp_services_disconnect(request: Request, mcp_id: str):
    """MCP 服务断开连接 → tool-svc"""
    return await _forward(request, TOOL_SVC)


@app.api_route(
    "/api/v1/mcp-services/{mcp_id}/discover",
    methods=["POST"],
    tags=["MCP Services"],
)
async def proxy_mcp_services_discover(request: Request, mcp_id: str):
    """MCP 服务工具发现 → tool-svc"""
    return await _forward(request, TOOL_SVC)


@app.api_route(
    "/api/v1/mcp-services/{mcp_id}/tools",
    methods=["GET"],
    tags=["MCP Services"],
)
async def proxy_mcp_services_tools(request: Request, mcp_id: str):
    """MCP 服务工具列表 → tool-svc"""
    return await _forward(request, TOOL_SVC)


@app.api_route(
    "/api/v1/mcp-services/{mcp_id}/tools/{tool_name}/toggle",
    methods=["POST"],
    tags=["MCP Services"],
)
async def proxy_mcp_services_tool_toggle(
    request: Request, mcp_id: str, tool_name: str
):
    """MCP 工具启用/停用切换 → tool-svc"""
    return await _forward(request, TOOL_SVC)


# ═══════════════════════════════════════════════════════════
# P2 新增路由：工具调用 → tool-svc (SSE流式)
# ═══════════════════════════════════════════════════════════

@app.api_route(
    "/api/v1/tools/call",
    methods=["POST"],
    tags=["Tools"],
)
async def proxy_tools_call(request: Request):
    """工具调用代理（SSE 流式转发，强制 stream=True）→ tool-svc"""
    return await _forward(request, TOOL_SVC, stream=True)


# ═══════════════════════════════════════════════════════════
# P2 新增路由：Skills 管理 → tool-svc
# ═══════════════════════════════════════════════════════════

@app.api_route(
    "/api/v1/skills",
    methods=["GET", "POST"],
    tags=["Skills"],
)
async def proxy_skills_list(request: Request):
    """Skill 列表 / 创建 → tool-svc"""
    return await _forward(request, TOOL_SVC)


@app.api_route(
    "/api/v1/skills/{skill_id}",
    methods=["GET", "PUT", "DELETE"],
    tags=["Skills"],
)
async def proxy_skills_detail(request: Request, skill_id: str):
    """Skill 详情 / 更新 / 删除 → tool-svc"""
    return await _forward(request, TOOL_SVC)


@app.api_route(
    "/api/v1/skills/{skill_id}/toggle",
    methods=["POST"],
    tags=["Skills"],
)
async def proxy_skills_toggle(request: Request, skill_id: str):
    """Skill 启用/停用切换 → tool-svc"""
    return await _forward(request, TOOL_SVC)


@app.api_route(
    "/api/v1/skills/{skill_id}/levels",
    methods=["GET"],
    tags=["Skills"],
)
async def proxy_skills_levels(request: Request, skill_id: str):
    """Skill 等级配置列表 → tool-svc"""
    return await _forward(request, TOOL_SVC)


@app.api_route(
    "/api/v1/skills/import/local",
    methods=["POST"],
    tags=["Skills"],
)
async def proxy_skills_import_local(request: Request):
    """Skill 本地文件导入（multipart/form-data 原样转发）→ tool-svc"""
    return await _forward(request, TOOL_SVC)


@app.api_route(
    "/api/v1/skills/import/online",
    methods=["POST"],
    tags=["Skills"],
)
async def proxy_skills_import_online(request: Request):
    """Skill 在线 URL 导入 → tool-svc"""
    return await _forward(request, TOOL_SVC)


# ═══════════════════════════════════════════════════════════
# P2 新增路由：Agent MCP/Skill bindings → agent-svc
# ═══════════════════════════════════════════════════════════

@app.api_route(
    "/api/v1/agents/{agent_id}/mcp-bindings",
    methods=["GET", "POST"],
    tags=["Agent Bindings"],
)
async def proxy_agent_mcp_bindings(request: Request, agent_id: str):
    """Agent 的 MCP 绑定列表 / 新增绑定 → agent-svc"""
    return await _forward(request, AGENT_SVC)


@app.api_route(
    "/api/v1/agents/{agent_id}/skill-bindings",
    methods=["GET", "POST"],
    tags=["Agent Bindings"],
)
async def proxy_agent_skill_bindings(request: Request, agent_id: str):
    """Agent 的 Skill 绑定列表 / 新增绑定 → agent-svc"""
    return await _forward(request, AGENT_SVC)


# ═══════════════════════════════════════════════════════════
# P2 新增路由：工具调用日志 → tool-svc
# ═══════════════════════════════════════════════════════════

@app.api_route(
    "/api/v1/tool-call-logs",
    methods=["GET"],
    tags=["Tools"],
)
async def proxy_tool_call_logs(request: Request):
    """工具调用日志查询 → tool-svc"""
    return await _forward(request, TOOL_SVC)


# ═══════════════════════════════════════════════════════════
# 通配兜底路由（保持 P1 原有逻辑，处理未显式注册的路径）
# ═══════════════════════════════════════════════════════════

@app.api_route("/api/v1/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy(request: Request, path: str):
    """API代理(兜底通配) - 转发到对应微服务"""
    full_path = f"/api/v1/{path}"
    target_service = get_target_service(full_path)

    if not target_service:
        return JSONResponse(
            status_code=404,
            content={"code": 4040, "message": f"未找到匹配的服务: {full_path}"},
        )
    return await _forward(request, target_service)


@app.on_event("startup")
async def startup():
    logger.info("API Gateway 启动中...")
    logger.info(f"已注册 {len(SERVICE_ROUTES)} 个服务路由(含通配匹配), P2显式路由17条")


@app.on_event("shutdown")
async def shutdown():
    logger.info("API Gateway 关闭中...")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,
    )
