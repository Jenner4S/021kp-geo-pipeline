# 021kp.com GEO Pipeline - Dockerfile (uv优化版)
# 版本: v2.0 | 使用 uv 管理依赖 (比pip快10-100x)
# 多阶段构建: 基础层 → 依赖层 → 运行层

# ==================== 阶段1: 基础环境 ====================
FROM python:3.12-slim AS base

# 安装uv(比pip快10-100x)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
# 设置时区与Python优化参数
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ="Asia/Shanghai" \
    UV_CACHE_DIR=/root/.cache/uv

# 安装系统依赖(lxml编译需要)
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc libxml2-dev libxslt1-dev curl \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /uv /usr/local/bin/uv

WORKDIR /app

# ==================== 阶段2: 依赖安装 ====================
FROM base AS deps

# 先复制依赖定义文件
COPY pyproject.toml ./

# 使用uv高速安装(自动创建虚拟环境+锁定依赖)
RUN uv pip install --system -e ".[production]" \
    && rm -rf $UV_CACHE_DIR

# ==================== 阶段3: 生产运行 ====================
FROM python:3.12-slim AS production

# 复制uv和已安装的依赖(避免重复下载)
COPY --from=base /uv /uvx /bin/
COPY --from=deps /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=deps /usr/local/bin /usr/local/bin

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ="Asia/Shanghai"

# 创建非root用户
RUN groupadd --gid 1000 geoapp \
    && useradd --uid 1000 --gid geoapp --create-home geouser \
    && mkdir -p /app/dist /app/audit_logs \
    && chown -R geouser:geoapp /app

USER geouser
WORKDIR /app

# 复制应用代码
COPY --chown=geouser:geoapp src/ ./src/
COPY --chown=geouser:geoapp config/ ./config/
COPY --chown=geouser:geoapp data/ ./data/

# 健康检查
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["/uv", "run", "python", "-c", \
         "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"]

EXPOSE 8080

# 默认启动HTTP服务模式
CMD ["uv", "run", "python", "-m", "src.main", "--mode", "server", "--port", "8080"]

# ==================== 阶段4: 开发调试 ====================
FROM base AS development

COPY . .

# 开发依赖
RUN uv pip install --system -e ".[dev]" \
    && rm -rf $UV_CACHE_DIR

CMD ["uv", "run", "pytest", "tests/", "-v"]

# ==================== 构建示例 ====================
#
# # 本地构建:
# docker build -t 021kp-geo-pipeline:latest .
# docker run -p 8080:8080 -v $(pwd)/config:/app/config 021kp-geo-pipeline:latest
#
# # 多架构构建(ARM64+AMD64):
# docker buildx build --platform linux/amd64,linux/arm64 \
#   -t 021kp/geo-pipeline:v1.1.0 --output type=docker .
#
# # 使用docker-compose(推荐生产):
# docker-compose up -d
