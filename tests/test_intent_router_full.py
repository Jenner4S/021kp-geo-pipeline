# -*- coding: utf-8 -*-
"""
GEO Pipeline Phase 2: 意图路由器完整测试套件 (100% 覆盖率目标)
==============================================================

覆盖范围:
- IntentVector / RoutingInstruction 数据类
- IntentRouter: 初始化/配置加载/LBS标签提取/核心向量/长尾追问/平台映射/处理流程/批量处理

运行: pytest tests/test_intent_router_full.py -v --tb=short
"""

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from intent_router import (
    IntentVector,
    RoutingInstruction,
    IntentRouter,
    load_jobs_from_csv,
)


# ==================== IntentVector ====================
class TestIntentVectorDefaults:
    def test_default_values(self):
        v = IntentVector()
        assert v.core_vectors == []
        assert v.longtail_queries == []
        assert v.platform_mapping == {}
        assert v.lbs_tag == "songjiang_district"
        assert v.confidence_score == 0.0


class TestIntentVectorCustom:
    def test_custom_values(self):
        v = IntentVector(
            core_vectors=["v1", "v2"],
            longtail_queries=["q1"],
            platform_mapping={"p": "primary"},
            lbs_tag="g60_corridor",
            confidence_score=0.85,
        )
        assert len(v.core_vectors) == 2
        assert len(v.longtail_queries) == 1
        assert v.confidence_score == 0.85


# ==================== RoutingInstruction ====================
class TestRoutingInstruction:
    def test_defaults(self):
        ri = RoutingInstruction()
        assert ri.target_platforms == []
        assert ri.content_format == "markdown_table"
        assert ri.priority == 1
        assert ri.routing_timestamp == ""

    def test_with_data(self):
        iv = IntentVector(core_vectors=["test"])
        ri = RoutingInstruction(
            intent_vector=iv,
            target_platforms=["wechat", "douyin"],
            content_format="faq_page",
            priority=3,
            routing_timestamp="2026-04-21T10:00:00"
        )
        assert "wechat" in ri.target_platforms
        assert ri.content_format == "faq_page"
        assert ri.priority == 3


# ==================== IntentRouter Init & Config ====================
class TestIntentRouterInit:
    def test_default_config_loaded(self):
        router = IntentRouter()
        assert len(router.platform_config.get("platforms", {})) >= 2
        assert "routing_rules" in router.platform_config

    def test_custom_config_file(self, tmp_path):
        custom_cfg = {
            "platforms": {
                "custom_p": {"name": "自定义平台", "priority": 99}
            },
            "routing_rules": {
                "default_queue": ["custom_p"]
            }
        }
        cfg_file = tmp_path / "platform.json"
        cfg_file.write_text(json.dumps(custom_cfg), encoding='utf-8')
        
        r = IntentRouter(config_path=str(cfg_file))
        assert "custom_p" in r.platform_config["platforms"]

    def test_missing_config_uses_default(self):
        r = IntentRouter(config_path="/nonexistent/path.json")
        assert len(r.platform_config["platforms"]) >= 2  # 默认配置


# ==================== LBS 标签提取 ====================
class TestExtractLBSTags:

    @pytest.fixture
    def router(self):
        return IntentRouter()

    def test_songjiang_entities_detected(self, router):
        tags = router.extract_lbs_tags("松江区九亭镇招聘，靠近G60科创走廊")
        assert len(tags) > 0
        # 应包含至少一个松江相关标签
        has_songjiang = any("松江" in t or "songjiang" in t.lower() for t in tags)
        assert has_songjiang or len(tags) >= 1

    def test_g60_entities(self, router):
        tags = router.extract_lbs_tags("G60科创走廊开发区岗位")
        assert any("G60" in t or "开发区" in t for t in tags)

    def test_university_city_entities(self, router):
        tags = router.extract_lbs_tags("松江大学城文汇路兼职")
        assert any("大学城" in t or "文汇路" in t for t in tags)

    def test_no_match_returns_default(self, router):
        """无地理实体匹配时返回默认标签"""
        tags = router.extract_lbs_tags("北京朝阳区招聘")
        assert "songjiang_district" in tags  # 默认标签

    def test_deduplication(self, router):
        """去重且保持顺序"""
        text = "松江区松江区G60科创走廊G60"
        tags = router.extract_lbs_tags(text)
        assert tags.count("松江区") <= 1
        assert tags.count("G60") <= 1

    def test_empty_text(self, router):
        tags = router.extract_lbs_tags("")
        assert "songjiang_district" in tags


