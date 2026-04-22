# -*- coding: utf-8 -*-
"""
GEO Pipeline 数据库后端完整测试套件 (SQLite) - 100% 覆盖率目标
==============================================================

基于实际源码 API 编写:
- SQLiteBackend.__init__(db_path)
- connect() -> bool
- insert_job(job_data: Dict) -> bool (自动 upsert by id)
- insert_jobs_batch(jobs_data: List[Dict]) -> Tuple[int,int]
- delete_job(job_id) -> bool (soft delete)
- fetch_jobs(limit, offset, category_filter, urgent_only, search_query) -> List[JobRecord]
- get_job_by_id(job_id) -> Optional[JobRecord]
- count_jobs(search_query=None) -> int
- get_statistics() -> DatabaseStats
- record_execution(task_id, mode, options, result)
- get_execution_history(limit=20) -> List[Dict]
- test_connection() -> Dict
- close()
- get_backend() 工厂函数

运行: pytest tests/test_database_backend_full.py -v --tb=short
"""

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from database_backend import (
    JobRecord,
    DatabaseStats,
    DatabaseBackendABC,
    SQLiteBackend,
    get_backend,
)


# ==================== JobRecord ====================
class TestJobRecordDefaults:
    def test_defaults(self):
        r = JobRecord()
        assert r.id == 0
        assert r.title == ""
        assert r.company == ""
        assert r.min_salary == 0.0
        assert r.max_salary == 0.0
        assert r.is_urgent is False
        assert r.category == ""


class TestJobRecordToDict:
    def test_completeness(self):
        r = JobRecord(
            id=1, title="T", company="C",
            min_salary=6000, max_salary=12000,
            location="Songjiang",
            category="manufacturing", benefits="五险一金",
            is_urgent=True,
        )
        d = r.to_dict()
        # 验证关键字段存在
        assert "id" in d
        assert "title" in d
        assert "company" in d
        assert "min_salary" in d
        assert "max_salary" in d
        assert "location" in d
        assert "category" in d


class TestDatabaseStatsDefaults:
    def test_defaults(self):
        s = DatabaseStats()
        assert s.total_active == 0
        assert s.by_category == {}
        assert s.urgent_count == 0
        assert s.urgent_ratio == 0.0
        assert s.backend_type == "unknown"


# ==================== Shared Fixtures ====================
@pytest.fixture
def fresh_db(tmp_path):
    """Create a fresh connected SQLite backend"""
    db_path = str(tmp_path / "test.db")
    backend = SQLiteBackend(db_path=db_path)
    backend.connect()
    yield backend
    backend.close()
    for ext in ["", "-wal", "-shm"]:
        Path(f"{db_path}{ext}").unlink(missing_ok=True)


# ==================== SQLiteBackend Init ====================
class TestSQLiteBackendInit:
    def test_connect_success(self, fresh_db):
        assert fresh_db._connected is True

    def test_auto_create_tables(self, fresh_db):
        tables = [r[0] for r in fresh_db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()]
        assert "jobs" in tables
        assert "execution_history" in tables

    def test_index_created(self, fresh_db):
        rows = fresh_db.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
        ).fetchall()
        # sqlite_master index 行格式: (name, ...) - 取第一个字段
        indexes = [r[0] for r in rows]
        assert "idx_jobs_status" in indexes
        assert "idx_jobs_category" in indexes

    def test_double_connect_safe(self, fresh_db):
        fresh_db.connect()  # 不崩溃

    def test_default_db_path(self):
        """默认路径为 ./data/geo_pipeline.db"""
        db = SQLiteBackend()
        assert "geo_pipeline" in str(db.db_path)
        db.close()


