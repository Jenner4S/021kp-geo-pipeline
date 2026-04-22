# -*- coding: utf-8 -*-
"""
GEO Pipeline - 配置持久化存储层 (SQLite)
=============================================================

设计原则:
    - 所有用户通过 Web UI 修改的配置项，持久化到 SQLite system_config 表
    - 仅启动引导参数（如数据库连接串）保留在 YAML 文件中
    - 首次运行时自动从 Schema 默认值初始化表数据
    - 线程安全的读写操作

分层策略:
    ┌──────────────────────────────────────┐
    │  引导配置 (Bootstrap)                 │ ← settings.local.yaml
    │  database.*, advanced.log_level      │   启动时读取, 启动前必须存在
    ├──────────────────────────────────────┤
    │  运行时配置 (Runtime)                 │ ← SQLite system_config 表
    │  site.*, content.*, compliance.*     │   UI 修改后写入 DB
    │  platform.*, monitoring.*            │
    │  scheduler.*, advanced.*             │
    └──────────────────────────────────────┘

Usage:
    from config_store import get_config_store
    
    store = get_config_store()
    value = store.get('site.name')           # 读
    store.set('site.name', '新值')           # 写
    all_cfg = store.load_all(schema)          # 批量读 (带 Schema 合并)

Author: GEO-Engine Team | Version: v2.1 | Date: 2026-04-21
"""

import json
import threading
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    from loguru import logger
except ImportError:
    import logging as logger


