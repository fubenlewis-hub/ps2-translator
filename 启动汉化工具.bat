@echo off
chcp 65001 >nul
title PS2 游戏一键汉化工具
cd /d "%~dp0"

REM 优先使用已打包的 exe（单文件，免依赖），否则回退到源码运行
if exist "dist\PS2汉化工具.exe" (
    echo 使用打包版（dist\PS2汉化工具.exe）...
    start "" "dist\PS2汉化工具.exe"
    exit /b
)

REM 源码模式：优先使用项目虚拟环境，否则用系统 Python
if exist venv\Scripts\python.exe (
    set PY=venv\Scripts\python.exe
) else (
    set PY=python
)

%PY% -c "import PySide6, pycdlib, PIL, requests" 2>nul
if errorlevel 1 (
    echo 正在安装依赖（首次运行需要几分钟）...
    %PY% -m pip install -r requirements.txt
)

echo 正在启动图形界面...
%PY% main.py
pause