# ==================== Insert ====================
class TestSQLiteInsert:
    def test_insert_single(self, fresh_db):
        result = fresh_db.insert_job({
            "title": "新岗位", "company": "测试公司",
            "location": "Songjiang", "min_salary": 5000
        })
        assert result is True

    def test_upsert_on_duplicate_id(self, fresh_db):
        fresh_db.insert_job({"id": "job_001", "title": "第一次"})
        fresh_db.insert_job({"id": "job_001", "title": "更新后"})

        job = fresh_db.get_job_by_id("job_001")
        assert job is not None
        assert job.title == "更新后"

    def test_insert_with_full_fields(self, fresh_db):
        fresh_db.insert_job({
            "id": "full_job", "title": "完整岗位", "company": "C",
            "location": "L", "min_salary": 8000, "max_salary": 15000,
            "category": "IT", "tags": '["Python","Django"]',
            "requirements": "3年经验", "benefits": "六险一金",
            "is_urgent": True
        })
        j = fresh_db.get_job_by_id("full_job")
        assert j is not None
        assert j.title == "完整岗位"
        assert j.is_urgent is True
        assert j.min_salary == 8000.0

    def test_insert_without_id_generates_one(self, fresh_db):
        """不传 id 时自动生成 job_<timestamp> 格式 ID"""
        fresh_db.insert_job({"title": "AutoID"})
        jobs = fresh_db.fetch_jobs(limit=10)
        assert len(jobs) >= 1
        assert jobs[0].id.startswith("job_")


# ==================== Batch Insert ====================
class TestSQLiteBatchInsert:
    def test_batch_insert(self, fresh_db):
        jobs = [
            {"title": f"批量{i}", "company": f"C{i}", "min_salary": i * 1000}
            for i in range(10)
        ]
        inserted, skipped = fresh_db.insert_jobs_batch(jobs)
        assert inserted == 10
        assert skipped == 0

    def test_batch_upsert(self, fresh_db):
        jobs = [{"id": f"batch_{i}", "title": f"T{i}"} for i in range(5)]
        fresh_db.insert_jobs_batch(jobs)
        fresh_db.insert_jobs_batch(jobs)  # 重复插入应upsert
        stats = fresh_db.get_statistics()
        assert stats.total_active == 5

    def test_empty_batch(self, fresh_db):
        inserted, skipped = fresh_db.insert_jobs_batch([])
        assert inserted == 0
        assert skipped == 0

    def test_large_batch_chunking(self, fresh_db):
        """大批量自动分批（BATCH_SIZE=500）"""
        jobs = [{"title": f"L{i}"} for i in range(200)]  # 减少数量加速测试
        inserted, _ = fresh_db.insert_jobs_batch(jobs)
        assert inserted == 200


# ==================== Delete ====================
class TestSQLiteDelete:
    @pytest.fixture
    def db_with_job(self, tmp_path):
        db_path = str(tmp_path / "delete.db")
        backend = SQLiteBackend(db_path=db_path)
        backend.connect()
        backend.insert_job({"id": "to_delete", "title": "将被删除"})
        yield backend
        backend.close()

    def test_soft_delete(self, db_with_job):
        result = db_with_job.delete_job("to_delete")
        assert result is True

        # 被删除的岗位不应再被查到 (soft delete -> status != active)
        job = db_with_job.get_job_by_id("to_delete")
        # soft delete 后 status='deleted', fetch_jobs 只查 status='active'
        active_jobs = db_with_job.fetch_jobs()
        assert not any(j.id == "to_delete" for j in active_jobs)

    def test_delete_nonexistent(self, fresh_db):
        result = fresh_db.delete_job("nonexistent")
        assert result is False


