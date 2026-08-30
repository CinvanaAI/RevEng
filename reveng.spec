# -*- mode: python ; coding: utf-8 -*-
# RevEng PyInstaller development spec
#
# Build steps:
#   1. python scripts/generate_icon.py         # generates reveng_icon.ico
#   2. pyinstaller reveng.spec --clean
#   3. Run dist/RevEng/RevEng.exe from a terminal (console=True) to resolve
#      any ModuleNotFoundError hidden imports, add them below, then rebuild.
#   4. Once clean, set console=False in the EXE block for the release build.
#
# First run: console=True is intentional. It reveals missing hidden imports
# without having to hunt for them via Process Monitor.

import sys
from pathlib import Path

block_cipher = None

a = Analysis(
    ['desktop.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        # Authoritative server-rendered UI
        ('reveng/platform/web/ui/templates', 'reveng/platform/web/ui/templates'),
        # Static assets served by FastAPI
        ('reveng/platform/web/ui/static',    'reveng/platform/web/ui/static'),
        # Capability environment skin images
        (
            'reveng/execution_environment/capability_environment/assets',
            'reveng/execution_environment/capability_environment/assets',
        ),
        # Agent environment source skin images
        (
            'reveng/execution_environment/agent_environment/source_skins',
            'reveng/execution_environment/agent_environment/source_skins',
        ),
    ],
    hiddenimports=[
        # uvicorn internals not picked up by static analysis
        'uvicorn.lifespan.on',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.http.h11_impl',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.logging',
        'uvicorn.main',
        # anyio backends
        'anyio._backends._asyncio',
        'anyio._backends._trio',
        # Starlette
        'starlette.responses',
        'starlette.staticfiles',
        'starlette.templating',
        'starlette.middleware.cors',
        # Jinja2 templates
        'jinja2.ext',
        # Pydantic
        'pydantic_core',
        'pydantic.v1',
        # stdlib
        'click',
        '_sqlite3',
        # multipart (file uploads)
        'multipart',
        'python_multipart',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='RevEng',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,  # Change to False for release after all import errors resolved
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='reveng_icon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='RevEng',
)
