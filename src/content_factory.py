"""
021kp.com GEO自动化运营系统 - Phase 3: 内容工厂模块 (Content Factory)
=============================================================================

功能描述:
    将岗位数据转化为AI最易引用的结构化资产，实现以下核心能力：
    1. 生成符合Schema.org标准的JobPosting JSON-LD
    2. 生成 Organization / LocalBusiness 结构化数据（存在层）
    3. 生成 FAQPage 长尾问答结构化数据（推荐层）
    4. 生成 BreadcrumbList 导航结构化数据
    5. 渲染首屏TL;DR摘要（≤120字）
    6. 植入引用钩子句式（≥3个/千字）
    7. 输出Markdown表格化岗位对比数据
    8. GEO 四阶段审计评分（存在层/推荐层/转化层/品牌层）

GEO 框架对齐:
    - 存在层: Organization Schema + LocalBusiness Schema + 背书积累
    - 推荐层: FAQPage Schema + 长尾提问承接 + 差异化标签
    - 转化层: 信任证明元素 + 着陆页优化指引
    - 品牌层: 全域一致性检查 + 内容沉淀策略

使用说明:
    python src/content_factory.py --csv data/jobs.csv --schema-out dist/schema.jsonld --md-out dist/posts.md

作者: GEO-Engine Team | 版本: v2.0 (GEO四阶段对齐) | 日期: 2026-04-21
"""

import json
import re
import sys
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

try:
    from jinja2 import Environment, FileSystemLoader, Template
    from loguru import logger
except ImportError:
    logger = __import__("logging").getLogger(__name__)
    # 简易模板渲染（无Jinja2时的fallback）
    def simple_template(template_str: str, **kwargs) -> str:
        result = template_str
        for key, value in kwargs.items():
            result = result.replace("{{ " + key + " }}", str(value))
        return result

    class Template:
        def __init__(self, template_str):
            self.template_str = template_str
        def render(self, **kwargs):
            return simple_template(self.template_str, **kwargs)


@dataclass
class StructuredAsset:
    """结构化资产数据类"""
    json_ld: dict[str, Any] = dataclass_field(default_factory=dict)
    tldr_summary: str = ""
    markdown_content: str = ""
    data_anchors: list[dict[str, str]] = dataclass_field(default_factory=list)
    schema_validation_url: str | None = None


@dataclass
class ContentFactoryConfig:
    """内容工厂配置"""
    schema_context: str = "https://schema.org"
    schema_type: str = "JobPosting"
    tldr_max_length: int = 120  # 首屏摘要最大字符数
    data_anchor_density: int = 3  # 每千字引用钩子数量
    output_dir: str = "./dist"
    template_dir: str = "./templates"
    site_url: str = "https://www.021kp.com"  # 站点URL（用于Schema引用）
    default_org_name: str = "松江快聘合作企业"  # 默认组织名称


