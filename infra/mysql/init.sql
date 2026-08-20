-- ============================================================
-- AgentService Platform Phase1 - 数据库初始化脚本
-- 基于实际运行数据库的真实表结构生成
-- ============================================================

-- ============================================================
-- 1. LLM模型配置表
-- ============================================================
DROP TABLE IF EXISTS evolution_records;
DROP TABLE IF EXISTS collaboration_steps;
DROP TABLE IF EXISTS collaboration_tasks;
DROP TABLE IF EXISTS query_records;
DROP TABLE IF EXISTS data_sources;
DROP TABLE IF EXISTS document_chunks;
DROP TABLE IF EXISTS documents;
DROP TABLE IF EXISTS knowledge_bases;
DROP TABLE IF EXISTS agent_skill_bindings;
DROP TABLE IF EXISTS skill_levels;
DROP TABLE IF EXISTS skills;
DROP TABLE IF EXISTS agent_mcp_bindings;
DROP TABLE IF EXISTS mcp_tools;
DROP TABLE IF EXISTS mcp_services;
DROP TABLE IF EXISTS messages;
DROP TABLE IF EXISTS conversations;
DROP TABLE IF EXISTS long_term_memories;
DROP TABLE IF EXISTS agents;
DROP TABLE IF EXISTS llm_configs;
DROP TABLE IF EXISTS skill_proposals;
DROP TABLE IF EXISTS tool_call_logs;

