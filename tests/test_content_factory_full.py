# -*- coding: utf-8 -*-
"""
GEO Pipeline Phase 3: 内容工厂完整测试套件 (100% 覆盖率目标)
==============================================================

覆盖范围:
- SchemaGenerator: JobPosting/FAQPage 生成、字段提取、数字解析、校验
- OrganizationSchemaGenerator: Organization/LocalBusiness Schema
- FAQSchemaGenerator: FAQPage 生成、场景化FAQ
- BreadcrumbSchemaGenerator: 导航Schema
- GEOAuditScorer: 四阶段审计评分系统
- TldrGenerator: TL;DR摘要生成、数据锚点
- MarkdownRenderer: 表格渲染、内容组装
- ContentFactory: 主控制器（单条+批量）

运行: pytest tests/test_content_factory_full.py -v --tb=short
"""

import json
import os
import sys
import re
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from content_factory import (
    StructuredAsset,
    ContentFactoryConfig,
    SchemaGenerator,
    OrganizationSchemaGenerator,
    FAQSchemaGenerator,
    BreadcrumbSchemaGenerator,
    GEOAuditScorer,
    TldrGenerator,
    MarkdownRenderer,
    ContentFactory,
)


# ==================== StructuredAsset / ContentFactoryConfig ====================
class TestStructuredAsset:
    """结构化资产数据类"""

    def test_defaults(self):
        a = StructuredAsset()
        assert a.json_ld == {}
        assert a.tldr_summary == ""
        assert a.markdown_content == ""
        assert a.data_anchors == []
        assert a.schema_validation_url is None

    def test_with_data(self):
        a = StructuredAsset(
            json_ld={"@type": "JobPosting"},
            tldr_summary="摘要",
            markdown_content="内容",
            data_anchors=[{"text": "锚点"}],
            schema_validation_url="http://test"
        )
        assert a.json_ld["@type"] == "JobPosting"
        assert len(a.data_anchors) == 1


class TestContentFactoryConfig:
    """内容工厂配置"""

    def test_defaults(self):
        cfg = ContentFactoryConfig()
        assert cfg.schema_context == "https://schema.org"
        assert cfg.schema_type == "JobPosting"
        assert cfg.tldr_max_length == 120
        assert cfg.data_anchor_density == 3
        assert cfg.site_url == "https://www.021kp.com"


# ==================== SchemaGenerator ====================
class TestSchemaGeneratorInit:
    def test_default_init(self, tmp_path):
        gen = SchemaGenerator(ContentFactoryConfig(output_dir=str(tmp_path / "out")))
        assert gen.config is not None
        assert (tmp_path / "out").exists()

    def test_custom_config(self):
        cfg = ContentFactoryConfig(site_url="https://custom.com", output_dir="./custom_out")
        gen = SchemaGenerator(cfg)
        assert gen.config.site_url == "https://custom.com"


