# AgentService 平台

> 基于 AgenticRAG + LangChain + LangGraph + FastAPI + Vue3 的智能体服务平台

**当前版本：Phase 2.1（对话与工具域 + 智能化增强）** — LLM接入 + Agent管理 + 流式对话 + 记忆管理 + MCP双模式接入 + Skill渐进式披露与按需筛选 + 工具调用ReAct循环 + 长期记忆自动评估 + 流式思考/回答事件分离 + Plan-and-Execute工作模式 + 记忆深化(Redis/Milvus)

---

## 快速开始

### 前置条件

| 组件 | 版本要求 | P2阶段用途 | Phase |
|------|----------|------------|-------|
| Python | ≥ 3.11 | 后端 FastAPI 微服务 | P1必需 |
| Node.js | ≥ 18 | 前端 Vue3 开发 | P1必需 |
| MySQL | ≥ 8.0 | 数据存储（20张核心表） | P1必需 |
| Redis | ≥ 6.2 | 短期记忆缓存（P2必需） | P2必需 |
| MinIO | ≥ 2024-01 | Skill本地文件存储 | P2必需 |
| Milvus | ≥ 2.4 | 长期记忆向量化 | P2必需 |

### 中间件 Docker 镜像清单

P2阶段需要拉取以下镜像：

| 镜像 | 容器名 | 端口 | 用途 |
|------|--------|------|------|
| `mysql:8.0` | agent-mysql | 3306 | 数据库（20张表） |
| `redis:7-alpine` | agent-redis | 6379 | 短期记忆缓存 |
| `minio/minio:RELEASE.2024-01-01T00-00-00Z` | agent-minio | 9000, 9001 | Skill文件存储 |
| `quay.io/coreos/etcd:v3.5.5` | agent-milvus-etcd | - | Milvus元数据存储 |
| `minio/minio:RELEASE.2023-03-20T20-16-18Z` | agent-milvus-minio | - | Milvus内部对象存储 |
| `milvusdb/milvus:v2.4.0` | agent-milvus | 19530, 9091 | 长期记忆向量检索 |

提前拉取镜像（可选，启动脚本也会自动拉取）：

```bash
docker pull mysql:8.0
docker pull redis:7-alpine
docker pull minio/minio:RELEASE.2024-01-01T00-00-00Z
docker pull quay.io/coreos/etcd:v3.5.5
docker pull minio/minio:RELEASE.2023-03-20T20-16-18Z
docker pull milvusdb/milvus:v2.4.0
```

> 国内用户如拉取缓慢，可配置 Docker 镜像加速：
> ```json
> // /etc/docker/daemon.json
> {
>   "registry-mirrors": [
>     "https://docker.mirrors.ustc.edu.cn",
>     "https://hub-mirror.c.163.com"
>   ]
> }
> ```

### 方式一：Docker Compose 一键启动（推荐）

```bash
# 1. 复制环境变量配置
cp .env.example .env
# 编辑 .env 填写 LLM API Key 等配置

# 2. 启动中间件
docker-compose up -d mysql redis minio milvus-etcd milvus-minio milvus-standalone

# 3. 初始化数据库
docker exec -i agent-mysql mysql -uroot -proot123 agent_service < infra/mysql/init.sql

# 4. 启动后端服务
docker-compose up -d agent-svc chat-svc mem-svc gateway tool-svc

# 5. 检查服务状态
docker-compose ps
curl http://localhost:8000/api/v1/health
```

### 方式二：本地开发模式启动

#### 1. 安装 Python 依赖

```bash
pip install fastapi uvicorn[standard] pydantic pydantic-settings \
  'sqlalchemy[asyncio]' aiomysql redis cryptography httpx \
  langchain langchain-openai langchain-community langchain-anthropic \
  aiohttp minio pymilvus python-multipart
```

#### 2. 启动中间件（一键脚本，推荐）

```bash
# Linux / macOS
./scripts/start-middleware.sh

# 或使用 Python 跨平台脚本
python scripts/start-middleware.py

# 首次启动先拉取镜像
./scripts/start-middleware.sh --pull
# 或
python scripts/start-middleware.py --pull

# 仅检查环境（Docker是否安装、端口是否占用）
./scripts/start-middleware.sh --check-only
```

