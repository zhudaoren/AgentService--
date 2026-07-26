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
    SUPPORTED_PROVIDERS = ["openai", "claude", "qwen", "deepseek", "ollama"]

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

    def _create_llm(self):
        """创建LangChain LLM实例"""
        if self._llm is not None:
            return self._llm

        if self.provider == "openai":
            self._llm = self._create_openai()
        elif self.provider == "claude":
            self._llm = self._create_claude()
        elif self.provider == "qwen":
            self._llm = self._create_qwen()
        elif self.provider == "deepseek":
            self._llm = self._create_deepseek()
        elif self.provider == "ollama":
            self._llm = self._create_ollama()
        else:
            raise LLMException(f"不支持的LLM提供商: {self.provider}")

        logger.info(f"LLM实例已创建: provider={self.provider}, model={self.model_name}")
        return self._llm

    def _create_openai(self):
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=self.model_name,
            api_key=self.api_key,
            base_url=self.api_base_url or None,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            top_p=self.top_p,
            streaming=True,
        )

    def _create_claude(self):
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(
            model=self.model_name,
            api_key=self.api_key,
            base_url=self.api_base_url or None,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            top_p=self.top_p,
            streaming=True,
        )

    def _create_qwen(self):
        from langchain_community.chat_models.tongyi import ChatTongyi
        import dashscope
        dashscope.api_key = self.api_key
        return ChatTongyi(
            model=self.model_name,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            top_p=self.top_p,
            streaming=True,
        )

    def _create_deepseek(self):
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=self.model_name,
            api_key=self.api_key,
            base_url=self.api_base_url or "https://api.deepseek.com/v1",
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            top_p=self.top_p,
            streaming=True,
        )

    def _create_ollama(self):
        from langchain_community.chat_models import ChatOllama
        return ChatOllama(
            model=self.model_name,
            base_url=self.api_base_url or "http://localhost:11434",
            temperature=self.temperature,
            top_p=self.top_p,
            num_predict=self.max_tokens,
        )

    async def invoke(self, messages: list[dict]) -> str:
        """同步调用 - 返回完整响应"""
        llm = self._create_llm()
        try:
            from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
            lc_messages = self._convert_messages(messages)
            response = await llm.ainvoke(lc_messages)
            return response.content
        except Exception as e:
            logger.error(f"LLM调用失败: {e}")
            raise LLMException(f"LLM调用失败: {str(e)}")

    async def stream(self, messages: list[dict]) -> AsyncIterator[str]:
        """流式调用 - 逐块返回"""
        llm = self._create_llm()
        try:
            lc_messages = self._convert_messages(messages)
            async for chunk in llm.astream(lc_messages):
                if chunk.content:
                    yield chunk.content
        except Exception as e:
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
