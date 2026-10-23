# -*- mode: python ; coding: utf-8 -*-
"""Executar em Windows: python -m PyInstaller --noconfirm BacBoAnalyticsPro.spec."""
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

root = Path(SPECPATH)
datas = [(str(root / "LEIA-ME.txt"), ".")]
if (root / "assets").is_dir():
    datas.append((str(root / "assets"), "assets"))
if (root / "tests" / "fixtures").is_dir():
    datas.append((str(root / "tests" / "fixtures"), "validation-reference"))
# Os hooks oficiais cuidam de Qt, OpenCV e NumPy. Dados de fuso são necessários
# no Windows, onde a base IANA nem sempre está disponível no sistema operacional.
datas += collect_data_files("tzdata")
hiddenimports = collect_submodules("mss") + ["PySide6.QtSvg"]

a = Analysis(
    [str(root / "main.py")],
    pathex=[str(root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PyQt5", "PyQt6", "PySide2", "tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="BacBoAnalyticsPro",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)
coll = COLLECT(
    exe, a.binaries, a.datas,
    strip=False, upx=False, name="BacBoAnalyticsPro",
)
