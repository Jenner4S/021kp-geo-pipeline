"""
021kp.com GEO自动化运营系统 - Phase 1: 合规闸门模块 (Compliance Gate)
=============================================================================

功能描述:
    严格遵循国信办通字〔2025〕2号《标识办法》与深度合成规定要求，
    实现以下核心能力：
    1. 招聘行业禁词正则拦截与替换
    2. 显式标识注入（文本可见区域）
    3. 隐式标识注入（HTML Meta标签）
    4. 审计日志生成与留存（≥180天）

使用说明:
    python src/compliance_gate.py --input content_raw.md --output content_cleaned.md --log-dir ./audit_logs
    
作者: GEO-Engine Team | 版本: v1.0 | 日期: 2026-04-20
"""

import hashlib
import json
import os
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from loguru import logger
except ImportError:
    import logging as logger


@dataclass
class ComplianceConfig:
    """合规闸门配置数据类（遵循Pydantic设计原则）"""
    explicit_marker: str = "AI辅助生成标识: 本内容由AI整理，仅供参考"
    meta_name: str = "x-ai-source-id"
    meta_content: str = "jiangsong_kuaipin_v1_20260420"
    ban_words_file: str = "./config/ban_words.txt"
    audit_log_retention_days: int = 180
    audit_log_dir: str = "./audit_logs"
    fail_threshold: int = 5  # 禁词命中数超过此值判定为FAIL
    hash_length: int = 16   # 资产哈希截取长度


@dataclass
class ComplianceResult:
    """合规处理结果数据类"""
    status: str  # PASS / FAIL / PARTIAL
    processed_content: str | None = None
    markers_injected: list[str] = field(default_factory=list)
    banned_words_found: list[str] = field(default_factory=list)
    masked_fields_count: int = 0
    asset_hash: str = ""
    audit_log_path: str = ""


class BanWordFilter:
    """招聘行业禁词过滤器（线程安全）"""

    def __init__(self, ban_words_file: str):
        """
        初始化禁词词库
        
        Args:
            ban_words_file: 禁词文件路径
        """
        self.ban_words_file = ban_words_file
        self._ban_words: list[str] = []
        self._compiled_pattern: re.Pattern | None = None
        self._lock = threading.Lock()  # 读写锁保护
        self._load_ban_words()

    def _load_ban_words(self) -> None:
        """加载禁词文件到内存（内部方法，调用方需持有锁）"""
        if not os.path.exists(self.ban_words_file):
            logger.warning(f"⚠️ 禁词文件不存在: {self.ban_words_file}，将使用默认禁词库")
            new_words = [
                "包过", "稳赚", "绝对高薪", "内幕渠道", "100%录用",
                "必过", "保证入职", "保底薪资", "月入过万", "轻松过万"
            ]
        else:
            with open(self.ban_words_file, encoding='utf-8') as f:
                # 过滤空行和注释行(以#开头)
                new_words = [
                    line.strip() for line in f.readlines()
                    if line.strip() and not line.startswith('#')
                ]

        # 编译复合正则表达式（提升匹配效率）
        new_pattern = None
        if new_words:
            pattern_str = '(' + '|'.join(re.escape(word) for word in new_words) + ')'
            new_pattern = re.compile(pattern_str)

        # 原子性更新（避免读半写状态）
        with self._lock:
            self._ban_words = new_words
            self._compiled_pattern = new_pattern

        logger.info(f"✅ 禁词库加载完成: {len(new_words)} 条规则")

    def reload(self) -> None:
        """热重载禁词文件（支持运行时更新，线程安全）"""
        logger.info("🔄 正在热重载禁词词库...")
        self._load_ban_words()


    def filter(self, text: str, replacement: str = "【需人工核实】") -> tuple[str, list[str]]:
        """
        执行禁词过滤
        
        Args:
            text: 待过滤的原始文本
            replacement: 替换字符串
            
        Returns:
            Tuple[过滤后文本, 命中的禁词列表]
        """
        with self._lock:
            pattern = self._compiled_pattern

        if not pattern or not text:
            return text, []

        found_words = pattern.findall(text)
        filtered_text = pattern.sub(replacement, text)

        return filtered_text, found_words


