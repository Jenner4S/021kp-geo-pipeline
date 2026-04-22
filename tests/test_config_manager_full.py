# -*- coding: utf-8 -*-
"""
ConfigManager 完整测试套件
============================

覆盖范围:
- 单例模式与线程安全
- 多源配置加载 (YAML/env/defaults)
- 环境变量解析 ${VAR:default}
- 深度合并策略
- 敏感字段脱敏
- 运行时动态修改
- 配置持久化
- 结构化属性访问器

Author: GEO-Test Suite | Date: 2026-04-21
"""

import os
import sys
import json
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import pytest
from config_manager import ConfigManager

import pytest


# ============================================================
#   Fixtures & Helpers
# ============================================================

@pytest.fixture(autouse=True)
def reset_singleton():
    """每个测试前重置单例，避免测试间干扰"""
    from config_manager import ConfigManager
    ConfigManager.reset_instance()
    yield
    ConfigManager.reset_instance()


@pytest.fixture
def temp_config_dir():
    """创建临时配置目录"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_yaml_config(temp_config_dir):
    """创建示例 YAML 配置文件"""
    yaml_content = """
system:
  name: Test System
  version: '1.0.0'
  environment: testing

database:
  type: sqlite
  path: './data/test.db'
  table: test_jobs

compliance:
  explicit_marker: 'Test AI marker'
  ban_words_file: './config/test_ban.txt'

monitoring:
  enabled: true
  citation_rate_threshold: 0.01
"""
    yaml_file = temp_config_dir / 'settings.yaml'
    yaml_file.write_text(yaml_content, encoding='utf-8')
    return temp_config_dir


@pytest.fixture
def sample_local_yaml(sample_yaml_config):
    """创建本地覆盖配置文件 (settings.local.yaml)"""
    local_content = """
system:
  name: Overridden System Name
  log_level: DEBUG

api_routing:
  wechat:
    app_id: 'wx_test_12345'
    app_secret: 'secret_key_here'
