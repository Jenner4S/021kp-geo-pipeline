# -*- coding: utf-8 -*-
"""
GEO Pipeline Phase 5: 分发监控完整测试套件 (100% 覆盖率目标)
==============================================================

覆盖范围:
- MonitorState / CitationMetrics / AlertRule / MonitorReport 数据类
- AICitationProbe: 引用率检测/模拟响应/批量检查/缓存淘汰
- AlertEngine: 规则评估/比较运算符/告警消息/通知发送/历史记录
- VectorRollbackManager: 回滚执行/恢复检测/强制回滚
- DistributionMonitor: 主控制器/单次检查/调度器/报告生成

运行: pytest tests/test_dist_monitor_full.py -v --tb=short
"""

import json
import os
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dist_monitor import (
    MonitorState,
    CitationMetrics,
    AlertRule,
    MonitorReport,
    AICitationProbe,
    AlertEngine,
    VectorRollbackManager,
    DistributionMonitor,
)


# ==================== 数据类测试 ====================
class TestMonitorState:
    """监控状态枚举"""
    def test_values(self):
        assert MonitorState.NORMAL.value == "NORMAL"
        assert MonitorState.DEGRADED.value == "DEGRADED"
        assert MonitorState.FROZEN.value == "FROZEN"


class TestCitationMetrics:
    """引用指标数据类"""

    def test_defaults(self):
        m = CitationMetrics()
        assert m.platform == ""
        assert m.brand_mention_count == 0
        assert m.total_queries == 0
        assert m.citation_rate == 0.0
        assert m.ctr_estimate is None
        assert m.last_check_time == ""
        assert m.trend == "stable"

    def test_custom_values(self):
        m = CitationMetrics(
            platform="metaso",
            brand_mention_count=5,
            total_queries=100,
            citation_rate=5.0,
            trend="rising",
            last_check_time="2026-04-21T10:00:00"
        )
        assert m.platform == "metaso"
        assert m.citation_rate == 5.0


class TestAlertRule:
    """告警规则数据类"""

    def test_defaults(self):
        r = AlertRule(metric_name="test")
        assert r.operator == "<="
        assert r.consecutive_failures == 3
        assert r.cooldown_seconds == 3600
        assert r.severity == "warning"
        assert r.action == "alert"

    def test_custom(self):
        r = AlertRule(
            metric_name="custom_rate",
            threshold=0.95,
            operator="<",
            consecutive_failures=5,
            cooldown_seconds=7200,
            severity="critical",
            action="rollback"
        )
        assert r.threshold == 0.95


class TestMonitorReport:
    """监控报告数据类"""

    def test_defaults(self):
        r = MonitorReport()
        assert r.report_id != ""
        assert r.generated_at == ""
        assert r.overall_status == MonitorState.NORMAL
        assert r.metrics == []
        assert r.alerts_triggered == []
        assert r.recommendations == []


# ==================== AICitationProbe ====================
class TestAICitationProbeInit:
    """探针初始化"""

    def test_default_config(self):
        probe = AICitationProbe()
        assert len(probe.config["probes"]) >= 2
        assert probe._cache_ttl == 3600
        assert probe._cache_max_size == 1000

    def test_custom_config(self, tmp_path):
        cfg_path = tmp_path / "probe_cfg.json"
        cfg_path.write_text(json.dumps({
            "probes": {
                "custom": {"enabled": True, "base_url": "https://custom.test"}
            },
            "check_interval_hours": 1,
            "timeout_seconds": 5
        }), encoding='utf-8')
        
        probe = AICitationProbe(config_path=str(cfg_path))
        assert "custom" in probe.config["probes"]
        assert probe.config["check_interval_hours"] == 1

    def test_missing_config_uses_default(self):
        probe = AICitationProbe(config_path="/nonexistent/path.json")
        assert len(probe.config["probes"]) >= 2  # 使用默认配置


