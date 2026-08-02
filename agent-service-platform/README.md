# AgentService 平台

> 基于 AgenticRAG + LangChain + LangGraph + FastAPI + Vue3 的智能体服务平台

**当前版本：Phase 1（基础设施与Agent核心域）** — LLM接入 + Agent管理 + 流式对话 + 记忆管理

---

## 快速开始

### 前置条件

| 组件 | 版本要求 | P1阶段用途 |
|------|----------|------------|
| Python | ≥ 3.11 | 后端 FastAPI 微服务 |
| Node.js | ≥ 18 | 前端 Vue3 开发 |
| MySQL | ≥ 8.0 | 数据存储（20张核心表） |
| Redis | ≥ 6.2 | 短期记忆缓存（可选，P1可不用） |

### 方式一：Docker Compose 一键启动（推荐）

```bash
# 1. 复制环境变量配置
cp .env.example .env
# 编辑 .env 填写 LLM API Key 等配置

# 2. 启动中间件
docker-compose up -d mysql redis

# 3. 初始化数据库
docker exec -i agent-mysql mysql -uroot -proot123 agent_service < infra/mysql/init.sql

# 4. 启动后端服务
docker-compose up -d agent-svc chat-svc mem-svc gateway

# 5. 检查服务状态
docker-compose ps
curl http://localhost:8000/api/v1/health
```

### 方式二：本地开发模式启动

#### 1. 安装 Python 依赖

```bash
pip install fastapi uvicorn[standard] pydantic pydantic-settings \
  'sqlalchemy[asyncio]' aiomysql redis cryptography httpx \
  langchain langchain-openai langchain-community langchain-anthropic
```

#### 2. 启动中间件

```bash
# MySQL
docker run -d --name agent-mysql -p 3306:3306 \
  -e MYSQL_ROOT_PASSWORD=root123 -e MYSQL_DATABASE=agent_service \
  mysql:8.0 --character-set-server=utf8mb4

# Redis（P1可选，Phase 2起必需）
docker run -d --name agent-redis -p 6379:6379 redis:7-alpine

# 初始化数据库表
mysql -u root -proot123 agent_service < infra/mysql/init.sql
```

#### 3. 配置环境变量

```bash
cp .env.example .env
```

编辑 `.env`，关键配置：
```ini
# 数据库
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=root123
MYSQL_DATABASE=agent_service

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379

# 加密密钥（保护API Key，请修改为自己的32字符密钥）
ENCRYPTION_KEY=your-32-char-secret-key-here

# LLM API Key（可选，也可在前端页面配置）
OPENAI_API_KEY=sk-xxx
```

#### 4. 启动后端服务

**推荐：使用一键启动脚本**

```bash
# Linux / macOS（前台运行，Ctrl+C 停止所有服务）
./scripts/start-backend.sh

# 或使用 Python 跨平台脚本
python scripts/start-backend.py

# 后台运行（配合 stop 脚本停止）
./scripts/start-backend.sh --daemon
# 或
python scripts/start-backend.py --daemon
```

**手动启动（如需单独调试某个服务）**

```bash
# API网关
cd services/gateway  && PYTHONPATH=../shared:. python -m uvicorn main:app --port 8000 --reload

# Agent服务（LLM配置 + Agent CRUD）
cd services/agent-svc && PYTHONPATH=../shared:. python -m uvicorn main:app --port 8001 --reload

# 对话服务（SSE流式对话）
cd services/chat-svc  && PYTHONPATH=../shared:. python -m uvicorn main:app --port 8002 --reload

# 记忆服务（长期记忆 + 短期记忆）
cd services/mem-svc   && PYTHONPATH=../shared:. python -m uvicorn main:app --port 8004 --reload
```

> P1阶段只需启动以上4个服务。tool-svc / rag-svc / chatbi-svc / coord-svc / evo-svc 仍为P0骨架。

#### 5. 停止后端服务

```bash
# 停止一键启动的后台服务
./scripts/stop-backend.sh

# 或使用 Python 脚本
python scripts/stop-backend.py

# 强制停止
./scripts/stop-backend.sh --force
# 或
python scripts/stop-backend.py --force
```