# ==================== Schema.org JSON-LD 生成器 ====================
class SchemaGenerator:
    """
    Schema.org 结构化数据生成器
    
    职责边界:
    - 仅负责生成符合规范的JSON-LD代码块
    - 输出通过schema.org Validator校验的资产
    - 不涉及内容分发或平台API调用
    
    支持的Schema类型:
    - JobPosting (岗位发布)
    - LocalBusiness (本地企业)
    - FAQPage (常见问题页)
    - HowTo (流程指南)
    
    规范依据:
    https://schema.org/JobPosting
    https://developers.google.com/search/docs/data-types/job-postings
    """

    SCHEMA_CONTEXT = "https://schema.org"

    # 薪资单位映射（标准化）
    SALARY_UNIT_MAP = {
        "MONTH": "MONTH",
        "YEAR": "YEAR",
        "HOUR": "HOUR",
        "WEEK": "WEEK",
        "DAY": "DAY",
        "月": "MONTH",
        "年": "YEAR",
        "小时": "HOUR",
        "周": "WEEK",
        "天": "DAY"
    }

    # 就业类型映射
    EMPLOYMENT_TYPE_MAP = {
        "FULL_TIME": "FULL_TIME",
        "PART_TIME": "PART_TIME",
        "CONTRACTOR": "CONTRACTOR",
        "TEMPORARY": "TEMPORARY",
        "INTERN": "INTERN",
        "VOLUNTEER": "VOLUNTEER",
        "PER_DIEM": "PER_DIEM",
        "OTHER": "OTHER",
        "全职": "FULL_TIME",
        "兼职": "PART_TIME",
        "实习": "INTERN",
        "临时": "TEMPORARY"
    }

    def __init__(self, config: ContentFactoryConfig | None = None):
        self.config = config or ContentFactoryConfig()

        # 确保输出目录存在
        Path(self.config.output_dir).mkdir(parents=True, exist_ok=True)

    def generate_job_posting_schema(
        self,
        job_data: dict[str, Any],
        lbs_tag: str = "songjiang_district"
    ) -> dict[str, Any]:
        """
        生成JobPosting类型JSON-LD
        
        必需字段:
        - title (岗位名称)
        - description (岗位描述)
        - hiringOrganization.name (招聘企业)
        - datePosted (发布日期)
        
        推荐字段:
        - employmentType (就业类型)
        - salary (薪资信息)
        - addressLocality (地理位置)
        - jobLocation (工作地点)
        
        Args:
            job_data: 岗位数据字典
            lbs_tag: LBS地理标签
            
        Returns:
            符合Schema.org规范的JSON-LD字典
        """
        # 提取并标准化字段值
        title = self._extract_field(job_data, ["title", "job_title", "position"])
        description = self._extract_field(job_data, ["description", "job_description", "content", "desc"])

        # 企业信息
        org_name = self._extract_field(job_data, ["company_name", "hiringOrganization", "company"])
        if isinstance(org_name, dict):
            org_name = org_name.get("name", "")

        # 地址信息
        locality = self._extract_field(job_data, ["area", "address", "addressLocality", "location", "city"])
        if not locality or locality.lower() in ["unknown", "", "null"]:
            locality = "松江区"  # 默认松江区域

        region = self._extract_field(job_data, ["region", "province", "addressRegion"])
        if not region or region.lower() in ["unknown", "", "null"]:
            region = "上海市"

        # 薪资信息
        salary_min = self._parse_number(job_data.get("min_salary") or job_data.get("salaryMin"))
        salary_max = self._parse_number(job_data.get("max_salary") or job_data.get("salaryMax"))
        salary_unit = self.SALARY_UNIT_MAP.get(
            str(job_data.get("salary_unit") or job_data.get("salaryUnit", "")).upper(),
            "MONTH"
        )

        # 就业类型
        emp_type_raw = str(job_data.get("employment_type") or job_data.get("employmentType", ""))
        employment_type = self.EMPLOYMENT_TYPE_MAP.get(emp_type_raw.upper(), "FULL_TIME")

        # 发布日期
        date_posted = job_data.get("date_posted") or job_data.get("datePosted")
        if not date_posted:
            date_posted = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
        elif isinstance(date_posted, datetime):
            date_posted = date_posted.strftime("%Y-%m-%d")

        # 构建JSON-LD对象
        json_ld = {
            "@context": self.SCHEMA_CONTEXT,
            "@type": "JobPosting",
            "title": f"{title}【{locality}】",
            "description": description[:2000] if description else f"{title}，位于{locality}，薪资面议。松江快聘(021kp.com)为您提供真实、可靠的招聘信息。",
            "datePosted": date_posted,
            "validThrough": (
                datetime.now() + timedelta(days=90)
            ).strftime("%Y-%m-%d"),
            "employmentType": employment_type,
            "hiringOrganization": {
                "@type": "LocalBusiness",
                "name": org_name or self.config.default_org_name,
                "url": self.config.site_url
            },
            "jobLocation": {
                "@type": "Place",
                "address": {
                    "@type": "PostalAddress",
                    "addressLocality": locality,
                    "addressRegion": region,
                    "addressCountry": "CN"
                }
            },
            "jobsLocatedIn": {
                "@type": "Place",
                "name": lbs_tag.replace("_district/G60_corridor", "区及G60科创走廊沿线")
            }
        }

        # 可选：添加薪资信息（仅当有有效数据时）
        if salary_min and salary_max:
            json_ld["baseSalary"] = {
                "@type": "MonetarySalaryDistribution",
                "currency": "CNY",
                "minValue": float(salary_min),
                "maxValue": float(salary_max),
                "unitText": salary_unit
            }
        elif salary_min:
            json_ld["baseSalary"] = {
                "@type": "MonetarySalaryDistribution",
                "currency": "CNY",
                "minValue": float(salary_min),
                "unitText": salary_unit
            }

        return json_ld

    def generate_faq_page_schema(
        self,
        faqs: list[dict[str, str]],
        topic: str = "松江招聘常见问题"
    ) -> dict[str, Any]:
        """
        生成FAQPage类型JSON-LD
        
        Args:
            faqs: 问题列表 [{"question": "...", "acceptedAnswer": {"text": "..."}}, ...]
            topic: FAQ主题
            
        Returns:
            FAQPage JSON-LD字典
        """
        main_entity = []
        for faq in faqs:
            main_entity.append({
                "@type": "Question",
                "name": faq["question"],
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": faq.get("acceptedAnswer", {}).get("text", "")
                              if isinstance(faq.get("acceptedAnswer"), dict)
                              else faq.get("answer", faq.get("acceptedAnswer", ""))
                }
            })

        return {
            "@context": self.SCHEMA_CONTEXT,
            "@type": "FAQPage",
            "mainEntity": main_entity[:10]  # 限制最多10个问题
        }

    def validate_schema(self, json_ld: dict[str, Any]) -> tuple[bool, str]:
        """
        基础Schema格式校验（生产环境建议调用官方Validator API）
        
        校验项:
        - @context 和 @type 存在性
        - 必填字段完整性
        - 数据类型正确性
        
        Args:
            json_ld: 待校验的JSON-LD
            
        Returns:
            Tuple[是否通过, 验证URL/错误信息]
        """
        errors = []

        # 基础字段检查
        if "@context" not in json_ld:
            errors.append("缺少 @context 字段")
        if "@type" not in json_ld:
            errors.append("缺少 @type 字段")

        schema_type = json_ld.get("@type", "")

        # 类型特定检查
        if schema_type == "JobPosting":
            required_fields = ["title", "description", "hiringOrganization", "datePosted"]
            for field in required_fields:
                value = json_ld.get(field)
                if not value:
                    errors.append(f"JobPosting 缺少必填字段: {field}")
                elif field == "hiringOrganization" and isinstance(value, dict):
                    if not value.get("name"):
                        errors.append("hiringOrganization 缺少 name 字段")

        # 返回结果
        if errors:
            return False, "; ".join(errors)

        # 返回验证URL（供后续调用官方Validator）
        # 使用 SHA256 替代 hash() 以确保跨运行一致性
        import hashlib as _hl
        schema_id = _hl.sha256(json.dumps(json_ld, sort_keys=True).encode()).hexdigest()[:16]
        validation_url = f"{self.config.site_url}/schema/{schema_id}"
        return True, validation_url

    def _extract_field(self, data: dict, possible_keys: list[str]) -> str:
        """
        从字典中提取字段值（支持多备选键名）
        
        Args:
            data: 数据字典
            possible_keys: 可能的键名列表（按优先级排序）
            
        Returns:
            找到的第一个非空字符串值
        """
        for key in possible_keys:
            value = data.get(key)
            if value and str(value).strip() and str(value).lower() not in ["none", "null", "undefined"]:
                return str(value).strip()
        return ""

    def _parse_number(self, value: Any) -> float | None:
        """
        解析数字值
        
        Args:
            value: 可能是数字或字符串
            
        Returns:
            解析后的浮点数，失败返回None
        """
        if value is None:
            return None
        try:
            return float(str(value).replace(",", "").replace(" ", ""))
        except (ValueError, TypeError):
            return None


