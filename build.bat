@echo off
REM ============================================================
REM 021kp GEO Pipeline - Windows 打包脚本
REM ============================================================
REM 用法: 双击运行 或 cmd> build.bat
REM 输出: dist\packages\
REM ============================================================

echo.
echo ========================================
echo   021kp GEO Pipeline - Windows Packager
echo ========================================
echo.

REM 检查uv
where uv >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] uv not installed!
    echo Install: winget install astral-sh.uv
    pause
    exit /b 1
)

echo [OK] uv detected

REM 初始化环境
if not exist ".venv" (
    echo [INFO] Creating virtual environment...
    uv venv --python 3.12 .venv
)

echo [INFO] Syncing dependencies...
uv sync

REM 安装PyInstaller
uv pip install pyinstaller --quiet

REM 构建参数
set OUTPUT_NAME=021kp-geo-pipeline-windows.exe
set BUILD_DIR=dist\packages

if not exist "%BUILD_DIR%" mkdir "%BUILD_DIR%"

echo.
echo [INFO] Building Windows executable...
echo.

uv run pyinstaller ^
    --name=%OUTPUT_NAME% ^
    --onefile ^
    --console ^
    --clean ^
    --noconfirm ^
    --hidden-import=compliance_gate ^
    --hidden-import=intent_router ^
    --hidden-import=content_factory ^
    --hidden-import=auth_signaler ^
    --hidden-import=dist_monitor ^
    --hidden-import=database_connector ^
    --hidden-import=loguru ^
    --hidden-import=jinja2 ^
    --hidden-import=pandas ^
    --hidden-import=bs4 ^
    --hidden-import=lxml ^
    --add-data="config;config" ^
    --add-data="data;data" ^
    --exclude-module=tkinter ^
    --exclude-module=matplotlib ^
    src\main.py

if exist "dist\%OUTPUT_NAME%" (
    move /Y "dist\%OUTPUT_NAME%" "%BUILD_DIR%\"
    echo.
    echo [SUCCESS] Build complete!
    echo [OUTPUT] %BUILD_DIR%\%OUTPUT_NAME%
    for %%A in ("%BUILD_DIR%\%OUTPUT_NAME%") do echo [SIZE]  %%~zA bytes
) else (
    echo.
    echo [ERROR] Build failed!
)

echo.
pause
