"""
021kp.com GEO自动化运营系统 - Phase 4: API路由与LBS注入模块 (Auth Signaler)
=============================================================================

功能描述:
    通过官方API将结构化内容推送至国内AI平台索引池，实现以下核心能力：
    1. 微信(元宝)开放平台API对接
    2. 抖音/头条(豆包)企业号API对接
    3. 百度搜索资源平台API对接
    4. LBS地域标签自动注入
    5. API凭证管理与限流熔断

使用说明:
    python src/auth_signaler.py --url https://www.021kp.com/job/123 --platforms wechat,douyin

作者: GEO-Engine Team | 版本: v1.0 | 日期: 2026-04-20
"""

import hashlib
import hmac
import json
import os
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any

try:
    import requests
    from loguru import logger
except ImportError:
    import logging as logger
    requests = None  # type: ignore


# ==================== 数据类型定义 ====================
class PlatformType(Enum):
    """目标平台枚举"""
    WECHAT = "wechat_yuanbao"
    DOUYIN = "douyin_doubao"
    BAIDU = "baidu_wenxin"


class PushStatus(Enum):
    """推送状态枚举"""
    QUEUED = "QUEUED"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    RATE_LIMITED = "RATE_LIMITED"
    AUTH_FAILED = "AUTH_FAILED"


@dataclass
class APICredential:
    """API凭证数据类"""
    app_id: str = ""
    app_secret: str = ""
    token: str = ""  # 运行时获取的access_token
    token_expiry: float = 0.0  # token过期时间戳

    def __repr__(self) -> str:
        """安全repr：隐藏token明文，避免日志泄露"""
        return (f"APICredential(app_id={self.app_id!r}, "
                f"token={'***' if self.token else ''}, "
                f"expires_at={self.token_expiry})")


@dataclass
class PushResult:
    """推送结果数据类"""
    platform: str = ""
    status: PushStatus = PushStatus.QUEUED
    push_id: str = ""
    response_code: int = 0
    response_message: str = ""
    timestamp: str = ""
    retry_after: int = 0


@dataclass
class CircuitBreakerState:
    """熔断器状态数据类"""
    state: str = "CLOSED"  # CLOSED / OPEN / HALF_OPEN
    failure_count: int = 0
    last_failure_time: float = 0.0
    next_retry_time: float = 0.0


# ==================== 熔断器 ====================
class CircuitBreaker:
    """
    API调用熔断器
    
    状态机转换规则:
    - CLOSED (正常) → 连续失败 ≥ failure_threshold → OPEN (熔断)
    - OPEN (熔断) → 超过 reset_timeout → HALF_OPEN (半开)
    - HALF_OPEN → 成功 → CLOSED | 失败 → OPEN
    """

    def __init__(
        self,
        failure_threshold: int = 3,
        reset_timeout_seconds: int = 86400,  # 默认24小时
        half_open_max_calls: int = 2
    ):
        self.failure_threshold = failure_threshold
        self.reset_timeout_seconds = reset_timeout_seconds
        self.half_open_max_calls = half_open_max_calls

        # 每个平台独立的熔断状态
        self._states: dict[str, CircuitBreakerState] = {}

    def get_state(self, platform_key: str) -> CircuitBreakerState:
        """获取指定平台的熔断状态"""
        if platform_key not in self._states:
            self._states[platform_key] = CircuitBreakerState()
        return self._states[platform_key]

    def is_available(self, platform_key: str) -> bool:
        """检查平台是否可用（未被熔断）"""
        state = self.get_state(platform_key)

        if state.state == "CLOSED":
            return True

        elif state.state == "OPEN":
            # 检查是否可以进入半开状态
            now = time.time()
            if now >= state.next_retry_time:
                state.state = "HALF_OPEN"
                state.failure_count = 0
                logger.info(f"🔓 平台 {platform_key} 进入HALF_OPEN状态")
                return True
            else:
                remaining = int(state.next_retry_time - now)
                logger.warning(f"🔒 平台 {platform_key} 已熔断，剩余 {remaining} 秒")
                return False

        elif state.state == "HALF_OPEN":
            return True

        return False

    def record_success(self, platform_key: str) -> None:
        """记录成功调用"""
        state = self.get_state(platform_key)

        if state.state == "HALF_OPEN":
            state.state = "CLOSED"
            state.failure_count = 0
            logger.info(f"✅ 平台 {platform_key} 恢复正常（CLOSED）")

    def record_failure(self, platform_key: str) -> None:
        """记录失败调用"""
        state = self.get_state(platform_key)
        state.failure_count += 1
        state.last_failure_time = time.time()

        if state.failure_count >= self.failure_threshold:
            state.state = "OPEN"
            state.next_retry_time = time.time() + self.reset_timeout_seconds
            logger.warning(
                f"🔒 平台 {platform_key} 触发熔断 (连续{state.failure_count}次失败)，"
                f"将在{self.reset_timeout_seconds}秒后重试"
            )


