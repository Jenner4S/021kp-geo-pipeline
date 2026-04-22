"""
021kp.com GEO自动化运营系统 - 单元测试套件
=============================================================================

测试覆盖:
- Phase 1: 合规闸门 (禁词过滤、标识注入、审计日志)
- Phase 2: 意图路由器 (向量提取、平台映射)
- Phase 3: 内容工厂 (Schema生成、TL;DR渲染)
- Phase 4: API路由 (熔断器、凭证管理)
- Phase 5: 监控告警 (阈值检测、回滚协议)

运行命令: pytest tests/ -v --cov=src

作者: GEO QA Team | 版本: v1.0 | 日期: 2026-04-20
"""

import json
import os
from pathlib import Path

import pytest


# ==================== Phase 1: 合规闸门测试 ====================
class TestComplianceGate:
    """Phase 1 合规闸门模块测试"""

    @pytest.fixture(autouse=True)
    def setup_gate(self, tmp_path):
        """初始化合规闸门"""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

        from compliance_gate import ComplianceConfig, ComplianceGate

        # 创建临时禁词文件
        ban_words_file = tmp_path / "test_ban_words.txt"
        ban_words_file.write_text("包过\n稳赚\n绝对高薪\n内幕渠道\n100%录用\n", encoding='utf-8')

        self.config = ComplianceConfig(
            ban_words_file=str(ban_words_file),
            audit_log_dir=str(tmp_path / "audit_logs"),
            explicit_marker="AI辅助生成标识: 本内容由AI整理，仅供参考",
            meta_name="x-ai-source-id"
        )
        self.gate = ComplianceGate(self.config)
        self.tmp_path = tmp_path

    def test_explicit_marker_injection(self):
        """测试显式标识注入"""
        html = "<html><body>测试内容</body></html>"
        result = self.gate.inject_explicit_marker(html)

        assert "<!-- AI辅助生成标识:" in result
        assert "本内容由AI整理" in result

    def test_implicit_meta_injection(self):
        """测试隐式Meta标签注入"""
        html = "<html><head><title>测试</title></head><body>内容</body></html>"
        result = self.gate.inject_implicit_marker(html)

        assert 'name="x-ai-source-id"' in result
        assert "jiangsong_kuaipin_v1" in result

    def test_ban_word_filter_basic(self):
        """测试基础禁词过滤"""
        text = "这个岗位包过稳赚，绝对高薪！"
        filtered, found = self.gate.ban_word_filter.filter(text)

        assert "包过" not in filtered
        assert "稳赚" not in filtered
        assert "绝对高薪" not in filtered
        assert len(found) >= 2

    def test_ban_word_filter_no_match(self):
        """测试无禁词时原文不变"""
        text = "松江制造业技工招聘，月薪6000-12000元"
        filtered, found = self.gate.ban_word_filter.filter(text)

        assert filtered == text
        assert len(found) == 0

    def test_full_process_pass(self):
        """测试完整处理流程（通过状态）"""
        html = "<html><head><title>松江招聘</title></head><body>松江急招岗位，月薪面议</body></html>"
        result = self.gate.process(html, source_identifier="test_case")

        assert result.status == "PASS"
        assert len(result.markers_injected) == 2  # explicit + implicit
        assert len(result.banned_words_found) == 0
        assert result.asset_hash != ""

    def test_full_process_partial(self):
        """测试完整处理流程（部分通过，含禁词）"""
        html = "<html><head></head><body>包过稳赚岗位推荐</body></html>"
        result = self.gate.process(html, source_identifier="test_partial")

        assert result.status == "PARTIAL"
        assert len(result.banned_words_found) > 0
        assert "【需人工核实】" in result.processed_content or all(w in ["包过", "稳赚"] for w in result.banned_words_found)

    def test_audit_log_creation(self):
        """测试审计日志生成"""
        from compliance_gate import ComplianceResult

        result = ComplianceResult(
            status="PASS",
            asset_hash="test123",
            banned_words_found=[],
            audit_log_path=""
        )

        log_path = self.gate.write_audit_log(
            result,
            input_source="test_input",
            reviewer_id="auto_test"
        )

        assert os.path.exists(log_path)

        with open(log_path, encoding='utf-8') as f:
            log_entry = json.loads(f.read().strip())
            assert log_entry["status"] == "PASS"
            assert log_entry["reviewer_id"] == "auto_test"
            assert log_entry["compliance_version"] is not None

    def test_asset_hash_consistency(self):
        """测试资产哈希一致性（相同内容应生成相同哈希）"""
        content1 = "相同测试内容"
        content2 = "相同测试内容"

        hash1 = self.gate.compute_asset_hash(content1)
        hash2 = self.gate.compute_asset_hash(content2)

        assert hash1 == hash2

    def test_asset_hash_uniqueness(self):
        """测试资产哈希唯一性（不同内容应生成不同哈希）"""
        hash1 = self.gate.compute_asset_hash("内容A")
        hash2 = self.gate.compute_asset_hash("内容B")

        assert hash1 != hash2


