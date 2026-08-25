# -*- coding: utf-8 -*-
"""
《心跳回忆2 音乐视频剪辑版》(SLPM-65118) 插件。

实测（见调研报告）：
- 全盘内容在单一容器 DATA.DAT（704MB）
- 容器目录表：文件头 0x3000 字节，364 条，每条 32 字节：
  u32 绝对偏移 + u32 大小 + char[24] 文件名（含 SE、1、2 等子目录）
- 场景文件（1*.BIN 等）以魔数 2A C9 43 F7（Konami 图形容器）开头，
  本盘为“音乐视频剪辑”盘，可译文本极少（字幕烧录在 CISE 视频流中）。
  插件提供：容器解包 + 通用字符串扫描 + 回写框架，文本量少属正常。
"""
import logging
import struct
from pathlib import Path

from ..text.model import TextEntry, TextFile, ExtractResult, CAT_MENU, CAT_OTHER
from ..text.extractor import SjisRunExtractor
from ..translate.jp_kanji import to_jis_encodable
from .base import BasePlugin

log = logging.getLogger("ps2hantool.tm2")

GAME_INFO = {
    "name": "心跳回忆2 音乐视频剪辑版 ～马戏团恋爱吧～（ときめきメモリアル2 Music Video Clips）",
    "slpm": "SLPM-65118",
    "platform": "PS2",
    "publisher": "Konami",
    "note": "本盘为视频剪辑盘，文本量极少，字幕烧录于视频流",
}

TOC_SIZE = 0x3000


def parse_dat_dat_toc(data):
    """解析 DATA.DAT 目录表。返回 [(offset, size, name)]。"""
    entries = []
    for i in range(TOC_SIZE // 32):
        p = i * 32
        off, sz = struct.unpack_from("<II", data, p)
        name = data[p + 8:p + 32].split(b"\x00")[0]
        if not name:
            break
        entries.append((off, sz, name.decode("ascii", "replace")))
    return entries


class TM2DatPlugin(BasePlugin):
    name = "tm2_dat"
    display_name = "心跳回忆2 音乐视频剪辑版 (SLPM-65118)"

    def detect(self, ctx):
        cnf = (ctx.get("system_cnf") or "").upper()
        if "SLPM_651.18" in cnf:
            return dict(GAME_INFO)
        return None

    def extract(self, ctx, progress_cb=None, cancel_event=None):
        work = Path(ctx["work_dir"])
        res = ExtractResult()
        res.detected_game = dict(GAME_INFO)

        dat_path = work / "DATA.DAT"
        if not dat_path.exists():
            res.notes.append("未找到 DATA.DAT")
            return res
        data = dat_path.read_bytes()
        toc = parse_dat_dat_toc(data)
        res.notes.append("DATA.DAT 目录表条目: %d" % len(toc))
        # 摘要输出容器内文件分布（供用户了解结构）
        cats = {}
        for off, sz, name in toc:
            top = name.split("\\")[0] if "\\" in name else "(根目录)"
            cats[top] = cats.get(top, 0) + 1
        res.notes.append("容器内容分布: " + ", ".join(
            "%s×%d" % (k, v) for k, v in sorted(cats.items())))

        # 本盘为“音乐视频剪辑”盘：场景文件为 Konami 图形容器（魔数 2A C9 43 F7），
        # 文本烧录在 CISE 视频流中，自动扫描只能得到图形数据噪声。
        # 因此默认不扫描；如需强制扫描请用通用插件（generic_sjis）并人工过滤。
        scan_small = ctx.get("tm2_scan_small", False)
        if scan_small:
            ext = SjisRunExtractor(min_run=8, min_kana=3, drop_dups=True)
            tf = TextFile(path="DATA.DAT")
            for off, sz, name in toc:
                if sz > 8 * 1024 or off >= len(data):
                    continue
                tf2 = ext.extract(data[off:off + sz], "DATA.DAT", CAT_OTHER)
                for e in tf2.entries:
                    e.offset = off + e.offset
                    tf.entries.append(e)
            res.files["DATA.DAT"] = tf
            res.notes.append("强制扫描（小文件）提取: %d 条" % len(tf.entries))
        res.notes.append("提示：本盘无可自动提取的游戏文本（视频盘），"
                         "如需汉化菜单请使用「手动导入/导出」兜底。")
        return res

    def writeback(self, ctx, result, progress_cb=None, cancel_event=None):
        """就地回写 DATA.DAT 内文本（与 TM3 插件同策略）。"""
        work = Path(ctx["work_dir"])
        report = {"written": 0, "skipped": 0, "too_long": [],
                  "unmapped_chars": {}, "files": {}}
        tf = result.files.get("DATA.DAT")
        if not tf:
            return report
        dat_path = work / "DATA.DAT"
        data = bytearray(dat_path.read_bytes())
        written = skipped = 0
        for e in tf.entries:
            if not e.translation or e.status in ("untranslated", "skipped"):
                continue
            jis_text = to_jis_encodable(e.translation, report["unmapped_chars"])
            new_bytes = jis_text.replace("\n", "\r").encode("cp932")
            if e.offset < 0 or e.offset + e.length > len(data):
                continue
            if len(new_bytes) <= e.length:
                data[e.offset:e.offset + e.length] = new_bytes + b" " * (e.length - len(new_bytes))
                written += 1
            else:
                report["too_long"].append((e.id, e.original[:20]))
                skipped += 1
        dat_path.write_bytes(bytes(data))
        report["written"], report["skipped"] = written, skipped
        report["files"]["DATA.DAT"] = {"written": written, "skipped": skipped}
        return report

    def font_support(self, ctx):
        return {
            "status": "无需修改",
            "desc": "本盘字幕烧录在视频流中，无独立字库可替换；如需汉化需视频重压制。",
        }