#### 6. 启动前端

```bash
cd frontend
npm install
npm run dev
# 打开 http://localhost:5173
```

#### 7. 开始使用

1. 打开 `http://localhost:5173` → 进入**LLM配置**页面，添加你的LLM配置（如OpenAI API Key）
2. 进入**Agent管理**页面，创建一个Agent并选择LLM配置
3. 进入**对话**页面，选择Agent创建会话，开始对话
4. 在**记忆查看器**页面查看和编辑Agent的长期记忆

---

## P1 功能清单

### LLM 配置管理
- [x] 支持 OpenAI / Claude / Qwen / DeepSeek / Ollama 五种Provider
- [x] API Key AES-256加密存储，列表返回掩码（sk-***xxxx）
- [x] 模型参数配置（temperature / max_tokens / top_p）
- [x] LLM连通性测试

### Agent 管理
- [x] Agent CRUD（创建/查询/更新/删除）
- [x] 创建Agent时自动初始化1:1长期记忆
- [x] 状态机：created → deployed → running ↔ paused → stopped
- [x] Agent克隆（复制配置，标记来源）
- [x] 5个官方Agent预置（编程/绘图/文档/RAG/ChatBI）

### 对话能力
- [x] SSE流式响应（打字机效果）
- [x] 对话历史持久化（MySQL messages表）
- [x] 多会话管理（创建/切换/删除）
- [x] 停止生成（中断LLM流式调用）
- [x] 消息复制
- [x] Markdown渲染（代码高亮、列表、表格等）

### 记忆管理
- [x] 长期记忆CRUD（用户画像/环境事实/历史经验）
- [x] 对话前自动加载长期记忆注入SystemPrompt
- [x] 上下文压缩（超Token阈值时只保留最近10条+摘要提示）
- [x] 短期记忆查看（会话消息历史）
- [x] 记忆摘要

### 前端界面
- [x] 对话页面（流式打字机 + Markdown渲染 + 停止生成 + 消息复制）
- [x] Agent管理页面（CRUD + 状态操作 + 克隆 + 官方Agent）
- [x] LLM配置页面（CRUD + API Key掩码 + 连通性测试）
- [x] 记忆查看器（长期记忆编辑 + 短期记忆查看）

---

## 服务端口

| 服务 | 端口 | P1状态 | 说明 |
|------|------|--------|------|
| Frontend | 5173 | ✅ 运行 | Vue3前端(开发模式) |
| API Gateway | 8000 | ✅ 运行 | API网关，统一入口 |
| agent-svc | 8001 | ✅ 运行 | Agent管理 + LLM配置 |
| chat-svc | 8002 | ✅ 运行 | 对话 + SSE流式 |
| mem-svc | 8004 | ✅ 运行 | 记忆管理 |
| tool-svc | 8003 | ⏳ P2 | 工具服务(MCP+Skill) |
| rag-svc | 8005 | ⏳ P3 | RAG检索服务 |
| chatbi-svc | 8006 | ⏳ P3 | ChatBI智能问数 |
| coord-svc | 8007 | ⏳ P4 | 多Agent协同服务 |
| evo-svc | 8008 | ⏳ P4 | 自我进化服务 |
| MySQL | 3306 | ✅ 必需 | 数据库（20张表） |
| Redis | 6379 | ⚠️ 可选 | 短期记忆缓存（P2起必需） |

---

## API 接口

### 健康检查

```bash
# 网关健康检查
curl http://localhost:8000/healthz

# 所有服务健康聚合
curl http://localhost:8000/api/v1/health

# 单个服务
curl http://localhost:8001/healthz  # agent-svc
```

### LLM 配置（网关 /api/v1/llm-configs）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | / | 创建LLM配置 |
| GET | / | 获取配置列表 |
| GET | /{id} | 获取配置详情 |
| PUT | /{id} | 更新配置 |
| DELETE | /{id} | 删除配置 |
| POST | /{id}/test | 测试连通性 |

