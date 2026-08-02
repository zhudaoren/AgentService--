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


# ── MCP SSE/STDIO 模式配置 ─────────────────────────────
class MCPSSEConfig(BaseModel):
    url: str = Field(..., max_length=512, description="SSE模式URL")


class MCPSTDIOConfig(BaseModel):
    command: str = Field(..., description="启动命令")
    args: list[str] = []
    env: dict = {}


# ── MCP 服务 ────────────────────────────────────────────
class MCPServiceCreate(BaseModel):
    name: str = Field(..., max_length=128)
    description: str = ""
    mode: str = Field(..., description="sse 或 stdio")
    sse_url: str = ""
    stdio_config: dict = {}
    status: str = "disconnected"


class MCPServiceUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    mode: Optional[str] = None
    sse_url: Optional[str] = None
    stdio_config: Optional[dict] = None
    status: Optional[str] = None
    error_message: Optional[str] = None


class MCPServiceOut(BaseModel):
    id: str
    name: str
    description: str = ""
    mode: str
    sse_url: str = ""
    stdio_config: dict = {}
    status: str = "disconnected"
    error_message: str = ""
    last_connected_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


# ── MCP 工具 ────────────────────────────────────────────
class MCPToolOut(BaseModel):
    id: str
    mcp_service_id: str
    name: str
    description: str = ""
    input_schema: dict = {}
    enabled: bool = True
    usage_count: int = 0
    created_at: datetime
    updated_at: datetime


# ── MCP 连接操作 ────────────────────────────────────────
class MCPConnectAction(BaseModel):
    action: str = Field(..., description="connect 或 disconnect")


# ── 工具调用 ────────────────────────────────────────────
class ToolCallRequest(BaseModel):
    tool_name: str
    arguments: dict = {}
    timeout: int = 30


class ToolCallResponse(BaseModel):
    tool_name: str
    status: str
    result: Any = None
    error_message: str = ""
    duration_ms: int = 0


# ── 工具调用日志 ────────────────────────────────────────
class ToolCallLogOut(BaseModel):
    id: str
    agent_id: Optional[str] = None
    conversation_id: Optional[str] = None
    mcp_service_id: Optional[str] = None
    tool_name: str
    arguments: dict = {}
    result: str = ""
    status: str
    duration_ms: Optional[int] = None
    error_message: str = ""
    created_at: datetime


# ── Skill Level ─────────────────────────────────────────
class SkillLevelOut(BaseModel):
    id: str
    skill_id: str
    level: int
    name: str = ""
    content: str
    token_count: int = 0
    created_at: datetime


# ── Skill ────────────────────────────────────────────────
class SkillCreate(BaseModel):
    name: str = Field(..., max_length=128)
    description: str = ""
    category: str = "general"
    version: str = "1.0.0"
    source: str = "local"
    source_url: str = ""
    enabled: bool = True
    author: str = ""
    tags: list = []
    levels: list = []


class SkillUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None
    version: Optional[str] = None
    source: Optional[str] = None
    source_url: Optional[str] = None
    enabled: Optional[bool] = None
    author: Optional[str] = None
    tags: Optional[list] = None


class SkillOut(BaseModel):
    id: str
    name: str
    description: str = ""
    category: str = "general"
    version: str = "1.0.0"
    source: str = "local"
    source_url: str = ""
    storage_path: str = ""
    enabled: bool = True
    usage_count: int = 0
    success_rate: float = 0.0
    author: str = ""
    tags: list = []
    levels: list[SkillLevelOut] = []
    created_at: datetime
    updated_at: datetime


# ── Skill 导入 ──────────────────────────────────────────
class SkillLocalImport(BaseModel):
    file_path: str = Field(..., description="本地Skill文件路径")
    category: str = "general"


class SkillOnlineImport(BaseModel):
    source_url: str = Field(..., max_length=512, description="在线Skill源地址")
    category: str = "general"


# ── Skill 渐进式加载响应 ────────────────────────────────
class SkillProgressiveResponse(BaseModel):
    skill_id: str
    skill_name: str
    requested_level: int
    prompt_text: str
    actual_tokens: int
    budget_tokens: int


# ── Agent-MCP 绑定 ─────────────────────────────────────
class AgentMCPBindingCreate(BaseModel):
    agent_id: str
    mcp_service_id: str
    config: dict = {}
    enabled: bool = True


class AgentMCPBindingOut(BaseModel):
    id: str
    agent_id: str
    mcp_service_id: str
    mcp_service_name: str = ""
    mcp_service_mode: str = ""
    mcp_service_status: str = ""
    config: dict = {}
    enabled: bool = True
    created_at: datetime


# ── Agent-Skill 绑定 ────────────────────────────────────
class AgentSkillBindingCreate(BaseModel):
    agent_id: str
    skill_id: str
    priority: int = 0
    enabled: bool = True


class AgentSkillBindingOut(BaseModel):
    id: str
    agent_id: str
    skill_id: str
    skill_name: str = ""
    skill_category: str = ""
    skill_source: str = ""
    priority: int = 0
    enabled: bool = True
    created_at: datetime