class ConfigStore:
    """
    基于 SQLite 的配置 KV 存储。
    
    单例模式，与主业务库共用同一个 SQLite 文件，
    通过独立表 'system_config' 隔离配置数据与业务数据。
    """

    _instance: Optional['ConfigStore'] = None
    _lock: threading.Lock = threading.Lock()

    # ---- 引导配置键集合（这些始终从 ConfigManager/YAML 读取，不存 DB）----
    BOOTSTRAP_KEYS = frozenset({
        'database.db_type',
        'database.host',
        'database.port',
        'database.user',
        'database.password',
        'database.database',
    })

    def __init__(self, db_path: str = './data/geo_pipeline.db'):
        self._db_path = Path(db_path)
        self._conn = None
        self._local = threading.local()
        self._ensure_connection()
        self._init_table()

    # ==================== 单例 ====================

    @classmethod
    def get_instance(cls, db_path: str = './data/geo_pipeline.db') -> 'ConfigStore':
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(db_path=db_path)
        return cls._instance

    @classmethod
    def reset_instance(cls):
        with cls._lock:
            if cls._instance is not None:
                try:
                    cls._instance.close()
                except Exception:
                    pass
            cls._instance = None

    # ==================== 连接管理 ====================

    def _get_conn(self):
        """线程本地连接（每个线程一个连接，避免并发冲突）"""
        conn = getattr(self._local, 'conn', None)
        if conn is None:
            import sqlite3
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self._db_path), timeout=30.0, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("PRAGMA foreign_keys=ON")
            self._local.conn = conn
        return conn

    def _ensure_connection(self):
        try:
            self._get_conn()
        except Exception as e:
            logger.error(f"[ConfigStore] 无法建立数据库连接: {e}")
            raise

    def close(self):
        if hasattr(self._local, 'conn') and self._local.conn:
            try:
                self._local.conn.close()
            except Exception:
                pass
            self._local.conn = None

    # ==================== 表结构 ====================

    def _init_table(self):
        conn = self._get_conn()
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS `system_config` (
                `key`       TEXT PRIMARY KEY,
                `value`     TEXT NOT NULL DEFAULT '',
                `value_type` TEXT NOT NULL DEFAULT 'string',
                `group_id`  TEXT NOT NULL DEFAULT '',
                `updated_at` TEXT NOT NULL DEFAULT (datetime('now', '+8 hours')),
                `created_at` TEXT NOT NULL DEFAULT (datetime('now', '+8 hours'))
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_cfg_group ON system_config(group_id)")
        conn.commit()
        logger.debug(f"[ConfigStore] system_config 表已就绪")

    # ==================== 核心 CRUD ====================

    def get(self, key: str, default: Any = None) -> Any:
        """
        读取单个配置值。

        Args:
            key: 配置键名 (如 'site.name')
            default: 未找到时的回退值

        Returns:
            配置值（自动还原 Python 类型）
        """
        if key in self.BOOTSTRAP_KEYS:
            return self._read_bootstrap(key, default)

        try:
            c = self._get_conn().cursor()
            c.execute("SELECT value, value_type FROM system_config WHERE key=?", (key,))
            row = c.fetchone()
            if row is None:
                return default
            return self._deserialize(row['value'], row['value_type'])
        except Exception as e:
            logger.warning(f"[ConfigStore] 读取 {key} 失败: {e}")
            return default

    def set(self, key: str, value: Any) -> bool:
        """
        写入单个配置值（UPSERT）。

        Args:
            key: 配置键名
            value: 值（自动序列化）

        Returns:
            是否成功
        """
        if key in self.BOOTSTRAP_KEYS:
            return self._write_bootstrap(key, value)

        now = datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')
        serialized, type_tag = self._serialize(value)

        try:
            conn = self._get_conn()
            c = conn.cursor()
            c.execute("""
                INSERT INTO system_config (key, value, value_type, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value=excluded.value,
                    value_type=excluded.value_type,
                    updated_at=excluded.updated_at
            """, (key, serialized, type_tag, now))
            conn.commit()
            logger.debug(f"[ConfigStore] 已保存 {key}")
            return True
        except Exception as e:
            logger.error(f"[ConfigStore] 写入 {key} 失败: {e}")
            return False

    def delete(self, key: str) -> bool:
        """删除配置项（恢复为 Schema 默认值）"""
        if key in self.BOOTSTRAP_KEYS:
            logger.warning(f"[ConfigStore] 不能删除引导配置: {key}")
            return False
        try:
            self._get_conn().execute("DELETE FROM system_config WHERE key=?", (key,)).connection.commit()
            return True
        except Exception as e:
            logger.error(f"[ConfigStore] 删除 {key} 失败: {e}")
            return False

    def exists(self, key: str) -> bool:
        """检查配置是否存在"""
        c = self._get_conn().cursor()
        c.execute("SELECT 1 FROM system_config WHERE key=? LIMIT 1", (key,))
        return c.fetchone() is not None

    def load_all(self, schema_fields=None) -> Dict[str, Any]:
        """
        批量加载所有配置，并与 Schema 默认值合并。

        这是 GET /api/config 的核心数据源。

        Args:
            schema_fields: 来自 config_schema 的字段定义列表 (可选)

        Returns:
            {key: current_value} 完整字典
        """
        result = {}

        # 1. 从 DB 加载已存储的值
        try:
            c = self._get_conn().cursor()
            c.execute("SELECT key, value, value_type FROM system_config")
            for row in c.fetchall():
                result[row['key']] = self._deserialize(row['value'], row['value_type'])
        except Exception as e:
            logger.warning(f"[ConfigStore] 批量读取失败: {e}")

        # 2. 从 ConfigManager 补充引导配置
        bootstrap_vals = self._load_all_bootstrap()
        result.update(bootstrap_vals)

        # 3. 用 Schema 默认值填充缺失项
        if schema_fields:
            for f in schema_fields:
                if f.key not in result:
                    result[f.key] = f.default

        return result

    # ==================== Schema 初始化 ====================

    def init_from_schema(self, schema_fields: list) -> int:
        """
        首次运行 / Schema 升级时：用默认值填充尚不存在的记录。

        Args:
            schema_fields: ConfigFieldDef 对象列表

        Returns:
            新插入的记录数
        """
        inserted = 0
        for f in schema_fields:
            if f.key in self.BOOTSTRAP_KEYS:
                continue
            if not self.exists(f.key):
                ok = self.set(f.key, f.default)
                if ok:
                    inserted += 1

        if inserted > 0:
            logger.info(f"[ConfigStore] 从 Schema 初始化了 {inserted} 条配置记录")

        return inserted

    # ==================== 序列化 / 反序列化 ====================

    @staticmethod
    def _serialize(value: Any) -> Tuple[str, str]:
        """Python 值 → (字符串, 类型标签)"""
        if value is None:
            return ('', 'string')
        if isinstance(value, bool):
            return ('true' if value else 'false', 'bool')
        if isinstance(value, int):
            return (str(value), 'int')
        if isinstance(value, float):
            return (str(value), 'float')
        if isinstance(value, (list, dict)):
            return (json.dumps(value, ensure_ascii=False), 'json')
        return (str(value), 'string')

    @staticmethod
    def _deserialize(value_str: str, type_tag: str) -> Any:
        "(字符串, 类型标签) → Python 值"
        if type_tag == 'bool':
            return value_str.lower() in ('true', '1', 'yes')
        if type_tag == 'int':
            try:
                return int(value_str)
            except ValueError:
                return value_str
        if type_tag == 'float':
            try:
                return float(value_str)
            except ValueError:
                return value_str
        if type_tag == 'json':
            try:
                return json.loads(value_str)
            except (json.JSONDecodeError, ValueError):
                return value_str
        return value_str

    # ==================== 引导配置代理 ====================

    def _read_bootstrap(self, key: str, default: Any = None) -> Any:
        """引导配置回退到 ConfigManager"""
        try:
            from config_manager import get_config
            cfg = get_config()
            return cfg.get(key, default)
        except ImportError:
            return default

    def _write_bootstrap(self, key: str, value: Any) -> bool:
        """引导配置写入 ConfigManager (YAML 文件)"""
        try:
            from config_manager import get_config
            cfg = get_config()
            return cfg.set(key, value, persist=True)
        except ImportError:
            return False

    def _load_all_bootstrap(self) -> Dict[str, Any]:
        """加载所有引导配置当前值"""
        try:
            from config_manager import get_config
            cfg = get_config()
            result = {}
            for key in self.BOOTSTRAP_KEYS:
                val = cfg.get(key)
                if val is not None:
                    result[key] = val
            return result
        except ImportError:
            return {}

    # ==================== 维护方法 ====================

    def export_all(self) -> List[Dict[str, Any]]:
        """导出全部配置（用于备份 / 调试）"""
        c = self._get_conn().cursor()
        c.execute("SELECT key, value, value_type, group_id, updated_at FROM system_config ORDER BY group_id, key")
        rows = []
        for r in c.fetchall():
            rows.append({
                'key': r['key'],
                'value': r['value'],
                'type': r['value_type'],
                'group': r['group_id'],
                'updated_at': r['updated_at'],
            })
        return rows

    def count(self) -> int:
        """已存储的配置条目数"""
        c = self._get_conn().cursor()
        c.execute("SELECT COUNT(*) FROM system_config")
        return c.fetchone()[0]

    def __repr__(self):
        return f"ConfigStore(db={self._db_path}, records={self.count()})"


# ==================== 便捷函数 ====================

_store_instance: Optional[ConfigStore] = None


def get_config_store(db_path: str = './data/geo_pipeline.db') -> ConfigStore:
    """获取全局 ConfigStore 单例"""
    global _store_instance
    if _store_instance is None:
        _store_instance = ConfigStore.get_instance(db_path=db_path)
    return _store_instance


def init_config_store(db_path: str = './data/geo_pipeline.db') -> ConfigStore:
    """
    初始化配置存储（含 Schema 默认值注入）。

    在服务启动时调用一次即可。
    """
    store = get_config_store(db_path)

    try:
        from config_schema import get_config_schema
        schema = get_config_schema()
        count = store.init_from_schema(schema)
        logger.info(f"[ConfigStore] 就绪，共 {store.count()} 条配置记录 (新增 {count})")
    except ImportError:
        logger.warning("[ConfigStore] config_schema 不可用，跳过默认值初始化")

    return store