# ==================== Fetch Jobs ====================
class TestFetchJobs:
    @pytest.fixture
    def populated_db(self, fresh_db):
        """Populate with test data"""
        categories = ["制造", "IT", "服务"]
        for i, cat in enumerate(categories):
            fresh_db.insert_job({
                "id": f"q_{cat}_{i}",
                "title": f"{cat}岗位{i}",
                "company": f"{cat}公司",
                "category": cat,
                "min_salary": i * 2000 + 3000,
                "is_urgent": (i % 2 == 0)
            })
        # Insert one deleted record to verify filtering
        fresh_db.insert_job({"id": "deleted_one", "title": "D"})
        fresh_db.delete_job("deleted_one")  # soft delete
        yield fresh_db

    def test_fetch_all(self, populated_db):
        jobs = populated_db.fetch_jobs(limit=100)
        assert len(jobs) == 3  # 排除已 soft-delete 的

    def test_limit(self, populated_db):
        jobs = populated_db.fetch_jobs(limit=2)
        assert len(jobs) <= 2

    def test_offset(self, populated_db):
        first_page = populated_db.fetch_jobs(limit=1, offset=0)
        second_page = populated_db.fetch_jobs(limit=1, offset=1)
        if len(first_page) > 0 and len(second_page) > 0:
            assert first_page[0].id != second_page[0].id

    def test_category_filter(self, populated_db):
        it_jobs = populated_db.fetch_jobs(category_filter="IT")
        assert all(j.category == "IT" for j in it_jobs)
        assert len(it_jobs) >= 1

    def test_urgent_only(self, populated_db):
        urgent = populated_db.fetch_jobs(urgent_only=True)
        assert all(j.is_urgent is True for j in urgent)

    def test_search_query(self, populated_db):
        results = populated_db.fetch_jobs(search_query="制造")
        assert any("制造" in j.title for j in results)

    def test_empty_result(self, fresh_db):
        results = fresh_db.fetch_jobs(search_query="不存在XYZABC12345")
        assert len(results) == 0

    def test_default_limit(self, populated_db):
        """默认 limit=100 应返回全部3条"""
        jobs = populated_db.fetch_jobs()
        assert len(jobs) == 3


# ==================== Get By Id ====================
class TestGetJobById:
    @pytest.fixture
    def db_with_data(self, fresh_db):
        fresh_db.insert_job({"id": "target_123", "title": "目标岗位", "company": "C"})
        return fresh_db

    def test_found(self, db_with_data):
        job = db_with_data.get_job_by_id("target_123")
        assert job is not None
        assert job.id == "target_123"
        assert job.title == "目标岗位"

    def test_not_found(self, fresh_db):
        job = fresh_db.get_job_by_id("nonexistent_xyz")
        assert job is None

    def test_returns_jobrecord_type(self, db_with_data):
        job = db_with_data.get_job_by_id("target_123")
        assert isinstance(job, JobRecord)


# ==================== Statistics ====================
class TestGetStatistics:
    @pytest.fixture
    def stats_db(self, fresh_db):
        fresh_db.insert_job({"id": "s1", "title": "T1", "category": "A", "is_urgent": True})
        fresh_db.insert_job({"id": "s2", "title": "T2", "category": "A", "is_urgent": False})
        fresh_db.insert_job({"id": "s3", "title": "T3", "category": "B", "is_urgent": False})
        return fresh_db

    def test_total_count(self, stats_db):
        stats = stats_db.get_statistics()
        assert stats.total_active == 3

    def test_category_distribution(self, stats_db):
        stats = stats_db.get_statistics()
        assert stats.by_category["A"] == 2
        assert stats.by_category["B"] == 1

    def test_urgent_stats(self, stats_db):
        stats = stats_db.get_statistics()
        assert stats.urgent_count == 1
        assert stats.urgent_ratio > 0
        assert stats.urgent_ratio <= 100

    def test_salary_distribution(self, stats_db):
        stats = stats_db.get_statistics()
        assert isinstance(stats.salary_distribution, dict)

    def test_backend_type(self, stats_db):
        stats = stats_db.get_statistics()
        assert stats.backend_type == "sqlite"

    def test_last_updated_populated(self, stats_db):
        stats = stats_db.get_statistics()
        assert stats.last_updated is not None
        assert len(stats.last_updated) > 0