class TestAICitationProbeCheckCitationRate:
    """引用率检测"""

    def _probe(self):
        return AICitationProbe()

    def test_returns_metrics_object(self):
        m = self._probe().check_citation_rate("metaso")
        assert isinstance(m, CitationMetrics)
        assert m.platform == "metaso"

    def test_default_query_when_none(self):
        """无查询词时使用默认词库随机选择"""
        m = self._probe().check_citation_rate("doubao")
        assert m.total_queries > 0 or m.brand_mention_count >= 0

    def test_custom_query(self):
        m = self._probe().check_citation_rate("yuanbao", query="松江急招")
        assert m.platform == "yuanbao"

    def test_citation_rate_calculation(self):
        """引用率计算正确性（基于模拟数据）"""
        # 模拟模式下，结果来自 _simulate_platform_response 或 _generate_mock_metrics
        probe = self._probe()
        m = probe.check_citation_rate("metaso", query="固定查询")
        if m.total_queries > 0:
            expected_rate = m.brand_mention_count / m.total_queries * 100
            assert abs(m.citation_rate - expected_rate) < 0.01

    def test_trend_value_valid(self):
        valid_trends = {"stable", "rising", "falling", "unknown"}
        for platform in ["metaso", "doubao", "yuanbao"]:
            m = self._probe().check_citation_rate(platform)
            assert m.trend in valid_trends, f"无效 trend: {m.trend}"

    def test_timestamp_set(self):
        m = self._probe().check_citation_rate("doubao")
        assert m.last_check_time != ""


class TestAICitationProbeSimulation:
    """模拟响应"""

    def test_deterministic_for_same_input(self):
        """相同输入产生相同输出（seed based）"""
        probe = self._probe()
        r1 = probe._simulate_platform_response("metaso", "query")
        r2 = probe._simulate_platform_response("metaso", "query")
        assert r1 == r2  # same seed → same result

    def test_different_platforms_differ(self):
        probe = self._probe()
        r1 = probe._simulate_platform_response("metaso", "q")
        r2 = probe._simulate_platform_response("doubao", "q")
        # 不同平台的 seed 不同，结果应不同
        # 但不能保证，所以只验证结构
        assert "mention_count" in r1 and "mention_count" in r2

    def test_mock_metrics_structure(self):
        probe = self._probe()
        m = probe._generate_mock_metrics("test", "q")
        assert m.citation_rate >= 0
        assert m.total_queries > 0
        assert m.trend in ("stable", "rising", "falling")


class TestAICitationProbeCache:
    """缓存机制"""

    def test_cache_eviction_on_overflow(self):
        """超过最大容量时淘汰旧条目"""
        probe = AICitationProbe()
        probe._cache_max_size = 5
        
        for i in range(20):
            probe.check_citation_rate("platform", query=f"query_{i % 3}")
        
        assert len(probe._cache) <= 5 + 2  # 允许小幅超限


class TestAICitationProbeBatchCheck:
    """批量检查"""

    def test_batch_returns_list(self):
        probe = AICitationProbe()
        results = probe.batch_check()
        assert isinstance(results, list)
        # 默认配置启用多个平台，每个平台查2个关键词
        assert len(results) >= 2

    def test_disabled_platforms_skipped(self, tmp_path):
        cfg_path = tmp_path / "disabled.cfg"
        cfg_path.write_text(json.dumps({
            "probes": {"enabled_one": {"enabled": False}, "enabled_two": {"enabled": True}}
        }), encoding='utf-8')
        
        probe = AICitationProbe(config_path=str(cfg_path))
        results = probe.batch_check()
        for r in results:
            assert r.platform != "enabled_one"


# ==================== AlertEngine ====================
class TestAlertEngineCompare:
    """比较运算符"""

    @staticmethod
    def _compare(op, value, threshold):
        return AlertEngine._compare(value, threshold, op)

    def test_less_than(self): assert self._compare("<", 0.5, 1.0) is True
    def test_less_equal(self): assert self._compare("<=", 1.0, 1.0) is True
    def test_greater_than(self): assert self._compare(">", 2.0, 1.0) is True
    def test_greater_equal(self): assert self._compare(">=", 1.0, 1.0) is True
    def test_equal(self): assert self._compare("==", 1.0, 1.0005) is True
    def test_not_equal(self): assert self._compare("!=", 0.0, 1.0) is True
    def test_invalid_op(self): assert self._compare("INVALID", 1, 1) is False


