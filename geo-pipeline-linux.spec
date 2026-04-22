# -*- mode: python ; coding: utf-8 -*-
import os
from pathlib import Path

block_cipher = None

a = Analysis(
    ['src/main.py'],
    pathex=[str(Path(__file__).parent)],
    binaries=[],
    datas=[
        ('config', 'config'),
        ('data', 'data'),
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
    ],
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
)