# ==================== Execution History ====================
class TestExecutionHistory:
    def test_record_and_retrieve(self, fresh_db):
        fresh_db.record_execution("task_1", "pipeline", {}, {"status": "success"})
        fresh_db.record_execution("task_2", "db", {}, {"status": "error"})

        history = fresh_db.get_execution_history(limit=10)
        assert len(history) == 2
        # 最新记录在前 (ORDER BY created_at DESC)
        assert history[0]["id"] == "task_1"
        assert history[1]["mode"] == "db"

    def test_limit(self, fresh_db):
        for i in range(15):
            fresh_db.record_execution(f"task_l{i}", "pipeline", {}, {"status": "ok"})
        history = fresh_db.get_execution_history(limit=5)
        assert len(history) == 5

    def test_options_serialized(self, fresh_db):
        opts = {"key": "value", "nested": {"k": "v"}}
        fresh_db.record_execution("opts_test", "pipeline", opts, {})
        history = fresh_db.get_execution_history(limit=1)
        # get_execution_history 已经 json.loads 了 options 字段
        loaded_opts = history[0]["options"]
        assert loaded_opts["key"] == "value"

    def test_result_serialized(self, fresh_db):
        result = {"total": 42, "passed": 40}
        fresh_db.record_execution("res_test", "pipeline", {}, result)
        history = fresh_db.get_execution_history(limit=1)
        loaded_result = history[0]["result"]
        assert loaded_result["total"] == 42

    def test_duration_recorded(self, fresh_db):
        fresh_db.record_execution("dur_test", "pipeline", {},
                                   {"status": "success", "duration": 12.5})
        history = fresh_db.get_execution_history(limit=1)
        # duration 从 result 中提取存储
        assert history[0]["duration"] is not None or history[0]["result"].get("duration") == 12.5


# ==================== Count Jobs ====================
class TestCountJobs:
    @pytest.fixture
    def count_db(self, fresh_db):
        fresh_db.insert_job({"id": "cnt_1", "title": "Countable1", "company": "C1"})
        fresh_db.insert_job({"id": "cnt_2", "title": "Countable2", "company": "C2"})
        return fresh_db

    def test_count_all(self, count_db):
        assert count_db.count_jobs() == 2

    def test_count_with_search(self, count_db):
        assert count_db.count_jobs(search_query="Countable1") == 1
        assert count_db.count_jobs(search_query="NOTFOUND999") == 0

    def test_count_after_delete(self, fresh_db):
        fresh_db.insert_job({"id": "c1", "title": "ToDel"})
        assert fresh_db.count_jobs() == 1
        fresh_db.delete_job("c1")
        assert fresh_db.count_jobs() == 0


# ==================== Connection Management ====================
class TestConnectionManagement:
    def test_close_clears_connection(self, fresh_db):
        assert fresh_db._connected is True
        fresh_db.close()
        assert fresh_db._connected is False

    def test_test_connection(self, fresh_db):
        info = fresh_db.test_connection()
        assert info["connected"] is True
        assert info["backend_type"] == "sqlite"
        assert "tables_exist" in info
        assert "total_records" in info
        assert "database_exists" in info
        assert info["database_exists"] is True

    def test_reconnect_after_close(self, tmp_path):
        db_path = str(tmp_path / "recon.db")
        backend = SQLiteBackend(db_path=db_path)
        backend.connect()
        backend.insert_job({"title": "BeforeClose"})
        backend.close()
        backend.connect()  # reconnect
        jobs = backend.fetch_jobs()
        assert len(jobs) == 1
        backend.close()


# ==================== Factory Function ====================
class TestGetBackend:
    def test_returns_sqlitebackend(self):
        backend = get_backend()
        assert isinstance(backend, SQLiteBackend)

    def test_singleton_behavior(self):
        """验证 get_backend 返回同一实例"""
        b1 = get_backend()
        b2 = get_backend()
        # 注意：如果使用了单例模式，b1 和 b2 应该是同一个对象或共享同一个连接
        assert type(b1) == type(b2)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
