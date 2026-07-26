"""短期记忆 Redis 缓存服务 (T1-026, Phase2 准备)

职责:
  - get_messages_from_cache: 从 Redis 读取会话消息缓存
  - cache_messages: 将会话消息缓存到 Redis (TTL=24小时)
  - clear_cache: 清除会话缓存

cache_key 格式: f"chat:messages:{conversation_id}"

说明: P1 阶段短期记忆直接从 messages 表读取; 此模块为 Phase2 缓存层准备,
所有操作均为 best-effort (Redis 不可用时不影响主流程)。
"""
from typing import Any, Optional

from common.logger import get_logger
from infrastructure.cache import RedisCache

logger = get_logger(__name__)


# 缓存 TTL: 24 小时 (单位: 秒)
CACHE_TTL = 24 * 60 * 60  # 86400


class ShortTermCache:
    """短期记忆 Redis 缓存"""

    def __init__(self) -> None:
        self._cache = RedisCache()

    @staticmethod
    def _make_key(conversation_id: str) -> str:
        """构造缓存 key: chat:messages:{conversation_id}"""
        return f"chat:messages:{conversation_id}"

    async def get_messages_from_cache(
        self, conversation_id: str
    ) -> Optional[list[dict[str, Any]]]:
        """从 Redis 读取会话消息缓存

        Returns:
            消息列表 (命中) / None (未命中或异常)
        """
        key = self._make_key(conversation_id)
        try:
            data = await self._cache.get_json(key)
            if data is None:
                return None
            if isinstance(data, list):
                return data
            logger.warning(
                f"缓存数据类型异常(非list): conversation_id={conversation_id}"
            )
            return None
        except Exception as e:
            logger.error(
                f"读取短期记忆缓存失败: conversation_id={conversation_id}, "
                f"error={e}"
            )
            return None

    async def cache_messages(
        self,
        conversation_id: str,
        messages: list[dict[str, Any]],
        ttl: int = CACHE_TTL,
    ) -> None:
        """将会话消息缓存到 Redis (默认 TTL=24小时)"""
        key = self._make_key(conversation_id)
        try:
            await self._cache.set_json(key, messages, ttl=ttl)
            logger.debug(
                f"缓存短期记忆: conversation_id={conversation_id}, "
                f"count={len(messages)}, ttl={ttl}s"
            )
        except Exception as e:
            logger.error(
                f"写入短期记忆缓存失败: conversation_id={conversation_id}, "
                f"error={e}"
            )

    async def clear_cache(self, conversation_id: str) -> bool:
        """清除会话缓存

        Returns:
            True 表示原缓存存在并已清除; False 表示缓存不存在或清除失败
        """
        key = self._make_key(conversation_id)
        try:
            existed = await self._cache.exists(key)
            if existed:
                await self._cache.delete(key)
                logger.debug(
                    f"清除短期记忆缓存: conversation_id={conversation_id}"
                )
                return True
            return False
        except Exception as e:
            logger.error(
                f"清除短期记忆缓存失败: conversation_id={conversation_id}, "
                f"error={e}"
            )
            return False


short_term_cache = ShortTermCache()
