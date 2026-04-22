#!/usr/bin/env python3
"""
松江快聘 GEO Pipeline - 定时任务调度器
==========================================
功能: 替代系统 crontab, 提供 Python 原生定时调度
支持: 流水线执行 / 监控检查 / 日志清理 / 健康探测

使用方式:
    python scripts/scheduler.py              # 交互式启动
    python scripts/scheduler.py --daemon      # 后台守护模式
    python scripts/scheduler.py --once        # 立即执行一次后退出

作者: GEO-Engine Team | 版本: v2.0.1
"""

import argparse
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

# 确保 src 目录在 Python 路径中
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

try:
    import schedule
    SCHEDULE_AVAILABLE = True
except ImportError:
    SCHEDULE_AVAILABLE = False
    print("[WARN] schedule 库未安装，请执行: pip3 install schedule")

try:
    from loguru import logger
    logger.remove()
    logger.add(
        sys.stdout,
        format="<green>{time:HH:mm:ss}</green> | <level>{level:<8}</level> | {message}",
        level="INFO"
    )
    logger.add(
        "logs/scheduler_{time:YYYYMMDD}.log",
        rotation="00:00",
        retention="30 days",
        level="DEBUG"
    )
except ImportError:
    import logging as logger
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(message)s"
    )


class GEOScheduler:
    """GEO Pipeline 定时调度器"""

    def __init__(self, csv_path: str = None, dry_run: bool = False):
        """
        初始化调度器

        Args:
            csv_path: 默认CSV数据源路径
            dry_run: 试运行模式（不实际执行）
        """
        self.csv_path = csv_path or str(Path(__file__).parent.parent / "data" / "sample_jobs.csv")
        self.dry_run = dry_run
        self._running = False
        self._jobs_registered = 0

    def register_default_jobs(self):
        """注册默认定时任务"""
        if not SCHEDULE_AVAILABLE:
            logger.error("schedule 库不可用，无法注册定时任务")
            return

        # === 任务1: 每日14:00 执行GEO流水线 ===
        schedule.every().day.at("14:00").do(
            self._run_pipeline,
            name="daily_pipeline_1400"
        ).tag("pipeline", "daily")
        logger.info("已注册: 每日 14:00 GEO流水线 (数据源: {})", self.csv_path)

        # === 任务2: 每日20:00 引用率监控与告警 ===
        schedule.every().day.at("20:00").do(
            self._run_monitor_check,
            name="monitor_2000"
        ).tag("monitor", "daily")
        logger.info("已注册: 每日 20:00 监控检查")

        # === 任务3: 每6小时健康检查(仅记录) ===
        schedule.every(6).hours.do(
            self._health_check,
            name="health_6h"
        ).tag("health")
        logger.info("已注册: 每6小时 API健康检查")

        # === 任务4: 每周一生成报告 ===
        schedule.every().monday.at("09:00").do(
            self._generate_report,
            name="weekly_report"
        ).tag("report", "weekly")
        logger.info("已注册: 每周一 09:00 周报生成")

        self._jobs_registered = len(schedule.jobs)
        logger.info("共注册 {} 个定时任务", self._jobs_registered)

    def _run_pipeline(self, name: str = ""):
        """执行GEO流水线"""
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        tag = f"[{name}]" if name else ""
        logger.info("=" * 50)
        logger.info("{} [Pipeline] 开始执行 GEO 流水线 {}", tag, ts)

        if self.dry_run:
            logger.info("[DRY RUN] 跳过实际执行")
            return

        try:
            from main import run_pipeline_mode

            result = run_pipeline_mode(csv_path=self.csv_path)

            if result.get("status") == "success":
                phases = result.get("phase_results", {})
                cg = phases.get("compliance_gate", {})
                cf = phases.get("content_factory", {})
                logger.info(
                    "[Pipeline] 完成 | 通过={}/{} | Schema资产={}套",
                    cg.get("passed", 0),
                    cg.get("processed", 0),
                    cf.get("assets_generated", 0)
                )
            else:
                logger.error("[Pipeline] 失败: {}", result.get("error_message", "未知错误"))

        except Exception as e:
            logger.error("[Pipeline] 异常: {}", e)

    def _run_monitor_check(self, name: str = ""):
        """执行监控检查"""
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        tag = f"[{name}]" if name else ""
        logger.info("{} [Monitor] 开始监控检查 {}", tag, ts)

        if self.dry_run:
            logger.info("[DRY RUN] 跳过监控检查")
            return

        try:
            from dist_monitor import DistributionMonitor

            monitor = DistributionMonitor()

            # 执行完整监控检查（采集指标 → 告警评估 → 回滚判断）
            report = monitor.run_single_check()
            logger.info(
                "[Monitor] 状态={} | 告警数={} | 报告ID={}",
                report.overall_status.value,
                len(report.alerts_triggered),
                report.report_id
            )

            # 如果有告警触发，自动推送通知
            if report.alerts_triggered:
                for alert in report.alerts_triggered:
                    severity = alert.get("severity", "info")
                    msg = alert.get("message", "")
                    if severity in ("warning", "error", "critical"):
                        logger.warning(
                            "[Monitor] 告警: [{}] {}",
                            severity.upper(),
                            msg[:100]
                        )

        except Exception as e:
            logger.error("[Monitor] 异常: {}", e)

    def _health_check(self, name: str = ""):
        """API健康检查"""
        try:
            from auth_signaler import APISignaler

            signer = APISignaler()
            health = signer.health_check()

            status = "OK" if health.get("overall") == "healthy" else "DEGRADED"
            logger.info(
                "[Health] {} | platforms={}",
                status,
                list(health.get("platforms", {}).keys())
            )

        except ImportError:
            logger.debug("[Health] auth_signaler 未配置，跳过检查")
        except Exception as e:
            logger.error("[Health] 异常: {}", e)

    def _generate_report(self, name: str = ""):
        """生成统计报告"""
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        tag = f"[{name}]" if name else ""
        logger.info("{} [Report] 生成周报 {}", tag, ts)

        try:
            from pathlib import Path
            import json
            from collections import defaultdict

            # 统计审计日志
            audit_dir = Path("./audit_logs")
            stats = {
                "generated_at": ts,
                "period": "weekly",
                "compliance": {"total": 0, "passed": 0, "blocked": 0},
                "assets_generated": 0,
                "top_banned_words": []
            }

            if audit_dir.exists():
                for log_file in sorted(audit_dir.glob("*.jsonl")):
                    for line in log_file.open(encoding="utf-8"):
                        try:
                            entry = json.loads(line.strip())
                            stats["compliance"]["total"] += 1
                            status = entry.get("status", "")
                            if status in ("PASS", "PASSED"):
                                stats["compliance"]["passed"] += 1
                            elif status == "FAIL":
                                stats["compliance"]["blocked"] += 1
                        except (json.JSONDecodeError, KeyError):
                            pass

            # 统计生成的资产
            dist_dir = Path("./dist")
            if dist_dir.exists():
                stats["assets_generated"] = len(list(dist_dir.glob("asset_*.json")))

            # 写入报告
            report_dir = Path("./reports")
            report_dir.mkdir(exist_ok=True)
            report_path = report_dir / f"weekly_{datetime.now().strftime('%Y%m%d')}.json"

            with open(report_path, "w", encoding="utf-8") as f:
                json.dump(stats, f, ensure_ascii=False, indent=2)

            logger.info(
                "[Report] 完成 | 审计记录={} (通过={}, 阻断={}) | 资产={}套 | 文件={}",
                stats["compliance"]["total"],
                stats["compliance"]["passed"],
                stats["compliance"]["blocked"],
                stats["assets_generated"],
                report_path.name
            )

        except Exception as e:
            logger.error("[Report] 异常: {}", e)

    def run_once(self):
        """立即执行一次所有任务后退出"""
        logger.info("[Once Mode] 立即执行所有任务...")
        self._run_pipeline(name="manual_once")
        self._run_monitor_check(name="manual_once")
        self._generate_report(name="manual_once")
        logger.info("[Once Mode] 所有任务执行完毕")

    def run_forever(self):
        """持续运行调度循环"""
        if not SCHEDULE_AVAILABLE:
            logger.error("schedule 库未安装，请执行: pip3 install schedule")
            sys.exit(1)

        self._running = True
        logger.info("=" * 50)
        logger.info("GEO Pipeline 调度器启动 | PID={}", os.getpid())
        logger.info("数据源: {}", self.csv_path)
        logger.info("模式: {}", "DRY-RUN" if self.dry_run else "PRODUCTION")
        logger.info("按 Ctrl+C 停止")
        logger.info("=" * 50)

        while self._running:
            schedule.run_pending()
            time.sleep(60)  # 每分钟检查一次

        logger.info("调度器已停止")

    def stop(self):
        """停止调度器"""
        self._running = False
        logger.info("正在停止调度器...")


def setup_signal_handlers(scheduler: GEOScheduler):
    """设置信号处理器"""
    def _handler(signum, frame):
        sig_name = {2: "SIGINT", 15: "SIGTERM"}.get(signum, str(signum))
        logger.info("接收到信号 {}, 正在优雅关闭...", sig_name)
        scheduler.stop()

    signal.signal(signal.SIGINT, _handler)
    signal.signal(signal.SIGTERM, _handler)


import os


def main():
    parser = argparse.ArgumentParser(
        description="松江快聘 GEO Pipeline 定时调度器 v2.0.1",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
    # 交互式运行（前台）
    python scripts/scheduler.py
    
    # 立即执行一次
    python scripts/scheduler.py --once
    
    # 指定数据源
    python scripts/scheduler.py --csv data/my_jobs.csv
    
    # 试运行（不实际执行）
    python scripts/scheduler.py --dry-run
        """
    )

    parser.add_argument("--csv", "-c", help="CSV数据源路径 (默认: data/sample_jobs.csv)")
    parser.add_argument("--once", action="store_true", help="立即执行一次后退出")
    parser.add_argument("--daemon", action="store_true", help="后台守护模式")
    parser.add_argument("--dry-run", action="store_true", help="试运行（不实际执行）")

    args = parser.parse_args()

    # 创建调度器实例
    scheduler = GEOScheduler(
        csv_path=args.csv,
        dry_run=args.dry_run
    )

    if args.once:
        scheduler.run_once()
        return

    # 注册默认任务
    scheduler.register_default_jobs()

    # 设置信号处理
    setup_signal_handlers(scheduler)

    if args.daemon:
        import subprocess
        print(f"[Daemon] 启动后台进程...")
        proc = subprocess.Popen(
            [sys.executable, __file__, "--csv", args.csv or ""],
            stdout=open("logs/scheduler_daemon.log", "a"),
            stderr=subprocess.STDOUT,
            start_new_session=True
        )
        print(f"[Daemon] PID: {proc.pid}")
        print(f"[Daemon] 日志: logs/scheduler_daemon.log")
        print(f"[Daemon] 停止: kill {proc.pid}")
        return

    # 前台持续运行
    scheduler.run_forever()


if __name__ == "__main__":
    main()