启动后脚本会自动等待所有中间件就绪（MySQL / Redis / MinIO / Milvus 健康检查通过）。

**手动启动（如需单独调试）**

```bash
# MySQL
docker run -d --name agent-mysql -p 3306:3306 \
  -e MYSQL_ROOT_PASSWORD=root123 -e MYSQL_DATABASE=agent_service \
  mysql:8.0 --character-set-server=utf8mb4

# Redis（P2必需）
docker run -d --name agent-redis -p 6379:6379 redis:7-alpine \
  redis-server --appendonly yes --requirepass ""

# MinIO（P2必需：Skill本地文件存储）
docker run -d --name agent-minio \
  -p 9000:9000 -p 9001:9001 \
  -e MINIO_ROOT_USER=minioadmin \
  -e MINIO_ROOT_PASSWORD=minioadmin \
  minio/minio:RELEASE.2024-01-01T00-00-00Z \
  server /data --console-address ":9001"

# Milvus（P2必需：长期记忆向量化 - standalone三件套）
# etcd（内部使用，不需要对外映射2379）
docker run -d --name agent-milvus-etcd \
  -e ETCD_AUTO_COMPACTION_MODE=revision \
  -e ETCD_AUTO_COMPACTION_RETENTION=1000 \
  -e ETCD_QUOTA_BACKEND_BYTES=4294967296 \
  quay.io/coreos/etcd:v3.5.5 \
  etcd -advertise-client-urls=http://127.0.0.1:2379 \
       -listen-client-urls http://0.0.0.0:2379 --data-dir /etcd

# milvus内部minio
docker run -d --name agent-milvus-minio \
  -e MINIO_ACCESS_KEY=minioadmin \
  -e MINIO_SECRET_KEY=minioadmin \
  minio/minio:RELEASE.2023-03-20T20-16-18Z \
  minio server /minio_data --console-address ":9001"

# milvus standalone（映射19530）
docker run -d --name agent-milvus \
  -p 19530:19530 -p 9091:9091 \
  -e ETCD_ENDPOINTS=host.docker.internal:2379 \
  -e MINIO_ADDRESS=host.docker.internal:9000 \
  milvusdb/milvus:v2.4.0 \
  milvus run standalone

# 初始化数据库表
mysql -u root -proot123 agent_service < infra/mysql/init.sql
```

#### 3. 停止中间件

```bash
# Linux / macOS
./scripts/stop-middleware.sh

# 或使用 Python 跨平台脚本
python scripts/stop-middleware.py

# 彻底删除中间件及数据卷（慎用：会清除所有持久化数据）
./scripts/stop-middleware.sh --volumes
# 或
python scripts/stop-middleware.py --volumes
```

#### 4. 配置环境变量

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

# Redis（P2必需）
REDIS_HOST=localhost
REDIS_PORT=6379

# MinIO（P2必需）
MINIO_ENDPOINT=localhost
MINIO_PORT=9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=agent-skills
MINIO_USE_SSL=false

# Milvus（P2必需）
MILVUS_HOST=localhost
MILVUS_PORT=19530
MILVUS_COLLECTION=agent_memory_vectors

# 加密密钥（保护API Key，请修改为自己的32字符密钥）
ENCRYPTION_KEY=your-32-char-secret-key-here

# LLM API Key（可选，也可在前端页面配置）
OPENAI_API_KEY=sk-xxx
```

#### 5. 启动后端服务

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

# 对话服务（SSE流式对话 + ReAct循环）
cd services/chat-svc  && PYTHONPATH=../shared:. python -m uvicorn main:app --port 8002 --reload

# 工具服务（MCP管理 + Skill管理 + 工具调用代理）
cd services/tool-svc  && PYTHONPATH=../shared:. python -m uvicorn main:app --port 8003 --reload

# 记忆服务（长期记忆 + 短期记忆缓存 + 语义检索）
cd services/mem-svc   && PYTHONPATH=../shared:. python -m uvicorn main:app --port 8004 --reload
```

> P2阶段需要启动以上5个服务（包含tool-svc）。rag-svc / chatbi-svc / coord-svc / evo-svc 仍为骨架。

