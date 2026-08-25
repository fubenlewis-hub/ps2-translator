# -*- coding: utf-8 -*-
# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 打包配置：PS2 游戏一键汉化工具
用法：pyinstaller PS2汉化工具.spec
产出：dist/PS2汉化工具.exe（单文件）
"""
import os
import sys

project_root = os.path.abspath(SPECPATH or os.getcwd())

# opencc-python-reimplemented 的字典文件（json）必须随包带上
opencc_data = []
try:
    import opencc
    opencc_pkg = os.path.dirname(opencc.__file__)
    for root, dirs, files in os.walk(opencc_pkg):
        for f in files:
            if f.endswith((".json", ".txt")):
                opencc_data.append((os.path.join(root, f), os.path.relpath(root, opencc_pkg)))
except Exception:
    pass

a = Analysis(
    [os.path.join(project_root, "main.py")],
    pathex=[project_root],
    binaries=[],
    datas=opencc_data,
    hiddenimports=["opencc", "opencc.cli", "opencc.converter", "opencc.shared"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter", "unittest", "pydoc", "doctest", "test",
        "sqlite3", "http.cookiejar",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
        "PySide6.QtWebChannel", "PySide6.QtQuick", "PySide6.QtQml",
        "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
        "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.QtCharts",
        "PySide6.QtDataVisualization", "PySide6.QtGraphs", "PySide6.QtPdf",
        "PySide6.QtPdfWidgets", "PySide6.QtPositioning", "PySide6.QtSensors",
        "PySide6.QtSerialPort", "PySide6.QtSql", "PySide6.QtTest",
        "PySide6.QtWebSockets", "PySide6.QtXml",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="PS2汉化工具",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,              # GUI 程序，不弹控制台
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(project_root, "icon.ico"),
)
