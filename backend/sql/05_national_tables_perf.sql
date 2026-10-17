-- =============================================================
-- 0.11.0 全国多省自适应：_all 总表性能兜底 + 索引确认
-- 执行：mysql -u root -p gaokao < sql/05_national_tables_perf.sql
-- =============================================================
USE gaokao;

-- -------------------------------------------------------------
-- 1. 列类型收紧（★ 必须执行）
--    pandas 全量字符串导入会把文本列建成 TEXT，TEXT 列不能高效参与
--    索引与排序，43 万行的 major_admission_2025_all 会直接查超时。
--    按需把高频过滤 / 排序 / 展示列改成 VARCHAR。
-- -------------------------------------------------------------
ALTER TABLE major_admission_2025_all
    MODIFY COLUMN province      VARCHAR(50),
    MODIFY COLUMN category      VARCHAR(50),
    MODIFY COLUMN batch         VARCHAR(50),
    MODIFY COLUMN university_name VARCHAR(100),
    MODIFY COLUMN major_name    VARCHAR(100),
    MODIFY COLUMN school_province VARCHAR(50),
    MODIFY COLUMN major_group   VARCHAR(50),
    MODIFY COLUMN subject_req   VARCHAR(100);

ALTER TABLE enrollment_plan_2025_all
    MODIFY COLUMN province      VARCHAR(50),
    MODIFY COLUMN category      VARCHAR(50),
    MODIFY COLUMN batch         VARCHAR(50),
    MODIFY COLUMN university_name VARCHAR(100),
    MODIFY COLUMN major_name    VARCHAR(100),
    MODIFY COLUMN school_province VARCHAR(50),
    MODIFY COLUMN subject_req   VARCHAR(100);

ALTER TABLE score_range_2025_all
    MODIFY COLUMN province      VARCHAR(50),
    MODIFY COLUMN category      VARCHAR(50),
    MODIFY COLUMN batch         VARCHAR(50);

-- -------------------------------------------------------------
-- 2. 复合索引（与 recommend_service.calculate_tiers 的 WHERE 对应）
--    查询形态：WHERE province=? AND year=? AND category=? AND min_rank BETWEEN ? AND ?
--    idx_prov_year_cat 已由导入脚本建好，这里补 min_rank 并做一致性确认。
-- -------------------------------------------------------------
-- major_admission_2025_all
CREATE INDEX IF NOT EXISTS idx_prov_year_cat ON major_admission_2025_all (province, year, category);
CREATE INDEX IF NOT EXISTS idx_min_rank      ON major_admission_2025_all (min_rank);
-- 一分一段表：按省份 + 科类 + 分数定位
CREATE INDEX IF NOT EXISTS idx_prov_cat_score ON score_range_2025_all (province, category, score);
-- 招生计划表：富化查询按 院校名 IN (...) 匹配
CREATE INDEX IF NOT EXISTS idx_univ_name      ON enrollment_plan_2025_all (university_name);
CREATE INDEX IF NOT EXISTS idx_prov_cat       ON enrollment_plan_2025_all (province, category);

-- -------------------------------------------------------------
-- 3. 统计信息刷新（改完列类型后执行，让优化器重新选索引）
-- -------------------------------------------------------------
ANALYZE TABLE major_admission_2025_all;
ANALYZE TABLE enrollment_plan_2025_all;
ANALYZE TABLE score_range_2025_all;

-- -------------------------------------------------------------
-- 4. 验证：EXPLAIN 应命中 idx_prov_year_cat + idx_min_rank，且 rows 远小于全表
-- -------------------------------------------------------------
-- EXPLAIN SELECT university_name, major_name, min_rank FROM major_admission_2025_all
--  WHERE province='河南' AND year=2025 AND category='物理类'
--    AND min_rank BETWEEN 40887 AND 45887 ORDER BY min_rank ASC LIMIT 50;
