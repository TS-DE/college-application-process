-- =============================================================
-- RAG 升级：用户表 + 知识库文件表（v2 结构）
-- 执行：mysql -u root -p gaokao < sql/04_rag_tables.sql
-- =============================================================
USE gaokao;

-- 1. 用户表（含角色）
CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role ENUM('admin', 'student') DEFAULT 'student',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='系统用户';

-- 2. 知识库文件表（UUID 重命名 + 切片数 + 上传者外键）
-- 0.10.0 新增：ocr_used（是否走了 OCR 兜底）/ image_count（入库图片数）
DROP TABLE IF EXISTS knowledge_files;
CREATE TABLE knowledge_files (
    id INT AUTO_INCREMENT PRIMARY KEY,
    filename VARCHAR(255) NOT NULL,
    stored_filename VARCHAR(255) NOT NULL COMMENT 'UUID 重命名后的文件名',
    file_path VARCHAR(500) NOT NULL,
    file_type VARCHAR(20) COMMENT 'pdf / txt / docx',
    file_size INT,
    upload_time DATETIME DEFAULT CURRENT_TIMESTAMP,
    chunk_count INT DEFAULT 0 COMMENT '切分后的片段数',
    status VARCHAR(50) DEFAULT '已上传' COMMENT '已上传 / 已向量化 / 失败',
    uploaded_by INT,
    ocr_used INT DEFAULT 0 COMMENT '0.10.0：是否走了 OCR 兜底，1=扫描件识别',
    image_count INT DEFAULT 0 COMMENT '0.10.0：写入图像集合的图片数量',
    FOREIGN KEY (uploaded_by) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='知识库文档';

-- 0.10.0 增量迁移（已建过表的库执行这一段即可）
-- ALTER TABLE knowledge_files ADD COLUMN ocr_used INT DEFAULT 0 COMMENT '是否走了 OCR 兜底';
-- ALTER TABLE knowledge_files ADD COLUMN image_count INT DEFAULT 0 COMMENT '入库图片数量';
