# -*- coding: utf-8 -*-
"""只读分析 PS2 ISO 文件结构（ISO9660 文件系统级别）。
不修改、不提取任何内容，仅列出目录树与文件元信息，供调研使用。
"""
import sys
import os
import pycdlib

ISOS = [
    r"E:\桌面\心跳回忆\Tokimeki Memorial 2 - Music Video Clips - Circus de Ai Imashou [Japan][SLPM-65118]心跳回忆2\Tokimeki Memorial 2 - Music Video Clips - Circus de Ai Imashou [NTSC-J] [SLPM-65118].iso",
    r"E:\桌面\心跳回忆\Tokimeki Memorial 3 [Japan][SLPM-65080]心跳回忆3\Tokimeki Memorial 3 [NTSC-J] [SLPM-65080].iso",
]

def analyze(path):
    print("=" * 100)
    print("ISO:", os.path.basename(path), "size=%.2f GB" % (os.path.getsize(path) / 1e9))
    iso = pycdlib.PyCdlib()
    iso.open(path)
    # 系统区域信息
    try:
        pvd = iso.pvd
        print("volume id:", pvd.volume_identifier)
        print("system id:", pvd.system_identifier)
        print("application id:", pvd.application_identifier)
    except Exception as e:
        print("pvd error:", e)
    print("-" * 100)
    # 递归列出
    entries = []
    def walk(dir_path, depth):
        if depth > 8:
            return
        for child in iso.list_children(iso_path=dir_path):
            fname = child.file_identifier().decode("utf-8", "replace")
            is_dir = child.is_dir()
            if fname in (".", ".."):
                continue
            full = (dir_path + "/" + fname) if dir_path != "/" else "/" + fname
            size = child.data_length if not is_dir else 0
            entries.append((full, is_dir, size))
            if is_dir:
                walk(full, depth + 1)
    walk("/", 0)
    print("total entries:", len(entries))
    # 只打印目录树 + 根目录文件
    for full, is_dir, size in entries:
        if is_dir or full.count("/") <= 1:
            marker = "[DIR]" if is_dir else "      "
            print("%s %10d  %s" % (marker, size, full))
    # 找疑似文本/字库/脚本文件（递归全盘，只看文件名）
    print("-" * 100)
    import re
    pat = re.compile(r"(text|script|msg|font|char|\.bin|\.dat|\.txt|\.msg|\.scp|\.afd|\.pak|\.arc|\.afs|\.tim|\.tm2)", re.I)
    hits = []
    for full, is_dir, size in entries:
        if not is_dir and pat.search(full):
            hits.append((full, size))
    hits.sort(key=lambda x: -x[1])
    print("candidate text/font files: %d (top 80 by size)" % len(hits))
    for full, size in hits[:80]:
        print("%12d  %s" % (size, full))
    iso.close()

for p in ISOS:
    analyze(p)
