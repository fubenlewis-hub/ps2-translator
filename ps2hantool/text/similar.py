# -*- coding: utf-8 -*-
"""近重复（相似）文本检测：找出“部分相同/大部分相同”的文本簇。

思路（借鉴 text-dedup 的候选生成 + OmegaT 翻译记忆的模糊匹配）：
1. 候选生成：首/尾 8 字符倒排索引 + 长度差 ≤25% 过滤（相似文本通常共享前缀或后缀）；
2. 精算：difflib.SequenceMatcher 相似度 ≥ threshold 才算相似对；
3. 聚簇：union-find 把相似对连通成分合并为“相似组”。

用途：翻译时把同组内已翻译条目的译文作为参考注入 LLM（fuzzy-match 参考），
提高译文一致性并复用可复用部分（不自动替换，避免语义误伤）。
"""
import difflib
import json
from collections import defaultdict
from pathlib import Path

DEFAULT_THRESHOLD = 0.85
_MIN_LEN = 8          # 过短文本（如“はい”）相似无意义，且已由精确去重处理
_MAX_LEN_DIFF = 0.25  # 长度差上限（比例）
_PREFIX_N = 4         # 前缀/后缀索引长度（4 字符可抓住“共享开头、中段差异”的相似句）


def find_similar_groups(entries, threshold=DEFAULT_THRESHOLD):
    """返回相似组列表：每组为 [entry, ...]（≥2 条），组内文本两两连通（相似度链）。"""
    docs = [e for e in entries if len(e.original.strip()) >= _MIN_LEN]
    n = len(docs)
    if n < 2:
        return []

    texts = [e.original.strip() for e in docs]
    pre = defaultdict(list)
    suf = defaultdict(list)
    for i, t in enumerate(texts):
        pre[t[:_PREFIX_N]].append(i)
        suf[t[-_PREFIX_N:]].append(i)

    pairs = set()
    for bucket in list(pre.values()) + list(suf.values()):
        if len(bucket) < 2:
            continue
        for a in range(len(bucket)):
            for b in range(a + 1, len(bucket)):
                i, j = bucket[a], bucket[b]
                li, lj = len(texts[i]), len(texts[j])
                if abs(li - lj) / max(li, lj) > _MAX_LEN_DIFF:
                    continue
                pairs.add((min(i, j), max(i, j)))

    # union-find
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i, j in pairs:
        if difflib.SequenceMatcher(None, texts[i], texts[j]).ratio() >= threshold:
            ri, rj = find(i), find(j)
            if ri != rj:
                parent[rj] = ri

    groups = defaultdict(list)
    for i in range(n):
        groups[find(i)].append(docs[i])
    out = [sorted(members, key=lambda e: (e.original, e.id or ""))
           for members in groups.values() if len(members) >= 2]
    out.sort(key=lambda g: -len(g))
    return out


def similar_stats(groups):
    """返回 (组数, 覆盖条数)。"""
    return len(groups), sum(len(g) for g in groups)


class SimilarIndex:
    """相似组索引：可保存/加载到工程 data/similar.json。"""

    def __init__(self, groups=None, threshold=DEFAULT_THRESHOLD):
        self.groups = groups or []      # 每组 [TextEntry, ...]
        self.threshold = threshold
        # id -> group 成员映射（供翻译时查参考）
        self._by_entry = {}
        self._rebuild()

    def _rebuild(self):
        self._by_entry = {}
        for g in self.groups:
            for e in g:
                self._by_entry[e.id] = g

    def references_for(self, entry):
        """返回同组内【已翻译】条目的参考 [(原文, 译文), ...]（不含 entry 自身）。"""
        g = self._by_entry.get(entry.id)
        if not g:
            return []
        out = []
        for m in g:
            if m is entry:
                continue
            if m.translation and m.status in ("translated", "reviewed"):
                out.append((m.original, m.translation))
        return out

    def group_of(self, entry):
        """返回 entry 所属相似组（list[TextEntry]）或 None。"""
        return self._by_entry.get(entry.id)

    def save(self, path):
        payload = {
            "threshold": self.threshold,
            "groups": [[e.id for e in g] for g in self.groups],
        }
        Path(path).write_text(json.dumps(payload, ensure_ascii=False), "utf-8")

    def load(self, path, entries_by_id):
        payload = json.loads(Path(path).read_text("utf-8"))
        self.threshold = payload.get("threshold", DEFAULT_THRESHOLD)
        self.groups = []
        for ids in payload.get("groups", []):
            g = [entries_by_id[i] for i in ids if i in entries_by_id]
            if len(g) >= 2:
                self.groups.append(g)
        self._rebuild()
        return self
