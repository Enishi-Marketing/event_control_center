# -*- mode: python ; coding: utf-8 -*-
"""Standalone Python service for the native macOS app."""

from PyInstaller.utils.hooks import collect_submodules
import os


hiddenimports = (
    collect_submodules("google.auth")
    + collect_submodules("google.oauth2")
    + collect_submodules("googleapiclient")
    + collect_submodules("google_auth_httplib2")
    + collect_submodules("httplib2")
    + collect_submodules("uritemplate")
)

a = Analysis(
    ["backend_bridge.py"],
    pathex=[],
    binaries=[],
    datas=[("assets/templates", "templates")],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="EventControlBackend",
    console=True,
    target_arch=None,
    codesign_identity=os.environ.get("CODESIGN_IDENTITY") or None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="EventControlBackend",
)
