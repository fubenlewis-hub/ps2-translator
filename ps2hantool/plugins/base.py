# -*- coding: utf-8 -*-
"""插件基类与注册表。"""
import logging

log = logging.getLogger("ps2hantool.plugins")


class PluginError(Exception):
    pass


class BasePlugin:
    """游戏插件接口（最小集，避免过度设计）。

    生命周期：detect -> extract -> (translate) -> writeback -> font_support
    """

    #: 插件名（唯一）
    name = "base"
    #: 显示名
    display_name = "Base"
    #: 支持的编码
    encodings = ["cp932"]

    # ---------- 识别 ----------
    def detect(self, ctx):
        """
        根据工程上下文判断是否适用本插件。
        ctx: dict，包含 system_cnf 内容、slpm 编号、文件列表等。
        返回 dict 或 None（None=不适用）。
        """
        return None

    # ---------- 提取 ----------
    def extract(self, ctx, progress_cb=None, cancel_event=None):
        """
        从工作目录（ctx['work_dir']）提取文本。
        返回 ExtractResult。
        """
        raise NotImplementedError

    # ---------- 回写 ----------
    def writeback(self, ctx, result, progress_cb=None, cancel_event=None):
        """
        把 result 中已翻译的条目回写（就地/重建），返回回写报告 dict。
        """
        raise NotImplementedError

    # ---------- 字库 ----------
    def font_support(self, ctx):
        """返回字库支持方案描述；None 表示不支持（走通用降级）。"""
        return None


class PluginManager:
    def __init__(self):
        self._plugins = []

    def register(self, plugin):
        self._plugins.append(plugin)
        return plugin

    def all(self):
        return list(self._plugins)

    def find(self, ctx):
        """
        按顺序尝试各插件 detect()；第一个命中的返回 (plugin, info)。
        未命中返回 (None, None)。
        """
        for p in self._plugins:
            try:
                info = p.detect(ctx)
            except Exception as e:
                log.warning("插件 %s detect 出错: %s", p.name, e)
                continue
            if info:
                log.info("命中插件: %s (%s)", p.name, p.display_name)
                return p, info
        return None, None


# 全局注册表
_manager = PluginManager()


def get_manager():
    return _manager