#### 6. 停止后端服务

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

#### 7. 启动前端

```bash
cd frontend
npm install
npm run dev
# 打开 http://localhost:5173
```

#### 8. 开始使用

1. 打开 `http://localhost:5173` → 进入**LLM配置**页面，添加你的LLM配置（如OpenAI / DeepSeek API Key）
2. 进入**MCP服务管理**页面，创建MCP服务（SSE/STDIO双模式），连接后自动发现工具
3. 进入**Skill管理**页面，导入或创建Skill（支持本地文件/在线URL导入）
4. 进入**Agent管理**页面，创建一个Agent并选择LLM配置，设置 `workflow_mode`（ReAct / Plan-and-Execute / Hybrid），绑定MCP服务和Skill
5. 进入**对话**页面，选择Agent创建会话，开始对话：
   - 自动触发 ReAct / Plan-and-Execute 工具调用循环
   - 思考过程与最终回答分离展示，思考区显示时长统计
   - 技能按用户查询关键词按需筛选加载
6. 多轮对话后，进入**记忆查看器**页面查看长期记忆（自动从对话历史中提炼的偏好/事实/经验）

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

| 服务 | 端口 | P2状态 | 说明 |
|------|------|--------|------|
| Frontend | 5173 | ✅ 运行 | Vue3前端(开发模式) |
| API Gateway | 8000 | ✅ 运行 | API网关，统一入口 |
| agent-svc | 8001 | ✅ 运行 | Agent管理 + LLM配置 |
| chat-svc | 8002 | ✅ 运行 | 对话 + SSE流式 + ReAct循环 |
| tool-svc | 8003 | ✅ 运行 | 工具服务(MCP+Skill) |
| mem-svc | 8004 | ✅ 运行 | 记忆管理(短期Redis+长期Milvus) |
| rag-svc | 8005 | ⏳ P3 | RAG检索服务 |
| chatbi-svc | 8006 | ⏳ P3 | ChatBI智能问数 |
| coord-svc | 8007 | ⏳ P4 | 多Agent协同服务 |
| evo-svc | 8008 | ⏳ P4 | 自我进化服务 |
| MySQL | 3306 | ✅ 必需 | 数据库（20张表） |
| Redis | 6379 | ✅ 必需 | 短期记忆缓存（P2必需） |
| MinIO | 9000 | ✅ 必需 | Skill本地文件存储（P2必需） |
| Milvus | 19530 | ✅ 必需 | 长期记忆向量化（P2必需） |

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
curl http://localhost:8003/healthz  # tool-svc
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
| POST | /chat/regenerate | 重新生成（删除最后消息+重跑） |

### 记忆（网关 /api/v1/memory）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /agents/{id}/long-term | 获取长期记忆 |
| PUT | /agents/{id}/long-term | 更新长期记忆 |
| GET | /agents/{id}/long-term/summary | 记忆摘要（含实际内容字段，便于摘要弹窗展示） |
| GET | /agents/{id}/short-term/{conv_id} | 短期记忆（优先Redis缓存） |
| DELETE | /agents/{id}/short-term/cache | 清除短期记忆缓存 |
| POST | /evaluate | **(P2.1)** 对话结束评估更新长期记忆（chat-svc 异步调用，best-effort） |
| POST | /semantic-search | **(P2.1)** 长期记忆语义检索（Milvus 未集成，关键词匹配降级） |

### MCP 服务管理（网关 /api/v1/mcp）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | /services | 创建MCP服务（SSE/STDIO） |
| GET | /services | 获取MCP服务列表 |
| GET | /services/{id} | 获取MCP服务详情 |
| PUT | /services/{id} | 更新MCP服务 |
| DELETE | /services/{id} | 删除MCP服务 |
| POST | /services/{id}/connect | 连接MCP服务 |
| POST | /services/{id}/disconnect | 断开MCP服务 |
| GET | /services/{id}/tools | 自动发现工具列表 |
| GET | /tools | 获取所有已发现工具 |
| PUT | /tools/{id}/toggle | 工具启用/禁用开关 |
| POST | /tools/{id}/call | 手动调用工具 |
| GET | /call-logs | 工具调用日志 |

