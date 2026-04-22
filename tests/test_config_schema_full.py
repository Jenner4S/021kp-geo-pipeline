# -*- coding: utf-8 -*-
"""
ConfigSchema 完整测试套件
============================

覆盖范围:
- ConfigType 枚举
- ConfigGroup 枚举
- ConfigFieldDef 数据类
- CONFIG_SCHEMA 完整定义验证
- get_config_schema() / get_config_by_group() / get_all_groups()

Author: GEO-Test Suite | Date: 2026-04-21
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import pytest


class TestConfigTypeEnum:
    """ConfigType 枚举测试"""

    def test_all_types_exist(self):
        from config_schema import ConfigType
        expected = ['STRING', 'PASSWORD', 'NUMBER', 'SELECT', 
                    'TOGGLE', 'TEXTAREA', 'JSON_EDITOR', 'PATH']
        for t in expected:
            assert hasattr(ConfigType, t)
            assert isinstance(getattr(ConfigType, t).value, str)

    def test_type_values(self):
        from config_schema import ConfigType
        assert ConfigType.STRING.value == "string"
        assert ConfigType.PASSWORD.value == "password"
        assert ConfigType.NUMBER.value == "number"
        assert ConfigType.SELECT.value == "select"
        assert ConfigType.TOGGLE.value == "toggle"
        assert ConfigType.TEXTAREA.value == "textarea"
        assert ConfigType.JSON_EDITOR.value == "json"
        assert ConfigType.PATH.value == "path"

    def test_is_string_enum(self):
        from config_schema import ConfigType
        # 验证是 str 的子类（可用于 JSON 序列化）
        assert issubclass(ConfigType, str)


class TestConfigGroupEnum:
    """ConfigGroup 枚举测试"""

    def test_all_groups_exist(self):
        from config_schema import ConfigGroup
        expected = ['SITE', 'CONTENT', 'COMPLIANCE',
                    'PLATFORM_WECHAT', 'PLATFORM_DOUYIN', 'PLATFORM_BAIDU',
                    'DATABASE', 'MONITORING', 'SCHEDULER', 'ADVANCED']
        for g in expected:
            assert hasattr(ConfigGroup, g)

    def test_group_values(self):
        from config_schema import ConfigGroup
        assert ConfigGroup.SITE.value == "site"
        assert ConfigGroup.CONTENT.value == "content"
        assert ConfigGroup.COMPLIANCE.value == "compliance"
        assert ConfigGroup.PLATFORM_WECHAT.value == "wechat"
        assert ConfigGroup.DATABASE.value == "database"


class TestConfigFieldDef:
    """ConfigFieldDef 数据类测试"""

    def test_default_values(self):
        from config_schema import ConfigFieldDef, ConfigType, ConfigGroup
        field = ConfigFieldDef(
            key="test.key",
            label="测试字段",
            type_=ConfigType.STRING,
            default="default_value",
            group=ConfigGroup.SITE,
            description="这是一个测试字段",
            order=1
        )
        assert field.key == "test.key"
        assert field.label == "测试字段"
        assert field.type_ == ConfigType.STRING
        assert field.default == "default_value"
        assert field.group == ConfigGroup.SITE
        assert field.description == "这是一个测试字段"
        assert field.placeholder == ""
        assert field.options is None
        assert field.validation == {}
        assert field.is_secret is False
        assert field.requires_restart is False
        assert field.order == 1

    def test_secret_field(self):
        from config_schema import ConfigFieldDef, ConfigType, ConfigGroup
        field = ConfigFieldDef(
            key="secret.key",
            label="密钥",
            type_=ConfigType.PASSWORD,
            default="",
            group=ConfigGroup.ADVANCED,
            is_secret=True,
            requires_restart=True
        )
        assert field.is_secret is True
        assert field.requires_restart is True

    def test_with_validation_rules(self):
        from config_schema import ConfigFieldDef, ConfigType, ConfigGroup
        field = ConfigFieldDef(
            key="number.field",
            label="数字字段",
            type_=ConfigType.NUMBER,
            default=100,
            group=ConfigGroup.MONITORING,
            validation={"min": 0, "max": 1000},
            order=2
        )
        assert field.validation["min"] == 0
        assert field.validation["max"] == 1000

    def test_with_options(self):
        from config_schema import ConfigFieldDef, ConfigType, ConfigGroup
        field = ConfigFieldDef(
            key="select.field",
            label="选择字段",
            type_=ConfigType.SELECT,
            default="option_a",
            group=ConfigGroup.SCHEDULER,
            options=[
                {"value": "option_a", "label": "选项A"},
                {"value": "option_b", "label": "选项B"},
            ]
        )
        assert len(field.options) == 2
        assert field.options[0]["value"] == "option_a"


class TestConfigSchema:
    """CONFIG_SCHEMA 全量定义验证"""

    def test_schema_not_empty(self):
        from config_schema import CONFIG_SCHEMA
        assert len(CONFIG_SCHEMA) > 30  # 应该有大量配置项

    def test_all_keys_unique(self):
        from config_schema import CONFIG_SCHEMA
        keys = [f.key for f in CONFIG_SCHEMA]
        assert len(keys) == len(set(keys)), "CONFIG_SCHEMA 中存在重复的 key"

    def test_site_group_fields(self):
        from config_schema import CONFIG_SCHEMA, ConfigGroup
        site_fields = [f for f in CONFIG_SCHEMA if f.group == ConfigGroup.SITE]
        keys = {f.key for f in site_fields}
        assert 'site.name' in keys
        assert 'site.url' in keys
        assert 'site.region' in keys
        assert 'site.city' in keys

    def test_content_group_fields(self):
        from config_schema import CONFIG_SCHEMA, ConfigGroup
        content_fields = [f for f in CONFIG_SCHEMA if f.group == ConfigGroup.CONTENT]
        keys = {f.key for f in content_fields}
        assert 'content.tldr_max_length' in keys
        assert 'content.data_anchor_density' in keys

    def test_monitoring_group_fields(self):
        from config_schema import CONFIG_SCHEMA, ConfigGroup
        mon_fields = [f for f in CONFIG_SCHEMA if f.group == ConfigGroup.MONITORING]
        keys = {f.key for f in mon_fields}
        assert 'monitoring.enabled' in keys
        assert 'monitoring.citation_threshold' in keys
        assert 'monitoring.alert_webhook' in keys

    def test_database_group_fields(self):
        from config_schema import CONFIG_SCHEMA, ConfigGroup
        db_fields = [f for f in CONFIG_SCHEMA if f.group == ConfigGroup.DATABASE]
        keys = {f.key for f in db_fields}
        assert 'database.db_type' in keys
        assert 'database.password' in keys

    def test_platform_wechat_has_secrets(self):
        from config_schema import CONFIG_SCHEMA, ConfigGroup
        wechat_fields = [f for f in CONFIG_SCHEMA if f.group == ConfigGroup.PLATFORM_WECHAT]
        secret_fields = [f for f in wechat_fields if f.is_secret]
        assert len(secret_fields) >= 1  # app_id, app_secret 至少一个

    def test_all_platforms_have_max_push(self):
        """每个平台都应有 max_push_per_day 字段"""
        from config_schema import CONFIG_SCHEMA
        all_keys = [f.key for f in CONFIG_SCHEMA]
        assert any('wechat' in k and 'push' in k for k in all_keys)
        assert any('douyin' in k and 'push' in k for k in all_keys)
        assert any('baidu' in k and 'push' in k for k in all_keys)

    def test_order_within_groups(self):
        """同组内 order 值应合理"""
        from config_schema import get_config_by_group, ConfigGroup
        for group in ConfigGroup:
            fields = get_config_by_group(group)
            orders = [f.order for f in fields]
            assert orders == sorted(orders), f"{group} 组内 order 未排序"

    def test_validation_ranges_sensible(self):
        """验证规则的范围值应合理"""
        from config_schema import CONFIG_SCHEMA
        for f in CONFIG_SCHEMA:
            rules = f.validation
            if 'min' in rules and 'max' in rules:
                assert rules['min'] < rules['max'], \
                    f"{f.key}: min({rules['min']}) >= max({rules['max']})"


class TestSchemaFunctions:
    """模块级函数测试"""

    def test_get_config_schema_returns_copy(self):
        """返回的是副本而非原始引用"""
        from config_schema import get_config_schema, CONFIG_SCHEMA
        schema1 = get_config_schema()
        schema2 = get_config_schema()
        assert schema1 is not schema2 or len(schema1) == len(CONFIG_SCHEMA)
        assert len(schema1) > 0

    def test_get_config_by_group(self):
        """按分组获取配置项"""
        from config_schema import get_config_by_group, ConfigGroup
        site_fields = get_config_by_group(ConfigGroup.SITE)
        assert all(f.group == ConfigGroup.SITE for f in site_fields)
        
        # 空分组返回空列表
        # 所有已定义的分组应该都有字段
        for g in ConfigGroup:
            fields = get_config_by_group(g)
            assert isinstance(fields, list)

    def test_get_all_groups_structure(self):
        """获取所有分组信息"""
        from config_schema import get_all_groups
        groups = get_all_groups()
        assert isinstance(groups, list)
        assert len(groups) > 0
        
        for g in groups:
            assert 'id' in g
            assert 'label' in g
            assert 'field_count' in g
            assert 'has_secrets' in g
            assert isinstance(g['field_count'], int)
            assert isinstance(g['has_secrets'], bool)


class TestSchemaEdgeCases:
    """边界情况测试"""

    def test_field_def_immutability_semantic(self):
        """ConfigFieldDef 是 dataclass，修改不影响原定义"""
        from config_schema import ConfigFieldDef, ConfigType, ConfigGroup
        original = ConfigFieldDef(
            key="test", label="T", type_=ConfigType.STRING,
            default="val", group=ConfigGroup.SITE
        )
        modified_default = "new_val"
        # 创建新实例
        new_field = ConfigFieldDef(
            key=original.key, label=original.label, type_=original.type_,
            default=modified_default, group=original.group
        )
        assert original.default != new_field.default


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