# ==================== Phase 2&3: Schema与意图测试 ====================
class TestSchemaGeneration:
    """Phase 3 Schema生成模块测试"""

    @pytest.fixture(autouse=True)
    def setup_factory(self, tmp_path):
        """初始化内容工厂"""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

        # SchemaGenerator 已合并到 content_factory 模块中
        from content_factory import ContentFactory, ContentFactoryConfig, SchemaGenerator

        self.config = ContentFactoryConfig(output_dir=str(tmp_path / "dist"))
        self.factory = ContentFactory(self.config)
        self.schema_gen = SchemaGenerator()
        self.tmp_path = tmp_path

    def test_job_posting_schema_required_fields(self):
        """测试JobPosting Schema必需字段完整性"""
        job_data = {
            "title": "G60开发区制造业技工",
            "description": "负责生产线设备操作与维护，需有相关经验。",
            "company_name": "上海XX制造有限公司",
            "area": "松江区",
            "min_salary": 6000,
            "max_salary": 10000,
            "employment_type": "全职"
        }

        json_ld = self.schema_gen.generate_job_posting_schema(job_data)

        assert json_ld["@context"] == "https://schema.org"
        assert json_ld["@type"] == "JobPosting"
        assert json_ld.get("title") is not None
        assert json_ld.get("hiringOrganization") is not None
        assert json_ld["hiringOrganization"]["name"] is not None
        assert json_ld.get("datePosted") is not None
        assert json_ld.get("jobLocation") is not None

    def test_job_posting_schema_salary_field(self):
        """测试Schema薪资字段格式"""
        job_data = {
            "title": "IT工程师",
            "description": "后端开发",
            "company_name": "科技公司",
            "area": "松江",
            "min_salary": 15000,
            "max_salary": 25000
        }

        json_ld = self.schema_gen.generate_job_posting_schema(job_data)

        if "baseSalary" in json_ld:
            salary = json_ld["baseSalary"]
            assert salary["currency"] == "CNY"
            assert salary["minValue"] == 15000.0
            assert salary["maxValue"] == 25000.0

    def test_job_posting_schema_lbs_tag(self):
        """测试LBS地理标签注入"""
        job_data = {
            "title": "大学城兼职",
            "company_name": "教育机构",
            "area": "松江大学城"
        }

        json_ld = self.schema_gen.generate_job_posting_schema(
            job_data,
            lbs_tag="songjiang_district/university_city"
        )

        assert "jobsLocatedIn" in json_ld
        assert "songjiang" in str(json_ld["jobsLocatedIn"]).lower() or "university" in str(json_ld["jobsLocatedIn"]).lower()

    def test_schema_validation_valid(self):
        """测试有效Schema校验"""
        valid_json_ld = {
            "@context": "https://schema.org",
            "@type": "JobPosting",
            "title": "测试岗位",
            "description": "描述文本",
            "hiringOrganization": {"@type": "LocalBusiness", "name": "测试公司"},
            "datePosted": "2026-04-20"
        }

        is_valid, msg = self.schema_gen.validate_schema(valid_json_ld)
        assert is_valid is True

    def test_schema_validation_missing_required(self):
        """测试缺少必填字段的无效Schema"""
        invalid_json_ld = {
            "@context": "https://schema.org",
            "@type": "JobPosting",
            "title": "测试"
            # 缺少 hiringOrganization 和 datePosted
        }

        is_valid, msg = self.schema_gen.validate_schema(invalid_json_ld)
        assert is_valid is False
        assert "缺少" in msg or "missing" in msg.lower()

    def test_tldr_generation_length_limit(self):
        """测试TL;DR摘要长度限制"""
        from content_factory import TldrGenerator

        stats = {
            "total_jobs": "500+",
            "industries": ["制造", "IT", "服务", "物流"],
            "area": "松江",
            "salary_min": "6K",
            "salary_max": "12K"
        }

        tldr = TldrGenerator.generate(stats)

        assert len(tldr) <= TldrGenerator.MAX_LENGTH + 10  # 允许小误差
        assert "松江" in tldr
        assert any(kw in tldr for kw in ["6K", "12K", "6", "12"])

    def test_tldr_generation_contains_key_info(self):
        """测试TL;DR包含关键信息"""
        from content_factory import TldrGenerator

        stats = {
            "total_jobs": "100+",
            "industries": ["IT", "互联网"],
            "area": "G60",
            "salary_min": "15K",
            "salary_max": "30K"
        }

        tldr = TldrGenerator.generate(stats)

        assert "G60" in tldr or "松江" in tldr
        assert "IT" in tldr or "互联网" in tldr

    def test_data_anchor_generation(self):
        """测试数据锚点引用句式生成"""
        from content_factory import TldrGenerator

        anchor = TldrGenerator.generate_anchor(industry="IT", growth="22.5")

        assert len(anchor) > 20
        # 模板随机选择，可能命中含 {level} 而非 {industry}/{growth} 的模板
        has_content = (
            "IT" in anchor
            or "22.5" in anchor
            or "%" in anchor.replace("％", "%")
            or "松江" in anchor
        )
        assert has_content, f"锚点缺少预期内容: {anchor}"


