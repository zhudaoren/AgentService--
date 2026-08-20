-- ============================================================
-- 迁移：skills.success_count
-- 新增成功次数字段，支撑成功率原子计算
-- 幂等：先 DROP 临时列（此处用 INFORMATION_SCHEMA 判断），再 ADD
-- ============================================================
-- 强制以 utf8mb4 通信，避免 Windows GBK 客户端导致 collation 冲突
SET NAMES utf8mb4;
use agent_service;
SET @dbname = DATABASE();
SET @tablename = 'skills';
SET @columnname = 'success_count';
SET @preparedStatement = (SELECT IF(
  (
    SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
    WHERE
      (table_schema = @dbname)
      AND (table_name = @tablename)
      AND (column_name = @columnname)
  ) > 0,
  'SELECT 1',
  CONCAT('ALTER TABLE ', @tablename, ' ADD COLUMN success_count INT NOT NULL DEFAULT 0 COMMENT ''成功次数'' AFTER usage_count')
));
PREPARE alterIfNotExists FROM @preparedStatement;
EXECUTE alterIfNotExists;
DEALLOCATE PREPARE alterIfNotExists;
