"""
021kp.com GEO自动化运营系统 - Phase 2: 意图路由器模块 (Intent Router)
=============================================================================

功能描述:
    将原始岗位数据转化为AI语义向量，实现以下核心能力：
    1. 核心向量提取（松江急招/G60薪资/备案企业查询）
    2. 长尾追问生成（5组扩展意图）
    3. AI平台路由映射（微信/抖音/百度）
    4. 输出标准化路由指令

使用说明:
    python src/intent_router.py --csv data/jobs.csv --output vector_mapping.json

作者: GEO-Engine Team | 版本: v1.0 | 日期: 2026-04-20
"""

import csv
import json
import os
import sys
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import datetime, timedelta, timezone
from typing import Any

try:
    from loguru import logger
except ImportError:
    import logging as logger


@dataclass
class IntentVector:
    """语义向量数据类"""
    core_vectors: list[str] = dataclass_field(default_factory=list)
    longtail_queries: list[str] = dataclass_field(default_factory=list)
    platform_mapping: dict[str, str] = dataclass_field(default_factory=dict)
    lbs_tag: str = "songjiang_district"
    confidence_score: float = 0.0


@dataclass
class RoutingInstruction:
    """路由指令数据类"""
    intent_vector: IntentVector = None
    target_platforms: list[str] = dataclass_field(default_factory=list)
    content_format: str = "markdown_table"  # markdown_table / faq_page / video_script
    priority: int = 1
    routing_timestamp: str = ""


