# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the main AgentDesk desktop application.

Produces a standalone ``AgentDesk.exe`` (windowed, no console) on Windows.
Run from the repository root:  pyinstaller packaging/agentdesk.spec
"""
import os

from PyInstaller.utils.hooks import collect_submodules

# Repository root (spec files live in <root>/packaging/).
ROOT = os.path.abspath(os.path.join(SPECPATH, os.pardir))

hiddenimports = collect_submodules('agentdesk') + [
    'PySide6.QtCore', 'PySide6.QtGui', 'PySide6.QtWidgets',
]

a = Analysis(
    [os.path.join(ROOT, 'agentdesk', 'app.py')],
    pathex=[ROOT],
    binaries=[],
    datas=[],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'numpy', 'scipy', 'pandas'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='AgentDesk',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # GUI application — no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=None,
)
