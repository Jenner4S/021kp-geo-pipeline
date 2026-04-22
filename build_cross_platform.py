#!/usr/bin/env python3
"""
021kp GEO Pipeline - 跨平台一键构建脚本
============================================
通过 PyInstaller 为 macOS / Linux / Windows 生成单文件可执行程序。
支持原生构建和 Docker 交叉编译。

用法:
  # 原生构建(当前平台)
  python build_cross_platform.py
  
  # 构建指定平台
  python build_cross_platform.py --platform macos
  python build_cross_platform.py --platform linux
  python build_cross_platform.py --platform windows
  
  # 全部构建(当前平台 + Docker 跨平台)
  python build_cross_platform.py --all
  
  # 仅使用 Docker 构建
  python build_cross_platform.py --all --docker-only

作者: GEO-Engine Team | v2.0 | 2026-04-21
"""

import argparse
import os
import subprocess
import sys
import platform
import shutil
import time
from pathlib import Path

# ======================== 配置 ========================
PROJECT_NAME = "021kp-geo-pipeline"
VERSION = "2.1.0"
PROJECT_ROOT = Path(__file__).parent.resolve()
SRC_DIR = PROJECT_ROOT / "src"
DIST_DIR = PROJECT_ROOT / "dist" / "packages"
ENTRY_POINT = SRC_DIR / "main.py"

# 隐藏导入列表 (基于实际代码分析)
HIDDEN_IMPORTS = [
    # 核心业务模块
    "compliance_gate",
    "intent_router",
    "content_factory",
    "auth_signaler",
    "dist_monitor",
    "database_connector",
    "database_backend",
    "config_manager",
    "config_schema",
    "web_ui",
    "exceptions",
    "config_store",
    # 第三方库
    "loguru",
    "jinja2",
    "lxml",
    "lxml.etree",
    "yaml",
    "requests",
    "python_dateutil",
    "schedule",
    "pydantic",
    # 标准库补充
    "csv",
    "json",
    "datetime",
    "threading",
    "argparse",
    "io",
    "html",
    "re",
    "urllib.parse",
    "http.server",
    "signal",
    "json",
]

# 排除模块
EXCLUDES = [
    "tkinter", "matplotlib", "numpy.f2py", "PIL", "scipy",
    "notebook", "IPython", "jupyter", "pytest", "sphinx",
]

# 数据文件
DATAS = [
    ("config", "config"),
    ("data", "data"),
]

# ======================== 工具函数 ========================
def log(level: str, msg: str):
    colors = {"INFO": "\033[0;34m", "OK": "\033[0;32m", "WARN": "\033[1;33m", "ERROR": "\033[0;31m", "NC": "\033[0m"}
    c = colors.get(level, "")
    print(f"{c}[{level}]{colors['NC']} {msg}")


def check_uv() -> bool:
    """检查 uv 是否可用"""
    return shutil.which("uv") is not None


def check_docker() -> bool:
    """检查 Docker 是否可用"""
    try:
        r = subprocess.run(["docker", "--version"], capture_output=True, timeout=10)
        return r.returncode == 0
    except Exception:
        return False


def detect_host_platform() -> str:
    s = system := platform.system()
    m = platform.machine()
    if s == "Darwin":
        return f"macos-{m}"
    elif s == "Linux":
        return f"linux-{m}"
    elif s == "Windows":
        return f"windows-{m}"
    return "unknown"