### Agent 管理（网关 /api/v1/agents）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | / | 创建Agent |
| GET | / | 获取Agent列表 |
| GET | /official/list | 获取官方Agent |
| GET | /{id} | 获取Agent详情 |
| PUT | /{id} | 更新Agent |
| DELETE | /{id} | 删除Agent |
| POST | /{id}/status | 状态变更（deploy/start/pause/resume/stop） |
| POST | /{id}/clone | 克隆Agent |

### 对话（网关 /api/v1）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /conversations | 创建会话 |
| GET | /conversations | 会话列表 |
| GET | /conversations/{id} | 会话详情 |
| DELETE | /conversations/{id} | 删除会话 |
| GET | /conversations/{id}/messages | 历史消息 |
| POST | /chat | 发送消息（stream=true返回SSE） |
| POST | /chat/stop | 停止生成 |

### 记忆（网关 /api/v1/memory）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /agents/{id}/long-term | 获取长期记忆 |
| PUT | /agents/{id}/long-term | 更新长期记忆 |
| GET | /agents/{id}/long-term/summary | 记忆摘要 |
| GET | /agents/{id}/short-term/{conv_id} | 短期记忆 |

---

## 项目结构

```
agent-service-platform/
├── docker-compose.yml              # Docker一键部署
├── .env.example                    # 环境变量模板
├── .gitignore
│
├── frontend/                       # Vue3 前端
│   ├── package.json                # 依赖（vue/antd/axios/marked）
│   ├── vite.config.js              # Vite配置 + API代理
│   └── src/
│       ├── api/index.js            # API请求封装 + SSE流式处理
│       ├── router/index.js         # 路由配置（9个页面）
│       ├── App.vue                 # 主布局（侧边栏+内容区）
│       └── views/
│           ├── chat/               # 对话页面 ★
│           ├── agent/              # Agent管理 ★
│           ├── llm-config/          # LLM配置 ★
│           ├── memory/              # 记忆查看器 ★
│           ├── mcp/                 # (P2) MCP管理占位
│           ├── skill/               # (P2) Skill管理占位
│           ├── rag/                 # (P3) RAG管理占位
│           ├── chatbi/              # (P3) ChatBI占位
│           └── collaboration/       # (P4) 协作占位
│
├── services/                       # 后端微服务
│   ├── shared/                     # 共享库
│   │   ├── common/
│   │   │   ├── config/             # 全局配置（Settings）
│   │   │   ├── logger/              # 结构化日志
│   │   │   ├── exceptions/         # 异常体系
│   │   │   ├── schemas/             # Pydantic请求/响应模型
│   │   │   └── utils/crypto.py     # AES加密服务
│   │   ├── domain/
│   │   │   ├── base_entity.py      # DDD基类
│   │   │   ├── models.py           # SQLAlchemy ORM模型 ★
│   │   │   └── llm_adapter.py      # LangChain LLM适配器 ★
│   │   └── infrastructure/
│   │       ├── db/                  # 数据库引擎+会话
│   │       └── cache/               # Redis缓存工具
│   │
│   ├── gateway/                    # API网关(:8000)
│   ├── agent-svc/                  # Agent服务(:8001) ★
│   │   ├── main.py
│   │   ├── routers/
│   │   │   ├── llm_config.py       # LLM配置CRUD
│   │   │   └── agent.py            # Agent CRUD+状态机
│   │   └── services/
│   │       ├── llm_service.py      # LLM业务逻辑（加密/掩码）
│   │       └── agent_service.py     # Agent业务逻辑（状态机/克隆/官方Agent）
│   │
│   ├── chat-svc/                   # 对话服务(:8002) ★
│   │   ├── main.py
│   │   ├── routers/chat.py         # 会话CRUD+SSE流式+停止生成
│   │   └── services/
│   │       ├── chat_service.py     # 对话编排核心 ★
│   │       └── memory_service.py   # 记忆加载+上下文压缩
│   │
│   ├── mem-svc/                    # 记忆服务(:8004) ★
│   │   ├── main.py
│   │   ├── routers/memory.py       # 长期记忆+短期记忆API
│   │   └── services/
│   │       ├── memory_service.py   # 记忆CRUD
│   │       └── short_term_cache.py # Redis缓存(TTL=24h)
│   │
│   ├── tool-svc/                   # (P2) 工具服务骨架
│   ├── rag-svc/                    # (P3) RAG服务骨架
│   ├── chatbi-svc/                 # (P3) ChatBI服务骨架
│   ├── coord-svc/                  # (P4) 协同服务骨架
│   └── evo-svc/                    # (P4) 进化服务骨架
│
└── infra/
    ├── mysql/init.sql              # 数据库初始化(20张表)
    └── nginx/default.conf          # Nginx配置
```

