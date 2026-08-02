import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
import httpx

from common.logger import get_logger
from common.config import settings

logger = get_logger("gateway")

# 全局共享的 httpx 客户端（保持连接池，避免频繁创建销毁）
_httpx_client: httpx.AsyncClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _httpx_client
    _httpx_client = httpx.AsyncClient(
        timeout=300,
        limits=httpx.Limits(
            max_connections=50,
            max_keepalive_connections=20,
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

# 服务路由表
SERVICE_ROUTES = {
    "/api/v1/agents": "http://localhost:8001",
    "/api/v1/llm-configs": "http://localhost:8001",
    "/api/v1/chat": "http://localhost:8002",
    "/api/v1/conversations": "http://localhost:8002",
    "/api/v1/messages": "http://localhost:8002",
    "/api/v1/mcp": "http://localhost:8003",
    "/api/v1/tools": "http://localhost:8003",
    "/api/v1/skills": "http://localhost:8003",
    "/api/v1/memories": "http://localhost:8004",
    "/api/v1/memory": "http://localhost:8004",
    "/api/v1/knowledge-bases": "http://localhost:8005",
    "/api/v1/rag": "http://localhost:8005",
    "/api/v1/datasources": "http://localhost:8006",
    "/api/v1/chatbi": "http://localhost:8006",
    "/api/v1/collaborations": "http://localhost:8007",
    "/api/v1/coord": "http://localhost:8007",
    "/api/v1/evolution": "http://localhost:8008",
    "/api/v1/skills/proposals": "http://localhost:8008",
}


def get_target_service(path: str) -> str:
    """根据路径匹配目标服务"""
    for prefix, target in SERVICE_ROUTES.items():
        if path.startswith(prefix):
            return target
    return None


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
        "agent-svc": "http://localhost:8001/healthz",
        "chat-svc": "http://localhost:8002/healthz",
        "tool-svc": "http://localhost:8003/healthz",
        "mem-svc": "http://localhost:8004/healthz",
        "rag-svc": "http://localhost:8005/healthz",
        "chatbi-svc": "http://localhost:8006/healthz",
        "coord-svc": "http://localhost:8007/healthz",
        "evo-svc": "http://localhost:8008/healthz",
    }
    async with httpx.AsyncClient(timeout=5) as client:
        for name, url in services.items():
            try:
                r = await client.get(url)
                results[name] = r.json()
            except Exception as e:
                results[name] = {"status": "error", "message": str(e)}
    return {"gateway": "ok", "services": results}


async def _proxy_stream(client: httpx.AsyncClient, method: str, url: str, body: bytes, headers: dict):
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


@app.api_route("/api/v1/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy(request: Request, path: str):
    """API代理 - 转发到对应微服务"""
    full_path = f"/api/v1/{path}"
    target_service = get_target_service(full_path)

    if not target_service:
        return JSONResponse(
            status_code=404,
            content={"code": 4040, "message": f"未找到匹配的服务: {full_path}"},
        )

    # 构建目标URL
    url = f"{target_service}{full_path}"
    query_string = request.url.query
    if query_string:
        url += f"?{query_string}"

    # 读取请求体
    body = await request.body()

    # 转发请求头
    headers = dict(request.headers)
    headers.pop("host", None)
    headers.pop("content-length", None)

    global _httpx_client
    if _httpx_client is None:
        return JSONResponse(
            status_code=503,
            content={"code": 5030, "message": "网关客户端未初始化"},
        )

    try:
        # 流式处理 SSE
        if "stream" in request.query_params or "chat" in full_path or "stream" in full_path:
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
        logger.error(f"服务调用失败: {url} - {e}")
        return JSONResponse(
            status_code=503,
            content={"code": 5030, "message": f"服务不可用: {str(e)}"},
        )


@app.on_event("startup")
async def startup():
    logger.info("API Gateway 启动中...")
    logger.info(f"已注册 {len(SERVICE_ROUTES)} 个服务路由")


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