### Skill 管理（网关 /api/v1/skills）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | / | 创建Skill |
| GET | / | 获取Skill列表（Level0） |
| GET | /{id} | 获取Skill详情（Level1/Level2按需） |
| PUT | /{id} | 更新Skill |
| DELETE | /{id} | 删除Skill |
| POST | /import/local | 本地文件导入（.md/.skill/.json/.zip） |
| POST | /import/url | 在线URL导入（HTTP GET拉取） |

---

## P2 新增：MCP + Skill 使用指南

### 创建一个 SSE 模式 MCP 服务

1. 进入**MCP服务管理** → 新建MCP服务 → 选择SSE模式 → 填入URL（如 https://mcp.example.com/sse ）
2. 点击「连接」→ 状态转为绿色connected → 自动发现工具列表
3. 进入**Agent管理** → 编辑Agent → 展开「MCP服务绑定」→ 添加刚创建的MCP服务
4. 开始对话，描述需求即可自动调用工具（ReAct循环最多8轮）

### 创建 STDIO 模式 MCP 服务

1. 选择STDIO模式 → 填入 command: `python` + args: `/path/to/your/mcp_server.py`
2. 保存后点击连接，自动启动子进程并JSON-RPC通信

### 导入 Skill

- **本地导入**：.md/.skill/.json 文件，自动解析生成3级Level
- **在线导入**：粘贴 raw.githubusercontent.com 或其他可直接GET的URL
- 手动创建：在表单里填入Level0/Level1/Level2内容

### 渐进式披露

Skill加载遵循3级：
- Level 0 (300 tokens)：Agent启动时加载所有Skill的名称+描述+标签
- Level 1 (3000 tokens)：当LLM决定使用某Skill时按需加载完整步骤+示例
- Level 2 (10000 tokens)：信息不足时自动追加边界条件+异常处理+最佳实践

### 工具调用可视化

在对话页面：
- 🔧 灰色卡片：正在调用的工具 + 入参
- ✅ 绿色卡片：工具返回结果（可展开查看）
- ❌ 红色卡片：工具调用失败原因
- 🔄 重新生成按钮：丢弃最后回答，重新执行对话轮次

---

## P2.1 新增：智能化增强使用指南

### 长期记忆自动评估

多轮对话结束后，chat-svc 会**异步**调用 mem-svc 的 `/api/v1/memory/evaluate` 接口，自动从对话历史中提炼值得持久化的信息：

1. chat-svc `_trigger_memory_evaluation`：best-effort 模式，失败不影响主对话
2. mem-svc `evaluate_memory`：加载 Agent 的 LLM 配置，动态创建适配器（复用 Agent 绑定模型）
3. LLM 按结构化 Prompt 返回 JSON：`{should_update, updates:[{segment, action, key, value}]}`
4. 按 segment（`user_profile` / `environment_facts` / `experience`）分别应用更新，version+1 持久化

> 验证方式：发起多轮对话后，进入**记忆查看器**页面查看长期记忆，应能看到从对话中提炼的偏好/事实/经验。

### 流式思考/回答事件分离

解决多轮 ReAct 推理中最终回答"先出现在思考区块、再迁移到回答区块"的视觉错位：

- 后端缓冲每轮 LLM content，流结束后根据 `has_tool_calls` 判断推送事件：
  - 中间轮（有 tool_calls）→ `thinking` 事件 → 思考区块
  - 最终轮（无 tool_calls）→ `message` 事件 → 回答区块
- 前端 `thinking_to_answer` 事件仅保留中间推理或清空思考区，不做迁移
- 思考区块显示时长统计（累加每轮 `duration_ms`）

### 技能按需筛选

避免所有 Skill 全量加载导致上下文开销过大：

- 关键词提取：中文 2/3/4 字滑动窗口 + 英文驼峰/分隔符拆分
- 两级匹配：**名称直接命中（强相关）优先**；描述命中（弱相关）次选
- 有名称命中时**只返回名称命中的技能**，排除纯描述匹配
- 无任何命中 → 回退全量（保守策略）

### Plan-and-Execute 工作模式

