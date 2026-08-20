-- ============================================================
-- 迁移：messages.attachments 多模态附件 JSON 列
-- ============================================================
-- 强制以 utf8mb4 通信，避免 Windows GBK 客户端导致 collation 冲突
SET NAMES utf8mb4;
use agent_service;
SET @dbname = DATABASE();
SET @tablename = 'messages';
SET @columnname = 'attachments';
SET @preparedStatement = (SELECT IF(
  (
    SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
    WHERE
      (table_schema = @dbname)
      AND (table_name = @tablename)
      AND (column_name = @columnname)
  ) > 0,
  'SELECT 1',
  CONCAT('ALTER TABLE ', @tablename, ' ADD COLUMN attachments JSON DEFAULT NULL COMMENT ''多模态附件列表（图片/音频 base64 或 URL）'' AFTER tool_results')
));
PREPARE alterIfNotExists FROM @preparedStatement;
EXECUTE alterIfNotExists;
DEALLOCATE PREPARE alterIfNotExists;