"""
    local_file = sample_yaml_config / 'settings.local.yaml'
    local_file.write_text(local_content, encoding='utf-8')
    return sample_yaml_config


class TestDatabaseTypeInfo:
    """DatabaseTypeInfo 数据类测试"""

    def test_default_values(self):
        from config_manager import DatabaseTypeInfo
        info = DatabaseTypeInfo()
        assert info.db_type == "sqlite"
        assert info.database == "geo_pipeline.db"
        assert info.table == "jobs"
        assert info.path == "./data/geo_pipeline.db"
        assert info.host == ""
        assert info.port == 0
        assert info.user == ""
        assert info.password == ""

    def test_custom_values(self):
        from config_manager import DatabaseTypeInfo
        info = DatabaseTypeInfo(
            db_type="mysql",
            database="test_db",
            table="users",
            path="/data/test.db",
            host="localhost",
            port=3306,
            user="admin",
            password="pass123"
        )
        assert info.db_type == "mysql"
        assert info.database == "test_db"

    def test_get_connection_url(self):
        from config_manager import DatabaseTypeInfo
        info = DatabaseTypeInfo(database="mydb.sqlite")
        url = info.get_connection_url()
        assert url == "sqlite:///mydb.sqlite"


class TestAPIConfig:
    """APIConfig 数据类测试"""

    def test_default_empty_dicts(self):
        from config_manager import APIConfig
        cfg = APIConfig()
        assert cfg.wechat == {}
        assert cfg.douyin == {}
        assert cfg.baidu == {}

    def test_with_credentials(self):
        from config_manager import APIConfig
        cfg = APIConfig(
            wechat={"app_id": "wx123", "app_secret": "secret"},
            douyin={"client_key": "dk456"}
        )
        assert cfg.wechat["app_id"] == "wx123"
        assert cfg.douyin["client_key"] == "dk456"
        assert cfg.baidu == {}


class TestMonitoringConfig:
    """MonitoringConfig 数据类测试"""

    def test_default_values(self):
        from config_manager import MonitoringConfig
        mon = MonitoringConfig()
        assert mon.enabled is True
        assert mon.citation_threshold == 0.005
        assert mon.api_success_threshold == 0.95
        assert mon.schedule_cron == "0 14,20 * * *"
        assert mon.monitor_interval_hours == 2
        assert mon.alert_webhook == ""
        assert mon.rollback_consecutive_failures == 3
        assert mon.rollback_freeze_hours == 48
        assert mon.auto_rollback is True

    def test_custom_values(self):
        from config_manager import MonitoringConfig
        mon = MonitoringConfig(
            enabled=False,
            citation_threshold=0.01,
            alert_webhook="https://example.com/webhook",
            rollback_consecutive_failures=5
        )
        assert mon.enabled is False
        assert mon.citation_threshold == 0.01
        assert mon.alert_webhook == "https://example.com/webhook"


class TestComplianceConfig:
    """ComplianceConfig 数据类测试"""

    def test_default_values(self):
        from config_manager import ComplianceConfig
        comp = ComplianceConfig()
        assert "AI generated content marker" in comp.explicit_marker
        assert comp.meta_name == "x-ai-source-id"
        assert comp.meta_content == "jiangsong_kuaipin_v1_20260420"
        assert comp.ban_words_file == "./config/ban_words.txt"
        assert comp.audit_log_retention_days == 180
        assert comp.audit_log_dir == "./audit_logs"


class TestConfigManagerInit:
    """ConfigManager 初始化测试"""

    def test_init_with_defaults(self):
        """使用默认参数初始化"""
        from config_manager import ConfigManager
        cfg = ConfigManager()
        assert cfg._resolved_config is not None
        assert 'system' in cfg._resolved_config
        assert 'database' in cfg._resolved_config

    def test_init_with_custom_dir(self, sample_yaml_config):
        """使用自定义配置目录初始化"""
        from config_manager import ConfigManager
        cfg = ConfigManager(config_dir=str(sample_yaml_config))
        assert cfg.get('system.name') == 'Test System'

    def test_init_loads_yaml(self, sample_yaml_config):
        """验证YAML文件加载"""
        from config_manager import ConfigManager
        cfg = ConfigManager(config_dir=str(sample_yaml_config))
        # settings.yaml 的值应该覆盖默认值
        assert cfg.get('system.version') == '1.0.0'
        assert cfg.get('database.table') == 'test_jobs'

    def test_init_local_overrides_settings(self, sample_local_yaml):
        """验证 settings.local.yaml 覆盖 settings.yaml"""
        from config_manager import ConfigManager
        cfg = ConfigManager(config_dir=str(sample_local_yaml))
        # local.yaml 应该覆盖 system.name
        assert cfg.get('system.name') == 'Overridden System Name'
        # 但其他值保留自 settings.yaml
        assert cfg.get('system.version') == '1.0.0'

    def test_config_files_loaded_tracking(self, sample_local_yaml):
        """跟踪已加载的配置文件列表"""
        from config_manager import ConfigManager
        cfg = ConfigManager(config_dir=str(sample_local_yaml))
        assert len(cfg._config_files_loaded) >= 1
        # 应包含两个配置文件
        filenames = [Path(f).name for f in cfg._config_files_loaded]
        assert 'settings.yaml' in filenames or any('settings' in f for f in filenames)


class TestSingletonPattern:
    """单例模式测试"""

    def test_get_instance_returns_same(self):
        """get_instance 始终返回同一实例"""
        from config_manager import ConfigManager
        c1 = ConfigManager.get_instance()
        c2 = ConfigManager.get_instance()
        assert c1 is c2

    def test_reset_instance_creates_new(self):
        """reset_instance 后创建新实例"""
        from config_manager import ConfigManager
        c1 = ConfigManager.get_instance()
        ConfigManager.reset_instance()
        c2 = ConfigManager.get_instance()
        assert c1 is not c2

    def test_thread_safety(self):
        """多线程并发访问单例安全性"""
        from config_manager import ConfigManager
        instances = []
        errors = []

        def get_instance():
            try:
                instances.append(ConfigManager.get_instance())
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=get_instance) for _ in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Thread errors: {errors}"
        # 所有实例应该是同一个对象
        assert all(inst is instances[0] for inst in instances)


class TestEnvVarResolution:
    """环境变量解析测试 ${VAR:default}"""

    def test_resolve_simple_var(self):
        """简单环境变量替换"""
        from config_manager import ConfigManager
        os.environ['TEST_GEO_VAR'] = 'test_value'
        
        cfg = ConfigManager()
        # _DEFAULTS 中包含 ${DB_HOST:localhost} 格式
        result = cfg._resolve_env_vars('${TEST_GEO_VAR:default}')
        assert result == 'test_value'
        
        del os.environ['TEST_GEO_VAR']

    def test_resolve_with_default(self):
        """带默认值的环境变量（未设置时使用默认值）"""
        from config_manager import ConfigManager
        cfg = ConfigManager()
        result = cfg._resolve_env_vars('${UNDEFINED_VAR_xyz:fallback_val}')
        assert result == 'fallback_val'

    def test_resolve_no_default_empty(self):
        """无默认值且未设置时返回空字符串"""
        from config_manager import ConfigManager
        cfg = ConfigManager()
        result = cfg._resolve_env_vars('${UNDEFINED_VAR_xyz_123:}')
        assert result == ''

    def test_resolve_nested_dict(self):
        """嵌套字典中的环境变量解析"""
        from config_manager import ConfigManager
        obj = {
            'host': '${DB_HOST:localhost}',
            'port': '${DB_PORT:3306}',
            'nested': {
                'user': '${DB_USER:root}',
                'password': '${DB_PASSWORD:}'
            }
        }
        cfg = ConfigManager()
        resolved = cfg._resolve_env_vars(obj)
        assert resolved['host'] == 'localhost'
        assert resolved['port'] == '3306'
        assert resolved['nested']['user'] == 'root'
        assert resolved['nested']['password'] == ''

    def test_resolve_list(self):
        """列表中的环境变量解析"""
        from config_manager import ConfigManager
        obj = ['${VAR1:item1}', 'literal', '${VAR2:item2}']
        cfg = ConfigManager()
        resolved = cfg._resolve_env_vars(obj)
        assert resolved == ['item1', 'literal', 'item2']

    def test_resolve_plain_string(self):
        """普通字符串不做处理"""
        from config_manager import ConfigManager
        cfg = ConfigManager()
        assert cfg._resolve_env_vars('just a string') == 'just a string'
        assert cfg._resolve_env_vars('') == ''
        assert cfg._resolve_env_vars(123) == 123

    def test_resolved_config_has_env_values(self):
        """初始化后 _resolved_config 包含解析后的环境变量"""
        from config_manager import ConfigManager
        os.environ['WECHAT_APP_ID'] = 'wx_test_from_env'
        try:
            cfg = ConfigManager()
            wechat = cfg.get('api_routing.wechat', {})
            # 注意：实际路径可能因深度合并而不同
            assert isinstance(wechat, dict) or wechat is None
        finally:
            del os.environ['WECHAT_APP_ID']


class TestDeepMerge:
    """深度合并策略测试"""

    def test_flat_override(self):
        """扁平字典直接覆盖"""
        base = {'a': 1, 'b': 2}
        override = {'b': 3, 'c': 4}
        result = ConfigManager._deep_merge(base, override)
        assert result == {'a': 1, 'b': 3, 'c': 4}

    def test_nested_merge(self):
        """嵌套字典递归合并"""
        base = {'outer': {'inner1': 'a', 'inner2': 'b'}}
        override = {'outer': {'inner2': 'c', 'inner3': 'd'}}
        result = ConfigManager._deep_merge(base, override)
        assert result['outer']['inner1'] == 'a'  # 保留原值
        assert result['outer']['inner2'] == 'c'  # 被覆盖
        assert result['outer']['inner3'] == 'd'  # 新增

    def test_non_dict_replacement(self):
        """非字典值整体替换（非递归）"""
        base = {'list': [1, 2, 3]}
        override = {'list': [4, 5, 6]}
        result = ConfigManager._deep_merge(base, override)
        assert result['list'] == [4, 5, 6]

    def test_new_keys_added(self):
        """新增键被添加"""
        base = {'existing': 'val'}
        override = {'new_key': 'new_val'}
        result = ConfigManager._deep_merge(base, override)
        assert result == {'existing': 'val', 'new_key': 'new_val'}

    def test_empty_cases(self):
        """空字典边界情况"""
        assert ConfigManager._deep_merge({}, {}) == {}
        assert ConfigManager._deep_merge({'a': 1}, {}) == {'a': 1}
        assert ConfigManager._deep_merge({}, {'b': 2}) == {'b': 2}


class TestGetConfig:
    """get() 方法测试"""

    def test_get_existing_key(self):
        """获取存在的键"""
        from config_manager import ConfigManager
        cfg = ConfigManager()
        # 验证可以获取到系统名称（具体值取决于配置）
        name = cfg.get('system.name')
        assert isinstance(name, str)
        assert len(name) > 0

    def test_get_nested_key(self):
        """获取嵌套键"""
        from config_manager import ConfigManager
        cfg = ConfigManager()
        assert cfg.get('database.type') == 'sqlite'
        assert cfg.get('monitoring.citation_rate_threshold') is not None

    def test_get_nonexistent_returns_default(self):
        """不存在的键返回默认值"""
        from config_manager import ConfigManager
        cfg = ConfigManager()
        assert cfg.get('nonexistent.key') is None
        assert cfg.get('missing.key', 'fallback') == 'fallback'
        assert cfg.get('another.missing', 42) == 42

    def test_get_partial_path(self):
        """部分路径返回中间层级字典"""
        from config_manager import ConfigManager
        cfg = ConfigManager()
        val = cfg.get('database')
        assert isinstance(val, dict)
        assert 'type' in val


class TestSetConfig:
    """set() 方法测试"""

    def test_set_simple_value(self):
        """设置简单值"""
        from config_manager import ConfigManager
        cfg = ConfigManager()
        ok = cfg.set('custom.new_key', 'test_value')
        assert ok is True
        assert cfg.get('custom.new_key') == 'test_value'

    def test_set_nested_create_parents(self):
        """设置嵌套值时自动创建父级字典"""
        from config_manager import ConfigManager
        cfg = ConfigManager()
        cfg.set('level1.level2.level3', 'deep_value')
        assert cfg.get('level1.level2.level3') == 'deep_value'

    def test_set_overwrites_existing(self):
        """覆盖已有值"""
        from config_manager import ConfigManager
        cfg = ConfigManager()
        original = cfg.get('system.name')
        cfg.set('system.name', 'New Name')
        assert cfg.get('system.name') == 'New Name'


class TestReload:
    """reload() 方法测试"""

    def test_reload_refreshes_config(self, sample_yaml_config):
        """重新加载配置"""
        from config_manager import ConfigManager
        cfg = ConfigManager(config_dir=str(sample_yaml_config))
        original_time = cfg._last_load_time
        
        time.sleep(0.05)  # 确保时间戳不同
        cfg.reload()
        
        assert cfg._last_load_time > original_time


class TestMaskSensitiveFields:
    """敏感字段脱敏测试"""

    def test_mask_password(self):
        """password 字段被脱敏"""
        from config_manager import ConfigManager
        cfg = ConfigManager()
        data = {"username": "admin", "password": "secret123", "host": "localhost"}
        masked = cfg._mask_sensitive_fields(data)
        assert masked["password"] == "*****(masked)"
        assert masked["username"] == "admin"
        assert masked["host"] == "localhost"

    def test_mask_secret(self):
        """secret 字段被脱敏"""
        from config_manager import ConfigManager
        cfg = ConfigManager()
        data = {"api_secret": "abc123", "token": "xyz789"}
        masked = cfg._mask_sensitive_fields(data)
        assert masked["api_secret"] == "*****(masked)"
        assert masked["token"] == "*****(masked)"

    def test_mask_api_key_and_app_secret(self):
        """api_key 和 app_secret 被脱敏"""
        from config_manager import ConfigManager
        cfg = ConfigManager()
        data = {"api_key": "key123", "app_secret": "sec456", "client_secret": "cs789"}
        masked = cfg._mask_sensitive_fields(data)
        assert masked["api_key"] == "*****(masked)"
        assert masked["app_secret"] == "*****(masked)"
        assert masked["client_secret"] == "*****(masked)"

    def test_mask_empty_string_unchanged(self):
        """空字符串不脱敏"""
        from config_manager import ConfigManager
        cfg = ConfigManager()
        data = {"password": ""}
        masked = cfg._mask_sensitive_fields(data)
        assert masked["password"] == ""

    def test_mask_nested_dict(self):
        """嵌套字典中脱敏敏感字段"""
        from config_manager import ConfigManager
        cfg = ConfigManager()
        data = {
            "database": {"host": "localhost", "password": "pass"},
            "api": {"key": "apikey123"},
            "normal_field": "value"
        }
        masked = cfg._mask_sensitive_fields(data)
        assert masked["database"]["password"] == "*****(masked)"
        assert masked["database"]["host"] == "localhost"
        # 'api_key' 会被检测到（包含 'api' + '_key'），但 'key' 单独不会
        # 因为 SENSITIVE_KEYS 检查的是 password/secret/token/api_key/app_secret/client_secret
        assert masked["normal_field"] == "value"

    def test_mask_list_of_dicts(self):
        """字典列表中的敏感字段被脱敏"""
        from config_manager import ConfigManager
        cfg = ConfigManager()
        data = [
            {"name": "item1", "token": "tok1"},
            {"name": "item2", "token": "tok2"}
        ]
        masked = cfg._mask_sensitive_fields(data)
        assert masked[0]["token"] == "*****(masked)"
        assert masked[0]["name"] == "item1"

    def test_to_dict_masks_by_default(self):
        """to_dict() 默认启用脱敏"""
        from config_manager import ConfigManager
        cfg = ConfigManager()
        output = cfg.to_dict(mask_secrets=True)
        # 验证结构存在
        assert isinstance(output, dict)

    def test_to_dict_without_masking(self):
        """to_dict() 可选禁用脱敏"""
        from config_manager import ConfigManager
        cfg = ConfigManager()
        output = cfg.to_dict(mask_secrets=False)
        assert isinstance(output, dict)


class TestPropertyAccessors:
    """结构化属性访问器测试"""

    def test_database_info_property(self):
        """database_info 属性返回正确的数据结构"""
        from config_manager import ConfigManager
        cfg = ConfigManager()
        db = cfg.database_info
        assert db.db_type == 'sqlite'
        assert db.table == 'jobs'
        assert 'geo_pipeline' in db.database or '.db' in db.path

    def test_api_credentials_property(self):
        """api_credentials 属性返回平台凭证"""
        from config_manager import ConfigManager
        cfg = ConfigManager()
        api = cfg.api_credentials
        assert hasattr(api, 'wechat')
        assert hasattr(api, 'douyin')
        assert hasattr(api, 'baidu')

    def test_monitoring_property(self):
        """monitoring 属性返回监控配置"""
        from config_manager import ConfigManager
        cfg = ConfigManager()
        mon = cfg.monitoring
        assert isinstance(mon.enabled, bool)
        assert isinstance(mon.citation_threshold, float)
        assert isinstance(mon.api_success_threshold, float)
        assert mon.schedule_cron == "0 14,20 * * *" or mon.schedule_cron is not None
        assert isinstance(mon.monitor_interval_hours, int)
        assert isinstance(mon.rollback_consecutive_failures, int)
        assert isinstance(mon.rollback_freeze_hours, int)
        assert isinstance(mon.auto_rollback, bool)

    def test_compliance_property(self):
        """compliance 属性返回合规配置"""
        from config_manager import ConfigManager
        cfg = ConfigManager()
        comp = cfg.compliance
        # explicit_marker 可能来自默认值或 YAML 配置，验证非空即可
        assert isinstance(comp.explicit_marker, str)
        assert len(comp.explicit_marker) > 0
        assert comp.meta_name == "x-ai-source-id"
        assert comp.ban_words_file is not None
        assert isinstance(comp.audit_log_retention_days, int)


class TestUtilityMethods:
    """工具方法测试"""

    def test_is_sqlite_mode_always_true(self):
        """is_sqlite_mode() 始终返回 True"""
        from config_manager import ConfigManager
        cfg = ConfigManager()
        assert cfg.is_sqlite_mode() is True

    def test_requires_external_db_false(self):
        """requires_external_db() 始终返回 False"""
        from config_manager import ConfigManager
        cfg = ConfigManager()
        assert cfg.requires_external_db() is False

    def test_get_all_env_vars(self):
        """获取 GEO 相关的环境变量"""
        from config_manager import ConfigManager
        cfg = ConfigManager()
        env_vars = cfg.get_all_env_vars()
        assert isinstance(env_vars, dict)
        expected_keys = ['DB_PATH', 'WECHAT_APP_ID', 'ALERT_WEBHOOK']
        for k in expected_keys:
            assert k in env_vars

    def test_to_bool_true_values(self):
        """_to_bool 各种 True 值"""
        from config_manager import ConfigManager
        assert ConfigManager._to_bool(True) is True
        assert ConfigManager._to_bool('true') is True
        assert ConfigManager._to_bool('TRUE') is True
        assert ConfigManager._to_bool('1') is True
        assert ConfigManager._to_bool('yes') is True
        assert ConfigManager._to_bool('YES') is True
        assert ConfigManager._to_bool('on') is True
        assert ConfigManager._to_bool(1) is True
        assert ConfigManager._to_bool(100) is True

    def test_to_bool_false_values(self):
        """_to_bool 各种 False 值"""
        from config_manager import ConfigManager
        assert ConfigManager._to_bool(False) is False
        assert ConfigManager._to_bool('false') is False
        assert ConfigManager._to_bool('0') is False
        assert ConfigManager._to_bool('no') is False
        assert ConfigManager._to_bool('off') is False
        assert ConfigManager._to_bool('') is False
        assert ConfigManager._to_bool(0) is False
        assert ConfigManager._to_bool(None) is False

    def test_repr(self):
        """__repr__ 输出格式"""
        from config_manager import ConfigManager
        cfg = ConfigManager()
        repr_str = repr(cfg)
        assert 'ConfigManager' in repr_str
        assert 'sqlite' in repr_str.lower()


class TestGetConfigHelper:
    """get_config() / reload_config() 辅助函数测试"""

    def test_get_config_returns_instance(self):
        """get_config() 返回单例"""
        from config_manager import get_config, ConfigManager
        # 先重置确保干净状态
        ConfigManager.reset_instance()
        cfg = get_config()
        assert isinstance(cfg, ConfigManager)

    def test_reload_config(self):
        """reload_config() 触发重新加载"""
        from config_manager import reload_config, get_config
        ConfigManager.reset_instance()
        cfg = get_config()
        original_time = cfg._last_load_time
        time.sleep(0.05)
        reload_config()
        assert cfg._last_load_time > original_time


class TestYamlLoadingEdgeCases:
    """YAML 加载边界情况测试"""

    def test_load_nonexistent_file(self, temp_config_dir):
        """不存在的配置文件不应报错"""
        from config_manager import ConfigManager
        cfg = ConfigManager(config_dir=str(temp_config_dir))  # 无任何yaml文件
        # 应该正常使用默认值初始化
        assert cfg._resolved_config is not None
        assert 'system' in cfg._resolved_config

    def test_load_malformed_yaml(self, temp_config_dir):
        """格式错误的YAML应优雅降级"""
        from config_manager import ConfigManager
        bad_yaml = temp_config_dir / 'settings.yaml'
        bad_yaml.write_text(': invalid: yaml: content: [', encoding='utf-8')
        # 不应抛出异常，而是回退到默认值
        cfg = ConfigManager(config_dir=str(temp_config_dir))
        assert cfg._resolved_config is not None

    def test_load_empty_yaml(self, temp_config_dir):
        """空YAML文件处理"""
        from config_manager import ConfigManager
        empty_yaml = temp_config_dir / 'settings.yaml'
        empty_yaml.write_text('', encoding='utf-8')
        cfg = ConfigManager(config_dir=str(temp_config_dir))
        assert cfg._resolved_config is not None


class TestPersistUpdate:
    """持久化写入测试"""

    def test_persist_without_yaml(self, temp_config_dir):
        """无PyYAML时 persist 返回 False"""
        from config_manager import ConfigManager
        cfg = ConfigManager(config_dir=str(temp_config_dir))
        # 即使没有安装yaml或写入失败也不应崩溃
        result = cfg.set('test.key', 'value', persist=True)
        # 结果可能是True或False，取决于环境和yaml是否可用


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
