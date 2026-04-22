# -*- coding: utf-8 -*-
"""
GEO Pipeline 异常体系测试套件
=====================================

目标: 覆盖 exceptions.py 所有异常类的构造、序列化、继承关系
运行: uv run pytest tests/test_exceptions.py -v --tb=short
"""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from exceptions import (
    GEOError,
    DatabaseError,
    ConnectionFailedError,
    QueryExecutionError,
    TransactionRollbackError,
    ConfigurationError,
    ConfigFileNotFoundError,
    ConfigValidationError,
    ComplianceError,
    BanWordDetectedError,
    APIError,
    RateLimitedError,
    AuthenticationError,
    CircuitOpenError,
    ValidationError,
    InvalidJobDataError,
    InvalidParameterError,
)


class TestGEOError:
    """根异常类基础行为"""

    def test_default_message(self):
        e = GEOError()
        assert e.message == "未知错误"
        assert e.error_code == "GEO-000"

    def test_custom_message(self):
        e = GEOError("自定义错误")
        assert e.message == "自定义错误"
        assert str(e) == "自定义错误"

    def test_error_code_override(self):
        e = GEOError("msg", error_code="CUSTOM-001")
        assert e.error_code == "CUSTOM-001"

    def test_details_serialization(self):
        e = GEOError("msg", details={"key": "value", "count": 42})
        d = e.to_dict()
        assert d["error"] == "GEOError"
        assert d["error_code"] == "GEO-000"
        assert d["details"]["key"] == "value"
        assert d["details"]["count"] == 42

    def test_empty_details_omitted(self):
        e = GEOError("msg")
        d = e.to_dict()
        assert "details" not in d

    def test_is_exception_subclass(self):
        assert issubclass(GEOError, Exception)
        e = GEOError("test")
        with pytest.raises(GEOError):
            raise e


class TestExceptionHierarchy:
    """继承关系与error_code一致性"""

    _CODE_MAP = [
        (DatabaseError, "DB-000"), (ConnectionFailedError, "DB-001"),
        (QueryExecutionError, "DB-002"), (TransactionRollbackError, "DB-003"),
        (ConfigurationError, "CFG-000"), (ConfigFileNotFoundError, "CFG-001"),
        (ConfigValidationError, "CFG-002"),
        (ComplianceError, "CMP-000"), (BanWordDetectedError, "CMP-001"),
        (APIError, "API-000"), (RateLimitedError, "API-001"),
        (AuthenticationError, "API-002"), (CircuitOpenError, "API-003"),
        (ValidationError, "VAL-000"), (InvalidJobDataError, "VAL-001"),
        (InvalidParameterError, "VAL-002"),
    ]

    def test_error_code_defaults(self):
        """每个子类应具有唯一的默认error_code"""
        for exc_type, expected_code in self._CODE_MAP:
            instance = exc_type()
            assert instance.error_code == expected_code, \
                f"{exc_type.__name__} error_code: {instance.error_code} != {expected_code}"

    _INHERITANCE_MAP = [
        (ConnectionFailedError, DatabaseError), (QueryExecutionError, DatabaseError),
        (TransactionRollbackError, DatabaseError),
        (ConfigFileNotFoundError, ConfigurationError), (ConfigValidationError, ConfigurationError),
        (BanWordDetectedError, ComplianceError),
        (RateLimitedError, APIError), (AuthenticationError, APIError),
        (CircuitOpenError, APIError),
        (InvalidJobDataError, ValidationError), (InvalidParameterError, ValidationError),
    ]

    def test_inheritance_chain(self):
        """验证完整的MRO继承链: Child -> Parent -> GEOError -> Exception"""
        for child, parent in self._INHERITANCE_MAP:
            assert issubclass(child, parent)
            assert issubclass(child, GEOError)
            assert issubclass(child, Exception)

    def test_all_errors_inherit_from_geo_root(self):
        all_classes = [
            DatabaseError, ConnectionFailedError, QueryExecutionError, TransactionRollbackError,
            ConfigurationError, ConfigFileNotFoundError, ConfigValidationError,
            ComplianceError, BanWordDetectedError,
            APIError, RateLimitedError, AuthenticationError, CircuitOpenError,
            ValidationError, InvalidJobDataError, InvalidParameterError,
        ]
        for cls in all_classes:
            assert issubclass(cls, GEOError), f"{cls.__name__} 不继承自 GEOError"


class TestCatchByParentType:
    """多态捕获: 子类异常可被父类型except捕获"""

    def test_catch_db_error_by_geo(self):
        with pytest.raises(GEOError):
            raise ConnectionFailedError("连接失败")

    def test_catch_connection_failed_by_db(self):
        with pytest.raises(DatabaseError):
            raise ConnectionFailedError("连接失败")

    def test_catch_ban_word_by_compliance(self):
        with pytest.raises(ComplianceError):
            raise BanWordDetectedError("检测到禁词: 包过")

    def test_catch_rate_limit_by_api(self):
        with pytest.raises(APIError):
            raise RateLimitedError("速率限制: 请在60s后重试")

    def test_catch_invalid_job_by_validation(self):
        with pytest.raises(ValidationError):
            raise InvalidJobDataError("岗位数据无效: title不能为空")


class TestToDictConsistency:
    """to_dict() 序列化格式验证"""

    def test_required_fields_present(self):
        for cls in [ConnectionFailedError, ConfigValidationError, BanWordDetectedError]:
            e = cls("test msg")
            d = e.to_dict()
            assert "error" in d
            assert "error_code" in d
            assert "message" in d
            assert d["message"] == "test msg"

    def test_class_name_in_output(self):
        e1 = BanWordDetectedError("x")
        e2 = CircuitOpenError("y")
        assert e1.to_dict()["error"] == "BanWordDetectedError"
        assert e2.to_dict()["error"] == "CircuitOpenError"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
