"""Agent管理服务入口 - AgentService平台 P1

端口: 8001
职责:
  - LLM 配置管理 (CRUD + 连通性测试)
  - Agent 管理 (CRUD + 状态机 + 克隆 + 官方Agent)
"""
import sys
import os

# 将 shared 层加入 sys.path，使 common/domain/infrastructure 可作为顶层包导入
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from common.config import settings
from common.logger import get_logger
from common.exceptions import AppException
from infrastructure.db import init_db

from routers.llm_config import llm_router
from routers.agent import agent_router
from services.agent_service import agent_service

logger = get_logger("agent-svc")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化数据库 + 官方Agent"""
    logger.info("Agent Service 启动中...")
    logger.info(f"环境: {settings.ENV}, DEBUG: {settings.DEBUG}")
    try:
        await init_db()
    except Exception as e:
        logger.error(f"数据库初始化检查失败(忽略继续启动): {e}")
    try:
        await agent_service.init_official_agents()
    except Exception as e:
        logger.error(f"官方Agent初始化失败(忽略继续启动): {e}")
    logger.info("Agent Service 启动完成")
    yield
    logger.info("Agent Service 关闭中...")


app = FastAPI(
    title="Agent Service API",
    description="Agent管理服务 - AgentService平台",
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


# ── 全局异常处理 ──────────────────────────────────────
@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException):
    logger.warning(
        f"AppException: code={exc.code}, message={exc.message}, "
        f"path={request.url.path}"
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.code, "message": exc.message, "data": None},
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error(
        f"未处理异常: {exc}, path={request.url.path}", exc_info=True
    )
    return JSONResponse(
        status_code=500,
        content={"code": 9999, "message": f"内部错误: {str(exc)}", "data": None},
    )


@app.get("/healthz", tags=["健康检查"])
async def health_check():
    return {"status": "ok", "service": "agent-svc", "version": "1.0.0"}


# ── 路由注册 ──────────────────────────────────────────
app.include_router(llm_router, prefix="/api/v1/llm-configs", tags=["LLM配置"])
app.include_router(agent_router, prefix="/api/v1/agents", tags=["Agent管理"])


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8001,
        reload=settings.DEBUG,
    )