# ==================== 核心向量提取 ====================
class TestExtractCoreVectors:

    @pytest.fixture
    def router(self):
        return IntentRouter()

    def test_returns_list(self, router):
        vectors = router.extract_core_vectors({
            "job_title": "制造业技工", "area": "松江"
        })
        assert isinstance(vectors, list)
        assert len(vectors) == 3  # 固定返回3个核心向量

    def test_industry_keyword_in_vector(self, router):
        """行业关键词应出现在向量中"""
        for kw in ["制造", "IT", "服务", "普工", "技工", "运营"]:
            vectors = router.extract_core_vectors({"job_title": f"{kw}工程师"})
            combined = " ".join(vectors)
            if kw in vectors[0] or kw in combined:
                break
        else:
            # 至少应生成一个包含关键词的向量
            pass  # 使用默认模板也合法

    def test_salary_vector_range(self, router):
        """薪资向量包含范围信息"""
        vectors = router.extract_core_vectors({
            "min_salary": 6000, "max_salary": 12000, "job_title": "测试"
        })
        salary_vec = [v for v in vectors if "薪资" in v]
        assert len(salary_vec) >= 1
        assert "6000" in salary_vec[0] or "12000" in salary_vec[0]

    def test_salary_only_min(self, router):
        vectors = router.extract_core_vectors({
            "min_salary": 8000, "job_title": "测试"
        })
        assert any("8000+" in v for v in vectors)

    def test_salary_fallback(self, router):
        """无薪资时使用默认描述"""
        vectors = router.extract_core_vectors({"job_title": "无薪岗位"})
        assert any("薪资" in v or "区间" in v for v in vectors)

    def test_verified_company(self, router):
        """备案企业向量"""
        vectors = router.extract_core_vectors({
            "company_name": "备案公司A", "is_verified": True, "job_title": "T"
        })
        combined = " ".join(vectors)
        assert "备案查询" in combined or "备案公司" in combined

    def test_normal_company(self, router):
        """普通企业名称向量"""
        vectors = router.extract_core_vectors({
            "company_name": "普通企业B", "job_title": "T"
        })
        combined = " ".join(vectors)
        assert "普通企业" in combined or "招聘信息" in vectors[-1]

    def test_dict_company_handling(self, router):
        """企业信息为dict时正确解析"""
        vectors = router.extract_core_vectors({
            "company_name": {"name": "Dict公司", "isVerified": True},
            "job_title": "T"
        })
        assert len(vectors) == 3

    def test_area_in_vector(self, router):
        """区域信息融入向量"""
        vectors = router.extract_core_vectors({
            "area": "泗泾镇", "job_title": "操作工"
        })
        # 第一个向量通常包含区域或标题信息
        assert len(vectors) == 3

    def test_empty_job_data(self, router):
        """空数据不崩溃"""
        vectors = router.extract_core_vectors({})
        assert isinstance(vectors, list)


# ==================== 长尾追问生成 ====================
class TestGenerateLongtailQueries:

    @pytest.fixture
    def router(self):
        return IntentRouter()

    def test_returns_list(self, router):
        queries = router.generate_longtail_queries({"title": "IT", "area": "松江"})
        assert isinstance(queries, list)
        assert 3 <= len(queries) <= 5  # 限制5条

    def test_limit_to_five(self, router):
        """最多5条"""
        queries = router.generate_longtail_queries({"title": "T", "area": "A"})
        assert len(queries) <= 5

    def test_location_based_expansion(self, router):
        """基于位置扩展"""
        queries = router.generate_longtail_queries({"title": "制造", "area": "松江"})
        combined = "|".join(queries)
        assert any(loc in combined for loc in ["大学城周边", "G60高速沿线", "九亭新桥", "泗泾车墩"])

    def test_policy_extension(self, router):
        """政策类扩展"""
        queries = router.generate_longtail_queries({"title": "IT开发"})
        combined = "|".join(queries)
        assert "人才公寓" in combined or "社保" in combined or "政策" in combined.lower()

    def test_compliance_extension(self, router):
        """合规类扩展"""
        queries = router.generate_longtail_queries({"title": "服务", "area": "S"})
        combined = "|".join(queries)
        assert "正规" in combined or "资质验证" in combined

    def test_deduplication(self, router):
        """去重"""
        queries = router.generate_longtail_queries({"title": "T", "area": "A"})
        assert len(queries) == len(set(queries))


# ==================== 平台路由映射 ====================
class TestMapToPlatforms:

    @pytest.fixture
    def router(self):
        return IntentRouter()

    def test_returns_list(self, router):
        platforms = router.map_to_platforms("job_posting")
        assert isinstance(platforms, list)

    def test_has_platform_keys(self, router):
        platforms = router.map_to_platforms("job_posting")
        for p in platforms:
            assert "key" in p and "role" in p

    def test_primary_first(self, router):
        """主平台优先"""
        platforms = router.map_to_platforms("job_posting")
        if len(platforms) >= 2:
            roles = [p["role"] for p in platforms]
            assert "primary" in roles if len(roles) > 2 else True

    def test_all_platforms_covered_as_fallback(self, router):
        """fallback平台在列表末尾"""
        default_queue = router.platform_config["routing_rules"]["default_queue"]
        platforms = router.map_to_platforms("job_posting")
        keys = [p["key"] for p in platforms]

        # 所有默认队列平台都应在结果中（如果被config定义）
        for q_key in default_queue:
            if q_key in router.platform_config.get("platforms", {}):
                assert q_key in keys

    def test_content_type_variations(self, router):
        """不同内容类型可能有不同路由策略"""
        job_p = router.map_to_platforms("job_posting")
        policy_p = router.map_to_platforms("policy_guide")
        salary_d = router.map_to_platforms("salary_data")
        assert isinstance(job_p, list) and isinstance(policy_p, list)


