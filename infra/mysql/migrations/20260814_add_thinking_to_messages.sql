-- 数据库迁移脚本：messages 表添加 thinking 字段
-- 用于：刷新页面后思考过程不丢失

ALTER TABLE messages 
ADD COLUMN IF NOT EXISTS thinking TEXT COMMENT '思考过程内容（推理中间产物）' 
AFTER content;
