# 变更日志 (CHANGELOG)

所有重要的版本变更都会记录在此。

格式基于 [Keep a Changelog](https://keepachangelog.com/)。

## [2.0.0] - 2026-04-22

### 新增
- GitHub Actions 多平台 CI/CD（Windows x64 / macOS ARM64 / Linux AMD64）
- `pyproject.toml` 项目配置（uv 生态支持）
- 完整的单元测试套件（pytest）
- Web UI 静态资源（static/）

### 修复
- PyInstaller spec 文件 `__file__` 作用域问题（适配 CI 环境）
- macOS 构建缺少 `data/` 目录文件
- `.gitignore` 误排除 spec 文件

### 变更
- 切换到 `pip install pyinstaller` 替代 `uv run pyinstaller`
- 移除 Linux ARM64 交叉编译（GitHub 原生 runners 不支持）
- 默认分支从 `master` 改为 `main`（CI 已同时支持）

### 已知问题
- Linux ARM64 交叉编译待后续 CI 平台支持
- macOS Intel x86_64 需单独构建（Universal2 因第三方 .so 库限制不可行）

## [1.x] - 历史版本
> 暂无详细记录