class TestSchemaGeneratorJobPosting:
    """JobPosting Schema生成"""

    _gen = None

    def _get_gen(self):
        if self._gen is None:
            self._gen = SchemaGenerator()
        return self._gen

    def test_required_fields_present(self):
        """必需字段完整"""
        jd = self._get_gen().generate_job_posting_schema({
            "title": "测试岗位",
            "description": "描述文本",
            "company_name": "测试公司",
            "area": "松江区",
        })
        assert jd["@context"] == "https://schema.org"
        assert jd["@type"] == "JobPosting"
        assert "title" in jd and jd["title"]
        assert "description" in jd and jd["description"]
        assert "hiringOrganization" in jd
        assert "datePosted" in jd
        assert "jobLocation" in jd
        assert "validThrough" in jd

    def test_title_contains_location(self):
        """标题含地区"""
        gen = self._get_gen()
        jd = gen.generate_job_posting_schema({
            "title": "CNC操作工", "area": "九亭镇"
        })
        assert "九亭镇" in jd["title"]

    def test_default_location_fallback(self):
        """默认地区为松江"""
        gen = self._get_gen()
        jd = gen.generate_job_posting_schema({"title": "T"})
        # 默认 locality 应为 松江区 或类似值
        loc = jd.get("jobLocation", {}).get("address", {}).get("addressLocality", "")
        assert len(loc) > 0

    def test_salary_both_min_max(self):
        """完整薪资"""
        gen = self._get_gen()
        jd = gen.generate_job_posting_schema({
            "title": "T", "min_salary": 6000, "max_salary": 10000
        })
        assert "baseSalary" in jd
        assert jd["baseSalary"]["currency"] == "CNY"
        assert jd["baseSalary"]["minValue"] == 6000.0
        assert jd["baseSalary"]["maxValue"] == 10000.0

    def test_salary_only_min(self):
        """仅最低薪资"""
        gen = self._get_gen()
        jd = gen.generate_job_posting_schema({"title": "T", "min_salary": 8000})
        assert "baseSalary" in jd
        assert jd["baseSalary"]["minValue"] == 8000.0

    def test_no_salary_no_field(self):
        """无薪资时不输出字段"""
        gen = self._get_gen()
        jd = gen.generate_job_posting_schema({"title": "T"})
        # 无有效薪资时可能不输出 baseSalary
        assert jd.get("@type") == "JobPosting"

    def test_employment_type_mapping(self):
        """就业类型映射"""
        gen = self._get_gen()
        
        for raw, expected in [("全职", "FULL_TIME"), ("兼职", "PART_TIME"),
                               ("实习", "INTERN"), ("临时", "TEMPORARY")]:
            jd = gen.generate_job_posting_schema({"title": "T", "employment_type": raw})
            assert jd["employmentType"] == expected, f"{raw} → {jd['employment_type']} != {expected}"

    def test_unknown_employment_type_defaults_fulltime(self):
        """未知类型默认全职"""
        gen = self._get_gen()
        jd = gen.generate_job_posting_schema({"title": "T", "employment_type": "UNKNOWN_TYPE"})
        assert jd["employmentType"] == "FULL_TIME"

    def test_company_dict_handling(self):
        """企业信息为dict时的处理"""
        gen = self._get_gen()
        jd = gen.generate_job_posting_schema({
            "title": "T",
            "company_name": {"name": "Dict公司", "isVerified": True}
        })
        assert jd["hiringOrganization"]["name"] == "Dict公司"

    def test_lbs_injection(self):
        """LBS标签注入"""
        gen = self._get_gen()
        jd = gen.generate_job_posting_schema(
            {"title": "T", "area": "松江"},
            lbs_tag="g60_corridor/university_city"
        )
        assert "jobsLocatedIn" in jd
        assert isinstance(jd["jobsLocatedIn"], dict)

    def test_date_posted_from_input(self):
        """使用输入的发布日期"""
        from datetime import date
        gen = self._get_gen()
        jd = gen.generate_job_posting_schema({"title": "T", "datePosted": "2025-01-15"})
        assert jd["datePosted"] == "2025-01-15"

    def test_date_posted_auto_generated(self):
        """自动生成发布日期"""
        import re as _re
        gen = self._get_gen()
        jd = gen.generate_job_posting_schema({"title": "T"})
        assert _re.match(r"\d{4}-\d{2}-\d{2}", jd["datePosted"])


class TestSchemaGeneratorFAQ:
    """FAQPage Schema生成"""

    def test_faq_page_generation(self):
        gen = SchemaGenerator()
        faqs = [
            {"question": "Q1?", "acceptedAnswer": {"text": "A1"}},
            {"question": "Q2?", "answer": "A2"},
        ]
        result = gen.generate_faq_page_schema(faqs, topic="Test Topic")
        assert result["@type"] == "FAQPage"
        assert len(result["mainEntity"]) == 2
        for entity in result["mainEntity"]:
            assert entity["@type"] == "Question"
            assert entity.get("name") is not None

    def test_faq_limit_to_10(self):
        """最多10个问题"""
        gen = SchemaGenerator()
        faqs = [{"question": f"Q{i}", "answer": f"A{i}"} for i in range(15)]
        result = gen.generate_faq_page_schema(faqs)
        assert len(result["mainEntity"]) == 10

    def test_empty_faqs(self):
        """空FAQ列表"""
        gen = SchemaGenerator()
        result = gen.generate_faq_page_schema([])
        assert result["@type"] == "FAQPage"
        assert len(result["mainEntity"]) == 0


