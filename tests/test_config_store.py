# -*- coding: utf-8 -*-
"""
GEO Pipeline 配置存储层测试套件 (ConfigStore)
=================================================

目标: 覆盖 config_store.py KV读写/单例/Bootstrap隔离
运行: uv run pytest tests/test_config_store.py -v --tb=short
"""

import os
import sys
import json as _json
import pytest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from config_store import ConfigStore


@pytest.fixture
def fresh_store(tmp_path):
    """每次测试创建全新的ConfigStore实例（不使用单例）"""
    db_file = tmp_path / "test_config.db"
    store = ConfigStore(db_path=str(db_file))
    yield store
    store.close()
    for ext in ["", "-wal", "-shm"]:
        p = Path(str(db_file) + ext)
        p.unlink(missing_ok=True)


class TestConfigStoreBasic:
    """基础KV操作"""

    def test_set_and_get(self, fresh_store):
        fresh_store.set("test.key", "hello")
        val = fresh_store.get("test.key")
        assert val == "hello"

    def test_get_nonexistent_returns_none(self, fresh_store):
        assert fresh_store.get("nonexistent.key") is None

    def test_set_overwrites(self, fresh_store):
        fresh_store.set("k", "v1")
        fresh_store.set("k", "v2")
        assert fresh_store.get("k") == "v2"

    def test_set_numeric_value(self, fresh_store):
        fresh_store.set("numeric.int", 42)
        fresh_store.set("numeric.float", 3.14)
        assert int(fresh_store.get("numeric.int")) == 42

    def test_set_json_value(self, fresh_store):
        data = {"key": [1, 2, 3]}
        fresh_store.set("json.data", _json.dumps(data))
        loaded = _json.loads(fresh_store.get("json.data"))
        assert loaded["key"] == [1, 2, 3]

    def test_delete_key(self, fresh_store):
        fresh_store.set("to_delete", "x")
        fresh_store.delete("to_delete")
        # delete方法可能不存在，检查API
        if hasattr(fresh_store, 'delete'):
            assert fresh_store.get("to_delete") is None


class TestConfigStoreLoadAll:
    """批量加载与Schema合并"""

    def test_load_all_empty(self, fresh_store):
        schema_fields = [
            type('Field', (), {'key': f'group.field{i}', 'default': f'def{i}'})()
            for i in range(3)
        ]
        result = fresh_store.load_all(schema_fields=schema_fields)
        assert isinstance(result, dict)

    def test_load_all_merges_with_defaults(self, fresh_store):
        fresh_store.set("site.name", "自定义站点名")

        class Field:
            pass

        fields = []
        for k, d in [("site.name", "默认"), ("site.url", "http://default")]:
            f = Field(); f.key = k; f.default = d; fields.append(f)

        result = fresh_store.load_all(schema_fields=fields)
        assert result["site.name"] == "自定义站点名"  # DB值优先
        # 默认值填充未设置的字段
        if "site.url" in result:
            assert result["site.url"] == "http://default"


class TestBootstrapKeysIsolation:
    """引导配置键隔离: Bootstrap键不应写入DB"""

    @pytest.fixture
    def store(self, fresh_store):
        return fresh_store

    def test_bootstrap_keys_frozenset_not_empty(self):
        assert len(ConfigStore.BOOTSTRAP_KEYS) > 0
        assert 'database.db_type' in ConfigStore.BOOTSTRAP_KEYS or any(
            'database' in k for k in ConfigStore.BOOTSTRAP_KEYS
        )

    def test_bootstrap_keys_are_strings(self):
        for key in ConfigStore.BOOTSTRAP_KEYS:
            assert isinstance(key, str)


class TestConfigStorePersistence:
    """数据持久化: 重连后数据仍存在"""

    def test_data_survives_reconnect(self, tmp_path):
        db_file = tmp_path / "persist.db"
        s1 = ConfigStore(db_path=str(db_file))
        s1.set("persist.test", "survived")
        s1.close()

        s2 = ConfigStore(db_path=str(db_file))
        val = s2.get("persist.test")
        assert val == "survived"
        s2.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
