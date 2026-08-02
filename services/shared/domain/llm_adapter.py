"""LangChain LLM 适配层

统一封装 OpenAI / Claude / Qwen / DeepSeek / Ollama 等主流 LLM，
提供同步调用、流式调用两种模式。
"""
import uuid
from typing import Any, AsyncIterator, Optional

from common.config import settings
from common.logger import get_logger
from common.exceptions import LLMException

logger = get_logger(__name__)


class LLMAdapter:
    """LLM 统一适配器 - 根据provider创建对应的LangChain模型实例"""

    # 支持的provider列表
    SUPPORTED_PROVIDERS = ["openai", "claude", "qwen", "deepseek", "ollama", "moonshot", "kimi", "glm", "zhipu", "siliconflow"]

    # 各提供商支持的参数白名单
    # key: provider名称, value: 支持的参数列表
    PROVIDER_SUPPORTED_PARAMS: dict[str, list[str]] = {
        "openai": ["temperature", "max_tokens", "top_p"],
        "claude": ["temperature", "max_tokens", "top_p"],
        "qwen": ["temperature", "max_tokens", "top_p"],
        "deepseek": ["temperature", "max_tokens", "top_p"],
        "ollama": ["temperature", "top_p", "num_predict"],
        "moonshot": ["temperature", "max_tokens", "top_p"],
        "kimi": ["temperature", "max_tokens", "top_p"],
        "zhipu": ["temperature", "max_tokens", "top_p"],
        "glm": ["temperature", "max_tokens", "top_p"],
        "siliconflow": ["temperature", "max_tokens", "top_p"],
    }

    def __init__(
        self,
        provider: str,
        model_name: str,
        api_key: str = "",
        api_base_url: str = "",
        temperature: float = 0.7,
        max_tokens: int = 4096,
        top_p: float = 0.9,
        **kwargs: Any,
    ):
        self.provider = provider.lower()
        self.model_name = model_name
        self.api_key = api_key
        self.api_base_url = api_base_url
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.top_p = top_p
        self.extra_params = kwargs
        self._llm = None
        self._fallback_used = False

    @property
    def is_fallback_used(self) -> bool:
        """是否因参数报错而降级到默认参数"""
        return self._fallback_used

    def get_supported_params(self) -> list[str]:
        """获取当前provider支持的参数列表"""
        return self.PROVIDER_SUPPORTED_PARAMS.get(self.provider, [])

    def _get_model_kwargs(self) -> dict:
        """根据provider支持的参数，构建模型调用的kwargs（只包含支持的参数）"""
        supported = self.get_supported_params()
        kwargs = {}
        if "temperature" in supported:
            kwargs["temperature"] = self.temperature
        if "max_tokens" in supported:
            kwargs["max_tokens"] = self.max_tokens
        if "top_p" in supported:
            kwargs["top_p"] = self.top_p
        if "num_predict" in supported:
            kwargs["num_predict"] = self.max_tokens
        return kwargs

    def _create_llm_by_provider(self, with_params: bool = True):
        """根据 provider 创建对应的 LangChain LLM 实例

        Args:
            with_params: 是否带模型参数（temperature/max_tokens/top_p）
                         False 时只创建裸实例，用于降级兜底
        """
        OPENAI_COMPATIBLE_PROVIDERS = ["openai", "moonshot", "kimi", "zhipu", "siliconflow"]
        kwargs = self._get_model_kwargs() if with_params else {}

        if self.provider in OPENAI_COMPATIBLE_PROVIDERS:
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model=self.model_name,
                api_key=self.api_key,
                base_url=self.api_base_url or None,
                streaming=True,
                **kwargs,
            )
        elif self.provider == "claude":
            from langchain_anthropic import ChatAnthropic
            return ChatAnthropic(
                model=self.model_name,
                api_key=self.api_key,
                base_url=self.api_base_url or None,
                streaming=True,
                **kwargs,
            )
        elif self.provider == "qwen":
            from langchain_community.chat_models.tongyi import ChatTongyi
            import dashscope
            dashscope.api_key = self.api_key
            return ChatTongyi(
                model=self.model_name,
                streaming=True,
                **kwargs,
            )
        elif self.provider == "deepseek":
            from langchain_openai import ChatOpenAI
            return ChatOpenAI(
                model=self.model_name,
                api_key=self.api_key,
                base_url=self.api_base_url or "https://api.deepseek.com/v1",
                streaming=True,
                **kwargs,
            )
        elif self.provider == "ollama":
            from langchain_community.chat_models import ChatOllama
            return ChatOllama(
                model=self.model_name,
                base_url=self.api_base_url or "http://localhost:11434",
                **kwargs,
            )
        elif self.provider == "glm":
            from langchain_community.chat_models import ChatZhipuAI
            return ChatZhipuAI(
                model=self.model_name,
                api_key=self.api_key,
                streaming=True,
                **kwargs,
            )
        else:
            raise LLMException(f"不支持的LLM提供商: {self.provider}")

    def _create_llm(self):
        """创建LangChain LLM实例（带降级兜底）

        优先使用用户配置的参数创建；若创建或调用时因参数不兼容报错，
        则自动回退到不传模型参数的方式重新创建。
        """
        if self._llm is not None:
            return self._llm

        try:
            self._llm = self._create_llm_by_provider(with_params=True)
            logger.info(
                f"LLM实例已创建: provider={self.provider}, model={self.model_name}, "
                f"supported_params={self.get_supported_params()}"
            )
        except Exception as e:
            logger.warning(
                f"带参数创建LLM实例失败，尝试使用默认参数: provider={self.provider}, "
                f"model={self.model_name}, err={e}"
            )
            self._llm = self._create_llm_by_provider(with_params=False)
            self._fallback_used = True
            logger.info(
                f"LLM实例已降级创建(默认参数): provider={self.provider}, "
                f"model={self.model_name}"
            )
        return self._llm

    def _reset_llm_with_fallback(self, reason: str):
        """重置 LLM 实例并使用默认参数重新创建（用于调用阶段的降级）"""
        logger.warning(f"LLM调用失败，尝试降级到默认参数重试: {reason}")
        self._llm = None
        self._llm = self._create_llm_by_provider(with_params=False)
        self._fallback_used = True

    @classmethod
    def get_provider_params_info(cls) -> dict[str, list[str]]:
        """获取所有提供商的支持参数信息（用于前端动态展示）"""
        return dict(cls.PROVIDER_SUPPORTED_PARAMS)

    async def invoke(self, messages: list[dict]) -> str:
        """同步调用 - 返回完整响应（带降级重试）"""
        llm = self._create_llm()
        lc_messages = self._convert_messages(messages)
        try:
            response = await llm.ainvoke(lc_messages)
            return response.content
        except Exception as e:
            # 若尚未降级，尝试用默认参数重试一次
            if not self._fallback_used:
                err_msg = str(e).lower()
                logger.warning(f"LLM调用失败，尝试降级重试: {e}")
                self._reset_llm_with_fallback(err_msg)
                try:
                    response = await self._llm.ainvoke(lc_messages)
                    return response.content
                except Exception as e2:
                    logger.error(f"降级重试仍失败: {e2}")
                    raise LLMException(f"LLM调用失败: {str(e2)}")
            logger.error(f"LLM调用失败: {e}")
            raise LLMException(f"LLM调用失败: {str(e)}")

    async def stream(self, messages: list[dict]) -> AsyncIterator[str]:
        """流式调用 - 逐块返回（带降级重试）"""
        llm = self._create_llm()
        lc_messages = self._convert_messages(messages)
        try:
            async for chunk in llm.astream(lc_messages):
                if chunk.content:
                    yield chunk.content
        except Exception as e:
            # 若尚未降级，尝试用默认参数重试一次
            if not self._fallback_used:
                logger.warning(f"LLM流式调用失败，尝试降级重试: {e}")
                self._reset_llm_with_fallback(str(e))
                try:
                    async for chunk in self._llm.astream(lc_messages):
                        if chunk.content:
                            yield chunk.content
                    return
                except Exception as e2:
                    logger.error(f"降级重试仍失败: {e2}")
                    raise LLMException(f"LLM流式调用失败: {str(e2)}")
            logger.error(f"LLM流式调用失败: {e}")
            raise LLMException(f"LLM流式调用失败: {str(e)}")

    def _convert_messages(self, messages: list[dict]) -> list:
        """将dict格式消息转换为LangChain消息对象"""
        from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
        result = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                result.append(SystemMessage(content=content))
            elif role == "assistant":
                result.append(AIMessage(content=content))
            else:
                result.append(HumanMessage(content=content))
        return result


async def create_llm_from_config(config: dict, decrypt_fn=None) -> LLMAdapter:
    """从数据库配置创建LLM适配器

    Args:
        config: 包含provider/model_name/api_key等字段的字典
        decrypt_fn: 解密函数，用于解密api_key
    """
    api_key = config.get("api_key", "")
    if decrypt_fn and api_key:
        try:
            api_key = decrypt_fn(api_key)
        except Exception as e:
            logger.warning(f"API Key解密失败，使用原始值: {e}")

    return LLMAdapter(
        provider=config.get("provider", "openai"),
        model_name=config.get("model_name", "gpt-4o"),
        api_key=api_key,
        api_base_url=config.get("api_base_url", ""),
        temperature=config.get("temperature", 0.7),
        max_tokens=config.get("max_tokens", 4096),
        top_p=config.get("top_p", 0.9),
    )