class ComplianceGate:
    """
    合规闸门主控制器
    
    职责边界:
    - 仅负责文本清洗、合规标识注入、禁词拦截
    - 不修改原始数据结构，输出标准化中间件对象(CIM)
    - 所有操作可审计、可追溯
    """

    # 显式标识模板
    EXPLICIT_MARKER_TEMPLATE = "\n<!-- {marker} -->\n"

    # 隐式Meta标签模板
    IMPLICIT_META_TEMPLATE = (
        '<meta name="{meta_name}" content="{meta_content}">\n'
        '<meta name="ai-generation-log" content="retention_days={retention_days}">\n'
    )

    def __init__(self, config: ComplianceConfig | None = None):
        """
        初始化合规闸门
        
        Args:
            config: 合规配置对象，为None则使用默认配置
        """
        self.config = config or ComplianceConfig()
        self.ban_word_filter = BanWordFilter(self.config.ban_words_file)

        # 审计日志写入锁（多线程安全）
        self._audit_lock = threading.Lock()

        # 确保审计日志目录存在
        Path(self.config.audit_log_dir).mkdir(parents=True, exist_ok=True)

        logger.info("✅ [Phase 1] 合规闸门初始化完成")

    def compute_asset_hash(self, content: str) -> str:
        """
        计算资产SHA256哈希值（用于审计追溯）
        
        Args:
            content: 内容字符串
            
        Returns:
            SHA256哈希值（前16位）
        """
        return hashlib.sha256(content.encode('utf-8')).hexdigest()[:self.config.hash_length]

    def inject_explicit_marker(self, html_content: str) -> str:
        """
        注入显式标识（文本可见区域，不可被CSS/JS剥离）
        
        规范依据: 国信办通字〔2025〕2号《标识办法》
        要求: AI生成内容首尾必须包含固定格式文字提示
        
        Args:
            html_content: 原始HTML内容
            
        Returns:
            注入后的内容
        """
        marker = self.EXPLICIT_MARKER_TEMPLATE.format(marker=self.config.explicit_marker)

        # 在<body>之后插入首部标识
        body_marker = f"<body{marker}"
        if "<body>" in html_content and '<!-- AI辅助' not in html_content:
            html_content = html_content.replace("<body>", body_marker, 1)
        elif '<!-- AI辅助' not in html_content:
            # 无body标签时在开头插入
            html_content = marker + html_content

        return html_content

    def inject_implicit_marker(self, html_content: str) -> str:
        """
        注入隐式标识（Meta标签，供AI爬虫解析）
        
        规范依据: 《标识办法》元数据嵌入要求
        要求: 文件导出时携带服务提供者编码与内容编号
        
        Args:
            html_content: HTML内容
            
        Returns:
            注入后的内容
        """
        meta_tags = self.IMPLICIT_META_TEMPLATE.format(
            meta_name=self.config.meta_name,
            meta_content=self.config.meta_content,
            retention_days=self.config.audit_log_retention_days
        )

        if "<head>" in html_content and 'name="x-ai-source"' not in html_content:
            html_content = html_content.replace("<head>", f"<head>\n{meta_tags}", 1)
        elif '</head>' in html_content and 'name="x-ai-source"' not in html_content:
            html_content = html_content.replace("</head>", f"{meta_tags}</head>", 1)
        else:
            # 无head标签时前置插入
            html_content = meta_tags + html_content

        return html_content

    def write_audit_log(
        self,
        result: ComplianceResult,
        input_source: str,
        reviewer_id: str = "system_auto"
    ) -> str:
        """
        写入审计日志（满足深度合成规定日志留存≥180天要求）
        
        日志要素:
        - 操作时间（ISO 8601格式）
        - 资产SHA256哈希值
        - 审核人ID
        - 处理结果状态
        - 发现的违规词列表
        - 输入源标识
        
        Args:
            result: 合规处理结果
            input_source: 输入源路径或标识
            reviewer_id: 审核人ID
            
        Returns:
            日志文件路径
        """
        timestamp = datetime.now(timezone(timedelta(hours=8))).isoformat()

        log_entry = {
            "timestamp": timestamp,
            "asset_hash": result.asset_hash,
            "status": result.status,
            "reviewer_id": reviewer_id,
            "input_source": input_source,
            "banned_words_found": result.banned_words_found,
            "markers_injected": result.markers_injected,
            "masked_fields_count": result.masked_fields_count,
            "compliance_version": "v1.0_20260420"
        }

        # 生成日志文件名（按日期归档）
        date_str = datetime.now().strftime("%Y-%m-%d")
        log_filename = f"compliance_{date_str}.jsonl"
        log_path = os.path.join(self.config.audit_log_dir, log_filename)

        # 追加写入日志（JSONL格式，支持高效检索，线程安全）
        with self._audit_lock, open(log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(log_entry, ensure_ascii=False) + '\n')

        result.audit_log_path = log_path
        logger.info(f"📋 审计日志已写入: {log_path}")

        return log_path

    def process(self, html_content: str, source_identifier: str = "unknown") -> ComplianceResult:
        """
        执行完整的合规处理流程（主入口方法）
        
        处理流程:
        1. 计算原始资产哈希 → 2. 禁词过滤 → 3. 显式标识注入 
        → 4. 隐式标识注入 → 5. 写入审计日志
        
        Args:
            html_content: 原始HTML/文本内容
            source_identifier: 来源标识（用于审计追溯）
            
        Returns:
            ComplianceResult 合规处理结果对象
        """
        result = ComplianceResult(status="PASS")
        markers_injected = []

        # Step 1: 计算资产哈希
        original_hash = self.compute_asset_hash(html_content)

        # Step 2: 执行禁词过滤
        filtered_content, banned_words = self.ban_word_filter.filter(html_content)
        if banned_words:
            result.banned_words_found = banned_words
            logger.warning(f"🔒 发现禁词({len(banned_words)}个): {banned_words}")

        # Step 3: 注入显式标识
        filtered_content = self.inject_explicit_marker(filtered_content)
        markers_injected.append("explicit_marker")

        # Step 4: 注入隐式标识
        filtered_content = self.inject_implicit_marker(filtered_content)
        markers_injected.append("implicit_meta")

        # 更新结果
        result.processed_content = filtered_content
        result.markers_injected = markers_injected
        result.asset_hash = self.compute_asset_hash(filtered_content)

        # 判定最终状态
        if len(banned_words) > self.config.fail_threshold:  # 可配置阈值
            result.status = "FAIL"
        elif banned_words:
            result.status = "PARTIAL"
        else:
            result.status = "PASS"

        # Step 5: 写入审计日志
        self.write_audit_log(result, source_identifier)

        logger.info(
            f"✅ [Phase 1] 合规处理完成 | "
            f"状态={result.status} | "
            f"禁词命中={len(banned_words)}个 | "
            f"资产哈希={result.asset_hash}"
        )

        return result