创建 Agent 时选择 `workflow_mode=plan-and-execute`：

1. LLM 先生成 `steps[]` 计划清单 → SSE 推送 `plan_generated` 事件
2. 前端渲染 checklist 卡片 + 状态指示器
3. 按 steps 顺序逐步执行，每步更新状态
4. 所有步骤完成后调用 LLM 综合总结输出最终回答

### DeepSeek R1 reasoning_content 回传

DeepSeek R1 系列思考模型的 reasoning token 会逐块累积并回传下一轮，避免 API 400 错误。无需用户干预，由 `llm_adapter.py` 自动处理。

### MCP web_search fallback

当绑定的 web_search MCP 服务不可用时，自动降级到 DuckDuckGo 搜索 + 结构化 mock，不阻断 ReAct 循环。

### Mermaid 图表渲染

LLM 回答中的 ` ```mermaid ` 代码块会被自动渲染为可视化图形：

- 工具栏切换"图形/源码"视图
- 渲染失败时回退显示源码 + 错误提示（不导致 UI 崩溃）
- 支持 dark mode 与自适应样式

---

## P2 功能清单

### MCP 双模式接入
- [x] SSE模式接入远程MCP服务（HTTP+SSE长连接）
- [x] STDIO模式启动本地子进程（JSON-RPC 2.0 over stdin/stdout）
- [x] 连接/断开/重连管理 + 状态可视化
- [x] 自动发现工具并持久化
- [x] 工具粒度启用/禁用开关
- [x] 工具调用日志记录（入参/结果/耗时）
- [x] **(P2.1)** web_search 内置 fallback（MCP不可用时走 DuckDuckGo + 结构化 mock）
- [x] **(P2.1)** OAuth 2.0 认证流程路由（支持 GitHub/Google 等 provider）

### Skills 技能管理
- [x] Skill CRUD + 3级渐进式披露结构（Level0/1/2）
- [x] 本地文件导入（.md/.skill/.json/.zip）
- [x] 在线URL导入（HTTP拉取+自动解析）
- [x] 渐进式Prompt构建（按Token预算截断）
- [x] Agent绑定Skill（优先级/开关）
- [x] **(P2.1)** 按需筛选：基于用户查询关键词动态筛选相关 Skill（名称优先匹配，中文滑动窗口 + 英文驼峰拆分）

### 对话增强（ReAct）
- [x] ReAct完整循环：Thought → ToolCall → Observation → 最多8轮
- [x] Function Calling模式：LLM原生bind_tools（如provider支持）
- [x] 文本模式兜底：从文本解析ACTION/ARGS调用工具
- [x] 工具调用SSE事件 + 前端可视化卡片
- [x] 对话重新生成（删除最后消息+重跑）
- [x] **(P2.1)** 流式思考/回答事件分离（后端缓冲 + `has_tool_calls` 路由，最终回答不再先显示在思考区）
- [x] **(P2.1)** Plan-and-Execute 工作模式（计划生成 → 分步执行 → 综合总结 LLM 调用）
- [x] **(P2.1)** DeepSeek R1 reasoning_content 回传（思考 token 累积，避免下一轮 API 400 错误）
- [x] **(P2.1)** LLM 调用失败 graceful degradation（已有回答 + 错误提示）
- [x] **(P2.1)** 单 SSE 事件异常隔离（onMessage/onDone/onError 全局 try/catch）

### 记忆深化
- [x] 短期记忆Redis缓存（活跃会话24h TTL，未命中fallback MySQL）
- [x] 长期记忆评估更新（对话结束LLM评估→持久化，P2含占位降级）
- [x] 长期记忆语义检索（Milvus占位，P2关键词匹配降级）
- [x] 短期记忆缓存失效接口
- [x] **(P2.1)** 长期记忆自动评估链路（chat-svc → mem-svc `/evaluate`，异步 best-effort 触发）
- [x] **(P2.1)** mem-svc 动态加载 Agent 的 LLM 配置创建适配器（复用 Agent 绑定模型）
- [x] **(P2.1)** 记忆摘要返回实际内容字段（user_profile/environment_facts/experience/shared_items）

### 前端交互增强
- [x] **(P2.1)** 用户消息复制/删除/回撤功能
- [x] **(P2.1)** Agent 最终回答复制按钮
- [x] **(P2.1)** Mermaid 图表渲染组件（图形/源码切换 + 失败兜底）
- [x] **(P2.1)** Plan-and-Execute 计划卡片（checklist 样式 + 状态指示器）
- [x] **(P2.1)** 工作模式徽标显示（ReAct / Plan-and-Execute / Hybrid）
- [x] **(P2.1)** 关键词高亮修复（`indexOf` 替代动态正则，无 SyntaxError）
- [x] **(P2.1)** 历史对话刷新工具状态正确合并（修复"执行中"卡死）
- [x] **(P2.1)** 区块固定顺序：工作模式 → 思考 → 技能 → 工具 → 最终回答

---

## 项目结构

```
agent-service-platform-phase1/
├── docker-compose.yml              # Docker一键部署
├── .env.example                    # 环境变量模板
├── requirements.txt                # Python 统一依赖
├── _launch_backends.py             # 后端一键启动（5 个服务）
├── _selftest_chat.py               # 聊天自测脚本（SSE + 持久化验证）
├── P1阶段代码修改文档.md             # P1 阶段代码修改文档
├── P2阶段代码修改文档.md             # P2 阶段代码修改文档（含 bd861bc 迭代）
├── P2阶段软件测试文档.md             # P2 阶段软件测试文档 v2.0
├── .gitignore
│
├── scripts/                        # 启动/停止脚本
│   ├── start-middleware.sh         # 中间件一键启动 (Linux/macOS)
│   ├── stop-middleware.sh          # 中间件一键停止 (Linux/macOS)
│   ├── start-middleware.py         # 中间件一键启动 (跨平台)
│   ├── stop-middleware.py          # 中间件一键停止 (跨平台)
│   ├── start-backend.sh            # 后端服务一键启动 (Linux/macOS)
│   ├── stop-backend.sh             # 后端服务一键停止 (Linux/macOS)
│   ├── start-backend.py            # 后端服务一键启动 (跨平台)
│   ├── stop-backend.py             # 后端服务一键停止 (跨平台)
│   ├── seed_via_mysql.py           # 数据库种子数据（官方 Agent/LLM/Skill）
│   └── seed_initial_data.{py,ps1}  # 跨平台种子脚本
│
├── frontend/                       # Vue3 前端
│   ├── package.json                # 依赖（vue/antd/axios/marked/mermaid）
│   ├── vite.config.js              # Vite配置 + API代理
│   └── src/
│       ├── api/index.js            # API请求封装 + SSE流式处理 ★
│       ├── router/index.js         # 路由配置（9个页面）
│       ├── App.vue                 # 主布局（侧边栏+内容区）
│       ├── components/
│       │   └── MermaidBlock.vue    # (P2.1) Mermaid 图表渲染组件 ★
│       └── views/
│           ├── chat/               # 对话页面（SSE全事件链路 + Plan&Execute） ★
│           ├── agent/              # Agent管理（含绑定面板 + tools-summary Drawer） ★
│           ├── llm-config/          # LLM配置 ★
│           ├── memory/              # 记忆查看器（长期/短期/摘要弹窗） ★
│           ├── mcp/                 # (P2) MCP管理 ★
│           ├── skill/               # (P2) Skill管理 ★
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
│   │   │   ├── llm_adapter.py      # LangChain LLM适配器（含 reasoning_content 回传） ★
│   │   │   ├── mcp_adapter.py      # (P2) MCP SSE/STDIO适配器 ★
│   │   │   └── skill_manager.py    # (P2) Skill渐进式披露管理器 ★
│   │   └── infrastructure/
│   │       ├── db/                  # 数据库引擎+会话
│   │       └── cache/               # Redis缓存工具
│   │
│   ├── gateway/                    # API网关(:8000)
│   ├── agent-svc/                  # Agent服务(:8001) ★
│   │   ├── main.py
│   │   ├── routers/
│   │   │   ├── llm_config.py       # LLM配置CRUD
│   │   │   └── agent.py            # Agent CRUD+状态机+绑定
│   │   └── services/
│   │       ├── llm_service.py      # LLM业务逻辑（加密/掩码）
│   │       └── agent_service.py     # Agent业务逻辑（状态机/克隆/官方Agent/tools-summary）
│   │
│   ├── chat-svc/                   # 对话服务(:8002) ★
│   │   ├── main.py
│   │   ├── routers/chat.py         # 会话CRUD+SSE流式+停止生成+重新生成
│   │   └── services/
│   │       ├── chat_service.py     # 对话编排核心：ReAct循环 + 事件分离 + 技能筛选 + 记忆评估触发 ★
│   │       └── memory_service.py   # 记忆加载+上下文压缩
│   │
│   ├── tool-svc/                   # 工具服务(:8003) ★
│   │   ├── main.py
│   │   ├── routers/
│   │   │   ├── mcp.py              # (P2) MCP服务CRUD+连接管理
│   │   │   ├── skill.py            # (P2) Skill CRUD+导入
│   │   │   ├── tool_call.py        # (P2) 工具调用代理+调用日志
│   │   │   └── oauth.py            # (P2.1) OAuth 2.0 认证流程
│   │   └── services/
│   │       ├── mcp_service.py      # (P2) MCP连接+工具发现+web_search fallback
│   │       ├── skill_service.py    # (P2) Skill导入解析+渐进披露
│   │       └── oauth_service.py    # (P2.1) OAuth 业务逻辑
│   │
│   ├── mem-svc/                    # 记忆服务(:8004) ★
│   │   ├── main.py
│   │   ├── routers/memory.py       # 长期/短期/语义检索 + /evaluate（动态加载 LLM adapter） ★
│   │   └── services/
│   │       ├── memory_service.py   # 记忆CRUD+评估更新+语义检索 ★
│   │       └── short_term_cache.py # (P2) Redis缓存(TTL=24h) ★
│   │
│   ├── rag-svc/                    # (P3) RAG服务骨架
│   ├── chatbi-svc/                 # (P3) ChatBI服务骨架
│   ├── coord-svc/                  # (P4) 协同服务骨架
│   └── evo-svc/                    # (P4) 进化服务骨架
│
└── infra/
    ├── mysql/
    │   ├── init.sql                # 数据库初始化(20张表)
    │   └── migrations/             # (P2.1) 迁移脚本
    │       ├── 20260814_add_thinking_to_messages.sql          # messages 表新增 thinking 字段
    │       ├── 20260819_add_attachments_to_messages.sql       # messages 表新增 attachments 字段
    │       ├── 20260819_add_builtin_flag.sql                  # skills 表新增 is_builtin 标记
    │       ├── 20260819_add_skill_success_count.sql            # skills 表新增 success_count
    │       └── 20260819_rename_drawing_agent_to_design_mermaid.sql  # 内置 Agent 重命名
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
| Redis | - | 短期记忆缓存（P2） |
| aiohttp | - | SSE模式MCP HTTP客户端（P2） |
| MinIO SDK (minio) | - | Skill文件对象存储（P2） |
| PyMilvus | - | 长期记忆向量检索（P2） |
| python-multipart | - | 文件上传解析（Skill导入）（P2） |

