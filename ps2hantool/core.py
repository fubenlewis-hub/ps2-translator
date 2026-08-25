# -*- coding: utf-8 -*-
"""核心流程编排：载入→提取→术语表→翻译→统一→回写→字库→打包。

GUI 与 CLI 均调用本模块；所有步骤支持 progress_cb 与 cancel_event。
"""
import json
import logging
import threading
import time
from pathlib import Path

from .plugins import load_builtin_plugins, get_manager
from .text.model import ExtractResult, TextFile
from .text.similar import DEFAULT_THRESHOLD
from .translate.engines import create_engine
from .translate.glossary import Glossary

log = logging.getLogger("ps2hantool.pipeline")


class Pipeline:
    def __init__(self, project):
        self.project = project
        self.plugin = None
        self.plugin_info = None
        self.result = None          # ExtractResult
        self.glossary = Glossary()
        self.engine = None
        self._cancel = threading.Event()

    # ---------- 工具 ----------
    def cancel(self):
        self._cancel.set()

    def reset_cancel(self):
        self._cancel = threading.Event()

    # ---------- 步骤 1：载入 ISO 并识别 ----------
    def load_iso(self, iso_path, progress_cb=None):
        self.reset_cancel()
        info = self.project.load_iso(iso_path, progress_cb)
        ctx = self._ctx()
        mgr = load_builtin_plugins()
        self.plugin, self.plugin_info = mgr.find(ctx)
        if not self.plugin:
            raise RuntimeError("未能识别游戏，也没有可用的通用插件")
        self.project.set("plugin", self.plugin.name)
        self.project.set("game_name", self.plugin_info.get("name", ""))
        self.project.log("识别游戏: %s（插件 %s）" % (
            self.plugin_info.get("name"), self.plugin.name))
        return self.plugin_info

    def _ctx(self):
        return {
            "work_dir": str(self.project.work_dir),
            "system_cnf": self.project.get("system_cnf", ""),
            "slpm": self.project.get("slpm", ""),
            "plugin": self.plugin,
        }

    def _ensure_plugin(self):
        """重开工程时从保存的 settings 恢复插件（无需重新载入 ISO）。"""
        if self.plugin:
            return self.plugin
        ctx = self._ctx()
        mgr = load_builtin_plugins()
        self.plugin, self.plugin_info = mgr.find(ctx)
        if not self.plugin:
            raise RuntimeError("未能识别游戏，也没有可用的通用插件")
        return self.plugin

    # ---------- 步骤 2：提取文本 ----------
    def extract(self, progress_cb=None):
        self._ensure_plugin()
        self.project.log("开始提取文本（插件 %s）" % self.plugin.name)
        self.result = self.plugin.extract(self._ctx(), progress_cb, self._cancel)
        self.project.extracted_path().write_text(
            json.dumps(self._result_payload(), ensure_ascii=False), "utf-8")
        stats = self.result.stats()
        self.project.log("提取完成: %d 条 / %d 字符 / %d 个文件" % (
            stats["total_entries"], stats["total_chars"], stats["files"]))
        return stats

    def _result_payload(self):
        return {
            "detected_game": self.result.detected_game,
            "notes": self.result.notes,
            "files": {fp: [e.to_dict() for e in f.entries]
                      for fp, f in self.result.files.items()},
        }

    def load_extracted(self):
        p = self.project.extracted_path()
        if p.exists():
            self.result = ExtractResult.load_json(str(p))
            # 合并已翻译结果（重开工程/跨会话断点续传：恢复译文与状态）
            tp = self.project.translated_path()
            if tp.exists():
                try:
                    payload = json.loads(tp.read_text("utf-8"))
                    by_id = {e.id: e for e in self.result.all_entries()}
                    merged = 0
                    for fp, es in payload.get("files", {}).items():
                        for d in es:
                            e = by_id.get(d.get("id"))
                            if e and d.get("translation"):
                                e.translation = d["translation"]
                                e.status = d.get("status", "translated")
                                merged += 1
                    if merged:
                        self.project.log("已恢复 %d 条译文（断点续传）" % merged)
                except Exception as ex:
                    log.warning("合并已翻译结果失败: %s", ex)
        return self.result

    # ---------- 步骤 3：术语表 ----------
    def prepare_glossary(self, auto_seed=True, search_online=False):
        self.glossary = Glossary()
        self.glossary.load_json(str(self.project.glossary_path()))
        if auto_seed:
            from .translate.glossary_search import auto_glossary_from_seed
            n = auto_glossary_from_seed(self.glossary)
            if n:
                self.project.log("内置预设术语 %d 条" % n)
        self.save_glossary()
        return self.glossary

    def save_glossary(self):
        self.glossary.save_json(str(self.project.glossary_path()))

    # ---------- 步骤 4：翻译 ----------
    def engine_test(self, cfg):
        """创建引擎并测试连接，返回 (ok, message)。"""
        self.engine = create_engine(cfg.get("kind", "openai"), cfg)
        return self.engine.test()

    def translate(self, cfg, progress_cb=None, limit=None, target_ids=None):
        if not self.result:
            raise RuntimeError("请先提取文本")
        self.engine = create_engine(cfg.get("kind", "openai"), cfg)
        if cfg.get("test_only"):
            return self.engine.test()

        entries = [e for f in self.result.files.values() for e in f.entries]
        if target_ids:
            entries = [e for e in entries if e.id in target_ids]
        if limit:
            entries = entries[:limit]
        todo = [e for e in entries if not e.translation]
        if not todo:
            return {"translated": 0, "errors": {}, "message": "没有待翻译条目"}

        # 去重复用（借鉴 GalTransl/AiNiee 的缓存复用思路）：
        # 按 (原文, 类型) 分组，每组只翻译一次，译文广播给同组所有条目。
        from .text.model import group_by_dedup_key
        groups = [g for g in group_by_dedup_key(todo) if g[1]]
        unique_count = len(groups)
        dup_count = len(todo) - unique_count
        self.project.log(
            "开始翻译：待译 %d 条，其中唯一文本 %d 条（重复 %d 条将直接复用译文）"
            "（引擎 %s / 模型 %s）" % (
                len(todo), unique_count, dup_count,
                self.engine.name, cfg.get("model", "")))

        game_ctx = self._game_context()
        # 相似文本参考（fuzzy-match 思路）：同相似组内已翻译条目的译文作为参考注入
        sim_index = self.similar_index()
        ref_used = 0
        ref_blocks = {}
        if sim_index is not None:
            for _, members in groups:
                rep = members[0]
                refs = sim_index.references_for(rep)
                if refs:
                    block = "\n".join(
                        "参考原文：%s\n参考译文：%s" % (o.strip()[:60], t.strip()[:60])
                        for o, t in refs[:3])
                    ref_blocks[rep.id] = block
                    ref_used += 1

        # 组批翻译（借鉴 AiNiee“每次翻译行数”+ 相似文本聚合）：
        # 把同一相似组内的待译代表合并为一个多行请求 → 省 system prompt 开销（省 token）、
        # 减少请求数（加速）、同组相似文本共享上下文（一致性↑）。
        reps = []                     # 代表条目（每组第一个）
        rep_by_id = {}                # id -> 代表条目
        rep2group = {}                # 代表 id -> 精确去重组（广播用）
        for _, members in groups:
            rep = members[0]
            reps.append(rep)
            rep_by_id[rep.id] = rep
            rep2group[rep.id] = members
        BATCH_MAX = 5                 # 每批最多行数（避免单请求过长）
        if sim_index is not None:
            # 按相似组聚合：同组代表放同一批；无相似组的代表各自独立成批
            sim2reps = {}             # key -> [代表...]
            for rep in reps:
                g = sim_index.group_of(rep)
                key = id(g) if g is not None else ("single", rep.id)
                sim2reps.setdefault(key, []).append(rep)
            batches = []
            for key, rs in sim2reps.items():
                for k in range(0, len(rs), BATCH_MAX):
                    batches.append([(r.id, r.original) for r in rs[k:k + BATCH_MAX]])
        else:
            batches = [[(r.id, r.original)] for r in reps]

        n_batch = len(batches)
        self.project.log("组批翻译：%d 条唯一文本，聚合为 %d 个请求（相似组共享上下文）" % (
            len(reps), n_batch))
        results, errors = self.engine.translate_batches(
            batches, glossary_block=self.glossary.format_block(),
            game_context=game_ctx, reference_block="\n\n".join(ref_blocks.values()),
            progress_cb=progress_cb, cancel_event=self._cancel)

        # 写入译文：把代表译文写入该组所有条目（重复条目直接复用），再统一保存
        for rep_id, text in results.items():
            members = rep2group.get(rep_id)
            if not members:
                continue
            for e in members:
                e.translation = text
                e.status = "translated"
        self.project.translated_path().write_text(
            json.dumps(self._result_payload(), ensure_ascii=False), "utf-8")
        reused = dup_count
        self.project.log("翻译完成: 唯一 %d 条, 复用重复 %d 条, 相似参考 %d 条, 失败 %d" % (
            len(results), reused, ref_used, len(errors)))
        return {"translated": len(results), "reused": reused,
                "ref_used": ref_used,
                "errors": errors, "unique": unique_count,
                "duplicate": dup_count, "batches": n_batch}

    def _game_context(self):
        info = (self.result and self.result.detected_game) or {}
        name = info.get("name", "")
        extra = info.get("note", "")
        if name:
            return "%s（%s）恋爱养成游戏，玩家扮演高中生与多位女主角互动。人物对话语气自然口语化，菜单文本简洁。%s" % (
                name, info.get("publisher", ""), extra)
        return ""

    # ---------- 相似文本索引（fuzzy-match 参考） ----------
    def similar_index(self, threshold=None):
        """构建/加载“部分相同文本”相似组索引（翻译时提供参考译文）。
        返回 SimilarIndex 或 None（无数据/失败时）。"""
        from .text.similar import SimilarIndex, find_similar_groups, similar_stats
        path = self.project.similar_path()
        entries = self.result.all_entries() if self.result else []
        by_id = {e.id: e for e in entries}
        if path.exists():
            try:
                return SimilarIndex().load(path, by_id)
            except Exception as e:
                self.project.log("相似索引加载失败，将重建: %s" % e)
        if not entries:
            return None
        groups = find_similar_groups(entries, threshold or DEFAULT_THRESHOLD)
        idx = SimilarIndex(groups, threshold or DEFAULT_THRESHOLD)
        try:
            idx.save(path)
        except Exception as e:
            self.project.log("相似索引保存失败: %s" % e)
        ng, nc = similar_stats(groups)
        self.project.log("相似文本检测: %d 组（覆盖 %d 条，阈值 %.2f）" % (ng, nc, idx.threshold))
        return idx

    # ---------- 步骤 5：术语统一 + 一致性检查 ----------
    def unify_terms(self, auto_fix=True):
        if not self.result:
            return []
        warnings = []
        for f in self.result.files.values():
            for e in f.entries:
                if not e.translation:
                    continue
                fixed = self.glossary.apply(e.translation)
                if fixed != e.translation:
                    if auto_fix:
                        e.translation = fixed
                    else:
                        warnings.append((e.id, e.translation, fixed))
        self.project.log("术语统一完成" if auto_fix else "术语统一预览完成")
        return warnings

    def consistency_report(self):
        texts = [(e.id, e.translation) for f in self.result.files.values()
                 for e in f.entries if e.translation]
        return self.glossary.check_consistency(texts)

    # ---------- 步骤 6：回写 ----------
    def writeback(self, progress_cb=None):
        self._ensure_plugin()
        if not self.result:
            raise RuntimeError("缺少提取结果")
        # 备份将被修改的文件
        touched = sorted({e.file for f in self.result.files.values() for e in f.entries
                          if e.translation})
        if touched:
            self.project.backup_files(touched)
        report = self.plugin.writeback(self._ctx(), self.result, progress_cb, self._cancel)
        self.project.log("回写完成: %s" % report)
        return report

    # ---------- 步骤 7：字库 ----------
    def build_font(self, size=16, charset=None, font_path=None):
        from .font.bitmap import BitmapFont
        self.project.log("生成 %dpx 点阵字库…" % size)
        bf = BitmapFont.generate(size=size, charset=charset, font_path=font_path)
        out = self.project.data_dir / "font_%dpx" % size
        bf.save(str(out))
        self.project.log("字库生成完成: %d 字" % len(bf.chars))
        return bf, str(out)

    def inject_font(self, bf, progress_cb=None):
        """尝试调用插件字库注入；插件未实现则返回降级方案。"""
        support = self.plugin.font_support(self._ctx()) if self.plugin else None
        return {
            "support": support,
            "degraded": True,
            "note": ("字库注入需要游戏字库格式逆向支持。已生成点阵字库文件（data/font_*px.bin+json），"
                     "可结合 TiledGGD 等工具人工对照替换，或等待插件完善。"),
        }

    # ---------- 步骤 8：打包 ----------
    def rebuild(self, progress_cb=None):
        from .iso import rebuild_iso
        out = self.project.output_dir / ("hanyihua_%s.iso" % self.project.get("slpm", "game"))
        self.project.log("开始重新打包 ISO → %s" % out.name)
        rebuild_iso(self.project.work_dir, out, progress_cb)
        self.project.log("打包完成: %s（%.1f MB）" % (out.name, out.stat().st_size / 1048576))
        return out
