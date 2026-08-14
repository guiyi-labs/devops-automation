-- ============================================================
-- E1 安全与配置基线：已有数据库升级脚本
-- 适用：从 E0 基线（旧版）升级的 MySQL 数据库
-- 全新部署无需执行（Base.metadata.create_all 会自动建表）
--
-- 执行方式：
--   mysql -u root -p < scripts/e1_migrate.sql
-- 说明：新增 host_key_fingerprint 列，用于存储 SSH 主机密钥指纹。
-- 若列已存在会报 Duplicate column name 错误，可安全忽略。
-- ============================================================

ALTER TABLE server_asset ADD COLUMN host_key_fingerprint VARCHAR(255) NULL;