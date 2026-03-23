# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path.cwd().resolve()
SRC = ROOT / "src"

datas = []
hiddenimports = []
for package_name in ("playwright", "dotenv"):
    datas += collect_data_files(package_name)
    hiddenimports += collect_submodules(package_name)

a = Analysis(
    [str(ROOT / "packaging" / "entry_cli.py")],
    pathex=[str(SRC)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="affitto_cli",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
)
