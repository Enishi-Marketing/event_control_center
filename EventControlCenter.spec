# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


app_version = Path("VERSION").read_text(encoding="utf-8").strip()


hiddenimports = (
    collect_submodules("google.auth")
    + collect_submodules("google.oauth2")
    + collect_submodules("googleapiclient")
    + collect_submodules("google_auth_httplib2")
    + collect_submodules("httplib2")
    + collect_submodules("uritemplate")
)

a = Analysis(
    ["main.py"],
    pathex=[],
    binaries=[],
    datas=[("assets/app_logo.png", "assets"), ("assets/templates", "templates")],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="EventControlCenter",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon="assets/app_icon.icns",
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="EventControlCenter",
)
app = BUNDLE(
    coll,
    name="Event Control Center.app",
    icon="assets/app_icon.icns",
    bundle_identifier="jp.ac.enishi.event-control-center",
    info_plist={
        "CFBundleDisplayName": "Event Control Center",
        "CFBundleName": "Event Control Center",
        "CFBundleShortVersionString": app_version,
        "CFBundleVersion": app_version,
        "NSHighResolutionCapable": True,
    },
)
