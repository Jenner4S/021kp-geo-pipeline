# -*- coding: utf-8 -*-
"""
021kp.com GEO System - SQLite Database Backend
=============================================================================

Design:
    - Single database: SQLite (file-based, zero-config)
    - Unified interface: same method calls
    - Auto-create tables on first connection

Usage:
    from database_backend import get_backend
    
    db = get_backend()              # returns SQLiteBackend instance
    jobs = db.fetch_jobs(limit=50)        # unified API
    stats = db.get_statistics()
    db.close()

Author: GEO-Engine Team | Version: v2.1 (SQLite-only) | Date: 2026-04-21
"""

import os
import json
import time
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Union, TYPE_CHECKING
from dataclasses import dataclass, field
from abc import ABC, abstractmethod

try:
    from loguru import logger
except ImportError:
    import logging as logger

try:
    from config_manager import get_config
    CONFIG_AVAILABLE = True
except ImportError:
    CONFIG_AVAILABLE = False


@dataclass
class JobRecord:
    """岗位记录数据结构（统一跨DB格式）"""
    id: int = 0
    title: str = ""
    company: str = ""
    salary: str = ""
    min_salary: float = 0.0
    max_salary: float = 0.0
    location: str = ""
    category: str = ""
    experience: str = ""
    education: str = ""
    hire_count: int = 0
    benefits: str = ""
    description: str = ""
    address: str = ""
    update_time: str = ""
    source_url: str = ""
    is_urgent: bool = False
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "title": self.title, "company": self.company,
            "salary": self.salary, "min_salary": self.min_salary,
            "max_salary": self.max_salary, "location": self.location,
            "category": self.category, "experience": self.experience,
            "education": self.education, "hire_count": self.hire_count,
            "benefits": self.benefits, "description": self.description,
            "address": self.address, "update_time": self.update_time,
            "source_url": self.source_url, "is_urgent": self.is_urgent,
        }


@dataclass
class DatabaseStats:
    """数据库统计快照"""
    total_active: int = 0
    by_category: Dict[str, int] = field(default_factory=dict)
    urgent_count: int = 0
    urgent_ratio: float = 0.0
    salary_distribution: Dict[str, int] = field(default_factory=dict)
    backend_type: str = "unknown"
    database_name: str = ""
    last_updated: str = ""


class DatabaseBackendABC(ABC):
    """
    Abstract base class for database backends (SQLite).

    All database backends MUST inherit from this class and implement
    all abstract methods.
    
    Methods:
        connect: Establish connection
        close: Clean up resources
        fetch_jobs: Paginated job listing with optional filters
        get_job_by_id: Single job lookup by primary key
        insert_job: Upsert single job record
        insert_jobs_batch: Bulk upsert with transaction support
        delete_job: Soft-delete a job record
        get_statistics: Aggregated statistics snapshot
        test_connection: Health check with metadata
        record_execution: Log pipeline execution history
        get_execution_history: Retrieve recent execution logs
        count_jobs: Count jobs with optional search filter
    """
    
    @abstractmethod
    def connect(self) -> bool: ...
    
    @abstractmethod
    def close(self) -> None: ...
    
    @abstractmethod
    def fetch_jobs(self, limit=100, offset=0, category_filter=None,
                    urgent_only=False, search_query=None) -> List[JobRecord]: ...
    
    @abstractmethod
    def get_job_by_id(self, job_id: str) -> Optional[JobRecord]: ...
    
    @abstractmethod
    def insert_job(self, job_data: Dict[str, Any]) -> bool: ...
    
    @abstractmethod
    def insert_jobs_batch(self, jobs_data: List[Dict[str, Any]]) -> Tuple[int, int]: ...
    
    @abstractmethod
    def delete_job(self, job_id: str) -> bool: ...
    
    @abstractmethod
    def get_statistics(self) -> DatabaseStats: ...
    
    @abstractmethod
    def test_connection(self) -> Dict[str, Any]: ...
    
    @abstractmethod
    def record_execution(self, task_id: str, mode: str, options: Dict, result: Dict) -> None: ...
    
    @abstractmethod
    def get_execution_history(self, limit: int = 20) -> List[Dict]: ...
    
    @abstractmethod
    def count_jobs(self, search_query=None) -> int: ...


