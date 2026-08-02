"""LLM 配置业务服务

职责:
  - create_config: api_key 用 crypto_service.encrypt 加密存储
  - get_configs: 返回时 api_key 用掩码处理 (如 sk-***xxxx)
  - test_connection: 用 LLMAdapter 发送 "你好" 测试连通性
"""
import uuid
from typing import Any

from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from common.exceptions import (
    NotFoundException,
    ValidationException,
    LLMException,
)
from common.logger import get_logger
from common.schemas import LLMConfigCreate, LLMConfigUpdate, LLMConfigOut
from common.utils.crypto import crypto_service
from domain.models import LLMConfig
from domain.llm_adapter import create_llm_from_config

logger = get_logger(__name__)


def _mask_api_key(api_key: str) -> str:
    """掩码处理 API Key，例如 sk-***xxxx

    规则: 保留前缀(到首个-或前3位) + *** + 后4位
    """
    if not api_key:
        return ""
    if len(api_key) < 8:
        return "***"
    dash_idx = api_key.find("-")
    if 0 <= dash_idx < 10:
        prefix = api_key[: dash_idx + 1]
    else:
        prefix = api_key[:3]
    suffix = api_key[-4:]
    return f"{prefix}***{suffix}"


class LLMConfigService:
    """LLM 配置业务服务"""

    async def create_config(
        self, db: AsyncSession, payload: LLMConfigCreate
    ) -> LLMConfigOut:
        # 名称唯一性校验
        existing = await db.execute(
            select(LLMConfig).where(LLMConfig.name == payload.name)
        )
        if existing.scalar_one_or_none():
            raise ValidationException(f"LLM配置名称已存在: {payload.name}")

        config_id = uuid.uuid4().hex
        encrypted_key = (
            crypto_service.encrypt(payload.api_key) if payload.api_key else ""
        )

        config = LLMConfig(
            id=config_id,
            name=payload.name,
            provider=payload.provider,
            model_name=payload.model_name,
            api_key=encrypted_key,
            api_base_url=payload.api_base_url,
            default_params=payload.default_params or {},
            is_default=payload.is_default,
        )
        db.add(config)

        # 若设为默认，取消其他默认
        if payload.is_default:
            await db.execute(
                update(LLMConfig)
                .where(LLMConfig.id != config_id)
                .values(is_default=False)
            )

        await db.flush()
        logger.info(f"创建LLM配置: id={config_id}, name={payload.name}")
        return await self._to_out(config)

    async def get_configs(
        self, db: AsyncSession, page: int = 1, page_size: int = 20
    ) -> tuple[list[LLMConfigOut], int]:
        # 总数
        total_result = await db.execute(select(func.count(LLMConfig.id)))
        total = total_result.scalar() or 0

        # 分页查询
        result = await db.execute(
            select(LLMConfig)
            .order_by(LLMConfig.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        configs = result.scalars().all()
        items = [await self._to_out(c) for c in configs]
        return items, total

    async def get_config(
        self, db: AsyncSession, config_id: str
    ) -> LLMConfigOut:
        config = await self._get_by_id(db, config_id)
        return await self._to_out(config)

    async def update_config(
        self, db: AsyncSession, config_id: str, payload: LLMConfigUpdate
    ) -> LLMConfigOut:
        config = await self._get_by_id(db, config_id)

        data = payload.model_dump(exclude_unset=True)
        # api_key 特殊处理: 提供非空值则加密; None/空串跳过(保留原值)
        if "api_key" in data:
            new_key = data["api_key"]
            if new_key:
                data["api_key"] = crypto_service.encrypt(new_key)
            else:
                data.pop("api_key", None)

        for k, v in data.items():
            setattr(config, k, v)

        # 处理默认设置
        if payload.is_default is True:
            await db.execute(
                update(LLMConfig)
                .where(LLMConfig.id != config_id)
                .values(is_default=False)
            )

        await db.flush()
        logger.info(f"更新LLM配置: id={config_id}")
        return await self._to_out(config)

    async def delete_config(self, db: AsyncSession, config_id: str) -> None:
        config = await self._get_by_id(db, config_id)
        await db.delete(config)
        await db.flush()
        logger.info(f"删除LLM配置: id={config_id}")

    async def test_connection(
        self, db: AsyncSession, config_id: str
    ) -> dict[str, Any]:
        """测试 LLM 连通性 - 发送 "你好" 测试消息"""
        config = await self._get_by_id(db, config_id)
        config_dict: dict[str, Any] = {
            "provider": config.provider,
            "model_name": config.model_name,
            "api_key": config.api_key or "",
            "api_base_url": config.api_base_url or "",
            "temperature": 0.7,
            "max_tokens": 100,
            "top_p": 0.9,
        }
        try:
            adapter = await create_llm_from_config(
                config_dict, decrypt_fn=crypto_service.decrypt
            )
            response = await adapter.invoke(
                [{"role": "user", "content": "你好"}]
            )
            resp_text = response if isinstance(response, str) else str(response)
            logger.info(f"LLM连通性测试成功: config_id={config_id}")
            result = {
                "success": True,
                "message": "连接成功",
                "response": resp_text[:200],
            }
            # 若发生了参数降级，附加提示
            if adapter.is_fallback_used:
                result["fallback"] = True
                result["message"] = (
                    "连接成功（已自动降级为模型默认参数，"
                    "当前模型不支持所配置的参数）"
                )
            return result
        except LLMException as e:
            logger.warning(f"LLM连通性测试失败: config_id={config_id}, err={e.message}")
            return {"success": False, "message": e.message}
        except Exception as e:
            logger.error(f"LLM连通性测试异常: config_id={config_id}", exc_info=True)
            return {"success": False, "message": f"测试失败: {str(e)}"}

    # ── 内部工具 ──────────────────────────────────────
    async def _get_by_id(
        self, db: AsyncSession, config_id: str
    ) -> LLMConfig:
        result = await db.execute(
            select(LLMConfig).where(LLMConfig.id == config_id)
        )
        config = result.scalar_one_or_none()
        if not config:
            raise NotFoundException(f"LLM配置不存在: {config_id}")
        return config

    async def _to_out(self, config: LLMConfig) -> LLMConfigOut:
        # 解密后掩码显示
        masked = ""
        if config.api_key:
            try:
                plain = crypto_service.decrypt(config.api_key)
                masked = _mask_api_key(plain)
            except Exception:
                masked = "***"
        return LLMConfigOut(
            id=config.id,
            name=config.name,
            provider=config.provider,
            model_name=config.model_name,
            api_key_masked=masked,
            api_base_url=config.api_base_url or "",
            default_params=config.default_params or {},
            is_default=bool(config.is_default),
            created_at=config.created_at,
            updated_at=config.updated_at,
        )


llm_service = LLMConfigService()
