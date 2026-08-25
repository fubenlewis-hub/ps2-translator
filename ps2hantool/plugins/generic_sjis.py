# -*- coding: utf-8 -*-
"""通用回退插件：对任意 PS2 ISO 的所有文件做 Shift-JIS 文本扫描。"""
import logging
from pathlib import Path

from ..text.model import TextEntry, TextFile, ExtractResult, CAT_OTHER
from ..text.extractor import SjisRunExtractor
from .base import BasePlugin

log = logging.getLogger("ps2hantool.generic")

# 跳过明显非文本的大文件（视频/音频/图像）以提速
SKIP_SUFFIX = (".trn", ".bsd", ".irx", ".img", ".ico")
SKIP_NAMES = ("EVSDATA.BIN",)


class GenericSjisPlugin(BasePlugin):
    name = "generic_sjis"
    display_name = "通用 Shift-JIS 扫描"

    def detect(self, ctx):
        cnf = (ctx.get("system_cnf") or "").upper()
        if "BOOT2" in cnf:
            return {"name": "未知 PS2 游戏", "slpm": ctx.get("slpm", ""),
                    "platform": "PS2", "generic": True}
        return None

    def extract(self, ctx, progress_cb=None, cancel_event=None):
        work = Path(ctx["work_dir"])
        res = ExtractResult()
        res.detected_game = {
            "name": "未知 PS2 游戏", "slpm": ctx.get("slpm", ""),
            "platform": "PS2", "generic": True}
        files = sorted(p for p in work.rglob("*") if p.is_file())
        ext = SjisRunExtractor(min_run=5, min_kana=0, drop_dups=True)
        total = len(files)
        n = 0
        for i, p in enumerate(files):
            if cancel_event and cancel_event.is_set():
                raise InterruptedError("用户取消")
            rel = str(p.relative_to(work)).replace("\\", "/")
            name = p.name.upper()
            if name.endswith(SKIP_SUFFIX) or name in SKIP_NAMES:
                continue
            if p.stat().st_size > 64 * 1024 * 1024:
                continue
            try:
                data = p.read_bytes()
            except Exception:
                continue
            tf = ext.extract(data, rel, CAT_OTHER)
            if tf.entries:
                res.files[rel] = tf
                n += 1
            if (i + 1) % 20 == 0 and progress_cb:
                progress_cb("扫描 %d/%d" % (i + 1, total))
        res.notes.append("通用扫描完成，含文本文件数: %d" % n)
        return res

    def writeback(self, ctx, result, progress_cb=None, cancel_event=None):
        # 通用插件不做自动回写（格式未知），返回说明
        return {"written": 0, "skipped": len(result.all_entries()),
                "note": "通用插件不支持自动回写，请使用手动导入/导出兜底"}

    def font_support(self, ctx):
        return {"status": "未知", "desc": "游戏字库位置未知，需人工分析。"}