CREATE TABLE llm_configs (
  id varchar(36) NOT NULL DEFAULT (uuid()),
  name varchar(128) NOT NULL COMMENT '配置名称',
  provider varchar(64) NOT NULL COMMENT 'LLM提供商: openai/claude/qwen/deepseek/ollama/...',
  model_name varchar(128) NOT NULL COMMENT '模型名称',
  api_key text COMMENT 'API密钥 (加密存储)',
  api_base_url varchar(512) DEFAULT NULL COMMENT 'API基础URL (本地部署用)',
  default_params json DEFAULT NULL COMMENT '默认参数: temperature/max_tokens/top_p',
  is_default tinyint(1) DEFAULT '0' COMMENT '是否默认模型',
  is_builtin tinyint(1) DEFAULT '0' COMMENT '是否平台内置官方LLM配置',
  created_at datetime DEFAULT CURRENT_TIMESTAMP,
  updated_at datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_provider (provider),
  KEY idx_default (is_default)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='LLM模型配置表';

-- ============================================================
-- 2. Agent表
-- ============================================================
CREATE TABLE agents (
  id varchar(36) NOT NULL DEFAULT (uuid()),
  name varchar(128) NOT NULL COMMENT 'Agent名称',
  description text COMMENT 'Agent描述',
  system_prompt text NOT NULL COMMENT '系统提示词',
  llm_config_id varchar(36) NOT NULL COMMENT 'LLM配置ID',
  status enum('created','deployed','running','paused','stopped','error') DEFAULT 'created' COMMENT 'Agent状态',
  is_official tinyint(1) DEFAULT '0' COMMENT '是否官方Agent',
  cloned_from_id varchar(36) DEFAULT NULL COMMENT '克隆来源AgentID',
  temperature float DEFAULT '0.7' COMMENT '采样温度',
  max_tokens int DEFAULT '4096' COMMENT '最大生成Token数',
  top_p float DEFAULT '0.9' COMMENT 'Top-P采样',
  memory_strategy varchar(32) DEFAULT 'standard' COMMENT '记忆策略',
  config json DEFAULT NULL COMMENT '其他配置',
  created_at datetime DEFAULT CURRENT_TIMESTAMP,
  updated_at datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_status (status),
  KEY idx_official (is_official),
  KEY llm_config_id (llm_config_id),
  CONSTRAINT agents_ibfk_1 FOREIGN KEY (llm_config_id) REFERENCES llm_configs (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='Agent表';

-- ============================================================
-- 3. 长期记忆表
-- ============================================================
CREATE TABLE long_term_memories (
  id varchar(36) NOT NULL DEFAULT (uuid()),
  agent_id varchar(36) NOT NULL COMMENT 'AgentID (1:1关系)',
  user_profile json DEFAULT NULL COMMENT '用户偏好画像',
  environment_facts json DEFAULT NULL COMMENT '环境事实',
  experience json DEFAULT NULL COMMENT '经验教训',
  shared_items json DEFAULT NULL COMMENT '标记为共享的记忆项',
  version int DEFAULT '1' COMMENT '记忆版本号',
  updated_at datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  created_at datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY agent_id (agent_id),
  CONSTRAINT long_term_memories_ibfk_1 FOREIGN KEY (agent_id) REFERENCES agents (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='长期记忆表 - 与Agent 1:1关系';

-- ============================================================
-- 4. 会话表
-- ============================================================
CREATE TABLE conversations (
  id varchar(36) NOT NULL DEFAULT (uuid()),
  agent_id varchar(36) NOT NULL COMMENT '所属AgentID',
  user_id varchar(36) DEFAULT NULL COMMENT '用户ID',
  title varchar(256) DEFAULT NULL COMMENT '会话标题',
  status enum('active','archived','deleted') DEFAULT 'active' COMMENT '会话状态',
  message_count int DEFAULT '0' COMMENT '消息数',
  created_at datetime DEFAULT CURRENT_TIMESTAMP,
  updated_at datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_agent (agent_id),
  KEY idx_status (status),
  CONSTRAINT conversations_ibfk_1 FOREIGN KEY (agent_id) REFERENCES agents (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='会话表';

-- ============================================================
-- 5. 消息表 (短期记忆)
-- ============================================================
CREATE TABLE messages (
  id varchar(36) NOT NULL DEFAULT (uuid()),
  conversation_id varchar(36) NOT NULL COMMENT '会话ID',
  message_type enum('user','assistant','system','tool_call','tool_result','error') NOT NULL COMMENT '消息类型',
  content mediumtext NOT NULL COMMENT '消息内容',
  thinking text COMMENT '思考过程内容（推理中间产物）',
  tool_calls mediumtext COMMENT '工具调用信息 (JSON字符串)',
  tool_results mediumtext COMMENT '工具返回结果 (JSON字符串)',
  attachments json DEFAULT NULL COMMENT '多模态附件列表（图片/音频 base64 或 URL）',
  token_count int DEFAULT '0' COMMENT 'Token数量',
  created_at datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_conversation (conversation_id, created_at),
  CONSTRAINT messages_ibfk_1 FOREIGN KEY (conversation_id) REFERENCES conversations (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='消息表 - 短期记忆';

-- ============================================================
-- 6. MCP服务表
-- ============================================================
CREATE TABLE mcp_services (
  id varchar(36) NOT NULL DEFAULT (uuid()),
  name varchar(128) NOT NULL COMMENT 'MCP服务名称',
  description text COMMENT '服务描述',
  mode enum('sse','stdio','streamable_http') NOT NULL COMMENT '接入模式: sse/stdio/streamable_http',
  sse_url varchar(512) DEFAULT NULL COMMENT 'SSE模式URL',
  stdio_config json DEFAULT NULL COMMENT 'STDIO模式配置 (command, args, env)',
  status enum('disconnected','connecting','connected','error') DEFAULT 'disconnected' COMMENT '连接状态',
  error_message text COMMENT '错误信息',
  last_connected_at datetime DEFAULT NULL COMMENT '最后连接时间',
  is_builtin tinyint(1) DEFAULT '0' COMMENT '是否平台内置官方MCP服务',
  created_at datetime DEFAULT CURRENT_TIMESTAMP,
  updated_at datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  headers json DEFAULT NULL COMMENT '自定义HTTP Headers',
  auth_type varchar(32) NOT NULL DEFAULT 'none' COMMENT '认证类型: none/bearer/basic/custom/oauth2',
  oauth_config json DEFAULT NULL COMMENT 'OAuth 2.1配置',
  oauth_tokens json DEFAULT NULL COMMENT 'OAuth 2.1令牌',
  oauth_status varchar(32) NOT NULL DEFAULT 'not_configured' COMMENT 'OAuth状态',
  PRIMARY KEY (id),
  KEY idx_status (status),
  KEY idx_mode (mode)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='MCP服务表';

-- ============================================================
-- 7. MCP工具表
-- ============================================================
CREATE TABLE mcp_tools (
  id varchar(36) NOT NULL DEFAULT (uuid()),
  mcp_service_id varchar(36) NOT NULL COMMENT 'MCP服务ID',
  name varchar(128) NOT NULL COMMENT '工具名称',
  description text COMMENT '工具描述',
  input_schema json DEFAULT NULL COMMENT '工具参数Schema (JSON Schema)',
  enabled tinyint(1) DEFAULT '1' COMMENT '是否启用',
  usage_count int DEFAULT '0' COMMENT '使用次数',
  created_at datetime DEFAULT CURRENT_TIMESTAMP,
  updated_at datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_mcp_tool (mcp_service_id, name),
  KEY idx_enabled (enabled),
  CONSTRAINT mcp_tools_ibfk_1 FOREIGN KEY (mcp_service_id) REFERENCES mcp_services (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='MCP工具表';

-- ============================================================
-- 8. Agent-MCP绑定表
-- ============================================================
CREATE TABLE agent_mcp_bindings (
  id varchar(36) NOT NULL DEFAULT (uuid()),
  agent_id varchar(36) NOT NULL COMMENT 'AgentID',
  mcp_service_id varchar(36) NOT NULL COMMENT 'MCP服务ID',
  config json DEFAULT NULL COMMENT '绑定配置',
  enabled tinyint(1) DEFAULT '1' COMMENT '是否启用',
  created_at datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_agent_mcp (agent_id, mcp_service_id),
  KEY mcp_service_id (mcp_service_id),
  CONSTRAINT agent_mcp_bindings_ibfk_1 FOREIGN KEY (agent_id) REFERENCES agents (id) ON DELETE CASCADE,
  CONSTRAINT agent_mcp_bindings_ibfk_2 FOREIGN KEY (mcp_service_id) REFERENCES mcp_services (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='Agent-MCP服务绑定表';

-- ============================================================
-- 9. Skill技能表
-- ============================================================
CREATE TABLE skills (
  id varchar(36) NOT NULL DEFAULT (uuid()),
  name varchar(128) NOT NULL COMMENT 'Skill名称',
  description text COMMENT 'Skill描述',
  category varchar(64) DEFAULT 'general' COMMENT '分类: programming/office/data-analysis/...',
  version varchar(32) DEFAULT '1.0.0' COMMENT '版本号',
  source enum('local','online','auto_generated') DEFAULT 'local' COMMENT '来源',
  source_url varchar(512) DEFAULT NULL COMMENT '来源URL (Git/HTTP)',
  storage_path varchar(512) DEFAULT NULL COMMENT '存储路径',
  enabled tinyint(1) DEFAULT '1' COMMENT '是否启用',
  usage_count int DEFAULT '0' COMMENT '使用次数',
  success_count int DEFAULT '0' COMMENT '成功次数（用于计算success_rate）',
  success_rate float DEFAULT '0' COMMENT '成功率',
  author varchar(128) DEFAULT NULL COMMENT '作者',
  tags json DEFAULT NULL COMMENT '标签数组',
  created_at datetime DEFAULT CURRENT_TIMESTAMP,
  updated_at datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_category (category),
  KEY idx_enabled (enabled),
  KEY idx_source (source)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='Skill技能表';

-- ============================================================
-- 10. Skill层级内容表 - 渐进式披露
-- ============================================================
CREATE TABLE skill_levels (
  id varchar(36) NOT NULL DEFAULT (uuid()),
  skill_id varchar(36) NOT NULL COMMENT 'SkillID',
  level tinyint NOT NULL COMMENT '层级: 0=概要, 1=完整, 2=深度',
  name varchar(128) DEFAULT NULL COMMENT '层级名称',
  content text NOT NULL COMMENT '层级内容',
  token_count int DEFAULT '0' COMMENT 'Token数量',
  created_at datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_skill_level (skill_id, level),
  CONSTRAINT skill_levels_ibfk_1 FOREIGN KEY (skill_id) REFERENCES skills (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='Skill层级内容表 - 渐进式披露';

-- ============================================================
-- 11. Agent-Skill绑定表
-- ============================================================
CREATE TABLE agent_skill_bindings (
  id varchar(36) NOT NULL DEFAULT (uuid()),
  agent_id varchar(36) NOT NULL COMMENT 'AgentID',
  skill_id varchar(36) NOT NULL COMMENT 'SkillID',
  priority int DEFAULT '0' COMMENT '优先级',
  enabled tinyint(1) DEFAULT '1' COMMENT '是否启用',
  created_at datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_agent_skill (agent_id, skill_id),
  KEY skill_id (skill_id),
  CONSTRAINT agent_skill_bindings_ibfk_1 FOREIGN KEY (agent_id) REFERENCES agents (id) ON DELETE CASCADE,
  CONSTRAINT agent_skill_bindings_ibfk_2 FOREIGN KEY (skill_id) REFERENCES skills (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='Agent-Skill绑定表';

-- ============================================================
-- 12. 知识库表 - RAG域
-- ============================================================
CREATE TABLE knowledge_bases (
  id varchar(36) NOT NULL DEFAULT (uuid()),
  name varchar(128) NOT NULL COMMENT '知识库名称',
  description text COMMENT '知识库描述',
  default_index enum('vector','keyword','tree','knowledge_graph','hybrid') DEFAULT 'hybrid' COMMENT '默认索引类型',
  embedding_model varchar(128) DEFAULT 'text-embedding-ada-002' COMMENT 'Embedding模型',
  chunk_size int DEFAULT '512' COMMENT '切片大小 (tokens)',
  chunk_overlap int DEFAULT '64' COMMENT '切片重叠 (tokens)',
  total_documents int DEFAULT '0' COMMENT '文档总数',
  total_chunks int DEFAULT '0' COMMENT '切片总数',
  created_at datetime DEFAULT CURRENT_TIMESTAMP,
  updated_at datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_default_index (default_index)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='知识库表 - RAG域';

-- ============================================================
-- 13. 文档表 - RAG域
-- ============================================================
CREATE TABLE documents (
  id varchar(36) NOT NULL DEFAULT (uuid()),
  kb_id varchar(36) NOT NULL COMMENT '知识库ID',
  filename varchar(256) NOT NULL COMMENT '文件名',
  file_path varchar(512) NOT NULL COMMENT 'MinIO存储路径',
  file_type varchar(32) DEFAULT NULL COMMENT '文件类型: pdf/docx/txt/md',
  file_size bigint DEFAULT '0' COMMENT '文件大小 (bytes)',
  total_pages int DEFAULT '0' COMMENT '总页数',
  total_chunks int DEFAULT '0' COMMENT '切片数',
  status enum('uploading','parsing','indexing','ready','error') DEFAULT 'uploading' COMMENT '处理状态',
  error_message text COMMENT '错误信息',
  metadata json DEFAULT NULL COMMENT '元数据',
  created_at datetime DEFAULT CURRENT_TIMESTAMP,
  updated_at datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_kb (kb_id),
  KEY idx_status (status),
  CONSTRAINT documents_ibfk_1 FOREIGN KEY (kb_id) REFERENCES knowledge_bases (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='文档表 - RAG域';

-- ============================================================
-- 14. 文档切片表 - RAG域
-- ============================================================
CREATE TABLE document_chunks (
  id varchar(36) NOT NULL DEFAULT (uuid()),
  document_id varchar(36) NOT NULL COMMENT '文档ID',
  kb_id varchar(36) NOT NULL COMMENT '知识库ID',
  chunk_index int NOT NULL COMMENT '切片序号',
  content text NOT NULL COMMENT '切片内容',
  page_number int DEFAULT NULL COMMENT '页码',
  token_count int DEFAULT '0' COMMENT 'Token数',
  metadata json DEFAULT NULL COMMENT '元数据',
  vector_id varchar(64) DEFAULT NULL COMMENT 'Milvus中的向量ID',
  created_at datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_document (document_id),
  KEY idx_kb (kb_id),
  CONSTRAINT document_chunks_ibfk_1 FOREIGN KEY (document_id) REFERENCES documents (id) ON DELETE CASCADE,
  CONSTRAINT document_chunks_ibfk_2 FOREIGN KEY (kb_id) REFERENCES knowledge_bases (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='文档切片表 - RAG域';

-- ============================================================
-- 15. 数据源表 - ChatBI域
-- ============================================================
CREATE TABLE data_sources (
  id varchar(36) NOT NULL DEFAULT (uuid()),
  name varchar(128) NOT NULL COMMENT '数据源名称',
  description text COMMENT '描述',
  db_type enum('mysql','postgresql','sqlite','clickhouse') NOT NULL COMMENT '数据库类型',
  host varchar(256) DEFAULT NULL COMMENT '主机地址',
  port int DEFAULT NULL COMMENT '端口',
  database_name varchar(128) DEFAULT NULL COMMENT '数据库名',
  username varchar(128) DEFAULT NULL COMMENT '用户名',
  encrypted_password text COMMENT '加密后的密码',
  sqlite_path varchar(512) DEFAULT NULL COMMENT 'SQLite文件路径',
  status enum('active','error','disabled') DEFAULT 'active' COMMENT '状态',
  schema_cache json DEFAULT NULL COMMENT 'Schema缓存',
  created_at datetime DEFAULT CURRENT_TIMESTAMP,
  updated_at datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_status (status),
  KEY idx_db_type (db_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='数据源表 - ChatBI域';

-- ============================================================
-- 16. 查询记录表 - ChatBI域
-- ============================================================
CREATE TABLE query_records (
  id varchar(36) NOT NULL DEFAULT (uuid()),
  datasource_id varchar(36) NOT NULL COMMENT '数据源ID',
  user_id varchar(36) DEFAULT NULL COMMENT '用户ID',
  natural_language text NOT NULL COMMENT '自然语言问题',
  sql_query text COMMENT '生成的SQL',
  result_json json DEFAULT NULL COMMENT '查询结果',
  result_count int DEFAULT '0' COMMENT '结果行数',
  execution_time float DEFAULT '0' COMMENT '执行时间 (秒)',
  status enum('success','failed','security_blocked') DEFAULT 'success' COMMENT '状态',
  error_message text COMMENT '错误信息',
  is_favorite tinyint(1) DEFAULT '0' COMMENT '是否收藏',
  created_at datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_datasource (datasource_id),
  KEY idx_status (status),
  KEY idx_favorite (is_favorite),
  CONSTRAINT query_records_ibfk_1 FOREIGN KEY (datasource_id) REFERENCES data_sources (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='查询记录表 - ChatBI域';

-- ============================================================
-- 17. 协作任务表 - 协同域
-- ============================================================
CREATE TABLE collaboration_tasks (
  id varchar(36) NOT NULL DEFAULT (uuid()),
  mode enum('supervisor','route','plan_execute') NOT NULL COMMENT '协作模式',
  task_description text NOT NULL COMMENT '任务描述',
  supervisor_agent_id varchar(36) DEFAULT NULL COMMENT '主管AgentID (supervisor模式)',
  participant_ids json DEFAULT NULL COMMENT '参与AgentID列表',
  status enum('pending','running','completed','failed','cancelled') DEFAULT 'pending' COMMENT '任务状态',
  result json DEFAULT NULL COMMENT '最终结果',
  error_message text COMMENT '错误信息',
  started_at datetime DEFAULT NULL COMMENT '开始时间',
  completed_at datetime DEFAULT NULL COMMENT '完成时间',
  created_at datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_status (status),
  KEY idx_mode (mode),
  KEY supervisor_agent_id (supervisor_agent_id),
  CONSTRAINT collaboration_tasks_ibfk_1 FOREIGN KEY (supervisor_agent_id) REFERENCES agents (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='协作任务表 - 协同域';

-- ============================================================
-- 18. 协作步骤表 - 协同域
-- ============================================================
CREATE TABLE collaboration_steps (
  id varchar(36) NOT NULL DEFAULT (uuid()),
  task_id varchar(36) NOT NULL COMMENT '协作任务ID',
  agent_id varchar(36) DEFAULT NULL COMMENT '执行AgentID',
  step_index int NOT NULL COMMENT '步骤序号',
  step_type varchar(32) DEFAULT NULL COMMENT '步骤类型',
  description text COMMENT '步骤描述',
  input json DEFAULT NULL COMMENT '输入',
  output json DEFAULT NULL COMMENT '输出',
  status enum('pending','running','completed','failed','skipped') DEFAULT 'pending' COMMENT '状态',
  error_message text COMMENT '错误信息',
  started_at datetime DEFAULT NULL COMMENT '开始时间',
  completed_at datetime DEFAULT NULL COMMENT '完成时间',
  created_at datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_task (task_id, step_index),
  KEY agent_id (agent_id),
  CONSTRAINT collaboration_steps_ibfk_1 FOREIGN KEY (task_id) REFERENCES collaboration_tasks (id) ON DELETE CASCADE,
  CONSTRAINT collaboration_steps_ibfk_2 FOREIGN KEY (agent_id) REFERENCES agents (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='协作步骤表 - 协同域';

-- ============================================================
-- 19. 进化记录表 - 进化域
-- ============================================================
CREATE TABLE evolution_records (
  id varchar(36) NOT NULL DEFAULT (uuid()),
  agent_id varchar(36) NOT NULL COMMENT 'AgentID',
  evolution_type enum('task_evaluation','skill_proposal','memory_consolidation','safety_scan') NOT NULL COMMENT '进化类型',
  content json DEFAULT NULL COMMENT '进化内容',
  success_score float DEFAULT NULL COMMENT '成功度评分 (0-100)',
  metadata json DEFAULT NULL COMMENT '元数据',
  created_at datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_agent (agent_id),
  KEY idx_type (evolution_type),
  CONSTRAINT evolution_records_ibfk_1 FOREIGN KEY (agent_id) REFERENCES agents (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='进化记录表 - 进化域';

-- ============================================================
-- 20. Skill提案表 (新增：当前数据库实际存在)
-- ============================================================
CREATE TABLE skill_proposals (
  id varchar(36) NOT NULL DEFAULT (uuid()),
  agent_id varchar(36) DEFAULT NULL COMMENT '来源AgentID',
  title varchar(256) NOT NULL COMMENT '提案标题',
  problem text COMMENT '要解决的问题描述',
  proposed_skill_name varchar(128) DEFAULT NULL COMMENT '建议的Skill名称',
  proposed_category varchar(64) DEFAULT NULL COMMENT '建议的分类',
  proposed_content mediumtext COMMENT '建议的Skill内容草稿',
  source enum('agent_suggestion','user_feedback','evaluation_summary') DEFAULT NULL COMMENT '提案来源',
  related_task_id varchar(36) DEFAULT NULL COMMENT '关联的协作任务ID',
  priority tinyint DEFAULT '1' COMMENT '优先级: 1=低, 2=中, 3=高',
  status enum('pending','reviewing','approved','rejected','implemented') DEFAULT 'pending' COMMENT '处理状态',
  reviewer_notes text COMMENT '审核备注',
  implemented_skill_id varchar(36) DEFAULT NULL COMMENT '落地后的SkillID',
  created_by varchar(36) DEFAULT NULL COMMENT '创建用户ID',
  created_at datetime DEFAULT CURRENT_TIMESTAMP,
  updated_at datetime DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_agent (agent_id),
  KEY idx_status (status),
  KEY idx_priority (priority)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='Skill提案表';

-- ============================================================
-- 21. 工具调用日志表
-- ============================================================
CREATE TABLE tool_call_logs (
  id varchar(36) NOT NULL DEFAULT (uuid()),
  conversation_id varchar(36) DEFAULT NULL COMMENT '会话ID',
  agent_id varchar(36) DEFAULT NULL COMMENT 'AgentID',
  user_id varchar(36) DEFAULT NULL COMMENT '用户ID',
  mcp_service_id varchar(36) DEFAULT NULL COMMENT 'MCP服务ID',
  mcp_service_name varchar(128) DEFAULT NULL COMMENT 'MCP服务名称（冗余）',
  tool_name varchar(128) NOT NULL COMMENT '工具名称',
  input_args json DEFAULT NULL COMMENT '工具入参',
  result_status enum('success','failed','timeout','cancelled') DEFAULT NULL COMMENT '执行状态',
  output_preview text COMMENT '结果预览（截断）',
  error_message text COMMENT '错误信息',
  duration_ms int DEFAULT NULL COMMENT '执行耗时(ms)',
  started_at datetime DEFAULT NULL COMMENT '开始时间',
  completed_at datetime DEFAULT NULL COMMENT '结束时间',
  created_at datetime DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_conv (conversation_id),
  KEY idx_agent (agent_id),
  KEY idx_tool (tool_name),
  KEY idx_created (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='工具调用审计日志表';
