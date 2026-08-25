# -*- coding: utf-8 -*-
"""
工程管理器：ISO 载入、工作目录、状态持久化、备份、日志。

目录结构：
  <project_dir>/
    iso/           原始 ISO 只读引用（或软链）
    work/          提取出的文件树（可修改）
    backup/        回写前的文件备份（可一键恢复）
    output/        汉化后重新打包的 ISO
    data/          工程状态（settings.json / glossary.json / extracted.json / translated.json）
    logs/          运行日志
"""
import json
import logging
import os
import shutil
import time
from pathlib import Path

log = logging.getLogger("ps2hantool.project")


class Project:
    def __init__(self, root: Path):
        self.root = Path(root)

    # ---------- 目录 ----------
    @property
    def iso_dir(self): return self.root / "iso"

    @property
    def work_dir(self): return self.root / "work"

    @property
    def backup_dir(self): return self.root / "backup"

    @property
    def output_dir(self): return self.root / "output"

    @property
    def data_dir(self): return self.root / "data"

    @property
    def log_dir(self): return self.root / "logs"

    def ensure_dirs(self):
        for d in (self.iso_dir, self.work_dir, self.backup_dir,
                  self.output_dir, self.data_dir, self.log_dir):
            d.mkdir(parents=True, exist_ok=True)

    # ---------- 状态 ----------
    def settings_path(self): return self.data_dir / "settings.json"

    def glossary_path(self): return self.data_dir / "glossary.json"

    def extracted_path(self): return self.data_dir / "extracted.json"

    def translated_path(self): return self.data_dir / "translated.json"

    def similar_path(self): return self.data_dir / "similar.json"

    def layout_path(self): return self.work_dir / "_layout.json"

    def load_settings(self):
        p = self.settings_path()
        if p.exists():
            return json.loads(p.read_text("utf-8"))
        return {}

    def save_settings(self, d):
        self.ensure_dirs()
        self.settings_path().write_text(
            json.dumps(d, ensure_ascii=False, indent=2), "utf-8")

    def get(self, key, default=None):
        return self.load_settings().get(key, default)

    def set(self, key, value):
        s = self.load_settings()
        s[key] = value
        self.save_settings(s)

    # ---------- 日志 ----------
    def log(self, msg, level="info"):
        self.ensure_dirs()
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(self.log_dir / "run.log", "a", encoding="utf-8") as f:
            f.write("[%s] %s: %s\n" % (stamp, level.upper(), msg))
        getattr(log, level, log.info)(msg)

    # ---------- ISO 载入与提取 ----------
    def load_iso(self, iso_path, progress_cb=None):
        """复制/引用 ISO 并整盘提取。返回检测到的 SYSTEM.CNF 内容。"""
        self.ensure_dirs()
        iso_path = Path(iso_path)
        self.iso_dir.mkdir(exist_ok=True)
        # 工程内保存 ISO 副本引用（不移动用户文件）
        from .iso import Ps2Iso
        system_cnf = ""
        slpm = ""
        with Ps2Iso(iso_path) as iso:
            entries = iso.list_all()
            # 保存布局（供重打包保序）
            layout = [{"path": p, "size": s} for (p, d, s) in entries if not d]
            self.layout_path().write_text(
                json.dumps(layout, ensure_ascii=False), "utf-8")
            # 提取 SYSTEM.CNF 用于识别
            for p, isdir, size in entries:
                if p.upper().endswith("SYSTEM.CNF;1"):
                    system_cnf = iso.read_bytes(p).decode("ascii", "replace")
                    m = __import__("re").search(r"cdrom0:\\([A-Z0-9_\.]+);1",
                                                system_cnf, __import__("re").I)
                    if m:
                        slpm = m.group(1)
                    break
            # 整盘提取
            def cb(i, total, path):
                self.log("提取 %d/%d %s" % (i, total, path), "info")
                if progress_cb:
                    progress_cb("提取 %d/%d %s" % (i, total, path))
            self.log("开始整盘提取: %s" % iso_path.name)
            iso.extract_all(self.work_dir, cb)
        # 保存 ISO 副本的引用信息
        self.set("iso_path", str(iso_path))
        self.set("iso_name", iso_path.name)
        self.set("system_cnf", system_cnf)
        self.set("slpm", slpm)
        self.log("ISO 载入完成，识别编号: %s" % (slpm or "未知"))
        return {"system_cnf": system_cnf, "slpm": slpm}

    # ---------- 备份 / 恢复 ----------
    def backup_files(self, paths):
        """把 work 下的文件备份到 backup/（保留相对路径）。返回备份时间戳。"""
        self.ensure_dirs()
        stamp = time.strftime("%Y%m%d_%H%M%S")
        dest_dir = self.backup_dir / stamp
        dest_dir.mkdir(parents=True, exist_ok=True)
        n = 0
        for rel in paths:
            src = self.work_dir / rel
            if src.exists():
                d = dest_dir / rel
                d.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, d)
                n += 1
        self.log("已备份 %d 个文件到 %s" % (n, dest_dir.name))
        return str(dest_dir)

    def restore_backup(self, stamp=None):
        """从指定（或最新）备份恢复。"""
        if not self.backup_dir.exists():
            return 0
        backups = sorted(self.backup_dir.iterdir(), reverse=True)
        if not backups:
            return 0
        src = self.backup_dir / (stamp or backups[0].name)
        n = 0
        for f in src.rglob("*"):
            if f.is_file():
                rel = f.relative_to(src)
                dst = self.work_dir / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, dst)
                n += 1
        self.log("已从备份 %s 恢复 %d 个文件" % (src.name, n))
        return n
