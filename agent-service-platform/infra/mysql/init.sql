-- ============================================================
-- AgentService平台 数据库初始化脚本
-- 数据库: MySQL 8.0
-- 版本: v3.0
-- ============================================================

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- ============================================================
-- 0. 创建数据库并启用数据库
-- ============================================================

CREATE DATABASE IF NOT EXISTS agent_service
DEFAULT CHARACTER SET utf8mb4
COLLATE utf8mb4_general_ci;

USE agent_service;

-- ============================================================
-- 1. LLM配置表
-- ============================================================
DROP TABLE IF EXISTS llm_configs;
CREATE TABLE llm_configs (
    id              VARCHAR(36) PRIMARY KEY DEFAULT (UUID()),
    name            VARCHAR(128) NOT NULL COMMENT '配置名称',
    provider        VARCHAR(64) NOT NULL COMMENT 'LLM提供商: openai/claude/qwen/deepseek/ollama/...',
    model_name      VARCHAR(128) NOT NULL COMMENT '模型名称',
    api_key         TEXT COMMENT 'API密钥 (加密存储)',
    api_base_url    VARCHAR(512) COMMENT 'API基础URL (本地部署用)',
    default_params  JSON COMMENT '默认参数: temperature/max_tokens/top_p',
    is_default      BOOLEAN DEFAULT FALSE COMMENT '是否默认模型',
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_provider (provider),
    INDEX idx_default (is_default)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='LLM模型配置表';

-- ============================================================
-- 2. Agent表
-- ============================================================
DROP TABLE IF EXISTS agents;
CREATE TABLE agents (
    id              VARCHAR(36) PRIMARY KEY DEFAULT (UUID()),
    name            VARCHAR(128) NOT NULL COMMENT 'Agent名称',
    description     TEXT COMMENT 'Agent描述',
    system_prompt   TEXT NOT NULL COMMENT '系统提示词',
    llm_config_id   VARCHAR(36) NOT NULL COMMENT 'LLM配置ID',
    status          ENUM('created','deployed','running','paused','stopped','error')
                    DEFAULT 'created' COMMENT 'Agent状态',
    is_official     BOOLEAN DEFAULT FALSE COMMENT '是否官方Agent',
    cloned_from_id  VARCHAR(36) COMMENT '克隆来源AgentID',
    temperature     FLOAT DEFAULT 0.7 COMMENT '采样温度',
    max_tokens      INT DEFAULT 4096 COMMENT '最大生成Token数',
    top_p           FLOAT DEFAULT 0.9 COMMENT 'Top-P采样',
    memory_strategy VARCHAR(32) DEFAULT 'standard' COMMENT '记忆策略',
    config          JSON COMMENT '其他配置',
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_status (status),
    INDEX idx_official (is_official),
    FOREIGN KEY (llm_config_id) REFERENCES llm_configs(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Agent表';

-- ============================================================
-- 3. 长期记忆表 (1:1对应Agent)
-- ============================================================
DROP TABLE IF EXISTS long_term_memories;
CREATE TABLE long_term_memories (
    id                VARCHAR(36) PRIMARY KEY DEFAULT (UUID()),
    agent_id          VARCHAR(36) UNIQUE NOT NULL COMMENT 'AgentID (1:1关系)',
    user_profile      JSON COMMENT '用户偏好画像',
    environment_facts JSON COMMENT '环境事实',
    experience        JSON COMMENT '经验教训',
    shared_items      JSON COMMENT '标记为共享的记忆项',
    version           INT DEFAULT 1 COMMENT '记忆版本号',
    updated_at        DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_at        DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='长期记忆表 - 与Agent 1:1关系';

-- ============================================================
-- 4. 会话表
-- ============================================================
DROP TABLE IF EXISTS conversations;
CREATE TABLE conversations (
    id              VARCHAR(36) PRIMARY KEY DEFAULT (UUID()),
    agent_id        VARCHAR(36) NOT NULL COMMENT '所属AgentID',
    user_id         VARCHAR(36) COMMENT '用户ID',
    title           VARCHAR(256) COMMENT '会话标题',
    status          ENUM('active','archived','deleted') DEFAULT 'active' COMMENT '会话状态',
    message_count   INT DEFAULT 0 COMMENT '消息数',
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_agent (agent_id),
    INDEX idx_status (status),
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='会话表';

-- ============================================================
-- 5. 消息表 (短期记忆)
-- ============================================================
DROP TABLE IF EXISTS messages;
CREATE TABLE messages (
    id              VARCHAR(36) PRIMARY KEY DEFAULT (UUID()),
    conversation_id VARCHAR(36) NOT NULL COMMENT '会话ID',
    message_type    ENUM('user','assistant','system','tool_call','tool_result','error')
                    NOT NULL COMMENT '消息类型',
    content         TEXT NOT NULL COMMENT '消息内容',
    tool_calls      JSON COMMENT '工具调用信息',
    tool_results    JSON COMMENT '工具返回结果',
    token_count     INT DEFAULT 0 COMMENT 'Token数量',
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_conversation (conversation_id, created_at),
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='消息表 - 短期记忆';

-- ============================================================
-- 6. MCP服务表
-- ============================================================
DROP TABLE IF EXISTS mcp_services;
CREATE TABLE mcp_services (
    id            VARCHAR(36) PRIMARY KEY DEFAULT (UUID()),
    name          VARCHAR(128) NOT NULL COMMENT 'MCP服务名称',
    description   TEXT COMMENT '服务描述',
    mode          ENUM('sse','stdio') NOT NULL COMMENT '接入模式: sse/stdio',
    sse_url       VARCHAR(512) COMMENT 'SSE模式URL',
    stdio_config  JSON COMMENT 'STDIO模式配置 (command, args, env)',
    status        ENUM('disconnected','connecting','connected','error')
                  DEFAULT 'disconnected' COMMENT '连接状态',
    error_message TEXT COMMENT '错误信息',
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_status (status),
    INDEX idx_mode (mode)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='MCP服务表';

-- ============================================================
-- 7. MCP工具表
-- ============================================================
DROP TABLE IF EXISTS mcp_tools;
CREATE TABLE mcp_tools (
    id              VARCHAR(36) PRIMARY KEY DEFAULT (UUID()),
    mcp_service_id  VARCHAR(36) NOT NULL COMMENT 'MCP服务ID',
    name            VARCHAR(128) NOT NULL COMMENT '工具名称',
    description     TEXT COMMENT '工具描述',
    input_schema    JSON COMMENT '工具参数Schema (JSON Schema)',
    enabled         BOOLEAN DEFAULT TRUE COMMENT '是否启用',
    usage_count     INT DEFAULT 0 COMMENT '使用次数',
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uk_mcp_tool (mcp_service_id, name),
    INDEX idx_enabled (enabled),
    FOREIGN KEY (mcp_service_id) REFERENCES mcp_services(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='MCP工具表';

-- ============================================================
-- 8. Agent-MCP绑定表
-- ============================================================
DROP TABLE IF EXISTS agent_mcp_bindings;
CREATE TABLE agent_mcp_bindings (
    id              VARCHAR(36) PRIMARY KEY DEFAULT (UUID()),
    agent_id        VARCHAR(36) NOT NULL COMMENT 'AgentID',
    mcp_service_id  VARCHAR(36) NOT NULL COMMENT 'MCP服务ID',
    config          JSON COMMENT '绑定配置',
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_agent_mcp (agent_id, mcp_service_id),
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE,
    FOREIGN KEY (mcp_service_id) REFERENCES mcp_services(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Agent-MCP服务绑定表';

-- ============================================================
-- 9. Skill表
-- ============================================================
DROP TABLE IF EXISTS skills;
CREATE TABLE skills (
    id           VARCHAR(36) PRIMARY KEY DEFAULT (UUID()),
    name         VARCHAR(128) NOT NULL COMMENT 'Skill名称',
    description  TEXT COMMENT 'Skill描述',
    category     VARCHAR(64) DEFAULT 'general' COMMENT '分类: programming/office/data-analysis/...',
    version      VARCHAR(32) DEFAULT '1.0.0' COMMENT '版本号',
    source       ENUM('local','online','auto_generated') DEFAULT 'local' COMMENT '来源',
    source_url   VARCHAR(512) COMMENT '来源URL (Git/HTTP)',
    enabled      BOOLEAN DEFAULT TRUE COMMENT '是否启用',
    usage_count  INT DEFAULT 0 COMMENT '使用次数',
    success_rate FLOAT DEFAULT 0.0 COMMENT '成功率',
    tags         JSON COMMENT '标签数组',
    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at   DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_category (category),
    INDEX idx_enabled (enabled),
    INDEX idx_source (source)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Skill技能表';

-- ============================================================
-- 10. Skill层级表 (渐进式披露 3级)
-- ============================================================
DROP TABLE IF EXISTS skill_levels;
CREATE TABLE skill_levels (
    id           VARCHAR(36) PRIMARY KEY DEFAULT (UUID()),
    skill_id     VARCHAR(36) NOT NULL COMMENT 'SkillID',
    level        TINYINT NOT NULL COMMENT '层级: 0=概要, 1=完整, 2=深度',
    name         VARCHAR(128) COMMENT '层级名称',
    content      TEXT NOT NULL COMMENT '层级内容',
    token_count  INT DEFAULT 0 COMMENT 'Token数量',
    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (skill_id) REFERENCES skills(id) ON DELETE CASCADE,
    UNIQUE KEY uk_skill_level (skill_id, level)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Skill层级内容表 - 渐进式披露';

-- ============================================================
-- 11. Agent-Skill绑定表
-- ============================================================
DROP TABLE IF EXISTS agent_skill_bindings;
CREATE TABLE agent_skill_bindings (
    id              VARCHAR(36) PRIMARY KEY DEFAULT (UUID()),
    agent_id        VARCHAR(36) NOT NULL COMMENT 'AgentID',
    skill_id        VARCHAR(36) NOT NULL COMMENT 'SkillID',
    priority        INT DEFAULT 0 COMMENT '优先级',
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uk_agent_skill (agent_id, skill_id),
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE,
    FOREIGN KEY (skill_id) REFERENCES skills(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Agent-Skill绑定表';

-- ============================================================
-- 12. 知识库表 (RAG)
-- ============================================================
DROP TABLE IF EXISTS knowledge_bases;
CREATE TABLE knowledge_bases (
    id              VARCHAR(36) PRIMARY KEY DEFAULT (UUID()),
    name            VARCHAR(128) NOT NULL COMMENT '知识库名称',
    description     TEXT COMMENT '知识库描述',
    default_index   ENUM('vector','keyword','tree','knowledge_graph','hybrid')
                    DEFAULT 'hybrid' COMMENT '默认索引类型',
    embedding_model VARCHAR(128) DEFAULT 'text-embedding-ada-002' COMMENT 'Embedding模型',
    chunk_size      INT DEFAULT 512 COMMENT '切片大小 (tokens)',
    chunk_overlap   INT DEFAULT 64 COMMENT '切片重叠 (tokens)',
    total_documents INT DEFAULT 0 COMMENT '文档总数',
    total_chunks    INT DEFAULT 0 COMMENT '切片总数',
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_default_index (default_index)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='知识库表 - RAG域';

-- ============================================================
-- 13. 文档表 (RAG)
-- ============================================================
DROP TABLE IF EXISTS documents;
CREATE TABLE documents (
    id              VARCHAR(36) PRIMARY KEY DEFAULT (UUID()),
    kb_id           VARCHAR(36) NOT NULL COMMENT '知识库ID',
    filename        VARCHAR(256) NOT NULL COMMENT '文件名',
    file_path       VARCHAR(512) NOT NULL COMMENT 'MinIO存储路径',
    file_type       VARCHAR(32) COMMENT '文件类型: pdf/docx/txt/md',
    file_size       BIGINT DEFAULT 0 COMMENT '文件大小 (bytes)',
    total_pages     INT DEFAULT 0 COMMENT '总页数',
    total_chunks    INT DEFAULT 0 COMMENT '切片数',
    status          ENUM('uploading','parsing','indexing','ready','error')
                    DEFAULT 'uploading' COMMENT '处理状态',
    error_message   TEXT COMMENT '错误信息',
    metadata        JSON COMMENT '元数据',
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_kb (kb_id),
    INDEX idx_status (status),
    FOREIGN KEY (kb_id) REFERENCES knowledge_bases(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='文档表 - RAG域';

-- ============================================================
-- 14. 文档切片表 (RAG)
-- ============================================================
DROP TABLE IF EXISTS document_chunks;
CREATE TABLE document_chunks (
    id              VARCHAR(36) PRIMARY KEY DEFAULT (UUID()),
    document_id     VARCHAR(36) NOT NULL COMMENT '文档ID',
    kb_id           VARCHAR(36) NOT NULL COMMENT '知识库ID',
    chunk_index     INT NOT NULL COMMENT '切片序号',
    content         TEXT NOT NULL COMMENT '切片内容',
    page_number     INT COMMENT '页码',
    token_count     INT DEFAULT 0 COMMENT 'Token数',
    metadata        JSON COMMENT '元数据',
    vector_id       VARCHAR(64) COMMENT 'Milvus中的向量ID',
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_document (document_id),
    INDEX idx_kb (kb_id),
    FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE,
    FOREIGN KEY (kb_id) REFERENCES knowledge_bases(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='文档切片表 - RAG域';

-- ============================================================
-- 15. 数据源表 (ChatBI)
-- ============================================================
DROP TABLE IF EXISTS data_sources;
CREATE TABLE data_sources (
    id                 VARCHAR(36) PRIMARY KEY DEFAULT (UUID()),
    name               VARCHAR(128) NOT NULL COMMENT '数据源名称',
    description        TEXT COMMENT '描述',
    db_type            ENUM('mysql','postgresql','sqlite','clickhouse')
                       NOT NULL COMMENT '数据库类型',
    host               VARCHAR(256) COMMENT '主机地址',
    port               INT COMMENT '端口',
    database_name      VARCHAR(128) COMMENT '数据库名',
    username           VARCHAR(128) COMMENT '用户名',
    encrypted_password TEXT COMMENT '加密后的密码',
    sqlite_path        VARCHAR(512) COMMENT 'SQLite文件路径',
    status             ENUM('active','error','disabled') DEFAULT 'active' COMMENT '状态',
    schema_cache       JSON COMMENT 'Schema缓存',
    created_at         DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at         DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_status (status),
    INDEX idx_db_type (db_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='数据源表 - ChatBI域';

-- ============================================================
-- 16. 查询记录表 (ChatBI)
-- ============================================================
DROP TABLE IF EXISTS query_records;
CREATE TABLE query_records (
    id              VARCHAR(36) PRIMARY KEY DEFAULT (UUID()),
    datasource_id   VARCHAR(36) NOT NULL COMMENT '数据源ID',
    user_id         VARCHAR(36) COMMENT '用户ID',
    natural_language TEXT NOT NULL COMMENT '自然语言问题',
    sql_query       TEXT COMMENT '生成的SQL',
    result_json     JSON COMMENT '查询结果',
    result_count    INT DEFAULT 0 COMMENT '结果行数',
    execution_time  FLOAT DEFAULT 0 COMMENT '执行时间 (秒)',
    status          ENUM('success','failed','security_blocked')
                    DEFAULT 'success' COMMENT '状态',
    error_message   TEXT COMMENT '错误信息',
    is_favorite     BOOLEAN DEFAULT FALSE COMMENT '是否收藏',
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_datasource (datasource_id),
    INDEX idx_status (status),
    INDEX idx_favorite (is_favorite),
    FOREIGN KEY (datasource_id) REFERENCES data_sources(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='查询记录表 - ChatBI域';

-- ============================================================
-- 17. 协作任务表
-- ============================================================
DROP TABLE IF EXISTS collaboration_tasks;
CREATE TABLE collaboration_tasks (
    id                  VARCHAR(36) PRIMARY KEY DEFAULT (UUID()),
    mode                ENUM('supervisor','route','plan_execute')
                        NOT NULL COMMENT '协作模式',
    task_description    TEXT NOT NULL COMMENT '任务描述',
    supervisor_agent_id VARCHAR(36) COMMENT '主管AgentID (supervisor模式)',
    participant_ids     JSON COMMENT '参与AgentID列表',
    status              ENUM('pending','running','completed','failed','cancelled')
                        DEFAULT 'pending' COMMENT '任务状态',
    result              JSON COMMENT '最终结果',
    error_message       TEXT COMMENT '错误信息',
    started_at          DATETIME COMMENT '开始时间',
    completed_at        DATETIME COMMENT '完成时间',
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_status (status),
    INDEX idx_mode (mode),
    FOREIGN KEY (supervisor_agent_id) REFERENCES agents(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='协作任务表 - 协同域';

-- ============================================================
-- 18. 协作步骤表
-- ============================================================
DROP TABLE IF EXISTS collaboration_steps;
CREATE TABLE collaboration_steps (
    id                  VARCHAR(36) PRIMARY KEY DEFAULT (UUID()),
    task_id             VARCHAR(36) NOT NULL COMMENT '协作任务ID',
    agent_id            VARCHAR(36) COMMENT '执行AgentID',
    step_index          INT NOT NULL COMMENT '步骤序号',
    step_type           VARCHAR(32) COMMENT '步骤类型',
    description         TEXT COMMENT '步骤描述',
    input               JSON COMMENT '输入',
    output              JSON COMMENT '输出',
    status              ENUM('pending','running','completed','failed','skipped')
                        DEFAULT 'pending' COMMENT '状态',
    error_message       TEXT COMMENT '错误信息',
    started_at          DATETIME COMMENT '开始时间',
    completed_at        DATETIME COMMENT '完成时间',
    created_at          DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_task (task_id, step_index),
    FOREIGN KEY (task_id) REFERENCES collaboration_tasks(id) ON DELETE CASCADE,
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='协作步骤表 - 协同域';

-- ============================================================
-- 19. 进化记录表
-- ============================================================
DROP TABLE IF EXISTS evolution_records;
CREATE TABLE evolution_records (
    id              VARCHAR(36) PRIMARY KEY DEFAULT (UUID()),
    agent_id        VARCHAR(36) NOT NULL COMMENT 'AgentID',
    evolution_type  ENUM('task_evaluation','skill_proposal','memory_consolidation','safety_scan')
                    NOT NULL COMMENT '进化类型',
    content         JSON COMMENT '进化内容',
    success_score   FLOAT COMMENT '成功度评分 (0-100)',
    metadata        JSON COMMENT '元数据',
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_agent (agent_id),
    INDEX idx_type (evolution_type),
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='进化记录表 - 进化域';

-- ============================================================
-- 20. Skill提议表 (自动生成的Skill提议)
-- ============================================================
DROP TABLE IF EXISTS skill_proposals;
CREATE TABLE skill_proposals (
    id              VARCHAR(36) PRIMARY KEY DEFAULT (UUID()),
    agent_id        VARCHAR(36) NOT NULL COMMENT '来源AgentID',
    name            VARCHAR(128) NOT NULL COMMENT '提议Skill名称',
    description     TEXT COMMENT 'Skill描述',
    proposed_content JSON COMMENT '提议的Skill内容',
    reason          TEXT COMMENT '提议原因 (基于什么模式)',
    source_tasks    JSON COMMENT '来源任务列表',
    status          ENUM('pending','approved','rejected','registered')
                    DEFAULT 'pending' COMMENT '状态',
    feedback        TEXT COMMENT '反馈意见',
    registered_skill_id VARCHAR(36) COMMENT '注册后的SkillID',
    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_agent (agent_id),
    INDEX idx_status (status),
    FOREIGN KEY (agent_id) REFERENCES agents(id) ON DELETE CASCADE,
    FOREIGN KEY (registered_skill_id) REFERENCES skills(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='Skill提议表 - 进化域';

-- ============================================================
-- 初始化数据
-- ============================================================

-- 默认LLM配置 (占位，用户自行填写API Key)
INSERT INTO llm_configs (id, name, provider, model_name, api_key, is_default, default_params) VALUES
(UUID(), 'OpenAI GPT-4o', 'openai', 'gpt-4o', '', TRUE,
 '{"temperature": 0.7, "max_tokens": 4096, "top_p": 0.9}');

-- 默认知识库
INSERT INTO knowledge_bases (id, name, description, default_index, total_documents, total_chunks) VALUES
(UUID(), '默认知识库', '系统默认知识库', 'hybrid', 0, 0);

SET FOREIGN_KEY_CHECKS = 1;