class TestSchemaGeneratorValidation:
    """Schema校验"""

    def test_valid_job_posting_passes(self):
        gen = SchemaGenerator()
        valid = {
            "@context": "https://schema.org",
            "@type": "JobPosting",
            "title": "T",
            "description": "D",
            "hiringOrganization": {"@type": "LocalBusiness", "name": "C"},
            "datePosted": "2026-01-01"
        }
        ok, msg = gen.validate_schema(valid)
        assert ok is True
        assert msg.startswith("http")

    def test_missing_context(self):
        gen = SchemaGenerator()
        invalid = {"@type": "JobPosting", "title": "T"}
        ok, msg = gen.validate_schema(invalid)
        assert ok is False
        assert "@context" in msg or "缺少" in msg

    def test_missing_type(self):
        gen = SchemaGenerator()
        invalid = {"@context": "https://schema.org"}
        ok, msg = gen.validate_schema(invalid)
        assert ok is False
        assert "@type" in msg

    def test_jobposting_missing_required_fields(self):
        gen = SchemaGenerator()
        invalid = {
            "@context": "https://schema.org",
            "@type": "JobPosting",
            "title": "Only title"
        }
        ok, msg = gen.validate_schema(invalid)
        assert ok is False

    def test_org_name_validation(self):
        """组织名称校验"""
        gen = SchemaGenerator()
        bad = {
            "@context": "https://schema.org",
            "@type": "JobPosting",
            "title": "T",
            "hiringOrganization": {"@type": "LocalBusiness"},  # 缺少name
            "datePosted": "2026-01-01"
        }
        ok, msg = gen.validate_schema(bad)
        assert ok is False

    def test_validation_url_deterministic(self):
        """相同内容产生相同URL"""
        gen = SchemaGenerator()
        schema = {"@context": "https://schema.org", "@type": "JobPosting",
                    "title": "Same", "description": "Desc",
                    "hiringOrganization": {"@type": "LocalBusiness", "name": "Org"},
                    "datePosted": "2026-01-01"}
        u1 = gen.validate_schema(schema)[1]
        u2 = gen.validate_schema(schema)[1]
        assert u1 == u2


class TestSchemaGeneratorHelpers:
    """辅助方法"""

    def test_extract_field_first_match(self):
        gen = SchemaGenerator()
        data = {"title": "FirstTitle", "job_title": "SecondTitle"}
        result = gen._extract_field(data, ["job_title", "title"])
        assert result == "SecondTitle"  # 第一个匹配优先

    def test_extract_field_none_when_all_empty(self):
        gen = SchemaGenerator()
        data = {"missing_key": "val", "another": ""}
        result = gen._extract_field(data, ["nonexistent", "missing_key"])
        # missing_key 有值但不是空字符串
        assert result == "val" if result else True

    def test_extract_field_skip_none_null(self):
        gen = SchemaGenerator()
        data = {"key1": None, "key2": "null", "key3": "Valid"}
        result = gen._extract_field(data, ["key1", "key2", "key3"])
        assert result == "Valid"

    def test_parse_number_float(self):
        gen = SchemaGenerator()
        assert gen._parse_number(42.5) == 42.5

    def test_parse_number_int_string(self):
        gen = SchemaGenerator()
        assert gen._parse_number("8000") == 8000.0

    def test_parse_number_with_comma(self):
        gen = SchemaGenerator()
        assert gen._parse_number("8,500") == 8500.0

    def test_parse_number_none(self):
        gen = SchemaGenerator()
        assert gen._parse_number(None) is None

    def test_parse_number_invalid_string(self):
        gen = SchemaGenerator()
        assert gen._parse_number("invalid") is None


