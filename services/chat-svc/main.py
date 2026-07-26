"""对话服务入口 - AgentService平台 P1

端口: 8002
职责:
  - 会话 CRUD
  - 消息历史查询
  - 流式 / 非流式对话
  - 停止生成
  - 短期 / 长期记忆加载
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

from routers.chat import chat_router
from services.chat_service import chat_service

logger = get_logger("chat-svc")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时初始化数据库"""
    logger.info("Chat Service 启动中...")
    logger.info(f"环境: {settings.ENV}, DEBUG: {settings.DEBUG}")
    try:
        await init_db()
    except Exception as e:
        logger.error(f"数据库初始化检查失败(忽略继续启动): {e}")
    logger.info("Chat Service 启动完成")
    yield
    logger.info("Chat Service 关闭中...")


app = FastAPI(
    title="Chat Service API",
    description="对话服务 - AgentService平台",
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
        content=ApiResponse(code=exc.code, message=exc.message, data=None).model_dump(),
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
    return {"status": "ok", "service": "chat-svc", "version": "1.0.0"}


# ── 路由注册 ──────────────────────────────────────────
app.include_router(chat_router, prefix="/api/v1", tags=["对话"])


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8002,
        reload=settings.DEBUG,
    )
