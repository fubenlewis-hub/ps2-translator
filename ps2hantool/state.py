# -*- coding: utf-8 -*-
"""软件状态机：统一管理各流程阶段，驱动状态栏/按钮可用性/页面导航。

状态流转：
  IDLE → LOADING → LOADED → EXTRACTING → EXTRACTED → [术语确认]
       → TRANSLATING → TRANSLATED → (校对) → WRITEBACKING → BUILDING → DONE
  任何步骤失败 → ERROR（可重试或返回）
"""
from enum import Enum


class AppState(Enum):
    IDLE = "idle"
    LOADING = "loading"          # 载入 ISO/整盘提取中
    LOADED = "loaded"            # 已载入，待提取
    EXTRACTING = "extracting"    # 文本提取中
    EXTRACTED = "extracted"      # 已提取，待确认术语表
    TRANSLATING = "translating"  # 翻译中
    TRANSLATED = "translated"    # 已翻译，可校对/回写
    WRITEBACKING = "writebacking"  # 回写中
    BUILDING = "building"        # 打包中
    DONE = "done"                # 全流程完成
    ERROR = "error"              # 出错


# 状态的中文描述（用于状态栏）
STATE_TEXT = {
    AppState.IDLE: "空闲（请载入 ISO）",
    AppState.LOADING: "正在载入 ISO 并整盘提取…",
    AppState.LOADED: "已载入，可提取文本",
    AppState.EXTRACTING: "正在提取文本…",
    AppState.EXTRACTED: "已提取，请确认术语表",
    AppState.TRANSLATING: "正在翻译…",
    AppState.TRANSLATED: "已翻译，可校对或开始回写",
    AppState.WRITEBACKING: "正在回写文件…",
    AppState.BUILDING: "正在重新打包 ISO…",
    AppState.DONE: "✅ 汉化完成",
    AppState.ERROR: "⚠️ 出错（详情见日志）",
}

# 每个状态允许的“页面跳转”：
# 页面 key: home / extract / glossary / settings / review / logs
PAGE_ACCESS = {
    AppState.IDLE: ("home", "logs"),
    AppState.LOADING: ("home", "logs"),
    AppState.LOADED: ("home", "logs"),
    AppState.EXTRACTING: ("home", "logs"),
    AppState.EXTRACTED: ("extract", "glossary", "settings", "logs"),
    AppState.TRANSLATING: ("home", "logs"),
    AppState.TRANSLATED: ("review", "glossary", "settings", "logs"),
    AppState.WRITEBACKING: ("home", "logs"),
    AppState.BUILDING: ("home", "logs"),
    AppState.DONE: ("home", "review", "logs"),
    AppState.ERROR: ("home", "extract", "glossary", "settings", "review", "logs"),
}
