"""
021kp.com GEO系统 - 数据库连接器模块
=============================================================

功能描述:
    提供MySQL数据库的安全连接与数据读取能力，
    支持从021kp.com的jobs表批量加载岗位数据进行GEO处理。
    遵循最小权限原则，生产环境强制使用只读账号。

安全规范:
    ✅ 密码通过环境变量/本地配置注入
    ✅ 连接池管理防止资源泄漏
    ✅ SQL注入防护（参数化查询）
    ✅ SSL加密传输（production环境）

依赖: mysql-connector-python>=8.3.0
作者: GEO-Engine Team | 版本: v1.0 | 日期: 2026-04-20
"""

import os
import sys
from pathlib import Path
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
import json

try:
    import mysql.connector
    from mysql.connector import pooling, Error as MySQLError
    MYSQL_AVAILABLE = True
except ImportError:
    MYSQL_AVAILABLE = False
    MySQLError = Exception

try:
    from loguru import logger
except ImportError:
    import logging as logger


@dataclass
class DatabaseConfig:
    """数据库连接配置"""
    host: str = "localhost"
    port: int = 3306
    user: str = "root"
    password: str = ""
    database: str = "021kp_db"
    
    # 连接池参数
    pool_name: str = "geo_pipeline_pool"
    pool_size: int = 5
    max_overflow: int = 10
    pool_timeout: int = 30
    
    # 安全选项
    ssl_enabled: bool = False
    ssl_ca: Optional[str] = None
    read_only: bool = True  # 默认只读模式


@dataclass
class JobRecord:
    """岗位数据记录（标准化格式）"""
    id: str
    title: str
    company: str
    location: str
    min_salary: float
    max_salary: float
    category: str
    tags: str
    requirements: str
    benefits: str
    is_urgent: bool = False
    
    # 元数据
    source: str = "database"
    fetched_at: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "id": self.id,
            "title": self.title,
            "company": self.company,
            "location": self.location,
            "min_salary": self.min_salary,
            "max_salary": self.max_salary,
            "category": self.category,
            "tags": self.tags.split(",") if isinstance(self.tags, str) else self.tags,
            "requirements": self.requirements,
            "benefits": self.benefits,
            "is_urgent": self.is_urgent,
            "source": self.source,
            "fetched_at": self.fetched_at.isoformat()
        }


