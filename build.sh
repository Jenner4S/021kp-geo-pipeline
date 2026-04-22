#!/usr/bin/env bash
# ============================================================
# 021kp GEO Pipeline - 跨平台打包脚本 (uv + PyInstaller)
# ============================================================
# 用途: 一键生成 macOS / Linux / Windows 可执行文件
# 前提: 已安装 uv (curl -LsSf https://astral.sh/uv/install.sh | sh)
#
# 使用方法:
#   ./build.sh              # 打包当前平台
#   ./build.sh --all        # 打包所有平台(需要对应环境的CI/CD)
#   ./build.sh --docker     # 通过Docker交叉编译
#   ./build.sh --clean      # 清理构建缓存
#
# 输出目录: dist/packages/
# 作者: GEO-Engine Team | 版本: v1.1 | 日期: 2026-04-21
# ============================================================

set -e

# ==================== 颜色定义 ====================
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# ==================== 项目根目录 ====================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
PROJECT_NAME="021kp-geo-pipeline"
VERSION="1.1.0"
BUILD_DIR="dist/packages"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

# ==================== 工具函数 ====================
log_info()  { echo -e "${BLUE}[INFO]${NC} $*"; }
log_ok()    { echo -e "${GREEN}[OK]${NC} $*"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_error() { echo -e "${RED}[ERROR]${NC} $*"; }

check_uv() {
    if ! command -v uv &>/dev/null; then
        log_error "uv 未安装!"
        echo "安装方式: curl -LsSf https://astral.sh/uv/install.sh | sh"
        exit 1
    fi
    log_ok "uv $(uv --version)"
}

check_pyinstaller() {
    if ! uv run python -c "import PyInstaller" 2>/dev/null; then
        log_info "安装 PyInstaller..."
        uv add --dev pyinstaller || pip install pyinstaller
    fi
}

detect_platform() {
    case "$(uname -s)" in
        Darwin)  echo "macos" ;;
        Linux)   echo "linux" ;;
        MINGW*|CYGWIN*|MSYS*) echo "windows" ;;
        *)       echo "unknown" ;;
    esac
}

# ==================== 核心流程 ====================
step_init() {
    log_info "===== 初始化环境 ====="
    check_uv
    
    # 创建虚拟环境(如果不存在)
    if [ ! -d ".venv" ]; then
        log_info "创建虚拟环境..."
        uv venv --python 3.12 .venv
    fi
    
    # 同步依赖
    log_info "同步Python依赖..."
    uv pip install -e ".[production]" --quiet || uv sync
    
    log_ok "环境就绪 ✓"
}

step_build() {
    local platform="$1"
    local output_name="${PROJECT_NAME}-${platform}"
    
    log_info "===== 构建 ${platform} 包 ====="
    
    mkdir -p "$BUILD_DIR"
    
    # PyInstaller 配置
    local PYINSTALLER_OPTS=(
        --name="$output_name"
        --onefile                    # 单文件输出
        --console                    # 控制台应用(保留日志可见性)
        --clean                      # 清理临时文件
        --noconfirm                  # 覆盖已有文件
        --log-level=ERROR            # 减少PyInstaller噪音
        
        # 隐式导入(解决动态导入问题)
        --hidden-import=compliance_gate
        --hidden-import=intent_router
        --hidden-import=content_factory
        --hidden-import=auth_signaler
        --hidden-import=dist_monitor
        --hidden-import=database_connector
        --hidden-import=loguru
        --hidden-import=jinja2
        --hidden-import=pandas
        --hidden-import=bs4
        --hidden-import=lxml
        --hidden-import=yaml
        --hidden-import=requests
        --hidden-import=httpx
        --hidden-import=schedule
        --hidden-import=mysql.connector
        
        # 数据文件(必须包含)
        --add-data="config:config"
        --add-data="data:data"
        
        # 排除不需要的模块(减小包体积)
        --exclude-module=tkinter
        --exclude-module=matplotlib
        --exclude-module=numpy.f2py
        --exclude-module=PIL
        
        # 入口点
        "src/main.py:main"
    )
    
    # 平台特定优化
    case "$platform" in
        macos)
            PYINSTALLER_OPTS+=(
                --icon=assets/icon.icns 2>/dev/null || true
            )
            ;;
        linux)
            PYINSTALLER_OPTS+=(
                --icon=assets/icon.png 2>/dev/null || true
            )
            ;;
        windows)
            PYINSTALLER_OPTS+=(
                --icon=assets/icon.ico 2>/dev/null || true
                --windowed  # Windows可选GUI模式
            )
            output_name="${output_name}.exe"
            ;;
    esac
    
    # 执行打包
    uv run pyinstaller "${PYINSTALLER_OPTS[@]}"
    
    # 移动到packages目录
    if [ -f "dist/${output_name}" ]; then
        mv "dist/${output_name}" "${BUILD_DIR}/"
        log_ok "生成: ${BUILD_DIR}/${output_name}"
        
        # 显示文件大小
        local size=$(du -h "${BUILD_DIR}/${output_name}" | cut -f1)
        log_info "文件大小: ${size}"
    else
        log_error "构建失败! 请检查上方错误信息"
        return 1
    fi
}