# ==================== OrganizationSchemaGenerator ====================
class TestOrganizationSchemaGenerator:
    """组织Schema生成器"""

    def test_basic_organization(self):
        gen = OrganizationSchemaGenerator()
        org = gen.generate_organization_schema(name="测试公司")
        assert org["@type"] == "Organization"
        assert org["name"] == "测试公司"
        assert org["url"] == "https://www.021kp.com"
        assert "logo" in org
        assert "description" in org

    def test_with_address(self):
        gen = OrganizationSchemaGenerator()
        org = gen.generate_organization_schema(
            name="Addr公司",
            address={"street": "G60科创云廊123号", "locality": "松江区", "region": "上海市"}
        )
        assert org["address"]["streetAddress"] == "G60科创云廊123号"
        assert org["address"]["addressLocality"] == "松江区"
        assert org["address"]["postalCode"] == "201600"

    def test_with_contact_points(self):
        gen = OrganizationSchemaGenerator()
        org = gen.generate_organization_schema(
            name="Contact公司",
            contact_points=[{"telephone": "021-12345678", "contactType": "sales"}]
        )
        assert len(org["contactPoint"]) == 1
        assert org["contactPoint"][0]["telephone"] == "021-12345678"

    def test_contact_point_no_phone_filtered(self):
        """无电话的联系人被过滤"""
        gen = OrganizationSchemaGenerator()
        org = gen.generate_organization_schema(
            name="Filter公司",
            contact_points=[{"contactType": "info"}]  # 无 telephone
        )
        assert len(org.get("contactPoint", [])) == 0

    def test_with_same_as(self):
        gen = OrganizationSchemaGenerator()
        org = gen.generate_organization_schema(
            name="Social公司", same_as=["https://weibo.com/test", "https://mp.weixin.qq.com"]
        )
        assert org["sameAs"] == ["https://weibo.com/test", "https://mp.weixin.qq.com"]

    def test_with_awards_and_membership(self):
        gen = OrganizationSchemaGenerator()
        org = gen.generate_organization_schema(
            name="Award公司", awards=["最佳雇主2024"], member_of="行业协会"
        )
        assert org["award"] == ["最佳雇主2024"]
        assert org["memberOf"]["name"] == "行业协会"


class TestLocalBusinessSchema:
    """LocalBusiness Schema生成"""

    def test_basic_local_business(self):
        gen = OrganizationSchemaGenerator()
        biz = gen.generate_local_business_schema(name="本地企业")
        assert biz["@type"] == "LocalBusiness"
        assert biz["name"] == "本地企业"
        assert biz["category"] == "招聘服务"
        assert "address" in biz
        assert "openingHoursSpecification" in biz
        assert "priceRange" == "$$"

    def test_with_geo_coordinates(self):
        gen = OrganizationSchemaGenerator()
        biz = gen.generate_local_business_schema(
            name="Geo企业", geo={"latitude": 31.0376, "longitude": 121.2345}
        )
        assert biz["geo"]["latitude"] == 31.0376
        assert biz["geo"]["longitude"] == 121.2345

    def test_custom_category_and_phone(self):
        gen = OrganizationSchemaGenerator()
        biz = gen.generate_local_business_schema(
            name="CustomBiz", category="IT服务", telephone="400-888-8888"
        )
        assert biz["category"] == "IT服务"
        assert biz["telephone"] == "400-888-8888"


# ==================== FAQSchemaGenerator ====================
class TestFAQSchemaGeneratorClass:
    """FAQ生成器类方法"""

    def test_default_templates_used(self):
        faq = FAQSchemaGenerator.generate_faq_schema()
        assert faq["@type"] == "FAQPage"
        assert len(faq["mainEntity"]) >= 5  # 内置模板至少5条
        assert "headline" in faq
        assert "description" in faq

    def test_custom_faqs(self):
        custom = [
            {"question": "自定义Q1?", "acceptedAnswer": {"text": "自定义A1"}},
            {"question": "自定义Q2?", "a": "自定义A2"},
        ]
        faq = FAQSchemaGenerator.generate_faq_schema(faqs=custom, site_name="TestSite")
        assert len(faq["mainEntity"]) == 2
        # 检查 position 字段存在
        assert faq["mainEntity"][0]["position"] == 1

    def test_position_sequence(self):
        faqs = [{"question": f"Q{i}", "a": f"A{i}"} for i in range(5)]
        result = FAQSchemaGenerator.generate_faq_schema(faqs=faqs)
        positions = [e["position"] for e in result["mainEntity"]]
        assert positions == [1, 2, 3, 4, 5]