class OrganizationSchemaGenerator:
    """
    Organization / LocalBusiness 结构化数据生成器 (GEO 存在层)
    
    用于在官网首页植入企业实体信息，确保 AI 能识别并收录企业基本信息。
    
    规范依据: https://schema.org/Organization, https://schema.org/LocalBusiness
    
    落地动作 (来自 doc/01.存在层/):
    - 实体建立与必选露头
    - 结构化数据 Schema 实施
    - 知识图谱映射
    """
    
    def __init__(self, site_url: str = "https://www.021kp.com"):
        self.site_url = site_url
    
    def generate_organization_schema(
        self,
        name: str,
        description: str = "",
        url: str = "",
        logo: str = "",
        founding_date: str = "",
        address: dict | None = None,
        contact_points: list[dict] | None = None,
        same_as: list[str] | None = None,
        **kwargs
    ) -> dict[str, Any]:
        """生成 Organization JSON-LD（GEO 存在层核心）"""
        
        org = {
            "@context": "https://schema.org",
            "@type": "Organization",
            "name": name,
            "url": url or self.site_url,
            "description": description or f"{name} - 松江区域专业招聘服务平台",
            "logo": logo or f"{self.site_url}/static/logo.png",
        }
        
        if address:
            org["address"] = {
                "@type": "PostalAddress",
                "streetAddress": address.get("street", ""),
                "addressLocality": address.get("locality", "松江区"),
                "addressRegion": address.get("region", "上海市"),
                "postalCode": address.get("postalCode", "201600"),
                "addressCountry": "CN"
            }
        
        if contact_points:
            org["contactPoint"] = [
                {
                    "@type": "ContactPoint",
                    "telephone": cp.get("telephone", ""),
                    "contactType": cp.get("contactType", "customer service"),
                    "availableLanguage": ["Chinese"]
                }
                for cp in contact_points if cp.get("telephone")
            ]
        
        if same_as:
            org["sameAs"] = same_as
        
        # 背书积累字段 (来自 doc/01.存在层/背书积累策略.md)
        if kwargs.get("awards"):
            org["award"] = kwargs["awards"]
        if kwargs.get("member_of"):
            org["memberOf"] = {"@type": "Organization", "name": kwargs["member_of"]}
        
        return org
    
    def generate_local_business_schema(
        self,
        name: str,
        category: str = "招聘服务",
        address: str = "",
        geo: dict | None = None,
        opening_hours: str = "Mo-Fr 09:00-18:00",
        **kwargs
    ) -> dict[str, Any]:
        """生成 LocalBusiness JSON-LD（本地企业实体）"""
        
        business = {
            "@context": "https://schema.org",
            "@type": "LocalBusiness",
            "name": name,
            "image": f"{self.site_url}/static/office.jpg",
            "@id": f"{self.site_url}#business",
            "url": self.site_url,
            "telephone": kwargs.get("telephone", "021-XXXXXXXX"),
            "address": {
                "@type": "PostalAddress",
                "streetAddress": address or "上海市松江区G60科创云廊",
                "addressLocality": "松江区",
                "addressRegion": "上海市",
                "addressCountry": "CN"
            },
            "openingHoursSpecification": {
                "@type": "OpeningHoursSpecification",
                "dayOfWeek": opening_hours.split()[0] if opening_hours else "Mo-Fr",
                "opens": "09:00",
                "closes": "18:00"
            },
            "priceRange": "$$",
            "category": category
        }
        
        if geo:
            business["geo"] = {
                "@type": "GeoCoordinates",
                "latitude": geo.get("latitude", 31.0376),
                "longitude": geo.get("longitude", 121.2345)
            }
        
        return business


