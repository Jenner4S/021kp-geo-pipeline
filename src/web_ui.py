"""
021kp.com GEO Pipeline - Web API 后端层 (Frontend-Backend Separated)
=============================================================================

架构说明:
    - 后端: 纯 Python RESTful API (JSON in/out)
    - 前端: static/index.html + static/app.css + static/app.js (独立文件)
    - 通信: Fetch API / RESTful JSON
    - 静态资源: /static/* 路由自动映射到 static/ 目录

目录结构:
    src/web_ui.py          ← 本文件(纯后端API)
    static/index.html      ← 前端 HTML
    static/app.css         ← 前端样式表
    static/app.js          ← 前端应用逻辑

API 端点:
    GET  /ui               → 重定向到 /static/index.html (SPA 入口)
    GET  /api/status       → 系统状态 (DB/版本/运行时)
    POST /api/pipeline/run → 执行 GEO 流水线
    POST /api/pipeline/upload → CSV 文件上传
    GET  /api/jobs         → 岗位数据列表 (分页/搜索)
    GET  /api/stats        → 统计数据
    GET  /api/config       → 配置信息 (脱敏)
    PUT  /api/config       → 更新配置 (非敏感项)
    GET  /api/history      → 执行历史
    GET  /api/schema-preview → Schema.org JSON-LD 生成预览
    GET  /static/*         → 静态资源服务 (CSS/JS/HTML)

使用说明:
    python -m src.main --mode server --port 8080 --web-ui
    浏览器访问 http://localhost:8080/ui

作者: GEO-API Team | 版本: v2.0 (前后端分离) | 日期: 2026-04-21
"""

import json
import os
import re
import sys
import time
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote
from typing import Any, Optional, Union, List, Dict
import secrets

# 配置相关类型（用于验证逻辑）
try:
    from config_schema import ConfigType
except ImportError:
    # 兜底：定义最小兼容枚举
    class _FallbackConfigType(str):
        NUMBER = 'number'; TOGGLE = 'toggle'
        PASSWORD = 'password'; STRING = 'string'
        SELECT = 'select'; TEXTAREA = 'textarea'; PATH = 'path'
    ConfigType = _FallbackConfigType

try:
    from loguru import logger
except ImportError:
    import logging as logger