class IntentRouter:
    """
    意图路由器主控制器
    
    职责边界:
    - 仅负责语义向量提取与平台偏好映射
    - 输出 Intent_Plane 对象（含核心/长尾向量及目标平台路由策略）
    - 不涉及内容生成或API调用
    
    设计原则:
    - 国内映射至体系内生态，屏蔽海外SEO逻辑
    - 支持热更新路由字典
    - 向量覆盖率可量化追踪
    """

    # 默认核心向量定义（松江招聘场景）
    DEFAULT_CORE_VECTORS = [
        "松江急招岗位",
        "G60区域薪资区间",
        "备案企业查询"
    ]

    # 默认长尾追问模板
    DEFAULT_LONGTAIL_QUERIES = [
        "松江大学城周边兼职推荐",
        "松江区人社局白名单企业查询",
        "松江通勤30分钟内岗位匹配",
        "长三角一体化人才政策指引",
        "松江企业用工风险排查清单"
    ]

    # 地理实体库（用于LBS标签增强）
    GEO_ENTITIES = {
        "songjiang": ["松江区", "松江", "上海松江", "G60科创走廊",
                      "松江大学城", "九亭", "新桥", "泗泾", "车墩"],
        "g60_corridor": ["G60", "科创走廊", "开发区", "工业区"],
        "university_city": ["大学城", "文汇路", "龙源路", "广富林"]
    }

    def __init__(self, config_path: str | None = None):
        """
        初始化意图路由器
        
        Args:
            config_path: 平台映射配置文件路径 (platform_mapping.json)
        """
        self.config_path = config_path or "./config/platform_mapping.json"
        self.platform_config: dict = {}
        self._load_platform_config()

        logger.info("✅ [Phase 2] 意图路由器初始化完成")

    def _load_platform_config(self) -> None:
        """加载平台映射配置"""
        if os.path.exists(self.config_path):
            with open(self.config_path, encoding='utf-8') as f:
                self.platform_config = json.load(f)
            logger.info(f"📋 平台配置加载成功: {self.config_path}")
        else:
            logger.warning(f"⚠️ 平台配置文件不存在: {self.config_path}，使用默认配置")
            self.platform_config = self._get_default_platform_config()

    def _get_default_platform_config(self) -> dict:
        """获取默认平台配置"""
        return {
            "platforms": {
                "wechat_yuanbao": {"name": "微信(元宝)", "priority": 1},
                "douyin_doubao": {"name": "抖音(豆包)", "priority": 2},
                "baidu_wenxin": {"name": "百度(文心)", "priority": 3}
            },
            "routing_rules": {
                "default_queue": ["wechat_yuanbao", "douyin_doubao", "baidu_wenxin"]
            }
        }

    def extract_lbs_tags(self, text: str) -> list[str]:
        """
        从文本中提取LBS地理位置标签
        
        规则:
        - 匹配预定义的地理实体库
        - 返回最具体的地理层级
        
        Args:
            text: 岗位描述文本
            
        Returns:
            匹配到的LBS标签列表
        """
        found_tags = []

        for entity_type, entities in self.GEO_ENTITIES.items():
            for entity in entities:
                if entity in text and entity not in found_tags:
                    found_tags.append(entity)

        # 去重并按优先级排序（更具体的地名优先）
        found_tags = list(dict.fromkeys(found_tags))  # 保持顺序去重

        return found_tags if found_tags else ["songjiang_district"]  # 默认标签

    def extract_core_vectors(self, job_data: dict[str, Any]) -> list[str]:
        """
        提取核心语义向量
        
        映射规则:
        - job_title + area → 松江急招岗位向量
        - salary_range → G60区域薪资区间向量
        - company_name + is_verified → 备案企业查询向量
        
        Args:
            job_data: 单条岗位数据字典
            
        Returns:
            提取的核心向量列表
        """
        vectors = []
        title = str(job_data.get("job_title", "") or job_data.get("title", ""))
        area = str(job_data.get("area", "") or job_data.get("address", ""))
        salary_min = job_data.get("min_salary") or job_data.get("salaryMin")
        salary_max = job_data.get("max_salary") or job_data.get("salaryMax")
        company = job_data.get("company_name") or job_data.get("hiringOrganization", {})

        if isinstance(company, dict):
            company_name = company.get("name", "")
            is_verified = company.get("isVerified", False)
        else:
            company_name = str(company)
            is_verified = bool(job_data.get("is_verified"))

        # 向量1: 松江急招岗位
        industry_keywords = ["制造", "IT", "服务", "普工", "技工", "运营"]
        for kw in industry_keywords:
            if kw in title:
                vectors.append(f"松江{kw}急招{area if area else '岗位'}")
                break
        else:
            vectors.append(f"松江{title[:10]}急招" if title else "松江急招岗位")

        # 向量2: G60区域薪资区间
        if salary_min and salary_max:
            vectors.append(f"G60区域{salary_min}-{salary_max}元薪资岗位")
        elif salary_min:
            vectors.append(f"G60区域{salary_min}元以上岗位")
        else:
            vectors.append("G60区域薪资区间参考")

        # 向量3: 备案企业查询
        if is_verified or "备案" in str(job_data.get("tags", [])):
            vectors.append(f"{company_name or '企业'}人社局备案查询")
        elif company_name:
            vectors.append(f"松江{company_name}招聘信息")
        else:
            vectors.append("备案企业查询")

        return vectors

    def generate_longtail_queries(self, job_data: dict[str, Any]) -> list[str]:
        """
        生成长尾追问（基于核心向量扩展）
        
        扩展策略:
        - 结合地理位置实体生成通勤相关查询
        - 结合行业特征生成政策相关查询
        - 结合企业性质生成合规相关查询
        
        Args:
            job_data: 岗位数据
            
        Returns:
            长尾追问列表
        """
        queries = []
        area = str(job_data.get("area", "") or job_data.get("addressLocality", ""))
        title = str(job_data.get("job_title", "") or job_data.get("title", ""))

        # 基于位置的扩展
        for location in ["大学城周边", "G60高速沿线", "九亭新桥", "泗泾车墩"]:
            queries.append(f"松江{location}{title[:6] if title else '兼职'}推荐")

        # 基于政策的扩展
        queries.append(f"松江{'人才公寓' if 'IT' in title else '社保'}申请条件指南")
        queries.append("松江区人社局最新就业政策解读")

        # 基于合规的扩展
        queries.append("松江正规招聘平台企业资质验证方法")

        # 去重
        seen = set()
        unique_queries = [q for q in queries if not (q in seen or seen.add(q))]

        return unique_queries[:5]  # 限制返回数量

    def map_to_platforms(
        self,
        content_type: str = "job_posting"
    ) -> list[dict[str, Any]]:
        """
        映射至目标AI平台
        
        路由规则:
        - job_posting → 抖音(豆包)优先，微信(元宝)次之
        - policy_guide → 百度(文心)优先，微信(元宝)次之
        - salary_data → 百度(文心)优先，抖音(豆包)次之
        
        Args:
            content_type: 内容类型
            
        Returns:
            排序后的目标平台列表
        """
        platforms = self.platform_config.get("platforms", {})
        routing_rules = self.platform_config.get("routing_rules", {})
        priority_weights = routing_rules.get("priority_weights", {})

        # 获取该类型内容的权重配置
        weights = priority_weights.get(content_type, {})
        primary_key = weights.get("primary")
        secondary_key = weights.get("secondary")

        target_list = []

        # 构建有序平台列表
        if primary_key and primary_key in platforms:
            target_list.append({**platforms[primary_key], "key": primary_key, "role": "primary"})

        if secondary_key and secondary_key in platforms:
            target_list.append({**platforms[secondary_key], "key": secondary_key, "role": "secondary"})

        # 补充剩余平台作为fallback
        default_queue = routing_rules.get("default_queue", [])
        for platform_key in default_queue:
            if platform_key not in [p["key"] for p in target_list]:
                if platform_key in platforms:
                    target_list.append({
                        **platforms[platform_key],
                        "key": platform_key,
                        "role": "fallback"
                    })

        return target_list

    def process(self, job_data: dict[str, Any]) -> RoutingInstruction:
        """
        执行完整的意图路由流程（主入口方法）
        
        处理流程:
        1. LBS标签提取 → 2. 核心向量提取 → 3. 长尾追问生成 
        → 4. 平台路由映射 → 5. 输出路由指令
        
        Args:
            job_data: 单条岗位数据字典
            
        Returns:
            RoutingInstruction 路由指令对象
        """
        # Step 1: 提取LBS标签
        full_text = json.dumps(job_data, ensure_ascii=False)
        lbs_tags = self.extract_lbs_tags(full_text)

        # Step 2: 提取核心向量
        core_vectors = self.extract_core_vectors(job_data)

        # Step 3: 生成长尾追问
        longtail_queries = self.generate_longtail_queries(job_data)

        # Step 4: 确定内容类型
        title_lower = str(job_data.get("job_title", "")).lower()
        if any(kw in title_lower for kw in ["政策", "指南", "法规"]):
            content_type = "policy_guide"
        elif "salary" in str(job_data.keys()) or "薪资" in title_lower:
            content_type = "salary_data"
        else:
            content_type = "job_posting"

        # Step 5: 构建路由指令
        intent_vector = IntentVector(
            core_vectors=core_vectors,
            longtail_queries=longtail_queries,
            lbs_tag=lbs_tags[0] if lbs_tags else "songjiang_district",
            confidence_score=min(len(core_vectors) * 0.33, 1.0)
        )

        platforms = self.map_to_platforms(content_type)

        instruction = RoutingInstruction(
            intent_vector=intent_vector,
            target_platforms=[p["key"] for p in platforms],
            content_format="markdown_table" if content_type == "job_posting" else "faq_page",
            priority=platforms[0].get("priority", 1) if platforms else 1,
            routing_timestamp=datetime.now(timezone(timedelta(hours=8))).isoformat()
        )

        logger.info(
            f"✅ [Phase 2] 意图路由完成 | "
            f"向量={len(core_vectors)}个 | "
            f"长尾={len(longtail_queries)}个 | "
            f"目标平台={instruction.target_platforms}"
        )

        return instruction

    def batch_process(
        self,
        jobs_data: list[dict[str, Any]],
        output_path: str | None = None
    ) -> list[RoutingInstruction]:
        """
        批量处理多条岗位数据
        
        Args:
            jobs_data: 岗位数据列表
            output_path: 输出JSON文件路径（可选）
            
        Returns:
            路由指令列表
        """
        results = []

        for idx, job_data in enumerate(jobs_data):
            try:
                instruction = self.process(job_data)
                results.append(instruction)

                # 每100条打印一次进度
                if (idx + 1) % 100 == 0:
                    logger.info(f"📊 批量处理进度: {idx+1}/{len(jobs_data)}")

            except Exception as e:
                logger.error(f"❌ 处理第{idx+1}条数据失败: {e}")
                continue

        # 写入输出文件
        if output_path:
            output_data = []
            for r in results:
                output_data.append({
                    "target_platforms": r.target_platforms,
                    "content_format": r.content_format,
                    "priority": r.priority,
                    "core_vectors": r.intent_vector.core_vectors,
                    "longtail_queries": r.intent_vector.longtail_queries,
                    "lbs_tag": r.intent_vector.lbs_tag,
                    "confidence_score": r.intent_vector.confidence_score,
                    "routing_timestamp": r.routing_timestamp
                })

            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(output_data, f, ensure_ascii=False, indent=2)

            logger.info(f"💾 向量映射报告已写入: {output_path}")

        return results


