# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for the Windows GUI build.
#
# Build it with packaging\build.ps1 (it creates the venv, runs the tests and zips the result),
# or directly:
#     python -m PyInstaller --noconfirm --clean packaging\DragonwildsSaveEditor.spec
#
# Output: dist\DragonwildsSaveEditor\DragonwildsSaveEditor.exe (one-folder build, windowed).
# The version resource is generated from dragonwilds_save_editor/__init__.py (__version__).

import glob
import os
import re

from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct,
    VSVersionInfo,
)

ROOT = os.path.abspath(os.path.join(SPECPATH, os.pardir))  # noqa: F821 (SPECPATH is injected)
APP_NAME = "DragonwildsSaveEditor"
PACKAGE = "dragonwilds_save_editor"
PKG_DIR = os.path.join(ROOT, PACKAGE)
ENTRY = os.path.join(PKG_DIR, "__main__.py")

# --- version resource from the package's __version__ -------------------------------------
with open(os.path.join(PKG_DIR, "__init__.py"), encoding="utf-8") as f:
    _vm = re.search(r"^__version__\s*=\s*['\"]([^'\"]+)['\"]", f.read(), re.M)
if not _vm:
    raise SystemExit("__version__ not found in %s/__init__.py" % PACKAGE)
VERSION = _vm.group(1)
m = re.match(r"^(\d+)\.(\d+)\.(\d+)(?:[-+].*)?$", VERSION)
if not m:
    raise SystemExit("__version__ must look like 1.2.3 (optionally -suffix), got %r" % VERSION)
nums = tuple(int(x) for x in m.groups()) + (0,)

version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=nums, prodvers=nums, mask=0x3F, flags=0x0,
                      OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0)),
    kids=[
        StringFileInfo([StringTable("040904B0", [
            StringStruct("CompanyName", "Dragonwilds Save Editor contributors"),
            StringStruct("FileDescription", "Dragonwilds Save Editor"),
            StringStruct("FileVersion", VERSION),
            StringStruct("InternalName", APP_NAME),
            StringStruct("OriginalFilename", APP_NAME + ".exe"),
            StringStruct("ProductName", "Dragonwilds Save Editor"),
            StringStruct("ProductVersion", VERSION),
            StringStruct("Comments", "Unofficial fan-made save editor for RuneScape: Dragonwilds. "
                                     "Not affiliated with or endorsed by Jagex."),
        ])]),
        VarFileInfo([VarStruct("Translation", [0x0409, 1200])]),
    ],
)
_workdir = globals().get("workpath") or os.path.join(ROOT, "build")
os.makedirs(_workdir, exist_ok=True)
VERSION_FILE = os.path.join(_workdir, "version_info.txt")
with open(VERSION_FILE, "w", encoding="utf-8") as f:
    f.write(str(version_info))

# --- modules ----------------------------------------------------------------------------
# List every module of the package explicitly (GUI tabs are imported lazily by name), so a
# newly added module or tab is bundled without editing this file.
hiddenimports = []
for p in sorted(glob.glob(os.path.join(PKG_DIR, "**", "*.py"), recursive=True)):
    rel = os.path.relpath(p, ROOT)[:-3].replace(os.sep, ".")
    if rel.endswith(".__init__"):
        rel = rel[:-len(".__init__")]
    if not rel.endswith(".__main__"):
        hiddenimports.append(rel)

a = Analysis(  # noqa: F821
    [ENTRY],
    pathex=[ROOT],
    binaries=[],
    # Read-only package data; paths.resource_path() finds it under
    # sys._MEIPASS/dragonwilds_save_editor/data (same layout as the source tree).
    datas=[(os.path.join(PKG_DIR, "data"), PACKAGE + "/data")],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Not needed at runtime; keeps the folder smaller.
    excludes=["pydoc_data", "lib2to3", "test", "idlelib", "turtledemo", "ensurepip", "venv"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,       # one-folder build: binaries go to COLLECT
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                   # UPX-packed exes trigger far more antivirus false positives
    console=False,               # windowed: no console window
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=VERSION_FILE,
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name=APP_NAME,
)
