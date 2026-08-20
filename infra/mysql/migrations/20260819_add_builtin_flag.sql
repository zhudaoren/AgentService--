-- ============================================================
-- 迁移：llm_configs.is_builtin + mcp_services.is_builtin
-- 并对 DeepSeek-V3 默认 / 联网搜索MCP 自动打标为内置官方
-- ============================================================

-- 强制以 utf8mb4 通信，避免 Windows GBK 客户端导致字符串比较时
-- 与表列 utf8mb4_0900_ai_ci 的 collation 冲突（ERROR 1267）
SET NAMES utf8mb4;

-- llm_configs.is_builtin
use agent_service;
SET @dbname = DATABASE();
SET @tablename = 'llm_configs';
SET @columnname = 'is_builtin';
SET @stmt_lm = (SELECT IF(
  (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
    WHERE table_schema=@dbname AND table_name=@tablename AND column_name=@columnname) > 0,
  'SELECT 1',
  CONCAT('ALTER TABLE ', @tablename, ' ADD COLUMN is_builtin TINYINT(1) NOT NULL DEFAULT 0 COMMENT ''是否平台内置官方LLM配置'' AFTER is_default')
));
PREPARE addLm FROM @stmt_lm; EXECUTE addLm; DEALLOCATE PREPARE addLm;

-- mcp_services.is_builtin
SET @tablename = 'mcp_services';
SET @stmt_ms = (SELECT IF(
  (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
    WHERE table_schema=@dbname AND table_name=@tablename AND column_name=@columnname) > 0,
  'SELECT 1',
  CONCAT('ALTER TABLE ', @tablename, ' ADD COLUMN is_builtin TINYINT(1) NOT NULL DEFAULT 0 COMMENT ''是否平台内置官方MCP服务'' AFTER last_connected_at')
));
PREPARE addMs FROM @stmt_ms; EXECUTE addMs; DEALLOCATE PREPARE addMs;

-- 对 DeepSeek-V3 默认 + 联网搜索MCP 自动打标（幂等）
UPDATE llm_configs SET is_builtin = 1 WHERE name = 'DeepSeek-V3 默认' AND is_builtin = 0;
UPDATE mcp_services SET is_builtin = 1 WHERE name = '联网搜索MCP' AND is_builtin = 0;
