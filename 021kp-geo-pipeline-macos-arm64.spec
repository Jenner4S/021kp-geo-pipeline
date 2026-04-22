# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['src/main.py'],
    pathex=[],
    binaries=[],
    datas=[('config', 'config'), ('data', 'data'), ('static', 'static')],
    hiddenimports=[
        'compliance_gate', 'intent_router', 'content_factory', 'auth_signaler',
        'dist_monitor', 'database_connector', 'database_backend',
        'config_manager', 'config_schema', 'web_ui',
        'loguru', 'jinja2', 'lxml', 'lxml.etree', 'yaml', 'requests',
        'pydantic', 'pydantic_settings', 'schedule',
        'dateutil', 'dateutil.parser', 'dateutil.tz',
        'csv', 'json', 'argparse', 'io', 'html', 're',
        'hashlib', 'pathlib', 'sqlite3', 'threading', 'datetime', 'os', 'sys',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='021kp-geo-pipeline-macos-arm64',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
