# -*- coding: utf-8 -*-
"""
GEO Pipeline Web API 集成测试套件
====================================

目标: 覆盖 main.py + web_ui.py 所有API端点的请求/响应/错误处理
运行: uv run pytest tests/test_web_api.py -v --tb=short

注意: 使用真实HTTP连接到测试服务器，非mock
"""

import sys
import json
import os
import time
import threading
import socket
import pytest
from pathlib import Path
from http.client import HTTPConnection
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

# ==================== 辅助 ====================

def _find_free_port():
    """查找可用端口（用于并行测试）"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        return s.getsockname()[1]


class TestWebAPISuite:
    """
    Web API 端到端集成测试套件
    
    策略:
      - 每个测试类独立启动一个HTTP服务器线程（不同端口）
      - 测试完成后自动清理
      - 避免端口冲突使用动态分配端口
    """

    @pytest.fixture(autouse=True)
    def setup_server(self, tmp_path):
        """启动独立的测试HTTP服务器"""
        self.port = _find_free_port()
        self.base_url = f"localhost:{self.port}"
        self.tmp_path = tmp_path
        
        # 设置临时数据库路径，避免污染生产数据
        os.environ["GEO_TEST_DB"] = str(tmp_path / "test_e2e.db")
        os.environ["GEO_TEST_MODE"] = "1"
        
        # 导入并启动服务器
        from main import run_server_mode
        self.server_thread = threading.Thread(
            target=run_server_mode,
            kwargs={"port": self.port, "db_enabled": True, "web_ui": True},
            daemon=True
        )
        self.server_thread.start()
        
        # 等待服务器就绪
        max_wait = 5.0
        start = time.time()
        while time.time() - start < max_wait:
            try:
                conn = HTTPConnection(self.base_url, timeout=2)
                conn.request("GET", "/health")
                resp = conn.getresponse()
                if resp.status == 200:
                    break
            except Exception:
                time.sleep(0.1)
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
        else:
            pytest.fail(f"测试服务器在 {max_wait}s 内未就绪 (port={self.port})")
        
        yield
        
        # 清理环境变量
        os.environ.pop("GEO_TEST_DB", None)
        os.environ.pop("GEO_TEST_MODE", None)

    def _request(self, method, path, body=None, headers=None):
        """发送HTTP请求辅助方法"""
        conn = HTTPConnection(self.base_url, timeout=10)
        hdrs = {"Content-Type": "application/json; charset=utf-8"}
        if headers:
            hdrs.update(headers)

        try:
            if body is not None:
                body_bytes = json.dumps(body).encode('utf-8')
                hdrs["Content-Length"] = str(len(body_bytes))
                conn.request(method, path, body=body_bytes, headers=hdrs)
            else:
                conn.request(method, path, headers=hdrs)
            
            response = conn.getresponse()
            status = response.status
            raw = response.read().decode('utf-8', errors='replace')

            try:
                data = json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                data = raw
            
            return status, data
        except Exception as e:
            raise
        finally:
            conn.close()


class TestHealthEndpoints(TestWebAPISuite):
    """健康检查端点"""

    def test_health_endpoint(self):
        status, data = self._request("GET", "/health")
        assert status == 200
        assert data.get("status") == "healthy"
        assert "version" in data

    def test_ready_endpoint(self):
        status, data = self._request("GET", "/ready")
        assert status in [200, 503]
        assert "status" in data
        assert "components" in data


class TestPipelineStatus(TestWebAPISuite):
    """Pipeline状态端点"""

    def test_pipeline_status_structure(self):
        status, data = self._request("GET", "/api/pipeline/status")
        assert status == 200
        assert "version" in data
        assert "phases" in data
        phases = data["phases"]
        expected_phase_keys = ["compliance_gate", "intent_router",
                              "content_factory", "auth_signaler"]
        for k in expected_phase_keys:
            assert k in phases, f"缺少阶段: {k}"


class TestStatsEndpoint(TestWebAPISuite):
    """统计信息端点"""

    def test_stats_returns_dict(self):
        status, data = self._request("GET", "/api/stats")
        assert status == 200
        assert isinstance(data, dict)


class TestJobsAPI(TestWebAPISuite):
    """岗位CRUD API"""

    def test_list_jobs_empty(self):
        """无数据时应返回空列表或默认分页"""
        status, data = self._request("GET", "/api/jobs?page=1&per_page=20")
        assert status == 200
        assert "data" in data or "pagination" in data

    def test_get_job_not_found_404(self):
        """不存在的job应返回404"""
        status, data = self._request("GET", "/api/job/NONEXISTENT_JOB_ID_12345")
        assert status == 404

    def test_delete_job_nonexistent(self):
        """删除不存在的job不应500"""
        status, data = self._request("DELETE", "/api/job/NO_SUCH_ID")
        assert status in [200, 204, 404]


class TestConfigAPI(TestWebAPISuite):
    """配置管理API"""

    def test_get_config_returns_schema(self):
        status, data = self._request("GET", "/api/config")
        assert status == 200
        # 应包含schema数组或至少一个配置项
        assert isinstance(data, dict)
        assert "schema" in data or "source" in data or "database" in data

    def test_put_config_valid_body(self):
        """PUT更新配置（如果实现）"""
        body = {"key": "site.name", "value": "E2E测试站点"}
        status, data = self._request("PUT", "/api/config", body=body)
        assert status in [200, 400, 422]  # 取决于是否支持该字段


class TestHistoryAPI(TestWebAPISuite):
    """执行历史API"""

    def test_history_returns_list(self):
        status, data = self._request("GET", "/api/history?limit=10")
        assert status == 200
        assert isinstance(data, dict) or isinstance(data, list)


class TestMonitorAPI(TestWebAPISuite):
    """分发监控API"""

    def test_monitor_citation_empty(self):
        status, data = self._request("GET", "/api/monitor/citation")
        assert status == 200
        assert isinstance(data, dict)

    def test_monitor_alerts_empty(self):
        status, data = self._request("GET", "/api/monitor/alerts")
        assert status == 200
        assert isinstance(data, dict)

    def test_monitor_rollback_state(self):
        status, data = self._request("GET", "/api/monitor/rollback")
        assert status == 200
        assert isinstance(data, dict)

    def test_monitor_reports_empty(self):
        status, data = self._request("GET", "/api/monitor/reports")
        assert status == 200
        assert isinstance(data, dict)


class TestGEOFrameworkAPI(TestWebAPISuite):
    """GEO框架API"""

    def test_framework_overview(self):
        status, data = self._request("GET", "/api/geo/framework")
        assert status == 200
        assert isinstance(data, dict)

    def test_geo_audit_basic(self):
        status, data = self._request("GET", "/api/geo/audit")
        assert status == 200
        assert isinstance(data, dict)


class TestStaticAssets(TestWebAPISuite):
    """静态资源服务"""

    def test_spa_entrypoint(self):
        """SPA入口应返回HTML"""
        status, data = self._request("GET", "/ui")
        assert status == 200

    def test_favicon_no_404(self):
        """Favicon不应返回404（可能返回空或重定向）"""
        status, _ = self._request("GET", "/favicon.ico")
        # 允许200/304或其他非404响应
        assert status != 404

    def test_root_redirect(self):
        """根路径应重定向到/ui或返回页面"""
        status, _ = self._request("GET", "/")
        assert status in [200, 302, 301]

    def test_unknown_route_404(self):
        """未知路由返回404"""
        status, data = self._request("GET", "/api/nonexistent_endpoint_xyz")
        assert status == 404


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