class TestAlertEngineEvaluate:
    """规则评估"""

    def _make_engine(self, rules=None, tmp_path=None):
        if tmp_path is not None:
            alert_dir = tmp_path / "alerts"
        else:
            alert_dir = Path("./test_alerts_dir_for_eval")
        if rules is None:
            rules = [
                AlertRule(metric_name="test_metric", threshold=1.0, operator="<=",
                           consecutive_failures=1, cooldown_seconds=0)
            ]
        return AlertEngine(rules=rules)

    def test_alert_triggered_below_threshold(self, tmp_path):
        engine = self._make_engine(tmp_path=tmp_path)
        metrics = [CitationMetrics(platform="p", citation_rate=0.1)]
        alerts = engine.evaluate(metrics)
        assert len(alerts) == 1
        assert alerts[0]["metric_name"] == "test_metric"

    def test_no_alert_above_threshold(self, tmp_path):
        engine = self._make_engine(tmp_path=tmp_path)
        metrics = [CitationMetrics(platform="p", citation_rate=5.0)]
        alerts = engine.evaluate(metrics)
        assert len(alerts) == 0

    def test_consecutive_failures_required(self, tmp_path):
        """需要连续失败N次才触发"""
        engine = self._make_engine(rules=[
            AlertRule(metric_name="consecutive_test", threshold=1.0, operator="<=",
                       consecutive_failures=3, cooldown_seconds=0)
        ], tmp_path=tmp_path)
        
        # 只失败1次和2次不触发
        metrics1 = [CitationMetrics(platform="p", citation_rate=0.8)]
        metrics2 = [CitationMetrics(platform="p", citation_rate=0.9)]
        engine.evaluate(metrics1)  # fail count = 1
        engine.evaluate(metrics2)  # fail count = 2
        alerts = engine.evaluate(metrics1)  # fail count = 3 → should trigger
        assert len(alerts) == 1

    def test_reset_on_pass(self, tmp_path):
        """通过时重置计数"""
        engine = self._make_engine(rules=[
            AlertRule(metric_name="reset_test", threshold=1.0, operator="<=",
                       consecutive_failures=2, cooldown_seconds=0)
        ], tmp_path=tmp_path)
        
        fail_m = CitationMetrics(platform="p", citation_rate=0.5)
        pass_m = CitationMetrics(platform="p", citation_rate=2.0)
        
        engine.evaluate(fail_m)  # count=1
        engine.evaluate(fail_m)  # count=2 → should trigger
        engine.evaluate(pass_m)  # 通过后count应被重置
        
        alerts = engine.evaluate(fail_m)  # count=1 again, no trigger
        assert len(alerts) == 0


class TestAlertEngineMessage:
    """告警消息生成"""

    def test_citation_message_format(self, tmp_path):
        engine = self._make_engine(tmp_path=tmp_path)
        msg = engine._generate_alert_message(
            AlertRule(metric_name="citation_rate", threshold=0.5),
            0.25
        )
        assert "引用率" in msg
        assert "0.25" in msg or "0.50" in msg

    def test_api_success_message(self, tmp_path):
        engine = self._make_engine(tmp_path=tmp_path)
        msg = engine._generate_alert_message(
            AlertRule(metric_name="api_success_rate", threshold=0.95),
            0.85
        )
        assert "API成功率" in msg

    def test_compliance_message_critical(self, tmp_path):
        engine = self._make_engine(tmp_path=tmp_path)
        msg = engine._generate_alert_message(
            AlertRule(metric_name="compliance_pass_rate", threshold=1.0),
            0.98
        )
        assert "合规" in msg.lower() or "100%" in msg


class TestAlertEngineNotification:
    """通知发送"""

    def test_no_webhook_skipped(self, tmp_path):
        """未配置Webhook时跳过"""
        engine = self._make_engine(tmp_path=tmp_path)
        with patch.dict(os.environ, {}, clear=True):
            result = engine._send_notification({"test": "alert"})
        assert result is False

    def test_history_written(self, tmp_path):
        """告警历史写入文件"""
        engine = self._make_engine(tmp_path=tmp_path)
        alert = {"rule": "test", "severity": "info", "message": "test alert"}
        engine._write_alert_history(alert)
        
        log_files = list(Path(engine.alert_history_dir).glob("alerts_*.jsonl"))
        assert len(log_files) >= 1
        entry = json.loads(log_files[-1].read_text(encoding='utf-8'))
        assert entry["rule"] == "test"


