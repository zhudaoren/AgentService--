"""Tool管理服务入口 - AgentService平台 P1

端口: 8003
职责:
  - MCP 服务管理 (CRUD + 连接/断开 + 工具发现)
  - Skill 管理 (CRUD + 导入 + 渐进式披露)
  - 工具调用代理 + 调用日志
"""
import sys
import os

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

from routers.mcp import mcp_router
from routers.skill import skill_router
from routers.tool_call import tool_call_router
from routers.oauth import oauth_router
from services.skill_service import skill_import_service

logger = get_logger("tool-svc")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化数据库 + Skill上传目录"""
    logger.info("Tool Service 启动中...")
    logger.info(f"环境: {settings.ENV}, DEBUG: {settings.DEBUG}")
    try:
        await init_db()
    except Exception as e:
        logger.error(f"数据库初始化检查失败(忽略继续启动): {e}")
    try:
        skill_import_service._init_storage()
    except Exception as e:
        logger.error(f"Skill上传目录初始化失败(忽略继续启动): {e}")
    logger.info("Tool Service 启动完成")
    yield
    logger.info("Tool Service 关闭中...")


app = FastAPI(
    title="Tool Service API",
    description="工具管理服务 - AgentService平台 (MCP/Skill/工具调用)",
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
    return {"status": "ok", "service": "tool-svc", "version": "1.0.0"}


app.include_router(mcp_router, prefix="/api/v1", tags=["MCP管理"])
app.include_router(skill_router, prefix="/api/v1", tags=["Skill管理"])
app.include_router(tool_call_router, prefix="/api/v1", tags=["工具调用"])
app.include_router(oauth_router, prefix="/api/v1", tags=["OAuth授权"])


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8003,
        reload=settings.DEBUG,
    )
