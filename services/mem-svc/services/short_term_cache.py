"""短期记忆缓存服务

职责:
  - get_messages: 从 Redis/内存 读取会话消息缓存
  - set_messages: 将会话消息缓存到 Redis/内存 (TTL=24小时)
  - append_message: 追加单条消息到缓存
  - invalidate: 清除会话缓存

缓存策略:
  - 优先使用 Redis (通过 infrastructure.cache.get_redis_client 获取)
  - Redis 不可用时回退到进程内 dict (打印警告日志)

cache_key 格式: f"short_term:{conversation_id}"
value: JSON 序列化的消息列表 (list[dict])
TTL: 24 小时 = 86400 秒
"""
import json
import time
from typing import Any, Optional

from common.logger import get_logger
from infrastructure.cache import get_redis_client

logger = get_logger(__name__)


CACHE_TTL = 24 * 60 * 60  # 86400 秒


class ShortTermCache:
    """短期记忆缓存（Redis 优先，内存回退）"""

    def __init__(self) -> None:
        # 内存回退存储: key=conversation_id, value={"messages": list, "expire_at": timestamp}
        self._memory_store: dict[str, dict[str, Any]] = {}
        self._fallback_warned: bool = False

    # ── 内部工具 ──────────────────────────────────────

    @staticmethod
    def _make_key(conversation_id: str) -> str:
        return f"short_term:{conversation_id}"

    def _warn_fallback_once(self) -> None:
        if not self._fallback_warned:
            self._fallback_warned = True
            logger.warning(
                "Redis不可用，短期记忆缓存已回退到进程内内存dict "
                "(重启后缓存将丢失，且多实例部署不共享)"
            )

    def _memory_expire(self, conversation_id: str) -> None:
        entry = self._memory_store.get(conversation_id)
        if entry and time.time() > entry["expire_at"]:
            self._memory_store.pop(conversation_id, None)

    # ── 新接口（P2 要求） ──────────────────────────────

    async def get_messages(self, conversation_id: str) -> list[dict]:
        """获取会话消息列表（无消息或过期返回空 list）"""
        key = self._make_key(conversation_id)
        redis_client = get_redis_client()

        if redis_client is not None:
            try:
                raw = await redis_client.get(key)
                if raw is None:
                    return []
                data = json.loads(raw)
                if isinstance(data, list):
                    return data
                logger.warning(
                    f"短期记忆缓存数据类型异常(非list): "
                    f"conversation_id={conversation_id}, type={type(data)}"
                )
                return []
            except Exception as e:
                logger.error(
                    f"Redis读取短期记忆失败(回退内存): "
                    f"conversation_id={conversation_id}, error={e}"
                )
                # 继续走内存回退
                self._warn_fallback_once()

        # 内存回退
        self._warn_fallback_once()
        self._memory_expire(conversation_id)
        entry = self._memory_store.get(conversation_id)
        if entry is None:
            return []
        messages = entry.get("messages") or []
        return list(messages) if isinstance(messages, list) else []

    async def set_messages(
        self, conversation_id: str, messages: list[dict]
    ) -> None:
        """全量设置会话消息列表"""
        key = self._make_key(conversation_id)
        redis_client = get_redis_client()
        messages_safe = messages if isinstance(messages, list) else []

        if redis_client is not None:
            try:
                payload = json.dumps(messages_safe, ensure_ascii=False)
                await redis_client.set(key, payload, ex=CACHE_TTL)
                logger.debug(
                    f"Redis写入短期记忆: conversation_id={conversation_id}, "
                    f"count={len(messages_safe)}, ttl={CACHE_TTL}s"
                )
                return
            except Exception as e:
                logger.error(
                    f"Redis写入短期记忆失败(回退内存): "
                    f"conversation_id={conversation_id}, error={e}"
                )
                self._warn_fallback_once()

        # 内存回退
        self._warn_fallback_once()
        self._memory_store[conversation_id] = {
            "messages": list(messages_safe),
            "expire_at": time.time() + CACHE_TTL,
        }
        logger.debug(
            f"内存写入短期记忆: conversation_id={conversation_id}, "
            f"count={len(messages_safe)}"
        )

    async def append_message(
        self, conversation_id: str, message: dict
    ) -> None:
        """追加单条消息到缓存末尾"""
        if not isinstance(message, dict):
            logger.warning(
                f"append_message 忽略非dict消息: "
                f"conversation_id={conversation_id}, type={type(message)}"
            )
            return

        key = self._make_key(conversation_id)
        redis_client = get_redis_client()

        if redis_client is not None:
            try:
                raw = await redis_client.get(key)
                if raw is None:
                    messages = []
                else:
                    data = json.loads(raw)
                    messages = data if isinstance(data, list) else []
                messages.append(message)
                payload = json.dumps(messages, ensure_ascii=False)
                await redis_client.set(key, payload, ex=CACHE_TTL)
                logger.debug(
                    f"Redis追加短期记忆: conversation_id={conversation_id}, "
                    f"total_count={len(messages)}"
                )
                return
            except Exception as e:
                logger.error(
                    f"Redis追加短期记忆失败(回退内存): "
                    f"conversation_id={conversation_id}, error={e}"
                )
                self._warn_fallback_once()

        # 内存回退
        self._warn_fallback_once()
        self._memory_expire(conversation_id)
        entry = self._memory_store.get(conversation_id)
        if entry is None:
            entry = {"messages": [], "expire_at": time.time() + CACHE_TTL}
            self._memory_store[conversation_id] = entry
        current = entry.get("messages") or []
        if not isinstance(current, list):
            current = []
        current.append(message)
        entry["messages"] = current
        logger.debug(
            f"内存追加短期记忆: conversation_id={conversation_id}, "
            f"total_count={len(current)}"
        )

    async def invalidate(self, conversation_id: str) -> None:
        """失效会话缓存（删除）"""
        key = self._make_key(conversation_id)
        redis_client = get_redis_client()

        redis_ok = False
        if redis_client is not None:
            try:
                await redis_client.delete(key)
                redis_ok = True
                logger.debug(
                    f"Redis失效短期记忆缓存: conversation_id={conversation_id}"
                )
            except Exception as e:
                logger.error(
                    f"Redis失效短期记忆失败(尝试内存): "
                    f"conversation_id={conversation_id}, error={e}"
                )

        # 内存回退（即使 Redis 成功也清一下，避免不一致）
        removed = self._memory_store.pop(conversation_id, None)
        if removed is not None and not redis_ok:
            logger.debug(
                f"内存失效短期记忆缓存: conversation_id={conversation_id}"
            )

    # ── 旧接口兼容（供 memory_service.py clear_short_term_memory 调用） ──

    async def get_messages_from_cache(
        self, conversation_id: str
    ) -> Optional[list[dict[str, Any]]]:
        result = await self.get_messages(conversation_id)
        return result if result else None

    async def cache_messages(
        self,
        conversation_id: str,
        messages: list[dict[str, Any]],
        ttl: int = CACHE_TTL,
    ) -> None:
        # 注意: 兼容层忽略传入的 ttl，统一使用 CACHE_TTL=24h
        await self.set_messages(conversation_id, messages)

    async def clear_cache(self, conversation_id: str) -> bool:
        """旧接口兼容：返回 True 表示存在并已清除"""
        existed = False
        # 先判断内存
        if conversation_id in self._memory_store:
            existed = True
        # 再判断 Redis（尽力而为）
        redis_client = get_redis_client()
        if redis_client is not None and not existed:
            try:
                key = self._make_key(conversation_id)
                if await redis_client.exists(key):
                    existed = True
            except Exception:
                pass
        await self.invalidate(conversation_id)
        return existed


short_term_cache = ShortTermCache()