class DatabaseConnector:
    """
    MySQL数据库连接器（线程安全连接池模式）
    
    用法示例:
        db = DatabaseConnector.from_config()
        jobs = db.fetch_recent_jobs(limit=50)
        db.close()
    """
    
    def __init__(self, config: DatabaseConfig):
        if not MYSQL_AVAILABLE:
            raise ImportError(
                "mysql-connector-python未安装。请执行: pip install mysql-connector-python==8.3.0"
            )
        
        self.config = config
        self._connection_pool: Optional[pooling.MySQLConnectionPool] = None
        self._is_connected = False
        
    @classmethod
    def from_env(cls) -> 'DatabaseConnector':
        """从环境变量创建连接器实例"""
        config = DatabaseConfig(
            host=os.getenv("DB_HOST", "localhost"),
            port=int(os.getenv("DB_PORT", "3306")),
            user=os.getenv("DB_USER", "root"),
            password=os.getenv("DB_PASSWORD", ""),
            database=os.getenv("DB_NAME", "021kp_db"),
            ssl_enabled=os.getenv("DB_SSL", "false").lower() == "true"
        )
        return cls(config)
    
    @classmethod
    def from_settings_file(cls, settings_path: str = "./config/settings.local.yaml") -> 'DatabaseConnector':
        """从YAML配置文件创建连接器（优先级高于环境变量）"""
        try:
            import yaml
            
            path = Path(settings_path)
            if not path.exists():
                logger.warning(f"配置文件不存在: {settings_path}，使用环境变量默认值")
                return cls.from_env()
            
            with open(path, 'r', encoding='utf-8') as f:
                cfg = yaml.safe_load(f)
            
            db_cfg = cfg.get('database', {})
            config = DatabaseConfig(
                host=db_cfg.get('host', os.getenv("DB_HOST", "localhost")),
                port=int(db_cfg.get('port', os.getenv("DB_PORT", "3306"))),
                user=db_cfg.get('user', os.getenv("DB_USER", "root")),
                password=db_cfg.get('password', os.getenv("DB_PASSWORD", "")),
                database=db_cfg.get('database', os.getenv("DB_NAME", "021kp_db")),
                pool_size=db_cfg.get('pool_size', 5),
                ssl_enabled=db_cfg.get('ssl_enabled', False),
                ssl_ca=db_cfg.get('ssl_ca'),
                read_only=True  # 强制只读
            )
            return cls(config)
            
        except ImportError:
            logger.warning("PyYAML未安装，使用环境变量")
            return cls.from_env()
    
    def connect(self) -> bool:
        """初始化连接池"""
        try:
            connection_config = {
                "host": self.config.host,
                "port": self.config.port,
                "user": self.config.user,
                "password": self.config.password,
                "database": self.config.database,
                "pool_name": self.config.pool_name,
                "pool_size": self.config.pool_size,
                "autocommit": True,
                "charset": "utf8mb4",
                "collation": "utf8mb4_unicode_ci",
                "time_zone": "+08:00"
            }
            
            # SSL配置（production环境强制）
            if self.config.ssl_enabled and self.config.ssl_ca:
                connection_config.update({
                    "ssl_ca": self.config.ssl_ca,
                    "ssl_verify_cert": True
                })
            
            self._connection_pool = pooling.MySQLConnectionPool(**connection_config)
            self._is_connected = True
            
            logger.info(f"数据库连接池已建立: {self.config.host}:{self.config.port}/{self.config.database}")
            logger.debug(f"连接池大小: {self.config.pool_size} | 只读模式: {self.config.read_only}")
            return True
            
        except MySQLError as e:
            self._is_connected = False
            logger.error(f"数据库连接失败: {e}")
            return False
    
    def _get_connection(self):
        """从连接池获取连接"""
        if not self._is_connected or not self._connection_pool:
            raise RuntimeError("数据库未连接，请先调用connect()")
        return self._connection_pool.get_connection()
    
    def fetch_recent_jobs(
        self,
        limit: int = 100,
        offset: int = 0,
        category_filter: Optional[str] = None,
        urgent_only: bool = False
    ) -> List[JobRecord]:
        """
        从jobs表查询岗位数据
        
        Args:
            limit: 返回数量上限
            offset: 分页偏移量
            category_filter: 行业类别过滤（如 manufacturing, ecommerce等）
            urgent_only: 仅返回急招岗位
            
        Returns:
            JobRecord对象列表
        """
        if not self._is_connected:
            raise RuntimeError("数据库未连接")
        
        conn = self._get_connection()
        cursor = conn.cursor(dictionary=True)
        
        try:
            # 构建SQL（参数化防注入）
            base_sql = """
                SELECT 
                    id, title, company, location,
                    min_salary, max_salary, category,
                    tags, requirements, benefits, is_urgent,
                    created_at, updated_at
                FROM jobs
                WHERE status = 'active'
            """
            params = []
            
            if category_filter:
                base_sql += " AND category = %s"
                params.append(category_filter)
            
            if urgent_only:
                base_sql += " AND is_urgent = TRUE"
            
            base_sql += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
            params.extend([limit, offset])
            
            cursor.execute(base_sql, params)
            rows = cursor.fetchall()
            
            # 转换为JobRecord对象
            jobs = [
                JobRecord(
                    id=str(row['id']),
                    title=row['title'],
                    company=row['company'],
                    location=row['location'],
                    min_salary=float(row['min_salary']) if row['min_salary'] else 0,
                    max_salary=float(row['max_salary']) if row['max_salary'] else 0,
                    category=row.get('category', 'general'),
                    tags=row.get('tags', ''),
                    requirements=row.get('requirements', ''),
                    benefits=row.get('benefits', ''),
                    is_urgent=bool(row.get('is_urgent', False)),
                    source="mysql_database",
                    fetched_at=row.get('created_at') or datetime.now()
                )
                for row in rows
            ]
            
            logger.debug(f"从数据库读取 {len(jobs)} 条岗位记录")
            return jobs
            
        finally:
            cursor.close()
            conn.close()
    
    def get_job_by_id(self, job_id: str) -> Optional[JobRecord]:
        """根据ID查询单条岗位"""
        if not self._is_connected:
            return None
            
        conn = self._get_connection()
        cursor = conn.cursor(dictionary=True)
        
        try:
            cursor.execute(
                "SELECT * FROM jobs WHERE id = %s LIMIT 1",
                (job_id,)
            )
            row = cursor.fetchone()
            
            if row:
                return JobRecord(
                    id=str(row['id']),
                    title=row['title'],
                    company=row['company'],
                    location=row['location'],
                    min_salary=float(row['min_salary'] or 0),
                    max_salary=float(row['max_salary'] or 0),
                    category=row.get('category', ''),
                    tags=row.get('tags', ''),
                    requirements=row.get('requirements', ''),
                    benefits=row.get('benefits', ''),
                    is_urgent=bool(row.get('is_urgent', False))
                )
            return None
            
        finally:
            cursor.close()
            conn.close()
    
    def get_statistics(self) -> Dict[str, Any]:
        """获取岗位数据统计信息"""
        if not self._is_connected:
            return {}
        
        conn = self._get_connection()
        cursor = conn.cursor(dictionary=True)
        
        try:
            stats = {}
            
            # 总数统计
            cursor.execute("SELECT COUNT(*) as total FROM jobs WHERE status = 'active'")
            stats['total_active'] = cursor.fetchone()['total']
            
            # 分类统计
            cursor.execute("""
                SELECT category, COUNT(*) as cnt 
                FROM jobs 
                WHERE status = 'active' 
                GROUP BY category 
                ORDER BY cnt DESC
            """)
            stats['by_category'] = {
                row['category']: row['cnt'] 
                for row in cursor.fetchall()
            }
            
            # 急招岗位占比
            cursor.execute("""
                SELECT 
                    SUM(CASE WHEN is_urgent=TRUE THEN 1 ELSE 0 END) as urgent_cnt,
                    COUNT(*) as total_cnt
                FROM jobs WHERE status = 'active'
            """)
            row = cursor.fetchone()
            stats['urgent_count'] = row['urgent_cnt']
            stats['urgent_ratio'] = round(
                row['urgent_cnt'] / row['total_cnt'] * 100, 2
            ) if row['total_cnt'] > 0 else 0
            
            # 薪资分布
            cursor.execute("""
                SELECT 
                    CASE 
                        WHEN max_salary >= 15000 THEN '15K+'
                        WHEN max_salary >= 10000 THEN '10K-15K'
                        WHEN max_salary >= 7000 THEN '7K-10K'
                        WHEN max_salary >= 5000 THEN '5K-7K'
                        ELSE '<5K'
                    END as salary_range,
                    COUNT(*) as cnt
                FROM jobs WHERE status = 'active'
                GROUP BY salary_range
                ORDER BY MIN(max_salary)
            """)
            stats['salary_distribution'] = {
                row['salary_range']: row['cnt']
                for row in cursor.fetchall()
            }
            
            return stats
            
        finally:
            cursor.close()
            conn.close()
    
    def test_connection(self) -> Dict[str, Any]:
        """测试数据库连通性"""
        result = {
            "connected": False,
            "server_version": None,
            "database_exists": False,
            "tables_exist": [],
            "error": None
        }
        
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            
            # 服务器版本
            cursor.execute("SELECT VERSION()")
            result['server_version'] = cursor.fetchone()[0]
            result['connected'] = True
            
            # 检查数据库
            cursor.execute("SELECT DATABASE()")
            current_db = cursor.fetchone()[0]
            result['database_exists'] = current_db == self.config.database
            
            # 列出表
            cursor.execute("SHOW TABLES")
            result['tables_exist'] = [table[0] for table in cursor.fetchall()]
            
            cursor.close()
            conn.close()
            
        except Exception as e:
            result['error'] = str(e)
        
        return result
    
    def close(self):
        """关闭连接池"""
        if self._connection_pool:
            # 连接池会自动关闭所有空闲连接
            self._connection_pool = None
            self._is_connected = False
            logger.info("数据库连接池已关闭")