### 前端

| 技术 | 版本 | 用途 |
|------|------|------|
| Vue | 3.4+ | 响应式框架 |
| Vue Router | 4 | 路由管理 |
| Pinia | 2 | 状态管理 |
| Ant Design Vue | 4 | UI组件库 |
| Axios | 1 | HTTP请求 |
| marked | 12 | Markdown渲染 |
| mermaid | 10+ | (P2.1) Mermaid 图表渲染 |
| Vite | 5 | 构建工具 |

---

## 开发进度

- [x] **Phase 0** — 项目初始化（8微服务骨架 + Docker环境 + 数据库脚本）
- [x] **Phase 1** — 基础设施与Agent核心域（LLM接入 + Agent管理 + 流式对话 + 记忆管理）
- [x] **Phase 2** — 对话与工具域（MCP双模式 + Skill管理 + ReAct）
- [x] **Phase 2.1** — 智能化增强（长期记忆自动评估 + 流式思考/回答分离 + 技能按需筛选 + Plan-and-Execute + DeepSeek R1 兼容 + MCP fallback + Mermaid 渲染）← **当前版本**
- [ ] Phase 3 — RAG与ChatBI域（Agentic RAG + 智能问数 + Milvus 向量检索落地）
- [ ] Phase 4 — 协同与进化域（多Agent协作 + Hermes自我进化）
- [ ] Phase 5 — P1增强功能
- [ ] Phase 6 — P2远期规划

