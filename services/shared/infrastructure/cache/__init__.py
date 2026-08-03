import json
import time
from typing import Any, Optional

import redis.asyncio as redis

from common.config import settings
from common.logger import get_logger

logger = get_logger(__name__)

_redis_client: Optional[redis.Redis] = None
_redis_client_safe: Optional[redis.Redis] = None
_redis_available: bool = False
_redis_last_check_ts: float = 0.0
_REDIS_CHECK_INTERVAL: float = 30.0  # 秒


def get_redis() -> redis.Redis:
    """获取Redis客户端（单例，异常会向上抛出）"""
    global _redis_client
    if _redis_client is None:
        _redis_client = redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_client


def get_redis_client() -> Optional[redis.Redis]:
    """获取Redis客户端（单例，失败返回None，不抛异常）

    用于 best-effort 场景：Redis不可用时调用方应回退到本地内存实现。
    """
    global _redis_client_safe, _redis_available, _redis_last_check_ts

    now = time.time()
    if (
        _redis_client_safe is not None
        and _redis_available
        and (now - _redis_last_check_ts) < _REDIS_CHECK_INTERVAL
    ):
        return _redis_client_safe

    try:
        _redis_client_safe = redis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        _redis_available = True
        _redis_last_check_ts = now
        logger.info(
            f"Redis连接就绪(安全模式): host={settings.REDIS_HOST}, "
            f"port={settings.REDIS_PORT}, db={settings.REDIS_DB}"
        )
        return _redis_client_safe
    except Exception as e:
        _redis_client_safe = None
        _redis_available = False
        _redis_last_check_ts = now
        logger.warning(
            f"Redis不可用(安全模式，将回退到内存缓存): "
            f"host={settings.REDIS_HOST}, port={settings.REDIS_PORT}, "
            f"error={e}"
        )
        return None


def is_available() -> bool:
    """返回Redis是否可用（基于最近一次探测结果）"""
    return _redis_available and _redis_client_safe is not None


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
