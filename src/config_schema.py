# -*- coding: utf-8 -*-
"""
GEO Pipeline - 动态配置 Schema 定义
=============================================================

定义所有可通过 Web UI 动态修改的配置项及其元数据。
每个配置项包含: 类型/默认值/验证规则/分组/UI标签/帮助文本。

设计原则:
    - 零依赖启动: 所有配置项有合理默认值，无需任何配置文件即可运行
    - 分层权限: 敏感项(API密钥)标记为 secret，前端做掩码显示
    - 实时生效: 非敏感项修改后立即生效(无需重启)，敏感项提示需重启
    - 输入验证: 前后端双重校验，防止非法值导致崩溃

Author: GEO-Engine Team | Version: v2.1 | Date: 2026-04-21
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union
from enum import Enum


class ConfigType(str, Enum):
    """配置字段类型（对应前端输入控件）"""
    STRING = "string"           # 文本输入框
    PASSWORD = "password"       # 密码框 (掩码显示)
    NUMBER = "number"           # 数字输入框
    SELECT = "select"           # 下拉选择框
    TOGGLE = "toggle"           # 开关切换
    TEXTAREA = "textarea"        # 多行文本
    JSON_EDITOR = "json"         # JSON 编辑器
    PATH = "path"               # 路径选择器
    ACTION = "action"            # 操作按钮


class ConfigGroup(str, Enum):
    """配置分组（对应前端 Tab 页）"""
    SITE = "site"               # 站点基本信息
    CONTENT = "content"          # 内容生成参数
    COMPLIANCE = "compliance"     # 合规闸门
    PLATFORM_WECHAT = "wechat"    # 微信平台
    PLATFORM_DOUYIN = "douyin"   # 抖音平台
    PLATFORM_BAIDU = "baidu"     # 百度平台
    DATABASE = "database"        # 数据库连接
    MONITORING = "monitoring"    # 监控与告警
    SCHEDULER = "scheduler"      # 定时任务
    ADVANCED = "advanced"        # 高级选项


@dataclass
class ConfigFieldDef:
    """
    单个配置字段的完整定义
    
    Attributes:
        key: 配置键路径 (如 'site.name', 'content.tldr_max_length')
        label: 显示名称 (中文)
        type_: 字段类型 (ConfigType 枚举)
        default: 默认值
        group: 所属分组 (ConfigGroup 枚举)
        description: 帮助说明文字
        placeholder: 输入框占位提示
        options: 选项列表 (SELECT/Toggle 类型使用)
        validation: 验证规则 {'min', 'max', 'pattern', 'required'}
        is_secret: 是否为敏感信息 (API 返回时脱敏显示)
        requires_restart: 修改后是否需要重启服务才生效
        order: 在同组内的排序序号 (越小越靠前)
    """
    key: str
    label: str
    type_: ConfigType
    default: Any
    group: ConfigGroup
    description: str = ""
    placeholder: str = ""
    options: Optional[List[Dict[str, Any]]] = None
    validation: Dict[str, Any] = field(default_factory=dict)
    is_secret: bool = False
    requires_restart: bool = False
    order: int = 0


# ================================================================
#   配置 Schema 定义（所有可动态配置的项）
# ================================================================

CONFIG_SCHEMA: List[ConfigFieldDef] = [
    # ==================== 站点基本信息 ====================
    ConfigFieldDef(
        key="site.name", label="站点名称", type_=ConfigType.STRING,
        default="松江快聘网", group=ConfigGroup.SITE,
        description="网站/品牌名称，用于生成内容的标题和署名",
        placeholder="例: 松江快聘网", order=1,
    ),
    ConfigFieldDef(
        key="site.url", label="站点 URL", type_=ConfigType.STRING,
        default="https://www.021kp.com", group=ConfigGroup.SITE,
        description="主站域名，用于 Schema.org 引用和 sitemap",
        placeholder="https://www.example.com", order=2,
        validation={"pattern": r"^https?://[\w\.-]+"},
    ),
    ConfigFieldDef(
        key="site.default_org_name", label="默认企业名称", type_=ConfigType.STRING,
        default="松江快聘合作企业", group=ConfigGroup.SITE,
        description="未指定公司时使用的默认组织名",
        placeholder="例: 上海XX科技有限公司", order=3,
    ),
    ConfigFieldDef(
        key="site.region", label="目标区域", type_=ConfigType.STRING,
        default="松江区", group=ConfigGroup.SITE,
        description="GEO 目标地理区域（用于 LBS 标注和内容生成）",
        placeholder="例: 松江区 / 浦东新区", order=4,
    ),
    ConfigFieldDef(
        key="site.city", label="所在城市", type_=ConfigType.STRING,
        default="上海市", group=ConfigGroup.SITE,
        description="站点所在城市（用于地址结构化数据）",
        placeholder="例: 上海市", order=5,
    ),

    # ==================== 内容工厂 ====================
    ConfigFieldDef(
        key="content.tldr_max_length", label="TL;DR 摘要长度", type_=ConfigType.NUMBER,
        default=120, group=ConfigGroup.CONTENT,
        description="首屏摘要的最大字符数（建议 80-200，影响 SEO 展示效果）",
        placeholder="120", order=1,
        validation={"min": 50, "max": 500},
    ),
    ConfigFieldDef(
        key="content.data_anchor_density", label="数据锚点密度", type_=ConfigType.NUMBER,
        default=3, group=ConfigGroup.CONTENT,
        description="每千字生成的引用钩子数量（0=禁用，5=密集引用）",
        placeholder="3", order=2,
        validation={"min": 0, "max": 10},
    ),
    ConfigFieldDef(
        key="content.valid_through_days", label="岗位有效期(天)", type_=ConfigType.NUMBER,
        default=90, group=ConfigGroup.CONTENT,
        description="Schema.org validThrough 距当前的天数（30-365）",
        placeholder="90", order=3,
        validation={"min": 7, "max": 365},
    ),
    ConfigFieldDef(
        key="content.schema_type", label="Schema 类型", type_=ConfigType.SELECT,
        default="JobPosting", group=ConfigGroup.CONTENT,
        description="结构化数据的 Schema.org 类型",
        options=[
            {"value": "JobPosting", "label": "JobPosting (招聘)"},
            {"value": "Article", "label": "Article (文章)"},
            {"value": "WebPage", "label": "WebPage (网页)"},
            {"value": "Event", "label": "Event (活动)"},
        ],
        order=4,
    ),
    ConfigFieldDef(
        key="content.output_dir", label="输出目录", type_=ConfigType.PATH,
        default="./dist", group=ConfigGroup.CONTENT,
        description="生成资产的输出根目录",
        placeholder="./dist", order=5,
    ),

    # ==================== 合规闸门 ====================
    ConfigFieldDef(
        key="compliance.fail_threshold", label="禁词 FAIL 阈值", type_=ConfigType.NUMBER,
        default=5, group=ConfigGroup.COMPLIANCE,
        description="命中禁词数量超过此值时判定为 FAIL（阻止发布）",
        placeholder="5", order=1,
        validation={"min": 1, "max": 20},
    ),
    ConfigFieldDef(
        key="compliance.hash_length", label="资产哈希长度", type_=ConfigType.NUMBER,
        default=16, group=ConfigGroup.COMPLIANCE,
        description="内容哈希的截取字符数（8-64，越长越唯一但存储开销越大）",
        placeholder="16", order=2,
        validation={"min": 8, "max": 64},
    ),
    ConfigFieldDef(
        key="compliance.audit_retention_days", label="审计日志保留天数", type_=ConfigType.NUMBER,
        default=180, group=ConfigGroup.COMPLIANCE,
        description="审计日志自动清理前的保留天数",
        placeholder="180", order=3,
        validation={"min": 7, "max": 720},
    ),
    ConfigFieldDef(
        key="compliance.explicit_marker", label="AI 显式标识文案", type_=ConfigType.TEXTAREA,
        default="AI辅助生成标识: 本内容由AI整理，仅供参考",
        group=ConfigGroup.COMPLIANCE,
        description="注入到每条内容中的 AI 生成标识文本（符合《深度合成规定》）",
        placeholder="AI辅助生成标识...", order=4,
    ),

    # ==================== 微信平台 ====================
    ConfigFieldDef(
        key="platform.wechat.app_id", label="AppID", type_=ConfigType.STRING,
        default="", group=ConfigGroup.PLATFORM_WECHAT,
        description="微信公众号/小程序的 AppID",
        placeholder="wx 开头的 AppID", order=1,
        is_secret=True, requires_restart=True,
    ),
    ConfigFieldDef(
        key="platform.wechat.app_secret", label="AppSecret", type_=ConfigType.PASSWORD,
        default="", group=ConfigGroup.PLATFORM_WECHAT,
        description="微信公众号 AppSecret（⚠️ 敏感信息）",
        placeholder="请输入 AppSecret", order=2,
        is_secret=True, requires_restart=True,
    ),
    ConfigFieldDef(
        key="platform.wechat.template_id", label="模板消息 ID", type_=ConfigType.STRING,
        default="", group=ConfigGroup.PLATFORM_WECHAT,
        description="模板消息的 template_id（用于推送通知）",
        placeholder="消息模板 ID", order=3,
    ),
    ConfigFieldDef(
        key="platform.wechat.push_title_suffix", label="推送标题后缀", type_=ConfigType.STRING,
        default="【松江招聘】", group=ConfigGroup.PLATFORM_WECHAT,
        description="微信推送消息标题的后缀文字",
        placeholder="【区域+类型】", order=4,
    ),
    ConfigFieldDef(
        key="platform.wechat.max_push_per_day", label="每日最大推送量", type_=ConfigType.NUMBER,
        default=10, group=ConfigGroup.PLATFORM_WECHAT,
        description="每日向微信推送的最大条数限制（防频率封禁）",
        placeholder="10", order=5,
        validation={"min": 1, "max": 100},
    ),

    # ==================== 抖音平台 ====================
    ConfigFieldDef(
        key="platform.douyin.client_key", label="Client Key", type_=ConfigType.STRING,
        default="", group=ConfigGroup.PLATFORM_DOUYIN,
        description="抖音开放平台的 Client Key",
        placeholder="aw 开头的 Client Key", order=1,
        is_secret=True, requires_restart=True,
    ),
    ConfigFieldDef(
        key="platform.douyin.client_secret", label="Client Secret", type_=ConfigType.PASSWORD,
        default="", group=ConfigGroup.PLATFORM_DOUYIN,
        description="抖音 Client Secret（⚠️ 敏感信息）",
        placeholder="请输入 Client Secret", order=2,
        is_secret=True, requires_restart=True,
    ),
    ConfigFieldDef(
        key="platform.douyin.max_push_per_day", label="每日最大推送量", type_=ConfigType.NUMBER,
        default=15, group=ConfigGroup.PLATFORM_DOUYIN,
        description="每日向抖音发布的最大条数",
        placeholder="15", order=3,
        validation={"min": 1, "max": 100},
    ),

    # ==================== 百度平台 ====================
    ConfigFieldDef(
        key="platform.baidu.api_key", label="API Key", type_=ConfigType.STRING,
        default="", group=ConfigGroup.PLATFORM_BAIDU,
        description="百度资源平台的 API Key（站长工具）",
        placeholder="百度 API Key", order=1,
        is_secret=True, requires_restart=True,
    ),
    ConfigFieldDef(
        key="platform.baidu.site_token", label="站点验证 Token", type_=ConfigType.STRING,
        default="", group=ConfigGroup.PLATFORM_BAIDU,
        description="百度站长平台验证用的 site_token",
        placeholder="站点验证 Token", order=2,
        is_secret=True,
    ),
    ConfigFieldDef(
        key="platform.baidu.max_push_per_day", label="每日最大推送量", type_=ConfigType.NUMBER,
        default=50, group=ConfigGroup.PLATFORM_BAIDU,
        description="每日推送到百度的最大条数（sitemap ping）",
        placeholder="50", order=3,
        validation={"min": 1, "max": 500},
    ),

    # ==================== 数据库 ====================
    ConfigFieldDef(
        key="database.db_type", label="数据库类型", type_=ConfigType.SELECT,
        default="sqlite", group=ConfigGroup.DATABASE,
        description="数据库引擎类型 (当前固定为SQLite)",
        options=[
            {"value": "sqlite", "label": "SQLite (本地文件)"},
        ],
        order=1, requires_restart=True,
    ),
    ConfigFieldDef(
        key="database.host", label="主机地址", type_=ConfigType.STRING,
        default="localhost", group=ConfigGroup.DATABASE,
        description="数据库服务器地址（SQLite 模式忽略此项）",
        placeholder="localhost 或 IP 地址", order=2, requires_restart=True,
    ),
    ConfigFieldDef(
        key="database.port", label="端口", type_=ConfigType.NUMBER,
        default=3306, group=ConfigGroup.DATABASE,
        description="(已弃用，保留用于兼容)",
        placeholder="3306", order=3,
        validation={"min": 1, "max": 65535},
    ),
    ConfigFieldDef(
        key="database.user", label="用户名", type_=ConfigType.STRING,
        default="root", group=ConfigGroup.DATABASE,
        description="数据库用户名（建议使用只读账号）",
        placeholder="root", order=4, requires_restart=True,
    ),
    ConfigFieldDef(
        key="database.password", label="密码", type_=ConfigType.PASSWORD,
        default="", group=ConfigGroup.DATABASE,
        description="数据库密码（⚠️ 敏感信息）",
        placeholder="数据库密码", order=5,
        is_secret=True, requires_restart=True,
    ),
    ConfigFieldDef(
        key="database.database", label="数据库名", type_=ConfigType.STRING,
        default="geo_pipeline", group=ConfigGroup.DATABASE,
        description="数据库名称",
        placeholder="geo_pipeline", order=6, requires_restart=True,
    ),

    # ==================== 监控与告警 ====================
    ConfigFieldDef(
        key="monitoring.enabled", label="启用监控", type_=ConfigType.TOGGLE,
        default=True, group=ConfigGroup.MONITORING,
        description="是否启用 Phase 5 分发监控模块",
        order=1,
    ),
    ConfigFieldDef(
        key="monitoring.citation_threshold", label="引用率阈值", type_=ConfigType.NUMBER,
        default=0.005, group=ConfigGroup.MONITORING,
        description="引用率低于此值触发告警（0.005 = 0.5%）",
        placeholder="0.005", order=2,
        validation={"min": 0.001, "max": 0.1},
    ),
    ConfigFieldDef(
        key="monitoring.api_success_threshold", label="API 成功率阈值", type_=ConfigType.NUMBER,
        default=0.95, group=ConfigGroup.MONITORING,
        description="平台 API 成功率低于此值告警",
        placeholder="0.95", order=3,
        validation={"min": 0.5, "max": 1.0},
    ),
    ConfigFieldDef(
        key="monitoring.monitor_interval_hours", label="监控间隔(小时)", type_=ConfigType.NUMBER,
        default=2, group=ConfigGroup.MONITORING,
        description="监控检查的间隔小时数",
        placeholder="2", order=4,
        validation={"min": 1, "max": 24},
    ),
    ConfigFieldDef(
        key="monitoring.alert_webhook", label="告警 Webhook URL", type_=ConfigType.STRING,
        default="", group=ConfigGroup.MONITORING,
        description="企业微信群机器人 Webhook 地址（留空则不推送）",
        placeholder="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx",
        order=5, is_secret=True,
    ),
    ConfigFieldDef(
        key="monitoring.rollback_failures", label="回滚连续失败次数", type_=ConfigType.NUMBER,
        default=3, group=ConfigGroup.MONITORING,
        description="连续 N 次严重告警后自动执行回滚",
        placeholder="3", order=6,
        validation={"min": 1, "max": 10},
    ),
    ConfigFieldDef(
        key="monitoring.rollback_freeze_hours", label="冻结时长(小时)", type_=ConfigType.NUMBER,
        default=48, group=ConfigGroup.MONITORING,
        description="回滚后系统冻结的时间（期间停止分发新内容）",
        placeholder="48", order=7,
        validation={"min": 1, "max": 168},
    ),

    # ==================== 定时任务 ====================
    ConfigFieldDef(
        key="scheduler.pipeline_cron", label="流水线 Cron 表达式", type_=ConfigType.STRING,
        default="0 14 * * *", group=ConfigGroup.SCHEDULER,
        description="GEO 流水线自动执行时间（Cron 格式）",
        placeholder='0 14 * * * (每天14点)', order=1,
        validation={"pattern": r"^(\S+\s+\S+\s+\*\s+\*\*|\S+\s+\S+\s+\S+\s+\*\s+\*)$"},
    ),
    ConfigFieldDef(
        key="scheduler.monitor_cron", label="监控检查 Cron 表达式", type_=ConfigType.STRING,
        default="0 20 * * *", group=ConfigGroup.SCHEDULER,
        description="监控检查自动执行时间",
        placeholder='0 20 * * * (每天20点)', order=2,
        validation={"pattern": r"^(\S+\s+\S+\s+\*\s+\*\*|\S+\s+\S+\s+\S+\s+\*\s+\*)$"},
    ),
    ConfigFieldDef(
        key="scheduler.health_check_interval", label="健康检查间隔(小时)", type_=ConfigType.NUMBER,
        default=6, group=ConfigGroup.SCHEDULER,
        description="API 健康探针检查间隔",
        placeholder="6", order=3,
        validation={"min": 1, "max": 24},
    ),

    # ==================== Advanced Options ====================
    ConfigFieldDef(
        key="advanced.log_level", label="Log Level", type_=ConfigType.SELECT,
        default="INFO", group=ConfigGroup.ADVANCED,
        description="Log verbosity level",
        options=[
            {"value": "DEBUG", "label": "DEBUG (verbose)"},
            {"value": "INFO", "label": "INFO (recommended)"},
            {"value": "WARNING", "label": "WARNING (warnings+errors)"},
            {"value": "ERROR", "label": "ERROR (errors only)"},
        ],
        order=1,
    ),
    ConfigFieldDef(
        key="advanced.rate_limit_rpm", label="Rate Limit (req/min)", type_=ConfigType.NUMBER,
        default=30, group=ConfigGroup.ADVANCED,
        description="Max requests per minute per IP",
        placeholder="30", order=2,
        validation={"min": 5, "max": 300},
    ),
    ConfigFieldDef(
        key="advanced.circuit_breaker_threshold", label="Circuit Breaker Threshold", type_=ConfigType.NUMBER,
        default=3, group=ConfigGroup.ADVANCED,
        description="Consecutive failures before triggering circuit breaker",
        placeholder="3", order=3,
        validation={"min": 1, "max": 20},
    ),
    ConfigFieldDef(
        key="advanced.circuit_breaker_reset_hours", label="Circuit Breaker Reset (hours)", type_=ConfigType.NUMBER,
        default=24, group=ConfigGroup.ADVANCED,
        description="Hours before attempting recovery after circuit break",
        placeholder="24", order=4,
        validation={"min": 1, "max": 168},
    ),
    # ==================== Data Management ====================
    ConfigFieldDef(
        key="advanced.clear_business_data", label="清理业务数据", type_=ConfigType.ACTION,
        default="", group=ConfigGroup.ADVANCED,
        description="清理所有岗位数据、uploads/、audit_logs/、dist/目录（保留配置），用于重复测试",
        order=99,
    ),
]


def get_config_schema() -> List[ConfigFieldDef]:
    """获取完整的配置 Schema 定义"""
    return list(CONFIG_SCHEMA)


def get_config_by_group(group: ConfigGroup) -> List[ConfigFieldDef]:
    """按分组获取配置项（已按 order 排序）"""
    return sorted(
        [f for f in CONFIG_SCHEMA if f.group == group],
        key=lambda f: f.order
    )


def get_all_groups() -> List[Dict[str, Any]]:
    """返回所有分组信息（用于前端渲染 Tab 列表）"""
    groups = []
    for g in ConfigGroup:
        fields = get_config_by_group(g)
        if fields:
            groups.append({
                "id": g.value,
                "label": {
                    ConfigGroup.SITE: "🌐 站点信息",
                    ConfigGroup.CONTENT: "📝 内容工厂",
                    ConfigGroup.COMPLIANCE: "🛡️ 合规闸门",
                    ConfigGroup.PLATFORM_WECHAT: "💬 微信平台",
                    ConfigGroup.PLATFORM_DOUYIN: "🎵 抖音平台",
                    ConfigGroup.PLATFORM_BAIDU: "🔍 百度平台",
                    ConfigGroup.DATABASE: "🗄️ 数据库",
                    ConfigGroup.MONITORING: "📊 监控告警",
                    ConfigGroup.SCHEDULER: "⏰ 定时任务",
                    ConfigGroup.ADVANCED: "⚙️ 高级选项",
                }.get(g, g.value),
                "field_count": len(fields),
                "has_secrets": any(f.is_secret for f in fields),
            })
    return groups
