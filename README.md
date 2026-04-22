# 松江快聘(021kp.com) GEO自动化运营系统

## 项目概述

本项目为 **松江快聘网 (021kp.com)** 设计的**生成式搜索引擎优化(GEO)全自动化运营管道**，采用软件工程方法论构建，实现从原始岗位数据到AI平台引用的全链路自动化。

### 核心能力

| 阶段 | 模块 | 功能 | 验收标准 |
|------|------|------|----------|
| Phase 1 | 合规闸门 (Compliance Gate) | 禁词过滤 + 显隐双标注入 | 100%资产过审 |
| Phase 2 | 意图路由器 (Intent Router) | 语义向量提取 + 平台映射 | 覆盖≥12类意图 |
| Phase 3 | 内容工厂 (Content Factory) | Schema JSON-LD + TL;DR渲染 | Schema验证100% |
| Phase 4 | API路由器 (Auth Signaler) | 微信/抖音/百度推送 + LBS标签 | API成功率≥99% |
| Phase 5 | 分发监控器 (Dist Monitor) | 引用率监控 + 自动回滚 | <0.5%触发告警 |

---

## 快速开始

### 环境要求

- Python >= 3.10
- pip / pipenv
- Docker (可选)

### 安装与运行

```bash
# 1. 克隆/进入项目目录
cd 021kp-geo-pipeline

# 2. 创建虚拟环境并安装依赖
python -m venv .venv && source .venv/bin/activate  # Mac/Linux
# .venv\Scripts\activate                             # Windows

pip install -r requirements.txt

# 3. 配置环境变量（可选）
cp config/settings.yaml config/settings.local.yaml
# 编辑 settings.local.yaml 填入平台API凭证

# 4. 运行完整流水线
python -m src.main --mode pipeline --csv data/jobs.csv

# 5. 启动HTTP服务模式
python -m src.main --mode server --port 8080

# 6. 运行测试套件
pytest tests/test_geo_pipeline.py -v --cov=src
```

### 单模块独立运行

```bash
# Phase 1: 合规处理
python src/compliance_gate.py --input raw.html --output clean.html

# Phase 2: 意图路由
python src/intent_router.py --csv data/jobs.csv --output vectors.json

# Phase 3: Schema生成
python src/content_factory.py --json '{"title":"松江急招"}'

# Phase 4: API推送
python src/auth_signaler.py --url https://021kp.com/job/123

# Phase 5: 监控检查
python src/dist_monitor.py --mode check
```

---

## 项目结构

```
021kp-geo-pipeline/
├── src/                          # 核心源代码
│   ├── compliance_gate.py        # Phase 1: 合规闸门
│   ├── intent_router.py          # Phase 2: 意图路由器
│   ├── content_factory.py        # Phase 3: 内容工厂(Schema)
│   ├── auth_signaler.py          # Phase 4: API路由调度器
│   ├── dist_monitor.py           # Phase 5: 分发监控器
│   └── main.py                  # 主入口模块
├── config/                       # 配置文件区
│   ├── settings.yaml             # 核心配置模板
│   ├── ban_words.txt            # 招聘行业禁词库
│   └── platform_mapping.json    # AI平台路由规则
├── tests/                        # 测试用例
│   └── test_geo_pipeline.py      # 全流程测试套件
├── workflows/                    # CI/CD流水线
│   └── github_actions.yml        # GitHub Actions配置
├── dist/                         # 输出目录（自动生成）
│   ├── schema.jsonld             # 结构化数据
│   ├── posts.md                  # Markdown内容
│   └── reports/                  # 监控报告
├── audit_logs/                   # 审计日志（自动生成）
├── Dockerfile                    # 容器化配置
├── requirements.txt              # Python依赖
└── README.md                     # 本文档
```

---

## 合规声明

本系统严格遵循以下法规：

| 法规 | 实现方式 |
|------|---------|
| 《标识办法》(2025) | 显式文本+隐式Meta双标 |
| 《深度合成规定》 | 日志留存≥180天 + 特征库过滤 |
| 《个保法》 | PII字段脱敏 + 本地存储不出境 |
| 招聘行业规范 | "包过/稳赚"等禁词正则拦截 |

---

## 技术栈

- **语言**: Python 3.12+
- **框架**: 原生实现（无重型框架依赖）
- **数据校验**: Pydantic + Loguru 结构化日志
- **模板渲染**: Jinja2 (Markdown/Schema.org)
- **HTTP请求**: requests (同步) / schedule (定时调度)
- **数据库**: SQLite(默认) / MySQL(生产)
- **解析**: lxml (HTML合规标记注入)
- **配置管理**: PyYAML + 环境变量
- **容器化**: Docker
- **CI/CD**: GitHub Actions / GitLab CI

---

## 监控与运维

### 关键指标

| 指标 | 目标值 | 触发条件 |
|------|--------|----------|
| AI引用率 | ≥5% (14天) | <0.5% → 回滚 |
| API成功率 | ≥99% | <95% → 切换路由 |
| 合规过审率 | 100% | <100% → 阻断发布 |

### 告警通知

支持企业微信/钉钉 Webhook 推送，配置方式：
```bash
export ALERT_WEBHOOK_URL="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=YOUR_KEY"
```

---

## 版本信息

- **版本**: v2.0.0 (动态配置 + 多数据库)
- **发布日期**: 2026-04-21
- **适用网站**: https://www.021kp.com
- **目标市场**: 中国大陆（上海松江区域）

---

## License

本项目仅供松江快聘网内部使用。
