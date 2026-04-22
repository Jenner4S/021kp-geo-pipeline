# -*- coding: utf-8 -*-
"""
021kp.com GEO System - Unified Config Manager (ConfigManager)
=============================================================================

Features:
  1. Multi-source config: YAML file -> env vars -> defaults (priority: high->low)
  2. SQLite database backend (zero-config)
  3. Env variable parsing: ${VAR:default} placeholder syntax support
  4. Runtime dynamic modification: API hot-update config items
  5. Secure credential management: sensitive fields masked in API output

Design:
    - Singleton pattern: single shared instance per process
    - Zero-config startup: works without any config files (all defaults)
    - Thread-safe: read/write lock protection

Usage:
    from config_manager import get_config
    
    cfg = get_config()
    db_path = cfg.get('database.path', './data/geo_pipeline.db')
    wechat_appid = cfg.get('api_routing.wechat.app_id', '')
    
Author: GEO-Engine Team | Version: v2.1 (SQLite-only) | Date: 2026-04-21
"""

import os
import re
import json
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from dataclasses import dataclass, field

try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    YAML_AVAILABLE = False

try:
    from loguru import logger
except ImportError:
    import logging as logger


@dataclass
class DatabaseTypeInfo:
    """Database configuration (SQLite)"""
    db_type: str = "sqlite"
    database: str = "geo_pipeline.db"
    table: str = "jobs"
    path: str = "./data/geo_pipeline.db"
    host: str = ""
    port: int = 0
    user: str = ""
    password: str = ""

    def get_connection_url(self) -> str:
        return f"sqlite:///{self.database}"


@dataclass
class APIConfig:
    """Platform API credentials"""
    wechat: Dict[str, str] = field(default_factory=dict)
    douyin: Dict[str, str] = field(default_factory=dict)
    baidu: Dict[str, str] = field(default_factory=dict)


@dataclass
class MonitoringConfig:
    """Monitoring configuration"""
    enabled: bool = True
    citation_threshold: float = 0.005
    api_success_threshold: float = 0.95
    schedule_cron: str = "0 14,20 * * *"
    monitor_interval_hours: int = 2
    alert_webhook: str = ""
    rollback_consecutive_failures: int = 3
    rollback_freeze_hours: int = 48
    auto_rollback: bool = True


@dataclass
class ComplianceConfig:
    """Compliance gate configuration"""
    explicit_marker: str = "AI generated content marker: AI organized, for reference only"
    meta_name: str = "x-ai-source-id"
    meta_content: str = "jiangsong_kuaipin_v1_20260420"
    ban_words_file: str = "./config/ban_words.txt"
    audit_log_retention_days: int = 180
    audit_log_dir: str = "./audit_logs"


