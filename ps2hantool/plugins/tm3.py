# -*- coding: utf-8 -*-
"""
《心跳回忆3》(SLPM-65080) 插件。

依据（详见 docs/调研报告.md）：
- DATA1~5.BIN 无自有目录表，TOC 内嵌于 ELF(SLPM_650.80) 三处：
  0x199008~0x19A748 / 0x19B360~0x1B2468 / 0x41D4C0~0x422870
- 条目 8 字节：u32(高8位=容器号，低24位=扇区号) + u16 压缩尺寸(扇区) + u16 解压尺寸(扇区)
  （引用 BloodRaynare 的 QuickBMS 脚本，ResHax 论坛）
- 容器号：DATA1=2, DATA2=3, DATA3=4, DATA4=5, DATA5=6
- DATA5.BIN 为未压缩文本（对话/菜单），Shift-JIS，0x0D 换行，行间夹控制码
- DATA3.BIN 内 ATP 条目含剧情文本（部分未压缩，部分为 Konami 自定义压缩，见 atp.py）
- ELF 内含系统文本（%s 占位）
"""
import logging
import os
import re
import struct
from pathlib import Path

from ..text.model import (TextEntry, TextFile, ExtractResult,
                          CAT_DIALOG, CAT_MENU, CAT_SYSTEM, CAT_OTHER)
from ..text.extractor import SjisRunExtractor
from ..translate.jp_kanji import to_jis_encodable
from .base import BasePlugin
from . import atp

log = logging.getLogger("ps2hantool.tm3")

GAME_INFO = {
    "name": "心跳回忆3（ときめきメモリアル3 ～約束のあの場所で～）",
    "slpm": "SLPM-65080",
    "platform": "PS2",
    "publisher": "Konami",
}

# ELF 内 TOC 区间
TOC_RANGES = [
    (0x199008, 0x19A748),
    (0x19B360, 0x1B2468),
    (0x41D4C0, 0x422870),
]

# 容器号 -> 文件名
ARC_FILES = {2: "DATA1.BIN", 3: "DATA2.BIN", 4: "DATA3.BIN",
             5: "DATA4.BIN", 6: "DATA5.BIN"}


def parse_elf_toc(elf_data):
    """从 ELF 解析出全部容器条目。
    返回 [(arc_num, sector, size_c, size_u)]（尺寸单位为 0x800 扇区）。
    """
    entries = []
    for start, end in TOC_RANGES:
        p = start
        while p + 8 <= end:
            e = struct.unpack_from(">IHH", elf_data, p)
            arc, sizes = e[0], (e[1], e[2])
            p += 8
            if arc == 0 and sizes == (0, 0x8000):
                continue
            arc_num = arc >> 24
            sector = arc & 0xFFFFFF
            entries.append((arc_num, sector, sizes[0], sizes[1]))
    return entries