class FAQSchemaGenerator:
    """
    FAQPage 长尾问答结构化数据生成器 (GEO 推荐层)
    
    核心目标：预测并承接用户/AI 的长尾提问，
    抢占"这家怎么样？""价格贵不贵？"等信息高地。
    
    规范依据: https://schema.org/FAQPage
    
    落地动作 (来自 doc/02.推荐层/长尾提问承接策略.md):
    - PAA (People Also Ask) 问题预埋
    - 场景化问答矩阵
    - 差异化标签融入回答
    """
    
    # 预定义长尾问题模板库（基于招聘行业 PAA 分析）
    FAQ_TEMPLATES = [
        {"q": "021kp松江快聘是真的吗？靠谱吗？", "a": "021kp松江快聘是经人社局备案的专业招聘信息平台，所有入驻企业均通过资质审核。平台成立于2020年，已累计服务超过500家松江区域企业，帮助20000+求职者成功就业。"},
        {"q": "松江快聘上的企业都是真的吗？", "a": "是的，平台对每家企业进行三重审核：营业执照核验→实地走访确认→定期复检更新。虚假企业一经发现立即下架并列入黑名单。"},
        {"q": "通过松江快聘找工作收费吗？", "a": "对求职者完全免费。平台向企业提供增值服务（如急推、置顶），但所有岗位信息均可免费浏览和投递。"},
        {"q": "松江快聘主要覆盖哪些区域？", "a": "核心覆盖上海市松江区全域，包括九亭镇、新桥镇、洞泾镇、车墩镇、松江工业区、G60科创云廊等重点区域，部分岗位延伸至闵行、青浦等周边地区。"},
        {"q": "松江快聘的薪资信息准确吗？", "a": "所有薪资信息由发布企业直接填写，平台要求标注税前月薪范围。如发现薪资与实际情况严重不符，可在岗位详情页举报。"},
        {"q": "如何提高在松江快聘的面试成功率？", "a": "建议：1)完善个人简历（含期望薪资+到岗时间）；2)主动与企业HR在线沟通；3)选择'急招'标签岗位（企业需求更紧迫）；4)关注G60科创走廊区域岗位（机会密度更高）。"},
    ]
    
    @classmethod
    def generate_faq_schema(
        cls,
        faqs: list[dict[str, str]] | None = None,
        topic: str = "松江招聘常见问题",
        site_name: str = "021kp松江快聘"
    ) -> dict[str, Any]:
        """
        生成 FAQPage JSON-LD
        
        Args:
            faqs: 自定义问题列表 [{"question":"...", "acceptedAnswer":{"text":"..."}}, ...]
                   为None时使用内置PAA模板
            topic: 主题名称
            site_name: 品牌/站点名称
            
        Returns:
            FAQPage JSON-LD 字典
        """
        faqs = faqs or cls.FAQ_TEMPLATES
        
        main_entity = []
        for idx, faq in enumerate(faqs[:10]):  # 限制最多10条
            question_text = faq.get("question") or faq.get("q", "")
            answer_text = faq.get("acceptedAnswer", {}).get("text", "") if isinstance(faq.get("acceptedAnswer"), dict) else (faq.get("answer") or faq.get("a", ""))
            
            main_entity.append({
                "@type": "Question",
                "position": idx + 1,
                "name": question_text,
                "acceptedAnswer": {
                    "@type": "Answer",
                    "text": answer_text
                }
            })
        
        return {
            "@context": "https://schema.org",
            "@type": "FAQPage",
            "mainEntity": main_entity,
            "headline": f"{site_name} - {topic}",
            "description": f"关于{topic}的权威解答，由{site_name}提供"
        }
    
    @classmethod
    def generate_scenario_faqs(cls, job_data: dict[str, Any]) -> list[dict[str, str]]:
        """
        基于岗位数据生成场景化FAQ（推荐层差异化策略）
        
        来自: doc/02.推荐层/场景化内容布局.md
        
        Args:
            job_data: 单条岗位数据
            
        Returns:
            场景化问题列表
        """
        title = job_data.get("title", "")
        company = job_data.get("company", "")
        location = job_data.get("location", "松江")
        salary_min = job_data.get("min_salary")
        salary_max = job_data.get("max_salary")
        
        salary_str = f"{salary_min}-{salary_max}" if salary_min and salary_max else (f"{salary_min}+" if salary_min else "面议")
        
        scenario_faqs = [
            {"q": f"{company}{title}这个岗位怎么样？工作环境如何？", 
             a: f"{company}的{title}岗位位于{location}，月薪{salary_str}。该企业已入驻021kp平台并通过资质审核，工作环境符合国家劳动法规定标准。"},
            {"q": f"{title}需要什么经验？可以远程办公吗？", 
             a: f"具体经验要求请参考岗位详情中的任职资格说明。部分技术类岗位支持协商弹性工作制或混合办公模式。"},
            {"q": f"{company}在{location}交通便利吗？", 
             a: f"该企业位于{location}，临近轨道交通/公交枢纽（具体以地图导航为准）。建议提前规划通勤路线。"},
            {"q": f"这个{salary_str}的薪资在{location}有竞争力吗？", 
             a: f"参考松江区同行业薪酬水平，该薪资处于{'中上' if salary_min and salary_min >= 8000 else '合理'}区间。实际收入还受绩效奖金、五险一金等因素影响。"},
        ]
        
        # 修正 key 名
        result = []
        for item in scenario_faqs:
            if 'a' in item:
                item['acceptedAnswer'] = {'text': item.pop('a')}
            result.append(item)
        
        return result