class ConfigManager:
    """
    Unified configuration manager (singleton)
    
    Load priority (high -> low):
      1. Environment variables (runtime override)
      2. settings.local.yaml (local credentials, not committed to Git)
      3. settings.yaml       (default config, committed to Git)
      4. Built-in defaults   (fallback)
    """
    
    _instance: Optional['ConfigManager'] = None
    _lock: threading.Lock = threading.Lock()
    
    _DEFAULTS = {
        'system': {
            'name': 'GEO Pipeline Auto System',
            'version': '2.0.0',
            'environment': 'production',
            'timezone': 'Asia/Shanghai',
            'log_level': 'INFO'
        },
        'database': {
            'type': 'sqlite',
            'path': './data/geo_pipeline.db',
            'table': 'jobs',
            'host': '${DB_HOST:localhost}',
            'port': '${DB_PORT:3306}',
            'user': '${DB_USER:root}',
            'password': '${DB_PASSWORD:}',
            'database': '${DB_NAME:geo_pipeline}',
            'pool_size': 5,
            'read_replica': False,
            'sync_interval_minutes': 15,
            'ssl_enabled': False,
            'ssl_ca': None
        },
        'compliance': {
            'explicit_marker': 'AI generated content marker: AI organized, for reference only',
            'meta_name': 'x-ai-source-id',
            'meta_content': 'jiangsong_kuaipin_v1_20260420',
            'ban_words_file': './config/ban_words.txt',
            'audit_log_retention_days': 180,
            'audit_log_dir': './audit_logs'
        },
        'intent': {
            'core_vectors': [
                'Songjiang urgent jobs',
                'G60 area salary range',
                'verified enterprise lookup'
            ],
            'longtail_queries': [
                'Songjiang University City part-time jobs',
                'Songjiang HR bureau whitelist enterprise query',
                'Songjiang 30-min commute job matching',
                'Yangtze River Delta talent policy guide',
                'Songjiang enterprise risk checklist'
            ],
            'platform_mapping_file': './config/platform_mapping.json'
        },
        'content_factory': {
            'schema_context': 'https://schema.org',
            'schema_type': 'JobPosting',
            'tldr_max_length': 120,
            'data_anchor_density': 3,
            'output_dir': './dist',
            'template_dir': './templates'
        },
        'api_routing': {
            'lbs_tag': 'songjiang_district/G60_corridor',
            'max_push_per_day_wechat': 10,
            'max_push_per_day_douyin': 15,
            'max_push_per_day_baidu': 50,
            'wechat': {
                'app_id': '${WECHAT_APP_ID:}',
                'app_secret': '${WECHAT_APP_SECRET:}',
                'base_url': 'https://api.weixin.qq.com'
            },
            'douyin': {
                'client_key': '${DOUYIN_CLIENT_KEY:}',
                'client_secret': '${DOUYIN_CLIENT_SECRET:}',
                'base_url': 'https://open.douyin.com'
            },
            'baidu': {
                'api_key': '${BAIDU_API_KEY:}',
                'site_url': 'https://www.021kp.com',
                'base_url': 'https://ziyuan.baidu.com'
            }
        },
        'monitoring': {
            'schedule_cron': '0 14,20 * * *',
            'citation_rate_threshold': 0.005,
            'api_success_rate_threshold': 0.95,
            'monitor_interval_hours': 2,
            'alert_webhook': '${ALERT_WEBHOOK:}',
            'rollback': {
                'consecutive_failures': 3,
                'freeze_duration_hours': 48,
                'auto_rollback_enabled': True
            }
        }
    }
    
    def __init__(self, config_dir: Optional[str] = None):
        self._config_dir = Path(config_dir) if config_dir else Path(__file__).parent.parent / 'config'
        self._raw_config: Dict[str, Any] = {}
        self._resolved_config: Dict[str, Any] = {}
        self._config_files_loaded: List[str] = []
        self._last_load_time: float = 0
        self._load_all()
    
    @classmethod
    def get_instance(cls) -> 'ConfigManager':
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance
    
    @classmethod
    def reset_instance(cls):
        with cls._lock:
            cls._instance = None
    
    def reload(self):
        with self._lock:
            self._load_all()
    
    def _load_all(self):
        merged = json.loads(json.dumps(self._DEFAULTS))
        
        settings_file = self._config_dir / 'settings.yaml'
        if settings_file.exists():
            file_cfg = self._load_yaml_file(settings_file)
            merged = self._deep_merge(merged, file_cfg)
            self._config_files_loaded.append(str(settings_file))
        
        local_settings = self._config_dir / 'settings.local.yaml'
        if local_settings.exists():
            local_cfg = self._load_yaml_file(local_settings)
            merged = self._deep_merge(merged, local_cfg)
            self._config_files_loaded.append(str(local_settings))
        
        self._raw_config = merged
        self._resolved_config = self._resolve_env_vars(merged)
        self._last_load_time = time.time()
    
    @staticmethod
    def _load_yaml_file(path: Path) -> Dict:
        try:
            if not YAML_AVAILABLE:
                logger.warning(f"PyYAML未安装，跳过配置文件: {path}")
                return {}
            
            with open(path, 'r', encoding='utf-8') as f:
                content = yaml.safe_load(f)
                return content or {}
                
        except FileNotFoundError:
            # 配置文件不存在是正常情况（使用默认值）
            return {}
        except yaml.YAMLError as e:
            # YAML语法错误应警告（可能是用户编辑错误）
            logger.warning(f"YAML解析错误 {path}: {e}")
            return {}
        except (PermissionError, OSError) as e:
            logger.warning(f"无法读取配置文件 {path}: {e}")
            return {}
    
    def _resolve_env_vars(self, obj: Any) -> Any:
        if isinstance(obj, str):
            def _replace_var(match):
                var_name = match.group(1)
                default_val = match.group(2) if match.group(2) is not None else ''
                return os.getenv(var_name, default_val)
            return re.sub(r'\$\{(\w+)(?::([^}]*))?\}', _replace_var, obj)
        elif isinstance(obj, dict):
            return {k: self._resolve_env_vars(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._resolve_env_vars(item) for item in obj]
        return obj
    
    @staticmethod
    def _deep_merge(base: Dict, override: Dict) -> Dict:
        result = base.copy()
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = ConfigManager._deep_merge(result[key], value)
            else:
                result[key] = value
        return result
    
    def get(self, key_path: str, default: Any = None) -> Any:
        keys = key_path.split('.')
        current = self._resolved_config
        for key in keys:
            if isinstance(current, dict) and key in current:
                current = current[key]
            else:
                return default
        return current
    
    def set(self, key_path: str, value: Any, persist: bool = False) -> bool:
        with self._lock:
            keys = key_path.split('.')
            current = self._resolved_config
            for key in keys[:-1]:
                if key not in current or not isinstance(current.get(key), dict):
                    current[key] = {}
                current = current[key]
            current[keys[-1]] = value
        
        if persist:
            return self._persist_update(key_path, value)
        
        return True
    
    def _persist_update(self, key_path: str, value: Any) -> bool:
        if not YAML_AVAILABLE:
            return False
        try:
            local_file = self._config_dir / 'settings.local.yaml'
            existing = {}
            if local_file.exists():
                with open(local_file, 'r', encoding='utf-8') as f:
                    existing = yaml.safe_load(f) or {}
            
            keys = key_path.split('.')
            target = existing
            for key in keys[:-1]:
                if key not in target or not isinstance(target.get(key), dict):
                    target[key] = {}
                target = target[key]
            target[keys[-1]] = value
            
            with open(local_file, 'w', encoding='utf-8') as f:
                yaml.dump(existing, f, allow_unicode=True, default_flow_style=False, sort_keys=True)
            return True
        except (OSError, IOError, yaml.YAMLError) as e:
            logger.warning(f"配置持久化写入失败 {local_file}: {e}")
            return False
    
    # === Structured property accessors ===
    
    @property
    def database_info(self) -> DatabaseTypeInfo:
        db_cfg = self.get('database', {})
        
        return DatabaseTypeInfo(
            db_type='sqlite',
            database=db_cfg.get('database') or db_cfg.get('path', './data/geo_pipeline.db'),
            table=db_cfg.get('table', 'jobs'),
            path=db_cfg.get('path', './data/geo_pipeline.db'),
        )
    
    @property
    def api_credentials(self) -> APIConfig:
        routing = self.get('api_routing', {}) or {}
        return APIConfig(
            wechat=routing.get('wechat', {}) or {},
            douyin=routing.get('douyin', {}) or {},
            baidu=routing.get('baidu', {}) or {}
        )
    
    @property
    def monitoring(self) -> MonitoringConfig:
        mon = self.get('monitoring', {}) or {}
        rollback = mon.get('rollback', {}) or {}
        return MonitoringConfig(
            enabled=self._to_bool(mon.get('enabled', True)),
            citation_threshold=float(mon.get('citation_rate_threshold', 0.005)),
            api_success_threshold=float(mon.get('api_success_rate_threshold', 0.95)),
            schedule_cron=mon.get('schedule_cron', '0 14,20 * * *'),
            monitor_interval_hours=int(mon.get('monitor_interval_hours', 2)),
            alert_webhook=mon.get('alert_webhook', ''),
            rollback_consecutive_failures=int(rollback.get('consecutive_failures', 3)),
            rollback_freeze_hours=int(rollback.get('freeze_duration_hours', 48)),
            auto_rollback=self._to_bool(rollback.get('auto_rollback_enabled', True))
        )
    
    @property
    def compliance(self) -> ComplianceConfig:
        comp = self.get('compliance', {}) or {}
        return ComplianceConfig(
            explicit_marker=comp.get('explicit_marker', 'AI generated content marker'),
            meta_name=comp.get('meta_name', 'x-ai-source-id'),
            meta_content=comp.get('meta_content', 'jiangsong_kuaipin_v1_20260420'),
            ban_words_file=comp.get('ban_words_file', './config/ban_words.txt'),
            audit_log_retention_days=int(comp.get('audit_log_retention_days', 180)),
            audit_log_dir=comp.get('audit_log_dir', './audit_logs')
        )
    
    # === Output methods ===
    
    def to_dict(self, mask_secrets: bool = True) -> Dict[str, Any]:
        output = dict(self._resolved_config)
        if mask_secrets:
            output = self._mask_sensitive_fields(output)
        return output
    
    def _mask_sensitive_fields(self, obj: Any) -> Any:
        SENSITIVE_KEYS = {'password', 'secret', 'token', 'api_key', 'app_secret', 'client_secret'}
        if isinstance(obj, dict):
            masked = {}
            for key, value in obj.items():
                if any(s in key.lower() for s in SENSITIVE_KEYS) and isinstance(value, str) and len(value) > 0:
                    # 固定输出 *****(masked)，不暴露任何真实字符（包括长度）
                    masked[key] = '*****(masked)'
                else:
                    masked[key] = self._mask_sensitive_fields(value)
            return masked
        elif isinstance(obj, list):
            return [self._mask_sensitive_fields(item) for item in obj]
        return obj
    
    # === DB shortcuts ===
    
    def is_sqlite_mode(self) -> bool:
        return True  # Always SQLite now
    
    def requires_external_db(self) -> bool:
        return False  # No external DB needed
    
    def get_all_env_vars(self) -> Dict[str, str]:
        geo_keys = [
            'DB_PATH',
            'WECHAT_APP_ID', 'WECHAT_APP_SECRET',
            'DOUYIN_CLIENT_KEY', 'DOUYIN_CLIENT_SECRET',
            'BAIDU_API_KEY', 'BAIDU_SECRET_KEY',
            'ALERT_WEBHOOK', 'GEO_MODE', 'LOG_LEVEL',
            'MONITOR_ENABLED', 'CITATION_THRESHOLD'
        ]
        return {k: os.getenv(k, '') for k in geo_keys}
    
    @staticmethod
    def _to_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() in ('true', '1', 'yes', 'on')
        return bool(value)
    
    def __repr__(self) -> str:
        db = self.database_info
        loaded = ', '.join(self._config_files_loaded) or '(built-in)'
        ts = datetime.fromtimestamp(self._last_load_time).strftime('%H:%M:%S') if hasattr(datetime, 'fromtimestamp') else ''
        return (f"ConfigManager(db={db.db_type}@{db.host}, "
                f"files=[{loaded}], loaded_at={ts})")


def get_config() -> ConfigManager:
    return ConfigManager.get_instance()

def reload_config():
    ConfigManager.get_instance().reload()


if __name__ == '__main__':
    print("=" * 60)
    print("GEO Pipeline Config Diagnostic Tool")
    print("=" * 60)
    
    cfg = get_config()
    
    print(f"\n[Config Instance]: {cfg}")
    print(f"\n[Database Config]:")
    db = cfg.database_info
    print(f"   Type:     {db.db_type}")
    print(f"   URL:      {db.get_connection_url()}")
    print(f"   Table:    {db.table}")
    print(f"   Read-only:{db.read_only}")
    
    print(f"\n[Platform Credentials]:")
    api = cfg.api_credentials
    print(f"   WeChat: {'configured' if api.wechat.get('app_id') else 'not set'}")
    print(f"   Douyin: {'configured' if api.douyin.get('client_key') else 'not set'}")
    print(f"   Baidu:  {'configured' if api.baidu.get('api_key') else 'not set'}")
    
    print(f"\n[Monitoring]:")
    mon = cfg.monitoring
    print(f"   Enabled:          {mon.enabled}")
    print(f"   Citation Thresh:   {mon.citation_threshold:.1%}")
    print(f"   Alert Webhook:     {'set' if mon.alert_webhook else 'not set'}")
    
    print(f"\n[Environment Variables]:")
    env_vars = cfg.get_all_env_vars()
    configured = {k: v for k, v in env_vars.items() if v}
    if configured:
        for k, v in configured.items():
            val_display = v if len(v) <= 8 else v[:8] + '...'
            print(f"   {k} = {val_display}")
    else:
        print("   (none using defaults)")
    
    print(f"\n[Config Files Loaded]: {len(cfg._config_files_loaded)}")
    for f in cfg._config_files_loaded:
        print(f"   - {f}")
    
    print("\n" + "=" * 60)