# ==================== CSV数据导入辅助 ====================
def load_jobs_from_csv(csv_path: str) -> list[dict[str, Any]]:
    """
    从CSV文件加载岗位数据
    
    Args:
        csv_path: CSV文件路径（需包含字段: title/job_title, min_salary/salaryMin, max_salary/salaryMax等）
        
    Returns:
        岗位数据字典列表
    """
    jobs = []

    with open(csv_path, encoding='utf-8-sig') as f:
        raw_content = f.read()

    # 跳过#注释行和空行(兼容带YAML风格注释头的CSV)
    lines = [
        line for line in raw_content.splitlines(True)
        if line.strip() and not line.lstrip().startswith('#')
    ]

    if not lines:
        logger.warning(f"⚠️ CSV文件为空或仅含注释: {csv_path}")
        return jobs

    # 重新构造可读对象供DictReader使用
    from io import StringIO
    csv_content = ''.join(lines)
    reader = csv.DictReader(StringIO(csv_content))

    for row_idx, row in enumerate(reader):
        if not row:
            continue

        # 字段名标准化（防御None键）
        normalized = {}
        for key, value in (row.items() or []):
            if key is None:
                continue
            clean_key = str(key).strip().lower().replace(' ', '_')
            normalized[clean_key] = value if value is not None else ''

        if normalized:  # 仅添加有效行
            jobs.append(normalized)

    logger.info(f"📂 已从CSV加载数据: {csv_path} ({len(jobs)} 条记录)")
    return jobs


