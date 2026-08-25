# -*- coding: utf-8 -*-
"""
PS2 游戏一键汉化工具
仅供个人学习研究使用，请确保拥有正版游戏。
"""
import sys
from pathlib import Path

__version__ = "0.1.0"


def get_app_root() -> Path:
    """应用根目录：源码运行时为项目根；PyInstaller 打包后为 exe 所在目录。
    工程/日志等用户数据默认存放在此目录下，避免落到 _MEIPASS 临时目录。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent
