# -*- coding: utf-8 -*-
"""术语表：模型、增删改查、导入导出、自动统一替换、一致性检查。"""
import csv
import json
import re
from pathlib import Path


class Glossary:
    def __init__(self):
        self.terms = {}   # 日文原文 -> {"zh": 中文, "note": 备注, "source": 来源}
        self.zh_lookup = None

    # ---------- 基础操作 ----------
    def add(self, jp, zh, note="", source=""):
        jp = (jp or "").strip()
        if not jp:
            return False
        if jp not in self.terms:
            self.terms[jp] = {}
        self.terms[jp]["zh"] = zh or ""
        if note:
            self.terms[jp]["note"] = note
        if source:
            self.terms[jp]["source"] = source
        self._rebuild()
        return True

    def remove(self, jp):
        self.terms.pop(jp, None)
        self._rebuild()

    def update(self, jp, zh=None, note=None, source=None):
        if jp not in self.terms:
            return False
        if zh is not None:
            self.terms[jp]["zh"] = zh
        if note is not None:
            self.terms[jp]["note"] = note
        if source is not None:
            self.terms[jp]["source"] = source
        self._rebuild()
        return True

    def search(self, kw):
        kw = (kw or "").lower()
        if not kw:
            return list(self.terms.items())
        out = []
        for jp, v in self.terms.items():
            if kw in jp.lower() or kw in (v.get("zh") or "").lower() or kw in (v.get("note") or "").lower():
                out.append((jp, v))
        return out

    def _rebuild(self):
        # 中文名 -> 日文名（用于一致性检查）
        self.zh_lookup = {}
        for jp, v in self.terms.items():
            zh = v.get("zh")
            if zh:
                self.zh_lookup.setdefault(zh, jp)

    def __len__(self):
        return len(self.terms)

    # ---------- 持久化 ----------
    def save_json(self, path):
        Path(path).write_text(json.dumps(self.terms, ensure_ascii=False, indent=2), "utf-8")

    def load_json(self, path):
        if Path(path).exists():
            self.terms = json.loads(Path(path).read_text("utf-8"))
            self._rebuild()
            return True
        return False

    def export_csv(self, path):
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["日文", "中文", "备注", "来源"])
            for jp, v in self.terms.items():
                w.writerow([jp, v.get("zh", ""), v.get("note", ""), v.get("source", "")])

    def import_csv(self, path):
        n = 0
        with open(path, newline="", encoding="utf-8-sig") as f:
            for row in csv.reader(f):
                if not row or not row[0].strip():
                    continue
                if row[0].strip() == "日文":
                    continue
                jp = row[0].strip()
                zh = row[1].strip() if len(row) > 1 else ""
                note = row[2].strip() if len(row) > 2 else ""
                src = row[3].strip() if len(row) > 3 else ""
                if self.add(jp, zh, note, src):
                    n += 1
        return n

    def format_block(self):
        """生成注入翻译 prompt 的术语表文本。"""
        lines = []
        for jp, v in self.terms.items():
            zh = v.get("zh")
            if zh:
                lines.append("%s → %s" % (jp, zh))
        return "\n".join(lines)

    # ---------- 自动统一 ----------
    def apply(self, text):
        """把术语表里的日文名词替换为中译（长词优先）。"""
        if not text:
            return text
        keys = sorted(self.terms.keys(), key=len, reverse=True)
        for k in keys:
            zh = self.terms[k].get("zh")
            if zh:
                text = text.replace(k, zh)
        return text

    # ---------- 一致性检查 ----------
    def check_consistency(self, translated_texts):
        """
        translated_texts: list[(entry_id, translation)]
        返回 [(entry_id, 原文片段, 疑似译文, 术语中译, 说明)] —— 术语表外写法。
        """
        issues = []
        for eid, t in translated_texts:
            for jp, v in self.terms.items():
                zh = v.get("zh")
                if not zh or zh not in t:
                    continue
                # 检查译文是否包含日文原名残留（说明未替换/混用）
                if jp in t:
                    issues.append((eid, jp, zh, "译文仍含日文原名"))
                # 检查中译是否带错误符号
                if zh + zh in t:
                    issues.append((eid, zh, zh, "疑似术语重复"))
        return issues


def term_frequency(result, top=60):
    """统计文本中的高频词（含假名/汉字，≥2 字符），供术语表补充建议。"""
    import collections
    from ..text.extractor import SjisRunExtractor, KANA
    counter = collections.Counter()
    for f in result.files.values():
        for e in f.entries:
            text = e.original
            # 简单 n-gram 高频词：长度 2~4 的字串
            for n in (2, 3, 4):
                for i in range(0, max(1, len(text) - n + 1)):
                    seg = text[i:i + n]
                    if any(c in KANA for c in seg) and not seg.isascii():
                        counter[seg] += 1
    return counter.most_common(top)
