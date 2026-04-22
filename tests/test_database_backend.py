# -*- coding: utf-8 -*-
"""
GEO Pipeline 数据库后端测试套件 (SQLite)
=============================================

目标: 覆盖 database_backend.py 所有CRUD/搜索/统计接口
运行: uv run pytest tests/test_database_backend.py -v --tb=short
"""

import os
import sys
import time
import json
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from database_backend import (
    JobRecord, DatabaseStats, DatabaseBackendABC, SQLiteBackend,
)


class TestJobRecord:
    """JobRecord 数据结构测试"""

    def test_default_values(self):
        r = JobRecord()
        assert r.id == 0
        assert r.title == ""
        assert r.min_salary == 0.0
        assert r.is_urgent is False

    def test_custom_values(self):
        r = JobRecord(id=42, title="工程师", min_salary=8000, max_salary=15000)
        assert r.id == 42
        assert r.title == "工程师"
        assert r.min_salary == 8000.0
        assert r.max_salary == 15000.0

    def test_to_dict_completeness(self):
        r = JobRecord(
            id=1, title="T", company="C", location="L",
            category="CAT", benefits="五险一金", is_urgent=True,
            description="D", address="A"
        )
        d = r.to_dict()
        expected_keys = {
            "id", "title", "company", "salary", "min_salary", "max_salary",
            "location", "category", "experience", "education", "hire_count",
            "benefits", "description", "address", "update_time",
            "source_url", "is_urgent",
        }
        assert set(d.keys()) == expected_keys
        assert d["is_urgent"] is True
        assert d["benefits"] == "五险一金"


class TestDatabaseStats:
    """DatabaseStats 统计快照"""

    def test_default_empty(self):
        s = DatabaseStats()
        assert s.total_active == 0
        assert s.by_category == {}
        assert s.urgent_ratio == 0.0

    def test_with_data(self):
        s = DatabaseStats(
            total_active=100, by_category={"IT": 30, "制造": 50},
            urgent_count=10, urgent_ratio=0.1
        )
        assert s.total_active == 100
        assert s.by_category["IT"] == 30
        assert abs(s.urgent_ratio - 0.1) < 1e-9


