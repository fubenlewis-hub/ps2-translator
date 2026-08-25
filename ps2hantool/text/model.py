# -*- coding: utf-8 -*-
"""文本数据模型与交换格式（JSON / CSV / XLIFF）。"""
import csv
import io
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

# 文本类别
CAT_DIALOG = "对话"
CAT_MENU = "菜单"
CAT_SYSTEM = "系统文本"
CAT_NAME = "角色/地名"
CAT_ITEM = "物品/说明"
CAT_OTHER = "其他"

CATEGORIES = [CAT_DIALOG, CAT_MENU, CAT_SYSTEM, CAT_NAME, CAT_ITEM, CAT_OTHER]


class TextEntry:
    """单条可翻译文本。offset/length 均相对所属文件。"""

    __slots__ = ("id", "file", "offset", "length", "category", "original",
                 "translation", "status", "note", "raw")

    def __init__(self, file="", offset=0, length=0, category=CAT_OTHER,
                 original="", translation="", status="untranslated",
                 note="", raw=None):
        self.id = None          # 稳定 id（由工程分配）
        self.file = file
        self.offset = offset
        self.length = length
        self.category = category
        self.original = original
        self.translation = translation
        self.status = status    # untranslated / translated / reviewed / skipped / error
        self.note = note
        self.raw = raw          # 原始字节（可选，仅供回写参考）

    def dedup_key(self):
        """去重键：原文 + 类型（同原文但不同类型不共享译文，避免菜单/对话语境冲突）。
        去首尾空白做轻量归一（避免 \r 等差异导致漏匹配）。"""
        return (self.original.strip(), self.category)

    def to_dict(self):
        return {
            "id": self.id, "file": self.file, "offset": self.offset,
            "length": self.length, "category": self.category,
            "original": self.original, "translation": self.translation,
            "status": self.status, "note": self.note,
        }

    @classmethod
    def from_dict(cls, d):
        e = cls()
        for k in cls.__slots__:
            if k == "raw":
                continue
            if k in d:
                setattr(e, k, d[k])
        return e


class TextFile:
    """一个源文件内提取出的文本集合。"""

    def __init__(self, path="", encoding="cp932"):
        self.path = path            # 相对工程工作目录
        self.encoding = encoding
        self.entries = []           # list[TextEntry]

    def add(self, entry):
        entry.file = self.path
        entry.id = "%s#%d" % (self.path, entry.offset)
        self.entries.append(entry)
        return entry


class ExtractResult:
    """一次提取的全部结果。"""

    def __init__(self):
        self.files = {}             # path -> TextFile
        self.detected_game = None   # 检测到的游戏信息 dict
        self.notes = []             # 说明/警告

    def all_entries(self):
        out = []
        for f in self.files.values():
            out.extend(f.entries)
        return out

    def stats(self):
        entries = self.all_entries()
        total_chars = sum(len(e.original) for e in entries)
        by_cat = {}
        for e in entries:
            by_cat[e.category] = by_cat.get(e.category, 0) + 1
        # 重复统计：按 (原文, 类型) 去重
        unique_keys = {e.dedup_key() for e in entries}
        unique = len(unique_keys)
        return {
            "total_entries": len(entries),
            "total_chars": total_chars,
            "by_category": by_cat,
            "files": len(self.files),
            "unique_entries": unique,
            "duplicate_entries": len(entries) - unique,
        }

    def save_json(self, path):
        payload = {
            "detected_game": self.detected_game,
            "notes": self.notes,
            "files": {fp: [e.to_dict() for e in f.entries]
                      for fp, f in self.files.items()},
        }
        Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=1), "utf-8")

    @classmethod
    def load_json(cls, path):
        payload = json.loads(Path(path).read_text("utf-8"))
        res = cls()
        res.detected_game = payload.get("detected_game")
        res.notes = payload.get("notes", [])
        for fp, entries in payload.get("files", {}).items():
            tf = TextFile(path=fp)
            for d in entries:
                e = TextEntry.from_dict(d)
                e.file = fp
                tf.entries.append(e)
            res.files[fp] = tf
        return res


def group_by_dedup_key(entries):
    """按 (原文, 类型) 分组，用于“同内容同类型复用翻译”。
    返回 [(key, [entries...])]，key=(original_stripped, category)。"""
    groups = {}
    for e in entries:
        groups.setdefault(e.dedup_key(), []).append(e)
    return list(groups.items())


# ---------------- 导出/导入 ----------------

def export_json(result, path):
    result.save_json(path)


def export_csv(result, path):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["id", "file", "offset", "category", "original", "translation", "status", "note"])
        for e in result.all_entries():
            w.writerow([e.id, e.file, e.offset, e.category, e.original,
                        e.translation, e.status, e.note])


def import_csv(path):
    """导入 CSV 译文（也可用于手工补充）。返回 {entry_id: TextEntry} 的更新。"""
    updates = {}
    with open(path, newline="", encoding="utf-8-sig") as f:
        r = csv.DictReader(f)
        for row in r:
            eid = row.get("id")
            if not eid:
                continue
            e = TextEntry.from_dict({
                "id": eid,
                "file": row.get("file", ""),
                "offset": int(row.get("offset") or 0),
                "category": row.get("category", CAT_OTHER),
                "original": row.get("original", ""),
                "translation": row.get("translation", ""),
                "status": row.get("status", "translated"),
                "note": row.get("note", ""),
            })
            updates[eid] = e
    return updates


def export_xliff(result, path):
    root = ET.Element("xliff", version="1.2", xmlns="urn:oasis:names:tc:xliff:document:1.2")
    body = ET.SubElement(root, "body")
    for e in result.all_entries():
        unit = ET.SubElement(body, "trans-unit", id=str(e.id))
        src = ET.SubElement(unit, "source")
        src.text = e.original
        tgt = ET.SubElement(unit, "target")
        tgt.text = e.translation
        ET.SubElement(unit, "note").text = "%s @%s:%s" % (e.file, e.offset, e.category)
    tree = ET.ElementTree(root)
    tree.write(path, encoding="utf-8", xml_declaration=True)


def import_xliff(path):
    updates = {}
    tree = ET.parse(path)
    root = tree.getroot()
    ns = {"x": "urn:oasis:names:tc:xliff:document:1.2"}
    for unit in root.iter("{urn:oasis:names:tc:xliff:document:1.2}trans-unit"):
        eid = unit.get("id")
        src = unit.find("x:source", ns)
        tgt = unit.find("x:target", ns)
        if src is None or src.text is None:
            continue
        e = TextEntry()
        e.id = eid
        e.original = src.text
        e.translation = tgt.text or "" if tgt is not None else ""
        note = unit.find("x:note", ns)
        if note is not None and note.text:
            m = re.match(r"(.+?) @(\d+):(.+)", note.text or "")
            if m:
                e.file, e.offset, e.category = m.group(1), int(m.group(2)), m.group(3)
        e.status = "translated" if e.translation else "untranslated"
        updates[eid] = e
    return updates