def get_pyinstaller_args(platform_name: str, output_name: str) -> list:
    """生成 PyInstaller 参数"""
    args = [
        "pyinstaller",
        "--name", output_name,
        "--onefile",
        "--console",
        "--clean",
        "--noconfirm",
        "--log-level=ERROR",
        str(ENTRY_POINT),
    ]
    
    # 隐式 imports
    for imp in HIDDEN_IMPORTS:
        args += ["--hidden-import", imp]
    
    # 数据文件
    for src, dst in DATAS:
        if (PROJECT_ROOT / src).exists():
            args += ["--add-data", f"{src}{os.pathsep}{dst}"]
    
    # 静态资源 (可选)
    static_dir = PROJECT_ROOT / "static"
    if static_dir.exists():
        args += ["--add-data", f"static{os.pathsep}static"]
    
    # 排除模块
    for mod in EXCLUDES:
        args += ["--exclude-module", mod]
    
    # 平台特定选项
    plat_lower = platform_name.lower()
    if "windows" in plat_lower:
        args.extend(["--windowed"])  # Windows 控制台模式
        # UPX 压缩 (减小体积)
        if shutil.which("upx"):
            args.append("--upx-dir=" + os.path.dirname(shutil.which("upx")))
    elif "macos" in plat_lower:
        # macOS 通用二进制 (Apple Silicon + Intel)
        pass
    
    return args


def build_native(platform_id: str) -> bool:
    """在当前系统上原生构建"""
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    
    # 确定输出名称
    host = detect_host_platform()
    if "windows" in host.lower():
        ext = ".exe"
    else:
        ext = ""
    
    output_name = f"{PROJECT_NAME}-{platform_id}{ext}"
    log("INFO", f"构建目标: {output_name}")
    log("INFO", f"主机平台: {host}")
    
    # 安装依赖
    log("INFO", "安装/更新 PyInstaller...")
    r = subprocess.run(
        ["uv", "pip", "install", "pyinstaller>=6.0", "--quiet"],
        cwd=PROJECT_ROOT,
        capture_output=True,
    )
    if r.returncode != 0:
        # 回退到 pip
        subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller>=6.0", "-q"],
                       cwd=PROJECT_ROOT)
    
    # 执行 PyInstaller
    args = get_pyinstaller_args(platform_id, output_name)
    log("INFO", f"运行: {' '.join(args[:5])}...")
    
    r = subprocess.run(args, cwd=PROJECT_ROOT)
    if r.returncode != 0:
        log("ERROR", f"PyInstaller 构建失败 (exit code: {r.returncode})")
        return False
    
    # 移动产物
    built = PROJECT_ROOT / "dist" / output_name
    if not built.exists():
        # 尝试不带平台后缀查找
        alt = list(PROJECT_ROOT.glob(f"dist/{PROJECT_NAME}*"))
        if alt:
            built = alt[0]
        else:
            log("ERROR", f"未找到构建产物: {built}")
            return False
    
    target = DIST_DIR / built.name
    shutil.move(str(built), str(target))
    
    size_mb = target.stat().st_size / (1024 * 1024)
    log("OK", f"✅ 构建成功: {target.name} ({size_mb:.1f} MB)")
    return True