class SQLiteBackend(DatabaseBackendABC):
    """
    SQLite backend (default, zero-config)
    
    Features:
      - Single file storage, easy backup/migration
      - Dev/test/small-scale production ready
      - Thread-safe (per-thread connections)
    """
    
    _local = threading.local()
    
    def __init__(self, db_path: str = "./data/geo_pipeline.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connected = False
    
    @property
    def conn(self):
        import sqlite3
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            self._local.conn = sqlite3.connect(
                str(self.db_path),
                check_same_thread=False,
                detect_types=sqlite3.PARSE_DECLTYPES,
                timeout=10
            )
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA foreign_keys = ON")
        return self._local.conn
    
    def connect(self) -> bool:
        try:
            c = self.conn
            self._ensure_tables(c)
            self._connected = True
            size = self.db_path.stat().st_size / 1024.0 if self.db_path.exists() else 0
            logger.info(f"SQLite connected: {self.db_path} ({size:.1f}KB)")
            return True
        except Exception as e:
            logger.error(f"SQLite connect error: {e}")
            self._connected = False
            return False
    
    def _ensure_tables(self, conn) -> None:
        c = conn.cursor()
        
        c.execute("""
            CREATE TABLE IF NOT EXISTS `jobs` (
                `id`          TEXT PRIMARY KEY,
                `title`       TEXT NOT NULL DEFAULT '',
                `company`     TEXT NOT NULL DEFAULT '',
                `location`    TEXT NOT NULL DEFAULT 'Songjiang District',
                `min_salary`  REAL NOT NULL DEFAULT 0,
                `max_salary`  REAL NOT NULL DEFAULT 0,
                `category`    TEXT NOT NULL DEFAULT 'general',
                `tags`        TEXT DEFAULT '',
                `requirements`TEXT DEFAULT '',
                `benefits`    TEXT DEFAULT '',
                `is_urgent`   INTEGER NOT NULL DEFAULT 0,
                `status`      TEXT NOT NULL DEFAULT 'active',
                `source`      TEXT DEFAULT 'csv_upload',
                `geo_processed` INTEGER DEFAULT 0,
                `created_at`  TEXT DEFAULT (datetime('now', '+8 hours')),
                `updated_at`  TEXT DEFAULT (datetime('now', '+8 hours'))
            )
        """)
        
        c.execute("""
            CREATE TABLE IF NOT EXISTS `execution_history` (
                `id`         TEXT PRIMARY KEY,
                `mode`       TEXT NOT NULL DEFAULT 'pipeline',
                `status`     TEXT NOT NULL DEFAULT 'pending',
                `options`    TEXT DEFAULT '{}',
                `result`     TEXT DEFAULT '{}',
                `duration`   REAL DEFAULT 0,
                `created_at` TEXT DEFAULT (datetime('now', '+8 hours'))
            )
        """)
        
        c.execute("CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_jobs_category ON jobs(category)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at)")
        conn.commit()
    
    # ========== Query Methods ==========
    
    def fetch_jobs(self, limit: int = 100, offset: int = 0, category_filter: Optional[str] = None,
                    urgent_only: bool = False, search_query: Optional[str] = None) -> List[JobRecord]:
        if not self._connected:
            self.connect()
        c = self.conn.cursor()
        sql = "SELECT * FROM jobs WHERE status='active'"
        params = []
        if category_filter:
            sql += " AND category=?"
            params.append(category_filter)
        if urgent_only:
            sql += " AND is_urgent=1"
        if search_query:
            sql += " AND (title LIKE ? OR company LIKE ? OR location LIKE ?)"
            # 转义 SQL LIKE 通配符 (% _ \)
            safe_query = search_query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
            q = f"%{safe_query}%"
            params.extend([q, q, q])
        sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        c.execute(sql, params)
        return [self._row_to_job(r) for r in c.fetchall()]
    
    def get_job_by_id(self, job_id: str) -> Optional[JobRecord]:
        if not self._connected:
            self.connect()
        c = self.conn.cursor()
        c.execute("SELECT * FROM jobs WHERE id=? LIMIT 1", (job_id,))
        row = c.fetchone()
        return self._row_to_job(row) if row else None
    
    def insert_job(self, job_data: Dict[str, Any]) -> bool:
        if not self._connected:
            self.connect()
        try:
            c = self.conn.cursor()
            now = datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')
            jid = job_data.get('id') or f"job_{int(time.time()*1000)}"
            c.execute("""
                INSERT INTO jobs (id,title,company,location,min_salary,max_salary,
                    category,tags,requirements,benefits,is_urgent,status,source,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,'active',?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title,company=excluded.company,
                    location=excluded.location,min_salary=excluded.min_salary,
                    max_salary=excluded.max_salary,updated_at=excluded.updated_at
            """, (
                jid, job_data.get('title',''), job_data.get('company',''),
                job_data.get('location','Songjiang'),
                float(job_data.get('min_salary',0)), float(job_data.get('max_salary',0)),
                job_data.get('category','general'),
                json.dumps(job_data.get('tags',[]), ensure_ascii=False),
                job_data.get('requirements',''), job_data.get('benefits',''),
                1 if job_data.get('is_urgent') else 0,
                'csv_upload', now, now
            ))
            self.conn.commit()
            return True
        except Exception as e:
            logger.warning(f"SQLite insert failed: {e}")
            return False
    
    def insert_jobs_batch(self, jobs_data: List[Dict[str, Any]]) -> Tuple[int, int]:
        """批量插入岗位数据 (SQLite版: 使用executemany分批事务提交)"""
        if not self._connected:
            self.connect()
        if not jobs_data:
            return 0, 0
        
        BATCH_SIZE = 500
        total_inserted = 0
        total_skipped = 0
        
        for batch_start in range(0, len(jobs_data), BATCH_SIZE):
            batch = jobs_data[batch_start:batch_start + BATCH_SIZE]
            
            try:
                c = self.conn.cursor()
                
                insert_sql = """
                    INSERT INTO jobs 
                    (id,title,company,location,min_salary,max_salary,
                     category,tags,requirements,benefits,is_urgent,status,source,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,'active','csv_upload',?,?)
                    ON CONFLICT(id) DO UPDATE SET
                        title=excluded.title,company=excluded.company,
                        location=excluded.location,min_salary=excluded.min_salary,
                        max_salary=excluded.max_salary,updated_at=excluded.updated_at
                """
                
                now = datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')
                params_list = []
                for job in batch:
                    jid = job.get('id') or f"job_{int(time.time()*1000)}_{total_inserted}"
                    params_list.append((
                        jid, job.get('title',''), job.get('company',''),
                        job.get('location','Songjiang'),
                        float(job.get('min_salary',0)), float(job.get('max_salary',0)),
                        job.get('category','general'),
                        json.dumps(job.get('tags',[]), ensure_ascii=False),
                        job.get('requirements',''), job.get('benefits',''),
                        1 if job.get('is_urgent') else 0,
                        now, now
                    ))
                
                c.executemany(insert_sql, params_list)
                self.conn.commit()
                total_inserted += len(params_list)
                
            except Exception as e:
                logger.warning(f"SQLite 批量插入失败 (batch {batch_start//BATCH_SIZE+1}): {e}")
                for j in batch:
                    if self.insert_job(j):
                        total_inserted += 1
                    else:
                        total_skipped += 1
        
        return total_inserted, total_skipped
    
    def delete_job(self, job_id: str) -> bool:
        if not self._connected:
            self.connect()
        try:
            now = datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')
            c = self.conn.cursor()
            c.execute("UPDATE jobs SET status='deleted', updated_at=? WHERE id=?", (now, job_id))
            self.conn.commit()
            return c.rowcount > 0
        except Exception as e:
            logger.warning(f"SQLite delete failed: {e}")
            return False
    
    def get_statistics(self) -> DatabaseStats:
        if not self._connected:
            self.connect()
        stats = DatabaseStats(backend_type="sqlite", database_name=str(self.db_path))
        c = self.conn.cursor()
        
        c.execute("SELECT COUNT(*) FROM jobs WHERE status='active'")
        stats.total_active = c.fetchone()[0]
        
        c.execute("""SELECT category, COUNT(*) as c FROM jobs WHERE status='active'
                     GROUP BY category ORDER BY c DESC""")
        stats.by_category = {r[0]: r[1] for r in c.fetchall()}
        
        c.execute("SELECT SUM(is_urgent), COUNT(*) FROM jobs WHERE status='active'")
        r = c.fetchone()
        stats.urgent_count = r[0] or 0
        t = r[1] or 0
        stats.urgent_ratio = round(stats.urgent_count/t*100, 2) if t else 0
        
        c.execute("""SELECT CASE WHEN max_salary>=15000 THEN '15K+'
                 WHEN max_salary>=10000 THEN '10K-15K'
                 WHEN max_salary>=7000 THEN '7K-10K'
                 WHEN max_salary>=5000 THEN '5K-7K' ELSE '<5K' END as label,
                 COUNT(*) FROM jobs WHERE status='active' GROUP BY label
                 ORDER BY MIN(max_salary)""")
        stats.salary_distribution = {r[0]: r[1] for r in c.fetchall()}
        stats.last_updated = datetime.now().isoformat()
        return stats
    
    def record_execution(self, task_id: str, mode: str, options: Dict, result: Dict) -> None:
        if not self._connected:
            self.connect()
        c = self.conn.cursor()
        now = datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')
        duration = result.get('duration', 0)
        c.execute("""
            INSERT INTO execution_history (id,mode,status,options,result,duration,created_at)
            VALUES (?,?,?,?,?,?,?)
        """, (
            task_id, mode, result.get('status','unknown').lower(),
            json.dumps(options, ensure_ascii=False),
            json.dumps(result, ensure_ascii=False, default=str)[:8000],
            duration, now
        ))
        self.conn.commit()
    
    def get_execution_history(self, limit: int = 20) -> List[Dict]:
        if not self._connected:
            self.connect()
        c = self.conn.cursor()
        c.execute("""
            SELECT id, mode, status, options, result, duration, created_at 
            FROM execution_history ORDER BY created_at DESC LIMIT ?
        """, (limit,))
        history = []
        for r in c.fetchall():
            history.append({
                'id': r['id'], 'mode': r['mode'], 'status': r['status'],
                'options': json.loads(r['options']) if r['options'] else {},
                'result': json.loads(r['result']) if r['result'] else {},
                'duration': r['duration'], 'created_at': r['created_at']
            })
        return history
    
    def count_jobs(self, search_query=None) -> int:
        """Count active jobs with optional LIKE filter"""
        if not self._connected:
            self.connect()
        c = self.conn.cursor()
        if search_query:
            safe_q = search_query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
            q = f"%{safe_q}%"
            c.execute("SELECT COUNT(*) FROM jobs WHERE status='active' AND (title LIKE ? OR company LIKE ? OR location LIKE ?)", [q, q, q])
        else:
            c.execute("SELECT COUNT(*) FROM jobs WHERE status='active'")
        return c.fetchone()[0]
    
    def test_connection(self) -> Dict[str, Any]:
        try:
            c = self.conn.cursor()
            c.execute("SELECT sqlite_version()")
            ver = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM jobs")
            total = c.fetchone()[0]
            c.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [t[0] for t in c.fetchall()]
            size_mb = round(self.db_path.stat().st_size / 1048576, 2) if self.db_path.exists() else 0
            return {'connected': True, 'backend_type': 'sqlite',
                    'server_version': f'SQLite {ver}', 'database_exists': True,
                    'database': str(self.db_path), 'tables_exist': tables,
                    'total_records': total, 'file_size_mb': size_mb}
        except Exception as e:
            return {'connected': False, 'error': str(e)}
    
    def close(self) -> None:
        if hasattr(self._local, 'conn') and self._local.conn:
            self._local.conn.close()
            self._local.conn = None
        self._connected = False
    
    @staticmethod
    def _row_to_job(row) -> JobRecord:
        # 兼容 dict 和 sqlite3.Row 两种行类型
        _safe = lambda k, d: row.get(k, d) if hasattr(row, 'get') else (row[k] if k in row.keys() else d)
        return JobRecord(
            id=row['id'], title=row['title'], company=row['company'],
            location=_safe('location', ''),
            min_salary=float(row['min_salary'] or 0),
            max_salary=float(row['max_salary'] or 0),
            category=_safe('category', '') or '',
            benefits=_safe('benefits', '') or '',
            is_urgent=bool(_safe('is_urgent', 0)),
            created_at=str(_safe('created_at', '')),
            updated_at=str(_safe('updated_at', '')),
        )


def get_backend(force_type=None) -> SQLiteBackend:
    """Get SQLite backend instance (always returns SQLiteBackend)."""
    return _create_default_sqlite()


def _create_default_sqlite():
    if CONFIG_AVAILABLE:
        p = get_config().get('database.path', './data/geo_pipeline.db')
    else:
        p = os.getenv('DB_PATH', './data/geo_pipeline.db')
    return SQLiteBackend(p)


if __name__ == '__main__':
    print("=" * 60)
    print("GEO SQLite Backend Diagnostic")
    print("=" * 60)
    db = get_backend()
    t = db.test_connection()
    print(f"\n[Backend Type]: {t.get('backend_type')}")
    print(f"[Connected]: {t.get('connected')}")
    if t.get('server_version'): print(f"[Version]: {t['server_version']}")
    if t.get('database'): print(f"[Database]: {t['database']}")
    if t.get('total_records') is not None: print(f"[Records]: {t['total_records']}")
    
    stats = db.get_statistics()
    print(f"\n[Stats]: active={stats.total_active}, urgent={stats.urgent_count}({stats.urgent_ratio}%)")
    
    jobs = db.fetch_jobs(limit=5)
    print(f"\n[Recent Jobs] ({len(jobs)}):")
    for j in jobs[:3]:
        print(f"  [{j.id}] {j.title} @ {j.company} | {j.min_salary}-{j.max_salary}")
    db.close()
    print("\n" + "=" * 60)