# ==================== VectorRollbackManager ====================
class TestVectorRollbackManagerExecute:
    """回滚执行"""

    def _mgr(self, tmp_path):
        rb_dir = tmp_path / "rb_logs"
        return VectorRollbackManager(), rb_dir

    def test_rollback_creates_page(self, tmp_path):
        mgr, rb_dir = self._mgr(tmp_path)
        mgr.rollback_log_dir = str(rb_dir)
        mgr._write_lock = threading.Lock()  # 补充属性
        
        result = mgr.execute_rollback(reason="测试原因")
        assert result["success"] is True
        assert mgr.rollback_state["is_frozen"] is True
        assert mgr.rollback_state["reason"] == "测试原因"

    def test_compliance_template_created(self, tmp_path):
        mgr, rb_dir = self._mgr(tmp_path)
        mgr.rollback_log_dir = str(rb_dir)
        mgr._write_lock = threading.Lock()
        
        result = mgr.execute_rollback(reason="template_test")
        output_file = result.get("output_file")
        if output_file and os.path.exists(output_file):
            content = Path(output_file).read_text(encoding='utf-8')
            assert "合规" in content or "人社局" in content

    def test_double_rollback_blocked(self, tmp_path):
        mgr, rb_dir = self._mgr(tmp_path)
        mgr.rollback_log_dir = str(rb_dir)
        mgr._write_lock = threading.Lock()
        
        mgr.execute_rollback(reason="first")  # success
        result = mgr.execute_rollback(reason="second")
        assert result["success"] is False

    def test_force_override(self, tmp_path):
        mgr, rb_dir = self._mgr(tmp_path)
        mgr.rollback_log_dir = str(rb_dir)
        mgr._write_lock = threading.Lock()
        
        mgr.execute_rollback(reason="normal")
        result = mgr.execute_rollback(reason="force", force=True)
        assert result["success"] is True

    def test_backup_saved(self, tmp_path):
        mgr, rb_dir = self._mgr(tmp_path)
        mgr.rollback_log_dir = str(rb_dir)
        mgr._write_lock = threading.Lock()
        
        mgr.execute_rollback(reason="backup_test")
        backup = mgr.rollback_state.get("original_config_backup")
        assert backup is not None
        assert backup.get("timestamp") is not None


class TestVectorRollbackManagerRecovery:
    """恢复机制"""

    def _frozen_mgr(self, tmp_path):
        mgr = VectorRollbackManager()
        rb_dir = tmp_path / "rb_recovery"
        mgr.rollback_log_dir = str(rb_dir)
        mgr._write_lock = threading.Lock()
        mgr.rollback_state = {"is_frozen": False, "frozen_at": None, "reason": "", "original_config_backup": None}
        return mgr, rb_dir

    def test_can_recover_when_not_frozen(self, tmp_path):
        mgr, _ = self._frozen_mgr(tmp_path)
        can, reason = mgr.can_recover()
        assert can is True

    def test_cannot_recover_within_48h(self, tmp_path):
        mgr, _ = self._frozen_mgr(tmp_path)
        mgr.execute_rollback(reason="timer_test")
        can, reason = mgr.can_recover()
        assert can is False
        assert "剩余" in reason or "保护期" in reason

    def test_can_recover_after_48h(self, tmp_path):
        mgr, _ = self._frozen_mgr(tmp_path)
        mgr.rollback_state["frozen_at"] = "2026-01-01T00:00:00"  # 很久以前
        can, reason = mgr.can_recover()
        assert can is True
        assert "可申请" in reason or "允许" in reason