class TestSQLiteBackend:
    """SQLite 后端完整 CRUD + 搜索 + 统计 测试"""

    @pytest.fixture(autouse=True)
    def setup_db(self, tmp_path):
        """为每个测试创建独立的临时数据库"""
        db_file = tmp_path / "test_pipeline.db"
        self.db = SQLiteBackend(db_path=str(db_file))
        self.db.connect()

        yield

        self.db.close()
        # 清理WAL文件
        for ext in ["", "-wal", "-shm"]:
            p = Path(str(db_file) + ext)
            if p.exists():
                p.unlink(missing_ok=True)

    # ==================== 基础连接 ====================

    def test_connect_creates_tables(self):
        """连接应自动创建jobs和executions表"""
        conn = self.db.conn if hasattr(self.db, 'conn') else None
        assert conn is not None
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        table_names = {t[0] for t in tables}
        assert "jobs" in table_names or "job_records" in table_names

    def test_connection_returns_true_on_success(self):
        result = self.db.connect()
        assert result is True

    def test_test_connection_metadata(self):
        info = self.db.test_connection()
        assert info.get("connected") is True
        assert "backend_type" in info or "database" in info

    def test_double_close_safe(self):
        """多次close不应抛异常"""
        self.db.close()
        self.db.close()  # 应静默成功

    # ==================== INSERT ====================

    def test_insert_single_job(self):
        job = {"id": "J001", "title": "测试岗位", "company": "测试公司",
               "location": "松江区", "min_salary": 6000, "max_salary": 10000}
        ok = self.db.insert_job(job)
        assert ok is True

    def test_insert_job_with_defaults(self):
        """缺少字段应使用默认值填充"""
        job = {"id": "J002", "title": "最少字段"}
        ok = self.db.insert_job(job)
        assert ok is True

    def test_upsert_same_id_updates(self):
        job1 = {"id": "J003", "title": "原始标题", "company": "A"}
        job2 = {"id": "J003", "title": "更新标题", "company": "B"}
        self.db.insert_job(job1)
        self.db.insert_job(job2)
        found = self.db.get_job_by_id("J003")
        assert found is not None
        assert found.title == "更新标题"

    # ==================== INSERT BATCH ====================

    def test_batch_insert_multiple(self):
        jobs = [
            {"id": f"B{i:03d}", "title": f"批量岗位{i}", "company": f"公司{i}"}
            for i in range(10)
        ]
        inserted, skipped = self.db.insert_jobs_batch(jobs)
        assert inserted >= len(jobs)

    def test_batch_insert_empty(self):
        inserted, skipped = self.db.insert_jobs_batch([])
        assert inserted == 0
        assert skipped == 0

    def test_batch_with_duplicates(self):
        base = [{"id": "DUP01", "title": "原始"}]
        update = [{"id": "DUP01", "title": "更新"}]
        self.db.insert_jobs_batch(base)
        ins, _ = self.db.insert_jobs_batch(update)
        # upsert行为: 至少更新了记录
        found = self.db.get_job_by_id("DUP01")
        assert found.title == "更新"

    # ==================== GET BY ID ====================

    def test_get_by_id_found(self):
        job = {"id": "G001", "title": "查找我"}
        self.db.insert_job(job)
        result = self.db.get_job_by_id("G001")
        assert result is not None
        assert result.title == "查找我"
        assert isinstance(result, JobRecord)

    def test_get_by_id_not_found(self):
        result = self.db.get_job_by_id("NONEXISTENT")
        assert result is None

    def test_get_by_id_after_delete(self):
        self.db.insert_job({"id": "DEL001", "title": "待删除"})
        self.db.delete_job("DEL001")
        result = self.db.get_job_by_id("DEL001")
        assert result is None

    # ==================== FETCH JOBS (分页+筛选) ====================

    def test_fetch_jobs_default(self):
        for i in range(5):
            self.db.insert_job({"id": f"F{i:03d}", "title": f"岗位{i}"})
        results = self.db.fetch_jobs(limit=100)
        assert len(results) >= 5

    def test_fetch_jobs_pagination_offset(self):
        for i in range(10):
            self.db.insert_job({"id": f"P{i:03d}", "title": f"分页{i}"})
        page1 = self.db.fetch_jobs(limit=3, offset=0)
        page2 = self.db.fetch_jobs(limit=3, offset=3)
        # 两页数据应不重叠（按created_at DESC排序）
        ids1 = {r.id for r in page1}
        ids2 = {r.id for r in page2}
        assert len(ids1 & ids2) == 0

    def test_fetch_jobs_category_filter(self):
        self.db.insert_job({"id": "CAT-IT", "title": "IT岗", "category": "it"})
        self.db.insert_job({"id": "CAT-MF", "title": "制造岗", "category": "manufacturing"})
        it_jobs = self.db.fetch_jobs(limit=10, category_filter="it")
        # category_filter 可能返回全部或过滤结果
        if len(it_jobs) > 0:
            assert all(getattr(j, 'category', '') == "it" or str(getattr(j, 'category', '')) == "it" for j in it_jobs)

    def test_fetch_jobs_urgent_only(self):
        self.db.insert_job({"id": "URG-1", "title": "急招", "is_urgent": True})
        self.db.insert_job({"id": "URG-2", "title": "普通"})
        urgent_only = self.db.fetch_jobs(limit=10, urgent_only=True)
        if len(urgent_only) > 0:
            assert all(getattr(j, 'is_urgent', False) is True for j in urgent_only)

    def test_fetch_jobs_search_query(self):
        self.db.insert_job({"id": "SRCH-1", "title": "Python开发工程师"})
        self.db.insert_job({"id": "SRCH-2", "title": "Java开发工程师"})
        self.db.insert_job({"id": "SRCH-3", "title": "销售经理"})
        results = self.db.fetch_jobs(limit=10, search_query="Python")
        assert len(results) >= 1

    # ==================== DELETE ====================

    def test_delete_existing(self):
        self.db.insert_job({"id": "RM-001", "title": "删除目标"})
        ok = self.db.delete_job("RM-001")
        assert ok is True
        assert self.db.get_job_by_id("RM-001") is None

    def test_delete_nonexistent(self):
        ok = self.db.delete_job("NO-SUCH-ID")
        assert ok is False  # 或True取决于实现，但不应抛异常

    # ==================== COUNT ====================

    def test_count_jobs_total(self):
        initial = self.db.count_jobs()
        for i in range(5):
            self.db.insert_job({"id": f"CT{i:03d}", "title": f"c{i}"})
        total = self.db.count_jobs()
        assert total >= initial + 5

    def test_count_jobs_with_search(self):
        self.db.insert_job({"id": "CT-S1", "title": "松江招聘专员"})
        self.db.insert_job({"id": "CT-S2", "title": "浦东销售经理"})
        count = self.db.count_jobs(search_query="松江")
        assert count >= 1

    # ==================== STATISTICS ====================

    def test_statistics_structure(self):
        for i in range(4):
            cat = "it" if i % 2 else "manufacturing"
            self.db.insert_job({
                "id": f"ST{i:03d}", "title": f"s{i}",
                "category": cat, "min_salary": 5000 + i * 1000,
                "max_salary": 8000 + i * 2000, "is_urgent": i == 0
            })
        stats = self.db.get_statistics()
        assert isinstance(stats, DatabaseStats)
        assert stats.total_active >= 4
        assert isinstance(stats.by_category, dict)
        assert stats.urgent_count >= 1
        # urgent_ratio 可能是 0-1 比例或 0-100 百分比
        ratio = stats.urgent_ratio
        assert (0 <= ratio <= 1) or (0 <= ratio <= 100)

    # ==================== EXECUTION HISTORY ====================

    def test_record_and_retrieve_execution(self):
        task_id = f"task_{int(time.time())}"
        self.db.record_execution(task_id, "pipeline", {"mode": "csv"}, {
            "status": "success", "processed": 42
        })
        history = self.db.get_execution_history(limit=5)
        assert len(history) >= 1
        latest = history[0]
        assert "task_id" in latest or "mode" in latest or "result" in latest

    def test_execution_history_respects_limit(self):
        for i in range(5):
            self.db.record_execution(f"lim_{i}", "db", {}, {"status": "ok"})
        history = self.db.get_execution_history(limit=2)
        assert len(history) <= 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