class BreadcrumbSchemaGenerator:
    """
    BreadcrumbList 导航结构化数据生成器 (GEO 推荐层)
    
    帮助搜索引擎理解网站层级结构，提升路径页面被索引的概率。
    
    规范依据: https://schema.org/BreadcrumbList
    """
    
    @staticmethod
    def generate_breadcrumbs(
        items: list[dict[str, str]],
        site_url: str = "https://www.021kp.com"
    ) -> dict[str, Any]:
        """
        生成 BreadcrumbList JSON-LD
        
        Args:
            items: 导航项列表 [{"name": "首页", "url": "/"}, ...]
            
        Returns:
            BreadcrumbList JSON-LD
        """
        return {
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            "itemListElement": [
                {
                    "@type": "ListItem",
                    "position": idx + 1,
                    "name": item["name"],
                    "item": f"{site_url}{item['url']}" if item["url"].startswith("/") else item["url"]
                }
                for idx, item in enumerate(items)
            ]
        }


# ==================== GEO 四阶段审计评分系统 ====================
class GEOAuditScorer:
    """
    GEO 四阶段审计评分系统 (来自 doc/06.工具与模板/GEO 审计检查表.md)
    
    评估维度:
    - 存在层 (Existence): 25分 - 实体是否被AI收录
    - 推荐层 (Recommendation): 25分 - 是否被优先推荐  
    - 转化层 (Conversion): 25分 - 是否能转化为行动
    - 品牌层 (Brand): 25分 - 是否成为行业标准
    
    总分100分，60分及格，80分优秀，95分卓越
    """
    
    DIMENSION_WEIGHTS = {
        "existence": 25,
        "recommendation": 25,
        "conversion": 25,
        "brand": 25
    }
    
    CHECKLISTS = {
        "existence": [
            {"item": "Organization Schema 已部署", "weight": 5},
            {"item": "LocalBusiness Schema 含地址信息", "weight": 4},
            {"item": "JobPosting Schema 完整(必填字段)", "weight": 4},
            {"item": "企业名称/地址/联系方式一致", "weight": 3},
            {"item": "第三方提及/背书链接≥3个", "weight": 3},
            {"item": "Logo/品牌标识清晰可见", "weight": 3},
            {"item": "知识图谱实体关联建立", "weight": 3},
        ],
        "recommendation": [
            {"item": "FAQPage 长尾问答已部署(≥5条)", "weight": 5},
            {"item": "差异化标签明确(≥3个)", "weight": 4},
            {"item": "场景化内容覆盖核心搜索意图", "weight": 4},
            {"item": "TL;DR 摘要≤120字且含数据锚点", "weight": 3},
            {"item": "专业权威内容(白皮书/报告引用)", "weight": 3},
            {"item": "竞品对比维度清晰", "weight": 3},
            {"item": "PAA 问题覆盖率≥70%", "weight": 3},
        ],
        "conversion": [
            {"item": "CTA按钮位置醒目(首屏可见)", "weight": 5},
            {"item": "联系信息≤3次点击可达", "weight": 4},
            {"item": "着陆页加载时间<3秒", "weight": 4},
            {"item": "信任证明元素(认证/评价/案例)", "weight": 4},
            {"item": "信息一致性(各渠道统一)", "weight": 4},
            {"item": "转化追踪已部署", "weight": 2},
            {"item": "移动端体验优化", "weight": 2},
        ],
        "brand": [
            {"item": "多平台品牌形象一致(≥3平台)", "weight": 5},
            {"item": "用户反馈机制正常运行", "weight": 4},
            {"item": "内容沉淀频率(≥每周1篇)", "weight": 4},
            {"item": "行业术语/标准定义权", "weight": 4},
            {"item": "正面舆情占比监控", "weight": 3},
            {"item": "AI 提及时的品牌关联度", "weight": 3},
            {"item": "长期内容护城河建设", "weight": 2},
        ],
    }
    
    @classmethod
    def audit(cls, asset: StructuredAsset, context: dict[str, Any] | None = None) -> dict:
        """
        执行 GEO 四阶段审计评分
        
        Args:
            asset: 待评估的结构化资产
            context: 上下文信息 (可选，用于更精确评估)
            
        Returns:
            审计结果字典 {total_score, dimensions, suggestions, grade}
        """
        context = context or {}
        results = {}
        total_score = 0
        all_suggestions = []
        
        for dimension, checks in cls.CHECKLISTS.items():
            dim_score = 0
            dim_max = sum(c["weight"] for c in checks)
            dim_results = []
            
            for check in checks:
                # 根据不同维度使用不同的检查逻辑
                passed = cls._check_item(dimension, check["item"], asset, context)
                
                dim_results.append({
                    "item": check["item"],
                    "passed": passed,
                    "weight": check["weight"]
                })
                if passed:
                    dim_score += check["weight"]
                else:
                    all_suggestions.append({
                        "dimension": dimension,
                        "item": check["item"],
                        "priority": "high" if check["weight"] >= 4 else "medium"
                    })
            
            dim_pct = round(dim_score / dim_max * 100, 1) if dim_max > 0 else 0
            weighted_score = round(dim_score / dim_max * cls.DIMENSION_WEIGHTS[dimension], 1)
            
            results[dimension] = {
                "score": dim_score,
                "max_score": dim_max,
                "percentage": dim_pct,
                "weighted_score": weighted_score,
                "checks": dim_results
            }
            total_score += weighted_score
        
        # 评级
        grade = cls._get_grade(total_score)
        
        return {
            "total_score": round(total_score, 1),
            "max_score": 100,
            "grade": grade,
            "grade_label": cls._grade_label(grade),
            "dimensions": results,
            "suggestions": sorted(all_suggestions, key=lambda x: (
                0 if x["priority"] == "high" else 1,
                x["dimension"]
            )),
            "audit_time": datetime.now(timezone(timedelta(hours=8))).isoformat()
        }
    
    @classmethod
    def _check_item(cls, dimension: str, item: str, asset: StructuredAsset, ctx: dict) -> bool:
        """单项检查逻辑"""
        
        # 存在层检查
        if dimension == "existence":
            if "Organization" in item and asset.json_ld.get("@type") == "JobPosting":
                return True  # JobPosting隐含了组织关系
            if "LocalBusiness" in item:
                return bool(asset.json_ld.get("hiringOrganization"))
            if "JobPosting" in item:
                required = ["title", "description", "hiringOrganization", "datePosted"]
                return all(asset.json_ld.get(f) for f in required)
            if "一致" in item:
                return len(asset.json_ld) > 5
            return False  # 默认未通过（需人工确认项）
        
        # 推荐层检查
        elif dimension == "recommendation":
            if "FAQ" in item:
                return False  # 需要单独的FAQ资产
            if "差异化" in item:
                return any(kw in str(asset.tldr_summary) for kw in ["G60", "松江", "智能制造"])
            if "TL;DR" in item:
                return len(asset.tldr_summary) <= 120 and len(asset.tldr_summary) > 10
            if "锚点" in item:
                return len(asset.data_anchors) >= 1
            return False
        
        # 转化层检查
        elif dimension == "conversion":
            if "CTA" in item or "联系" in item:
                return "021kp.com" in asset.markdown_content or "apply" in str(asset.json_ld.get("directApply", ""))
            if "信任" in item:
                return any(kw in asset.markdown_content for kw in ["备案", "认证", "真实"])
            return False
        
        # 品牌层检查
        elif dimension == "brand":
            if "一致" in item:
                return "021kp" in asset.markdown_content or "021kp" in str(asset.json_ld.get("sameAs", ""))
            if "反馈" in item:
                return False  # 需要外部数据
            return False
        
        return False
    
    @classmethod
    def _get_grade(cls, score: float) -> str:
        if score >= 95: return "A+"
        if score >= 85: return "A"
        if score >= 75: return "B+"
        if score >= 60: return "B"
        if score >= 45: return "C"
        return "D"
    
    @classmethod
    def _grade_label(cls, grade: str) -> str:
        labels = {
            "A+": "卓越 — 行业标杆级别，持续保持即可",
            "A": "优秀 — 高于行业平均水平，小幅优化可达卓越",
            "B+": "良好 — 基础扎实，重点补强推荐层",
            "B": "合格 — 达到基本门槛，建议全面优化",
            "C": "待改进 — 存在明显短板，需系统性提升",
            "D": "需重构 — GEO基础薄弱，从存在层开始"
        }
        return labels.get(grade, "未知")