# ==================== 凭证管理器 ====================
class CredentialManager:
    """
    API凭证管理器
    
    功能:
    - 安全存储API密钥
    - 自动刷新Token（微信AccessToken等）
    - Token缓存与过期检测
    - 凭证轮换支持
    """

    TOKEN_CACHE_TTL = 7000  # 微信Access Token有效期约7200秒，提前200秒刷新

    def __init__(self, config_path: str | None = None):
        self.config = self._load_config(config_path)
        self._credentials: dict[str, APICredential] = {}
        self._token_cache: dict[str, tuple[str, float]] = {}  # {platform: (token, expiry)}
        # 实例级 Session（线程安全：每个实例独立，内部连接池有锁保护）
        self._session: requests.Session | None = requests.Session() if requests else None
        self._cache_lock = threading.Lock()  # token缓存读写锁

    def _load_config(self, config_path: str | None) -> dict:
        """加载配置文件或使用环境变量"""
        if config_path and os.path.exists(config_path):
            with open(config_path, encoding='utf-8') as f:
                return json.load(f)

        # 从环境变量构建配置
        return {
            "wechat": {
                "app_id": os.environ.get("WECHAT_APP_ID", ""),
                "app_secret": os.environ.get("WECHAT_APP_SECRET", "")
            },
            "douyin": {
                "client_key": os.environ.get("DOUYIN_CLIENT_KEY", ""),
                "client_secret": os.environ.get("DOUYIN_CLIENT_SECRET", "")
            },
            "baidu": {
                "api_key": os.environ.get("BAIDU_API_KEY", ""),
                "site_url": "https://www.021kp.com"
            }
        }

    def get_wechat_token(self) -> str | None:
        """
        获取微信AccessToken（带缓存）
        
        Token有效期: ~7200秒，提前200秒刷新
        """
        cache_key = "wechat"

        # 检查缓存
        cached = self._token_cache.get(cache_key)
        if cached:
            token, expiry = cached
            if time.time() < expiry:
                return token

        # 刷新Token
        if requests is None:
            logger.error("❌ requests库未安装，无法获取微信Token")
            return None

        app_id = self.config.get("wechat", {}).get("app_id", "")
        app_secret = self.config.get("wechat", {}).get("app_secret", "")

        if not app_id or not app_secret:
            logger.warning("⚠️ 微信凭证未配置")
            return None

        try:
            url = "https://api.weixin.qq.com/cgi-bin/token"
            params = {
                "grant_type": "client_credential",
                "appid": app_id,
                "secret": app_secret
            }

            response = self._session.get(url, params=params, timeout=10)
            data = response.json()

            if "access_token" in data:
                token = data["access_token"]
                expires_in = data.get("expires_in", 7200)

                # 缓存Token（提前过期以避免边界问题）
                self._token_cache[cache_key] = (
                    token,
                    time.time() + min(expires_in - 200, self.TOKEN_CACHE_TTL)
                )

                logger.info("✅ 微信AccessToken已刷新")
                return token
            else:
                logger.error(f"❌ 获取微信Token失败: {data}")
                return None

        except Exception as e:
            logger.error(f"❌ 微信Token请求异常: {e}")
            return None

    def invalidate_cache(self, platform: str) -> None:
        """使指定平台的Token缓存失效"""
        if platform in self._token_cache:
            del self._token_cache[platform]
            logger.info(f"🔄 {platform} Token缓存已清除")


