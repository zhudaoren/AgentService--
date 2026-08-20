"""LangChain LLM 适配层

统一封装 OpenAI / Claude / Qwen / DeepSeek / Ollama 等主流 LLM，
提供同步调用、流式调用两种模式。
"""
from __future__ import annotations

import json
import re
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

    # ── 多模态能力探测 ──────────────────────────────

    _VISION_MODEL_RE = re.compile(
        r"(vision|vl|image|gpt-4o|gpt-4|deepseek-vl|qwen-vl|qwen2-vl)",
        re.IGNORECASE,
    )
    _VISION_CAPABLE_PROVIDERS = {
        "openai", "azure_openai", "deepseek", "qwen", "dashscope",
        "ollama", "zhipuai", "zhipu", "moonshot",
    }

    def supports_modality(self, modality: str) -> bool:
        """根据 provider + model_name 判断是否支持多模态。

        - image(视觉): provider 在视觉集合内，且 model_name 命中视觉关键字
        - audio(input_audio): 暂返回 False（留作后续扩展）
        """
        m = (modality or "").lower()
        if m in {"image", "vision", "visual", "img"}:
            return (
                self.provider in self._VISION_CAPABLE_PROVIDERS
                and bool(self._VISION_MODEL_RE.search(self.model_name or ""))
            )
        if m in {"audio", "input_audio"}:
            return False
        return False

    # ── 多模态降级：不支持视觉时把数组 content 还原为文本 ──

    def _normalize_messages_for_model(
        self, messages: list[dict]
    ) -> list[dict]:
        """若 user 消息 content 是数组且含视觉附件，但模型不支持视觉，则降级为纯文本。

        降级后文本末尾追加系统提示警告，并打印 WARN 日志。
        """
        if not messages:
            return messages
        supports_image = self.supports_modality("image")
        out: list[dict] = []
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content")
            if role == "user" and isinstance(content, list):
                has_image = any(
                    isinstance(p, dict) and p.get("type") == "image_url"
                    for p in content
                )
                if has_image and not supports_image:
                    text_parts: list[str] = []
                    for p in content:
                        if isinstance(p, dict):
                            if p.get("type") == "text":
                                text_parts.append(str(p.get("text", "") or ""))
                            elif p.get("type") == "image_url":
                                # image 附件降级：文本提醒（信息尽量保序，不展开 URL）
                                text_parts.append("\n[已忽略图片附件（当前模型不支持视觉）]")
                            else:
                                text_parts.append(str(p))
                        else:
                            text_parts.append(str(p))
                    new_text = "".join(text_parts)
                    warn_suffix = (
                        "\n\n[系统提示：当前模型不支持图片输入，已忽略你上传的图片/音频附件。"
                        "请换用视觉模型后重试]"
                    )
                    if warn_suffix not in new_text:
                        new_text = new_text + warn_suffix
                    logger.warning(
                        f"多模态降级: provider={self.provider} model={self.model_name} "
                        f"不支持视觉，user 消息 content 数组已还原为纯文本。"
                    )
                    new_msg = dict(msg)
                    new_msg["content"] = new_text
                    out.append(new_msg)
                    continue
            out.append(msg)
        return out

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
        """重置 LLM 实例并使用默认参数重新创建（用于调用阶段的降级）

        针对 DeepSeek R1 等推理模型特定错误做定向降级：
        - "reasoning_content must be passed back": 说明上一轮的 reasoning_content 没有回传
          给 API。这里会显式关闭 model_kwargs["reasoning_effort"]，避免后续重试仍然请求
          thinking 模式导致同样 400。
        """
        reason_lc = (reason or "").lower()
        logger.warning(f"LLM调用失败，尝试降级到默认参数重试: {reason}")
        self._llm = None
        # 先尝试裸实例（不带 temperature/max_tokens 等）
        self._llm = self._create_llm_by_provider(with_params=False)
        self._fallback_used = True
        # DeepSeek R1 thinking 模式定向降级：直接用 model_kwargs 关掉 reasoning
        if "reasoning_content" in reason_lc and self.provider in ("deepseek", "openai", "moonshot", "kimi", "zhipu", "siliconflow"):
            try:
                from langchain_openai import ChatOpenAI
                base_url = self.api_base_url or ("https://api.deepseek.com/v1" if self.provider == "deepseek" else None)
                # 注意："none" 是 DeepSeek R1 官方支持的关闭 reasoning 级别；
                # 使用空字符串会被 API 拒绝（unknown variant）。
                self._llm = ChatOpenAI(
                    model=self.model_name,
                    api_key=self.api_key,
                    base_url=base_url,
                    streaming=True,
                    model_kwargs={"reasoning_effort": "none"},
                )
                logger.warning(f"已针对 DeepSeek/OpenAI reasoning 错误降级：reasoning_effort=none，model={self.model_name}")
            except Exception as e2:
                logger.warning(f"关闭 reasoning_effort 失败，继续使用默认裸实例: {e2}")

    @classmethod
    def get_provider_params_info(cls) -> dict[str, list[str]]:
        """获取所有提供商的支持参数信息（用于前端动态展示）"""
        return dict(cls.PROVIDER_SUPPORTED_PARAMS)

    async def invoke(self, messages: list[dict]) -> str:
        """同步调用 - 返回完整响应（带降级重试）"""
        llm = self._create_llm()
        normalized = self._normalize_messages_for_model(messages)
        lc_messages = self._convert_messages(normalized)
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
                    logger.error(f"降级重试仍失败: {e2}", exc_info=True)
                    raise LLMException(f"LLM调用失败: {str(e2)}")
            logger.error(f"LLM调用失败: {e}", exc_info=True)
            raise LLMException(f"LLM调用失败: {str(e)}")

    async def stream(self, messages: list[dict]) -> AsyncIterator[str]:
        """流式调用 - 逐块返回（带降级重试）"""
        llm = self._create_llm()
        normalized = self._normalize_messages_for_model(messages)
        lc_messages = self._convert_messages(normalized)
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
                    logger.error(f"降级重试仍失败: {e2}", exc_info=True)
                    raise LLMException(f"LLM流式调用失败: {str(e2)}")
            logger.error(f"LLM流式调用失败: {e}", exc_info=True)
            raise LLMException(f"LLM流式调用失败: {str(e)}")

    def _convert_messages(self, messages: list[dict]) -> list:
        """将dict格式消息转换为LangChain消息对象

        前置步骤：对多模态数组 content 执行降级（若模型不支持视觉）。
        支持 user 消息 content 为数组（多模态）；其它 role 若为数组则拼成字符串。
        """
        from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
        messages = self._normalize_messages_for_model(messages)
        result = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                if isinstance(content, list):
                    text_parts = []
                    for p in content:
                        if isinstance(p, dict) and p.get("type") == "text":
                            text_parts.append(str(p.get("text", "") or ""))
                        else:
                            text_parts.append(str(p))
                    content = "".join(text_parts)
                result.append(SystemMessage(content=content))
            elif role == "assistant":
                if isinstance(content, list):
                    text_parts = []
                    for p in content:
                        if isinstance(p, dict) and p.get("type") == "text":
                            text_parts.append(str(p.get("text", "") or ""))
                        else:
                            text_parts.append(str(p))
                    content = "".join(text_parts)
                lc_msg = AIMessage(content=content)
                # ── reasoning_content 回传（DeepSeek R1 / thinking 模型必填） ──────
                # 若上一轮 LLM 返回了 reasoning_content，必须在下一轮以 AIMessage 的
                # additional_kwargs["reasoning_content"] 形式回传，否则 DeepSeek API
                # 会抛 400: "The reasoning_content in the thinking mode must be passed back"
                add_kwargs: dict = {}
                extra_rc = msg.get("reasoning_content") or msg.get("additional_kwargs", {}).get("reasoning_content")
                if isinstance(extra_rc, str) and extra_rc.strip():
                    add_kwargs["reasoning_content"] = extra_rc
                # 其它来自上一轮 AIMessage 的额外字段原样透传
                extras = msg.get("additional_kwargs") if isinstance(msg.get("additional_kwargs"), dict) else {}
                for k, v in extras.items():
                    if k == "reasoning_content":
                        continue
                    add_kwargs[k] = v
                if add_kwargs:
                    try:
                        lc_msg.additional_kwargs = add_kwargs
                    except Exception:
                        pass
                # 兼容 function calling: assistant 消息可能携带 tool_calls 字段
                tool_calls = msg.get("tool_calls")
                if tool_calls and isinstance(tool_calls, list):
                    try:
                        normalized_tcs: list[dict] = []
                        for tc in tool_calls:
                            if not isinstance(tc, dict):
                                continue
                            # 支持两种格式：
                            # (A) LangChain原生: {name, args, id, type}
                            # (B) OpenAI API:  {id, type:"function", function:{name, arguments:<str_or_dict>}}
                            if "name" in tc and "args" in tc:
                                n_tc = {
                                    "name": str(tc.get("name") or ""),
                                    "args": tc.get("args") if isinstance(tc.get("args"), dict) else {},
                                    "id": str(tc.get("id") or ""),
                                }
                                if tc.get("type"):
                                    n_tc["type"] = tc["type"]
                                normalized_tcs.append(n_tc)
                                continue
                            fn = tc.get("function") if isinstance(tc.get("function"), dict) else {}
                            raw_name = fn.get("name") or tc.get("tool_name") or tc.get("name") or ""
                            raw_args = fn.get("arguments") or tc.get("arguments") or {}
                            if isinstance(raw_args, str):
                                try:
                                    parsed_args = json.loads(raw_args)
                                    args_dict = parsed_args if isinstance(parsed_args, dict) else {}
                                except Exception:
                                    args_dict = {}
                            elif isinstance(raw_args, dict):
                                args_dict = raw_args
                            else:
                                args_dict = {}
                            normalized_tcs.append({
                                "name": str(raw_name or ""),
                                "args": args_dict,
                                "id": str(tc.get("id") or ""),
                                "type": tc.get("type") or "tool_call",
                            })
                        # LangChain AIMessage 序列化时需要 tool_call_chunks/tool_calls 都有 `name` 键
                        # 否则会抛 KeyError('name')。因此显式赋值并校验。
                        if normalized_tcs:
                            lc_msg.tool_calls = normalized_tcs
                    except Exception:
                        logger.warning("AIMessage tool_calls 归一化失败，跳过该字段", exc_info=True)
                result.append(lc_msg)
            else:
                # user / tool 等：HumanMessage 支持 list content（多模态）
                if role == "tool":
                    from langchain_core.messages import ToolMessage
                    tool_call_id = str(msg.get("tool_call_id") or f"toolcall_{id(result)}")
                    raw_name = (
                        msg.get("name")
                        or msg.get("tool_name")
                        or (msg.get("tool") if isinstance(msg.get("tool"), str) else None)
                        or ""
                    )
                    tool_name = str(raw_name or "tool") or "tool"
                    # langchain_core 在序列化 ToolMessage 时（特别是 bind_tools 后的
                    # astream 多轮）会读取 tm.name 做 API 请求体拼装，必须显式传入
                    # 非空 name 与 tool_call_id，否则会抛 KeyError('name'/'tool_call_id')。
                    result.append(ToolMessage(
                        content=content if not isinstance(content, list) else str(content),
                        tool_call_id=tool_call_id,
                        name=tool_name,
                    ))
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