### Git 版本节点

| 版本 | Tag | 说明 |
|------|-----|------|
| Phase 0 | - | 项目初始化骨架 |
| Phase 1 | **v1.0-phase1** | LLM接入+Agent管理+流式对话+记忆管理 |
| Phase 2 | **v2.0-phase2** | MCP双模式+Skill渐进披露+ReAct循环+记忆深化 |
| **Phase 2.1** | **v2.1-phase2.1** | **长期记忆自动评估+流式思考/回答分离+技能按需筛选+Plan-and-Execute+DeepSeek R1+MCP fallback+Mermaid** |

---

## 数据库

数据库初始化脚本位于 [infra/mysql/init.sql](infra/mysql/init.sql)，共20张表；P2.1 迭代迁移脚本位于 [infra/mysql/migrations/](infra/mysql/migrations/)：

| 表名 | 所属域 | 说明 |
|------|--------|------|
| llm_configs | Agent域 | LLM配置（API Key加密存储） |
| agents | Agent域 | Agent定义（状态机/官方标记/克隆来源/workflow_mode） |
| long_term_memories | 记忆域 | 长期记忆（1:1关联Agent，version 化） |
| conversations | 对话域 | 会话 |
| messages | 对话域 | 消息记录（P2.1 新增 thinking / attachments 字段） |
| mcp_services | 工具域 | (P2) MCP服务注册 |
| mcp_tools | 工具域 | (P2) MCP工具 |
| agent_mcp_bindings | 工具域 | (P2) Agent-MCP绑定 |
| skills | 工具域 | (P2) Skill技能（Level0/1/2，P2.1 新增 is_builtin / success_count） |
| agent_skill_bindings | 工具域 | (P2) Agent-Skill绑定 |
| knowledge_bases | RAG域 | (P3) 知识库 |
| documents | RAG域 | (P3) 文档 |
| datasource_configs | ChatBI域 | (P3) 数据源配置 |
| collaboration_tasks | 协同域 | (P4) 协作任务 |
| collaboration_steps | 协同域 | (P4) 协作步骤 |
| evolution_records | 进化域 | (P4) 进化记录 |
| skill_proposals | 进化域 | (P4) Skill提议 |
| tool_call_logs | 工具域 | (P2) 工具调用日志 |
| skill_usage_stats | 进化域 | Skill使用统计 |
| evolution_metrics | 进化域 | 进化指标 |

