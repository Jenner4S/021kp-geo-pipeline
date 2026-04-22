# -*- coding: utf-8 -*-
"""
Exceptions 完整测试套件
========================

覆盖范围:
- GEOError 基类及 to_dict()
- DatabaseError 层次结构
- ConfigurationError 层次结构
- ComplianceError 层次结构
- APIError 层次结构 (含 CircuitOpenError)
- ValidationError 层次结构
- 错误码唯一性与继承链
- 序列化格式验证

Author: GEO-Test Suite | Date: 2026-04-21
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import pytest


class TestGEOErrorBase:
    """GEOError 基类测试"""

    def test_default_message(self):
        from exceptions import GEOError
        err = GEOError()
        assert err.message == "未知错误"
        assert str(err) == "未知错误"

    def test_custom_message(self):
        from exceptions import GEOError
        err = GEOError("数据库连接超时")
        assert err.message == "数据库连接超时"
        assert str(err) == "数据库连接超时"

    def test_default_error_code(self):
        from exceptions import GEOError
        err = GEOError()
        assert err.error_code == "GEO-000"

    def test_custom_error_code(self):
        from exceptions import GEOError
        err = GEOError(error_code="CUSTOM-001")
        assert err.error_code == "CUSTOM-001"

    def test_details_default_empty(self):
        from exceptions import GEOError
        err = GEOError()
        assert err.details == {}

    def test_details_with_context(self):
        from exceptions import GEOError
        err = GEOError(details={"host": "db.example.com", "port": 3306})
        assert err.details == {"host": "db.example.com", "port": 3306}

    def test_is_exception_subclass(self):
        from exceptions import GEOError
        assert issubclass(GEOError, Exception)
        
        err = GEOError("test")
        with pytest.raises(GEOError):
            raise err

    def test_catch_with_base_class(self):
        """可以用 GEOError 捕获所有子类"""
        from exceptions import GEOError, ConnectionFailedError
        with pytest.raises(GEOError):
            raise ConnectionFailedError("连接失败")

    def test_to_dict_basic(self):
        from exceptions import GEOError
        err = GEOError(message="测试错误", error_code="TEST-001")
        d = err.to_dict()
        assert d["error"] == "GEOError"
        assert d["error_code"] == "TEST-001"
        assert d["message"] == "测试错误"

    def test_to_dict_with_details(self):
        from exceptions import GEOError
        err = GEOError(
            message="查询执行错误",
            error_code="DB-002",
            details={"sql": "SELECT * FROM jobs", "row_count": 0}
        )
        d = err.to_dict()
        assert d["details"]["sql"] == "SELECT * FROM jobs"
        assert d["details"]["row_count"] == 0

    def test_to_dict_no_details_key_when_empty(self):
        """details 为空时不输出 details 键"""
        from exceptions import GEOError
        err = GEOError(message="简单错误")
        d = err.to_dict()
        assert "details" not in d


class TestDatabaseErrors:
    """数据库错误层次结构测试"""

    def test_database_error_inherits_geo(self):
        from exceptions import DatabaseError, GEOError
        assert issubclass(DatabaseError, GEOError)

    def test_database_error_default_code(self):
        from exceptions import DatabaseError
        err = DatabaseError()
        assert err.error_code == "DB-000"

    def test_connection_failed_error(self):
        from exceptions import ConnectionFailedError
        err = ConnectionFailedError("无法连接到 MySQL")
        assert err.error_code == "DB-001"
        assert err.message == "无法连接到 MySQL"
        assert "ConnectionFailedError" in err.to_dict()["error"]

    def test_query_execution_error(self):
        from exceptions import QueryExecutionError
        err = QueryExecutionError("语法错误 near 'FROM'")
        assert err.error_code == "DB-002"
        assert "语法错误" in err.message

    def test_transaction_rollback_error(self):
        from exceptions import TransactionRollbackError
        err = TransactionRollbackError("死锁检测触发回滚")
        assert err.error_code == "DB-003"


class TestConfigurationErrors:
    """配置错误层次结构测试"""

    def test_configuration_error_inherits_geo(self):
        from exceptions import ConfigurationError, GEOError
        assert issubclass(ConfigurationError, GEOError)

    def test_config_not_found_error(self):
        from exceptions import ConfigFileNotFoundError
        err = ConfigFileNotFoundError("settings.yaml 不存在")
        assert err.error_code == "CFG-001"

    def test_config_validation_error(self):
        from exceptions import ConfigValidationError
        err = ConfigValidationError("端口号必须在 1-65535 范围内")
        assert err.error_code == "CFG-002"


class TestComplianceErrors:
    """合规错误层次结构测试"""

    def test_compliance_error_inherits_geo(self):
        from exceptions import ComplianceError, GEOError
        assert issubclass(ComplianceError, GEOError)

    def test_ban_word_detected_error(self):
        from exceptions import BanWordDetectedError
        err = BanWordDetectedError("内容包含禁词: 赚钱")
        assert err.error_code == "CMP-001"


class TestAPIErrors:
    """API 错误层次结构测试"""

    def test_api_error_inherits_geo(self):
        from exceptions import APIError, GEOError
        assert issubclass(APIError, GEOError)

    def test_rate_limited_error(self):
        from exceptions import RateLimitedError
        err = RateLimitedError("请求频率超过限制 (30/min)")
        assert err.error_code == "API-001"

    def test_authentication_error(self):
        from exceptions import AuthenticationError
        err = AuthenticationError("微信 AppID 或 AppSecret 无效")
        assert err.error_code == "API-002"

    def test_circuit_open_error(self):
        from exceptions import CircuitOpenError
        err = CircuitOpenError("熔断器已打开 - 微信平台不可用")
        assert err.error_code == "API-003"


class TestValidationErrors:
    """验证错误层次结构测试"""

    def test_validation_error_inherits_geo(self):
        from exceptions import ValidationError, GEOError
        assert issubclass(ValidationError, GEOError)

    def test_invalid_job_data_error(self):
        from exceptions import InvalidJobDataError
        err = InvalidJobDataError("岗位数据缺少必填字段: title")
        assert err.error_code == "VAL-001"

    def test_invalid_parameter_error(self):
        from exceptions import InvalidParameterError
        err = InvalidParameterError("limit 参数必须为正整数")
        assert err.error_code == "VAL-002"


class TestErrorCodeUniqueness:
    """错误码唯一性测试"""

    def test_all_error_codes_unique(self):
        """所有异常类的 error_code 必须唯一"""
        import exceptions as exc_module
        
        error_classes = [
            exc_module.GEOError,
            exc_module.DatabaseError,
            exc_module.ConnectionFailedError,
            exc_module.QueryExecutionError,
            exc_module.TransactionRollbackError,
            exc_module.ConfigurationError,
            exc_module.ConfigFileNotFoundError,
            exc_module.ConfigValidationError,
            exc_module.ComplianceError,
            exc_module.BanWordDetectedError,
            exc_module.APIError,
            exc_module.RateLimitedError,
            exc_module.AuthenticationError,
            exc_module.CircuitOpenError,
            exc_module.ValidationError,
            exc_module.InvalidJobDataError,
            exc_module.InvalidParameterError,
        ]
        
        codes = [cls.error_code for cls in error_classes]
        assert len(codes) == len(set(codes)), f"重复的错误码: {codes}"

    def test_error_code_naming_convention(self):
        """错误码遵循 MODULE-NNN 格式"""
        import re
        import exceptions as exc_module
        
        for cls_name in dir(exc_module):
            cls = getattr(exc_module, cls_name)
            if (isinstance(cls, type) and 
                issubclass(cls, Exception) and 
                cls is not Exception and
                hasattr(cls, 'error_code')):
                
                code = cls.error_code
                assert re.match(r'^[A-Z]+-\d{3}$', code), \
                    f"{cls_name}.error_code '{code}' 格式不符合 MODULE-NNN"


class TestExceptionChaining:
    """异常链测试"""

    def test_raise_from(self):
        """支持异常链 (raise ... from ...)"""
        from exceptions import ConnectionFailedError
        try:
            try:
                raise OSError("Network unreachable")
            except OSError as e:
                raise ConnectionFailedError("数据库不可达") from e
        except ConnectionFailedError as e:
            assert e.__cause__ is not None
            assert "Network unreachable" in str(e.__cause__)

    def test_multiple_exception_attrs(self):
        """异常对象可以携带多个属性"""
        from exceptions import GEOError
        err = GEOError(
            message="复杂错误",
            error_code="COMP-001",
            details={
                "component": "content_factory",
                "job_id": "job_123",
                "phase": 3
            }
        )
        assert err.details["component"] == "content_factory"
        assert err.details["job_id"] == "job_123"


class TestRealWorldScenarios:
    """真实场景异常构建示例"""

    def test_full_database_error_scenario(self):
        """完整数据库错误场景"""
        from exceptions import ConnectionFailedError
        err = ConnectionFailedError(
            message="无法建立数据库连接池",
            details={
                "host": "prod-db.internal",
                "port": 3306,
                "timeout_seconds": 30,
                "pool_size": 10
            }
        )
        d = err.to_dict()
        assert d["error"] == "ConnectionFailedError"
        assert d["error_code"] == "DB-001"
        assert d["details"]["host"] == "prod-db.internal"

    def test_compliance_rejection_scenario(self):
        """合规拦截场景"""
        from exceptions import BanWordDetectedError
        err = BanWordDetectedError(
            message="命中禁词: ['赚大钱', '日入过万']",
            details={
                "ban_words_found": ["赚大钱", "日入过万"],
                "job_id": "job_xyz",
                "threshold": 5,
                "count": 2
            }
        )
        d = err.to_dict()
        assert d["error_code"] == "CMP-001"
        assert len(d["details"]["ban_words_found"]) == 2

    def test_circuit_breaker_open_scenario(self):
        """熔断器打开场景"""
        from exceptions import CircuitOpenError
        err = CircuitOpenError(
            message="微信平台连续3次调用失败，已触发熔断",
            details={
                "platform": "wechat",
                "consecutive_failures": 3,
                "threshold": 3,
                "last_error": "errcode: 40013 invalid appid",
                "auto_recovery_at": "2026-04-22T06:00:00"
            }
        )
        d = err.to_dict()
        assert d["error_code"] == "API-003"
        assert d["details"]["platform"] == "wechat"


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
