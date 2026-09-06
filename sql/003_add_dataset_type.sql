-- ============================================================
-- 数据治理第一阶段：weibo_posts 数据分类
-- 执行日期：2026-09-05
-- 影响表：仅 weibo_posts（不修改其他表）
-- ============================================================

-- 1. 新增 dataset_type 字段 + 索引
ALTER TABLE `weibo_posts`
  ADD COLUMN `dataset_type` VARCHAR(32) NOT NULL DEFAULT 'ai_industry'
    COMMENT '数据集类型: ai_industry=AI行业 / brand_monitor=企业品牌 / general_hotspot=全网热点'
    AFTER `topic`,
  ADD INDEX `idx_dataset_type` (`dataset_type`);

-- 2. 历史数据迁移
-- 账号采集的明星/测试内容 → general_hotspot
UPDATE weibo_posts SET dataset_type = 'general_hotspot' WHERE source = 'account';
-- （topic为空的数据与source=account完全重叠，无需重复执行）

-- 3. 迁移后结果
-- ai_industry:     1000 条 (99.5%) — 全部AI关键词采集
-- general_hotspot:    5 条 (0.5%)  — 迪丽热巴账号采集
-- brand_monitor:      0 条 (预留)