def build_in_docker(platform_id: str, docker_image: str, arch: str = "auto") -> bool:
    """在 Docker 容器中构建"""
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    
    if "windows" in platform_id.lower():
        ext = ".exe"
    else:
        ext = ""
    
    output_name = f"{PLATFORM_ALIASES.get(platform_id, platform_id)}{ext}" if ext else f"{PROJECT_NAME}-{platform_id}{ext}"
    if "windows" in platform_id.lower():
        output_name = f"{PROJECT_NAME}-windows.exe"
    else:
        output_name = f"{PROJECT_NAME}-{platform_id}"
    
    log("INFO", f"Docker 构建 [{arch}]: {output_name}")
    log("INFO", f"镜像: {docker_image}")
    
    # Docker 构建命令 - 将项目挂载进去并在容器内执行 pyinstaller
    # 使用 --platform 指定架构
    docker_cmd = [
        "docker", "run", "--rm",
        "-v", f"{PROJECT_ROOT}:/app/project",
        "-w", "/app/project",
        "-e", "PYINSTALLER_COMPILE=1",
    ]
    
    if arch != "auto":
        docker_cmd.extend(["--platform", f"linux/{arch}"])
    
    docker_cmd.extend([
        docker_image,
        "bash", "-c",
        f"""
        set -e
        apt-get update -qq && apt-get install -y -qq > /dev/null 2>&1 || true
        
        # 安装 Python + pip
        which python3 || apt-get install -y -qq python3 python3-pip python3-venv > /dev/null 2>&1 || true
        
        # 安装 uv
        curl -LsSf https://astral.sh/uv/install.sh | sh > /dev/null 2>&1 || true
        export PATH="$HOME/.local/bin:$PATH:/root/.local/bin:/root/.cargo/bin:$PATH"
        
        which uv || (curl -LsSf https://astral.sh/uv/install.sh | sh)
        
        cd /app/project
        
        # 创建虚拟环境并安装依赖
        uv venv --python 3.12 /tmp/build-env 2>/dev/null || true
        . /tmp/build-env/bin/activate
        
        uv pip install -e "." --quiet 2>/dev/null || pip install -e . -q
        uv pip install pyinstaller>=6.0 --quiet 2>/dev/null || pip install pyinstaller -q
        
        # 清理旧的构建产物
        rm -rf dist/{output_name} build/
        
        # PyInstaller 参数
        PYARGS=(
            --name {output_name}
            --onefile
            --console
            --clean
            --noconfirm
            --log-level=ERROR
            {' '.join('--hidden-import ' + imp for imp in HIDDEN_IMPORTS)}
            {' '.join('--add-data ' + f"{s}{os.pathsep}{d}" for s, d in DATAS if (Path(s).exists()))}
            {' '.join('--exclude-module ' + m for m in EXCLUDES)}
            src/main.py
        )
        
        echo "=== Running PyInstaller ==="
        pyinstaller "${{PYARGS[@]}}"
        
        # 输出结果信息
        if [ -f "dist/{output_name}" ]; then
            ls -lh dist/{output_name}
            cp dist/{output_name} /app/project/dist/packages/{output_name} 2>/dev/null || true
            mv dist/{output_name} /app/project/dist/packages/ 2>/dev/null || true
            echo "BUILD_OK"
        else
            echo "BUILD_FAILED"
            ls -la dist/ 2>/dev/null || true
            exit 1
        fi
        """
    ])
    
    log("INFO", "启动 Docker 容器构建...")
    r = subprocess.run(docker_cmd, capture_output=True, text=True, timeout=600)
    
    if r.stdout:
        for line in r.stdout.strip().split("\n"):
            if line.strip():
                print(f"  [docker] {line}")
    if r.stderr and "BUILD_OK" not in r.stdout:
        for line in r.stderr.strip().split("\n")[-20:]:
            if line.strip() and "warning" not in line.lower():
                print(f"  [docker-err] {line}", file=sys.stderr)
    
    if "BUILD_OK" in r.stdout:
        target = DIST_DIR / output_name
        if target.exists():
            size_mb = target.stat().st_size / (1024 * 1024)
            log("OK", f"Docker 构建成功: {output_name} ({size_mb:.1f} MB)")
            return True
    
    log("ERROR", f"Docker 构建失败")
    return False


# 平台别名映射
PLATFORM_ALIASES = {
    "macos-arm64": "macos-arm64",
    "macos-x86_64": "macos-x86_64",
    "linux-x86_64": "linux-amd64",
    "linux-aarch64": "linux-arm64",
    "windows-x86_64": "windows-x86_64",
}

DOCKER_IMAGES = {
    "linux-amd64": "python:3.12-slim",
    "linux-arm64": "python:3.12-slim",
    "windows-x86_64": "ghcr.io/pyinstaller/pyinstaller-windows:latest",  # 官方 PyInstaller Windows 交叉编译镜像
}