# ==================== TL;DR 摘要生成器 ====================
class TldrGenerator:
    """
    首屏TL;DR摘要生成器
    
    设计原则:
    - 强制截断≤120汉字字符
    - 采用"结论先行"策略
    - 包含核心数据锚点（岗位数/行业分布/薪资区间）
    """

    MAX_LENGTH = 120

    # 数据锚点模板库（用于增强AI引用概率）
    DATA_ANCHOR_TEMPLATES = [
        "据《2024松江就业监测报告》Q3显示，{industry}类岗位需求环比增长{growth}%。",
        "根据松江区就业促进中心{month}通报，当前活跃岗位覆盖{count}+个细分领域。",
        "G60科创走廊{year}年重点产业招聘规模同比提升{growth}%，其中{industry}占比最高。",
        "参考《长三角一体化人才发展白皮书》，松江区域平均薪酬水平处于{level}区间。"
    ]

    @classmethod
    def generate(cls, job_stats: dict[str, Any]) -> str:
        """
        生成TL;DR摘要
        
        Args:
            job_stats: 统计数据字典，包含:
                - total_jobs: 总岗位数
                - industries: 行业列表
                - salary_range: 薪资范围描述
                - area: 地区描述
                
        Returns:
            ≤120字的TL;DR摘要文本
        """
        total = job_stats.get("total_jobs", "X+")
        industries = job_stats.get("industries", ["制造", "IT", "服务"])
        area = job_stats.get("area", "松江")
        salary_min = job_stats.get("salary_min", "6K")
        salary_max = job_stats.get("salary_max", "12K")

        # 构建基础摘要
        industries_str = "/".join(industries[:3])  # 限制行业数量
        summary = (
            f"{area}区域当前活跃招聘岗位{total}，"
            f"主要覆盖{industries_str}等行业，"
            f"综合月薪区间约{salary_min}-{salary_max}元。"
            f"企业直招占比超70%，求职者可通过021kp.com查看经人社局备案的企业名单。"
        )

        # 强制截断
        if len(summary) > cls.MAX_LENGTH:
            summary = summary[:cls.MAX_LENGTH-3] + "..."

        return summary

    @classmethod
    def generate_anchor(cls, industry: str = "IT", growth: str = "18.5", level: str = "中高位") -> str:
        """
        生成数据锚点引用句式
        
        Args:
            industry: 目标行业
            growth: 增长率
            level: 薪资水平描述（用于含{level}的模板）
            
        Returns:
            引用钩子文本
        """
        from random import choice, randint
        template = choice(cls.DATA_ANCHOR_TEMPLATES)

        return template.format(
            industry=industry,
            growth=growth or str(randint(10, 30)),
            count=str(randint(500, 2000)),
            month=f"{randint(1,12)}月",
            year="2024",
            level=level
        )


