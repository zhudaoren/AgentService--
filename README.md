# AgentService平台

> 基于 AgenticRAG + LangChain + LangGraph + FastAPI + Vue3 的智能体服务平台

## 快速开始

### 方式一：Docker Compose 一键启动（推荐）

```bash
# 1. 复制环境变量配置
cp .env.example .env

# 2. 一键启动所有服务
docker-compose up -d

# 3. 检查服务状态
docker-compose ps

# 4. 验证健康检查
curl http://localhost:8000/api/v1/health
```

### 方式二：本地开发模式启动

#### 前置条件
- Python 3.12+
- Node.js 18+
- MySQL 8.0+
- Redis 7.0+

#### 后端启动

```bash
# 1. 安装Python依赖
pip install fastapi uvicorn[standard] pydantic pydantic-settings sqlalchemy aiomysql redis cryptography httpx python-multipart

# 2. 初始化数据库
mysql -u root -p < infra/mysql/init.sql

# 3. 启动API网关
cd services/gateway
PYTHONPATH=../shared:. python -m uvicorn main:app --port 8000 --reload

# 4. 启动各微服务（每个开一个终端）
cd services/agent-svc  && PYTHONPATH=../shared:. python -m uvicorn main:app --port 8001 --reload
cd services/chat-svc   && PYTHONPATH=../shared:. python -m uvicorn main:app --port 8002 --reload
cd services/tool-svc   && PYTHONPATH=../shared:. python -m uvicorn main:app --port 8003 --reload
cd services/mem-svc    && PYTHONPATH=../shared:. python -m uvicorn main:app --port 8004 --reload
cd services/rag-svc    && PYTHONPATH=../shared:. python -m uvicorn main:app --port 8005 --reload
cd services/chatbi-svc && PYTHONPATH=../shared:. python -m uvicorn main:app --port 8006 --reload
cd services/coord-svc  && PYTHONPATH=../shared:. python -m uvicorn main:app --port 8007 --reload
cd services/evo-svc    && PYTHONPATH=../shared:. python -m uvicorn main:app --port 8008 --reload
```

#### 前端启动

```bash
cd frontend
npm install
npm run dev
# 打开 http://localhost:5173
```

## 服务端口

| 服务 | 端口 | 说明 |
|------|------|------|
| API Gateway | 8000 | API网关，统一入口 |
| agent-svc | 8001 | Agent管理服务 |
| chat-svc | 8002 | 对话服务 |
| tool-svc | 8003 | 工具服务(MCP+Skill) |
| mem-svc | 8004 | 记忆管理服务 |
| rag-svc | 8005 | RAG检索服务 |
| chatbi-svc | 8006 | ChatBI智能问数 |
| coord-svc | 8007 | 多Agent协同服务 |
| evo-svc | 8008 | 自我进化服务 |
| Frontend | 5173 | Vue3前端(开发模式) |
| MySQL | 3306 | 数据库 |
| Redis | 6379 | 缓存 |
| MinIO | 9000/9001 | 对象存储 |
| RabbitMQ | 5672/15672 | 消息队列 |

## 健康检查

```bash
# 检查网关
curl http://localhost:8000/healthz

# 检查所有下游服务
curl http://localhost:8000/api/v1/health

# 检查单个服务
curl http://localhost:8001/healthz  # agent-svc
curl http://localhost:8002/healthz  # chat-svc
# ...以此类推
```

## 项目结构

```
agent-service-platform/
├── docker-compose.yml          # Docker一键部署
├── .env.example                # 环境变量模板
├── frontend/                   # Vue3前端
├── services/                   # 后端微服务
│   ├── shared/                 # 共享库(DDD基类/基础设施)
│   ├── gateway/                # API网关(:8000)
│   ├── agent-svc/              # Agent服务(:8001)
│   ├── chat-svc/               # 对话服务(:8002)
│   ├── tool-svc/               # 工具服务(:8003)
│   ├── mem-svc/                # 记忆服务(:8004)
│   ├── rag-svc/                # RAG服务(:8005)
│   ├── chatbi-svc/             # ChatBI服务(:8006)
│   ├── coord-svc/              # 协同服务(:8007)
│   └── evo-svc/                # 进化服务(:8008)
└── infra/                      # 基础设施配置
    ├── mysql/init.sql          # 数据库初始化(20张表)
    └── nginx/default.conf      # Nginx配置
```

## 开发进度

- [x] **Phase 0** - 项目初始化 (已完成)
- [ ] Phase 1 - 基础设施与Agent核心域
- [ ] Phase 2 - 对话与工具域
- [ ] Phase 3 - RAG与ChatBI域
- [ ] Phase 4 - 协同与进化域
- [ ] Phase 5 - P1增强功能
