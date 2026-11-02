-- =============================================================
-- 后台知识库管理模块 · 建表 SQL
-- 在 gaokao 库中执行：mysql -u root -p gaokao < 03_knowledge.sql
-- =============================================================
USE gaokao;

-- 1. 知识库文件表
CREATE TABLE IF NOT EXISTS knowledge_files (
    id INT AUTO_INCREMENT PRIMARY KEY,
    filename VARCHAR(255) NOT NULL COMMENT '原始文件名',
    file_path VARCHAR(500) COMMENT '磁盘存储路径（UUID 重命名后）',
    file_size INT DEFAULT 0 COMMENT '文件大小（字节）',
    content_type VARCHAR(100) COMMENT '文件 MIME 类型',
    upload_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(50) DEFAULT '已上传' COMMENT '已上传/解析中/已解析/向量化中/已向量化',
    KEY idx_upload_time (upload_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='知识库文档（未来用于 RAG 检索）';

-- 2. 后台用户表（最简角色体系：admin / student）
CREATE TABLE IF NOT EXISTS admin_users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(64) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL COMMENT 'pbkdf2_sha256$salt$hash',
    role VARCHAR(20) NOT NULL DEFAULT 'student' COMMENT 'admin / student',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='后台登录用户';
