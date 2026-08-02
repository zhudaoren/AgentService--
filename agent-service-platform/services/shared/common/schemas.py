"""Pydantic 请求/响应模型"""
from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field


# ── 通用响应 ──────────────────────────────────────────
class ApiResponse(BaseModel):
    code: int = 0
    message: str = "ok"
    data: Any = None


class PageData(BaseModel):
    items: list[Any] = []
    total: int = 0
    page: int = 1
    page_size: int = 20


# ── LLM 配置 ──────────────────────────────────────────
class LLMConfigCreate(BaseModel):
    name: str = Field(..., max_length=128)
    provider: str = Field(..., max_length=64)
    model_name: str = Field(..., max_length=128)
    api_key: str = ""
    api_base_url: str = ""
    default_params: dict = {}
    is_default: bool = False


class LLMConfigUpdate(BaseModel):
    name: Optional[str] = None
    provider: Optional[str] = None
    model_name: Optional[str] = None
    api_key: Optional[str] = None
    api_base_url: Optional[str] = None
    default_params: Optional[dict] = None
    is_default: Optional[bool] = None


class LLMConfigOut(BaseModel):
    id: str
    name: str
    provider: str
    model_name: str
    api_key_masked: str = ""
    api_base_url: str = ""
    default_params: dict = {}
    is_default: bool = False
    created_at: datetime
    updated_at: datetime


# ── Agent ──────────────────────────────────────────────
class AgentCreate(BaseModel):
    name: str = Field(..., max_length=128)
    description: str = ""
    system_prompt: str
    llm_config_id: str
    temperature: float = 0.7
    max_tokens: int = 4096
    top_p: float = 0.9
    memory_strategy: str = "standard"
    config: dict = {}


class AgentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    llm_config_id: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None
    memory_strategy: Optional[str] = None
    config: Optional[dict] = None


class AgentOut(BaseModel):
    id: str
    name: str
    description: str = ""
    system_prompt: str
    llm_config_id: str
    llm_config_name: str = ""
    status: str = "created"
    is_official: bool = False
    cloned_from_id: Optional[str] = None
    temperature: float = 0.7
    max_tokens: int = 4096
    top_p: float = 0.9
    memory_strategy: str = "standard"
    config: dict = {}
    created_at: datetime
    updated_at: datetime


class AgentStatusChange(BaseModel):
    action: str = Field(..., description="deploy|pause|stop|resume")


# ── 对话 ──────────────────────────────────────────────
class ConversationCreate(BaseModel):
    agent_id: str
    title: str = "新对话"
    user_id: str = "default"


class ConversationOut(BaseModel):
    id: str
    agent_id: str
    user_id: str = ""
    title: str = ""
    status: str = "active"
    message_count: int = 0
    created_at: datetime
    updated_at: datetime


class MessageOut(BaseModel):
    id: str
    conversation_id: str
    message_type: str
    content: str
    tool_calls: Optional[dict] = None
    tool_results: Optional[dict] = None
    token_count: int = 0
    created_at: datetime


class ChatRequest(BaseModel):
    conversation_id: str
    content: str
    stream: bool = True


# ── 记忆 ──────────────────────────────────────────────
# 注: experience / shared_items 既可能是 dict 也可能是 list,
# 用 Any 兼容两种结构; id/created_at/updated_at 设为 Optional 以支持
# mem-svc 中"长期记忆不存在时返回空结构"的场景。
class LongTermMemoryOut(BaseModel):
    id: Optional[str] = None
    agent_id: str
    user_profile: dict = {}
    environment_facts: dict = {}
    experience: Any = []
    shared_items: Any = []
    version: int = 1
    updated_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class LongTermMemoryUpdate(BaseModel):
    user_profile: Optional[dict] = None
    environment_facts: Optional[dict] = None
    experience: Optional[Any] = None
    shared_items: Optional[Any] = None
