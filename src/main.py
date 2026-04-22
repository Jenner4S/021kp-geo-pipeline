"""
021kp.com GEO自动化运营系统 - 主入口模块
=============================================================================

功能描述:
    统一协调Phase 1-5各模块的运行时调度，
    提供CLI命令行接口与HTTP API服务两种运行模式。
    支持数据源: CSV文件 / SQLite数据库

运行模式:
    pipeline  - 标准GEO流水线(CSV输入)
    db        - 数据库驱动模式(从SQLite读取→GEO处理)
    server    - HTTP API服务模式(含/health+/ready端点)
    import    - 数据导入模式(CSV→SQLite)

使用说明:
    # CLI模式（单次执行全流程）
    python -m src.main --mode pipeline --csv data/jobs.csv
    
    # 数据库模式
    python -m src.main --mode db --limit 50 --category manufacturing
    
    # HTTP服务模式
    python -m src.main --mode server --port 8080
    
    # 导入CSV到SQLite
    python -m src.main --mode import --csv data/jobs.csv

作者: GEO-Engine Team | 版本: v2.1 (SQLite-only) | 日期: 2026-04-21
"""

import argparse
import json
import os
import sys
from pathlib import Path
from datetime import datetime, timezone, timedelta
from urllib.parse import parse_qs

try:
    from loguru import logger
except ImportError:
    import logging as logger

# 尝试提前导入 ConfigManager (可选依赖)
try:
    from config_manager import get_config as _get_cfg
    CONFIG_AVAILABLE = True
except ImportError:
    CONFIG_AVAILABLE = False
    def _get_cfg():
        return None


def _init_system():
    """系统初始化 (配置管理器 + 数据库后端)"""
    # 确保src目录在Python路径中
    _ensure_src_in_path()
    
    # 初始化统一配置管理器
    try:
        from config_manager import get_config
        cfg = get_config()
        
        # 输出启动信息
        db = cfg.database_info
        logger.info(f"配置管理器已加载 | DB类型={db.db_type} | 配置文件数={len(cfg._config_files_loaded)}")
        
    except ImportError:
        pass


def run_pipeline_mode(csv_path: str = None, json_input: str = None) -> dict:
    """
    标准GEO流水线模式（CSV/JSON输入）
    
    流程:
    CSV/JSON输入 → 合规闸门(Phase1) → 意图路由(Phase2)
    → 内容工厂(Phase3) → API路由(Phase4) → 监控记录(Phase5)
    
    Args:
        csv_path: 岗位数据CSV文件路径
        json_input: 单条岗位JSON字符串
        
    Returns:
        处理结果汇总字典
    """
    # 确保src目录在Python路径中
    _ensure_src_in_path()
    
    results = {
        "status": "success",
        "mode": "pipeline",
        "timestamp": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        "phase_results": {}
    }
    
    try:
        # 准备输入数据
        from intent_router import load_jobs_from_csv
        
        if csv_path and Path(csv_path).exists():
            jobs_data = load_jobs_from_csv(csv_path)
            source_id = csv_path
        elif json_input:
            try:
                jobs_data = [json.loads(json_input)] if isinstance(json_input, str) else [json_input]
            except (json.JSONDecodeError, TypeError) as e:
                raise ValueError(f"JSON格式错误: {e}")
            source_id = "json_input"
        else:
            raise ValueError("请提供 --csv 或 --json 参数")
        
        if not jobs_data:
            raise ValueError("未读取到有效数据")
        
        print("\n" + "=" * 60)
        print("🚀 启动GEO自动化流水线 (Pipeline Mode)...")
        print(f"   数据源: {source_id} | 记录数: {len(jobs_data)}")
        print("=" * 60)
        
        # 执行核心GEO流程
        _run_geo_phases(jobs_data, results, source_id=source_id)
        
        print(f"\n✅ Pipeline模式完成! 处理 {len(jobs_data)} 条记录")
        print("=" * 60)
        
    except Exception as e:
        results["status"] = "error"
        results["error_message"] = str(e)
        if os.environ.get('GEO_LOG_LEVEL', '').upper() in ('DEBUG', 'TRACE'):
            import traceback
            results["traceback"] = traceback.format_exc()
    
    return results