# ==================== 平台适配器 ====================
class WeChatAdapter:
    """微信(元宝)平台适配器"""

    BASE_URL = "https://api.weixin.qq.com"
    _session = requests.Session() if requests else None  # 连接复用

    @staticmethod
    def build_payload(
        url: str,
        title: str,
        description: str,
        lbs_tag: str
    ) -> dict[str, Any]:
        """构建微信推送载荷"""
        return {
            "url": url,
            "title": f"{title}【松江招聘】",
            "description": description[:120],
            "lbs_tag": lbs_tag,
            "source_type": "ai_optimized_content",
            "tags": ["#松江招聘", "#松江急招"]
        }

    @staticmethod
    def push(
        payload: dict[str, Any],
        credential: APICredential,
        timeout: int = 15
    ) -> PushResult:
        """执行推送"""
        result = PushResult(platform="wechat_yuanbao", timestamp=datetime.now().isoformat())

        if not credential.token:
            result.status = PushStatus.AUTH_FAILED
            result.response_message = "微信Token未获取"
            return result

        try:
            api_url = f"{WeChatAdapter.BASE_URL}/cgi-bin/freshpush/push"
            headers = {"Content-Type": "application/json"}

            response = WeChatAdapter._session.post(
                api_url,
                params={"access_token": credential.token},
                json=payload,
                headers=headers,
                timeout=timeout
            )

            data = response.json()
            result.response_code = response.status_code

            if response.status_code == 200 and data.get("errcode") == 0:
                result.status = PushStatus.SUCCESS
                result.push_id = data.get("msgid", "")
                result.response_message = "推送成功"
            elif response.status_code == 429 or data.get("errcode") == 45009:
                result.status = PushStatus.RATE_LIMITED
                result.retry_after = 3600  # 1小时后重试
                result.response_message = "频率限制"
            else:
                result.status = PushStatus.FAILED
                result.response_message = f"错误码: {data.get('errmsg', 'unknown')}"

        except requests.exceptions.Timeout:
            result.status = PushStatus.FAILED
            result.response_message = "请求超时"
        except Exception as e:
            result.status = PushStatus.FAILED
            result.response_message = str(e)

        return result