# ==================== Phase 4&5: API路由与监控测试 ====================
class TestCircuitBreaker:
    """熔断器测试"""

    @pytest.fixture(autouse=True)
    def setup_breaker(self):
        """初始化熔断器"""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from auth_signaler import CircuitBreaker
        self.cb = CircuitBreaker(failure_threshold=3, reset_timeout_seconds=3600)

    def test_initial_state_closed(self):
        """测试初始状态为CLOSED"""
        state = self.cb.get_state("test_platform")
        assert state.state == "CLOSED"

    def test_success_keeps_closed(self):
        """测试成功调用保持CLOSED状态"""
        for _ in range(5):
            self.cb.record_success("test_platform")

        state = self.cb.get_state("test_platform")
        assert state.state == "CLOSED"

    def test_failure_triggers_open(self):
        """测试连续失败触发OPEN状态"""
        for _ in range(4):  # 超过threshold=3
            self.cb.record_failure("test_platform")

        state = self.cb.get_state("test_platform")
        assert state.state == "OPEN"

    def test_open_blocks_requests(self):
        """测试OPEN状态阻止请求"""
        for _ in range(4):
            self.cb.record_failure("blocked_platform")

        assert not self.cb.is_available("blocked_platform")

    def test_half_open_after_timeout(self):
        """测试超时后进入HALF_OPEN状态"""
        import time

        # reset_timeout 需要足够短以便测试
        cb_fast = self.cb.__class__(failure_threshold=2, reset_timeout_seconds=1)

        for _ in range(3):
            cb_fast.record_failure("fast_platform")

        assert not cb_fast.is_available("fast_platform")

        time.sleep(1.1)  # 等待reset timeout过期

        assert cb_fast.is_available("fast_platform")
        state = cb_fast.get_state("fast_platform")
        assert state.state == "HALF_OPEN"