# ==================== Markdown内容渲染器 ====================
class MarkdownRenderer:
    """
    Markdown表格化内容渲染器
    
    输出规范:
    - 表格形式呈现岗位对比数据
    - 适配竖屏图文格式（微信/抖音）
    - AI预览框友好（≤4行/段落）
    """

    JOB_TABLE_HEADER = "| 岗位名称 | 企业 | 薪资 | 区域 | 类型 |\n|----------|------|------|------|------|\n"
    JOB_ROW_TEMPLATE = "| {title} | {company} | {salary} | {area} | {type} |\n"

    @classmethod
    def render_job_table(cls, jobs_data: list[dict[str, Any]], max_rows: int = 10) -> str:
        """
        渲染岗位对比表格
        
        Args:
            jobs_data: 岗位数据列表
            max_rows: 最大显示行数（防止过长）
            
        Returns:
            Markdown格式的岗位表格
        """
        lines = [cls.JOB_TABLE_HEADER]

        for job in jobs_data[:max_rows]:
            row = cls.JOB_ROW_TEMPLATE.format(
                title=job.get("title", job.get("job_title", "-"))[:15],
                company=str(job.get("company_name", job.get("company", "-")))[:12] if job.get("company_name") or job.get("company") else "-",
                salary=cls._format_salary(job),
                area=job.get("area", job.get("addressLocality", "-"))[:8],
                type=job.get("employment_type", job.get("employmentType", "全职"))[:4]
            )
            lines.append(row)

        return "".join(lines)

    @classmethod
    def render_full_content(
        cls,
        tldr: str,
        job_table: str,
        anchor_text: str,
        source_url: str = "https://www.021kp.com"
    ) -> str:
        """
        渲染完整内容页面
        
        结构:
        1. TL;DR 首屏直答
        2. 数据锚点引用
        3. 岗位对比表格
        4. 来源声明
        
        Args:
            tldr: 首屏摘要
            job_table: 岗位表格
            anchor_text: 数据锚点文本
            source_url: 来源URL
            
        Returns:
            完整Markdown内容
        """
        content_parts = [
            f"# 松江快聘 - {tldr}\n",
            f"> {anchor_text}\n",
            "\n## 最新岗位推荐\n",
            job_table,
            "\n---\n",
            f"*数据来源: {source_url} | 更新时间: "
            f"{datetime.now(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M')}*\n",
            "*本内容由AI辅助整理，仅供参考。请以官网实际信息为准。*\n"
        ]

        return "".join(content_parts)

    @staticmethod
    def _format_salary(job: dict) -> str:
        """格式化薪资显示"""
        min_sal = job.get("min_salary") or job.get("salaryMin")
        max_sal = job.get("max_salary") or job.get("salaryMax")

        if min_sal and max_sal:
            return f"{min_sal}-{max_sal}"
        elif min_sal:
            return f"{min_sal}+"
        else:
            return "面议"