class DouyinAdapter:
    """抖音(豆包)平台适配器"""

    BASE_URL = "https://open.douyin.com"
    _session = requests.Session() if requests else None  # 连接复用

    @staticmethod
    def _generate_signature(client_secret: str, params: dict) -> str:
        """生成HmacSHA256签名"""
        sorted_params = sorted(params.items())
        query_string = "&".join([f"{k}={v}" for k, v in sorted_params])
        signature = hmac.new(
            client_secret.encode('utf-8'),
            query_string.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        return signature

    @staticmethod
    def build_payload(url: str, content: str, lbs_tag: str) -> dict[str, Any]:
        """构建抖音推送载荷"""
        return {
            "content": content[:500],
            "media_type": "text",
            "source_url": url,
            "lbs_tag": lbs_tag,
            "hashtags": ["#松江招聘", "#G60科创走廊"]
        }

    @staticmethod
    def push(payload: dict, credential: APICredential, timeout: int = 20) -> PushResult:
        """执行推送"""
        result = PushResult(platform="douyin_doubao", timestamp=datetime.now().isoformat())

        try:
            # 构建签名参数
            params = {
                "client_key": getattr(credential, 'client_key', ''),
                "timestamp": str(int(time.time()))
            }

            headers = {
                "Content-Type": "application/json",
                "X-Signature": DouyinAdapter._generate_signature(
                    credential.app_secret, params
                )
            }

            response = DouyinAdapter._session.post(
                f"{DouyinAdapter.BASE_URL}/enterprise/content/push",
                params=params,
                json=payload,
                headers=headers,
                timeout=timeout
            )

            data = response.json()
            result.response_code = response.status_code

            if response.status_code == 200 and data.get("code") == 0:
                result.status = PushStatus.SUCCESS
                result.push_id = data.get("task_id", "")
            elif response.status_code == 429:
                result.status = PushStatus.RATE_LIMITED
                result.retry_after = 1800
            else:
                result.status = PushStatus.FAILED
                result.response_message = data.get("message", "unknown error")

        except Exception as e:
            result.status = PushStatus.FAILED
            result.response_message = str(e)

        return result


class BaiduAdapter:
    """百度(文心/秘塔)平台适配器"""

    BASE_URL = "https://ziyuan.baidu.com"
    _session = requests.Session() if requests else None  # 连接复用

    @staticmethod
    def build_payload(urls: list[str]) -> dict[str, Any]:
        """构建百度推送载荷"""
        return {
            "urls": urls,
            "site": "021kp.com"
        }

    @staticmethod
    def push(payload: dict, credential: APICredential, timeout: int = 10) -> PushResult:
        """执行推送（百度资源平台主动推送）"""
        result = PushResult(platform="baidu_wenxin", timestamp=datetime.now().isoformat())

        if not credential.app_id:  # 复用字段存储api_key
            result.status = PushStatus.AUTH_FAILED
            result.response_message = "百度API Key未配置"
            return result

        try:
            headers = {"User-Agent": "021kp-geo-pipeline/1.0"}

            response = BaiduAdapter._session.post(
                f"{BaiduAdapter.BASE_URL}/sitesite/api/pushurl",
                params={
                    "site": payload["site"],
                    "token": credential.app_id
                },
                data="\n".join(payload.get("urls", [])),
                headers=headers,
                timeout=timeout
            )

            result.response_code = response.status_code

            if response.status_code == 200:
                body = response.json()
                if body.get("success"):
                    result.status = PushStatus.SUCCESS
                    result.push_id = body.get("remain", "")
                    result.response_message = f"剩余配额: {body.get('remain', 0)}"
                else:
                    result.status = PushStatus.FAILED
                    result.response_message = body.get("message", "unknown")
            else:
                result.status = PushStatus.FAILED
                result.response_message = f"HTTP {response.status_code}"

        except Exception as e:
            result.status = PushStatus.FAILED
            result.response_message = str(e)

        return result


# ==================== 主控制器 ====================
class AuthSignaler:
    """
    API路由调度器主控制器
    
    职责边界:
    - 仅负责平台API鉴权、限流控制与LBS标签追加
    - 不持有用户隐私数据，仅传递URL与结构化摘要
    - 集成熔断器实现自动降级
    """

    DEFAULT_LBS_TAG = "songjiang_district/G60_corridor"

    def __init__(self, config_path: str | None = None):
        self.credential_manager = CredentialManager(config_path)
        self.circuit_breaker = CircuitBreaker()

        # 平台适配器注册表
        self._adapters = {
            PlatformType.WECHAT: WeChatAdapter,
            PlatformType.DOUYIN: DouyinAdapter,
            PlatformType.BAIDU: BaiduAdapter
        }

        logger.info("✅ [Phase 4] API路由调度器初始化完成")

    def push_to_platforms(
        self,
        url: str,
        title: str = "松江最新招聘信息",
        description: str = "",
        platforms: list[str] | None = None,
        lbs_tag: str | None = None,
        max_retries: int = 2
    ) -> list[PushResult]:
        """
        推送内容至多平台（主入口方法）
        
        流程:
        1. 检查各平台熔断状态
        2. 构建平台专属载荷
        3. 执行推送并记录结果
        4. 更新熔断器状态
        
        Args:
            url: 要推送的URL
            title: 标题
            description: 描述文本
            platforms: 目标平台列表（为None则推送到所有平台）
            lbs_tag: LBS地理标签
            max_retries: 最大重试次数
            
        Returns:
            各平台推送结果列表
        """
        lbs_tag = lbs_tag or self.DEFAULT_LBS_TAG
        target_platforms = platforms or ["wechat_yuanbao", "douyin_doubao", "baidu_wenxin"]

        results = []
        successful_count = 0

        for platform_key in target_platforms:
            # 映射到枚举
            try:
                platform_enum = PlatformType(platform_key)
            except ValueError:
                results.append(PushResult(
                    platform=platform_key,
                    status=PushStatus.FAILED,
                    response_message=f"未知平台: {platform_key}",
                    timestamp=datetime.now().isoformat()
                ))
                continue

            # 检查熔断状态
            if not self.circuit_breaker.is_available(platform_key):
                results.append(PushResult(
                    platform=platform_key,
                    status=PushStatus.FAILED,
                    response_message="平台已熔断，跳过推送",
                    timestamp=datetime.now().isoformat()
                ))
                continue

            # 获取适配器并执行推送
            adapter_cls = self._adapters.get(platform_enum)
            if adapter_cls is None:
                continue

            # 构建凭证
            credential = APICredential()
            if platform_enum == PlatformType.WECHAT:
                credential.token = self.credential_manager.get_wechat_token() or ""

            # 重试机制
            for attempt in range(max_retries + 1):
                try:
                    # 构建载荷
                    payload = self._build_platform_payload(
                        platform_enum, url, title, description, lbs_tag
                    )

                    # 执行推送
                    result = adapter_cls.push(payload, credential)

                    # 更新熔断器状态
                    if result.status == PushStatus.SUCCESS:
                        self.circuit_breaker.record_success(platform_key)
                        successful_count += 1
                    else:
                        self.circuit_breaker.record_failure(platform_key)

                        if result.status == PushStatus.RATE_LIMITED and attempt < max_retries:
                            wait = result.retry_after or (attempt + 1) * 60
                            logger.warning(f"⏳ {platform_key} 频率限制，等待 {wait}秒后重试...")
                            time.sleep(min(wait, 300))  # 最长等5分钟
                            continue

                    results.append(result)
                    break

                except Exception as e:
                    logger.error(f"❌ {platform_key} 推送异常 (尝试{attempt+1}): {e}")
                    if attempt == max_retries:
                        results.append(PushResult(
                            platform=platform_key,
                            status=PushStatus.FAILED,
                            response_message=f"异常: {str(e)[:100]}",
                            timestamp=datetime.now().isoformat()
                        ))

        # 输出汇总日志
        success_rate = successful_count / len(target_platforms) * 100
        logger.info(
            f"✅ [Phase 4] 推送完成 | "
            f"目标={len(target_platforms)}个平台 | "
            f"成功={successful_count}个 | "
            f"成功率={success_rate:.1f}%"
        )

        return results

    def _build_platform_payload(
        self,
        platform: PlatformType,
        url: str,
        title: str,
        description: str,
        lbs_tag: str
    ) -> dict[str, Any]:
        """根据平台类型构建对应载荷"""
        if platform == PlatformType.WECHAT:
            return WeChatAdapter.build_payload(url, title, description, lbs_tag)
        elif platform == PlatformType.DOUYIN:
            return DouyinAdapter.build_payload(url, description, lbs_tag)
        elif platform == PlatformType.BAIDU:
            return BaiduAdapter.build_payload([url])
        else:
            return {"url": url}

    def get_push_statistics(self, day_range: int = 7) -> dict[str, Any]:
        """
        获取推送统计信息（从审计日志中汇总）
        
        Args:
            day_range: 统计天数范围
            
        Returns:
            统计数据字典
        """
        audit_dir = "./audit_logs"
        stats = {
            "total_pushes": 0,
            "successes": 0,
            "failures": 0,
            "rate_limited": 0,
            "by_platform": {}
        }

        if not Path(audit_dir).exists():
            return stats

        cutoff_date = (datetime.now() - timedelta(days=day_range)).strftime("%Y-%m-%d")

        for log_file in Path(audit_dir).glob("*.jsonl"):
            if log_file.name < f"compliance_{cutoff_date}":
                continue

            try:
                with open(log_file, encoding='utf-8') as f:
                    for line in f:
                        entry = json.loads(line.strip())
                        if entry.get("status") != "PASS":
                            continue

                        # 统计（此处为示例逻辑，实际应解析专门的推送日志）
                        stats["total_pushes"] += 1

            except Exception as e:
                logger.debug(f"读取日志文件跳过: {log_file} ({e})")

        return stats


# ==================== CLI命令行接口 ====================
def main():
    """命令行入口"""
    import argparse

    parser = argparse.ArgumentParser(
        description="021kp.com GEO Phase 4: API路由与LBS注入模块"
    )

    parser.add_argument("--url", "-u", required=True, help="要推送的URL")
    parser.add_argument("--title", "-t", default="松江最新招聘信息", help="标题")
    parser.add_argument("--description", "-d", default="", help="描述文本")
    parser.add_argument(
        "--platforms", "-p",
        default="wechat,douyin,baidu",
        help="目标平台列表(逗号分隔): wechat/douyin/baidu"
    )
    parser.add_argument("--lbs-tag", default=None, help="LBS地理标签")

    args = parser.parse_args()

    signaler = AuthSignaler()
    platforms = [p.strip() + ("_yuanbao" if p.strip() == "wechat" else "_doubao" if p.strip() == "douyin" else "_wenxin")
                 for p in args.platforms.split(",")]

    results = signaler.push_to_platforms(
        url=args.url,
        title=args.title,
        description=args.description,
        platforms=platforms,
        lbs_tag=args.lbs_tag
    )

    print("\n" + "=" * 60)
    print("📡 推送结果报告")
    print("=" * 60)

    for r in results:
        status_icon = {
            PushStatus.SUCCESS: "✅",
            PushStatus.RATE_LIMITED: "⏳",
            PushStatus.AUTH_FAILED: "🔑",
            PushStatus.FAILED: "❌"
        }.get(r.status, "❓")

        print(f"\n  {status_icon} {r.platform.upper()}")
        print(f"     状态: {r.status.value}")
        print(f"     响应: {r.response_code} | {r.response_message}")
        if r.push_id:
            print(f"     ID:   {r.push_id}")

    print("\n" + "=" * 60)


if __name__ == "__main__":
    main()