step_package() {
    log_info "===== 生成分发包归档 ====="
    
    cd "$BUILD_DIR"
    
    local archive_name="${PROJECT_NAME}-v${VERSION}-${TIMESTAMP}-$(uname -s)"
    
    # 创建分发压缩包
    case "$(detect_platform)" in
        macos|linux)
            tar -czvf "${archive_name}.tar.gz" \
                *.zip *.exe 2>/dev/null \
                ../../README.md \
                ../../.env.example \
                ../../config/settings.local.yaml.template \
                ../../config/crontab.example \
                2>/dev/null || true
            
            # 也创建独立zip
            zip -r "${archive_name}.zip" *.zip *.exe *.app 2>/dev/null \
                ../../README.md ../../.env.example \
                ../../config/settings.local.yaml.template 2>/dev/null || true
            ;;
        windows)
            powershell Compress-Archive -Path * -DestinationPath "${archive_name}.zip"
            ;;
    esac
    
    cd ..
    log_ok "分发包已生成:"
    ls -lh "${BUILD_DIR}/${archive_name}".*
}

step_docker_build() {
    log_info "===== Docker 多架构构建 ====="
    
    # 构建多平台镜像
    docker buildx build \
        --platform linux/amd64,linux/arm64 \
        -t "021kp/geo-pipeline:${VERSION}" \
        -t "021kp/geo-pipeline:latest" \
        --output "type=docker,prefix=${BUILD_DIR}/docker/" \
        .
    
    log_ok "Docker镜像已导出至 ${BUILD_DIR}/docker/"
}

step_clean() {
    log_info "清理构建缓存..."
    rm -rf build/ *.spec dist/*.exe dist/*.zip dist/*.app 2>/dev/null || true
    rm -rf __pycache__ src/__pycache__ **/__pycache__ 2>/dev/null || true
    log_ok "清理完成"
}

# ==================== 主入口 ====================
main() {
    local cmd="${1:-build}"
    
    case "$cmd" in
        init)
            step_init
            ;;
        build)
            step_init
            local plat="$(detect_platform)"
            step_build "$plat"
            step_package
            ;;
        --all|--cross)
            step_init
            log_warn "跨平台构建需要在各目标OS上分别运行此脚本"
            log_info "当前平台: $(detect_platform)"
            step_build "$(detect_platform)"
            step_package
            ;;
        --docker)
            step_docker_build
            ;;
        --clean)
            step_clean
            ;;
        --help|-h)
            echo "用法: $0 [命令]"
            echo ""
            echo "命令:"
            echo "  init          初始化虚拟环境和依赖"
            echo "  build         打包当前平台可执行文件 (默认)"
            echo "  --all         打包当前平台(跨平台别名)"
            echo "  --docker      构建Docker多架构镜像"
            echo "  --clean       清理构建缓存"
            echo "  --help        显示帮助"
            echo ""
            echo "示例:"
            echo "  $0                    # macOS/Linux: 生成单文件可执行程序"
            echo "  $0 --clean && $0      # 清理后重新构建"
            echo "  uvx ${PROJECT_NAME}   # 直接通过uvx运行"
            ;;
        *)
            log_error "未知命令: $cmd"
            echo "使用 $0 --help 查看帮助"
            exit 1
            ;;
    esac
    
    echo ""
    log_info "===== 构建完成 ====="
    log_info "输出目录: $(realpath "$BUILD_DIR")"
}

main "$@"
