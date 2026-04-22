-- 021kp GEO Pipeline - MySQL 初始化脚本
-- 用途: Docker Compose 首次启动时自动执行建表
-- 执行位置: /docker-entrypoint-initdb.d/init.sql

-- 切换到目标数据库
USE `021kp_db`;

-- ==================== jobs 主表 ====================
CREATE TABLE IF NOT EXISTS `jobs` (
    `id` VARCHAR(32) NOT NULL COMMENT '主键(UUID)',
    `title` VARCHAR(200) NOT NULL COMMENT '岗位名称',
    `company` VARCHAR(200) NOT NULL COMMENT '企业名称',
    `location` VARCHAR(300) NOT NULL COMMENT '工作地点(LBS地址)',
    `latitude` DECIMAL(10, 7) DEFAULT NULL COMMENT '纬度坐标',
    `longitude` DECIMAL(10, 7) DEFAULT NULL COMMENT '经度坐标',
    `min_salary` DECIMAL(10, 2) DEFAULT 0 COMMENT '最低月薪(元)',
    `max_salary` DECIMAL(10, 2) DEFAULT 0 COMMENT '最高月薪(元)',
    `salary_unit` ENUM('month','year','hour') DEFAULT 'month' COMMENT '薪资单位',
    `category` VARCHAR(50) DEFAULT 'general' COMMENT '行业分类',
    `tags` TEXT COMMENT '标签(JSON数组)',
    `requirements` TEXT COMMENT '岗位要求',
    `benefits` TEXT COMMENT '福利待遇',
    `is_urgent` TINYINT(1) DEFAULT 0 COMMENT '是否急招',
    `contact_phone` VARCHAR(20) DEFAULT NULL COMMENT '联系电话(加密存储)',
    `status` ENUM('active','paused','closed','deleted') DEFAULT 'active' COMMENT '状态',
    `source` VARCHAR(50) DEFAULT 'manual' COMMENT '数据来源(manual/crawl/api)',
    `geo_processed` TINYINT(1) DEFAULT 0 COMMENT '是否已GEO处理',
    `geo_processed_at` DATETIME DEFAULT NULL COMMENT 'GEO处理时间',
    `schema_jsonld` JSON DEFAULT NULL COMMENT '生成的Schema.org结构化数据',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    `updated_at` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',

    PRIMARY KEY (`id`),
    INDEX `idx_status_created` (`status`, `created_at`),
    INDEX `idx_category` (`category`),
    INDEX `idx_location` (`location`(191)),
    INDEX `idx_salary_range` (`min_salary`, `max_salary`),
    INDEX `idx_urgent` (`is_urgent`, `status`),
    INDEX `idx_geo_status` (`geo_processed`, `geo_processed_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='松江快聘网岗位主表';

-- ==================== 审计日志表 ====================
CREATE TABLE IF NOT EXISTS `audit_logs` (
    `id` BIGINT AUTO_INCREMENT PRIMARY KEY,
    `job_id` VARCHAR(32) NOT NULL COMMENT '关联岗位ID',
    `phase` VARCHAR(20) NOT NULL COMMENT '阶段标识(compliance/router/factory/monitor)',
    `action` VARCHAR(50) NOT NULL COMMENT '操作类型',
    `status` VARCHAR(20) NOT NULL COMMENT '结果状态',
    `details` JSON COMMENT '详细信息(JSON)',
    `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX `idx_job_phase` (`job_id`, `phase`),
    INDEX `idx_created` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
COMMENT='GEO处理审计日志表';

-- ==================== 只读用户授权 ====================
GRANT SELECT ON `021kp_db`.`jobs` TO 'geo_readonly'@'%';
GRANT INSERT ON `021kp_db`.`audit_logs` TO 'geo_readonly'@'%';
FLUSH PRIVILEGES;

-- ==================== 插入示例数据 (可选) ====================
INSERT INTO `jobs` (`id`, `title`, `company`, `location`, `min_salary`, `max_salary`, 
                     `category`, `tags`, `requirements`, `benefits`, `is_urgent`) VALUES
('DEMO-001', '松江G60 CNC数控操作员', '上海精工模具制造有限公司', 
 '上海市松江区九亭镇伴亭路288号G60科创园', 6500.00, 9000.00, 
 'manufacturing', '["CNC","数控机床","三菱系统"]', 
 '1.熟悉法兰克/三菱数控系统;2.能独立编程调试', 
 '五险一金+包住宿+餐补400元/月', 1),
('DEMO-002', '新桥电商运营专员', '上海松江电子商务产业园有限公司',
 '上海市松江区新桥镇新润路168号电商园', 7000.00, 12000.00,
 'ecommerce', '["电商运营","拼多多","数据分析"]',
 '1.本科及以上学历;2.1年以上电商经验;3.熟悉直通车推广工具',
 '底薪+提成+五险一金', 0);

SELECT '✅ 数据库初始化完成!' AS result;
SELECT COUNT(*) AS total_jobs FROM jobs;