def _ensure_src_in_path():
    """确保src目录在sys.path中（支持python -m src.main调用）"""
    import os
    src_dir = Path(__file__).parent.resolve()
    project_root = src_dir.parent
    
    paths_to_add = [str(src_dir), str(project_root)]
    for p in paths_to_add:
        if p not in sys.path:
            sys.path.insert(0, p)


def run_db_pipeline_mode(
    limit: int = 100,
    category_filter: str = None,
    urgent_only: bool = False
) -> dict:
    """
    数据库驱动模式：从SQLite读取岗位数据→执行GEO全流程
    
    Args:
        limit: 最大处理条数
        category_filter: 行业类别过滤
        urgent_only: 仅急招岗位
        
    Returns:
        处理结果汇总字典
    """
    results = {
        "status": "success",
        "mode": "database",
        "timestamp": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        "db_source": {},
        "phase_results": {}
    }
    
    try:
        from database_backend import get_backend
        
        print("\n" + "=" * 60)
        print("🔗 GEO Pipeline (Database Mode - SQLite)")
        print("=" * 60)
        
        backend = get_backend()
        if not backend.connect():
            raise ConnectionError("无法连接到SQLite数据库")
        
        try:
            test_result = backend.test_connection()
            results['db_source'] = {
                "backend_type": "sqlite",
                "database": test_result.get('database', 'unknown'),
                "total_records": test_result.get('total_records', 0),
            }
            
            stats = backend.get_statistics()
            results['db_source']['statistics'] = {
                'total_active': stats.total_active,
                'urgent_ratio': stats.urgent_ratio,
            }
            
            print(f"\n📊 数据库状态:")
            print(f"   活跃岗位: {stats.total_active} 条")
            print(f"   急招占比: {stats.urgent_ratio}%")
            
            jobs_data = [job.to_dict() for job in backend.fetch_jobs(
                limit=limit,
                category_filter=category_filter,
                urgent_only=urgent_only
            )]
            
            if not jobs_data:
                print("\n⚠️ 未查询到符合条件的岗位数据")
                return {**results, "status": "empty", "jobs_processed": 0}
            
            print(f"   已加载: {len(jobs_data)} 条记录")
            
            _run_geo_phases(jobs_data, results, source_id="sqlite_db")
            
            print(f"\n✅ DB模式流水线完成! 共处理 {len(jobs_data)} 条")
        finally:
            backend.close()
        
    except Exception as e:
        results["status"] = "error"
        results["error_message"] = str(e)
        if os.environ.get('GEO_LOG_LEVEL', '').upper() in ('DEBUG', 'TRACE'):
            import traceback
            results["traceback"] = traceback.format_exc()
    
    return results


def run_import_mode(csv_path: str, dry_run: bool = False) -> dict:
    """
    CSV导入模式：将岗位数据从CSV导入SQLite
    
    Args:
        csv_path: CSV文件路径
        dry_run: 试运行模式(不实际写入DB)
        
    Returns:
        导入结果汇总
    """
    results = {
        "status": "success",
        "mode": "import",
        "timestamp": datetime.now(timezone(timedelta(hours=8))).isoformat(),
        "source_file": csv_path,
        "dry_run": dry_run,
        "import_stats": {"read": 0, "valid": 0, "skipped": 0, "inserted": 0}
    }
    
    try:
        from database_backend import get_backend
        from intent_router import load_jobs_from_csv
        
        print("\n" + "=" * 60)
        print("📥 GEO Pipeline (Import Mode: CSV → SQLite)")
        print("=" * 60)
        
        # 1. 读取CSV
        jobs = load_jobs_from_csv(csv_path)
        results['import_stats']['read'] = len(jobs)
        print(f"\n📂 从CSV读取: {len(jobs)} 条记录")
        
        if dry_run:
            print("   [DRY RUN] 不写入数据库，仅验证格式")
            results['status'] = 'dry_run'
            return results
        
        # 2. 连接SQLite并批量插入
        backend = get_backend()
        
        if not backend.connect():
            raise ConnectionError("SQLite数据库连接失败")
        
        try:
            inserted, skipped = backend.insert_jobs_batch(jobs)
            
            results['import_stats'].update({
                "valid": len(jobs) - skipped,
                "skipped": skipped,
                "inserted": inserted
            })
            
            print(f"\n✅ 导入完成:")
            print(f"   读取: {len(jobs)} | 有效: {len(jobs)-skipped} | 跳过: {skipped}")
            print(f"   写入/更新: {inserted} 条")
            
        finally:
            backend.close()
        
    except Exception as e:
        results["status"] = "error"
        results["error_message"] = str(e)
        if os.environ.get('GEO_LOG_LEVEL', '').upper() in ('DEBUG', 'TRACE'):
            import traceback
            results["traceback"] = traceback.format_exc()
    
    return results