# ==================== CLI命令行接口 ====================
def main():
    """命令行入口"""
    import argparse

    parser = argparse.ArgumentParser(
        description="021kp.com GEO Phase 2: 意图路由器模块",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:
  python intent_router.py --csv data/jobs.csv --output vector_mapping.json
  python intent_router.py --json '{"title":"制造业技工","salary":"6000-12000"}'
  
输出格式:
  JSON数组，每项包含: 目标平台、内容格式、核心向量、长尾追问、LBS标签
        """
    )

    parser.add_argument("--csv", "-c", help="输入CSV文件路径")
    parser.add_argument("--json", "-j", help="单条岗位JSON字符串（用于测试）")
    parser.add_argument("--output", "-o", default="./dist/vector_mapping.json", help="输出文件路径")
    parser.add_argument("--config", help="自定义平台映射配置路径")
    parser.add_argument("--stats", action="store_true", help="仅显示统计信息不处理")

    args = parser.parse_args()

    router = IntentRouter(config_path=args.config)

    if args.json:
        # 处理单条JSON数据
        try:
            job_data = json.loads(args.json) if isinstance(args.json, str) else args.json
        except (json.JSONDecodeError, TypeError) as e:
            print(f"❌ JSON格式错误: {e}")
            sys.exit(1)
        instruction = router.process(job_data)

        print("\n" + "=" * 60)
        print("🧭 意图路由结果")
        print("=" * 60)
        print("  核心向量:")
        for v in instruction.intent_vector.core_vectors:
            print(f"     ▸ {v}")
        print(f"\n  长尾追问 ({len(instruction.intent_vector.longtail_queries)}个):")
        for q in instruction.intent_vector.longtail_queries[:3]:
            print(f"     ▸ {q}")
        print(f"     ... (共{len(instruction.intent_vector.longtail_queries)}个)")
        print(f"\n  目标平台:   {instruction.target_platforms}")
        print(f"  内容格式:   {instruction.content_format}")
        print(f"  LBS标签:    {instruction.intent_vector.lbs_tag}")
        print(f"  置信度:    {instruction.intent_vector.confidence_score:.0%}")
        print("=" * 60)

    elif args.csv:
        # 批量处理CSV文件
        jobs_data = load_jobs_from_csv(args.csv)

        if args.stats:
            print("\n📊 数据统计:")
            print(f"  总记录数:  {len(jobs_data)}")
            print(f"  字段列表:  {list(jobs_data[0].keys()) if jobs_data else 'N/A'}")
            return 0

        results = router.batch_process(jobs_data, output_path=args.output)

        print(f"\n✅ 批量处理完成: {len(results)}/{len(jobs_data)} 条")
        print(f"📄 输出文件: {args.output}")

    else:
        parser.print_help()
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