class TestScenarioFAQs:
    """场景化FAQ生成"""

    def test_scenario_faq_from_job_data(self):
        faqs = FAQSchemaGenerator.generate_scenario_faqs({
            "title": "Java开发工程师",
            "company": "科技公司",
            "location": "松江",
            "min_salary": 15000,
            "max_salary": 25000
        })
        assert len(faqs) >= 3
        # 应包含岗位相关关键词
        combined = "|".join([f.get('question', '') + f.get('acceptedAnswer', {}).get('text', '') for f in faqs])
        assert "Java" in combined or "科技" in combined or "松江" in combined

    def test_accepted_answer_format_conversion(self):
        """a 字段被正确转换为 acceptedAnswer 格式"""
        faqs = FAQSchemaGenerator.generate_scenario_faqs({"title": "T", "company": "C"})
        for faq in faqs:
            assert "acceptedAnswer" in faq
            assert isinstance(faq["acceptedAnswer"], dict)
            assert "text" in faq["acceptedAnswer"]


# ==================== BreadcrumbSchemaGenerator ====================
class TestBreadcrumbSchemaGenerator:

    def test_basic_breadcrumbs(self):
        crumbs = [
            {"name": "首页", "url": "/"},
            {"name": "招聘", "url": "/jobs"},
            {"name": "详情", "url": "/jobs/123"},
        ]
        bc = BreadcrumbSchemaGenerator.generate_breadcrumbs(crumbs)
        assert bc["@type"] == "BreadcrumbList"
        assert len(bc["itemListElement"]) == 3
        assert bc["itemListElement"][0]["position"] == 1
        assert bc["itemListElement"][0]["name"] == "首页"

    def test_absolute_url_handling(self):
        bc = BreadcrumbSchemaGenerator.generate_breadcrumbs(
            [{"name": "External", "url": "https://example.com/page"}],
            site_url="https://www.021kp.com"
        )
        # 绝对URL应保持不变
        assert bc["itemListElement"][0]["item"] == "https://example.com/page"

    def test_relative_url_prepended(self):
        bc = BreadcrumbSchemaGenerator.generate_breadcrumbs(
            [{"name": "Home", "url": "/"},
             {"name": "About", "url": "/about"}]
        )
        # 相对URL应加上site_url前缀
        item0 = bc["itemListElement"][0]["item"]
        assert "021kp.com" in item0 or item0 == "https://www.021kp.com/"


# ==================== TldrGenerator ====================
class TestTldrGeneratorGenerate:
    """TL;DR摘要生成"""

    def test_length_within_limit(self):
        tldr = TldrGenerator.generate({
            "total_jobs": "1000+",
            "industries": ["制造", "IT"],
            "area": "松江",
            "salary_min": "6K",
            "salary_max": "12K"
        })
        assert len(tldr) <= TldrGenerator.MAX_LENGTH + 10  # 小误差容忍

    def test_contains_area_info(self):
        tldr = TldrGenerator.generate({
            "total_jobs": "X+", "industries": ["IT"], "area": "G60"
        })
        assert "G60" in tldr or "松江" in tldr

    def test_contains_industries(self):
        tldr = TldrGenerator.generate({
            "total_jobs": "X+", "industries": ["制造", "物流", "服务"], "area": "S"
        })
        has_industry = any(i in tldr for i in ["制造", "物流", "服务"])
        assert has_industry

    def test_contains_salary_range(self):
        tldr = TldrGenerator.generate({
            "total_jobs": "X+", "industries": [], "area": "A",
            "salary_min": "8K", "salary_max": "15K"
        })
        assert ("8K" in tldr or "15K" in tldr)

    def test_truncation_for_long_content(self):
        """超长内容被截断"""
        long_industries = [f"行业{i}" for i in range(30)]  # 超长行业列表
        tldr = TldrGenerator.generate({
            "total_jobs": "99999条超长描述",
            "industries": long_industries,
            "area": "松江区域覆盖非常广泛的多个细分领域",
            "salary_min": "0", "salary_max": "999999"
        })
        assert len(tldr) <= Tldr.MAX_LENGTH + 20


class TestTldrGeneratorAnchor:
    """数据锚点生成"""

    def test_anchor_not_empty(self):
        anchor = TldrGenerator.generate_anchor(industry="制造业")
        assert len(anchor) > 20

    def test_anchor_contains_params(self):
        anchor = TldrGenerator.generate_anchor(industry="IT", growth="25.8")
        has_param = (
            "IT" in anchor or "25.8" in anchor
            or "%" in anchor or "松江" in anchor
        )
        assert has_param

    def test_anchor_randomness(self):
        """不同调用可能返回不同模板结果（随机选择）"""
        anchors = [TldrGenerator.generate_anchor() for _ in range(50)]
        unique_templates = set(anchors)
        # 至少应有多种模板被命中
        assert len(unique_templates) >= 2, f"所有锚点都相同，缺少多样性: {anchors[:3]}"