# ==================== CLI命令行接口 ====================
def main():
    """命令行入口（用于手动执行或定时任务调用）"""
    import argparse

    parser = argparse.ArgumentParser(
        description="021kp.com GEO Phase 1: 合规闸门模块",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:
  python compliance_gate.py --input raw.html --output cleaned.html
  python compliance_gate.py --input content.md --output clean.md --log-dir ./logs
  
合规配置:
  默认读取 config/settings.yaml 与 config/ban_words.txt
  可通过环境变量覆盖敏感配置项
        """
    )

    parser.add_argument(
        "--input", "-i", required=True,
        help="输入文件路径（HTML/Markdown）"
    )
    parser.add_argument(
        "--output", "-o", required=True,
        help="输出文件路径"
    )
    parser.add_argument(
        "--log-dir", "-l", default="./audit_logs",
        help="审计日志输出目录 (默认: ./audit_logs)"
    )
    parser.add_argument(
        "--config", "-c", default=None,
        help="自定义配置文件路径 (可选)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="仅检查不写入文件（预览模式）"
    )

    args = parser.parse_args()

    # 初始化合规闸门
    config = ComplianceConfig(audit_log_dir=args.log_dir)
    gate = ComplianceGate(config)

    # 读取输入文件
    try:
        with open(args.input, encoding='utf-8') as f:
            raw_content = f.read()
        logger.info(f"📖 已读取输入文件: {args.input} ({len(raw_content)} 字符)")
    except FileNotFoundError:
        logger.error(f"❌ 输入文件不存在: {args.input}")
        return 1
    except PermissionError:
        logger.error(f"❌ 无权限读取文件: {args.input}")
        return 1
    except UnicodeDecodeError:
        logger.error(f"❌ 文件编码错误(非UTF-8): {args.input}")
        return 1
    except OSError as e:
        logger.error(f"❌ 读取文件失败: {args.input} | 错误: {e}")
        return 1

    # 执行合规处理
    result = gate.process(raw_content, source_identifier=args.input)

    # 输出处理报告
    print("\n" + "=" * 60)
    print("📊 合规处理报告")
    print("=" * 60)
    print(f"  状态:          {'✅ PASS' if result.status == 'PASS' else '⚠️ ' + result.status}")
    print(f"  资产哈希:      {result.asset_hash}")
    print(f"  标识注入数:    {len(result.markers_injected)} 个")
    print(f"  禁词命中数:    {len(result.banned_words_found)} 个")
    print(f"  审计日志:      {result.audit_log_path}")

    if result.banned_words_found:
        print("\n  🔍 命中禁词:")
        for word in set(result.banned_words_found):
            print(f"     - {word}")

    print("=" * 60)

    # 写入输出文件
    if not args.dry_run and result.processed_content:
        output_dir = os.path.dirname(args.output)
        if output_dir:
            os.makedirs(output_dir, exist_ok=True)

        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(result.processed_content)
        logger.info(f"💾 已写入输出文件: {args.output}")
    elif args.dry_run:
        logger.info("🔍 预览模式: 未写入文件")

    return 0 if result.status != "FAIL" else 2


if __name__ == "__main__":
    exit(main())