---

## 技术栈

### 后端

| 技术 | 版本 | 用途 |
|------|------|------|
| FastAPI | 0.100+ | Web框架（异步、自动文档） |
| SQLAlchemy | 2.0 | ORM（异步引擎） |
| aiomysql | 0.3 | MySQL异步驱动 |
| Pydantic | 2.0+ | 数据校验与序列化 |
| LangChain | 0.2+ | LLM统一调用框架 |
| langchain-openai | - | OpenAI/DeepSeek适配 |
| langchain-anthropic | - | Claude适配 |
| langchain-community | - | Qwen/Ollama适配 |
| cryptography | - | AES加密（Fernet） |
| Redis | - | 短期记忆缓存 |

### 前端

| 技术 | 版本 | 用途 |
|------|------|------|
| Vue | 3.4+ | 响应式框架 |
| Vue Router | 4 | 路由管理 |
| Pinia | 2 | 状态管理 |
| Ant Design Vue | 4 | UI组件库 |
| Axios | 1 | HTTP请求 |
| marked | 12 | Markdown渲染 |
| Vite | 5 | 构建工具 |

---

## 开发进度

- [x] **Phase 0** — 项目初始化（8微服务骨架 + Docker环境 + 数据库脚本）
- [x] **Phase 1** — 基础设施与Agent核心域（LLM接入 + Agent管理 + 流式对话 + 记忆管理）← **当前版本**
- [ ] Phase 2 — 对话与工具域（MCP双模式 + Skill管理 + ReAct）
- [ ] Phase 3 — RAG与ChatBI域（Agentic RAG + 智能问数）
- [ ] Phase 4 — 协同与进化域（多Agent协作 + Hermes自我进化）
- [ ] Phase 5 — P1增强功能
- [ ] Phase 6 — P2远期规划

### Git 版本节点

| 版本 | Tag | 说明 |
|------|-----|------|
| Phase 0 | - | 项目初始化骨架 |
| **Phase 1** | **v1.0-phase1** | **LLM接入+Agent管理+流式对话+记忆管理** |

---

## 数据库

数据库初始化脚本位于 [infra/mysql/init.sql](infra/mysql/init.sql)，共20张表：

| 表名 | 所属域 | 说明 |
|------|--------|------|
| llm_configs | Agent域 | LLM配置（API Key加密存储） |
| agents | Agent域 | Agent定义（状态机/官方标记/克隆来源） |
| long_term_memories | 记忆域 | 长期记忆（1:1关联Agent） |
| conversations | 对话域 | 会话 |
| messages | 对话域 | 消息记录 |
| mcp_services | 工具域 | (P2) MCP服务注册 |
| mcp_tools | 工具域 | (P2) MCP工具 |
| agent_mcp_bindings | 工具域 | (P2) Agent-MCP绑定 |
| skills | 工具域 | (P2) Skill技能 |
| agent_skill_bindings | 工具域 | (P2) Agent-Skill绑定 |
| knowledge_bases | RAG域 | (P3) 知识库 |
| documents | RAG域 | (P3) 文档 |
| datasource_configs | ChatBI域 | (P3) 数据源配置 |
| collaboration_tasks | 协同域 | (P4) 协作任务 |
| collaboration_steps | 协同域 | (P4) 协作步骤 |
| evolution_records | 进化域 | (P4) 进化记录 |
| skill_proposals | 进化域 | (P4) Skill提议 |
| tool_call_logs | 工具域 | 工具调用日志 |
| skill_usage_stats | 进化域 | Skill使用统计 |
| evolution_metrics | 进化域 | 进化指标 |

> P1阶段使用前5张表（llm_configs / agents / long_term_memories / conversations / messages），其余表已建好待后续Phase使用。