def _run_geo_phases(jobs_data: list, results: dict, source_id: str = "unknown"):
    """内部函数：执行GEO Phase 1-5流水线核心逻辑"""
    
    from compliance_gate import ComplianceGate, ComplianceConfig
    from intent_router import IntentRouter, load_jobs_from_csv
    from content_factory import ContentFactory, ContentFactoryConfig
    from dist_monitor import DistributionMonitor
    
    # Phase 1: 合规闸门
    print("\n🛡️ Phase 1: 合规闸门检查...")
    gate = ComplianceGate()
    
    passed_jobs = []
    compliance_results = []
    
    for idx, job in enumerate(jobs_data):
        job_str = json.dumps(job, ensure_ascii=False)
        result = gate.process(job_str, source_identifier=f"{source_id}_{idx}")
        compliance_results.append(result)
        
        if result.status.upper() in ("PASS", "PASSED", "PARTIAL"):
            passed_jobs.append(job)
    
    passed_rate = len(passed_jobs) / len(jobs_data) * 100 if jobs_data else 0
    results['phase_results']['compliance_gate'] = {
        "processed": len(jobs_data),
        "passed": len(passed_jobs),
        "blocked": len(jobs_data) - len(passed_jobs),
        "pass_rate": f"{passed_rate:.1f}%"
    }
    print(f"   通过率: {passed_rate:.1f}% ({len(passed_jobs)}/{len(jobs_data)})")
    
    if not passed_jobs:
        print("   ⚠️ 无合规数据通过，终止后续流程")
        return
    
    # Phase 2: 意图路由
    print("\n🧭 Phase 2: 意图路由分发...")
    router = IntentRouter()
    routing_results = router.batch_process(passed_jobs)
    
    platform_stats = {}
    for r in routing_results:
        for p in r.target_platforms:
            platform_stats[p] = platform_stats.get(p, 0) + 1
    
    results['phase_results']['intent_routing'] = {
        "processed_count": len(routing_results),
        "platform_distribution": platform_stats,
        "lbs_entities_detected": sum(
            1 for r in routing_results
            if r.intent_vector and getattr(r.intent_vector, 'lbs_entity', None)
        )
    }
    print(f"   分发目标: {json.dumps(platform_stats, ensure_ascii=False)}")
    
    # Phase 3: 内容工厂
    print("\n🏭 Phase 3: 内容资产生成...")
    factory = ContentFactory()
    assets = factory.batch_process(passed_jobs)
    
    results['phase_results']['content_factory'] = {
        "assets_generated": len(assets),
        "schemas_valid": sum(1 for a in assets if a.schema_validation_url is not None),
        "sample_schema_type": assets[0].json_ld.get('@type', 'N/A') if assets else None
    }
    print(f"   生成资产: {len(assets)} 套")
    
    # Phase 4 & 5
    results['phase_results']['api_signaler'] = {
        "status": "ready",
        "note": "需配置平台凭证(settings.local.yaml)"
    }
    results['phase_results']['monitoring'] = {
        "status": "active",
        "note": "dist_monitor已就绪，等待首次分发后启动监控"
    }


