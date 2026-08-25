# -*- coding: utf-8 -*-
"""插件注册。新增游戏插件只需：实现 BasePlugin 并在此导入注册。"""
from .base import PluginManager, get_manager, BasePlugin
from .tm3 import TM3Plugin
from .tm2_dat import TM2DatPlugin
from .generic_sjis import GenericSjisPlugin


def load_builtin_plugins():
    m = get_manager()
    if not m.all():
        m.register(TM3Plugin())
        m.register(TM2DatPlugin())
        m.register(GenericSjisPlugin())
    return m


__all__ = ["PluginManager", "get_manager", "BasePlugin", "load_builtin_plugins"]