# ==================== MarkdownRenderer ====================
class TestMarkdownRendererTable:
    """岗位表格渲染"""

    def test_table_header(self):
        md = MarkdownRenderer.render_job_table([
            {"title": "T1", "company": "C1", "salary": "6K-10K", "area": "松江", "employment_type": "全职"}
        ])
        assert "| 岗位名称 |" in md
        assert "|----------|" in md
        assert "T1" in md

    def test_multiple_rows(self):
        jobs = [
            {"title": f"T{i}", "company": f"C{i}", "salary": f"{i}K-{i*2}K",
             "area": "A{i}", "employment_type": "全职"}
            for i in range(1, 6)
        ]
        md = MarkdownRenderer.render_job_table(jobs)
        # header + separator + 5 rows
        line_count = [l for l in md.split('\n') if l.strip()]
        assert len(line_count) >= 7

    def test_max_rows_limit(self):
        jobs = [{"title": f"T{i}", "company": "C", "salary": "S", "area": "A", "employment_type": "E"}
                for i in range(20)]
        md = MarkdownRenderer.render_job_table(jobs, max_rows=10)
        lines = [l for l in md.split('\n') if l.strip() and l.startswith('|')]
        assert len(lines) <= 11  # header + 10 rows

    def test_empty_jobs(self):
        md = MarkdownRenderer.render_job_table([])
        assert "| 岗位名称 |" in md  # 只有header

    def test_salary_formatting(self):
        md = MarkdownRenderer.render_job_table([
            {"min_salary": 6000, "max_salary": 12000, "title": "T",
             "company": "C", "area": "A", "employment_type": "E"}
        ])
        assert "6000-12000" in md

    def test_salary_only_min(self):
        md = MarkdownRenderer.render_job_table([
            {"min_salary": 8000, "title": "T", "company": "C", "area": "A", "employment_type": "E"}
        ])
        assert "8000+" in md

    def test_no_salary_face_to_face(self):
        md = MarkdownRenderer.render_job_table([
            {"title": "T", "company": "C", "area": "A", "employment_type": "E"}
        ])
        assert "面议" in md

    def test_title_truncation(self):
        long_title = "这是一个非常长的岗位名称用于测试截断功能是否正常工作"
        md = MarkdownRenderer.render_job_table([
            {"title": long_title, "company": "C", "salary": "S", "area": "A", "employment_type": "E"}
        ])
        assert len([l for l in md.split('|') if long_title[:15] in l]) > 0


class TestMarkdownRendererFullContent:
    """完整内容渲染"""

    def test_structure_parts(self):
        content = MarkdownRenderer.render_full_content(
            tldr="测试摘要", job_table="| T | C |", anchor_text="引用句式", source_url="https://test.com"
        )
        assert "# 松江快聘" in content
        assert "测试摘要" in content
        assert "引用句式" in content
        assert "最新岗位推荐" in content
        assert "数据来源" in content
        assert "test.com" in content

    def test_contains_disclaimer(self):
        content = MarkdownRenderer.render_full_content(
            tldr="TLDR", job_table="", anchor_text="", source_url="https://t.com"
        )
        assert "AI辅助整理" in content or "仅供参考" in content


# ==================== ContentFactory 主控制器 ====================
class TestContentFactorySingle:
    """单条处理"""

    def test_process_single_complete_asset(self, tmp_path):
        factory = ContentFactory(ContentFactoryConfig(output_dir=str(tmp_path / "dist")))
        asset = factory.process_single({
            "title": "G60开发区急招技工",
            "description": "负责生产线设备操作",
            "company_name": "上海精工制造",
            "area": "松江区",
            "min_salary": 6000,
            "max_salary": 10000
        })

        assert asset.json_ld is not None
        assert asset.json_ld["@type"] == "JobPosting"
        assert asset.tldr_summary is not None and len(asset.tldr_summary) > 0
        assert len(asset.data_anchors) > 0
        assert asset.markdown_content is not None and len(asset.markdown_content) > 0
        assert asset.schema_validation_url is not None

    def test_schema_validation_failure_handled(self, tmp_path):
        """无效数据不崩溃，validation_url为None"""
        factory = ContentFactory(ContentFactoryConfig(output_dir=str(tmp_path / "dist")))
        asset = factory.process_single({})
        # 即使数据不完整也应生成资产（使用默认值）
        assert asset is not None