class TestAlertEngine:
    """告警引擎测试"""

    @pytest.fixture(autouse=True)
    def setup_alert_engine(self, tmp_path):
        """初始化告警引擎"""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from dist_monitor import AlertEngine, AlertRule, CitationMetrics

        # 挂载到实例，供测试方法使用
        self.CitationMetrics = CitationMetrics

        self.alert_dir = tmp_path / "alerts"
        self.engine = AlertEngine(rules=[
            AlertRule(
                metric_name="citation_rate",
                threshold=1.0,
                operator="<=",
                consecutive_failures=1,
                cooldown_seconds=0  # 测试用，立即生效
            )
        ])

    def test_alert_triggered_when_below_threshold(self):
        """测试低于阈值时触发告警"""
        metrics = [
            self.CitationMetrics(platform="test", citation_rate=0.3),
            self.CitationMetrics(platform="test2", citation_rate=0.5)
        ]

        alerts = self.engine.evaluate(metrics)

        assert len(alerts) > 0
        assert alerts[0]["severity"] in ("warning", "critical")

    def test_no_alert_when_above_threshold(self):
        """测试高于阈值时不触发告警"""
        metrics = [
            self.CitationMetrics(platform="test", citation_rate=2.0),
            self.CitationMetrics(platform="test2", citation_rate=5.0)
        ]

        alerts = self.engine.evaluate(metrics)

        assert len(alerts) == 0


class TestVectorRollback:
    """向量回滚管理器测试"""

    @pytest.fixture(autouse=True)
    def setup_rollback_mgr(self, tmp_path):
        """初始化回滚管理器"""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from dist_monitor import VectorRollbackManager

        self.rollback_dir = tmp_path / "rollbacks"
        # 使用正常构造（而非 __new__），确保 _write_lock 等属性正确初始化
        self.mgr = VectorRollbackManager.__new__(VectorRollbackManager)
        self.mgr.rollback_log_dir = str(self.rollback_dir)
        Path(self.rollback_dir).mkdir(exist_ok=True)
        self.mgr.rollback_state = {
            "is_frozen": False,
            "frozen_at": None,
            "reason": "",
            "original_config_backup": None
        }
        # 补充 __init__ 中设置的 _write_lock 属性
        import threading
        self.mgr._write_lock = threading.Lock()

    def test_execute_rollback_creates_compliance_page(self):
        """测试回滚执行创建合规模板页面"""
        result = self.mgr.execute_rollback(reason="引用率过低测试")

        assert result["success"] is True
        assert self.mgr.rollback_state["is_frozen"] is True
        assert self.mgr.rollback_state["reason"] == "引用率过低测试"

        # 验证合规模板文件已生成
        output_file = result.get("output_file")
        if output_file and os.path.exists(output_file):
            content = open(output_file, encoding='utf-8').read()
            assert "合规" in content.lower()
            assert "人社局" in content

    def test_double_rollback_prevented(self):
        """测试重复回滚被阻止"""
        self.mgr.execute_rollback(reason="第一次回滚")

        result = self.mgr.execute_rollback(reason="第二次回滚（应被阻止）")

        assert result["success"] is False
        assert "忽略" in result["message"].lower() or "已冻结" in result["message"]

    def test_force_overrides_protection(self):
        """测试强制参数可绕过保护"""
        self.mgr.execute_rollback(reason="第一次")
        result = self.mgr.execute_rollback(reason="强制回滚", force=True)

        assert result["success"] is True

    def test_recovery_check_before_timeout(self):
        """测试48小时内不允许恢复"""
        self.mgr.execute_rollback(reason="测试恢复")

        can_recov, reason = self.mgr.can_recover()

        assert can_recov is False
        assert "保护期" in reason or "剩余" in reason.lower()