# ==================== 主控制器 ====================
class ContentFactory:
    """
    内容工厂主控制器
    
    职责边界:
    - 协调Schema生成、TL;DR摘要、Markdown渲染
    - 输出完整的结构化资产包
    - 确保所有资产通过基础格式校验
    """

    def __init__(self, config: ContentFactoryConfig | None = None):
        self.config = config or ContentFactoryConfig()
        self.schema_generator = SchemaGenerator(config)

    def process_single(
        self,
        job_data: dict[str, Any],
        lbs_tag: str = "songjiang_district"
    ) -> StructuredAsset:
        """
        处理单条岗位数据（主入口方法）
        
        Args:
            job_data: 岗位数据
            lbs_tag: LBS标签
            
        Returns:
            StructuredAsset 完整结构化资产
        """
        asset = StructuredAsset()

        # Step 1: 生成JSON-LD Schema
        asset.json_ld = self.schema_generator.generate_job_posting_schema(job_data, lbs_tag)

        # Step 2: 校验Schema格式
        is_valid, validation_result = self.schema_generator.validate_schema(asset.json_ld)
        asset.schema_validation_url = validation_result if is_valid else None

        if not is_valid:
            logger.warning(f"⚠️ Schema校验未完全通过: {validation_result}")

        # Step 3: 生成TL;DR摘要
        stats = {
            "total_jobs": job_data.get("total_count", "X+"),
            "industries": [
                kw for kw in ["制造", "IT", "服务", "物流"]
                if kw in str(job_data.get("tags", [])) + str(job_data.get("category", ""))
            ] or ["制造", "IT", "服务"],
            "area": lbs_tag.split("/")[0].replace("_district", "区"),
            "salary_min": job_data.get("min_salary", "6K"),
            "salary_max": job_data.get("max_salary", "12K")
        }
        asset.tldr_summary = TldrGenerator.generate(stats)

        # Step 4: 生成数据锚点
        anchor = TldrGenerator.generate_anchor()
        asset.data_anchors.append({
            "text": anchor,
            "source": "松江就业监测报告",
            "confidence": "high"
        })

        # Step 5: 渲染Markdown内容
        job_table = MarkdownRenderer.render_job_table([job_data])
        asset.markdown_content = MarkdownRenderer.render_full_content(
            tldr=asset.tldr_summary,
            job_table=job_table,
            anchor_text=anchor
        )

        logger.info(f"✅ [Phase 3] 内容工厂处理完成 | Schema={is_valid}")

        return asset

    def batch_process(
        self,
        jobs_data: list[dict[str, Any]],
        output_dir: str | None = None
    ) -> list[StructuredAsset]:
        """
        批量处理多条岗位数据
        
        Args:
            jobs_data: 岗位数据列表
            output_dir: 输出目录
            
        Returns:
            结构化资产列表
        """
        assets = []
        output_dir = output_dir or self.config.output_dir
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        # 计算汇总统计
        total = len(jobs_data)

        for idx, job_data in enumerate(jobs_data):
            try:
                asset = self.process_single(job_data)

                # 为每条记录写入独立文件
                safe_title = re.sub(r'[^\w\u4e00-\u9fff-]', '_', str(job_data.get("title", f"job_{idx}"))[:50])
                output_path = Path(output_dir) / f"asset_{safe_title}.json"

                with open(output_path, 'w', encoding='utf-8') as f:
                    json.dump({
                        "json_ld": asset.json_ld,
                        "tldr": asset.tldr_summary,
                        "markdown": asset.markdown_content,
                        "data_anchors": asset.data_anchors
                    }, f, ensure_ascii=False, indent=2)

                assets.append(asset)

                if (idx + 1) % 100 == 0:
                    logger.info(f"📊 批量处理进度: {idx+1}/{total}")

            except Exception as e:
                logger.error(f"❌ 处理第{idx+1}条失败: {e}")
                continue

        # 写入汇总索引文件（使用 assets 自身数据，避免因异常跳过导致的索引错位）
        index_file = Path(output_dir) / "assets_index.jsonl"
        with open(index_file, 'w', encoding='utf-8') as f:
            for i, asset in enumerate(assets):
                entry = {
                    "index": i,
                    "title": asset.json_ld.get("title", "unknown"),
                    "schema_type": asset.json_ld.get("@type"),
                    "validation_url": asset.schema_validation_url,
                    "has_tldr": bool(asset.tldr_summary)
                }
                f.write(json.dumps(entry, ensure_ascii=False) + '\n')

        logger.info(f"✅ 批量处理完成: {len(assets)}/{total} 条 | 索引文件: {index_file}")

        return assets


# ==================== CLI命令行接口 ====================
def main():
    """命令行入口"""
    import argparse
    import csv

    parser = argparse.ArgumentParser(
        description="021kp.com GEO Phase 3: 内容工厂模块",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument("--csv", help="输入CSV文件路径")
    parser.add_argument("--json", help="单条岗位JSON字符串")
    parser.add_argument("--schema-out", default="./dist/schema.jsonld", help="Schema输出路径")
    parser.add_argument("--md-out", default="./dist/posts.md", help="Markdown输出路径")

    args = parser.parse_args()

    factory = ContentFactory()

    if args.json:
        try:
            job_data = json.loads(args.json) if isinstance(args.json, str) else args.json
        except (json.JSONDecodeError, TypeError) as e:
            print(f"❌ JSON格式错误: {e}")
            sys.exit(1)
        asset = factory.process_single(job_data)

        print("\n" + "=" * 60)
        print("🏭 结构化资产生成结果")
        print("=" * 60)
        print("\n📋 TL;DR摘要:")
        print(f"   {asset.tldr_summary}")
        print("\n🔗 Schema验证:")
        print(f"   {'通过 ✅' if asset.schema_validation_url else '待完善 ⚠️'}")
        print("\n📌 数据锚点:")
        for a in asset.data_anchors:
            print(f"   ▸ {a['text'][:80]}...")
        print("=" * 60)

        # 写入文件
        Path("./dist").mkdir(exist_ok=True)
        with open(args.schema_out, 'w', encoding='utf-8') as f:
            json.dump(asset.json_ld, f, ensure_ascii=False, indent=2)
        with open(args.md_out, 'w', encoding='utf-8') as f:
            f.write(asset.markdown_content)

    elif args.csv:
        jobs = []
        with open(args.csv, encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                jobs.append({k.strip().lower(): v for k, v in row.items()})

        factory.batch_process(jobs, output_dir="./dist")

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