class TM3Plugin(BasePlugin):
    name = "tm3"
    display_name = "心跳回忆3 (SLPM-65080)"

    # ---------------- 识别 ----------------
    def detect(self, ctx):
        cnf = (ctx.get("system_cnf") or "").upper()
        if "SLPM_650.80" in cnf:
            return dict(GAME_INFO)
        return None

    # ---------------- 提取 ----------------
    def extract(self, ctx, progress_cb=None, cancel_event=None):
        work = Path(ctx["work_dir"])
        res = ExtractResult()
        res.detected_game = dict(GAME_INFO)

        elf_data = (work / "SLPM_650.80").read_bytes()
        toc = parse_elf_toc(elf_data)
        res.notes.append("ELF 目录表条目数: %d" % len(toc))

        def step(msg):
            if progress_cb:
                progress_cb(msg)
            if cancel_event and cancel_event.is_set():
                raise InterruptedError("用户取消")

        # --- DATA5.BIN 未压缩文本 ---
        step("提取 DATA5.BIN 文本…")
        d5 = (work / "DATA5.BIN").read_bytes()
        ext = SjisRunExtractor(min_run=4, min_kana=1, rare_filter=False)
        tf = ext.extract(d5, "DATA5.BIN", CAT_DIALOG)
        # 类别细分：短文本或含 % 的归为菜单/系统
        for e in tf.entries:
            if len(e.original) <= 12 or "%" in e.original:
                e.category = CAT_MENU if len(e.original) <= 12 else CAT_SYSTEM
        res.files["DATA5.BIN"] = tf
        res.notes.append("DATA5.BIN 提取文本: %d 条" % len(tf.entries))
        step("DATA5.BIN 完成（%d 条）" % len(tf.entries))

        # --- ELF 系统文本 ---
        step("提取 ELF 系统文本…")
        tf2 = SjisRunExtractor(min_run=5, min_kana=2, drop_dups=False,
                               rare_filter=False).extract(
            elf_data, "SLPM_650.80", CAT_SYSTEM)
        res.files["SLPM_650.80"] = tf2
        res.notes.append("ELF 系统文本: %d 条" % len(tf2.entries))

        # --- DATA3.BIN 内 ATP 条目文本 ---
        step("扫描 DATA3.BIN 文本…")
        data3 = (work / "DATA3.BIN").read_bytes()
        # 1) 全文件原始扫描：压缩流中文字按字面透传，可读到较长的完整句段
        ext3 = SjisRunExtractor(min_run=24, min_kana=8, drop_dups=True)
        tf3 = ext3.extract(data3, "DATA3.BIN", CAT_DIALOG)
        # 2) 逐条目尝试 ATP 解压（实验功能，移植自 TM3_Tools）
        arc_entries = sorted([e for e in toc if e[0] == 4], key=lambda x: x[1])
        decoded_found = 0
        for i, (arc, sector, sc, su) in enumerate(arc_entries):
            if cancel_event and cancel_event.is_set():
                raise InterruptedError("用户取消")
            off = sector * 0x800
            sz = sc * 0x800
            if off >= len(data3) or sz <= 0:
                continue
            chunk = data3[off:off + sz]
            if chunk[:4] == b"ATP\x00":
                try:
                    blob = atp.decode_atp(chunk)
                except Exception:
                    blob = None
                if blob and len(blob) > 128:
                    extd = SjisRunExtractor(min_run=6, min_kana=4, drop_dups=True)
                    for e in extd.extract(blob, "DATA3.BIN#dec%d" % i, CAT_DIALOG).entries:
                        if e.original not in {x.original for x in tf3.entries}:
                            tf3.entries.append(e)
                            decoded_found += 1
            if (i + 1) % 400 == 0:
                step("DATA3 ATP 条目 %d/%d" % (i + 1, len(arc_entries)))
        if tf3.entries:
            res.files["DATA3.BIN"] = tf3
        res.notes.append("DATA3.BIN 文本: %d 条（其中 ATP 解压新增 %d 条）" % (
            len(tf3.entries), decoded_found))
        step("DATA3.BIN 完成（%d 条）" % len(tf3.entries))

        # --- 自动提取说话人名字（供术语表使用）---
        names = set()
        for f in res.files.values():
            for e in f.entries:
                m = re.match(r"^([^\n「」]{1,8})「", e.original)
                if m:
                    names.add(m.group(1))
        if names:
            res.notes.append("自动检测到的说话人名: " + ", ".join(sorted(names)[:20]))
        return res

    # ---------------- 回写 ----------------
    def writeback(self, ctx, result, progress_cb=None, cancel_event=None):
        work = Path(ctx["work_dir"])
        report = {"written": 0, "skipped": 0, "too_long": [],
                  "unmapped_chars": {}, "files": {}}

        # 以文件为单位回写（仅处理 DATA5.BIN 与 SLPM_650.80）
        for fpath in ("DATA5.BIN", "SLPM_650.80"):
            tf = result.files.get(fpath)
            if not tf:
                continue
            ffull = work / fpath
            data = bytearray(ffull.read_bytes())
            written = 0
            skipped = 0
            for e in tf.entries:
                if not e.translation or e.status in ("untranslated", "skipped"):
                    continue
                # 简体中文 → cp932 可编码（记录无法映射的字符）
                jis_text = to_jis_encodable(e.translation, report["unmapped_chars"])
                new_bytes = jis_text.replace("\n", "\r").encode("cp932")
                old_len = e.length
                if e.offset < 0 or e.offset + old_len > len(data):
                    continue
                if len(new_bytes) <= old_len:
                    pad = old_len - len(new_bytes)
                    # 若原文本以 \r 结尾，填充放在最后一个 \r 之前，避免尾部空行
                    ends_cr = old_len > 0 and data[e.offset + old_len - 1] == 0x0D
                    if ends_cr:
                        data[e.offset:e.offset + old_len] = (
                            new_bytes + b" " * pad + b"\r")
                    else:
                        data[e.offset:e.offset + old_len] = new_bytes + b" " * pad
                    written += 1
                else:
                    report["too_long"].append((e.id, e.original[:20],
                                               len(new_bytes), old_len))
                    skipped += 1
            ffull.write_bytes(bytes(data))
            report["files"][fpath] = {"written": written, "skipped": skipped}
            report["written"] += written
            report["skipped"] += skipped
            if progress_cb:
                progress_cb("回写 %s: 成功 %d, 跳过 %d" % (fpath, written, skipped))
        return report

    # ---------------- 字库 ----------------
    def font_support(self, ctx):
        return {
            "status": "需逆向",
            "desc": ("TM3 字库位于 DATA2.BIN / DATA4.BIN（PS2 GS 纹理容器，"
                     "DATA4 内 0x50 起为 32 级阶梯调色板）。支持 TiledGGD 查看。"
                     "精确字形布局待插件继续逆向；降级方案：字模替换/同音字占位。"),
        }
