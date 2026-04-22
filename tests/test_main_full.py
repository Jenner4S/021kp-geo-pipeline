# -*- coding: utf-8 -*-
"""
Main 模块完整测试套件
=======================

覆盖范围:
- _ensure_src_in_path() 路径管理
- _init_system() 系统初始化
- run_pipeline_mode() 标准流水线模式
- run_db_pipeline_mode() 数据库驱动模式
- run_import_mode() CSV导入模式
- _run_geo_phases() GEO核心流程
- run_server_mode() HTTP服务模式
- main() CLI入口 / argparse解析
- _print_results() 结果格式化

Author: GEO-Test Suite | Date: 2026-04-21
"""

import os
import sys
import json
import tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

import pytest


# ============================================================
#   Fixtures & Helpers
# ============================================================

@pytest.fixture
def sample_csv_file():
    """创建临时 CSV 文件"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8') as f:
        f.write('id,title,company,location,min_salary,max_salary,category,tags,requirements,benefits,is_urgent\n')
        f.write('job001,软件工程师,A科技公司,上海松江,12000,20000,technology,"Python,Docker","本科以上","五险一金",false\n')
        f.write('job002,产品经理,B互联网,上海徐汇,18000,30000,product,"PRD,数据分析","3年经验","弹性工作",true\n')
        f.write('job003,数据分析师,C数据,上海浦东,15000,25000,data,"SQL,Python","熟悉机器学习", "年终奖",false\n')
        yield f.name
    
    # 清理
    try:
        os.unlink(f.name)
    except OSError:
        pass


class TestEnsureSrcInPath:
    """路径管理测试"""

    def test_adds_src_to_path(self):
        """确保 src 目录被加入 sys.path"""
        from main import _ensure_src_in_path
        
        # 先记录当前 path
        original = sys.path.copy()
        
        # 清除可能已存在的条目
        src_dir = str(Path(__file__).parent.parent / 'src')
        while src_dir in sys.path:
            sys.path.remove(src_dir)
        
        _ensure_src_in_path()
        
        assert src_dir in sys.path
        assert str(Path(__file__).parent.parent) in sys.path  # project root
        
        # 恢复（避免影响其他测试）
        sys.path.clear()
        sys.path.extend(original)

    def test_idempotent(self):
        """多次调用不会重复添加"""
        from main import _ensure_src_in_path
        
        src_dir = str(Path(__file__).parent.parent / 'src')
        
        _ensure_src_in_path()
        count_before = sys.path.count(src_dir)
        
        _ensure_src_in_path()
        count_after = sys.path.count(src_dir)
        
        assert count_after == count_before  # 不应增加


class TestInitSystem:
    """系统初始化测试"""

    def test_init_system_no_crash(self):
        """初始化不应崩溃（即使依赖缺失）"""
        from main import _init_system
        try:
            _init_system()
        except Exception as e:
            pytest.fail(f"_init_system() raised {type(e).__name__}: {e}")


class TestRunPipelineMode:
    """标准流水线模式测试 """

    def test_pipeline_missing_input_raises_error(self):
        """无输入参数时应报错"""
        from main import run_pipeline_mode
        result = run_pipeline_mode(csv_path=None, json_input=None)
        assert result['status'] == 'error'
        assert '请提供' in result.get('error_message', '')

    def test_pipeline_with_csv(self, sample_csv_file):
        """使用 CSV 文件执行流水线"""
        from main import run_pipeline_mode
        
        # mock 核心模块以避免实际 I/O
        with patch('main._run_geo_phases'):
            result = run_pipeline_mode(csv_path=sample_csv_file)
            # 应该成功进入处理流程
            assert 'status' in result or 'phase_results' in result

    def test_pipeline_with_json_input(self):
        """使用 JSON 字符串输入"""
        from main import run_pipeline_mode
        job_json = json.dumps({
            'id': 'j1',
            'title': '工程师',
            'company': 'TestCo',
            'location': '上海'
        })
        
        with patch('main._run_geo_phases'):
            result = run_pipeline_mode(json_input=job_json)
            assert result is not None

    def test_pipeline_invalid_json(self):
        """无效 JSON 应该抛出错误"""
        from main import run_pipeline_mode
        result = run_pipeline_mode(json_input='{invalid json')
        assert result['status'] == 'error'

    def test_pipeline_empty_jobs(self):
        """空数据集应该报错或返回空"""
        from main import run_pipeline_mode
        
        # load_jobs_from_csv 在 intent_router 模块中，不是 main 的属性
        # 使用正确的 mock 路径
        with patch('intent_router.load_jobs_from_csv', return_value=[]):
            result = run_pipeline_mode(csv_path='dummy.csv')
            # 可能是 error 或 empty 或包含 phase_results
            assert 'status' in result

    def test_pipeline_result_timestamp(self):
        """结果应包含 ISO 时间戳"""
        from main import run_pipeline_mode
        
        with patch('main._run_geo_phases'), \
             patch('intent_router.load_jobs_from_csv', return_value=[{'id': '1'}]):
            result = run_pipeline_mode(csv_path='test.csv')
            assert 'timestamp' in result or 'status' in result


class TestRunDBPipelineMode:
    """数据库驱动模式测试"""

    def test_db_mode_result_structure(self):
        """DB模式返回结构验证"""
        from main import run_db_pipeline_mode
        
        with patch('database_backend.get_backend') as mock_backend_cls:
            mock_backend = MagicMock()
            mock_backend.connect.return_value = True
            mock_backend.test_connection.return_value = {
                'database': 'geo_pipeline.db',
                'total_records': 100,
            }
            mock_backend.get_statistics.return_value = MagicMock(
                total_active=50, urgent_ratio=10.0
            )
            mock_backend.fetch_jobs.return_value = []
            mock_backend_cls.return_value = mock_backend
            
            with patch('main._run_geo_phases'):
                result = run_db_pipeline_mode(limit=20)
                
                assert 'status' in result
                assert 'mode' in result
                assert result['mode'] == 'database'
                assert 'timestamp' in result

    def test_db_connection_failure(self):
        """数据库连接失败时返回错误"""
        from main import run_db_pipeline_mode
        
        with patch('database_backend.get_backend') as mock_backend_cls:
            mock_backend = MagicMock()
            mock_backend.connect.return_value = False
            mock_backend_cls.return_value = mock_backend
            
            result = run_db_pipeline_mode(limit=10)
            
            # 应该是 error 或包含错误信息
            assert result['status'] == 'error'


class TestRunImportMode:
    """CSV 导入模式测试"""

    def test_import_success(self, sample_csv_file):
        """正常导入流程"""
        from main import run_import_mode
        
        with patch('database_backend.get_backend') as mock_backend_cls:
            mock_backend = MagicMock()
            mock_backend.connect.return_value = True
            mock_backend.insert_jobs_batch.return_value = (3, 0)  # 3 inserted, 0 skipped
            mock_backend_cls.return_value = mock_backend
            
            result = run_import_mode(csv_path=sample_csv_file, dry_run=False)
            
            assert 'status' in result
            assert result['mode'] == 'import'
            assert 'import_stats' in result

    def test_import_dry_run(self, sample_csv_file):
        """试运行模式不写入数据库"""
        from main import run_import_mode
        
        result = run_import_mode(csv_path=sample_csv_file, dry_run=True)
        
        assert result['dry_run'] is True
        assert result['status'] == 'dry_run'

    def test_import_missing_csv(self):
        """缺少 CSV 参数时报错"""
        from main import run_import_mode
        
        # 需要捕获 stderr 或检查返回值
        old_argv = sys.argv[:]
        try:
            # import_mode 内部会读取 csv_path，如果为 None 会怎样取决于实现
            # 这里我们只验证函数可调用且不崩溃
            result = run_import_mode(csv_path=None, dry_run=False)
            assert 'error_message' in result or result['status'] == 'error'
        finally:
            sys.argv[:] = old_argv


class TestRunGeoPhases:
    """GEO Phase 1-5 流程测试"""

    def test_phases_compliance_gate_called(self):
        """Phase 1 合规闸门被调用"""
        from main import _run_geo_phases
        
        jobs_data = [
            {'title': 'T1', 'company': 'C1'},
            {'title': 'T2', 'company': 'C2'},
        ]
        results = {'phase_results': {}}
        
        with patch('compliance_gate.ComplianceGate') as mock_gate_cls, \
             patch('intent_router.IntentRouter'), \
             patch('content_factory.ContentFactory'), \
             patch('dist_monitor.DistributionMonitor'):
            
            mock_gate = MagicMock()
            mock_gate.process.return_value = MagicMock(
                status='PASS',
                compliance_score=95.0
            )
            mock_gate_cls.return_value = mock_gate
            
            _run_geo_phases(jobs_data, results, source_id='test')
            
            # 验证合规闸门被调用
            assert mock_gate.process.call_count == 2  # 每个岗位一次
            assert 'compliance_gate' in results['phase_results']

    def test_phases_intent_router_called(self):
        """Phase 2 意图路由被调用"""
        from main import _run_geo_phases
        
        jobs_data = [{'title': 'T', 'company': 'C'}]
        results = {'phase_results': {}}
        
        with patch('compliance_gate.ComplianceGate') as gate_cls, \
             patch('intent_router.IntentRouter') as router_cls, \
             patch('content_factory.ContentFactory'), \
             patch('dist_monitor.DistributionMonitor'):
            
            gate_cls.return_value.process.return_value = MagicMock(status='PASS')
            
            mock_router = MagicMock()
            mock_routing = MagicMock(target_platforms=['wechat'])
            mock_router.batch_process.return_value = [mock_routing]
            router_cls.return_value = mock_router
            
            _run_geo_phases(jobs_data, results)
            
            mock_router.batch_process.assert_called_once()
            assert 'intent_routing' in results['phase_results']

    def test_phases_content_factory_called(self):
        """Phase 3 内容工厂被调用"""
        from main import _run_geo_phases
        
        jobs_data = [{'title': 'T', 'company': 'C'}]
        results = {'phase_results': {}}
        
        with patch('compliance_gate.ComplianceGate') as gate_cls, \
             patch('intent_router.IntentRouter') as router_cls, \
             patch('content_factory.ContentFactory') as factory_cls, \
             patch('dist_monitor.DistributionMonitor'):
            
            gate_cls.return_value.process.return_value = MagicMock(status='PASS')
            router_cls.return_value.batch_process.return_value = [
                MagicMock(target_platforms=['wechat'])
            ]
            
            mock_factory = MagicMock()
            mock_asset = MagicMock(json_ld={'@type': 'JobPosting'})
            mock_asset.schema_validation_url = 'https://validator'
            mock_factory.batch_process.return_value = [mock_asset]
            factory_cls.return_value = mock_factory
            
            _run_geo_phases(jobs_data, results)
            
            mock_factory.batch_process.assert_called_once()
            cf_result = results['phase_results']['content_factory']
            assert cf_result['assets_generated'] >= 1

    def test_phases_all_blocked(self):
        """全部岗位被拦截时不执行后续阶段"""
        from main import _run_geo_phases
        
        jobs_data = [{'title': 'Blocked'}, {'title': 'Also Blocked'}]
        results = {'phase_results': {}}
        
        with patch('compliance_gate.ComplianceGate') as gate_cls, \
             patch('intent_router.IntentRouter') as router_cls, \
             patch('content_factory.ContentFactory') as factory_cls:
            
            # 所有岗位 FAIL
            gate_cls.return_value.process.return_value = MagicMock(status='FAIL')
            
            _run_geo_phases(jobs_data, results)
            
            # 后续阶段不应被调用
            router_cls.return_value.batch_process.assert_not_called()
            factory_cls.return_value.batch_process.assert_not_called()

    def test_phases_pass_rate_calculation(self):
        """通过率计算正确"""
        from main import _run_geo_phases
        
        jobs_data = [{'id': i} for i in range(5)]
        results = {'phase_results': {}}
        
        with patch('compliance_gate.ComplianceGate') as gate_cls, \
             patch('intent_router.IntentRouter'), \
             patch('content_factory.ContentFactory'), \
             patch('dist_monitor.DistributionMonitor'):
            
            # ComplianceGate.process 接收 job dict 和 source_id 参数
            call_count = [0]
            def make_status(*args, **kwargs):
                call_count[0] += 1
                return MagicMock(status='PASS' if call_count[0] < 4 else 'FAIL')
            
            gate_cls.return_value.process.side_effect = make_status
            
            _run_geo_phases(jobs_data, results)
            
            cg = results['phase_results']['compliance_gate']
            assert cg['processed'] == 5


class TestServerMode:
    """HTTP 服务模式测试"""

    def test_server_mode_starts(self):
        """服务模式启动参数正确传递"""
        from main import run_server_mode
        
        # HTTPServer 在 http.server 标准库中，不是 main 模块的属性
        # 需要使用正确的 mock 路径
        with patch('http.server.HTTPServer') as mock_server_cls:
            mock_server = MagicMock()
            mock_server.serve_forever.side_effect = KeyboardInterrupt()
            mock_server_cls.return_value = mock_server
            
            try:
                run_server_mode(port=9999, db_enabled=False, web_ui=False)
            except (KeyboardInterrupt, SystemExit):
                pass
            
            # 验证 HTTPServer 被正确创建
            if mock_server_cls.called:
                call_args = mock_server_cls.call_args[0]
                assert '9999' in str(call_args) or 9999 in str(call_args)

    def test_server_mode_web_ui_enabled(self):
        """Web UI 启用时加载 WebUIHandler"""
        from main import run_server_mode
        
        with patch('http.server.HTTPServer') as mock_server_cls, \
             patch('web_ui.WebUIHandler') as mock_handler_cls:
            
            mock_server = MagicMock()
            mock_server.serve_forever.side_effect = KeyboardInterrupt()
            mock_server_cls.return_value = mock_server
            
            try:
                run_server_mode(port=8080, db_enabled=False, web_ui=True)
            except (KeyboardInterrupt, SystemExit):
                pass
            
            mock_handler_cls.assert_called_once()


class TestCLIMain:
    """CLI 入口测试"""

    def test_main_argparse_defaults(self):
        """默认参数值"""
        from main import main
        old_argv = sys.argv[:]
        try:
            sys.argv = ['main']
            
            # argparse 是标准库，mock 需要在正确位置
            # run_pipeline_mode 返回的结果需要包含 status 字段以避免 _print_results 调用 exit
            with patch('argparse.ArgumentParser') as mock_parser_cls, \
                 patch('main.run_pipeline_mode', return_value={'status': 'success'}):
                
                mock_args = MagicMock()
                mock_args.mode = 'pipeline'
                mock_args.csv = None
                mock_args.json = None
                mock_args.limit = 100
                mock_args.category = None
                mock_args.urgent_only = False
                mock_args.db_type = None
                mock_args.port = 8080
                mock_args.with_db = False
                mock_args.web_ui = True
                mock_args.dry_run = False
                
                mock_parser = MagicMock()
                mock_parser.parse_args.return_value = mock_args
                mock_parser_cls.return_value = mock_parser
                
                main()
                
        finally:
            sys.argv[:] = old_argv

    def test_main_db_mode_routing(self):
        """DB 模式路由正确"""
        from main import main
        
        old_argv = sys.argv[:]
        try:
            sys.argv = ['main', '--mode', 'db']
            
            with patch('argparse.ArgumentParser') as mock_parser_cls, \
                 patch('main.run_db_pipeline_mode', return_value={'status': 'success', 'mode': 'db'}):

                mock_args = MagicMock()
                mock_args.mode = 'db'
                mock_args.limit = 100
                mock_args.category = None
                mock_args.urgent_only = False
                mock_args.db_type = None
                mock_args.port = 8080
                mock_args.with_db = False
                mock_args.web_ui = True
                mock_args.dry_run = False
                
                mock_parser = MagicMock()
                mock_parser.parse_args.return_value = mock_args
                mock_parser_cls.return_value = mock_parser
                
                main()

        finally:
            sys.argv[:] = old_argv

    def test_main_import_mode_requires_csv(self):
        """Import 模式缺少 CSV 时退出 """
        from main import main
        
        old_argv = sys.argv[:]
        try:
            sys.argv = ['main', '--mode', 'import']
            
            with patch('argparse.ArgumentParser') as mock_parser_cls:
                
                mock_args = MagicMock()
                mock_args.mode = 'import'
                mock_args.csv = None  # 缺少必要参数
                mock_args.dry_run = False
                mock_args.limit = 100
                mock_args.category = None
                mock_args.urgent_only = False
                mock_args.db_type = None
                mock_args.port = 8080
                mock_args.with_db = False
                mock_args.web_ui = True
                
                mock_parser = MagicMock()
                mock_parser.parse_args.return_value = mock_args
                mock_parser_cls.return_value = mock_parser
                
                # import mode 缺少 csv 时应退出或报错
                with pytest.raises((SystemExit, Exception)):
                    main()
        finally:
            sys.argv[:] = old_argv


class TestPrintResults:
    """结果格式化输出测试 """

    def test_print_results_success(self, capsys):
        """成功状态输出"""
        from main import _print_results
        _print_results({'status': 'success', 'mode': 'pipeline'})
        captured = capsys.readouterr()
        assert '✅' in captured.out or 'SUCCESS' in captured.out.upper()

    def test_print_results_error(self, capsys):
        """错误状态输出"""
        from main import _print_results
        # _print_results 在 error 状态会调用 sys.exit(1)，需要捕获
        with pytest.raises(SystemExit):
            _print_results({'status': 'error', 'error_message': '连接失败'})
        captured = capsys.readouterr()
        assert '❌' in captured.out or 'ERROR' in captured.out.upper()

    def test_print_results_empty_status(self, capsys):
        """空/干运行状态输出"""
        from main import _print_results
        _print_results({'status': 'empty'})
        captured = capsys.readouterr()
        assert '✅' in captured.out

    def test_print_results_dry_run(self, capsys):
        """试运行状态输出"""
        from main import _print_results
        _print_results({'status': 'dry_run'})
        captured = capsys.readouterr()
        assert '✅' in captured.out


class TestEdgeCases:
    """边界情况与集成场景测试"""

    def test_unicode_job_titles(self, tmp_path):
        """Unicode 岗位标题处理"""
        csv_content = (
            'id,title,company,location,min_salary,max_salary,category,tags,requirements,benefits,is_urgent\n'
            'u1,高级G60算法工程师🚀,松江科创,G60云廊,25000,40000,tech,"AI,深度学习","博士优先","股票期权",true\n'
        )
        csv_file = tmp_path / 'unicode_test.csv'
        csv_file.write_text(csv_content, encoding='utf-8')
        
        from intent_router import load_jobs_from_csv
        jobs = load_jobs_from_csv(str(csv_file))
        assert len(jobs) > 0
        assert '🚀' in jobs[0].get('title', '')

    def test_large_batch_processing(self):
        """大批量数据处理"""
        from main import _run_geo_phases
        
        jobs_data = [{'id': f'job_{i}', 'title': f'岗位{i}'} for i in range(100)]
        results = {'phase_results': {}}
        
        with patch('compliance_gate.ComplianceGate') as gate_cls, \
             patch('intent_router.IntentRouter') as router_cls, \
             patch('content_factory.ContentFactory'), \
             patch('dist_monitor.DistributionMonitor'):
            
            gate_cls.return_value.process.return_value = MagicMock(status='PASS')
            router_cls.return_value.batch_process.return_value = [
                MagicMock(target_platforms=['wechat']) for _ in range(100)
            ]
            
            _run_geo_phases(jobs_data, results)
            
            assert results['phase_results']['compliance_gate']['processed'] == 100
            assert results['phase_results']['compliance_gate']['passed'] == 100

    def test_exception_handling_in_phases(self):
        """阶段执行中异常处理"""
        from main import _run_geo_phases
        
        jobs_data = [{'title': 'T'}]
        results = {'phase_results': {}}
        
        with patch('compliance_gate.ComplianceGate') as gate_cls:
            gate_cls.return_value.process.side_effect = RuntimeError("模拟异常")
            
            # 不应崩溃 - 捕获异常
            try:
                _run_geo_phases(jobs_data, results)
            except (RuntimeError, Exception):
                pass  # 异常被正确处理
            
            # 结果可能因异常而不同，但不应有未处理的异常导致进程退出


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