def main():
    parser = argparse.ArgumentParser(description="GEO Pipeline 跨平台构建工具",
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--platform", "-p",
                        choices=["macos", "linux", "windows", "all"],
                        default=None,
                        help="目标平台 (默认: 自动检测当前平台)")
    parser.add_argument("--all", "-a", action="store_true", help="构建所有平台")
    parser.add_argument("--docker-only", action="store_true", help="仅使用 Docker 构建跳过原生构建")
    parser.add_argument("--clean", action="store_true", help="清理后重新构建")
    parser.add_argument("--list", action="store_true", help="仅列出可构建的平台")
    
    args = parser.parse_args()
    
    # 列出平台
    if args.list:
        host = detect_host_platform()
        print("可用构建目标:")
        print(f"  [native]  {host} (当前主机)")
        print(f"  [docker]  linux-amd64  (需 Docker)")
        print(f"  [docker]  linux-arm64  (需 Docker)")
        print(f"  [docker]  windows-x86_64 (需 Docker + mingw)")
        return
    
    # 清理
    if args.clean:
        import glob
        log("INFO", "清理构建缓存...")
        for d in ["build", "__pycache__"]:
            p = PROJECT_ROOT / d
            if p.exists():
                shutil.rmtree(p)
        for pattern in ["src/__pycache__", "**/__pycache__"]:
            for p in PROJECT_ROOT.glob(pattern):
                if p.is_dir():
                    shutil.rmtree(p)
        log("OK", "清理完成")
    
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    results = {}
    
    host = detect_host_platform()
    log("INFO", f"GEO Pipeline Cross-Platform Builder v{VERSION}")
    log("INFO", f"项目根目录: {PROJECT_ROOT}")
    log("INFO", f"输出目录:   {DIST_DIR}")
    log("INFO", f"主机平台:   {host}")
    print()
    
    targets = []
    
    if args.all or args.platform == "all":
        # 确定所有要构建的目标
        if "darwin" in platform.system().lower() and not args.docker_only:
            targets.append(("macos-arm64", "native"))
        targets.extend([
            ("linux-amd64", "docker"),
            ("linux-arm64", "docker"),
            ("windows-x86_64", "docker"),
        ])
    elif args.platform:
        plat = args.platform.lower()
        if plat == "macos" and "darwin" in platform.system().lower() and not args.docker_only:
            targets.append((host, "native"))
        elif plat == "linux":
            targets.extend([(f, "docker") for f in ["linux-amd64", "linux-arm64"]])
        elif plat == "windows":
            targets.append(("windows-x86_64", "docker"))
    else:
        # 默认: 构建当前平台
        if not args.docker_only:
            targets.append((host, "native"))
    
    if not targets:
        if not args.docker_only:
            targets.append((host, "native"))
    
    # 执行构建
    for platform_id, method in targets:
        print(f"\n{'='*60}")
        log("INFO", f"▶ 构建: {platform_id} ({method})")
        print(f"{'='*60}\n")
        
        start = time.time()
        
        if method == "native":
            ok = build_native(platform_id)
        elif method == "docker":
            image = DOCKER_IMAGES.get(platform_id, "python:3.12-slim")
            arch = "amd64" if "amd64" in platform_id else ("arm64" if "arm64" in platform_id else "x86_64")
            ok = build_in_docker(platform_id, image, arch)
        else:
            ok = False
        
        elapsed = time.time() - start
        status = "✅ PASS" if ok else "❌ FAIL"
        results[platform_id] = {"ok": ok, "time": elapsed}
        log("INFO", f"{status} | 耗时: {elapsed:.1f}s\n")
    
    # ==================== 汇总 ========================
    print(f"\n{'='*60}")
    log("INFO", "📊 构建汇总")
    print(f"{'='*60}")
    
    all_ok = True
    for pid, info in results.items():
        icon = "✅" if info["ok"] else "❌"
        print(f"  {icon} {pid:<20} {info['time']:>6.1f}s")
        if not info["ok"]:
            all_ok = False
    
    print()
    
    # 列出产物
    artifacts = sorted(DIST_DIR.iterdir(), key=lambda x: x.stat().st_size, reverse=True)
    if artifacts:
        log("INFO", "📦 产出文件:")
        for f in artifacts:
            size_mb = f.stat().st_size / (1024 * 1024)
            print(f"     📄 {f.name:<45} {size_mb:>7.1f} MB")
    
    print()
    if all_ok:
        log("OK", "全部平台构建完成!")
    else:
        log("WARN", "部分平台构建失败，请检查上方日志。")
        sys.exit(1)


if __name__ == "__main__":
    main()