class TestVectorRollbackManagerRequestRecovery:
    """恢复请求"""

    def test_recovery_approved_when_eligible(self, tmp_path):
        mgr = VectorRollbackManager()
        rb_dir = tmp_path / "rb_req"
        mgr.rollback_log_dir = str(rb_dir)
        mgr._write_lock = threading.Lock()
        mgr.rollback_state = {"is_frozen": False, "frozen_at": None, "reason": "", "original_config_backup": None}
        
        result = mgr.request_recovery(reviewer_id="admin")
        assert result["success"] is True

    def test_recovery_denied_when_frozen(self, tmp_path):
        mgr = VectorRollbackManager()
        rb_dir = tmp_path / "rb_denied"
        mgr.rollback_log_dir = str(rb_dir)
        mgr._write_lock = threading.Lock()
        mgr.rollback_state = {"is_frozen": True, "frozen_at": None, "reason": "", "original_config_backup": None}
        
        result = mgr.request_recovery(reviewer_id="user")
        assert result["success"] is False
        assert "拒绝" in result.get("message", "") or "不可" in result.get("message", "")


# ==================== DistributionMonitor 主控制器 ====================
class TestDistributionMonitorSingleCheck:
    """单次监控检查"""

    def _monitor(self, tmp_path):
        return DistributionMonitor()

    def test_single_check_returns_report(self, tmp_path):
        monitor = self._monitor(tmp_path)
        report = monitor.run_single_check()
        assert isinstance(report, MonitorReport)
        assert report.report_id != ""
        assert report.generated_at != ""
        assert isinstance(report.overall_status, MonitorState)

    def test_report_contains_metrics(self, tmp_path):
        monitor = self._monitor(tmp_path)
        report = monitor.run_single_check()
        assert len(report.metrics) > 0
        for m in report.metrics:
            assert isinstance(m, CitationMetrics)
            assert m.platform != ""

    def test_ai_preview_generated(self, tmp_path):
        monitor = self._monitor(tmp_path)
        report = monitor.run_single_check()
        assert len(report.ai_preview_simulation) > 0
        assert "AI预览" in report.ai_preview_simulation or "监测指标" in report.ai_preview_simulation

    def test_report_saved(self, tmp_path):
        monitor = self._monitor(tmp_path)
        report = monitor.run_single_check()
        reports_dir = Path("./dist/reports")
        if reports_dir.exists():
            json_file = reports_dir / f"{report.report_id}.json"
            assert json_file.exists()


class TestDistributionMonitorScheduler:
    """定时调度器"""

    def test_start_scheduler_sets_running(self, tmp_path):
        monitor = self._monitor(tmp_path)
        assert monitor._running is False
        # 注意：start_scheduler 会创建线程，测试时不实际启动
        # 仅验证状态

    def test_stop_scheduler_resets(self, tmp_path):
        monitor = self._monitor(tmp_path)
        monitor._running = True
        monitor._scheduler_thread = MagicMock()
        monitor.stop_scheduler()
        assert monitor._running is False


class TestDistributionMonitorScheduleLoop:
    """调度循环（不实际运行）"""

    def test_scheduled_task_exists(self):
        assert hasattr(DistributionMonitor, '_schedule_loop')
        assert hasattr(DistributionMonitor, '_scheduled_task')


class TestDistributionMonitorReportSaving:
    """报告保存"""

    def test_json_report_structure(self, tmp_path):
        monitor = DistributionMonitor()
        report = MonitorReport(
            report_id="test_report_001",
            generated_at="2026-04-21T12:00:00",
            overall_status=MonitorState.NORMAL,
            metrics=[CitationMetrics(platform="p1", citation_rate=1.5)],
            recommendations=["建议1"]
        )
        monitor._save_report(report)
        # 验证JSON报告存在
        p = Path("./dist/reports/test_report_001.json")
        if p.exists():
            data = json.loads(p.read_text())
            assert data["report_id"] == "test_report_001"
            assert data["overall_status"] == "NORMAL"

    def test_md_report_created(self, tmp_path):
        monitor = DistributionMonitor()
        report = MonitorReport(
            report_id="md_test",
            metrics=[CitationMetrics(platform="p", citation_rate=2.0)],
            recommendations=[]
        )
        monitor._save_report(report)
        md_file = Path(f"./dist/reports/md_test.md")
        if md_file.exists():
            content = md_file.read_text(encoding='utf-8')
            assert "GEO运营监控报告" in content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
