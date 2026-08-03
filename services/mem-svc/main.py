"""记忆管理服务入口 - AgentService平台 P1

端口: 8004
职责:
  - 长期记忆管理 (查询/更新/摘要)
  - 短期记忆管理 (查询/清空)
  - Redis 短期记忆缓存 (T1-026, Phase2 准备)
"""
import sys
import os

# 将 shared 层加入 sys.path，使 common/domain/infrastructure 可作为顶层包导入
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from common.config import settings
from common.logger import get_logger
from common.exceptions import AppException
from common.schemas import ApiResponse
from infrastructure.db import init_db

from routers.memory import memory_router

logger = get_logger("mem-svc")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化数据库"""
    logger.info("Memory Service 启动中...")
    logger.info(f"环境: {settings.ENV}, DEBUG: {settings.DEBUG}")
    try:
        await init_db()
    except Exception as e:
        logger.error(f"数据库初始化检查失败(忽略继续启动): {e}")
    logger.info("Memory Service 启动完成")
    yield
    logger.info("Memory Service 关闭中...")


app = FastAPI(
    title="Memory Service API",
    description="记忆管理服务 - AgentService平台",
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
        content=ApiResponse(
            code=exc.code, message=exc.message, data=None
        ).model_dump(),
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.error(
        f"未处理异常: {exc}, path={request.url.path}", exc_info=True
    )
    return JSONResponse(
        status_code=500,
        content=ApiResponse(
            code=9999, message=f"内部错误: {str(exc)}", data=None
        ).model_dump(),
    )


@app.get("/healthz", tags=["健康检查"])
async def health_check():
    return {"status": "ok", "service": "mem-svc", "version": "1.0.0"}


# ── 路由注册 ──────────────────────────────────────────
app.include_router(
    memory_router, prefix="/api/v1/memory", tags=["记忆管理"]
)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8004,
        reload=settings.DEBUG,
    )
