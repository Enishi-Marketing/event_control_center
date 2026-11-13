# -*- mode: python ; coding: utf-8 -*-
"""Standalone Python service for the native macOS app."""

from PyInstaller.utils.hooks import collect_submodules, collect_data_files, copy_metadata
from imageio_ffmpeg import get_ffmpeg_exe
from pathlib import Path
import os


hiddenimports = (
    collect_submodules("google.auth")
    + collect_submodules("google.oauth2")
    + collect_submodules("googleapiclient")
    + collect_submodules("google_auth_httplib2")
    + collect_submodules("httplib2")
    + collect_submodules("uritemplate")
    + collect_submodules("imageio_ffmpeg")
)

a = Analysis(
    ["backend_bridge.py"],
    pathex=[],
    binaries=[(get_ffmpeg_exe(), "imageio_ffmpeg/binaries"), ("build/filmcraft-tool/filmcraft-cli", "filmcraft"), ("build/lightcraft-tool/lightcraft-cli", "lightcraft")],
    datas=[("assets/templates", "templates")]
    + collect_data_files("imageio_ffmpeg", excludes=["binaries/ffmpeg-*"])
    + copy_metadata("imageio-ffmpeg")
    + [(str(path), "filmcraft/licenses") for path in Path("build/filmcraft-tool").iterdir() if path.is_file() and path.name != "filmcraft-cli"]
    + [(str(path), "lightcraft/licenses") for path in Path("build/lightcraft-tool").iterdir() if path.is_file() and path.name != "lightcraft-cli"],
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