> P1阶段使用前5张表（llm_configs / agents / long_term_memories / conversations / messages）。
> P2阶段追加使用 mcp_services / mcp_tools / agent_mcp_bindings / skills / agent_skill_bindings / tool_call_logs 共6张表。
> P2.1 阶段通过迁移脚本为现有表补充字段：messages 新增 thinking/attachments；skills 新增 is_builtin/success_count；并将内置"绘图助手"Agent 重命名为"软件设计图绘图助手"。
> 其余表已建好待后续 Phase 使用。

### P2.1 迁移脚本执行顺序

```bash
# 在 init.sql 执行后按时间顺序执行迁移
mysql -u root -proot123 agent_service < infra/mysql/migrations/20260814_add_thinking_to_messages.sql
mysql -u root -proot123 agent_service < infra/mysql/migrations/20260819_add_attachments_to_messages.sql
mysql -u root -proot123 agent_service < infra/mysql/migrations/20260819_add_builtin_flag.sql
mysql -u root -proot123 agent_service < infra/mysql/migrations/20260819_add_skill_success_count.sql
mysql -u root -proot123 agent_service < infra/mysql/migrations/20260819_rename_drawing_agent_to_design_mermaid.sql
```

> 所有迁移脚本均为**幂等**设计（`IF NOT EXISTS` / `IGNORE`），可重复执行不会报错。