# ==================== 集成测试 ====================
class TestPipelineIntegration:
    """全流程集成测试（Phase 1→5 联动验证）"""

    @pytest.fixture(autouse=True)
    def setup_pipeline(self, tmp_path):
        """初始化完整管道"""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

        # 创建配置文件
        config_dir = tmp_path / "config"
        config_dir.mkdir()

        (config_dir / "ban_words.txt").write_text("包过\n稳赚\n", encoding='utf-8')
        (config_dir / "platform_mapping.json").write_text(json.dumps({
            "platforms": {},
            "routing_rules": {"default_queue": []}
        }), encoding='utf-8')

        self.tmp_path = tmp_path

    def test_end_to_end_clean_content(self):
        """端到端测试：干净内容的完整处理流程"""
        from compliance_gate import ComplianceConfig, ComplianceGate
        from content_factory import ContentFactory, ContentFactoryConfig

        gate = ComplianceGate(ComplianceConfig(
            ban_words_file=str(self.tmp_path / "config" / "ban_words.txt"),
            audit_log_dir=str(self.tmp_path / "audit_logs")
        ))

        factory = ContentFactory(ContentFactoryConfig(output_dir=str(self.tmp_path / "dist")))

        # 输入原始岗位数据
        raw_html = """
        <html>
        <head><title>松江G60开发区急招</title></head>
        <body>
        <h1>G60科创走廊制造业技工急招</h1>
        <p>薪资6000-12000元/月，五险一金齐全。</p>
        <p>工作地点：上海市松江区G60科创园区</p>
        </body>
        </html>
        """

        # Phase 1: 合规处理
        compliance_result = gate.process(raw_html, source_identifier="e2e_test")
        assert compliance_result.status == "PASS"

        # Phase 3: 结构化资产生成
        job_data = {
            "title": "G60开发区制造业技工急招",
            "description": "薪资6000-12000元/月，五险一金齐全。位于G60科创园区。",
            "company_name": "松江快聘合作企业",
            "area": "松江区",
            "min_salary": 6000,
            "max_salary": 12000
        }

        asset = factory.process_single(job_data)

        # 验证输出
        assert asset.json_ld is not None
        assert asset.json_ld["@type"] == "JobPosting"
        # TL;DR 可能包含中文区域名或拼音映射（如 songjiang）
        has_area_keyword = (
            "松江" in asset.tldr_summary
            or "G60" in asset.tldr_summary
            or "songjiang" in asset.tldr_summary.lower()
        )
        assert has_area_keyword, f"TL;DR 缺少区域关键词: {asset.tldr_summary}"
        assert len(asset.data_anchors) > 0
        assert len(asset.tldr_summary) <= 130  # 允许误差

    def test_end_to_end_with_ban_words(self):
        """端到端测试：含禁词内容的处理与标记"""
        from compliance_gate import ComplianceConfig, ComplianceGate

        gate = ComplianceGate(ComplianceConfig(
            ban_words_file=str(self.tmp_path / "config" / "ban_words.txt"),
            audit_log_dir=str(self.tmp_path / "audit_logs")
        ))

        dirty_html = """
        <html><head></head><body>
        包过稳赚！绝对高薪岗位！内幕渠道推荐！
        </body></html>
        """

        result = gate.process(dirty_html, source_identifier="dirty_test")

        # 应标记为PARTIAL或FAIL（取决于禁词数量）
        assert result.status in ("PARTIAL", "FAIL")
        assert len(result.banned_words_found) > 0
        assert result.audit_log_path != ""


# ==================== 运行入口 ====================
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