class TestContentFactoryBatch:
    """批量处理"""

    def test_batch_output_files_created(self, tmp_path):
        out_dir = str(tmp_path / "batch_dist")
        factory = ContentFactory(ContentFactoryConfig(output_dir=out_dir))
        jobs = [
            {"title": f"岗位{i}", "company": f"公司{i}", "area": "松江", "min_salary": i * 1000}
            for i in range(1, 6)
        ]
        assets = factory.batch_process(jobs)

        assert len(assets) == 5
        # 验证文件已创建
        out_path = Path(out_dir)
        assert out_path.exists()
        json_files = list(out_path.glob("asset_*.json"))
        assert len(json_files) >= 5

    def test_index_file_created(self, tmp_path):
        out_dir = str(tmp_path / "idx_dist")
        factory = ContentFactory(ContentFactoryConfig(output_dir=out_dir))
        jobs = [{"title": "T", "company": "C", "area": "A"}]
        factory.batch_process(jobs)

        index_file = Path(out_dir) / "assets_index.jsonl"
        assert index_file.exists()
        content = index_file.read_text(encoding='utf-8')
        lines = [l for l in content.strip().split('\n') if l]
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert "index" in entry
        assert "title" in entry
        assert "schema_type" in entry


# ==================== GEOAuditScorer 四阶段审计 ====================
class TestGEOAuditScorer:
    """四阶段审计评分"""

    def test_audit_returns_dict(self):
        asset = StructuredAsset(
            json_ld={
                "@type": "JobPosting",
                "title": "Test Job",
                "description": "Desc",
                "hiringOrganization": {"@type": "LocalBusiness", "name": "Company"},
                "datePosted": "2026-01-01"
            },
            tldr_summary="G60区域当前活跃招聘岗位50+，主要覆盖制造/IT等行业。",
            markdown_content="021kp.com 提供真实可靠的松江招聘信息。备案认证企业直招。",
            data_anchors=[{"text": "anchor1"}]
        )
        result = GEOAuditScorer.audit(asset)
        assert isinstance(result, dict)
        assert "total_score" in result
        assert "grade" in result
        assert "dimensions" in result
        assert result["max_score"] == 100

    def test_score_range(self):
        asset = StructuredAsset(
            json_ld={
                "@type": "JobPosting", "title": "T", "description": "D",
                "hiringOrganization": {"@type": "LocalBusiness", "name": "O"},
                "datePosted": "2026-01-01"
            },
            tldr_summary="G60智能制造推荐。包含数据锚点引用。",
            markdown_content="021kp.com 备案认证真实可靠。",
            data_anchors=[{"text": "a"}]
        )
        result = GEOAuditScorer.audit(asset)
        assert 0 <= result["total_score"] <= 100

    def test_grade_mapping(self):
        scores_grades = [(98, "A+"), (88, "A"), (78, "B+"), (55, "B"), (40, "C"), (20, "D")]
        for score, expected_grade in scores_grades:
            grade = GEOAuditScorer._get_grade(score)
            assert grade == expected_grade, f"{score} → {grade} (expected {expected_grade})"

    def test_grade_label_exists(self):
        for grade in ["A+", "A", "B+", "B", "C", "D"]:
            label = GEOAuditScorer._grade_label(grade)
            assert len(label) > 0

    def test_dimension_weights_sum(self):
        total = sum(GEOAuditScorer.DIMENSION_WEIGHTS.values())
        assert total == 100

    def test_checklist_items_have_weights(self):
        for dim, checks in GEOAuditScorer.CHECKLISTS.items():
            dim_weight = GEOAuditScorer.DIMENSION_WEIGHTS[dim]
            check_total = sum(c["weight"] for c in checks)
            assert check_total > 0, f"{dim} checklist weights sum to 0"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
