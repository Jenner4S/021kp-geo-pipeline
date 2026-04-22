#!/usr/bin/env python3
"""
松江快聘GEO系统 - AI预览模拟器
===================================

功能描述:
    模拟AI增强的内容生成效果，展示GEO处理后的预期输出，
    帮助用户在正式发布前预览和审核内容质量。

特性:
    ✅ 本地化运行，无需外部AI API
    ✅ 基于规则引擎的智能内容优化
    ✅ 实时预览HTML渲染效果
    ✅ 一键导出为可发布格式

作者: GEO-Engine Team | 版本: v1.0 | 日期: 2026-04-20
"""

import sys
import json
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
import random

# 添加项目路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))


@dataclass
class AIPreviewResult:
    """AI预览结果"""
    original_job: Dict[str, Any]
    optimized_title: str
    seo_description: str
    schema_jsonld: Dict[str, Any]
    tldr_summary: str
    suggested_tags: List[str]
    compliance_score: float  # 0-100
    quality_score: float     # 0-100
    preview_html: str
    estimated_citation_rate: float  # 预估引用率


class AIPreviewSimulator:
    """
    AI预览模拟器
    
    使用规则引擎模拟AI内容优化效果，
    无需调用外部API即可快速预览。
    """
    
    # 松江区地理实体词库（用于SEO增强）
    SONGJIANG_ENTITIES = [
        "松江", "G60科创走廊", "松江大学城", "松江南站",
        "九亭镇", "新桥镇", "车墩镇", "洞泾镇", "泗泾镇",
        "佘山镇", "小昆山镇", "新浜镇", "叶榭镇", "石湖荡镇",
        "松江新城", "松江老城", "松江经开区", "松江综保区",
        "长三角一体化", "上海西南门户", "科创云廊"
    ]
    
    # 行业热词映射
    INDUSTRY_HOTWORDS = {
        "manufacturing": ["智能制造", "工业4.0", "数控加工", "质量体系认证", "五险一金包吃住"],
        "ecommerce": ["电商运营", "数据分析", "直播带货", "流量变现", "团队氛围好"],
        "technology": ["技术研发", "创新驱动", "职业发展", "期权激励", "弹性工作制"],
        "logistics": ["智慧物流", "供应链管理", "仓储优化", "现代化园区", "包吃住"],
        "education": ["教育培训", "成长平台", "双休稳定", "带薪年假", "节日福利"],
        "hr_services": ["人力资源", "专业发展", "行业领先", "五险一金", "绩效奖金"]
    }
    
    # 高薪吸引力词汇
    SALARY_ATTRACTORS = {
        "high": ["薪资优厚", "竞争力薪酬", "行业领先水平", "丰厚年终奖"],
        "medium": ["待遇从优", "绩效奖金", "晋升空间大", "福利完善"],
        "entry": ["提供培训", "包教包会", "新手友好", "稳定收入保障"]
    }
    
    def __init__(self):
        self.preview_history: List[AIPreviewResult] = []
    
    def optimize_job_title(self, job: Dict) -> str:
        """
        优化岗位标题（增加地理实体+吸引力词汇）
        
        示例输入: "CNC数控操作员"
        示例输出: "[松江G60急招] CNC数控操作员 | 五险一金+包住 | 月薪6500-9000"
        """
        original_title = job.get('title', '')
        location = job.get('location', '')
        min_sal = job.get('min_salary', 0)
        max_sal = job.get('max_salary', 0)
        is_urgent = job.get('is_urgent', False)
        category = job.get('category', 'general')
        
        # 提取地理关键词
        geo_keywords = self._extract_geo_keywords(location)
        primary_geo = geo_keywords[0] if geo_keywords else "松江"
        
        # 构建优化标题
        parts = []
        
        # 1. 地理标签
        if is_urgent:
            parts.append(f"[{primary_geo}急招]")
        else:
            parts.append(f"[{primary_geo}]")
        
        # 2. 原始标题
        parts.append(original_title)
        
        # 3. 薪资亮点
        if max_sal >= 15000:
            salary_text = f"月薪{min_sal//1000}K-{max_sal//1000}K"
        elif max_sal >= 8000:
            salary_text = f"¥{min_sal}-{max_sal}"
        else:
            salary_text = f"薪资{min_sal}-{max_sal}"
        parts.append(salary_text)
        
        # 4. 核心福利（取前2个）
        benefits = job.get('benefits', '')
        benefit_items = re.split(r'[，,；;、]', benefits)[:2]
        if benefit_items and benefit_items[0]:
            parts.append('+'.join(benefit_items))
        
        return " ".join(parts)
    
    def generate_seo_description(self, job: Dict) -> str:
        """生成SEO友好的职位描述"""
        title = job.get('title', '')
        company = job.get('company', '')
        location = job.get('location', '')
        category = job.get('category', '')
        requirements = job.get('requirements', '')[:200]
        
        geo = self._extract_geo_keywords(location)[0] if self._extract_geo_keywords(location) else "松江区"
        
        desc = f"""{company}诚聘{title}，工作地点位于{geo}{location[len(geo):] if geo in location else ''}。
本岗位{self._get_category_description(category)}，薪资待遇优厚。
{'急招岗位，名额有限！' if job.get('is_urgent') else ''}
主要职责：{requirements[:80]}...
立即投递，开启您的{geo}职场新篇章！"""
        
        return desc.replace('\n', ' ').strip()
    
    def generate_schema_jsonld(self, job: Dict) -> Dict[str, Any]:
        """
        生成Schema.org JobPosting结构化数据
        
        符合Google搜索富媒体展示要求
        """
        now = datetime.now().strftime("%Y-%m-%d")
        
        schema = {
            "@context": "https://schema.org",
            "@type": "JobPosting",
            "title": job.get('title', ''),
            "description": self.generate_seo_description(job),
            "datePosted": now,
            "employmentType": "FULL_TIME",
            "hiringOrganization": {
                "@type": "Organization",
                "name": job.get('company', ''),
                "sameAs": "https://www.021kp.com",
                "logo": "https://www.021kp.com/logo.png"
            },
            "jobLocation": {
                "@type": "Place",
                "address": {
                    "@type": "PostalAddress",
                    "addressLocality": "上海市松江区",
                    "addressRegion": "上海市",
                    "addressCountry": "CN"
                }
            },
            "baseSalary": {
                "@type": "MonetaryAmount",
                "currency": "CNY",
                "value": {
                    "@type": "QuantitativeValue",
                    "minValue": job.get('min_salary', 0),
                    "maxValue": job.get('max_salary', 0),
                    "unitText": "MONTH"
                }
            }
        }
        
        # 可选字段
        if job.get('benefits'):
            schema['jobBenefits'] = job.get('benefits')[:200]
        
        if job.get('requirements'):
            schema['experienceRequirements'] = {
                "@type": "OccupationalExperienceRequirements",
                "monthsOfExperience": self._estimate_experience(job.get('requirements', ''))
            }
        
        return schema
    
    def generate_tldr(self, job: Dict, max_length: int = 120) -> str:
        """
        生成TL;DR首屏摘要（≤120字）
        
        格式: 【公司】岗位 | 薪资 | 核心要求 | 福利亮点
        """
        company_short = job.get('company', '')[:8]
        title = job.get('title', '')
        
        min_s = job.get('min_salary', 0)
        max_s = job.get('max_salary', 0)
        
        # 薪资显示
        if max_s >= 10000:
            sal_str = f"{min_s//1000}K-{max_s//1000}K/月"
        else:
            sal_str = f"{min_s}-{max_s}/月"
        
        # 提取核心要求（第一句话）
        req = job.get('requirements', '')
        req_core = re.split(r'[；;。，]', req)[0][:30] if req else ""
        
        # 提取核心福利（第一个）
        ben = job.get('benefits', '')
        ben_core = re.split(r'[，,；;]', ben)[0][:15] if ben else ""
        
        tldr = f"【{company_short}】{title} | {sal_str}"
        if req_core:
            tldr += f" | 要求:{req_core}"
        if ben_core:
            tldr += f" | {ben_core}"
        
        # 截断至最大长度
        if len(tldr) > max_length:
            tldr = tldr[:max_length-3] + "..."
        
        return tldr
    
    def suggest_tags(self, job: Dict) -> List[str]:
        """
        推荐SEO标签组合
        
        策略: 地理标签 + 行业标签 + 薪资区间标签 + 长尾关键词
        """
        tags = set()
        
        # 地理标签
        location = job.get('location', '')
        geo_tags = self._extract_geo_keywords(location)[:2]
        tags.update(geo_tags)
        
        # 行业标签
        category = job.get('category', '')
        industry_tags = self.INDUSTRY_HOTWORDS.get(category, [])[:2]
        tags.update([t.split(',')[0] for t in industry_tags if t])
        
        # 薪资区间标签
        max_sal = job.get('max_salary', 0)
        if max_sal >= 15000:
            tags.add("高薪岗位")
        elif max_sal >= 8000:
            tags.add("薪资优厚")
        elif max_sal >= 5000:
            tags.add("待遇从优")
        
        # 急招标签
        if job.get('is_urgent'):
            tags.add("松江急招岗位")
        
        # 长尾关键词
        longtail_map = {
            "manufacturing": ["松江制造业技工", "G60工业园区招聘"],
            "ecommerce": ["松江电商运营", "长三角电商人才"],
            "technology": ["松江科技研发", "G60科创走廊岗位"],
            "education": ["松江教育行业", "大学城周边兼职"],
            "logistics": ["松江物流园区", "智慧物流岗位"]
        }
        longtail = longtail_map.get(category, [])[:1]
        tags.update(longtail)
        
        return list(tags)[:8]  # 最多返回8个标签
    
    def calculate_scores(self, job: Dict) -> tuple:
        """
        计算合规评分与质量评分
        
        Returns:
            (compliance_score, quality_score) 元组, 范围0-100
        """
        comp_score = 100.0
        qual_score = 50.0  # 基础分
        
        # 合规扣分项
        content = json.dumps(job, ensure_ascii=False)
        
        # 检测疑似违规词汇
        suspicious_words = ["包过", "稳赚", "绝对", "最高", "第一", "国家级"]
        for word in suspicious_words:
            if word in content:
                comp_score -= 10
        
        # 检查必填字段完整性
        required_fields = ['title', 'company', 'location', 'min_salary', 'max_salary']
        for field in required_fields:
            if job.get(field):
                qual_score += 8
            else:
                qual_score -= 5
        
        # 质量加分项
        if len(job.get('requirements', '')) > 30:
            qual_score += 10  # 要求描述充分
        if len(job.get('benefits', '')) > 20:
            qual_score += 8   # 福利说明清晰
        if job.get('tags') and len(job['tags']) >= 3:
            qual_score += 7   # 标签丰富
        if job.get('min_salary', 0) > 0 and job.get('max_salary', 0) > 0:
            qual_score += 7   # 薪资透明
        
        # 分数归一化到0-100
        comp_score = max(0, min(100, comp_score))
        qual_score = max(0, min(100, qual_score))
        
        return comp_score, qual_score
    
    def estimate_citation_rate(self, job: Dict) -> float:
        """
        预估搜索引擎引用率
        
        基于因素:
        - 地理实体丰富度 (+)
        - 薪资竞争力 (+)
        - 内容完整度 (+)
        - 行业热度 (+)
        - 急招时效性 (+++)
        """
        base_rate = 0.002  # 基础引用率 0.2%
        
        factors = []
        
        # 地理实体因子
        location = job.get('location', '')
        geo_count = len(self._extract_geo_keywords(location))
        factors.append(geo_count * 0.0005)  # 每个地理实体+0.05%
        
        # 薪资竞争力
        avg_sal = (job.get('min_salary', 0) + job.get('max_salary', 0)) / 2
        if avg_sal >= 12000:
            factors.append(0.003)
        elif avg_sal >= 8000:
            factors.append(0.0015)
        else:
            factors.append(0.0005)
        
        # 急招加成
        if job.get('is_urgent'):
            factors.append(0.002)
        
        # 内容质量
        _, qual_score = self.calculate_scores(job)
        factors.append((qual_score / 100) * 0.001)
        
        # 行业热度权重
        hot_categories = {"manufacturing": 1.2, "technology": 1.3, "ecommerce": 1.1}
        cat_weight = hot_categories.get(job.get('category', ''), 1.0)
        
        estimated = base_rate * cat_weight + sum(factors)
        
        # 加入随机波动(±0.001)模拟真实环境
        estimated += random.uniform(-0.0005, 0.001)
        
        return round(max(0.001, min(0.02, estimated)), 4)  # 限制在0.1%-2%范围内
    
    def generate_preview_html(self, job: Dict, preview_result: AIPreviewResult) -> str:
        """
        生成HTML预览页面（用于浏览器查看效果）
        """
        schema_html = json.dumps(preview_result.schema_jsonld, ensure_ascii=False, indent=2)
        
        html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>GEO预览 - {preview_result.optimized_title}</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
               max-width: 800px; margin: 40px auto; padding: 20px; background: #f5f5f5; }}
        .card {{ background: white; border-radius: 12px; padding: 24px; box-shadow: 0 2px 8px rgba(0,0,0,0.1); margin-bottom: 20px; }}
        .header {{ border-left: 4px solid #1890ff; padding-left: 16px; margin-bottom: 20px; }}
        .score-badge {{ display: inline-block; padding: 4px 12px; border-radius: 16px; font-size: 14px; margin-right: 8px; }}
        .score-high {{ background: #f6ffed; color: #52c41a; border: 1px solid #b7eb8f; }}
        .score-medium {{ background: #fffbe6; color: #faad14; border: 1px solid #ffe58f; }}
        .tag {{ display: inline-block; background: #e6f7ff; color: #1890ff; padding: 4px 10px; border-radius: 4px; margin: 4px 4px 4px 0; font-size: 13px; }}
        pre {{ background: #f6f6f6; padding: 16px; border-radius: 8px; overflow-x: auto; font-size: 13px; }}
        .tldr {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 16px; border-radius: 8px; font-size: 15px; line-height: 1.6; }}
        .ai-marker {{ color: #999; font-size: 12px; margin-top: 12px; }}
        h2 {{ color: #333; margin-top: 24px; }}
        h3 {{ color: #666; font-size: 16px; }}
    </style>
</head>
<body>
    <div class="card">
        <div class="header">
            <h1 style="margin: 0;">🔍 AI预览模拟结果</h1>
            <p style="color: #999; margin: 8px 0 0 0;">松江快聘GEO自动化管道 | {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
        </div>
        
        <!-- 评分 -->
        <div style="margin-bottom: 24px;">
            <span class="score-badge {'score-high' if preview_result.compliance_score >= 90 else 'score-medium'}">
                合规评分: {preview_result.compliance_score:.0f}
            </span>
            <span class="score-badge {'score-high' if preview_result.quality_score >= 70 else 'score-medium'}">
                质量评分: {preview_result.quality_score:.0f}
            </span>
            <span class="score-badge score-medium">
                预估引用率: {preview_result.estimated_citation_rate*100:.2f}%
            </span>
        </div>
        
        <!-- 优化后的标题 -->
        <h2>📌 优化后标题</h2>
        <p style="font-size: 18px; font-weight: bold; color: #1890ff;">{preview_result.optimized_title}</p>
        
        <!-- TL;DR摘要 -->
        <h2>⚡ TL;DR 首屏摘要</h2>
        <div class="tldr">{preview_result.tldr_summary}</div>
        
        <!-- SEO描述 -->
        <h2>📝 SEO描述</h2>
        <p>{preview_result.seo_description}</p>
        
        <!-- 推荐标签 -->
        <h2>🏷️ 推荐标签</h2>
        <div>
            {''.join(f'<span class="tag">{tag}</span>' for tag in preview_result.suggested_tags)}
        </div>
        
        <!-- Schema.org JSON-LD -->
        <h2>📋 Schema.org 结构化数据 (JSON-LD)</h2>
        <pre><code>{schema_html}</code></pre>
        
        <!-- 原始数据对照 -->
        <h2>📊 原始数据对照</h2>
        <pre><code>{json.dumps(preview_result.original_job, ensure_ascii=False, indent=2)}</code></pre>
        
        <!-- AI标识 -->
        <div class="ai-marker">
            ⚠️ AI辅助生成标识: 本内容由AI整理，仅供参考 | 
            来源: jiangsong_kuaipin_v1_{datetime.now().strftime('%Y%m%d')}
        </div>
    </div>
</body>
</html>"""
        return html
    
    def preview_single_job(self, job: Dict) -> AIPreviewResult:
        """对单条岗位进行AI预览模拟"""
        optimized_title = self.optimize_job_title(job)
        seo_desc = self.generate_seo_description(job)
        schema = self.generate_schema_jsonld(job)
        tldr = self.generate_tldr(job)
        tags = self.suggest_tags(job)
        comp_score, qual_score = self.calculate_scores(job)
        citation_rate = self.estimate_citation_rate(job)
        
        result = AIPreviewResult(
            original_job=job,
            optimized_title=optimized_title,
            seo_description=seo_desc,
            schema_jsonld=schema,
            tldr_summary=tldr,
            suggested_tags=tags,
            compliance_score=comp_score,
            quality_score=qual_score,
            preview_html="",  # 占位，下面立即填充
            estimated_citation_rate=citation_rate
        )
        
        # 生成HTML预览（依赖完整result对象）
        result.preview_html = self.generate_preview_html(job, result)
        
        self.preview_history.append(result)
        return result
    
    def batch_preview(self, jobs: List[Dict], limit: int = 5) -> List[AIPreviewResult]:
        """批量预览多条岗位"""
        results = []
        for job in jobs[:limit]:
            result = self.preview_single_job(job)
            results.append(result)
        
        return results
    
    # ==================== 私有方法 ====================
    
    def _extract_geo_keywords(self, location: str) -> List[str]:
        """从地址中提取松江区地理实体"""
        found = []
        for entity in self.SONGJIANG_ENTITIES:
            if entity in location:
                found.append(entity)
        return found if found else ["松江区"]
    
    def _get_category_description(self, category: str) -> str:
        """获取行业类别描述"""
        descriptions = {
            "manufacturing": "属于松江G60先进制造业重点发展领域",
            "ecommerce": "立足松江电子商务产业园，发展前景广阔",
            "technology": "依托G60科创走廊，技术创新驱动发展",
            "logistics": "服务松江智慧物流枢纽，供应链核心岗位",
            "education": "毗邻松江大学城，教育资源优质丰富",
            "hr_services": "深耕松江人力资源市场，专业可靠"
        }
        return descriptions.get(category, "位于上海市松江区")
    
    def _estimate_experience(self, requirements: str) -> int:
        """根据要求文本估算经验月份"""
        exp_patterns = [(r'(\d+)\s*年', 12), (r'(\d+)\s*以上', 36), (r'(\d+)\s*-', 12)]
        
        for pattern, multiplier in exp_patterns:
            match = re.search(pattern, requirements)
            if match:
                return int(match.group(1)) * multiplier
        
        return 0  # 默认不限经验


def main():
    """命令行入口"""
    import argparse
    import csv
    
    parser = argparse.ArgumentParser(description="松江快聘GEO系统 - AI预览模拟器")
    parser.add_argument("--csv", "-c", default=str(PROJECT_ROOT / "data" / "sample_jobs.csv"))
    parser.add_argument("--output", "-o", default="./dist/previews")
    parser.add_argument("--limit", "-l", type=int, default=3, help="预览条数上限")
    parser.add_argument("--open-browser", action="store_true", help="在浏览器中打开预览")
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("🤖 松江快聘 GEO AI预览模拟器")
    print("=" * 60)
    
    # 加载数据
    jobs = []
    with open(args.csv, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            jobs.append(row)
    
    if not jobs:
        print("❌ 未读取到数据")
        sys.exit(1)
    
    print(f"📂 加载了 {len(jobs)} 条岗位数据\n")
    
    # 执行预览
    simulator = AIPreviewSimulator()
    results = simulator.batch_preview(jobs, limit=args.limit)
    
    # 输出目录
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # 保存预览结果
    for idx, result in enumerate(results):
        # 保存HTML
        html_path = output_dir / f"preview_{result.original_job.get('id', idx)}.html"
        with open(html_path, 'w', encoding='utf-8') as f:
            f.write(result.preview_html)
        
        print(f"--- 预览 #{idx+1}: {result.original_job.get('title', 'N/A')} ---")
        print(f"   优化标题: {result.optimized_title[:60]}...")
        print(f"   TL;DR: {result.tldr_summary}")
        print(f"   合规评分: {result.compliance_score:.0f} | 质量评分: {result.quality_score:.0f}")
        print(f"   预估引用率: {result.estimated_citation_rate*100:.2f}%")
        print(f"   HTML预览: {html_path}")
        print()
    
    # 保存汇总JSON
    summary_path = output_dir / "preview_summary.json"
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump([
            {
                "original": r.original_job,
                "optimized_title": r.optimized_title,
                "tldr": r.tldr_summary,
                "compliance_score": r.compliance_score,
                "quality_score": r.quality_score,
                "estimated_citation_rate": r.estimated_citation_rate,
                "tags": r.suggested_tags
            }
            for r in results
        ], f, ensure_ascii=False, indent=2)
    
    print(f"✅ 预览完成! 共生成 {len(results)} 个预览文件")
    print(f"📁 输出目录: {output_dir}")
    
    if args.open_browser:
        import webbrowser
        webbrowser.open(str(output_dir / f"preview_{results[0].original_job.get('id', 0)}.html"))


if __name__ == "__main__":
    main()