def run_server_mode(port: int = 8080, db_enabled: bool = False, web_ui: bool = True):
    """启动HTTP API服务模式（含Web UI控制面板）
    
    Args:
        port: 监听端口
        db_enabled: 是否启用数据库探针(/ready端点会检查DB连通性)
        web_ui: 是否启用Web UI可视化界面（默认开启）
    """
    try:
        from http.server import HTTPServer, BaseHTTPRequestHandler
        
        # 预初始化DB连接(如果启用)
        _db_instance = None
        if db_enabled:
            try:
                from database_backend import get_backend
                _db_instance = get_backend()
                _db_instance.connect()
                print("   ✅ SQLite数据库探针已启用")
            except Exception as e:
                print(f"   ⚠️ 数据库探针初始化失败: {e}")
                _db_instance = None
        
        # 初始化Web UI处理器
        _web_handler = None
        if web_ui:
            try:
                from web_ui import WebUIHandler
                _web_handler = WebUIHandler(geo_app=None)
                print("   ✅ Web UI 控制板已启用")
            except ImportError:
                print("   ⚠️ Web UI模块未找到，仅提供API端点")
        
        class GEORequestHandler(BaseHTTPRequestHandler):
            
            def do_GET(self):
                """GET请求处理器 — 顶层异常防护防止ERR_EMPTY_RESPONSE"""
                method = 'GET'
                try:
                    path = self.path.split('?')[0]

                    # === Favicon (避免404) ===
                    if path == '/favicon.ico' and _web_handler:
                        result = _web_handler._serve_favicon({'path': path})
                        self._send_response_dict(result)
                        return

                    # === SPA 入口 (前后端分离: 返回 static/index.html) ===
                    if path in ('/ui', '/dashboard'):
                        if _web_handler:
                            result = _web_handler._serve_spa({'path': path})
                            self._send_response_dict(result)
                        return

                    # === 静态资源服务 (前后端分离: static/*.css, *.js) ===
                    elif path.startswith('/static/') and _web_handler:
                        result = _web_handler._serve_static_file({'path': path})
                        self._send_response_dict(result)
                        return
                    
                    # === API Endpoints ===
                    if path == '/api/status' and _web_handler:
                        result = _web_handler._api_status({'path': path})
                        self._send_response_dict(result)
                        return
                    
                    elif path == '/api/pipeline/status':
                        self._send_json({
                            "version": "v2.0.0",
                            "web_ui": web_ui,
                            "modes_supported": ["pipeline", "db", "server", "import"],
                            "phases": {
                                "compliance_gate": {"status": "running"},
                                "intent_router": {"status": "running"},
                                "content_factory": {"status": "running"},
                                "auth_signaler": {"status": "configured"},
                                "dist_monitor": {
                                    "status": "ok" if _db_instance else "disabled"
                                }
                            },
                            "last_run": datetime.now().isoformat()
                        })
                    
                    elif path == '/api/stats' and _web_handler:
                        result = _web_handler._api_statistics({'path': path})
                        self._send_response_dict(result)
                        return
                    
                    elif path == '/api/config' and _web_handler:
                        if method == 'GET':
                            query_str = self.path.split('?', 1)[-1] if '?' in self.path else ''
                            if 'export' in parse_qs(query_str) or path.startswith('/api/config/export'):
                                result = _web_handler._api_config_export({'path': self.path})
                            else:
                                result = _web_handler._api_get_config({'path': path})
                        else:
                            self._send_json({"error": f"Method not allowed: {path}"}, 405)
                            return
                        self._send_response_dict(result)
                        return
                    
                    elif path == '/api/history' and _web_handler:
                        result = _web_handler._api_history({'path': path})
                        self._send_response_dict(result)
                        return
                    
                    elif path.startswith('/api/schema-preview') and _web_handler:
                        result = _web_handler._api_schema_preview({'path': self.path})
                        self._send_response_dict(result)
                        return

                    # === GEO 四阶段框架 API ===
                    elif path.startswith('/api/geo/') and _web_handler:
                        if path.startswith('/api/geo/audit'):
                            if path.startswith('/api/geo/audit/history') and method == 'GET':
                                result = _web_handler._api_audit_history({'path': self.path})
                            elif path.startswith('/api/geo/audit/save') and method == 'POST':
                                result = _web_handler._api_save_audit({'path': self.path, 'method': 'POST', 'body': b''})
                            elif path.startswith('/api/geo/audit/export') and method == 'GET':
                                result = _web_handler._api_audit_export({'path': self.path})
                            else:
                                result = _web_handler._api_geo_audit({'path': self.path})
                        elif path.startswith('/api/geo/org-schema'):
                            result = _web_handler._api_org_schema({'path': self.path})
                        elif path.startswith('/api/geo/faq-schema'):
                            result = _web_handler._api_faq_schema({'path': self.path})
                        elif path.startswith('/api/geo/breadcrumb'):
                            result = _web_handler._api_breadcrumb_schema({'path': self.path})
                        elif path == '/api/geo/framework':
                            result = _web_handler._api_framework_overview({'path': self.path})
                        else:
                            self._send_json({"error": f"GEO API not found: {path}"}, 404)
                            return
                        self._send_response_dict(result)
                        return

                    # === Phase 5 分发监控 API ===
                    elif path.startswith('/api/monitor/') and _web_handler:
                        if path.startswith('/api/monitor/citation'):
                            result = _web_handler._api_monitor_citation({'path': self.path})
                        elif path.startswith('/api/monitor/alerts'):
                            result = _web_handler._api_monitor_alerts({'path': self.path})
                        elif path.startswith('/api/monitor/rollback'):
                            result = _web_handler._api_monitor_rollback({'path': self.path})
                        elif path.startswith('/api/monitor/reports'):
                            result = _web_handler._api_monitor_reports({'path': self.path})
                        elif path.startswith('/api/monitor/check') and method == 'POST':
                            result = _web_handler._api_manual_check({'path': self.path, 'method': 'POST'})
                        else:
                            self._send_json({"error": f"Monitor API not found: {path}"}, 404)
                            return
                        self._send_response_dict(result)
                        return

                    elif path.startswith('/api/jobs') and _web_handler:
                        if path.startswith('/api/job/') and path.count('/') == 3:
                            result = _web_handler._api_get_job({'path': self.path})
                        else:
                            result = _web_handler._api_list_jobs({'path': self.path})
                        self._send_response_dict(result)
                        return
                    
                    elif path == '/api/db/stats':
                        if not _db_instance:
                            self._send_json({"error": "数据库未连接"}, 503)
                            return
                        stats = _db_instance.get_statistics() if hasattr(_db_instance, 'get_statistics') else {}
                        self._send_json(stats, ensure_ascii=False)
                    
                    # === Health Checks ===
                    elif path == '/health':
                        self._send_json({
                            "status": "healthy",
                            "version": "v2.0.0",
                            "has_web_ui": web_ui,
                            "timestamp": datetime.now(timezone(timedelta(hours=8))).isoformat(),
                        })
                    
                    elif path == '/ready':
                        readiness = {
                            "status": "ready",
                            "components": {
                                "pipeline": "ok",
                                "database": "not_configured",
                                "web_ui": "ok" if _web_handler else "disabled"
                            },
                            "timestamp": datetime.now(timezone(timedelta(hours=8))).isoformat()
                        }
                        
                        if _db_instance:
                            try:
                                test = _db_instance.test_connection() if hasattr(_db_instance, 'test_connection') else {}
                                readiness['components']['database'] = (
                                    "ok" if test.get('connected') else "error"
                                )
                                if not test.get('connected'):
                                    readiness['status'] = 'not_ready'
                                    readiness['db_error'] = test.get('error')
                            except Exception as e:
                                readiness['components']['database'] = f"error: {str(e)[:50]}"
                                readiness['status'] = 'not_ready'
                        
                        code = 200 if readiness['status'] == 'ready' else 503
                        self._send_json(readiness, code)
                    
                    # === Root → redirect ===
                    elif path == '/':
                        if web_ui:
                            self.send_response(302)
                            self.send_header('Location', '/ui')
                            self.end_headers()
                        else:
                            self._send_simple_html(_db_instance)
                    
                    else:
                        self._send_json({"error": "Not Found"}, 404)

                except Exception as e:
                    # [R-07] 全局异常防护: 防止未捕获异常导致ERR_EMPTY_RESPONSE
                    logger.error(f"[HTTP] GET {self.path.split('?')[0]} 未处理异常: {type(e).__name__}: {e}", exc_info=True)
                    try:
                        self.send_response(500)
                        self.send_header('Content-Type', 'application/json; charset=utf-8')
                        err_path = self.path.split('?')[0]
                        body = json.dumps({
                            "error": "Internal Server Error",
                            "detail": f"{type(e).__name__}: {str(e)[:200]}",
                            "path": err_path,
                            "method": "GET"
                        }, ensure_ascii=False).encode('utf-8')
                        self.send_header('Content-Length', str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                    except Exception:
                        pass  # 连接可能已断开，静默忽略
                path = self.path.split('?')[0]
                try:
                    content_length = int(self.headers.get('Content-Length', 0))
                    body = self.rfile.read(content_length) if content_length > 0 else b''
                
                    # CSV文件上传
                    if path == '/api/pipeline/upload' and _web_handler:
                        content_type = self.headers.get('Content-Type', '')
                        result = _web_handler._api_csv_upload({
                            'content-type': content_type,
                            'body': body,
                            'path': path
                        })
                        self._send_response_dict(result)
                        return
                    
                    # 执行流水线
                    elif path == '/api/pipeline/run' and _web_handler:
                        result = _web_handler._api_pipeline_run({
                            'body': body.decode('utf-8', errors='replace'),
                            'path': path
                        })
                        self._send_response_dict(result)
                        return
                    
                    # 配置导入
                    elif path == '/api/config/import' and _web_handler:
                        result = _web_handler._api_config_import({
                            'body': body.decode('utf-8', errors='replace'),
                            'path': path,
                            'method': 'POST'
                        })
                        self._send_response_dict(result)
                        return
                    
                    # 审计保存
                    elif path == '/api/geo/audit/save' and _web_handler:
                        result = _web_handler._api_save_audit({
                            'body': body.decode('utf-8', errors='replace'),
                            'path': path,
                            'method': 'POST'
                        })
                        self._send_response_dict(result)
                        return
                    
                    else:
                        self._send_json({"error": f"Not Found: {path}"}, 404)

                except Exception as e:
                    logger.error(f"[HTTP] POST {path} 未处理异常: {type(e).__name__}: {e}", exc_info=True)
                    try:
                        self.send_response(500)
                        self.send_header('Content-Type', 'application/json; charset=utf-8')
                        body = json.dumps({"error": "Internal Server Error", "detail": str(e)[:200]}, ensure_ascii=False).encode('utf-8')
                        self.send_header('Content-Length', str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                    except Exception:
                        pass

                except Exception as e:
                    # [R-07] 全局异常防护: 防止未捕获异常导致ERR_EMPTY_RESPONSE
                    logger.error(f"[HTTP] GET {path} 未处理异常: {type(e).__name__}: {e}", exc_info=True)
                    try:
                        self.send_response(500)
                        self.send_header('Content-Type', 'application/json; charset=utf-8')
                        body = json.dumps({
                            "error": "Internal Server Error",
                            "detail": f"{type(e).__name__}: {str(e)[:200]}",
                            "path": path,
                            "method": method
                        }, ensure_ascii=False).encode('utf-8')
                        self.send_header('Content-Length', str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                    except Exception:
                        pass  # 连接可能已断开，静默忽略

            def do_DELETE(self):
                path = self.path.split('?')[0]
                try:
                    # DELETE /api/job/:id
                    if path.startswith('/api/job/') and _web_handler:
                        result = _web_handler._api_delete_job({'path': path})
                        # Handle 204 No Content
                        if result.get('status') == 204:
                            self.send_response(204)
                            self.end_headers()
                            return
                        self._send_response_dict(result)
                        return

                    else:
                        self._send_json({"error": f"Not Found: {path}"}, 404)

                except Exception as e:
                    logger.error(f"[HTTP] DELETE {path} 未处理异常: {type(e).__name__}: {e}", exc_info=True)
                    try:
                        self.send_response(500)
                        self.send_header('Content-Type', 'application/json; charset=utf-8')
                        body = json.dumps({"error": "Internal Server Error", "detail": str(e)[:200]}, ensure_ascii=False).encode('utf-8')
                        self.send_header('Content-Length', str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                    except Exception:
                        pass

            def do_PUT(self):
                path = self.path.split('?')[0]
                try:
                    content_length = int(self.headers.get('Content-Length', 0))
                    body = self.rfile.read(content_length) if content_length > 0 else b''

                    # PUT /api/config
                    if path == '/api/config' and _web_handler:
                        result = _web_handler._api_update_config({
                            'body': body.decode('utf-8', errors='replace'),
                            'path': path
                        })
                        self._send_response_dict(result)
                        return

                    else:
                        self._send_json({"error": f"Not Found: {path}"}, 404)

                except Exception as e:
                    logger.error(f"[HTTP] PUT {path} 未处理异常: {type(e).__name__}: {e}", exc_info=True)
                    try:
                        self.send_response(500)
                        self.send_header('Content-Type', 'application/json; charset=utf-8')
                        body = json.dumps({"error": "Internal Server Error", "detail": str(e)[:200]}, ensure_ascii=False).encode('utf-8')
                        self.send_header('Content-Length', str(len(body)))
                        self.end_headers()
                        self.wfile.write(body)
                    except Exception:
                        pass
            def _send_response_dict(self, result):
                """发送Web UI处理器的结果"""
                self.send_response(result.get('status', 200))
                headers = result.get('headers', {})
                for key, value in headers.items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(result.get('body', b''))
            
            def _send_json(self, data, status=200):
                """发送JSON响应"""
                body = json.dumps(data, ensure_ascii=False, default=str).encode('utf-8')
                self.send_response(status)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            
            def _send_simple_html(self, db_inst):
                """无UI模式下的简单HTML页面"""
                db_ok = db_inst is not None
                db_name = '?'
                if db_ok:
                    try:
                        t = db_inst.test_connection() if hasattr(db_inst, 'test_connection') else {}
                        db_name = t.get('database', t.get('tables_exist', ['?'])[0] if isinstance(t.get('tables_exist'), list) else '?')
                    except Exception:
                        pass

                html = """<!DOCTYPE html>
<html><head><title>GEO Pipeline v2.1</title>
<meta charset="utf-8"><style>
body{font-family:-apple-system,sans-serif;max-width:900px;margin:40px auto;padding:0 20px;color:#333}
h1{color:#1a73e8}.card{background:#f9fafb;border-radius:8px;padding:20px;margin:15px 0}
.ok{color:#059669}.warn{color:#d97706} table{width:100%;border-collapse:collapse}
th,td{padding:8px 12px;text-align:left;border-bottom:1px solid #e5e7eb}
</style></head><body>
<h1>🚀 松江快聘 GEO Pipeline <small>v2.1 (SQLite)</small></h1>
<div class="card"><h3>系统状态</h3><table>
<tr><td>合规闸门</td><td class="ok">✅</td></tr>
<tr><td>意图路由</td><td class="ok">✅</td></tr>
<tr><td>内容工厂</td><td class="ok">✅</td></tr>
<tr><td>分发监控</td><td class="ok">✅</td></tr>
<tr><td>SQLite</td><td class="ok">✅ """ + str(db_name) + """</td></tr>
</table></div>
<p style='color:#666'>💡 访问 <a href='/ui'>/ui</a> 打开完整控制台 | Powered by GEO-Pipeline © 2026</p>
</body></html>"""
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(html.encode('utf-8'))
            
            def log_message(self, format, *args):
                # 仅记录错误和关键信息，避免刷屏
                if '200' not in str(args):
                    logger.debug(f"[HTTP] {format % args}")
        
        server = HTTPServer(('0.0.0.0', port), GEORequestHandler)
        
        ui_url = f"http://localhost:{port}"
        ui_link = f"\n   🎨 Web UI: http://localhost:{port}/ui" if web_ui else ""
        
        print(f"\n{'='*60}")
        print(f"🌐 GEO Pipeline Server v2.0 启动完成")
        print(f"{'='*60}")
        print(f"   地址:       {ui_url}")
        print(f"   健康检查:   {ui_url}/health")
        print(f"   就绪探测:   {ui_url}/ready")
        if web_ui:
            print(f"   🎨 控制台:   {ui_url}/ui")
        print(f"   API状态:    {ui_url}/api/pipeline/status")
        print(f"   DB探针:     {'✅ 已启用' if _db_instance else '⚠️ 未配置 (--with-db)'}")
        print(f"\n   按 Ctrl+C 停止服务")
        print(f"{'='*60}\n")
        
        # 注册信号处理器（优雅停机，仅主线程有效）
        import signal
        def _shutdown_handler(signum, frame):
            logger.info(f"接收到信号 {signum}，正在优雅关闭服务器...")
            logger.info("正在进行中的任务将完成当前批次后停止")
            server.shutdown()
        
        try:
            signal.signal(signal.SIGTERM, _shutdown_handler)
            signal.signal(signal.SIGINT, _shutdown_handler)
        except (ValueError, OSError):
            # 子线程中无法注册信号处理器（signal only works in main thread）
            logger.debug("非主线程环境，跳过信号处理器注册")
        
        # 自动打开浏览器（双击运行时）
        import webbrowser
        webbrowser.open(ui_url, new=2, autoraise=True)

        server.serve_forever()
        
    except ImportError:
        print("❌ HTTP服务模式需要标准库支持")


def main():
    """主入口"""
    # 初始化系统 (配置管理器 + 数据库后端)
    _init_system()
    
    parser = argparse.ArgumentParser(
        description="021kp.com GEO自动化运营系统 - 主控制器 (v2.1 SQLite-only)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
运行模式:
  pipeline  标准GEO流水线(CSV输入 → 合规→路由→生成)
  db        数据库驱动模式(从SQLite读取→GEO处理)
  server    HTTP API服务模式(含/health+/ready健康检查端点)
  import    数据导入模式(CSV→SQLite批量写入)

示例用法:
  # 全流程模式（CSV输入，默认使用SQLite存储）
  python -m src.main --mode pipeline --csv data/jobs.csv
  
  # 从SQLite读取并处理数据
  python -m src.main --mode db
  
  # HTTP服务（含Web UI控制台）
  python -m src.main --mode server --port 8080
  
  # 导入数据到SQLite
  python -m src.main --mode import --csv data/jobs.csv

  # 单模块测试
  python src/config_manager.py          # 配置诊断
  python src/database_backend.py         # 数据库诊断
  python -m src/compliance_gate.py      # 合规闸门
  python -m src/intent_router.py     # 意图路由
  python -m src/content_factory.py      # 内容工厂
        """
    )
    
    parser.add_argument(
        "--mode", "-m",
        choices=["pipeline", "db", "server", "import"],
        default="server",
        help="运行模式: pipeline/db/server/import (默认: server)"
    )
    
    # Pipeline模式参数
    parser.add_argument("--csv", "-c", help="输入CSV文件路径")
    parser.add_argument("--json", "-j", help="单条岗位JSON字符串")
    
    # DB模式参数
    parser.add_argument("--limit", "-l", type=int, default=100, help="DB模式最大处理条数(默认100)")
    parser.add_argument("--category", help="行业类别过滤(manufacturing/ecommerce/it等)")
    parser.add_argument("--urgent-only", action="store_true", help="仅处理急招岗位")
    parser.add_argument(
        "--db-type", "-t",
        choices=["sqlite"],
        default=None,
        help="强制指定数据库类型 (默认: sqlite)"
    )
    
    # Server模式参数
    parser.add_argument("--port", "-p", type=int, default=8080, help="HTTP服务端口(默认8080)")
    parser.add_argument("--with-db", action="store_true", help="Server模式启用数据库探针(自动根据配置选择DB类型)")
    parser.add_argument("--web-ui", action="store_true", default=True, help="启用Web UI控制面板(默认开启)")
    parser.add_argument("--no-web-ui", dest="web_ui", action="store_false", help="禁用Web UI")
    
    # Import模式参数
    parser.add_argument("--dry-run", action="store_true", help="Import试运行(不实际写入)")
    
    args = parser.parse_args()
    
    # 如果指定了 --db-type，设置环境变量供 ConfigManager 读取
    if getattr(args, 'db_type', None):
        os.environ['DB_TYPE'] = args.db_type
    
    # 路由到对应运行模式
    if args.mode == "server":
        # Server 模式: --with-db 启用SQLite探针
        db_enabled = args.with_db
        run_server_mode(port=args.port, db_enabled=db_enabled, web_ui=args.web_ui)
        
    elif args.mode == "db":
        results = run_db_pipeline_mode(
            limit=args.limit,
            category_filter=args.category,
            urgent_only=args.urgent_only
        )
        _print_results(results)
        
    elif args.mode == "import":
        if not args.csv:
            print("❌ Import模式需要 --csv 参数指定文件路径")
            sys.exit(1)
        results = run_import_mode(csv_path=args.csv, dry_run=args.dry_run)
        _print_results(results)
        
    else:
        # 默认pipeline模式
        results = run_pipeline_mode(csv_path=args.csv, json_input=args.json)
        _print_results(results)


def _print_results(results: dict):
    """格式化输出结果"""
    if results.get("status") not in ("success", "empty", "dry_run"):
        print(f"\n❌ 执行失败: {results.get('error_message', '未知错误')}")
        sys.exit(1)

    print(f"\n{'='*60}")
    print(f"✅ 执行完成 | 状态: {results.get('status').upper()} | 模式: {results.get('mode', 'pipeline')}")
    print(f"{'='*60}")

    # 输出摘要信息
    summary_keys = {
        'db_source': '📊 数据库',
        'phase_results': '🔄 处理阶段',
        'import_stats': '📥 导入统计'
    }
    for key, label in summary_keys.items():
        if key in results and results[key]:
            print(f"\n{label}:")
            print(f"   {json.dumps(results[key], ensure_ascii=False, indent=2)[:500]}")


if __name__ == "__main__":
    main()
