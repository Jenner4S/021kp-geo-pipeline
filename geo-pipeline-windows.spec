# -*- mode: python ; coding: utf-8 -*-
import os
from pathlib import Path

block_cipher = None
SPECROOT = Path(os.getcwd())

a = Analysis(
    ['src/main.py'],
    pathex=[str(SPECROOT)],
    binaries=[],
    datas=[
        (str(SPECROOT / 'config'), 'config'),
        (str(SPECROOT / 'data'), 'data'),
    ],
    hiddenimports=[
        'compliance_gate',
        'intent_router',
        'content_factory',
        'auth_signaler',
        'dist_monitor',
        'database_connector',
        'database_backend',
        'config_manager',
        'config_schema',
        'web_ui',
        'loguru',
        'jinja2',
        'lxml',
        'lxml.etree',
        'yaml',
        'requests',
        'pydantic',
        'pydantic_settings',
        'schedule',
        'dateutil',
        'dateutil.parser',
        'dateutil.tz',
        'csv',
        'json',
        'argparse',
        'io',
        'html',
        're',
        'hashlib',
        'pathlib',
        'sqlite3',
        'threading',
        'datetime',
        'os',
        'sys',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'numpy',
        'scipy',
        'notebook',
        'IPython',
        'jupyter',
        'PIL',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='021kp-geo-pipeline',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    icon=str(SPECROOT / 'assets' / 'icon.ico') if (SPECROOT / 'assets' / 'icon.ico').exists() else None,
    version='version_info.txt' if Path('version_info.txt').exists() else None,
)
