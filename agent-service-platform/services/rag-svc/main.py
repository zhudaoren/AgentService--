import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "shared"))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from common.logger import get_logger
from common.config import settings

logger = get_logger("rag-svc")

app = FastAPI(
    title="RAG Service API",
    description="RAG检索服务 - AgentService平台",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/healthz", tags=["健康检查"])
async def health_check():
    return {"status": "ok", "service": "rag-svc", "version": "1.0.0"}


@app.on_event("startup")
async def startup():
    logger.info("RAG Service 启动中...")


@app.on_event("shutdown")
async def shutdown():
    logger.info("RAG Service 关闭中...")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8005,
        reload=settings.DEBUG,
    )