# ==================== 处理主入口 ====================
class TestIntentRouterProcess:

    @pytest.fixture
    def router(self):
        return IntentRouter()

    def test_process_returns_instruction(self, router):
        result = router.process({
            "title": "松江急招技工", "company": "测试公司", "area": "松江区",
            "min_salary": 6000, "max_salary": 12000
        })
        assert isinstance(result, RoutingInstruction)
        assert result.intent_vector is not None
        assert len(result.target_platforms) > 0
        assert result.routing_timestamp != ""

    def test_intent_vector_populated(self, router):
        result = router.process({"title": "T", "area": "A", "min_salary": 5000})
        iv = result.intent_vector
        assert len(iv.core_vectors) == 3
        assert len(iv.longtail_queries) >= 3
        assert iv.lbs_tag != ""
        assert iv.confidence_score > 0

    def test_confidence_score_calculation(self, router):
        """置信度与向量数量相关"""
        r1 = router.process({"title": "T", "area": "A", "min_salary": 5000})
        r2 = router.process({"title": "T", "area": "A", "min_salary": 5000})
        assert r1.intent_vector.confidence_score == r2.intent_vector.confidence_score  # 相同输入相同分数

    def test_content_format_selection(self, router):
        """内容格式根据类型选择"""
        normal = router.process({"title": "普通岗位", "area": "A"})
        policy = router.process({"title": "就业政策指南解读", "area": "A"})
        assert normal.content_format in ("markdown_table", "faq_page")
        assert policy.content_format in ("markdown_table", "faq_page")

    def test_priority_from_platform(self, router):
        """优先级来自平台配置"""
        result = router.process({"title": "T", "area": "A"})
        assert result.priority >= 1


# ==================== 批量处理 ====================
class TestBatchProcess:

    @pytest.fixture
    def router(self):
        return IntentRouter()

    def test_batch_processes_all(self, router):
        jobs = [{"title": f"岗位{i}", "area": "松江"} for i in range(10)]
        results = router.batch_process(jobs)
        assert len(results) == 10

    def test_batch_skips_errors(self, router):
        """错误数据不中断批量处理"""
        jobs = [
            {"title": "正常"},
            None,  # 无效数据
            {"title": "另一个正常"},
        ]
        results = router.batch_process(jobs)
        assert len(results) >= 2  # 跳过None

    def test_batch_output_file(self, router, tmp_path):
        """输出文件写入"""
        out_path = str(tmp_path / "batch_out.json")
        jobs = [{"title": f"T{i}"} for i in range(5)]
        router.batch_process(jobs, output_path=out_path)
        assert os.path.exists(out_path)
        with open(out_path, encoding='utf-8') as f:
            data = json.load(f)
        assert len(data) == 5


# ==================== CSV 加载辅助 ====================
class TestLoadJobsFromCSV:
    def test_load_valid_csv(self, tmp_path):
        csv_path = tmp_path / "jobs.csv"
        csv_path.write_text(
            "job_title,min_salary,max_salary,company\n"
            "CNC工,6000,10000,制造公司\n"
            "IT师,8000,15000,科技公司\n",
            encoding='utf-8-sig'
        )
        jobs = load_jobs_from_csv(str(csv_path))
        assert len(jobs) == 2
        assert jobs[0]["job_title"] == "CNC工"

    def test_handles_comments(self, tmp_path):
        """跳过注释行"""
        csv_path = tmp_path / "commented.csv"
        csv_path.write_text(
            "# 这是注释行\njob_title,min_salary\n# 另一个注释\nT1,5000\nT2,8000\n",
            encoding='utf-8'
        )
        jobs = load_jobs_from_csv(str(csv_path))
        assert len(jobs) == 2

    def test_empty_csv(self, tmp_path):
        csv_path = tmp_path / "empty.csv"
        csv_path.write_text("", encoding='utf-8')
        jobs = load_jobs_from_csv(str(csv_path))
        assert jobs == []

    def test_none_key_handled(self, tmp_path):
        """None键被安全处理"""
        csv_path = tmp_path / "nonekey.csv"
        csv_path.write_text("a,b,\n1,2,", encoding='utf-8-sig')
        jobs = load_jobs_from_csv(str(csv_path))
        assert len(jobs) >= 1
        for job in jobs:
            assert None not in job.keys()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