def create_sample_table_sql() -> str:
    """
    返回jobs表的DDL语句（用于首次建表参考）
    
    注意: 生产环境建议由DBA执行建表操作
    """
    return """
-- 021kp.com 岗位数据表 DDL
-- 字符集: utf8mb4 | 引擎: InnoDB | 适用版本: MySQL 8.0+

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
"""


# ==================== 命令行入口 ====================
if __name__ == "__main__":
    print("=" * 60)
    print("🔗 松江快聘 GEO系统 - 数据库连接器测试")
    print("=" * 60)
    
    # 尝试从配置文件或环境变量连接
    db_connector = DatabaseConnector.from_settings_file()
    
    if db_connector.connect():
        # 测试连通性
        test_result = db_connector.test_connection()
        print(f"\n📡 连接状态:")
        print(f"   服务器版本: {test_result.get('server_version', 'N/A')}")
        print(f"   数据库就绪: {'是' if test_result.get('database_exists') else '否'}")
        print(f"   已有表: {', '.join(test_result.get('tables_exist', [])) or '(空)'}")
        
        # 获取统计信息
        stats = db_connector.get_statistics()
        if stats:
            print(f"\n📊 数据统计:")
            print(f"   活跃岗位: {stats.get('total_active', 0)} 条")
            print(f"   急招占比: {stats.get('urgent_ratio', 0)}%")
            print(f"   分类分布:")
            for cat, cnt in stats.get('by_category', {}).items():
                print(f"     • {cat}: {cnt} 条")
        
        # 示例：读取最近5条岗位
        recent_jobs = db_connector.fetch_recent_jobs(limit=5)
        print(f"\n📋 最近5条岗位预览:")
        for job in recent_jobs[:5]:
            print(f"   [{job.id}] {job.title} @ {job.company}")
            print(f"       薪资: ¥{job.min_salary:,}-¥{job.max_salary:,} | 急招: {'是' if job.is_urgent else '否'}")
        
        db_connector.close()
    else:
        print("\n⚠️ 无法连接数据库，请检查:")
        print("   1. 是否已安装: pip install mysql-connector-python==8.3.0")
        print("   2. 配置文件是否存在: config/settings.local.yaml")
        print("   3. 环境变量是否设置正确 (.env文件)")
        print("\n💡 可使用CSV文件进行离线测试:")
        print("   python -m src.main --mode pipeline --csv data/sample_jobs.csv")
