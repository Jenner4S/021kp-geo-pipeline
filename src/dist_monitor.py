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

使用说明:
    python src/dist_monitor.py --mode schedule    # 启动定时监控
    python src/dist_monitor.py --mode check       # 单次检查
    python src/dist_monitor.py --mode report      # 生成报告

作者: GEO-Engine Team | 版本: v1.0 | 日期: 2026-04-20
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
    citation_rate: float = 0.0  # 引用率 (0-1)
    ctr_estimate: float | None = None
    last_check_time: str = ""
    trend: str = "stable"  # stable / rising / falling


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
    """

    # 搜索关键词库（松江招聘相关）
    SEARCH_QUERIES = [
        "松江招聘",
        "上海松江找工作",
        "松江急招岗位",
        "G60科创走廊招聘",
        "松江大学城兼职"
    ]

    # 品牌关键词（用于检测是否被引用）
    BRAND_KEYWORDS = [
        "021kp.com", "松江快聘", "021kp", "松江快聘网"
    ]

    def __init__(self, config_path: str | None = None):
        self.config = self._load_config(config_path)

        # 探针缓存（避免频繁请求同一URL）+ TTL淘汰
        self._cache: dict[str, dict] = {}
        self._cache_ttl = 3600  # 缓存1小时
        self._cache_max_size = 1000  # 最大缓存条目数(防止内存泄漏)

    def _load_config(self, config_path: str | None) -> dict:
        """加载配置"""
        default_config = {
            "probes": {
                "metaso": {"enabled": True, "base_url": "https://metaso.cn"},
                "doubao": {"enabled": True, "base_url": "https://www.doubao.com"},
                "yuanbao": {"enabled": True, "base_url": "https://yuanbao.tencent.com"}
            },
            "check_interval_hours": 2,
            "timeout_seconds": 15,
            "user_agent": "021kp-GEO-Monitor/1.0"
        }

        if config_path and os.path.exists(config_path):
            with open(config_path, encoding='utf-8') as f:
                return {**default_config, **json.load(f)}
        return default_config

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
            CitationMetrics 引用指标对象
        """
        query = query or self.SEARCH_QUERIES[int(time.time()) % len(self.SEARCH_QUERIES)]

        metrics = CitationMetrics(
            platform=platform_key,
            total_queries=1,
            last_check_time=datetime.now(timezone(timedelta(hours=8))).isoformat()
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
        # 此处返回模拟数据用于验证系统流程
        # 实际部署时应：
        # 1. 调用平台官方搜索接口
        # 2. 解析AI概览区域内容
        # 3. 统计品牌提及次数
        # 4. 计算引用率

        try:
            # 尝试实际请求（示例）
            probe_config = self.config.get("probes", {}).get(platform_key, {})

            if probe_config.get("enabled") and requests is not None:
                base_url = probe_config.get("base_url", "")

                # 构建模拟搜索请求
                # 注意：此处仅为框架示例，具体API参数需根据平台文档调整
                headers = {
                    "User-Agent": self.config.get("user_agent", ""),
                    "Accept": "application/json"
                }

                # 模拟请求逻辑
                response_data = self._simulate_platform_response(
                    platform_key, query
                )

                metrics.brand_mention_count = response_data.get("mention_count", 0)
                metrics.total_queries = response_data.get("total_results", 100)

                if metrics.total_queries > 0:
                    metrics.citation_rate = (
                        metrics.brand_mention_count / metrics.total_queries * 100
                    )

                metrics.trend = response_data.get("trend", "stable")

            else:
                # 纯模拟模式（无网络或禁用时）
                metrics = self._generate_mock_metrics(platform_key, query)

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
        seed = hash(f"{platform}:{query}") % 10000
        rng = random.Random(seed)

        return {
            "mention_count": rng.randint(0, 5),
            "total_results": rng.randint(50, 500),
            "trend": rng.choice(["stable", "rising", "falling"]),
            "response_time_ms": rng.randint(200, 1500)
        }

    def _generate_mock_metrics(self, platform: str, query: str) -> CitationMetrics:
        """生成模拟指标数据"""
        import random
        seed = hash(f"{platform}:{query}:mock") % 10000
        rng = random.Random(seed)

        mention_count = rng.randint(0, 3)
        total_queries = rng.randint(80, 300)

        return CitationMetrics(
            platform=platform,
            brand_mention_count=mention_count,
            total_queries=total_queries,
            citation_rate=(mention_count / max(total_queries, 1)) * 100,
            last_check_time=datetime.now().isoformat(),
            trend=rng.choice(["stable", "rising", "falling"])
        )

    def batch_check(self) -> list[CitationMetrics]:
        """
        批量检查所有启用平台的引用率
        
        Returns:
            所有平台的指标列表
        """
        results = []

        for platform_key, probe_config in self.config.get("probes", {}).items():
            if not probe_config.get("enabled"):
                continue

            for query in self.SEARCH_QUERIES[:2]:  # 每个平台查2个关键词
                metrics = self.check_citation_rate(platform_key, query)
                results.append(metrics)
                time.sleep(1)  # 避免请求过于密集

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

        for rule in self.rules:
            # 获取对应指标的值
            metric_value = self._extract_metric_value(rule.metric_name, metrics)
            if metric_value is None:
                continue

            # 判断是否满足条件
            triggered = self._compare(metric_value, rule.threshold, rule.operator)

            if triggered:
                key = f"{rule.metric_name}_{rule.operator}"
                self._failure_counts[key] = self._failure_counts.get(key, 0) + 1

                # 检查连续失败次数
                if self._failure_counts[key] >= rule.consecutive_failures:
                    # 检查冷却时间
                    last_alert = self._last_alert_times.get(key, 0)
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

                        triggered_alerts.append(alert)

                        # 发送通知
                        self._send_notification(alert)

                        # 写入告警历史
                        self._write_alert_history(alert)

                        self._last_alert_times[key] = now

                        # 重置计数（已处理）
                        self._failure_counts[key] = 0
            else:
                # 条件不满足，重置计数
                key = f"{rule.metric_name}_{rule.operator}"
                if key in self._failure_counts:
                    del self._failure_counts[key]

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
        report = MonitorReport(
            report_id=f"report_{datetime.now().strftime('%Y%m%d%H%M%S')}",
            generated_at=datetime.now(timezone(timedelta(hours=8))).isoformat(),
            period_start=(datetime.now() - timedelta(hours=2)).isoformat(),  # 近2小时
            period_end=datetime.now().isoformat(),
            overall_status=MonitorState.NORMAL
        )

        # Step 1: 采集指标
        logger.info("🔍 [Step 1] 开始采集AI引用率指标...")
        metrics = self.probe.batch_check()
        report.metrics.extend(metrics)

        # Step 2: 评估告警规则
        logger.info("📊 [Step 2] 评估告警规则...")
        triggered_alerts = self.alert_engine.evaluate(metrics)
        report.alerts_triggered = triggered_alerts

        # Step 3: 判断是否需要回滚
        critical_alerts = [a for a in triggered_alerts if a.get("severity") == "critical"]
        if critical_alerts and any(a.get("action") == "rollback" for a in critical_alerts):
            reason = "; ".join([a.get("message", "") for a in critical_alerts[:2]])
            rollback_result = self.rollback_mgr.execute_rollback(reason=reason)
            report.overall_status = MonitorState.FROZEN
            report.recommendations.append("已自动执行向量回滚，切换至合规模板")
        elif triggered_alerts:
            report.overall_status = MonitorState.DEGRADED
            report.recommendations.append("存在警告项，请关注后续趋势")

        # Step 4: 生成AI预览模拟
        report.ai_preview_simulation = self._generate_ai_preview_simulation(metrics)

        # Step 5: 输出报告
        self._save_report(report)

        logger.info(
            f"✅ [Phase 5] 监控检查完成 | "
            f"状态={report.overall_status.value} | "
            f"告警数={len(triggered_alerts)} | "
            f"报告ID={report.report_id}"
        )

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
                            "trend": m.trend
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
