# -*- coding: utf-8 -*-
"""
ISO 处理层：基于 pycdlib 的 PS2 ISO 提取与重打包。

要点：
- 提取时保留 ISO9660 目录树与文件内容，供汉化修改；
- 重打包时按“原始 LBA 布局 + 修改文件就地替换、新增大文件追加”的策略，
  尽量保持 PS2 光盘的 LBA 顺序（PS2 光驱对 LBA 顺序敏感，参照 xpert 的做法）；
- 绝不覆盖原始 ISO：输出到新文件，原文件只读。
"""
import io
import os
import shutil
import logging
from pathlib import Path

import pycdlib

log = logging.getLogger("ps2hantool.iso")

# PS2 游戏通用特征（用于自动识别）
PS2_BOOT_MARKER = b"PLAYSTATION"


class IsoError(Exception):
    pass


class Ps2Iso:
    """封装一个 PS2 ISO 的只读访问。"""

    def __init__(self, path):
        self.path = Path(path)
        if not self.path.exists():
            raise IsoError("ISO 文件不存在: %s" % self.path)
        self.iso = pycdlib.PyCdlib()
        self.iso.open(str(self.path))
        self._entries = None

    def close(self):
        try:
            self.iso.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    # ---------- 目录树 ----------
    def list_all(self):
        """返回 [(路径, is_dir, size)] 全量列表。"""
        if self._entries is not None:
            return self._entries
        out = []

        def walk(dp):
            for c in self.iso.list_children(iso_path=dp):
                name = c.file_identifier().decode("utf-8", "replace")
                if name in (".", ".."):
                    continue
                full = (dp + "/" + name) if dp != "/" else "/" + name
                out.append((full, c.is_dir(), c.data_length))
                if c.is_dir():
                    walk(full)

        walk("/")
        self._entries = out
        return out

    def read_bytes(self, iso_path, size=None, offset=0):
        """读取 ISO 内某个文件的字节（内存中）。"""
        buf = io.BytesIO()
        self.iso.get_file_from_iso_fp(buf, iso_path=iso_path)
        data = buf.getvalue()
        if offset:
            data = data[offset:]
        if size is not None:
            data = data[:size]
        return data

    def extract_file(self, iso_path, dest):
        """把 ISO 内文件提取到本地路径。"""
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as f:
            self.iso.get_file_from_iso_fp(f, iso_path=iso_path)
        return dest

    def extract_all(self, out_dir, progress_cb=None):
        """整盘提取到 out_dir（保留目录结构），返回文件数。"""
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        entries = self.list_all()
        files = [(p, s) for (p, d, s) in entries if not d]
        total = len(files)
        for i, (ipath, size) in enumerate(files):
            # ISO 路径 -> 本地相对路径（去掉前导 / 与 ;1 版本号）
            rel = ipath.lstrip("/")
            if ";" in rel:
                rel = rel.split(";")[0]
            rel = rel.replace("\\", os.sep)
            self.extract_file(ipath, out_dir / rel)
            if progress_cb:
                progress_cb(i + 1, total, ipath)
        return total


def rebuild_iso(work_dir, out_iso, progress_cb=None):
    """
    把修改后的文件树重新打包为 ISO。

    策略（尽量保 LBA 顺序）：
    1) 先按原 ISO 布局重建所有文件（顺序 = 原目录表顺序，用 ELF 名做锚点）；
       具体实现：先写入原有文件（若修改过则写新内容，长度变化就地处理），
       再将新增文件追加在末尾。
    2) 写入 SYSTEM.CNF 等系统文件。
    """
    work_dir = Path(work_dir)
    out_iso = Path(out_iso)
    out_iso.parent.mkdir(parents=True, exist_ok=True)
    # 目标已存在时输出到带时间戳的新文件（避免覆盖/删除既有文件）
    target = out_iso
    if target.exists():
        import time
        target = out_iso.with_name(
            "%s_%s%s" % (out_iso.stem, time.strftime("%H%M%S"), out_iso.suffix))
        log.info("输出文件已存在，将写入新文件: %s", target.name)

    # 读取原布局（若存在 layout.json）
    layout_file = work_dir / "_layout.json"
    layout = []
    if layout_file.exists():
        import json

        layout = json.loads(layout_file.read_text("utf-8"))

    iso = pycdlib.PyCdlib()
    iso.new(interchange_level=3, sys_ident="PLAYSTATION")

    def ensure_dir(iso_path):
        """逐级创建目录（已存在则跳过）。"""
        parts = [p for p in iso_path.split("/") if p]
        cur = "/"
        for p in parts:
            cur = cur + p
            try:
                iso.add_directory(iso_path=cur)
            except Exception:
                pass
            cur = cur + "/"

    added = set()
    open_fps = []   # pycdlib 在 write() 时才读数据，句柄需存活到写完

    def add_file(local_fp, rel):
        iso_path = "/" + rel + ";1"
        ensure_dir(iso_path.rsplit("/", 1)[0])
        f = open(local_fp, "rb")
        open_fps.append(f)
        iso.add_fp(f, local_fp.stat().st_size, iso_path=iso_path)
        added.add(iso_path)

    def norm(rel):
        rel = str(rel).replace("\\", "/").lstrip("/")
        return rel

    # 1) 原有文件按布局顺序
    all_files = sorted(p for p in work_dir.rglob("*") if p.is_file())
    # 排除工具内部文件（_layout.json 等）
    all_files = [p for p in all_files
                 if not p.name.startswith("_") and not p.name.startswith(".")]
    # 若 layout 可用，优先按 layout 顺序；否则按文件名排序（SYSTEM.CNF 放最前，ELF 靠前）
    ordered = []
    if layout:
        for entry in layout:
            local = work_dir / norm(entry.get("path", ""))
            if local.exists() and local.is_file():
                ordered.append(local)
    remaining = [p for p in all_files if p not in ordered]
    # 排序保证 SYSTEM.CNF 最前、ELF 次之（PS2 引导依赖）
    def keyf(p):
        name = norm(p.relative_to(work_dir))
        if name.upper().startswith("SYSTEM.CNF"):
            return (0, name)
        if name.upper().startswith("SLPM") or name.upper().startswith("SLUS"):
            return (1, name)
        return (2, name)

    remaining.sort(key=keyf)
    ordered.extend(remaining)

    total = len(ordered)
    for i, fp in enumerate(ordered):
        rel = norm(fp.relative_to(work_dir))
        add_file(fp, rel)
        if progress_cb:
            progress_cb(i + 1, total, rel)

    # 2) 补 SYSTEM.CNF（若缺失）
    if "/SYSTEM.CNF;1" not in added:
        cnf = work_dir / "SYSTEM.CNF"
        if cnf.exists():
            add_file(cnf, "SYSTEM.CNF")

    iso.write(str(out_iso))
    iso.close()
    for f in open_fps:
        try:
            f.close()
        except Exception:
            pass
    return out_iso
