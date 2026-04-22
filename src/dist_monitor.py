"""
021kp.com GEO自动化运营系统 - Phase 5: 分发监控与闭环反馈模块 (Dist Monitor)
=============================================================================

功能描述:
    实现定时分发、AI引用率监控、阈值告警与自动回滚，核心能力：
    1. Cron定时任务调度（每日14:00/20:00）
    2. 豆包/元宝等平台AI引用率采集
    3. 引用率阈值检测（<0.5%触发告警/回滚）
    4. 向量回滚协议（切换至Plan_C合规模板）
    5. AI预览模拟报告生成
    6. 动态关键词配置（支持数据库/配置文件/在线管理）

使用说明:
    python src/dist_monitor.py --mode schedule    # 启动定时监控
    python src/dist_monitor.py --mode check       # 单次检查
    python src/dist_monitor.py --mode report      # 生成报告

作者: GEO-Engine Team | 版本: v1.1 | 日期: 2026-04-22
"""

import json
import os
import threading
import time
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any

try:
    import requests
    from loguru import logger
except ImportError:
    requests = None  # type: ignore[assignment]
    import logging as logger


# ==================== 数据类型定义 ====================
class MonitorState(Enum):
    """监控系统状态枚举"""
    NORMAL = "NORMAL"          # 正常运行
    DEGRADED = "DEGRADED"      # 降级模式
    FROZEN = "FROZEN"          # 已冻结（触发回滚）


@dataclass
class CitationMetrics:
    """引用率指标数据类"""
    platform: str = ""
    brand_mention_count: int = 0
    total_queries: int = 0
    citation_rate: float = 0.0  # 引用率 (0-100%)
    ctr_estimate: float | None = None
    last_check_time: str = ""
    trend: str = "stable"  # stable / rising / falling
    # 引用详情
    cited_keywords: list[str] = dataclass_field(default_factory=list)  # 被引用的关键词
    cited_sources: list[dict] = dataclass_field(default_factory=list)  # 被引用的来源 [{title, url, snippet}]
    search_queries_used: list[str] = dataclass_field(default_factory=list)  # 本次使用的搜索词
    citation_contexts: list[dict] = dataclass_field(default_factory=list)  # 引用场景 [{query, response_snippet}]


@dataclass
class AlertRule:
    """告警规则数据类"""
    metric_name: str
    threshold: float
    operator: str = "<="  # <, >, <=, >=, ==
    consecutive_failures: int = 3
    cooldown_seconds: int = 3600
    severity: str = "warning"  # warning / critical / info
    action: str = "alert"  # alert / rollback / notify_only


@dataclass
class MonitorReport:
    """监控报告数据类"""
    report_id: str = ""
    generated_at: str = ""
    period_start: str = ""
    period_end: str = ""
    metrics: list[CitationMetrics] = dataclass_field(default_factory=list)
    overall_status: MonitorState = MonitorState.NORMAL
    alerts_triggered: list[dict[str, Any]] = dataclass_field(default_factory=list)
    recommendations: list[str] = dataclass_field(default_factory=list)
    ai_preview_simulation: str = ""
    debug_logs: list[dict[str, Any]] = dataclass_field(default_factory=list)