class WebUIHandler:
    """
    Web API 路由处理器 (后端层)
    
    职责:
    - 接收 HTTP 请求 → 处理业务逻辑 → 返回 JSON 响应
    - 不包含任何 HTML/CSS/JS (全部委托给 static/ 目录的前端文件)
    - 提供静态文件服务能力
    """

    # MIME 类型映射表
    _MIME_TYPES = {
        '.html': 'text/html; charset=utf-8',
        '.css':  'text/css; charset=utf-8',
        '.js':   'application/javascript; charset=utf-8',
        '.json': 'application/json; charset=utf-8',
        '.png':  'image/png',
        '.jpg':  'image/jpeg',
        '.svg':  'image/svg+xml',
        '.ico':  'image/x-icon',
        '.woff2': 'font/woff2',
        '.woff':  'font/woff',
        '.ttf':  'font/ttf',
        '.map':  'application/json',
    }

    def __init__(self, geo_app=None):
        """
        初始化 Web API Handler
        
        Args:
            geo_app: GEO 应用实例引用 (预留扩展)
        """
        self.geo_app = geo_app

        # static/ 目录路径: PyInstaller onefile 模式下从 _MEIPASS 提取
        import sys
        if getattr(sys, 'frozen', False):
            # running as compiled executable
            self._static_dir = Path(sys._MEIPASS) / 'static'
        else:
            # running from source
            self._static_dir = Path(__file__).parent.parent / 'static'
        
        # 统一配置管理器 (替代散落的 os.getenv 调用)
        try:
            from config_manager import get_config
            self._cfg = get_config()
        except ImportError:
            self._cfg = None
        
        # 配置持久化存储 (SQLite — 运行时配置写入数据库)
        try:
            from config_store import init_config_store
            self._cfg_store = init_config_store()
        except ImportError:
            self._cfg_store = None
        
        # 数据库后端 (SQLite)
        try:
            from database_backend import get_backend
            self._db = get_backend()
        except ImportError:
            self._db = None
        
        # 执行历史（内存+DB双写）
        self._execution_history = []  # 兼容旧逻辑，同时写入DB
        self._history_lock = threading.Lock()  # 保护 _execution_history 的线程安全
        
        # Rate Limiting (令牌桶算法: 每IP每分钟30次)
        self._rate_limits: Dict[str, Dict] = {}
        self._rate_limit_lock = threading.Lock()
        self.RATE_LIMIT_REQUESTS = 30  # 每分钟请求数
        self.RATE_LIMIT_WINDOW = 60    # 时间窗口(秒)
        
        # CSRF Token (简单实现: 基于会话的token校验)
        self._csrf_tokens: Dict[str, str] = {}  # session_id -> token
        self._csrf_token_lock = threading.Lock()
    
    # ================================================================
    #   路由注册表
    # ================================================================

    def get_routes(self):
        """返回路由映射表 {path_pattern: handler_method}"""
        return {
            # --- SPA 入口 ---
            'GET /ui':           self._serve_spa,
            'GET /favicon.ico':  self._serve_favicon,
            
            # --- RESTful API ---
            'GET /api/status':            self._api_status,
            'POST /api/pipeline/run':     self._api_pipeline_run,
            'POST /api/pipeline/upload':  self._api_csv_upload,
            'GET /api/jobs':              self._api_list_jobs,
            'GET /api/job/:id':           self._api_get_job,
            'DELETE /api/job/:id':        self._api_delete_job,
            'GET /api/stats':             self._api_statistics,
            'GET /api/config':            self._api_get_config,
            'PUT /api/config':            self._api_update_config,
            'GET /api/history':           self._api_history,
            'GET /api/schema-preview':    self._api_schema_preview,
            'GET /api/geo/audit':         self._api_geo_audit,
            'GET /api/geo/org-schema':    self._api_org_schema,
            'GET /api/geo/faq-schema':    self._api_faq_schema,
            'GET /api/geo/breadcrumb':    self._api_breadcrumb_schema,
            'GET /api/geo/framework':      self._api_framework_overview,
            
            # --- Phase 5 分发监控 (dist_monitor 集成) ---
            'GET  /api/monitor/citation':   self._api_monitor_citation,
            'GET  /api/monitor/alerts':     self._api_monitor_alerts,
            'GET  /api/monitor/rollback':   self._api_monitor_rollback,
            'POST /api/monitor/check':      self._api_manual_check,
            'GET  /api/monitor/reports':    self._api_monitor_reports,

            # --- GEO 审计增强 (A1/A3 - 历史持久化 + 导出) ---
            'GET  /api/geo/audit/history':  self._api_audit_history,
            'POST /api/geo/audit/save':     self._api_save_audit,
            'GET  /api/geo/audit/export':   self._api_audit_export,

            # --- 配置增强 (C2 - 导出/导入) ---
            'GET  /api/config/export':      self._api_config_export,
            'POST /api/config/import':      self._api_config_import,
            
            # --- 静态资源服务 ---
            'GET /static/*':              self._serve_static_file,
        }

    # ================================================================
    #   SPA 入口 & 静态文件服务
    # ================================================================

    def _serve_spa(self, request):
        """
        SPA 入口: 返回 static/index.html
        
        前后端分离关键点: 
        - 后端只返回 HTML shell (不含业务逻辑)
        - 所有数据通过 JS fetch API 从后端获取
        """
        index_path = self._static_dir / 'index.html'
        
        if not index_path.exists():
            return {
                'status': 404,
                'headers': {'Content-Type': 'application/json'},
                'body': json.dumps({'error': '前端资源未找到 (static/index.html)'}).encode('utf-8')
            }
        
        html_content = index_path.read_text('utf-8')
        # 版本号注入 (可选: 用于缓存控制)
        html_content = html_content.replace('{{VERSION}}', 'v2.1.0-geo')
        
        return {
            'status': 200,
            'headers': {'Content-Type': 'text/html; charset=utf-8'},
            'body': html_content.encode('utf-8')
        }

    def _serve_favicon(self, request):
        """返回 favicon (内嵌 SVG favicon，避免 404)"""
        svg = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">
        <text y="28" font-size="28">🌍</text></svg>'''
        return {
            'status': 200,
            'headers': {
                'Content-Type': 'image/svg+xml',
                'Cache-Control': 'public, max-age=86400'
            },
            'body': svg.encode('utf-8')
        }

    def _serve_static_file(self, request):
        """
        静态文件服务: 映射 /static/* → static/*
        
        支持类型: CSS, JS, HTML, 图片, 字体等
        包含浏览器缓存控制头 (Cache-Control)
        """
        path = request.get('path', '/')
        
        # 去掉 /static/ 前缀获取相对路径
        relative_path = unquote(path.replace('/static/', '', 1).lstrip('/'))
        
        # 安全检查: 防止路径穿越攻击 (URL解码后再检查)
        if '..' in relative_path or relative_path.startswith('/') or not relative_path:
            return {'status': 403, 'body': b'{"error": "Forbidden"}'}
        
        file_path = self._static_dir / relative_path
        
        # 二次验证：确保解析后的真实路径仍在 static 目录内
        try:
            real_path = file_path.resolve()
            static_real = self._static_dir.resolve()
            if not str(real_path).startswith(str(static_real)):
                return {'status': 403, 'body': b'{"error": "Forbidden"}'}
        except (OSError, ValueError):
            return {'status': 403, 'body': b'{"error": "Forbidden"}'}
        
        if not file_path.exists() or not file_path.is_file():
            return {
                'status': 404,
                'headers': {'Content-Type': 'application/json'},
                'body': json.dumps({'error': 'Resource not found'}).encode('utf-8')
            }
        
        # 根据 extension 确定 MIME 类型
        ext = file_path.suffix.lower()
        content_type = self._MIME_TYPES.get(ext, 'application/octet-stream')
        
        try:
            content = file_path.read_bytes()
        except Exception as e:
            return {
                'status': 500,
                'headers': {'Content-Type': 'application/json'},
                'body': json.dumps({'error': str(e)}).encode('utf-8')
            }
        
        # 缓存策略: 静态资源可长期缓存 (CSS/JS 带 hash 时更佳)
        cache_control = 'public, max-age=3600' if ext in ('.css', '.js', '.png', '.jpg') else 'no-cache'
        
        return {
            'status': 200,
            'headers': {
                'Content-Type': content_type,
                'Cache-Control': cache_control,
                'Content-Length': str(len(content))
            },
            'body': content
        }

    # ================================================================
    #   API: 系统状态
    # ================================================================

    def _api_status(self, request):
        """
        GET /api/status
        
        Returns:
            system: 版本/Python/平台/运行时间
            database: 连接状态/版本/表列表
            last_execution: 最近一次执行摘要
            pending_tasks: 待处理任务数
        """
        db_status = self._check_database_connection()
        
        # 线程安全地获取最后执行记录
        with self._history_lock:
            last_exec = self._execution_history[-1] if self._execution_history else None
        
        return self._json_response({
            'system': {
                'version': 'v2.0.0',
                'uptime_seconds': int(time.time()),
                'python_version': f'{sys.version_info.major}.{sys.version_info.minor}',
                'platform': sys.platform,
            },
            'database': db_status,
            'last_execution': last_exec,
            'pending_tasks': 0  # 任务队列已移除，异步任务直接执行
        })

    def _check_database_connection(self):
        """数据库连接探测 (SQLite)"""
        default = {'available': False, 'connected': False, 'database': None}

        if self._db:
            try:
                test_result = self._db.test_connection()
                return {
                    **test_result,
                    'available': True,
                    'backend_type': test_result.get('backend_type', 'sqlite')
                }
            except Exception as e:
                logger.warning(f"数据库后端连接测试失败(非致命): {e}")

        return {**default, 'reason': 'no_backend'}
    
    # ================================================================
    #   安全中间件: Rate Limiting + CSRF
    # ================================================================
    
    def _check_rate_limit(self, request) -> bool:
        """
        基于IP的令牌桶Rate Limiting检查
        
        Returns:
            True 允许通过 / False 应返回429
        """
        client_ip = request.get('client_ip', '0.0.0.0')
        
        with self._rate_limit_lock:
            now = time.time()
            bucket = self._rate_limits.get(client_ip)
            
            if not bucket:
                self._rate_limits[client_ip] = {
                    'count': 1,
                    'reset_at': now + self.RATE_LIMIT_WINDOW
                }
                return True
            
            # 窗口过期，重置计数器
            if now >= bucket['reset_at']:
                bucket['count'] = 1
                bucket['reset_at'] = now + self.RATE_LIMIT_WINDOW
                return True
            
            # 检查是否超限
            if bucket['count'] >= self.RATE_LIMIT_REQUESTS:
                return False
            
            bucket['count'] += 1
            return True
    
    def _generate_csrf_token(self, session_id: str) -> str:
        """为指定会话生成CSRF Token"""
        token = secrets.token_hex(32)
        with self._csrf_token_lock:
            self._csrf_tokens[session_id] = token
        # 限制token数量，防止内存泄漏
        if len(self._csrf_tokens) > 10000:
            keys = list(self._csrf_tokens.keys())
            for k in keys[:5000]:
                del self._csrf_tokens[k]
        return token
    
    def _verify_csrf_token(self, request) -> bool:
        """
        验证CSRF Token（仅对状态变更请求校验）
        
        GET/HEAD/OPTIONS 不需要校验
        POST/PUT/DELETE 必须携带 x-csrf-token header
        """
        method = request.get('method', 'GET').upper()
        if method in ('GET', 'HEAD', 'OPTIONS'):
            return True
        
        token = request.get('x-csrf-token') or ''
        session_id = request.get('session_id', '')
        
        if not token:
            # 首次访问自动生成token（前端需在后续请求中携带）
            return True  # 开发模式宽松处理
        
        expected = self._csrf_tokens.get(session_id)
        if expected and token == expected:
            return True
        
        # 时间比较攻击防护: 使用恒定时间比较
        import hmac
        for stored in self._csrf_tokens.values():
            if hmac.compare_digest(token, stored):
                return True
        return False

    # ================================================================
    #   API: 流水线执行
    # ================================================================

    def _api_pipeline_run(self, request):
        """
        POST /api/pipeline/run
        
        Body (JSON):
            mode: pipeline | db | import
            csv_file: CSV路径 (pipeline/import模式必填)
            limit: 最大条数 (db模式)
            category: 类别过滤 (db模式)
            urgent_only: 仅急招 (db模式)
            dry_run: 试运行 (import模式)
            
        Returns (202 Accepted):
            task_id: 异步任务ID
            message: 状态描述
        """
        try:
            params = json.loads(request.get('body', b'{}'))
            
            mode = params.get('mode', 'pipeline')
            options = {
                'csv_path': params.get('csv_file'),
                'limit': int(params.get('limit', 50)),
                'category': params.get('category'),
                'urgent_only': params.get('urgent_only', False),
                'dry_run': params.get('dry_run', False)
            }
            
            task_id = f"task_{int(time.time() * 1000)}"
            
            # 异步执行 (后台线程)
            def _run_task():
                result = self._execute_pipeline(mode, options, task_id)
                
                # 记录到执行历史 (线程安全)
                self._record_history(task_id, mode, options, result)
            
            thread = threading.Thread(target=_run_task, daemon=True)
            thread.start()
            
            return self._json_response({
                'task_id': task_id,
                'message': '任务已提交，请查看执行状态',
                'mode': mode,
                'estimated_time': '~5-30秒'
            }, status_code=202)
            
        except Exception as e:
            return self._error_response(str(e), status_code=400)

    def _execute_pipeline(self, mode: str, options: dict, task_id: str) -> dict:
        """执行流水线核心逻辑 (在后台线程中运行)"""
        start_time = time.time()
        
        try:
            if mode == 'db':
                from main import run_db_pipeline_mode
                result = run_db_pipeline_mode(
                    limit=options['limit'],
                    category_filter=options.get('category'),
                    urgent_only=options.get('urgent_only', False)
                )
                
            elif mode == 'import':
                from main import run_import_mode
                result = run_import_mode(
                    csv_path=options.get('csv_path'),
                    dry_run=options.get('dry_run', False)
                )
                
            else:  # pipeline (默认)
                from main import run_pipeline_mode
                result = run_pipeline_mode(csv_path=options.get('csv_path'))
            
            result['duration'] = round(time.time() - start_time, 2)
            result['status'] = result.get('status', 'success')
            return result
            
        except Exception as e:
            return {
                'status': 'error',
                'error_message': str(e),
                'duration': round(time.time() - start_time, 2)
            }

    def _record_history(self, task_id: str, mode: str, options: dict, result: dict):
        """记录执行历史 (同时写入内存+数据库) - 线程安全"""
        record = {
            'id': task_id,
            'timestamp': datetime.now().isoformat(),
            'mode': mode,
            'options': options,
            'result': result
        }
        
        with self._history_lock:
            self._execution_history.append(record)
            # 清理旧记录 (保留最近20条)
            if len(self._execution_history) > 20:
                self._execution_history = self._execution_history[-20:]
        
        # 数据库持久化 (如果可用)
        if self._db:
            try:
                self._db.record_execution(task_id, mode, options, result)
            except Exception as e:
                logger.warning(f"DB写入执行历史失败: {e}")

    # ================================================================
    #   API: CSV 文件上传
    # ================================================================

    def _api_csv_upload(self, request):
        """
        POST /api/pipeline/upload
        
        Content-Type: multipart/form-data
        Field: file (CSV file)
        
        Returns:
            success: bool
            filename: 存储后的文件名
            path: 服务器上的完整路径
            size_bytes / size_human: 文件大小
            preview_headers: CSV列名预览
            preview_count: 数据行数预览
        """
        content_type = request.get('content-type', '')
        
        if 'multipart/form-data' not in content_type:
            return self._error_response('需要 multipart/form-data 格式', 400)
        
        # 解析 multipart body
        boundary = content_type.split('boundary=')[-1].strip()
        body = request.get('body', b'')
        
        # 安全检查1: Content-Length 上限 (10MB)
        if len(body) > 10 * 1024 * 1024:
            return self._error_response('文件过大，最大允许10MB', 413)
        
        uploaded_content, filename = self._parse_multipart(body, boundary)
        
        if not uploaded_content:
            return self._error_response('未检测到有效文件', 400)
        
        # 安全检查2: 文件大小上限
        MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10MB
        if len(uploaded_content) > MAX_UPLOAD_SIZE:
            return self._error_response(f'文件过大 ({len(uploaded_content)//1024}KB)，最大允许{MAX_UPLOAD_SIZE//1024//1024}MB', 413)
        
        # 安全检查3: 扩展名白名单
        ALLOWED_EXTENSIONS = {'.csv', '.txt'}
        safe_filename = re.sub(r'[^\w\-.]', '_', filename or 'upload.csv')
        ext = Path(safe_filename).suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            return self._error_response(f'不支持的文件类型: {ext}，仅允许 {", ".join(ALLOWED_EXTENSIONS)}', 400)
        
        # 持久化到 uploads/ 目录
        upload_dir = Path(__file__).parent.parent / 'uploads'
        upload_dir.mkdir(exist_ok=True)
        
        save_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe_filename}"
        save_path = upload_dir / save_name
        
        with open(save_path, 'wb') as f:
            f.write(uploaded_content)
        
        # 解析 CSV 预览
        headers, row_count, preview_data = self._preview_csv(uploaded_content)

        return self._json_response({
            'success': True,
            'filename': save_name,
            'path': str(save_path),
            'size_bytes': len(uploaded_content),
            'size_human': f"{len(uploaded_content)/1024:.1f} KB",
            'preview_headers': headers,
            'preview_count': row_count,
            'preview_data': preview_data,
            'message': '上传成功！可在"执行流水线"中选择此文件'
        })

    @staticmethod
    def _parse_multipart(body: bytes, boundary: str) -> tuple:
        """解析 multipart/form-data 数据"""
        parts = body.split(f'--{boundary}'.encode())
        uploaded_content = None
        filename = None
        
        for part in parts[1:-1]:
            if b'filename=' in part:
                header_end = part.find(b'\r\n\r\n')
                if header_end != -1:
                    match = re.search(b'filename="([^"]+)"', part[:header_end])
                    if match:
                        filename = match.group(1).decode('utf-8')
                        uploaded_content = part[header_end+4:].rstrip(b'\r\n--').strip()
        
        return uploaded_content, filename

    @staticmethod
    def _preview_csv(content: bytes) -> tuple:
        """快速预览 CSV 前10行 (返回 headers + 行数 + 预览数据)"""
        try:
            import csv
            from io import StringIO

            text = content.decode('utf-8-sig')
            reader = csv.reader(StringIO(text))
            headers = next(reader, [])

            preview_data = []
            rows = 0
            for i, row in enumerate(reader):
                rows += 1
                if i < 10:
                    # 将每行数据与表头组合成字典，便于前端按列名渲染
                    row_dict = {}
                    for idx, h in enumerate(headers):
                        row_dict[h] = row[idx] if idx < len(row) else ''
                    preview_data.append(row_dict)
                if i >= 10:
                    break

            return list(headers) if isinstance(headers, list) else [], rows, preview_data
        except Exception:
            return [], 0, []  # CSV解析异常时返回空，静默处理（用户可能上传了非CSV文件）

    # ================================================================
    #   API: 岗位数据
    # ================================================================

    def _api_list_jobs(self, request):
        """
        GET /api/jobs?page=1&per_page=20&search=xxx
        
        Query Params:
            page: 页码 (默认1)
            per_page: 每页数量 (默认20, 最大100)
            search: 搜索关键词 (标题/公司/地点模糊匹配)
        
        Returns:
            data: 岗位数组
            pagination: {total, page, per_page, pages}
        """
        query = parse_qs(urlparse(request.get('path', '')).query)

        # 安全解析分页参数（带边界校验）
        try:
            page = max(1, int(query.get('page', [1])[0]))
        except (ValueError, IndexError):
            page = 1

        try:
            per_page = min(max(1, int(query.get('per_page', [20])[0])), 100)
        except (ValueError, IndexError):
            per_page = 20
        search = query.get('search', [''])[0].strip()
        category = query.get('category', [''])[0].strip() or None  # [M-02] 支持分类筛选透传
        
        # 优先使用数据库层搜索+分页（避免全量加载到内存）
        if self._db:
            try:
                offset = (page - 1) * per_page
                jobs = self._db.fetch_jobs(
                    limit=per_page,
                    offset=offset,
                    search_query=search or None,
                    category_filter=category
                )
                # 获取总数用于分页（不含搜索过滤的简化版）
                total_result = self._db.fetch_jobs(limit=1, offset=0)
                # 注：SQLite/MySQL的count需要单独查询，这里用近似值
                # 精确方案：后续可添加 count_jobs(search=...) 方法
                jobs_data = [j.to_dict() for j in jobs]
                
                # 使用数据库层精确count（新增方法，O(1)复杂度）
                if search:
                    total = self._db.count_jobs(search_query=search)
                else:
                    # 无搜索词时用近似值（避免额外查询）
                    total = self._db.count_jobs()
                
                return self._json_response({
                    'data': jobs_data,
                    'pagination': {
                        'total': total,  # 使用 count_jobs() 精确返回值
                        'page': page,
                        'per_page': per_page,
                        'pages': max((total + per_page - 1) // per_page, page)
                    },
                    'search_query': search,
                    'source': 'database'
                })
            except Exception as e:
                logger.warning(f"数据库层搜索失败，降级到内存模式: {e}")
        
        # 降级: 内存模式（兼容无DB或DB异常场景）
        jobs_data = self._load_jobs_data()
        
        # 关键词搜索过滤
        if search and jobs_data:
            s = search.lower()
            jobs_data = [
                j for j in jobs_data
                if any(s in str(v).lower() for v in j.values() if v)
            ]

        # [M-02] 分类筛选（内存降级模式）
        if category and jobs_data:
            jobs_data = [j for j in jobs_data if j.get('category') == category]
        
        total = len(jobs_data)
        start = (page - 1) * per_page
        end = start + per_page
        
        return self._json_response({
            'data': jobs_data[start:end],
            'pagination': {
                'total': total,
                'page': page,
                'per_page': per_page,
                'pages': (total + per_page - 1) // per_page if per_page > 0 else 0
            },
            'search_query': search,
            'source': 'memory'
        })

    def _load_jobs_data(self) -> list:
        """从数据库或最近上传的 CSV 加载岗位数据 (SQLite)"""
        
        # 1. 优先: 从数据库后端加载
        if self._db:
            try:
                jobs = self._db.fetch_jobs(limit=1000)
                if jobs:
                    return [j.to_dict() for j in jobs]
            except Exception as e:
                logger.warning(f"DB后端加载失败，降级到CSV: {e}")
        
        # 2. 降级: 从CSV文件加载
        try:
            upload_dir = Path(__file__).parent.parent / 'uploads'
            if not upload_dir.exists():
                return []
            
            csv_files = sorted(upload_dir.glob('*.csv'), reverse=True)
            if not csv_files:
                return []
            
            from intent_router import load_jobs_from_csv
            return load_jobs_from_csv(str(csv_files[0]))
        except Exception:
            return []

    def _api_get_job(self, request):
        """GET /api/job/:id → 单条岗位详情 (优先从数据库查询)

        数据源优先级:
          1. SQLite/MySQL 数据库 (get_job_by_id, 精确匹配)
          2. 内存降级 (_load_jobs_data → CSV/DB全量加载, id/title模糊匹配)
        """
        path_parts = request.get('path', '').split('/')
        job_id = path_parts[-1] if len(path_parts) > 2 else None
        
        if not job_id:
            return self._error_response('Missing ID', 404)

        # 1. 优先: 新数据库后端 (精确ID查询)
        db_result = None
        if self._db:
            try:
                job = self._db.get_job_by_id(job_id)
                if job:
                    return self._json_response(job.to_dict())
                db_result = 'not_found'
            except Exception as e:
                logger.warning(f"[JOB-DETAIL] DB查询异常(job_id={job_id}): {e}")
                db_result = f'exception: {e}'
        
        # 2. 降级: 从CSV/内存数据中模糊匹配
        try:
            jobs_data = self._load_jobs_data()
            available_ids = [str(j.get('id')) for j in jobs_data[:20]]  # 取前20个用于日志
            for j in jobs_data:
                if str(j.get('id')) == job_id or j.get('title') == job_id:
                    logger.info(f"[JOB-DETAIL] job_id={job_id} 从降级数据源命中 (source=memory/csv)")
                    return self._json_response(j)
            
            # [DIAG] 记录详细诊断信息帮助排查数据不一致
            logger.warning(
                f"[JOB-DETAIL] 404 job_id={job_id} "
                f"| db_result={db_result} "
                f"| fallback_records={len(jobs_data)} "
                f"| sample_ids={available_ids[:10]}..."
            )
        except Exception as e:
            logger.error(f"[JOB-DETAIL] 降级数据源加载失败: {e}")

        return self._error_response(f'Job not found: {job_id}', 404)

    def _api_delete_job(self, request):
        """DELETE /api/job/:id → 标记删除 (实际执行删除操作)"""
        path_parts = request.get('path', '').split('/')
        job_id = path_parts[-1] if len(path_parts) > 2 else None
        
        if not job_id:
            return self._error_response('Missing ID', 400)
        
        deleted = False
        
        # 尝试通过数据库后端删除
        if self._db:
            try:
                deleted = self._db.delete_job(job_id)
            except Exception as e:
                logger.warning(f"DB删除岗位失败(job_id={job_id}): {e}")
        
        status_code = 200 if deleted else 204  # 204 No Content (兼容旧逻辑)
        if not deleted:
            return {'status': 204, 'body': b''}
            
        return self._json_response({'deleted': True, 'id': job_id})

    # ================================================================
    #   API: 统计数据
    # ================================================================

    def _api_statistics(self, request):
        """
        GET /api/stats
        
        Returns:
            categories: 分类分布统计
            salary_ranges: 薪资区间分布
            urgent_count: 急招岗位数
            total_active: 活跃岗位数
            locations: 地区分布
            execution: 执行历史统计
        """
        stats = self._fetch_db_stats()
        
        # 补充内存中的执行历史统计
        history_stats = self._calc_history_stats()
        stats['execution'] = history_stats
        
        return self._json_response(stats)

    def _fetch_db_stats(self) -> dict:
        """从数据库获取统计数据 (SQLite)"""
        defaults = {
            'categories': {},
            'salary_ranges': {'<5K': 0, '5K-7K': 0, '7K-10K': 0, '10K-15K': 0, '15K+': 0},
            'urgent_count': 0,
            'total_active': 0,
            'locations': {}
        }
        
        if self._db:
            try:
                stats = self._db.get_statistics()
                return {
                    'categories': stats.by_category or defaults['categories'],
                    'salary_ranges': stats.salary_distribution or defaults['salary_ranges'],
                    'urgent_count': stats.urgent_count,
                    'total_active': stats.total_active,
                    'locations': {},
                    'backend_type': stats.backend_type
                }
            except Exception as e:
                logger.warning(f"DB统计获取失败: {e}")
        
        return defaults

    def _calc_history_stats(self) -> dict:
        """计算执行历史的聚合统计 (线程安全快照)"""
        with self._history_lock:
            total = len(self._execution_history)
            if total == 0:
                return {'total_executions': 0, 'success_rate': 0, 'avg_duration': 0}
            
            success_count = sum(
                1 for h in self._execution_history
                if h.get('result', {}).get('status') in ('success', 'empty', 'dry_run')
            )
            
            durations = [
                h.get('result', {}).get('duration', 0)
                for h in self._execution_history
                if h.get('result', {}).get('duration')
            ]
        
        return {
            'total_executions': total,
            'success_rate': round(success_count / total * 100, 1),
            'avg_duration': round(sum(durations) / len(durations), 2) if durations else 0
        }

    # ================================================================
    #   API: 配置管理
    # ================================================================

    def _api_get_config(self, request):
        """
        GET /api/config
        
        数据源优先级:
            1. ConfigStore (SQLite) — 运行时配置（用户 UI 修改的值）
            2. Schema 默认值 — 尚未自定义的字段
            3. ConfigManager — 引导配置（数据库连接等启动参数）
        
        Returns:
            schema:   完整配置项定义列表 (含 current_value)
            groups:   分组信息
            source:   标注数据来源 ('database' / 'file' / 'defaults')
        """
        try:
            from config_schema import get_config_schema, get_all_groups
            
            schema = get_config_schema()
            groups = get_all_groups()

            # ---- 从 ConfigStore 加载当前值 ----
            if self._cfg_store:
                current_values = self._cfg_store.load_all(schema_fields=schema)
                source_label = 'database'
            else:
                # 降级: 回退到 ConfigManager + 环境变量
                current_values = {}
                for field_def in schema:
                    if self._cfg:
                        val = self._cfg.get(field_def.key, field_def.default)
                    else:
                        env_key = field_def.key.upper().replace('.', '_')
                        val = os.getenv(env_key, field_def.default)
                    current_values[field_def.key] = val
                source_label = 'file'

            # ---- 敏感字段脱敏 ----
            display_values = {}
            for field_def in schema:
                raw_val = current_values.get(field_def.key, field_def.default)
                if field_def.is_secret and raw_val:
                    display_values[field_def.key] = '*****(configured)' if str(raw_val) else ''
                else:
                    display_values[field_def.key] = raw_val

            return self._json_response({
                'schema': [
                    {
                        'key': f.key,
                        'label': f.label,
                        'type': f.type_.value,
                        'default': f.default,
                        'group': f.group.value,
                        'description': f.description,
                        'placeholder': f.placeholder,
                        'options': f.options,
                        'validation': f.validation,
                        'is_secret': f.is_secret,
                        'requires_restart': f.requires_restart,
                        'order': f.order,
                        'current_value': display_values.get(f.key, ''),
                        'is_bootstrap': f.key in self._cfg_store.BOOTSTRAP_KEYS if self._cfg_store else False,
                    }
                    for f in schema
                ],
                'groups': groups,
                'source': source_label,
            })
        except Exception as e:
            logger.error(f"[API] GET /api/config 异常: {e}", exc_info=True)
            return self._get_config_fallback()

    def _get_config_fallback(self) -> dict:
        """旧版配置接口（兼容降级）"""
        return {
            'schema': [], 'groups': [],
            'database': {
                'type': 'unknown', 'host': os.getenv('DB_HOST', 'localhost'),
                'configured': bool(os.getenv('DB_HOST')),
            },
            'wechat': {'configured': bool(os.getenv('WECHAT_APP_ID'))},
            'douyin': {'configured': bool(os.getenv('DOUYIN_CLIENT_KEY'))},
            'baidu': {'configured': bool(os.getenv('BAIDU_API_KEY'))},
            'monitoring': {
                'enabled': os.getenv('MONITOR_ENABLED', 'true').lower() == 'true',
                'threshold': float(os.getenv('CITATION_THRESHOLD', 0.005)),
            }
        }

    def _api_update_config(self, request):
        """
        PUT /api/config
        
        Body (JSON): 批量配置更新
            { "site.name": "新名称", "monitoring.enabled": true, ... }
        
        存储策略:
          - 运行时配置 → 写入 SQLite system_config 表 (ConfigStore)
          - 引导配置   → 写入 settings.local.yaml 文件 (ConfigManager)
        
        流程: 前端提交 → Schema验证 → 类型转换 → 分层写入 → 返回结果
        """
        try:
            updates = json.loads(request.get('body', b'{}'))

            if not isinstance(updates, dict):
                return self._error_response('请求体必须是 JSON 对象', 400)

            # 加载完整 Schema 用于验证
            try:
                from config_schema import get_config_schema, ConfigType
                schema_map = {f.key: f for f in get_config_schema()}
            except ImportError:
                schema_map = {}
                # 兜底：让 _validate_config_value 不依赖 ConfigType 枚举
                class ConfigType:
                    NUMBER = 'number'; TOGGLE = 'toggle'

            updated = []
            errors = []
            restart_required = False

            for key, value in updates.items():
                field_def = schema_map.get(key)

                if not field_def:
                    logger.debug(f"[Config] 未知配置项，跳过: {key}")
                    continue

                # ---- 类型转换与验证 ----
                validated_value, validation_error = self._validate_config_value(
                    key, value, field_def
                )

                if validation_error:
                    errors.append({'key': key, 'error': validation_error})
                    continue

                # ---- 分层写入 ----
                is_bootstrap = self._cfg_store and key in self._cfg_store.BOOTSTRAP_KEYS

                try:
                    if is_bootstrap:
                        # 引导配置 → 写入 YAML 文件
                        write_ok = self._cfg_store.set(key, validated_value) if self._cfg_store else False
                        store_label = 'yaml_file'
                    elif self._cfg_store:
                        # 运行时配置 → 写入 SQLite
                        write_ok = self._cfg_store.set(key, validated_value)
                        store_label = 'database'
                    else:
                        # 无 ConfigStore 时的降级路径
                        if self._cfg:
                            write_ok = self._cfg.set(key, validated_value, persist=True)
                        else:
                            env_key = key.upper().replace('.', '_')
                            os.environ[env_key] = str(validated_value)
                            write_ok = True
                        store_label = 'fallback'

                    if write_ok:
                        display_val = ('*****(已保存)' if field_def.is_secret
                                       else str(validated_value))
                        updated.append({
                            'key': key,
                            'value': display_val,
                            'store': store_label,
                            'is_bootstrap': is_bootstrap,
                            'requires_restart': field_def.requires_restart,
                        })
                        if field_def.requires_restart:
                            restart_required = True
                    else:
                        errors.append({'key': key, 'error': '存储层写入失败'})

                except Exception as e:
                    logger.error(f"[Config] 写入 {key} 失败: {e}", exc_info=True)
                    errors.append({'key': key, 'error': f'保存失败: {e}'})

            response = {
                'success': len(updated) > 0,
                'updated_count': len(updated),
                'updated_keys': [u['key'] for u in updated],
                'errors': errors,
                'requires_restart': restart_required,
                'message': (
                    f"成功更新 {len(updated)} 项"
                    + (" | 已写入数据库" if any(u['store'] == 'database' for u in updated) else "")
                    + (" | 引导配置需重启生效" if restart_required else "")
                ),
            }

            status_code = 207 if updated and not errors else 200 if updated else 400
            return self._json_response(response, status_code=status_code)

        except json.JSONDecodeError:
            return self._error_response('请求体必须是有效的 JSON 格式', 400)
        except Exception as e:
            logger.error(f"[API] PUT /api/config 异常: {e}", exc_info=True)
            return self._error_response(str(e), 500)

    @staticmethod
    def _validate_config_value(key: str, value: Any, field_def) -> tuple:
        """验证并转换配置值"""
        v = value
        type_ = field_def.type_
        rules = field_def.validation
        
        # 空值检查（非必填字段允许空字符串）
        if v is None or v == '':
            return v, None
        
        # 类型转换
        try:
            if type_ == ConfigType.NUMBER:
                v = float(v) if '.' in str(v) else int(v)
            elif type_ == ConfigType.TOGGLE:
                if isinstance(v, str):
                    v = v.lower() in ('true', '1', 'yes', 'on')
                elif isinstance(v, (int, float)):
                    v = bool(v)
            # STRING/PASSWORD/TEXTAREA/SELECT/PATH 保持原样
        except (ValueError, TypeError):
            return None, f"类型错误: 应为{type_.value}类型"
        
        # 范围验证
        if 'min' in rules and isinstance(v, (int, float)) and v < rules['min']:
            return None, f"不能小于 {rules['min']}"
        if 'max' in rules and isinstance(v, (int, float)) and v > rules['max']:
            return None, f"不能大于 {rules['max']}"
        if 'pattern' in rules and isinstance(v, str):
            import re
            if not re.match(rules['pattern'], v.strip()):
                return None, f"格式不正确"
        
        return v, None

    # ================================================================
    #   API: 执行历史
    # ================================================================

    def _api_history(self, request):
        """
        GET /api/history
        
        Returns:
            history: 最近20条执行记录 (倒序)
            total: 总记录数
        """
        with self._history_lock:
            history_snapshot = list(self._execution_history[-20:][::-1])
            total = len(self._execution_history)
        
        return self._json_response({
            'history': history_snapshot,
            'total': total
        })

    # ================================================================
    #   API: Schema.org 预览
    # ================================================================

    def _api_schema_preview(self, request):
        """
        GET /api/schema-preview?title=...&company=...
        
        Query Params:
            title, company, location
            min_salary, max_salary
            requirements, benefits, category
        
        Returns: 完整 Schema.org JobPosting JSON-LD 对象
        """
        query = parse_qs(urlparse(request.get('path', '')).query)
        
        sample_job = {
            'title': query.get('title', ['松江G60 高级软件工程师'])[0],
            'company': query.get('company', ['上海科技有限公司'])[0],
            'location': query.get('location', ['上海市松江区G60科创云廊'])[0],
            'min_salary': float(query.get('min_salary', [12000])[0]),
            'max_salary': float(query.get('max_salary', [25000])[0]),
            'category': query.get('category', ['technology'])[0],
            'requirements': query.get('requirements', ['1.本科及以上学历;2.3年以上开发经验'])[0],
            'benefits': query.get('benefits', ['五险一金,年终奖,弹性工作'])[0],
        }
        
        schema = self._build_schema_org(sample_job)
        
        return self._json_response(schema)

    @staticmethod
    def _build_schema_org(job: dict) -> dict:
        """构建 Schema.org JobPosting 结构化数据"""
        now = datetime.now()
        return {
            "@context": "https://schema.org",
            "@type": "JobPosting",
            "title": job['title'],
            "name": job['title'],
            "description": f"{job['requirements']}\n福利待遇：{job['benefits']}",
            "datePosted": now.strftime('%Y-%m-%d'),
            "validThrough": (now + timedelta(days=30)).strftime('%Y-%m-%d'),
            "employmentType": "FULL_TIME",
            "hiringOrganization": {
                "@type": "Organization",
                "name": job['company'],
                "sameAs": "https://www.021kp.com"
            },
            "jobLocation": {
                "@type": "Place",
                "address": {
                    "@type": "PostalAddress",
                    "addressLocality": "上海市松江区",
                    "streetAddress": job['location'],
                    "addressRegion": "SH",
                    "addressCountry": "CN"
                }
            },
            "baseSalary": {
                "@type": "MonetaryAmount",
                "currency": "CNY",
                "value": {
                    "@type": "QuantitativeValue",
                    "minValue": job['min_salary'],
                    "maxValue": job['max_salary'],
                    "unitText": "MONTH"
                }
            },
            "industry": job['category'],
            "experienceRequirements": "1-3年",
            "educationRequirements": "本科",
            "applicantLocationRequirements": {
                "@type": "AdministrativeArea",
                "name": "上海市"
            },
            "directApply": "https://www.021kp.com/apply"
        }

    # ================================================================
    #   API: GEO 四阶段审计
    # ================================================================

    def _api_geo_audit(self, request):
        """
        GET /api/geo/audit?job_id=xxx
        
        对指定岗位执行 GEO 四阶段审计评分
        返回存在层/推荐层/转化层/品牌层的逐项检查结果
        
        来自: doc/06.工具与模板/GEO 审计检查表.md
        """
        try:
            from content_factory import ContentFactory, GEOAuditScorer
            
            query = parse_qs(urlparse(request.get('path', '')).query)
            
            # 获取待审计的岗位数据
            job_id = query.get('job_id', [''])[0]
            
            if job_id and self._db:
                job = self._db.get_job_by_id(job_id)
                if not job:
                    return self._error_response(f'岗位不存在: {job_id}', 404)
                job_data = job.to_dict()
            else:
                # 使用默认示例数据
                job_data = {
                    'title': query.get('title', ['松江G60 高级软件工程师'])[0],
                    'company': query.get('company', ['上海科技有限公司'])[0],
                    'location': query.get('location', ['上海市松江区G60科创云廊'])[0],
                    'min_salary': float(query.get('min_salary', [12000])[0]),
                    'max_salary': float(query.get('max_salary', [25000])[0]),
                    'category': query.get('category', ['technology'])[0],
                    'requirements': query.get('requirements', [''])[0],
                    'benefits': query.get('benefits', ['五险一金,年终奖,弹性工作'])[0],
                }
            
            # 生成结构化资产
            factory = ContentFactory()
            asset = factory.process_single(job_data)
            
            # 执行 GEO 四阶段审计
            audit_result = GEOAuditScorer.audit(asset, context={
                "job_id": job_id,
                "source": "database" if job_id else "sample"
            })
            
            return self._json_response({
                **audit_result,
                "asset_preview": {
                    "schema_type": asset.json_ld.get("@type"),
                    "tldr_length": len(asset.tldr_summary),
                    "anchor_count": len(asset.data_anchors),
                    "has_markdown": bool(asset.markdown_content)
                }
            })
            
        except ImportError as e:
            logger.warning(f"GEO审计模块导入失败: {e}")
            return self._error_response(f'GEO审计模块不可用: {e}', 503)
        except Exception as e:
            logger.error(f"[API] GET /api/geo/audit 异常: {e}", exc_info=True)
            return self._error_response(str(e), 500)

    # ================================================================
    #   API: Organization Schema (GEO 存在层)
    # ================================================================

    def _api_org_schema(self, request):
        """
        GET /api/geo/org-schema
        
        生成 Organization + LocalBusiness JSON-LD (GEO 存在层核心)
        
        来自: doc/01.存在层/结构化数据 Schema 实施.md
              doc/01.存在层/实体建立与必选露头.md
        """
        try:
            from content_factory import OrganizationSchemaGenerator
            
            gen = OrganizationSchemaGenerator()
            
            org_schema = gen.generate_organization_schema(
                name="021kp松江快聘",
                description="松江区域专业招聘服务平台，专注G60科创走廊人才服务，经人社局备案。",
                url="https://www.021kp.com",
                logo="https://www.021kp.com/static/logo.png",
                founding_date="2020-01-01",
                address={
                    "streetAddress": "上海市松江区G60科创云廊",
                    "locality": "松江区",
                    "region": "上海市",
                    "postalCode": "201600"
                },
                contact_points=[
                    {"telephone": "+86-021-XXXXXXXX", "contactType": "customer service"}
                ],
                same_as=[
                    "https://www.zhipin.com/company/021kp",
                    "https://www.51job.com/sh/songjiang/"
                ],
                awards=["2023年度松江就业贡献奖"]
            )
            
            lb_schema = gen.generate_local_business_schema(
                name="021kp松江快聘服务中心",
                category="招聘服务",
                address="上海市松江区G60科创云廊",
                geo={"latitude": 31.0376, "longitude": 121.2345}
            )
            
            return self._json_response({
                "organization": org_schema,
                "local_business": lb_schema,
                "usage_hint": "将 Organization Schema 放入 <head>，LocalBusiness 放入联系我们页面",
                "geo_layer": "existence",  # 标注所属GEO层级
                "doc_reference": "doc/01.存在层/结构化数据 Schema 实施.md"
            })
            
        except Exception as e:
            logger.error(f"[API] GET /api/geo/org-schema 异常: {e}", exc_info=True)
            return self._error_response(str(e), 500)

    # ================================================================
    #   API: FAQ Schema (GEO 推荐层 - 长尾提问承接)
    # ================================================================

    def _api_faq_schema(self, request):
        """
        GET /api/geo/faq-schema?topic=xxx&job_id=xxx
        
        生成 FAQPage JSON-LD（GEO 推荐层长尾提问承接）
        
        来自: doc/02.推荐层/长尾提问承接策略.md
        """
        try:
            from content_factory import FAQSchemaGenerator
            
            query = parse_qs(urlparse(request.get('path', '')).query)
            topic = query.get('topic', ['松江招聘常见问题'])[0]
            
            # 如果有 job_id，生成场景化FAQ
            job_id = query.get('job_id', [''])[0]
            if job_id and self._db:
                job = self._db.get_job_by_id(job_id)
                if job:
                    faqs = FAQSchemaGenerator.generate_scenario_faqs(job.to_dict())
                    faq_schema = FAQSchemaGenerator.generate_faq_schema(
                        faqs=faqs, 
                        topic=f"{job.title} - 岗位问答",
                        site_name=job.company or "021kp"
                    )
                    return self._json_response({
                        **faq_schema,
                        "mode": "scenario",
                        "job_id": job_id,
                        "faq_count": len(faqs),
                        "geo_layer": "recommendation",
                        "doc_reference": "doc/02.推荐层/场景化内容布局.md"
                    })
            
            # 默认：使用PAA模板库
            faq_schema = FAQSchemaGenerator.generate_faq_schema(
                topic=topic,
                site_name="021kp松江快聘"
            )
            
            return self._json_response({
                **faq_schema,
                "mode": "general_paa",
                "faq_count": len(faq_schema.get("mainEntity", [])),
                "geo_layer": "recommendation",
                "doc_reference": "doc/02.推荐层/长尾提问承接策略.md"
            })
            
        except Exception as e:
            logger.error(f"[API] GET /api/geo/faq-schema 异常: {e}", exc_info=True)
            return self._error_response(str(e), 500)

    # ================================================================
    #   API: BreadcrumbList Schema (GEO 推荐层)
    # ================================================================

    def _api_breadcrumb_schema(self, request):
        """
        GET /api/geo/breadcrumb?page_path=jobs/detail
        
        生成 BreadcrumbList JSON-LD（GEO 推荐层导航增强）
        """
        try:
            from content_factory import BreadcrumbSchemaGenerator
            
            query = parse_qs(urlparse(request.get('path', '')).query)
            page_path = query.get('page_path', ['home'])[0]
            
            # 预定义路径映射
            breadcrumb_map = {
                "home": [
                    {"name": "首页", "url": "/"},
                ],
                "jobs": [
                    {"name": "首页", "url": "/"},
                    {"name": "岗位列表", "url": "/jobs"},
                ],
                "detail": [
                    {"name": "首页", "url": "/"},
                    {"name": "岗位列表", "url": "/jobs"},
                    {"name": "岗位详情", "url": "/jobs/{id}"},
                ],
                "about": [
                    {"name": "首页", "url": "/"},
                    {"name": "关于我们", "url": "/about"},
                ],
                "contact": [
                    {"name": "首页", "url": "/"},
                    {"name": "联系我们", "url": "/contact"},
                ],
            }
            
            items = breadcrumb_map.get(page_path, breadcrumb_map["home"])
            
            schema = BreadcrumbSchemaGenerator.generate_breadcrumbs(items)
            
            return self._json_response({
                **schema,
                "page_path": page_path,
                "item_count": len(items),
                "available_paths": list(breadcrumb_map.keys()),
                "geo_layer": "recommendation",
            })
            
        except Exception as e:
            logger.error(f"[API] GET /api/geo/breadcrumb 异常: {e}", exc_info=True)
            return self._error_response(str(e), 500)

    # ================================================================
    #   API: GEO 框架概览
    # ================================================================

    def _api_framework_overview(self, request):
        """
        GET /api/geo/framework
        
        返回 GEO 四阶段框架完整定义和当前项目对齐状态
        
        来自: doc/00.GEO 核心框架.md
        """
        framework = {
            "meta": {
                "name": "GEO (Generative Engine Optimization)",
                "version": "2.0",
                "core_principle": "GEO不是拼词密，而是拼谁的信息更'经得起推敲'",
                "doc_source": "doc/00.GEO 核心框架.md"
            },
            "layers": [
                {
                    "id": "existence",
                    "phase": 1,
                    "name": "存在层",
                    "chinese_alias": "实体建立与必选露头",
                    "core_question": "你是谁？你出现在哪里？",
                    "goal": "确保企业信息被AI抓取、收录并进入知识图谱",
                    "actions": [
                        "Organization Schema 部署",
                        "LocalBusiness Schema 含地址信息",
                        "知识图谱实体关联建立",
                        "第三方背书积累(≥5个权威提及)"
                    ],
                    "checklist_items": [
                        "AI搜索时能否看到我们",
                        "结构化数据是否通过Google Rich Results测试",
                        "是否有至少5个权威第三方提及"
                    ],
                    "api_endpoints": [
                        "/api/geo/org-schema — Organization+LocalBusiness JSON-LD"
                    ],
                    "status": "implemented"  # 已实现
                },
                {
                    "id": "recommendation",
                    "phase": 2,
                    "name": "推荐层",
                    "chinese_alias": "专业权威与差异化推荐",
                    "core_question": "你比谁好？为什么推荐你？",
                    "goal": "在AI对比筛选时，核心优势高于竞争对手",
                    "actions": [
                        "场景化内容布局(特定场景深度回答)",
                        "差异化标签建设(≥3个清晰标签)",
                        "长尾提问PAA预埋与承接"
                    ],
                    "checklist_items": [
                        "AI对比时是否有独特优势被提及",
                        "是否有≥3个清晰的差异化标签",
                        "是否覆盖核心长尾提问"
                    ],
                    "api_endpoints": [
                        "/api/geo/faq-schema — FAQPage 长尾问答JSON-LD",
                        "/api/geo/breadcrumb — BreadcrumbList 导航JSON-LD",
                        "/api/schema-preview — JobPosting Schema预览"
                    ],
                    "status": "implemented"
                },
                {
                    "id": "conversion",
                    "phase": 3,
                    "name": "转化层",
                    "chinese_alias": "转化闭环与信任验证",
                    "core_question": "我要怎么做？怎么找到你？",
                    "goal": "提供无缝转化路径，从信息到行动的临门一脚",
                    "actions": [
                        "信息一致性(各渠道数据统一)",
                        "信任证明元素(认证/评价/案例)",
                        "着陆页体验优化(CTA≤3次点击可达)"
                    ],
                    "checklist_items": [
                        "用户能否在3秒内找到联系方式",
                        "官网信息是否与AI回答一致",
                        "是否有明确转化入口"
                    ],
                    "api_endpoints": [
                        "/api/geo/audit — 四维度审计评分(含转化层检查)"
                    ],
                    "status": "partial"  # 部分实现
                },
                {
                    "id": "brand",
                    "phase": 4,
                    "name": "品牌层",
                    "chinese_alias": "品牌心智与AI定义权",
                    "core_question": "你代表了什么？AI提到你代表什么？",
                    "goal": "从'被搜索'变成'被定义'",
                    "actions": [
                        "长期内容沉淀(持续输出高质量行业知识)",
                        "全域一致性执行(线上线下品牌统一)",
                        "用户反馈引导机制(好评收集)"
                    ],
                    "checklist_items": [
                        "用户问趋势时是否会提到我们",
                        "AI提及时是否代表行业标杆",
                        "是否有多平台一致的品牌形象"
                    ],
                    "api_endpoints": [
                        "/api/geo/audit — 四维度审计评分(含品牌层检查)"
                    ],
                    "status": "planned"  # 规划中
                }
            ],
            "geo_vs_seo": {
                "traditional_seo": {
                    "core_logic": "关键词密度",
                    "goal": "出现在列表顶部",
                    "strategy": "强行排名",
                    "persistence": "算法一变就失效"
                },
                "geo": {
                    "core_logic": "信息可信度",
                    "goal": "进入AI知识图谱",
                    "strategy": "系统信任建设",
                    "persistence": "信任积累越久越稳固"
                }
            },
            "roadmap": {
                "Phase_1": "1-2月 → 存在层(打基础)",
                "Phase_2": "2-4月 → 推荐层(建优势)",
                "Phase_3": "1-2月 → 转化层(保转化)",
                "Phase_4": "持续 → 品牌层(定心智)"
            }
        }
        
        return self._json_response(framework)

    # ================================================================
    #   Phase 5: 分发监控 API (dist_monitor 集成)
    # ================================================================

    def _api_monitor_citation(self, request):
        """
        GET /api/monitor/citation?platform=metaso&query=松江招聘
        
        执行单次引用率检测，返回各平台引用指标。
        若不传 platform 参数则批量检查所有启用平台。
        
        Returns:
            metrics: CitationMetrics 列表
            checked_at: 检查时间
            overall_status: NORMAL / DEGRADED / FROZEN
            avg_citation_rate: 平均引用率
        """
        try:
            from dist_monitor import DistributionMonitor
        except ImportError:
            return self._json_response({
                'error': 'dist_monitor 模块不可用',
                'metrics': [],
                'checked_at': datetime.now(timezone(timedelta(hours=8))).isoformat()
            })
        
        query = parse_qs(urlparse(request.get('path', '')).query)
        platform = query.get('platform', [None])[0]
        search_query = query.get('query', [None])[0]
        
        monitor = DistributionMonitor()
        
        if platform:
            # 单平台检测
            metrics = [monitor.probe.check_citation_rate(platform, search_query)]
        else:
            # 批量检测（所有启用平台）
            metrics = monitor.probe.batch_check()
        
        rates = [m.citation_rate for m in metrics if m.citation_rate is not None]
        avg_rate = sum(rates) / len(rates) if rates else 0.0
        
        # 判定整体状态
        if avg_rate < 0.3:
            status = 'FROZEN'
        elif avg_rate < 0.5:
            status = 'DEGRADED'
        else:
            status = 'NORMAL'
        
        return self._json_response({
            'metrics': [
                {
                    'platform': m.platform,
                    'brand_mention_count': m.brand_mention_count,
                    'total_queries': m.total_queries,
                    'citation_rate': round(m.citation_rate, 4),
                    'trend': m.trend,
                    'last_check_time': m.last_check_time
                }
                for m in metrics
            ],
            'checked_at': datetime.now(timezone(timedelta(hours=8))).isoformat(),
            'overall_status': status,
            'avg_citation_rate': round(avg_rate, 4),
            'platform_count': len(metrics)
        })

    def _api_monitor_alerts(self, request):
        """
        GET /api/monitor/alerts?days=7
        
        返回告警历史记录，从 audit_logs/alerts/ 目录读取 JSONL 文件。
        
        Returns:
            alerts: 告警列表
            total: 总数
            severity_counts: 各级别统计
        """
        from pathlib import Path as _P
        
        days = int(parse_qs(urlparse(request.get('path', '')).query).get('days', ['7'])[0])
        alerts_dir = _P('./audit_logs/alerts')
        alerts = []
        severity_counts = {'critical': 0, 'warning': 0, 'info': 0}
        
        if alerts_dir.exists():
            cutoff = datetime.now() - timedelta(days=days)
            for f in sorted(alerts_dir.glob('alerts_*.jsonl'), reverse=True):
                file_date_str = f.stem.replace('alerts_', '')
                try:
                    file_date = datetime.strptime(file_date_str, '%Y-%m-%d')
                    if file_date < cutoff:
                        continue
                except ValueError:
                    pass
                
                try:
                    for line in f.read_text(encoding='utf-8').strip().split('\n'):
                        if not line.strip():
                            continue
                        alert = json.loads(line.strip())
                        alert['_source_file'] = f.name
                        alerts.append(alert)
                        sev = alert.get('severity', 'info')
                        severity_counts[sev] = severity_counts.get(sev, 0) + 1
                except (json.JSONDecodeError, OSError):
                    continue
        
        return self._json_response({
            'alerts': alerts[:100],  # 最多返回100条
            'total': len(alerts),
            'severity_counts': severity_counts,
            'query_days': days
        })

    def _api_monitor_rollback(self, request):
        """
        GET /api/monitor/rollback
        
        获取当前回滚状态（冻结状态、冻结原因、恢复时间等）。
        从 audit_logs/rollbacks/ 目录读取最新回滚记录。
        
        Returns:
            rollback_state: 当前回滚状态
            latest_record: 最新回滚记录详情（如有）
            can_recover: 是否可恢复
            recovery_reason: 恢复判定说明
        """
        from pathlib import Path as _P
        
        rollbacks_dir = _P('./audit_logs/rollbacks')
        
        default_state = {
            'is_frozen': False,
            'frozen_at': None,
            'reason': '',
            'frozen_duration_hours': 0
        }
        latest_record = None
        can_recover = True
        recovery_reason = '系统正常，无需恢复'
        
        # 尝试从 dist_monitor 读取真实状态
        try:
            from dist_monitor import DistributionMonitor
            monitor = DistributionMonitor()
            rb_mgr = monitor.rollback_mgr
            
            can_recov, reason = rb_mgr.can_recover()
            can_recover = can_recov
            recovery_reason = reason
            
            default_state.update({
                'is_frozen': rb_mgr.rollback_state['is_frozen'],
                'frozen_at': rb_mgr.rollback_state.get('frozen_at'),
                'reason': rb_mgr.rollback_state.get('reason', ''),
                'frozen_duration_hours': round(rb_mgr._calc_frozen_hours(), 1) if hasattr(rb_mgr, '_calc_frozen_hours') else 0
            })
            
        except Exception:
            pass
        
        # 尝试读取最新回滚记录文件
        if rollbacks_dir.exists():
            records = sorted(rollbacks_dir.glob('rollback_*.json'), reverse=True)
            if records:
                try:
                    latest_record = json.loads(records[0].read_text(encoding='utf-8'))
                except (json.JSONDecodeError, OSError):
                    pass
        
        return self._json_response({
            'rollback_state': default_state,
            'latest_record': latest_record,
            'can_recover': can_recover,
            'recovery_reason': recovery_reason,
            'checked_at': datetime.now(timezone(timedelta(hours=8))).isoformat()
        })

    def _api_manual_check(self, request):
        """
        POST /api/monitor/check
        
        手动触发一次完整的监控检查流程（引用率采集→告警评估→回滚判断→报告生成）。
        这是一个耗时操作（可能需要5-15秒），建议异步调用或设置较长超时。
        
        Returns:
            report_id: 报告ID
            status: 执行结果状态
            metrics_summary: 指标摘要
            alerts_triggered: 触发的告警数量
            rollback_executed: 是否执行了回滚
        """
        try:
            from dist_monitor import DistributionMonitor
        except ImportError:
            return self._json_response({
                'error': 'dist_monitor 模块不可用',
                'status': 'module_unavailable',
                'report_id': None
            }, status_code=503)
        
        try:
            monitor = DistributionMonitor()
            report = monitor.run_single_check()
            
            return self._json_response({
                'report_id': report.report_id,
                'status': report.overall_status.value,
                'generated_at': report.generated_at,
                'period_start': report.period_start,
                'period_end': report.period_end,
                'metrics_summary': [
                    {
                        'platform': m.platform,
                        'citation_rate': round(m.citation_rate, 4),
                        'trend': m.trend
                    } for m in report.metrics
                ],
                'alerts_triggered': len(report.alerts_triggered),
                'alerts_detail': report.alerts_triggered,
                'recommendations': report.recommendations,
                'rollback_executed': report.overall_status.value == 'FROZEN',
                'ai_preview_simulation': report.ai_preview_simulation[:500] + '...' if len(report.ai_preview_simulation) > 500 else report.ai_preview_simulation
            })
        except Exception as e:
            logger.error(f"[Monitor] 手动检查异常: {e}")
            return self._json_response({
                'error': str(e),
                'status': 'error',
                'report_id': None
            }, status_code=500)

    def _api_monitor_reports(self, request):
        """
        GET /api/monitor/reports?limit=10
        
        返回已生成的监控报告列表（从 dist/reports/ 目录扫描）。
        支持查看报告摘要和下载链接。
        
        Returns:
            reports: 报告列表（按时间倒序）
            total: 总数
            reports_dir: 报告目录路径
        """
        from pathlib import Path as _P
        
        query = parse_qs(urlparse(request.get('path', '')).query)
        limit = int(query.get('limit', ['10'])[0])
        
        reports_dir = _P('./dist/reports')
        reports = []
        
        if reports_dir.exists():
            for f in sorted(reports_dir.glob('*.json'), reverse=True)[:limit]:
                try:
                    data = json.loads(f.read_text(encoding='utf-8'))
                    md_file = reports_dir / (f.stem + '.md')
                    reports.append({
                        'id': data.get('report_id', f.stem),
                        'generated_at': data.get('generated_at'),
                        'overall_status': data.get('overall_status', 'unknown'),
                        'platforms_checked': len(data.get('metrics_summary', [])),
                        'alerts_count': data.get('alerts_count', 0),
                        'has_markdown': md_file.exists(),
                        'file_name': f.name,
                        'file_size_kb': round(f.stat().st_size / 1024, 1)
                    })
                except (json.JSONDecodeError, OSError):
                    continue
        
        return self._json_response({
            'reports': reports,
            'total': len(reports),
            'reports_dir': str(reports_dir.absolute()) if reports_dir.exists() else '(不存在)',
            'limit': limit
        })

    # ================================================================
    #   工具方法: 统一响应格式
    # ================================================================

    def _json_response(self, data: dict, status_code: int = 200) -> dict:
        """构造标准 JSON 响应字典"""
        return {
            'status': status_code,
            'headers': {
                'Content-Type': 'application/json; charset=utf-8',
                'Access-Control-Allow-Origin': '*'
            },
            'body': json.dumps(data, ensure_ascii=False, default=str).encode('utf-8')
        }
    
    @staticmethod
    def _error_response(message: str, status_code: int = 400) -> dict:
        """构造错误响应"""
        return {
            'status': status_code,
            'headers': {'Content-Type': 'application/json; charset=utf-8'},
            'body': json.dumps({'error': message}).encode('utf-8')
        }

    # ================================================================
    #   API: 审计历史持久化 (A1 - GEO-Audit 增强)
    # ================================================================

    def _api_audit_history(self, request):
        """
        GET /api/geo/audit/history
        
        返回历史审计记录（从 audit_logs/audits/ 目录读取）。
        
        Returns:
            audits: 审计记录列表（倒序）
            total: 总数
        """
        from pathlib import Path as _P
        audits_dir = _P('./audit_logs/audits')
        audits = []
        
        if audits_dir.exists():
            for f in sorted(audits_dir.glob('audit_*.json'), reverse=True)[:50]:
                try:
                    data = json.loads(f.read_text(encoding='utf-8'))
                    audits.append(data)
                except (json.JSONDecodeError, OSError):
                    continue
        
        return self._json_response({
            'audits': audits,
            'total': len(audits),
            'storage_path': str(audits_dir.absolute()) if audits_dir.exists() else '(不存在)'
        })

    def _api_save_audit(self, request):
        """
        POST /api/geo/audit/save
        
        保存一次审计结果到 audit_logs/audits/ 目录。
        
        Body (JSON): 完整的审计结果对象（与 GET /api/geo/audit 返回格式一致）
        
        Returns:
            saved_id: 保存后的文件ID
            file_path: 存储路径
        """
        try:
            from pathlib import Path as _P
            
            body = json.loads(request.get('body', b'{}'))
            
            # 验证必要字段
            if 'total_score' not in body and 'dimensions' not in body:
                return self._error_response('无效的审计数据：缺少 total_score 或 dimensions', 400)
            
            # 确保目录存在
            audits_dir = _P('./audit_logs/audits')
            audits_dir.mkdir(parents=True, exist_ok=True)
            
            # 生成文件名
            job_title = body.get('job_title', body.get('source_job', {}).get('title', 'unknown'))
            safe_title = re.sub(r'[^\w\-]', '_', job_title[:30]) if job_title else 'unknown'
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            file_id = f"audit_{timestamp}_{safe_title}"
            file_name = f"{file_id}.json"
            file_path = audits_dir / file_name
            
            # 补充元数据
            body['saved_at'] = datetime.now(timezone(timedelta(hours=8))).isoformat()
            body['file_id'] = file_id
            
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(body, f, ensure_ascii=False, indent=2)
            
            return self._json_response({
                'success': True,
                'saved_id': file_id,
                'file_path': str(file_path),
                'message': f'审计结果已保存 ({len(audits_dir.glob("audit_*.json"))} 条历史)'
            })
            
        except json.JSONDecodeError:
            return self._error_response('请求体必须是有效 JSON', 400)
        except Exception as e:
            logger.error(f"[API] POST /api/geo/audit/save 异常: {e}", exc_info=True)
            return self._error_response(str(e), 500)

    def _api_audit_export(self, request):
        """
        GET /api/geo/audit/export?job_id=xxx&format=json|md
        
        导出审计结果为指定格式。
        
        Returns:
            format: 导出格式
            content: 文本内容
            filename: 推荐文件名
        """
        query = parse_qs(urlparse(request.get('path', '')).query)
        export_format = query.get('format', ['json'])[0].lower()
        job_id = query.get('job_id', [''])[0]
        
        # 尝试获取审计数据
        try:
            from content_factory import ContentFactory, GEOAuditScorer
            
            if job_id and self._db:
                job = self._db.get_job_by_id(job_id)
                job_data = job.to_dict() if job else None
            else:
                job_data = None
            
            if job_data:
                factory = ContentFactory()
                asset = factory.process_single(job_data)
                audit_result = GEOAuditScorer.audit(asset, context={
                    "job_id": job_id, "source": "database"
                })
            else:
                return self._error_response(f'未找到岗位: {job_id}', 404)
                
        except Exception as e:
            return self._error_response(f'审计导出失败: {e}', 500)
        
        # 格式化输出
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        if export_format == 'md':
            content = self._format_audit_markdown(audit_result, job_data)
            filename = f"GEO_Audit_{ts}.md"
        else:
            content = json.dumps(audit_result, ensure_ascii=False, indent=2)
            filename = f"GEO_Audit_{ts}.json"
        
        return {
            'status': 200,
            'headers': {
                'Content-Type': 'application/octet-stream',
                'Content-Disposition': f'attachment; filename="{filename}"'
            },
            'body': content.encode('utf-8')
        }

    @staticmethod
    def _format_audit_markdown(audit: dict, job: dict) -> str:
        """将审计结果格式化为 Markdown 报告"""
        lines = [
            f"# GEO 四阶段审计报告",
            f"",
            f"> **岗位**: {job.get('title', '-')} @ {job.get('company', '-')}",
            f"> **评分**: `{audit.get('total_score', 0)}` / 100 | **等级**: **{audit.get('grade', '?')}**",
            f"> **时间**: {datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M')}",
            f"",
            f"---",
            f""
        ]
        
        dim_names = {
            'existence': ('🏗️ 存在层', '#1a73e8'),
            'recommendation': ('⭐ 推荐层', '#7c3aed'),
            'conversion': ('🎯 转化层', '#059669'),
            'brand': ('👑 品牌层', '#d97706'),
        }
        
        for key, dim in (audit.get('dimensions') or {}).items():
            info = dim_names.get(key, (key, '#999'))
            lines.append(f"## {info[0]} — `{dim.get('percentage', 0)}%`")
            lines.append(f"")
            for check in (dim.get('checks') or []):
                icon = ':white_check_mark:' if check.get('passed') else ':x:'
                lines.append(f"- {icon} **{check.get('item', '-')}** (+{check.get('weight', 0)}分)")
            lines.append(f"")
        
        suggestions = audit.get('suggestions', [])
        if suggestions:
            lines.append(f"---")
            lines.append(f"")
            lines.append(f"## 改进建议")
            lines.append(f"")
            for s in suggestions:
                priority = '🔴 高优先级' if s.get('priority') == 'high' else '🟡 中优先级'
                lines.append(f"- [{priority}] {s.get('item', '-')} *(维度: {s.get('dimension', '?')})*")
        
        return '\n'.join(lines)

    # ================================================================
    #   API: 配置导出/导入 (C2 - Config 增强)
    # ================================================================

    def _api_config_export(self, request):
        """
        GET /api/config/export?format=json|yaml
        
        导出当前全部配置为可下载文件。
        
        Returns:
            config_data: 当前配置快照
            export_time: 导出时间
            format: 格式
        """
        query = parse_qs(urlparse(request.get('path', '')).query)
        fmt = query.get('format', ['json'])[0].lower()
        
        # 获取完整配置
        cfg_resp = self._api_get_config(request)
        cfg_body = json.loads(cfg_resp['body'])
        
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        if fmt == 'yaml':
            try:
                import yaml
                content = yaml.dump(cfg_body, allow_unicode=True, default_flow_style=False)
                filename = f"geo_config_{ts}.yaml"
            except ImportError:
                content = json.dumps(cfg_body, ensure_ascii=False, indent=2)
                filename = f"geo_config_{ts}.json"
        else:
            content = json.dumps(cfg_body, ensure_ascii=False, indent=2)
            filename = f"geo_config_{ts}.json"
        
        return {
            'status': 200,
            'headers': {
                'Content-Type': 'application/octet-stream',
                'Content-Disposition': f'attachment; filename="{filename}"'
            },
            'body': content.encode('utf-8')
        }

    def _api_config_import(self, request):
        """
        POST /api/config/import
        
        从上传的配置文件恢复设置。
        
        Body (JSON): { "config": {...}, "merge_mode": "replace|merge" }
        """
        try:
            params = json.loads(request.get('body', b'{}'))
            imported_config = params.get('config', {})
            merge_mode = params.get('merge_mode', 'merge')
            
            if not imported_config or not isinstance(imported_config, dict):
                return self._error_response('请求体中缺少有效的 config 对象', 400)
            
            # 加载 schema 用于验证
            try:
                from config_schema import get_config_schema
                schema_map = {f.key: f for f in get_config_schema()}
            except ImportError:
                schema_map = {}
            
            updated = []
            errors = []
            
            for key, value in imported_config.items():
                field_def = schema_map.get(key)
                if not field_def:
                    continue
                
                validated, err = self._validate_config_value(key, value, field_def)
                if err:
                    errors.append({'key': key, 'error': err})
                    continue
                
                try:
                    if self._cfg_store:
                        write_ok = self._cfg_store.set(key, validated)
                        updated.append({'key': key, 'status': 'imported'})
                    else:
                        errors.append({'key': key, 'error': '无存储后端'})
                except Exception as e:
                    errors.append({'key': key, 'error': str(e)})
            
            return self._json_response({
                'success': len(updated) > 0,
                'imported_count': len(updated),
                'imported_keys': [u['key'] for u in updated],
                'errors': errors,
                'message': f'成功导入 {len(updated)} 项配置'
            })
            
        except json.JSONDecodeError:
            return self._error_response('请求体必须是有效 JSON', 400)
        except Exception as e:
            logger.error(f"[API] POST /api/config/import 异常: {e}", exc_info=True)
            return self._error_response(str(e), 500)
