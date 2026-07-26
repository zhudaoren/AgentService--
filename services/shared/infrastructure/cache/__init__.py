import json
from typing import Any, Optional

import redis.asyncio as redis

from ...common.config import settings
from ...common.logger import get_logger

logger = get_logger(__name__)

_redis_client: Optional[redis.Redis] = None


def get_redis() -> redis.Redis:
    """获取Redis客户端（单例）"""
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_client


class RedisCache:
    """Redis缓存工具类"""

    def __init__(self):
        self._client = get_redis()

    async def get(self, key: str) -> Optional[str]:
        return await self._client.get(key)

    async def get_json(self, key: str) -> Optional[Any]:
        val = await self.get(key)
        if val:
            return json.loads(val)
        return None

    async def set(self, key: str, value: str, ttl: int = 3600) -> None:
        await self._client.set(key, value, ex=ttl)

    async def set_json(self, key: str, value: Any, ttl: int = 3600) -> None:
        await self.set(key, json.dumps(value, ensure_ascii=False), ttl)

    async def delete(self, key: str) -> None:
        await self._client.delete(key)

    async def exists(self, key: str) -> bool:
        return await self._client.exists(key) > 0


async def init_redis() -> None:
    """初始化Redis连接"""
    try:
        r = get_redis()
        await r.ping()
        logger.info("Redis连接成功")
    except Exception as e:
        logger.error(f"Redis连接失败: {e}")
        raise