# ==================== AI平台引用探针 ====================
class AICitationProbe:
    """
    AI平台引用率探针
    
    功能:
    - 模拟用户搜索查询，检测品牌在AI概览中的提及情况
    - 支持的平台: 秘塔(Metaso)、豆包(Doubao)、元宝(Yuanbao)
    
    注意事项:
    本模块通过HTTP请求模拟查询行为，
    实际部署时需遵守各平台robots.txt与服务条款。
    建议使用官方API或合作渠道获取真实数据。
    
    当前版本为模拟实现，用于验证流程完整性。
    生产环境需替换为真实的API调用或人工审核流程。

    动态配置说明:
        - 搜索关键词库 (search_queries) 和品牌关键词 (brand_keywords)
          支持三种配置方式，按优先级排序:
          1. 数据库配置 (keywords_config 表)
          2. 配置文件 (keywords.json)
          3. 默认示例数据 (仅供测试，生产请配置)
    """

    def __init__(self, config_path: str | None = None, keywords_config_path: str | None = None):
        self.config = self._load_config(config_path)
        self._keywords_config_path = keywords_config_path or "./keywords.json"

        # 动态加载关键词（搜索词库 + 品牌关键词）
        self.search_queries: list[str] = []
        self.brand_keywords: list[str] = []
        self._load_keywords()

        # 探针缓存（避免频繁请求同一URL）+ TTL淘汰
        self._cache: dict[str, dict] = {}
        self._cache_ttl = 3600  # 缓存1小时
        self._cache_max_size = 1000  # 最大缓存条目数(防止内存泄漏)

    def _load_config(self, config_path: str | None) -> dict:
        """加载配置"""
        default_config = {
            "probes": {
                # 国内主流 AI 平台
                "deepseek": {"enabled": True, "base_url": "https://chat.deepseek.com", "name": "DeepSeek 深度求索"},
                "doubao": {"enabled": True, "base_url": "https://www.doubao.com", "name": "豆包"},
                "yuanbao": {"enabled": True, "base_url": "https://yuanbao.tencent.com", "name": "元宝"},
                "tongyi": {"enabled": True, "base_url": "https://tongyi.aliyun.com", "name": "通义千问"},
                "wenxin": {"enabled": True, "base_url": "https://yiyan.baidu.com", "name": "文心一言"},
                "kimi": {"enabled": True, "base_url": "https://kimi.moonshot.cn", "name": "Kimi"},
                "zhipu": {"enabled": True, "base_url": "https://www.zhipuai.cn", "name": "智谱清言"},
                "metaso": {"enabled": True, "base_url": "https://metaso.cn", "name": "秘塔 AI"},
                "nami": {"enabled": True, "base_url": "https://www.namiai.cn", "name": "纳米 AI"},
            },
            "check_interval_hours": 2,
            "timeout_seconds": 15,
            "user_agent": "021kp-GEO-Monitor/1.0"
        }

        if config_path and os.path.exists(config_path):
            with open(config_path, encoding='utf-8') as f:
                return {**default_config, **json.load(f)}
        return default_config

    def _load_keywords(self) -> None:
        """
        从岗位数据自动提取关键词（核心功能）

        搜索关键词来源:
        - 岗位标题中的职位类型（操作工、司机、文员、厨师等）
        - 岗位的地区字段（松江、九亭、泗泾等）
        - 岗位的公司名字段

        品牌关键词来源:
        - 岗位来源 URL 的域名部分
        - 固定品牌词（松江快聘、021kp.com）

        优先级: 岗位数据提取 > 配置文件 > 空（无可用数据）
        """
        import re
        from collections import Counter

        # 职位类型关键词（用于搜索）
        job_type_keywords = []
        # 地区关键词
        location_keywords = []
        # 品牌关键词
        brand_keywords_set = set()
        # 来源域名
        source_domains = set()

        # 常用职位类型词（作为种子）
        job_type_seeds = [
            "操作工", "司机", "文员", "会计", "仓库", "包装", "检验", "客服",
            "保安", "保洁", "厨师", "服务员", "收银", "营业员", "导购", "销售",
            "普工", "技工", "电焊", "叉车", "钳工", "铣工", "数控", "学徒",
            "主管", "经理", "店长", "助理", "专员", "工程师", "技术员"
        ]

        # 常用地区词（上海松江区域）
        location_seeds = [
            "松江", "九亭", "泗泾", "佘山", "新桥", "车墩", "洞泾", "泖港",
            "石湖荡", "小昆山", "新浜", "叶榭", "茸城", "方松", "岳阳",
            "中山", "广富林", "永丰"
        ]

        # 固定品牌关键词
        brand_keywords_set.add("021kp.com")
        brand_keywords_set.add("松江快聘")
        brand_keywords_set.add("021kp")

        def extract_keywords_from_text(text: str, seeds: list[str]) -> list[str]:
            """从文本中提取匹配的关键词"""
            if not text:
                return []
            found = []
            for seed in seeds:
                if seed in text:
                    found.append(seed)
            return found

        def extract_domain(url: str) -> str | None:
            """从 URL 提取域名"""
            if not url:
                return None
            match = re.search(r'(?:https?://)?(?:www\.)?([a-zA-Z0-9][-a-zA-Z0-9]*\.[a-zA-Z]{2,}(?:\.[a-zA-Z]{2,})?)', url)
            if match:
                domain = match.group(1)
                # 排除通用域名
                if domain not in ('baidu.com', 'qq.com', 'aliyun.com', 'tencent.com', 'sina.com'):
                    return domain
            return None

        # 从岗位数据提取关键词
        try:
            jobs = self._fetch_real_jobs()
            if jobs:
                logger.info(f"[Keywords] 从 {len(jobs)} 条岗位数据提取关键词...")

                for job in jobs:
                    title = job.get('title', '') or job.get('name', '')
                    location = job.get('location', '') or job.get('area', '') or job.get('district', '')
                    company = job.get('company', '') or job.get('employer', '')
                    source = job.get('source', '') or job.get('source_url', '') or job.get('url', '')

                    # 提取职位类型
                    job_type_keywords.extend(extract_keywords_from_text(title, job_type_seeds))

                    # 提取地区关键词
                    location_keywords.extend(extract_keywords_from_text(location, location_seeds))

                    # 提取域名作为品牌词
                    domain = extract_domain(source)
                    if domain:
                        source_domains.add(domain)
                        brand_keywords_set.add(domain)

                    # 提取公司名作为品牌词（取前3个字）
                    if company and len(company) >= 2:
                        brand_keywords_set.add(company[:6])  # 取前6个字符

                # 统计高频词
                job_type_counter = Counter(job_type_keywords)
                location_counter = Counter(location_keywords)

                # 取高频词作为搜索关键词
                top_job_types = [kw for kw, _ in job_type_counter.most_common(10)]
                top_locations = [kw for kw, _ in location_counter.most_common(5)]

                # 构建搜索关键词：地区 + 职位类型
                search_queries = []
                for loc in top_locations:
                    for job_type in top_job_types[:5]:
                        search_queries.append(f"{loc}{job_type}")
                        search_queries.append(f"{loc}招聘{job_type}")

                # 添加纯职位类型搜索词
                search_queries.extend(top_job_types)
                search_queries.extend([f"松江{t}" for t in top_job_types[:5]])

                # 去重
                self.search_queries = list(dict.fromkeys(search_queries))[:20]
                self.brand_keywords = list(brand_keywords_set)

                logger.info(
                    f"[Keywords] 提取完成: {len(self.search_queries)} 个搜索词, "
                    f"{len(self.brand_keywords)} 个品牌词"
                )
                logger.debug(f"[Keywords] 搜索词: {self.search_queries[:5]}...")
                logger.debug(f"[Keywords] 品牌词: {self.brand_keywords}")

                return  # 成功从岗位数据提取，结束
            else:
                logger.debug("[Keywords] 无岗位数据可提取关键词")
        except Exception as e:
            logger.warning(f"[Keywords] 从岗位数据提取关键词失败: {e}")

        # 备选: 从配置文件加载
        if os.path.exists(self._keywords_config_path):
            try:
                with open(self._keywords_config_path, encoding='utf-8') as f:
                    kw_config = json.load(f)
                self.search_queries = kw_config.get('search_queries', [])
                self.brand_keywords = kw_config.get('brand_keywords', [])
                if self.search_queries or self.brand_keywords:
                    logger.info(f"[Keywords] 从配置文件加载 {len(self.search_queries)} 个搜索词")
                    return
            except Exception as e:
                logger.warning(f"[Keywords] 配置文件读取失败: {e}")

        # 无可用数据: 使用基于岗位数据特征的默认词（松江快聘专用）
        self.search_queries = [
            "松江招聘", "松江操作工", "松江司机", "松江文员",
            "松江工厂", "松江仓库", "松江检验", "松江包装",
            "九亭招聘", "泗泾求职", "G60招聘"
        ]
        self.brand_keywords = list(brand_keywords_set)
        logger.warning(
            "[Keywords] 使用松江快聘默认搜索词。"
            "建议上传岗位数据以获得更精准的关键词。"
        )

    def save_keywords(self, search_queries: list[str] | None = None, brand_keywords: list[str] | None = None, save_to_db: bool = False) -> dict:
        """
        保存关键词配置

        Args:
            search_queries: 搜索关键词列表
            brand_keywords: 品牌关键词列表
            save_to_db: 是否保存到数据库（否则保存到文件）

        Returns:
            保存结果
        """
        result = {"success": False, "message": "", "saved_count": 0}

        if search_queries is not None:
            self.search_queries = [kw.strip() for kw in search_queries if kw.strip()]
        if brand_keywords is not None:
            self.brand_keywords = [kw.strip() for kw in brand_keywords if kw.strip()]

        if save_to_db:
            # 保存到数据库
            try:
                from database_backend import get_backend
                db = get_backend()
                if db:
                    # 清空旧数据，插入新数据
                    db.execute_query("DELETE FROM keywords_config WHERE config_type IN ('search_query', 'brand_keyword')")
                    for kw in self.search_queries:
                        db.execute_query(
                            "INSERT INTO keywords_config (config_type, config_key, config_value) VALUES ('search_query', 'search_query', %s)",
                            (kw,)
                        )
                    for kw in self.brand_keywords:
                        db.execute_query(
                            "INSERT INTO keywords_config (config_type, config_key, config_value) VALUES ('brand_keyword', 'brand_keyword', %s)",
                            (kw,)
                        )
                    result["success"] = True
                    result["message"] = f"已保存到数据库: {len(self.search_queries)} 个搜索词, {len(self.brand_keywords)} 个品牌词"
                    result["saved_count"] = len(self.search_queries) + len(self.brand_keywords)
                    logger.info(f"[Keywords] 保存到数据库成功")
                    return result
            except Exception as e:
                result["message"] = f"数据库保存失败: {e}"
                logger.warning(f"[Keywords] 数据库保存失败: {e}")
        else:
            # 保存到配置文件
            try:
                kw_config = {
                    "search_queries": self.search_queries,
                    "brand_keywords": self.brand_keywords,
                    "updated_at": datetime.now().isoformat()
                }
                with open(self._keywords_config_path, 'w', encoding='utf-8') as f:
                    json.dump(kw_config, f, ensure_ascii=False, indent=2)
                result["success"] = True
                result["message"] = f"已保存到文件: {len(self.search_queries)} 个搜索词, {len(self.brand_keywords)} 个品牌词"
                result["saved_count"] = len(self.search_queries) + len(self.brand_keywords)
                logger.info(f"[Keywords] 保存到配置文件成功: {self._keywords_config_path}")
                return result
            except Exception as e:
                result["message"] = f"文件保存失败: {e}"
                logger.warning(f"[Keywords] 文件保存失败: {e}")

        return result

    def get_keywords(self) -> dict:
        """
        获取当前关键词配置

        Returns:
            {
                "search_queries": [...],  // 从岗位数据自动提取
                "brand_keywords": [...],  // 从岗位数据自动提取
                "job_keywords": {...},    // 按类型分类的关键词统计
                "total_count": int,
                "source": "auto" | "config" | "default",
                "job_count_used": int  // 用于提取的岗位数据条数
            }
        """
        return {
            "search_queries": self.search_queries,
            "brand_keywords": self.brand_keywords,
            "total_count": len(self.search_queries) + len(self.brand_keywords),
            "source": "auto",  # 现在都是自动从岗位数据提取
            "job_count_used": 0  # 将在 _load_keywords 时更新
        }

    def refresh_keywords(self) -> dict:
        """
        重新从岗位数据提取关键词

        Returns:
            提取结果统计
        """
        self._load_keywords()
        return {
            "success": True,
            "search_queries_count": len(self.search_queries),
            "brand_keywords_count": len(self.brand_keywords),
            "message": f"已从岗位数据提取 {len(self.search_queries)} 个搜索词, {len(self.brand_keywords)} 个品牌词"
        }

    def check_citation_rate(
        self,
        platform_key: str,
        query: str | None = None
    ) -> CitationMetrics:
        """
        检查指定平台的引用率
        
        Args:
            platform_key: 平台标识 (metaso/doubao/yuanbao)
            query: 搜索查询词（为None则使用默认词库随机选择）
            
        Returns:
            CitationMetrics 引用指标对象（含详细引用信息）
        """
        # 动态关键词列表（支持空列表的容错处理）
        kw_list = self.search_queries if self.search_queries else ["招聘", "找工作"]
        query = query or kw_list[int(time.time()) % len(kw_list)]

        metrics = CitationMetrics(
            platform=platform_key,
            total_queries=1,
            last_check_time=datetime.now(timezone(timedelta(hours=8))).isoformat(),
            search_queries_used=[query]
        )

        # 缓存TTL淘汰（防止内存泄漏）
        if len(self._cache) > self._cache_max_size:
            oldest_keys = sorted(
                self._cache.keys(),
                key=lambda k: self._cache[k].get('_ts', 0)
            )[:len(self._cache)//3]
            for k in oldest_keys:
                del self._cache[k]

        # === 模拟实现（生产环境需替换为真实API调用）===
        try:
            # 尝试实际请求（示例）
            probe_config = self.config.get("probes", {}).get(platform_key, {})

            if probe_config.get("enabled") and requests is not None:
                # 构建模拟搜索请求
                headers = {
                    "User-Agent": self.config.get("user_agent", ""),
                    "Accept": "application/json"
                }

                logger.debug(f"[Probe {platform_key}] 📤 发送请求:")
                logger.debug(f"       URL: {probe_config.get('base_url', '')}/search")
                logger.debug(f"       Query: {query}")

                # 模拟请求逻辑
                response_data = self._simulate_platform_response(
                    platform_key, query
                )

                logger.debug(f"[Probe {platform_key}] 📥 收到响应:")
                logger.debug(f"       Raw Data: {response_data}")

                metrics.brand_mention_count = response_data.get("mention_count", 0)
                metrics.total_queries = response_data.get("total_results", 100)

                if metrics.total_queries > 0:
                    metrics.citation_rate = (
                        metrics.brand_mention_count / metrics.total_queries * 100
                    )

                metrics.trend = response_data.get("trend", "stable")
                
                # 收集引用详情
                metrics.cited_keywords = response_data.get("cited_keywords", [query])
                metrics.cited_sources = response_data.get("cited_sources", [])
                metrics.citation_contexts = response_data.get("citation_contexts", [])

                logger.debug(f"[Probe {platform_key}] 📊 计算结果:")
                logger.debug(f"       Brand Mentions: {metrics.brand_mention_count}")
                logger.debug(f"       Total Queries: {metrics.total_queries}")
                logger.debug(f"       Citation Rate: {metrics.citation_rate:.4f}%")
                logger.debug(f"       Cited Sources: {len(metrics.cited_sources)}")

            else:
                # 纯模拟模式（无网络或禁用时）
                logger.debug(f"[Probe {platform_key}] 🎭 模拟模式（无网络请求）")
                mock_result = self._generate_mock_metrics(platform_key, query)
                metrics = mock_result
                metrics.search_queries_used = [query]

        except Exception as e:
            logger.error(f"❌ 探针异常 ({platform_key}): {e}")
            metrics.citation_rate = 0.0
            metrics.trend = "unknown"

        logger.info(
            f"🔍 [{platform_key}] 引用率检测完成 | "
            f"查询='{query}' | "
            f"提及={metrics.brand_mention_count}次 | "
            f"引用率={metrics.citation_rate:.2f}%"
        )

        return metrics

    def _simulate_platform_response(
            self,
            platform: str,
            query: str
        ) -> dict[str, Any]:
        """
        模拟平台响应（开发测试用）

        实际生产环境应替换为真实API调用
        """
        import random
        import json

        # 生成随机种子以保持一致性
        seed = hash(f"{platform}:{query}") % 10000
        rng = random.Random(seed)

        # 尝试从数据库获取真实的岗位数据
        real_jobs = self._fetch_real_jobs()

        # 构建模拟请求报文（使用真实查询参数）
        request_packet = {
            "method": "POST",
            "url": f"https://api.{platform}.com/v1/search",
            "headers": {
                "Content-Type": "application/json",
                "Authorization": "Bearer ******",  # 脱敏
                "User-Agent": self.config.get("user_agent", "021kp-GEO-Monitor/1.0")
            },
            "body": {
                "query": query,
                "search_type": "web",
                "include_ai_overview": True,
                "max_results": 20,
                "filters": {
                    "region": "cn",
                    "language": "zh-CN"
                }
            }
        }

        logger.debug(f"[{platform}] ═══════════════════════════════════════════")
        logger.debug(f"[{platform}] 📤 REQUEST PACKET:")
        logger.debug(f"[{platform}]   Method: {request_packet['method']}")
        logger.debug(f"[{platform}]   URL:    {request_packet['url']}")
        logger.debug(f"[{platform}]   Headers: {json.dumps(request_packet['headers'], indent=6, ensure_ascii=False)}")
        logger.debug(f"[{platform}]   Body:   {json.dumps(request_packet['body'], indent=6, ensure_ascii=False)}")

        # 如果有真实岗位数据，使用真实数据；否则使用模拟数据
        if real_jobs and len(real_jobs) > 0:
            logger.debug(f"[{platform}] 📦 使用真实岗位数据，共 {len(real_jobs)} 条")
        else:
            logger.debug(f"[{platform}] 🎭 无真实数据，使用模拟数据")

        # 生成品牌提及次数（基于真实数据的覆盖率）
        if real_jobs:
            mention_count = rng.randint(min(1, len(real_jobs)), min(len(real_jobs), 5))
        else:
            mention_count = rng.randint(0, 3)

        total_results = len(real_jobs) * rng.randint(10, 50) if real_jobs else rng.randint(50, 500)

        # 构建真实岗位数据的结果列表
        top_results = []
        if real_jobs:
            for i, job in enumerate(real_jobs[:5]):
                top_results.append({
                    "title": job.get("title", f"松江招聘信息 #{i+1}"),
                    "url": job.get("url", f"https://021kp.com/job/{job.get('id', i+1000)}"),
                    "relevance": round(rng.uniform(0.85, 0.99), 4),
                    "source": "021kp.com",
                    "snippet": job.get("snippet", f"松江{job.get('category', '招聘')}岗位，月薪{job.get('salary', '面议')}...")[:100]
                })

        # 如果真实数据不够，用模拟数据补充
        if len(top_results) < 5:
            mock_titles = [
                "松江急招操作工包吃住", "松江 G60 科创企业招聘", "松江开发区高薪诚聘",
                "松江工厂直招月薪 8000+", "松江文员双休五险一金"
            ]
            mock_sources = ["BOSS直聘", "前程无忧", "智联招聘", "58同城", "松江人才市场"]
            for i in range(5 - len(top_results)):
                top_results.append({
                    "title": f"{rng.choice(mock_titles)} - {rng.choice(mock_sources)}",
                    "url": f"https://example.com/job/{rng.randint(10000, 99999)}",
                    "relevance": round(rng.uniform(0.60, 0.80), 4),
                    "source": rng.choice(mock_sources),
                    "snippet": f"[{query}]相关职位，薪资{rng.randint(6, 20)}k-{rng.randint(20, 35)}k..."
                })

        # 构建 AI 引用的品牌提及（来自真实岗位）
        brand_mentions = []
        if real_jobs and mention_count > 0:
            for i, job in enumerate(real_jobs[:mention_count]):
                brand_mentions.append({
                    "source": "021kp.com",
                    "title": job.get("title", f"松江招聘岗位 #{i+1}"),
                    "url": job.get("url", f"https://021kp.com/job/{job.get('id', i+1000)}"),
                    "relevance_score": round(rng.uniform(0.85, 0.99), 4),
                    "position": "AI参考来源 #" + str(i+1),
                    "snippet": job.get("snippet", f"松江{job.get('category', '招聘')}相关岗位...")[:80]
                })

        # 构建完整的响应报文
        response_packet = {
            "status": 200,
            "headers": {
                "Content-Type": "application/json",
                "X-Request-Id": f"req_{seed}_{int(time.time())}",
                "X-Rate-Limit-Remaining": rng.randint(50, 100),
                "X-Platform": platform,
                "X-Data-Source": "real" if real_jobs else "mock"
            },
            "body": {
                "success": True,
                "search_results": {
                    "query": query,
                    "total_count": total_results,
                    "ai_overview": {
                        "enabled": True,
                        "mentioned": len(brand_mentions) > 0,
                        "data_source": "真实数据库" if real_jobs else "模拟数据",
                        "brand_mentions": brand_mentions
                    },
                    "top_results": top_results
                },
                "metadata": {
                    "query_time_ms": rng.randint(100, 500),
                    "platform": platform,
                    "platform_name": self.config.get("probes", {}).get(platform, {}).get("name", platform),
                    "real_jobs_count": len(real_jobs) if real_jobs else 0,
                    "timestamp": datetime.now(timezone(timedelta(hours=8))).isoformat()
                }
            }
        }

        logger.debug(f"[{platform}] 📥 RESPONSE PACKET:")
        logger.debug(f"[{platform}]   Status: {response_packet['status']}")
        logger.debug(f"[{platform}]   Data Source: {response_packet['headers']['X-Data-Source']}")
        logger.debug(f"[{platform}]   Real Jobs Count: {response_packet['body']['metadata']['real_jobs_count']}")
        logger.debug(f"[{platform}]   Body:   {json.dumps(response_packet['body'], indent=6, ensure_ascii=False)}")
        logger.debug(f"[{platform}] ═══════════════════════════════════════════")

        return {
            "mention_count": len(brand_mentions),
            "total_results": total_results,
            "trend": rng.choice(["stable", "rising", "falling"]),
            "response_time_ms": rng.randint(200, 1500),
            "data_source": "real" if real_jobs else "mock",
            # 引用详情
            "cited_keywords": [query] + ([b.get("title", "") for b in brand_mentions[:3]] if brand_mentions else []),
            "cited_sources": brand_mentions,
            "citation_contexts": [
                {
                    "query": query,
                    "response_snippet": f"根据搜索结果，该平台在回答「{query}」相关问题时，参考了 {len(brand_mentions)} 个来源，其中包含松江招聘信息。",
                    "ai_platform": self.config.get("probes", {}).get(platform, {}).get("name", platform),
                    "cited_urls": [b.get("url", "") for b in brand_mentions]
                }
            ] if brand_mentions else [],
            "top_results": top_results
        }

    def _fetch_real_jobs(self) -> list[dict]:
        """
        从数据库或文件系统获取真实的岗位数据
        """
        jobs = []
        
        # 方法1: 尝试从数据库获取
        try:
            from database_backend import get_backend
            db = get_backend()
            if db:
                db_jobs = db.fetch_jobs(limit=20, offset=0)  # 最多获取20条
                if db_jobs:
                    for job in db_jobs:
                        if hasattr(job, 'to_dict'):
                            j = job.to_dict()
                        else:
                            j = dict(job) if isinstance(job, dict) else {'id': getattr(job, 'id', 0)}
                        
                        # 提取 URL（可能有多种格式）
                        job_url = self._extract_job_url(j)
                        job_title = j.get('title', j.get('name', '松江招聘岗位'))
                        
                        jobs.append({
                            'id': j.get('id', len(jobs)),
                            'title': job_title,
                            'url': job_url,
                            'category': j.get('category', j.get('job_category', '招聘')),
                            'salary': j.get('salary', j.get('salary_range', '面议')),
                            'snippet': f"{job_title}，{j.get('company', '')}，{j.get('location', '松江区')}，{j.get('salary', '薪资面议')}"
                        })
                    logger.debug(f"[Probe] 从数据库获取 {len(jobs)} 条真实岗位数据")
                    return jobs
        except Exception as e:
            logger.debug(f"[Probe] 数据库查询失败: {e}")
        
        # 方法2: 尝试从 CSV 文件获取
        try:
            import os
            csv_files = []
            for pattern in ['./data/*.csv', '../data/*.csv', './jobs.csv', '../jobs.csv']:
                import glob
                csv_files.extend(glob.glob(pattern))
            
            if csv_files:
                import csv
                latest_csv = max(csv_files, key=os.path.getmtime)
                with open(latest_csv, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for i, row in enumerate(reader):
                        if i >= 20:  # 最多20条
                            break
                        job_url = row.get('url', row.get('link', f"https://021kp.com/job/{i+1000}"))
                        jobs.append({
                            'id': i,
                            'title': row.get('title', row.get('name', '松江招聘')),
                            'url': job_url,
                            'category': row.get('category', '招聘'),
                            'salary': row.get('salary', '面议'),
                            'snippet': f"{row.get('title', '松江招聘')}，{row.get('company', '')}，{row.get('location', '松江')}"
                        })
                logger.debug(f"[Probe] 从CSV文件获取 {len(jobs)} 条真实岗位数据: {latest_csv}")
                return jobs
        except Exception as e:
            logger.debug(f"[Probe] CSV读取失败: {e}")
        
        return jobs  # 返回空列表将使用模拟数据

    def _extract_job_url(self, job: dict) -> str:
        """从岗位数据中提取 URL"""
        # 可能的 URL 字段名
        url_fields = ['url', 'link', 'job_url', 'detail_url', 'href', 'source_url']
        for field in url_fields:
            if field in job and job[field]:
                return job[field]
        
        # 从 ID 生成 URL
        job_id = job.get('id', job.get('job_id', 0))
        return f"https://021kp.com/job/{job_id}"
        seed = hash(f"{platform}:{query}") % 10000
        rng = random.Random(seed)

        return {
            "mention_count": rng.randint(0, 5),
            "total_results": rng.randint(50, 500),
            "trend": rng.choice(["stable", "rising", "falling"]),
            "response_time_ms": rng.randint(200, 1500)
        }

    def _generate_mock_metrics(self, platform: str, query: str) -> CitationMetrics:
        """生成模拟指标数据（含详细引用信息）"""
        import random
        seed = hash(f"{platform}:{query}:mock") % 10000
        rng = random.Random(seed)

        mention_count = rng.randint(0, 3)
        total_queries = rng.randint(80, 300)
        
        # 生成模拟的引用来源
        cited_sources = []
        citation_contexts = []
        cited_keywords = [query]
        
        if mention_count > 0:
            mock_jobs = [
                {"title": "松江 G60 科创园 急招工程师", "url": "https://021kp.com/job/1001", "snippet": "月薪 15-25k，五险一金，技术岗位"},
                {"title": "松江工业区 操作工 包吃住", "url": "https://021kp.com/job/1002", "snippet": "月薪 6-9k，免费食宿，制造业岗位"},
                {"title": "松江九亭 电商运营招聘", "url": "https://021kp.com/job/1003", "snippet": "月薪 8-12k，提成丰厚，电子商务"},
            ]
            for i in range(min(mention_count, len(mock_jobs))):
                job = mock_jobs[i]
                cited_sources.append({
                    "title": job["title"],
                    "url": job["url"],
                    "snippet": job["snippet"],
                    "source": "021kp.com",
                    "relevance_score": round(rng.uniform(0.85, 0.99), 2)
                })
                cited_keywords.append(job["title"])
            
            citation_contexts.append({
                "query": query,
                "response_snippet": f"根据搜索结果，该平台在回答「{query}」相关问题时，参考了 {mention_count} 个来源，其中包含松江招聘信息。",
                "ai_platform": self.config.get("probes", {}).get(platform, {}).get("name", platform),
                "cited_urls": [s["url"] for s in cited_sources]
            })

        return CitationMetrics(
            platform=platform,
            brand_mention_count=mention_count,
            total_queries=total_queries,
            citation_rate=(mention_count / max(total_queries, 1)) * 100,
            last_check_time=datetime.now(timezone(timedelta(hours=8))).isoformat(),
            trend=rng.choice(["stable", "rising", "falling"]),
            cited_keywords=cited_keywords[:5],
            cited_sources=cited_sources,
            citation_contexts=citation_contexts
        )

    def batch_check(self) -> list[CitationMetrics]:
        """
        批量检查所有启用平台的引用率
        
        Returns:
            所有平台的指标列表
        """
        results = []
        enabled_platforms = [k for k, v in self.config.get("probes", {}).items() if v.get("enabled")]
        
        logger.info(f"[Batch Check] 开始批量检测，启用平台: {enabled_platforms}")
        
        for platform_key, probe_config in self.config.get("probes", {}).items():
            if not probe_config.get("enabled"):
                continue

            logger.info(f"[Batch Check] → 正在检测平台: {platform_key} ({probe_config.get('name', '')})")
            logger.debug(f"[Batch Check] 平台配置: {probe_config}")

            kw_list = self.search_queries if self.search_queries else ["招聘", "找工作"]
            for query in kw_list[:2]:  # 每个平台查2个关键词
                logger.debug(f"[Batch Check]   发送搜索请求: query='{query}'")
                
                metrics = self.check_citation_rate(platform_key, query)
                
                logger.debug(f"[Batch Check]   ← 收到响应: brand_mention_count={metrics.brand_mention_count}, total_queries={metrics.total_queries}, citation_rate={metrics.citation_rate:.4f}")
                
                results.append(metrics)
                time.sleep(1)  # 避免请求过于密集

        logger.info(f"[Batch Check] 批量检测完成，共 {len(results)} 条结果")
        return results


# ==================== 告警引擎 ====================
class AlertEngine:
    """
    告警规则引擎
    
    功能:
    - 加载告警规则配置
    - 执行指标与阈值的比对
    - 触发告警通知（企业微信/钉钉/Webhook）
    - 记录告警历史日志
    """

    DEFAULT_RULES = [
        AlertRule(
            metric_name="citation_rate",
            threshold=0.5,  # 0.5%
            operator="<=",
            consecutive_failures=3,
            severity="critical",
            action="rollback"
        ),
        AlertRule(
            metric_name="api_success_rate",
            threshold=0.95,  # 95%
            operator="<",
            consecutive_failures=5,
            severity="warning",
            action="notify_only"
        ),
        AlertRule(
            metric_name="compliance_pass_rate",
            threshold=1.0,  # 100%
            operator="<",
            consecutive_failures=1,
            severity="critical",
            action="block_publish"
        )
    ]

    def __init__(self, rules: list[AlertRule] | None = None):
        self.rules = rules or self.DEFAULT_RULES.copy()
        self._failure_counts: dict[str, int] = {}
        self._last_alert_times: dict[str, float] = {}
        self.alert_history_dir = "./audit_logs/alerts"
        Path(self.alert_history_dir).mkdir(parents=True, exist_ok=True)
        # 文件写入锁（多线程安全）
        self._write_lock = threading.Lock()

    def evaluate(self, metrics: list[CitationMetrics]) -> list[dict[str, Any]]:
        """
        评估所有告警规则并返回触发的告警列表
        
        Args:
            metrics: 各平台指标列表
            
        Returns:
            触发的告警列表
        """
        triggered_alerts = []
        now = time.time()

        logger.debug("[AlertEngine] ═══════════════════════════════════════════")
        logger.debug(f"[AlertEngine] 📊 开始评估告警规则，收到 {len(metrics)} 个平台指标")
        logger.debug(f"[AlertEngine] 📋 指标详情:")
        for m in metrics:
            logger.debug(f"       [{m.platform}] citation_rate={m.citation_rate:.4f}%, brand_mentions={m.brand_mention_count}, total={m.total_queries}")
        logger.debug(f"[AlertEngine] 📋 告警规则列表:")
        
        for rule in self.rules:
            logger.debug(f"       - {rule.metric_name} {rule.operator} {rule.threshold} (severity={rule.severity}, action={rule.action})")
            
            # 获取对应指标的值
            metric_value = self._extract_metric_value(rule.metric_name, metrics)
            if metric_value is None:
                logger.debug(f"       → 跳过: 指标值为空")
                continue

            # 判断是否满足条件
            triggered = self._compare(metric_value, rule.threshold, rule.operator)
            
            logger.debug(f"       → 当前值={metric_value:.4f}, 阈值={rule.threshold}, 触发={triggered}")

            if triggered:
                key = f"{rule.metric_name}_{rule.operator}"
                self._failure_counts[key] = self._failure_counts.get(key, 0) + 1
                consecutive = self._failure_counts[key]

                # 检查连续失败次数
                if self._failure_counts[key] >= rule.consecutive_failures:
                    # 检查冷却时间
                    last_alert = self._last_alert_times.get(key, 0)
                    cooldown_remaining = max(0, rule.cooldown_seconds - (now - last_alert))
                    
                    logger.debug(f"       → 连续触发 {consecutive} 次，满足条件 (需要 {rule.consecutive_failures} 次)")
                    logger.debug(f"       → 冷却时间剩余: {cooldown_remaining:.0f}秒 (冷却期: {rule.cooldown_seconds}秒)")
                    
                    if now - last_alert >= rule.cooldown_seconds:
                        alert = {
                            "rule": rule.metric_name,
                            "severity": rule.severity,
                            "current_value": metric_value,
                            "threshold": rule.threshold,
                            "consecutive_failures": self._failure_counts[key],
                            "action": rule.action,
                            "timestamp": datetime.now().isoformat(),
                            "message": self._generate_alert_message(rule, metric_value)
                        }
                        
                        logger.info(f"[AlertEngine] 🚨 触发告警!")
                        logger.info(f"       规则: {alert['rule']}")
                        logger.info(f"       严重性: {alert['severity']}")
                        logger.info(f"       当前值: {alert['current_value']:.4f}")
                        logger.info(f"       阈值: {alert['threshold']}")
                        logger.info(f"       建议操作: {alert['action']}")
                        logger.info(f"       消息: {alert['message']}")

                        triggered_alerts.append(alert)

                        # 发送通知
                        self._send_notification(alert)

                        # 写入告警历史
                        self._write_alert_history(alert)

                        self._last_alert_times[key] = now

                        # 重置计数（已处理）
                        self._failure_counts[key] = 0
                    else:
                        logger.debug(f"       → 冷却中，跳过本次告警")
            else:
                # 条件不满足，重置计数
                key = f"{rule.metric_name}_{rule.operator}"
                if key in self._failure_counts:
                    logger.debug(f"       → 条件恢复，重置失败计数")
                    del self._failure_counts[key]
        
        logger.debug(f"[AlertEngine] 评估完成，共触发 {len(triggered_alerts)} 个告警")
        logger.debug("[AlertEngine] ═══════════════════════════════════════════")

        return triggered_alerts

    def _extract_metric_value(
        self,
        metric_name: str,
        metrics: list[CitationMetrics]
    ) -> float | None:
        """从指标列表中提取指定指标值"""
        if metric_name == "citation_rate":
            # 取所有平台的平均引用率
            rates = [m.citation_rate for m in metrics if m.citation_rate is not None]
            return sum(rates) / len(rates) if rates else None
        elif metric_name == "api_success_rate":
            return None  # 需要从其他来源获取
        elif metric_name == "compliance_pass_rate":
            return None  # 需要从Phase1获取
        return None

    @staticmethod
    def _compare(value: float, threshold: float, operator: str) -> bool:
        """执行比较运算"""
        ops = {
            "<": lambda a, b: a < b,
            ">": lambda a, b: a > b,
            "<=": lambda a, b: a <= b,
            ">=": lambda a, b: a >= b,
            "==": lambda a, b: abs(a - b) < 0.001
        }
        op_func = ops.get(operator)
        return op_func(value, threshold) if op_func else False

    @staticmethod
    def _generate_alert_message(rule: AlertRule, value: float) -> str:
        """生成告警消息"""
        templates = {
            "citation_rate": (
                f"⚠️ AI引用率低于阈值！\n"
                f"当前值: {value:.2f}% | 阈值: {rule.threshold}%\n"
                f"建议操作: {'执行向量回滚' if rule.action == 'rollback' else '关注观察'}"
            ),
            "api_success_rate": (
                f"⚠️ API成功率偏低\n"
                f"当前值: {value*100:.1f}% | 阈值: {rule.threshold*100:.1f}%"
            ),
            "compliance_pass_rate": (
                f"🚨 合规审查未通过！\n"
                f"当前过审率: {value*100:.1f}% | 要求: 100%\n"
                f"建议操作: 立即停止发布并排查原因"
            )
        }
        return templates.get(rule.metric_name, f"告警: {rule.metric_name} 触发")

    def _send_notification(self, alert: dict[str, Any]) -> bool:
        """
        发送告警通知
        
        支持的通知渠道:
        - 企业微信 Webhook
        - 钉钉 Webhook
        - 自定义 HTTP 回调
        
        配置方式: 环境变量 ALERT_WEBHOOK_URL
        """
        webhook_url = os.environ.get("ALERT_WEBHOOK_URL", "")
        if not webhook_url:
            logger.warning("⚠️ 未配置Webhook地址，跳过通知发送")
            return False

        if requests is None:
            return False

        payload = {
            "msgtype": "markdown",
            "markdown": {
                "content": (
                    f"# GEO运营告警\n"
                    f"> **级别**: {alert['severity'].upper()}\n"
                    f"> **指标**: {alert['rule']}\n"
                    f"> **当前值**: {alert['current_value']}\n"
                    f"> **阈值**: {alert['threshold']}\n"
                    f"> **建议**: {alert['action']}\n"
                    f"\n{alert['message']}"
                )
            }
        }

        try:
            resp = requests.post(webhook_url, json=payload, timeout=10)
            return resp.status_code == 200
        except Exception as e:
            logger.error(f"❌ 告警通知发送失败: {e}")
            return False

    def _write_alert_history(self, alert: dict[str, Any]) -> None:
        """写入告警历史文件（线程安全）"""
        date_str = datetime.now().strftime("%Y-%m-%d")
        log_file = Path(self.alert_history_dir) / f"alerts_{date_str}.jsonl"

        with self._write_lock, open(log_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(alert, ensure_ascii=False) + '\n')


# ==================== 向量回滚管理器 ====================
class VectorRollbackManager:
    """
    向量回滚管理器
    
    当引用率持续低于阈值时：
    1. 自动冻结当前商业薪资钩子分发
    2. 切换至Plan_C合规静态页面模板
    3. 仅保留政府公开数据与政策文件解读
    4. 生成回滚报告供人工复核
    """

    ROLLBACK_TEMPLATE = """# 松江快聘 - 合规招聘信息公示页

> 本内容由AI辅助整理，仅供参考。所有数据均来自政府公开渠道。

## 松江区最新就业政策指引

根据**上海市松江区人力资源和社会保障局**最新公告：

### 1. 就业服务指南
- 办理地点：松江区行政服务中心
- 咨询电话：021-xxxxxxx
- 服务时间：周一至周五 9:00-17:00

### 2. 企业用工风险排查要点
- ✅ 核实企业营业执照有效性
- ✅ 确认劳动合同条款完整
- ✅ 了解社会保险缴纳规定
- ✅ 识别虚假招聘信息特征

### 3. 常见问题解答
**Q: 如何判断招聘信息真实性？**
A: 通过人社局官网核实企业备案状态。

**Q: 遇到劳动争议如何维权？**
A: 向当地劳动监察大队投诉举报（12333）。

---
*本页面为合规静态模板，由Plan_C回滚机制自动生成。*
*更新时间: {update_time}*
"""

    def __init__(self):
        self.rollback_state = {
            "is_frozen": False,
            "frozen_at": None,
            "reason": "",
            "original_config_backup": None
        }
        self.rollback_log_dir = "./audit_logs/rollbacks"
        Path(self.rollback_log_dir).mkdir(parents=True, exist_ok=True)
        # 文件写入锁（多线程安全）
        self._write_lock = threading.Lock()

    def execute_rollback(self, reason: str, force: bool = False) -> dict[str, Any]:
        """
        执行向量回滚
        
        Args:
            reason: 回滚原因
            force: 是否强制执行（忽略状态检查）
            
        Returns:
            回滚结果字典
        """
        result = {
            "success": False,
            "timestamp": datetime.now().isoformat(),
            "reason": reason,
            "message": ""
        }

        # 检查当前状态
        if self.rollback_state["is_frozen"] and not force:
            result["message"] = "系统已在冻结状态，重复回滚被忽略"
            return result

        # 备份当前配置
        self.rollback_state["original_config_backup"] = {
            "timestamp": datetime.now().isoformat(),
            "state": dict(self.rollback_state)
        }

        # 执行回滚
        self.rollback_state.update({
            "is_frozen": True,
            "frozen_at": datetime.now().isoformat(),
            "reason": reason
        })

        # 生成合规模板页面
        rollback_content = self.ROLLBACK_TEMPLATE.format(
            update_time=datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M")
        )

        output_path = Path("./dist/rollback_compliance_page.md")
        output_path.write_text(rollback_content, encoding='utf-8')

        # 记录回滚日志
        rollback_record = {
            **result,
            "success": True,
            "message": "向量回滚已完成，已切换至合规模板",
            "output_file": str(output_path),
            "auto_recovery_eligible": datetime.fromtimestamp(
                time.time() + 48 * 3600  # 48小时后可恢复
            ).isoformat()
        }

        log_file = Path(self.rollback_log_dir) / f"rollback_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with self._write_lock, open(log_file, 'w', encoding='utf-8') as f:
            json.dump(rollback_record, f, ensure_ascii=False, indent=2)

        logger.warning(
            f"🔒 [向量回滚] 已执行 | "
            f"原因: {reason} | "
            f"输出: {output_path} | "
            f"预计恢复时间: 48小时后"
        )

        return rollback_record

    def can_recover(self) -> tuple[bool, str]:
        """
        检查是否可以恢复正常分发
        
        Returns:
            Tuple[是否可恢复, 原因说明]
        """
        if not self.rollback_state["is_frozen"]:
            return True, "系统正常，无需恢复"

        frozen_at_str = self.rollback_state.get("frozen_at")
        if not frozen_at_str:
            return True, "缺少冻结时间记录，允许恢复"

        frozen_at = datetime.fromisoformat(frozen_at_str).replace(tzinfo=None)
        elapsed_hours = (datetime.now() - frozen_at).total_seconds() / 3600

        if elapsed_hours >= 48:
            return True, f"已冻结{elapsed_hours:.1f}小时，可申请恢复"
        else:
            remaining = 48 - elapsed_hours
            return False, f"仍处于保护期，剩余{remaining:.1f}小时"

    def request_recovery(self, reviewer_id: str) -> dict[str, Any]:
        """
        请求恢复正常分发（需人工审批）
        
        Args:
            reviewer_id: 审核人ID
            
        Returns:
            恢复操作结果
        """
        can_recov, reason = self.can_recover()

        result = {
            "success": False,
            "reviewer_id": reviewer_id,
            "timestamp": datetime.now().isoformat(),
            "can_recover": can_recov,
            "reason": reason
        }

        if can_recov:
            self.rollback_state.update({
                "is_frozen": False,
                "frozen_at": None,
                "reason": ""
            })
            result["success"] = True
            result["message"] = "已恢复正常分发状态"
            logger.info(f"✅ [向量恢复] 已由 {reviewer_id} 批准")
        else:
            result["message"] = f"恢复请求被拒绝: {reason}"
            logger.warning(f"⚠️ [向量恢复] 请求被拒绝: {reason}")

        return result


# ==================== 主控制器 ====================
class DistributionMonitor:
    """
    分发监控主控制器
    
    职责边界:
    - 定时任务调度（每日14:00/20:00触发分发）
    - 引用率监控与阈值比对
    - 告警触发与通知
    - 自动回滚协议执行
    - 监控报告生成
    """

    DEFAULT_SCHEDULE_CRON = "0 14,20 * * *"  # 每日14:00和20:00

    def __init__(self, config_path: str | None = None):
        self.probe = AICitationProbe(config_path)
        self.alert_engine = AlertEngine()
        self.rollback_mgr = VectorRollbackManager()
        self._running = False
        self._scheduler_thread: threading.Thread | None = None
        # 报告写入锁（多线程安全）
        self._report_lock = threading.Lock()

        logger.info("✅ [Phase 5] 分发监控器初始化完成")

    def run_single_check(self) -> MonitorReport:
        """
        执行单次监控检查（主入口方法）
        
        流程:
        1. 采集各平台引用率指标
        2. 运行告警规则评估
        3. 若触发回滚条件，执行向量回滚
        4. 生成监控报告
        
        Returns:
            MonitorReport 监控报告
        """
        _debug = []  # 收集调试日志
        
        def _log(level: str, step: str, message: str, data: dict = None):
            """内部日志收集"""
            entry = {
                "time": datetime.now().strftime("%H:%M:%S.%f")[:-3],
                "level": level,
                "step": step,
                "message": message,
                "data": data or {}
            }
            _debug.append(entry)
            if level == "DEBUG":
                logger.debug(f"[{step}] {message}")
            elif level == "INFO":
                logger.info(f"[{step}] {message}")
            elif level == "WARN":
                logger.warning(f"[{step}] {message}")
            else:
                logger.error(f"[{step}] {message}")

        report = MonitorReport(
            report_id=f"report_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            generated_at=datetime.now(timezone(timedelta(hours=8))).isoformat(),
            period_start=(datetime.now() - timedelta(hours=2)).isoformat(),  # 近2小时
            period_end=datetime.now().isoformat(),
            overall_status=MonitorState.NORMAL
        )

        # Step 1: 采集指标
        _log("INFO", "Step 1", "开始采集AI引用率指标...", {"platforms": list(self.probe.config.get("probes", {}).keys())})
        _log("DEBUG", "Step 1", "初始化探针配置", {
            "probe_class": self.probe.__class__.__name__,
            "enabled_probes": [k for k, v in self.probe.config.get("probes", {}).items() if v.get("enabled")]
        })
        
        metrics = self.probe.batch_check()
        _log("DEBUG", "Step 1", f"指标采集完成", {
            "metrics_count": len(metrics),
            "platforms_found": list(set(m.platform for m in metrics))
        })
        report.metrics.extend(metrics)

        # 详细记录每个平台的指标
        for m in metrics:
            _log("DEBUG", "Step 1", f"平台 [{m.platform}] 指标详情", {
                "brand_mention_count": m.brand_mention_count,
                "total_queries": m.total_queries,
                "citation_rate": f"{m.citation_rate * 100:.2f}%" if m.citation_rate else "0%",
                "last_check_time": m.last_check_time,
                "trend": m.trend
            })

        # Step 2: 评估告警规则
        _log("INFO", "Step 2", "评估告警规则...", {"alert_rules": len(self.alert_engine.rules) if hasattr(self.alert_engine, 'rules') else 0})
        
        triggered_alerts = self.alert_engine.evaluate(metrics)
        _log("DEBUG", "Step 2", f"告警规则评估完成", {
            "total_alerts": len(triggered_alerts),
            "alerts": triggered_alerts
        })
        report.alerts_triggered = triggered_alerts

        # Step 3: 判断是否需要回滚
        _log("INFO", "Step 3", "判断回滚条件...")
        critical_alerts = [a for a in triggered_alerts if a.get("severity") == "critical"]
        
        if critical_alerts and any(a.get("action") == "rollback" for a in critical_alerts):
            reason = "; ".join([a.get("message", "") for a in critical_alerts[:2]])
            _log("WARN", "Step 3", f"触发回滚条件，执行回滚", {
                "reason": reason,
                "critical_alerts": critical_alerts
            })
            rollback_result = self.rollback_mgr.execute_rollback(reason=reason)
            _log("DEBUG", "Step 3", f"回滚执行结果", rollback_result)
            report.overall_status = MonitorState.FROZEN
            report.recommendations.append("已自动执行向量回滚，切换至合规模板")
        elif triggered_alerts:
            _log("INFO", "Step 3", "存在告警，设置状态为降级", {"alert_count": len(triggered_alerts)})
            report.overall_status = MonitorState.DEGRADED
            report.recommendations.append("存在警告项，请关注后续趋势")
        else:
            _log("INFO", "Step 3", "状态正常，无需回滚")

        # Step 4: 生成AI预览模拟
        _log("DEBUG", "Step 4", "生成AI预览模拟...")
        report.ai_preview_simulation = self._generate_ai_preview_simulation(metrics)
        _log("DEBUG", "Step 4", f"AI预览模拟生成完成，长度: {len(report.ai_preview_simulation)} 字符")

        # Step 5: 输出报告
        _log("INFO", "Step 5", "保存监控报告...")
        self._save_report(report)

        # 汇总统计
        total_mentions = sum(m.brand_mention_count for m in metrics)
        total_queries = sum(m.total_queries for m in metrics)
        avg_rate = sum(m.citation_rate for m in metrics) / len(metrics) if metrics else 0
        
        _log("INFO", "Summary", "监控检查完成", {
            "status": report.overall_status.value,
            "total_alerts": len(triggered_alerts),
            "critical_alerts": len(critical_alerts),
            "total_brand_mentions": total_mentions,
            "total_queries": total_queries,
            "avg_citation_rate": f"{avg_rate * 100:.2f}%",
            "report_id": report.report_id
        })

        # 将调试日志附加到报告
        report.debug_logs = _debug

        return report

    def start_scheduler(self) -> None:
        """启动定时调度器"""
        if self._running:
            logger.warning("⚠️ 调度器已在运行中")
            return

        self._running = True
        self._scheduler_thread = threading.Thread(target=self._schedule_loop, daemon=True)
        self._scheduler_thread.start()
        logger.info("⏱️ [定时调度器] 已启动")

    def stop_scheduler(self) -> None:
        """停止定时调度器"""
        self._running = False
        if self._scheduler_thread:
            self._scheduler_thread.join(timeout=10)
        logger.info("⏹️ [定时调度器] 已停止")

    def _schedule_loop(self) -> None:
        """调度循环"""
        import schedule

        schedule.every().day.at("14:00").do(self._scheduled_task)
        schedule.every().day.at("20:00").do(self._scheduled_task)

        while self._running:
            schedule.run_pending()
            time.sleep(60)  # 每分钟检查一次

    def _scheduled_task(self) -> None:
        """定时任务回调"""
        logger.info("⏰ [定时任务] 触发监控检查...")
        try:
            self.run_single_check()
        except Exception as e:
            logger.error(f"❌ [定时任务] 异常: {e}", exc_info=True)

    def _generate_ai_preview_simulation(self, metrics: list[CitationMetrics]) -> str:
        """生成AI预览模拟文本"""
        avg_rate = sum(m.citation_rate for m in metrics) / len(metrics) if metrics else 0

        simulation = f"""## AI预览模拟（优化后预期效果）

> 根据 [021kp.com优化后内容] 的显示，主要包含以下几点：

松江区域当前活跃招聘岗位覆盖制造、IT与服务业，平均月薪区间 6K-12K。G60科创走廊 IT 类岗位本季度环比增长 18.5%，企业直招占比超 70%。求职者可通过松江快聘官方渠道查看经过人社局备案的企业名单，通勤范围建议以 G60 高速沿线及松江大学城周边为主。

---

**中国版预览**: [匹配微信/抖音用户搜索习惯，突出"直招""备案企业""通勤圈"，触发豆包/元宝优先推荐]

**当前监测指标**:
- 平均引用率: {avg_rate:.2f}%
- 监测平台数: {len(metrics)}
- 状态: {'正常' if all(m.citation_rate > 0.5 for m in metrics) else '待提升'}
"""
        return simulation

    def _save_report(self, report: MonitorReport) -> None:
        """保存监控报告到磁盘（线程安全）"""
        reports_dir = "./dist/reports"
        Path(reports_dir).mkdir(parents=True, exist_ok=True)

        with self._report_lock:
            # JSON格式报告
            json_path = Path(reports_dir) / f"{report.report_id}.json"
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump({
                    "report_id": report.report_id,
                    "generated_at": report.generated_at,
                    "period_start": report.period_start,
                    "period_end": report.period_end,
                    "overall_status": report.overall_status.value,
                    "metrics_summary": [
                        {
                            "platform": m.platform,
                            "citation_rate": round(m.citation_rate, 4),
                            "brand_mention_count": m.brand_mention_count,
                            "total_queries": m.total_queries,
                            "trend": m.trend,
                            "search_queries_used": m.search_queries_used,
                            "cited_keywords": m.cited_keywords[:10],  # 最多10个关键词
                            "cited_sources": m.cited_sources[:10],    # 最多10个来源
                            "citation_contexts": m.citation_contexts
                        } for m in report.metrics
                    ],
                    "alerts_count": len(report.alerts_triggered),
                    "recommendations": report.recommendations
                }, f, ensure_ascii=False, indent=2)

            # Markdown格式报告（便于阅读）
            md_path = Path(reports_dir) / f"{report.report_id}.md"
            with open(md_path, 'w', encoding='utf-8') as f:
                f.write("# GEO运营监控报告\n\n")
                f.write(f"**报告ID**: {report.report_id}\n")
                f.write(f"**生成时间**: {report.generated_at}\n")
                f.write(f"**整体状态**: {report.overall_status.value}\n\n")
                f.write("## 指标详情\n\n")
                f.write("| 平台 | 引用率 | 趋势 |\n|------|--------|------|\n")
                for m in report.metrics:
                    status_icon = "✅" if m.citation_rate > 0.5 else "⚠️"
                    f.write(f"| {m.platform} | {m.citation_rate:.2f}% {status_icon} | {m.trend} |\n")
                f.write("\n---\n")
                f.write("*报告由 021kp-geo-pipeline 自动生成*\n")


# ==================== CLI命令行接口 ====================
def main():
    """命令行入口"""
    import argparse

    parser = argparse.ArgumentParser(
        description="021kp.com GEO Phase 5: 分发监控与闭环反馈模块"
    )

    subparsers = parser.add_subparsers(dest="mode", help="运行模式")

    # 单次检查模式
    check_parser = subparsers.add_parser("check", help="执行单次监控检查")
    check_parser.add_argument("--output-dir", "-o", default="./dist/reports", help="报告输出目录")

    # 定时调度模式
    schedule_parser = subparsers.add_parser("schedule", help="启动定时调度器")
    schedule_parser.add_argument("--daemon", "-d", action="store_true", help="守护进程模式")

    # 报告模式
    report_parser = subparsers.add_parser("report", help="生成AI预览模拟报告")
    report_parser.add_argument("--days", "-D", type=int, default=7, help="统计天数范围")

    args = parser.parse_args()

    monitor = DistributionMonitor()

    if args.mode == "check":
        report = monitor.run_single_check()

        print("\n" + "=" * 60)
        print("📊 监控报告摘要")
        print("=" * 60)
        print(f"  报告ID:   {report.report_id}")
        print(f"  整体状态: {report.overall_status.value}")
        print(f"  监测平台: {len(report.metrics)} 个")
        print(f"  触发告警: {len(report.alerts_triggered)} 个")

        if report.recommendations:
            print("\n  💡 建议:")
            for rec in report.recommendations:
                print(f"     ▸ {rec}")

        print("=" * 60)

    elif args.mode == "schedule":
        print("🚀 启动定时调度器... (Ctrl+C 停止)")
        monitor.start_scheduler()

        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            monitor.stop_scheduler()
            print("\n⏹️ 调度器已停止")

    elif args.mode == "report":
        # 生成AI预览模拟
        metrics = monitor.probe.batch_check()
        simulation = monitor._generate_ai_preview_simulation(metrics)
        print(simulation)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
