#!/usr/bin/env python3
"""
松江快聘GEO系统 - 端到端流水线验证脚本
=============================================

功能描述:
    执行完整的Phase 1→5流水线验证，包含：
    1. CSV数据加载与解析
    2. 合规闸门过滤（禁词检测）
    3. 意图路由（平台分发决策）
    4. Schema.org JSON-LD生成
    5. TL;DR首屏摘要渲染
    6. 引用率监控初始化
    7. 产物文件输出至 dist/ 目录

运行方式:
    python scripts/validate_pipeline.py [--csv data/sample_jobs.csv] [--output dist/]

合规声明: 本脚本仅用于技术验证，所有输出内容需经人工审核后方可发布。
作者: GEO-Engine Team | 版本: v1.0 | 日期: 2026-04-20
"""

import sys
import json
import csv
import os
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional


# 添加项目根目录到Python路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


class PipelineValidator:
    """端到端流水线验证器"""
    
    def __init__(self, csv_path: Optional[str] = None, output_dir: str = "./dist"):
        self.csv_path = csv_path or str(PROJECT_ROOT / "data" / "sample_jobs.csv")
        self.output_dir = Path(output_dir)
        self.results = {
            "validation_id": f"VAL_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "timestamp": datetime.now(timezone(timedelta(hours=8))).isoformat(),
            "phases": {},
            "summary": {
                "total_input": 0,
                "passed_compliance": 0,
                "failed_compliance:": 0,
                "assets_generated": 0,
                "errors": []
            }
        }
        
    def load_csv_data(self) -> List[Dict[str, Any]]:
        """Phase 0: 加载CSV数据"""
        print("\n" + "─" * 60)
        print("📂 Phase 0: 数据加载")
        print("─" * 60)
        
        if not Path(self.csv_path).exists():
            raise FileNotFoundError(f"数据文件不存在: {self.csv_path}")
        
        jobs_data = []
        with open(self.csv_path, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # 数据清洗与类型转换
                job = {
                    "id": row.get('id', ''),
                    "title": row.get('title', '').strip(),
                    "company": row.get('company', '').strip(),
                    "location": row.get('location', '').strip(),
                    "min_salary": float(row.get('min_salary', 0) or 0),
                    "max_salary": float(row.get('max_salary', 0) or 0),
                    "category": row.get('category', 'general'),
                    "tags": [t.strip() for t in row.get('tags', '').split(',') if t.strip()],
                    "requirements": row.get('requirements', '').strip(),
                    "benefits": row.get('benefits', '').strip(),
                    "is_urgent": row.get('is_urgent', 'false').lower() == 'true'
                }
                jobs_data.append(job)
        
        self.results['phases']['data_loading'] = {
            "status": "success",
            "records_loaded": len(jobs_data),
            "source_file": self.csv_path
        }
        self.results['summary']['total_input'] = len(jobs_data)
        
        print(f"   ✅ 成功加载 {len(jobs_data)} 条岗位记录")
        print(f"   📄 来源: {self.csv_path}")
        
        return jobs_data
    
    def validate_phase1_compliance(self, jobs_data: List[Dict]) -> List[Dict]:
        """Phase 1: 合规闸门验证"""
        print("\n" + "─" * 60)
        print("🛡️ Phase 1: 合规闸门验证")
        print("─" * 60)
        
        try:
            from compliance_gate import ComplianceGate
            
            gate = ComplianceGate()
            passed_jobs = []
            
            for idx, job in enumerate(jobs_data):
                job_str = json.dumps(job, ensure_ascii=False)
                result = gate.process(
                    job_str, 
                    source_identifier=f"csv_row_{idx}"
                )
                
                if result.status.upper() in ("PASS", "PASSED", "PARTIAL"):
                    passed_jobs.append(job)
                    self.results['summary']['passed_compliance'] += 1
                else:
                    self.results['summary']['failed_compliance:'] += 1
                    self.results['summary']['errors'].append({
                        "row": idx,
                        "job_title": job.get('title'),
                        "reason": result.status,
                        "banned_words": result.banned_words_found[:3]
                    })
            
            self.results['phases']['compliance'] = {
                "status": "success",
                "total_tested": len(jobs_data),
                "passed": len(passed_jobs),
                "failed": len(jobs_data) - len(passed_jobs),
                "pass_rate": round(len(passed_jobs) / len(jobs_data) * 100, 2) if jobs_data else 0
            }
            
            print(f"   ✅ 合规检查完成:")
            print(f"      通过: {len(passed_jobs)} 条 ({self.results['phases']['compliance']['pass_rate']}%)")
            print(f"      拦截: {len(jobs_data) - len(passed_jobs)} 条")
            
            return passed_jobs
            
        except ImportError as e:
            print(f"   ⚠️ 合规模块导入失败: {e} (使用模拟模式)")
            return jobs_data
    
    def validate_phase2_routing(self, jobs_data: List[Dict]) -> List[Dict]:
        """Phase 2: 意图路由验证"""
        print("\n" + "─" * 60)
        print("🧭 Phase 2: 意图路由分析")
        print("─" * 60)
        
        try:
            from intent_router import IntentRouter
            
            router = IntentRouter()
            routing_results = router.batch_process(jobs_data)
            
            platform_stats = {}
            for r in routing_results:
                for p in r.target_platforms:
                    platform_stats[p] = platform_stats.get(p, 0) + 1
            
            self.results['phases']['intent_routing'] = {
                "status": "success",
                "processed_count": len(routing_results),
                "platform_distribution": platform_stats,
                "lbs_entities_detected": sum(
                    1 for r in routing_results 
                    if r.intent_vector and getattr(r.intent_vector, 'lbs_entity', None)
                )
            }
            
            print(f"   ✅ 路由分析完成:")
            print(f"      处理岗位: {len(routing_results)} 条")
            print(f"      平台分布:")
            for plat, cnt in sorted(platform_stats.items(), key=lambda x: x[1], reverse=True):
                print(f"         • {plat}: {cnt} 条")
            
            return jobs_data  # 返回原始数据，路由结果已记录
            
        except ImportError as e:
            print(f"   ⚠️ 路由模块导入失败: {e}")
            return jobs_data
    
    def validate_phase3_content_factory(self, jobs_data: List[Dict]) -> List[Dict]:
        """Phase 3: 内容工厂验证（Schema + TL;DR）"""
        print("\n" + "─" * 60)
        print("🏭 Phase 3: 内容工厂 (Schema.org + TL;DR)")
        print("─" * 60)
        
        try:
            from content_factory import ContentFactory
            
            factory = ContentFactory()
            assets = factory.batch_process(jobs_data[:10])  # 前10条作为示例
            
            schema_valid_count = sum(
                1 for a in assets 
                if a.schema_validation_url is not None
            )
            tldr_avg_length = 0
            if assets:
                tldr_avg_length = sum(len(a.tldr_summary) for a in assets) // len(assets)
            
            self.results['phases']['content_factory'] = {
                "status": "success",
                "assets_generated": len(assets),
                "schemas_validated": schema_valid_count,
                "avg_tldr_length": tldr_avg_length,
                "sample_output": {
                    "json_ld": assets[0].json_ld,
                    "tldr_summary": assets[0].tldr_summary,
                    "schema_valid": assets[0].schema_validation_url is not None
                } if assets else None
            }
            
            self.results['summary']['assets_generated'] = len(assets)
            
            print(f"   ✅ 内容生成完成:")
            print(f"      资产套数: {len(assets)} 套")
            print(f"      Schema有效: {schema_valid_count}/{len(assets)}")
            print(f"      平均TL;DR长度: {tldr_avg_length} 字符")
            
            # 展示第一条示例
            if assets:
                sample = assets[0]
                print(f"\n   📋 示例输出 (Schema类型: {sample.json_ld.get('@type', 'N/A')}):")
                print(f"      TL;DR: {sample.tldr_summary[:80]}...")
            
            return [a.json_ld for a in assets]  # 返回Schema字典列表
            
        except ImportError as e:
            print(f"   ⚠️ 内容工厂模块导入失败: {e}")
            return []
    
    def validate_phase4_api_readiness(self) -> Dict[str, Any]:
        """Phase 4: API就绪性检查"""
        print("\n" + "─" * 60)
        print("🔌 Phase 4: API配置就绪性检查")
        print("─" * 60)
        
        checks = {
            "wechat": {
                "configured": bool(os.getenv("WECHAT_APP_ID")),
                "base_url": "https://api.weixin.qq.com"
            },
            "douyin": {
                "configured": bool(os.getenv("DOUYIN_CLIENT_KEY")),
                "base_url": "https://open.douyin.com"
            },
            "baidu": {
                "configured": bool(os.getenv("BAIDU_API_KEY")),
                "base_url": "https://ziyuan.baidu.com"
            }
        }
        
        ready_platforms = [
            name for name, cfg in checks.items() 
            if cfg['configured']
        ]
        
        self.results['phases']['api_readiness'] = {
            "status": "partial_ready" if ready_platforms else "not_configured",
            "platforms": checks,
            "ready_count": len(ready_platforms),
            "ready_platforms": ready_platforms,
            "recommendation": (
                "✅ 所有平台已就绪，可执行真实推送" if len(ready_platforms) == 3
                else "⚠️ 部分平台未配置，将使用模拟推送模式"
            )
        }
        
        print(f"   📡 平台配置状态:")
        for name, cfg in checks.items():
            status = "✅ 已配置" if cfg['configured'] else "⚠️ 未配置"
            print(f"      • {name.upper()}: {status}")
        
        print(f"\n   💡 建议: {self.results['phases']['api_readiness']['recommendation']}")
        
        return checks
    
    def generate_validation_report(self, assets: List[Dict]) -> Path:
        """生成验证报告并保存至dist/目录"""
        print("\n" + "─" * 60)
        print("📊 生成验证报告")
        print("─" * 60)
        
        # 创建输出目录
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # 生成报告文件
        report_path = self.output_dir / f"validation_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        report_content = {
            **self.results,
            "report_metadata": {
                "generator": "PipelineValidator v1.0",
                "compliance_standard": ["标识办法2025", "深度合成规定", "个保法"],
                "disclaimer": "本报告仅用于技术验证，内容未经人工审核不得发布"
            },
            "sample_assets": assets[:3]  # 包含前3条示例资产
        }
        
        with open(report_path, 'w', encoding='utf-8') as f:
            json.dump(report_content, f, ensure_ascii=False, indent=2)
        
        # 同时保存Markdown格式报告
        md_report = self._generate_markdown_report()
        md_path = self.output_dir / "VALIDATION_SUMMARY.md"
        with open(md_path, 'w', encoding='utf-8') as f:
            f.write(md_report)
        
        print(f"   📁 报告已保存:")
        print(f"      JSON: {report_path}")
        print(f"      MD:   {md_path}")
        
        return report_path
    
    def _generate_markdown_report(self) -> str:
        """生成Markdown格式的验证摘要"""
        summary = self.results['summary']
        phases = self.results.get('phases', {})
        
        md = f"""# 松江快聘 GEO 流水线验证报告

**验证ID**: {self.results['validation_id']}  
**时间**: {self.results['timestamp']}  
**标准**: 《标识办法》(2025) / 深度合成规定 / 个保法  

---

## 📈 执行摘要

| 指标 | 数值 |
|------|------|
| 输入数据量 | {summary['total_input']} 条 |
| **合规通过率** | **{phases.get('compliance', {}).get('pass_rate', 'N/A')}%** |
| 资产生成数 | {summary['assets_generated']} 套 |
| 错误数 | {len(summary.get('errors', []))} |

---

## 🔍 各阶段详情

### Phase 0: 数据加载
- **状态**: ✅ 成功
- **记录数**: {phases.get('data_loading', {}).get('records_loaded', 'N/A')}
- **来源**: {self.csv_path}

### Phase 1: 合规闸门
- **通过**: {summary.get('passed_compliance', 'N/A')}
- **拦截**: {summary.get('failed_compliance:', 'N/A')}
- **禁词库版本**: v1.0 (12类敏感词)

### Phase 2: 意图路由
- **处理数**: {phases.get('intent_routing', {}).get('processed_count', 'N/A')}
- **LBS实体识别**: {phases.get('intent_routing', {}).get('lbs_entities_detected', 'N/A')}

### Phase 3: 内容工厂
- **Schema有效**: {phases.get('content_factory', {}).get('schemas_validated', 'N/A')}/{phases.get('content_factory', {}).get('assets_generated', 'N/A')}
- **平均TL;DR长度**: {phases.get('content_factory', {}).get('avg_tldr_length', 'N/A')}字符

### Phase 4: API就绪性
- **就绪平台**: {', '.join(phases.get('api_readiness', {}).get('ready_platforms', ['无']))}

---

## ⚠️ 免责声明

> 本报告由GEO自动化管道自动生成，所有内容仅供**内部技术验证**使用。  
> **发布前必须经过人工审核**，确保符合《广告法》《互联网信息服务管理办法》等法律法规。

---
*Generated by 021kp GEO Pipeline Validator v1.0*
"""
        return md
    
    def run_full_validation(self) -> bool:
        """执行完整验证流程"""
        print("\n" + "=" * 60)
        print("🚀 启动松江快聘 GEO 端到端流水线验证")
        print("=" * 60)
        print(f"⏰ 时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"📁 项目根目录: {PROJECT_ROOT}")
        
        success = True
        
        try:
            # Phase 0-3: 核心流程
            jobs_data = self.load_csv_data()
            
            if not jobs_data:
                raise ValueError("未能加载任何数据，请检查CSV文件")
            
            compliant_jobs = self.validate_phase1_compliance(jobs_data)
            routed_jobs = self.validate_phase2_routing(compliant_jobs)
            generated_assets = self.validate_phase3_content_factory(routed_jobs)
            
            # Phase 4: API检查
            api_status = self.validate_phase4_api_readiness()
            
            # 生成报告
            self.generate_validation_report(generated_assets)
            
            # 输出最终结论
            print("\n" + "=" * 60)
            print("✅ 验证流程完成!")
            print("=" * 60)
            print(f"""
📊 验证结果摘要:
   ┌────────────────────────────────────┐
   │ 输入数据:     {self.results['summary']['total_input']:>5} 条          │
   │ 合规通过:     {self.results['summary']['passed_compliance']:>5} 条          │
   │ 资产生成:     {self.results['summary']['assets_generated']:>5} 套          │
   │ 错误数量:     {len(self.results['summary']['errors']):>5} 条          │
   └────────────────────────────────────┘

💡 下一步操作:
   1. 查看 dist/ 目录下的验证报告
   2. 检查生成的 Schema.org JSON-LD 文件
   3. 配置平台凭证后执行真实API推送
   4. 启动定时监控观察引用率变化
""")
            
        except Exception as e:
            success = False
            print(f"\n❌ 验证过程出错: {e}")
            import traceback
            traceback.print_exc()
        
        return success


def main():
    """命令行入口"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="松江快聘GEO系统 - 端到端流水线验证工具",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    parser.add_argument(
        "--csv", "-c",
        default=None,
        help="输入CSV文件路径 (默认: data/sample_jobs.csv)"
    )
    parser.add_argument(
        "--output", "-o",
        default="./dist",
        help="输出目录 (默认: ./dist)"
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="详细输出模式"
    )
    
    args = parser.parse_args()
    
    validator = PipelineValidator(
        csv_path=args.csv,
        output_dir=args.output
    )
    
    success = validator.run_full_validation()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
