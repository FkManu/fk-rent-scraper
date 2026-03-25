# -*- mode: python ; coding: utf-8 -*-
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path.cwd().resolve()
SRC = ROOT / "src"
PYTHON_HOME = Path(sys.base_prefix).resolve()
PYTHON_DLLS = PYTHON_HOME / "DLLs"
PYTHON_TCL = PYTHON_HOME / "tcl"

datas = []
hiddenimports = []
binaries = []
for package_name in ("playwright", "dotenv"):
    datas += collect_data_files(package_name)
    hiddenimports += collect_submodules(package_name)

hiddenimports += ["tkinter", "tkinter.scrolledtext", "_tkinter"]

for folder_name in ("tcl8.6", "tk8.6", "tcl8", "dde1.4", "reg1.3", "tix8.4.3"):
    source = PYTHON_TCL / folder_name
    if source.exists():
        datas.append((str(source), folder_name))

for dll_name in ("tcl86t.dll", "tk86t.dll"):
    source = PYTHON_DLLS / dll_name
    if source.exists():
        binaries.append((str(source), "."))

a = Analysis(
    [str(ROOT / "packaging" / "entry_gui.py")],
    pathex=[str(SRC)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(ROOT / "packaging" / "runtime_hook_tk.py")],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="affitto_gui",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="affitto_gui",
)
