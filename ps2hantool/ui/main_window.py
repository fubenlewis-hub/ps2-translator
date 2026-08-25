# -*- coding: utf-8 -*-
"""主窗口：左侧流程导航 + 页面堆栈 + 后台流水线 + 状态机。"""
import logging
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QListWidget,
    QListWidgetItem, QStackedWidget, QMessageBox, QFileDialog, QApplication,
)

from ..core import Pipeline
from ..project import Project
from ..state import AppState, STATE_TEXT
from .workers import PipelineWorker
from .pages import (HomePage, ExtractPage, GlossaryPage, SettingsPage,
                    ReviewPage, LogPage, TermCandidateDialog)

log = logging.getLogger("ps2hantool.ui")


class MainWindow(QMainWindow):
    # 日志/进度统一走信号队列，保证 UI 只被主线程触碰（工作线程直改 QWidget 会触发 Qt fatal → abort 闪退）
    logSignal = Signal(str)

    def __init__(self, project_dir=None):
        super().__init__()
        self.setWindowTitle("PS2 游戏一键汉化工具")
        self.resize(1180, 780)

        # 中央：左侧导航 + 页面堆栈
        central = QWidget()
        root = QHBoxLayout(central)
        self.nav = QListWidget()
        self.nav.setFixedWidth(170)
        self.nav.addItems(["1 首页/流程", "2 提取结果", "3 术语管理",
                           "4 翻译设置", "5 文本校对", "6 日志/报告"])
        self.nav.currentRowChanged.connect(self._nav)
        self.stack = QStackedWidget()
        self.home = HomePage()
        self.extract = ExtractPage()
        self.glossary_page = GlossaryPage()
        self.settings = SettingsPage()
        self.review = ReviewPage()
        self.logpage = LogPage()
        for w in (self.home, self.extract, self.glossary_page,
                  self.settings, self.review, self.logpage):
            self.stack.addWidget(w)
        root.addWidget(self.nav)
        root.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        # 底部状态栏（状态机实时显示）
        self.statusBar().showMessage("就绪")

        # 事件
        self.home.loadRequested.connect(self._load_iso)
        self.home.stepRequested.connect(self._step)
        self.extract.glossaryRequested.connect(lambda: self._goto(2))
        self.extract.confirmRequested.connect(self._run_all)
        self.extract.translateRequested.connect(self._run_translate)
        self.glossary_page.glossaryChanged.connect(self._glossary_changed)
        self.glossary_page.onlineRequested.connect(self._glossary_online)
        self.glossary_page.aiRequested.connect(self._glossary_ai)
        self.settings.testRequested.connect(self._test_engine)
        self.settings.saved.connect(self._save_settings)
        self.settings.savedAndTranslateRequested.connect(self._run_translate)
        self.logpage.reportRequested.connect(self._consistency_report)

        self.pipeline = None
        self.worker = None
        self._detached_workers = []
        self.project_dir = project_dir
        self._iso_path = ""
        self.state = AppState.IDLE
        self._init_log_hook()
        self._set_state(AppState.IDLE)

        if project_dir:
            self._open_project(project_dir)

    # ---------- 状态机 ----------
    # 忙碌状态集合（显示进度条）
    _BUSY_STATES = {AppState.LOADING, AppState.EXTRACTING,
                    AppState.TRANSLATING, AppState.WRITEBACKING,
                    AppState.BUILDING}

    def _set_state(self, state, msg=None):
        """更新状态机：主页横幅 + 进度条 + 底部状态栏 + 日志。"""
        self.state = state
        text = STATE_TEXT[state]
        self.home.set_state_text("当前状态：%s" % text)
        self.home.set_busy(state in self._BUSY_STATES)
        self.statusBar().showMessage("状态：%s" % text)
        if msg:
            self.logpage.append(msg)

    # ---------- 日志钩子 ----------
    def _init_log_hook(self):
        """日志可来自工作线程：handler 只 emit 信号（跨线程安全），
        由信号槽在主线程刷新 QPlainTextEdit，避免跨线程操作 Qt 控件导致崩溃。"""
        class Handler(logging.Handler):
            def __init__(self, win):
                super().__init__()
                self.win = win

            def emit(self, record):
                try:
                    self.win.logSignal.emit(record.getMessage())
                except Exception:
                    pass

        h = Handler(self)
        h.setLevel(logging.INFO)
        logging.getLogger().addHandler(h)          # 只挂 root，子 logger 自动传播
        for name in ("ps2hantool",):
            logging.getLogger(name).setLevel(logging.INFO)
        self.logSignal.connect(self.logpage.append)

    # ---------- 导航 ----------
    def _nav(self, row):
        self.stack.setCurrentIndex(max(0, row))

    def _goto(self, idx):
        self.nav.setCurrentRow(idx)

    # ---------- 工程 ----------
    def _open_project(self, project_dir):
        try:
            self.pipeline = Pipeline(Project(Path(project_dir)))
            self.pipeline.load_extracted()
            self.pipeline.prepare_glossary(auto_seed=True)
            try:
                self.pipeline._ensure_plugin()
            except Exception:
                pass
            self.extract.refresh(self.pipeline.result, self.pipeline.glossary)
            self.glossary_page.set_glossary(self.pipeline.glossary)
            self.review.set_result(self.pipeline.result)
            cfg = self.pipeline.project.load_settings().get("engine", {})
            self.settings.load_cfg(cfg)
            if self.pipeline.plugin_info:
                self.home.set_detected("已载入工程：%s（%s）" % (
                    self.pipeline.plugin_info.get("name", "未知游戏"),
                    self.pipeline.plugin_info.get("slpm", "")))
            elif self.pipeline.result:
                self.home.set_detected("已载入工程（提取结果 %d 条）" % len(
                    self.pipeline.result.all_entries()))
            if self.pipeline.result and self.pipeline.result.all_entries():
                self._set_state(AppState.EXTRACTED, "已载入工程，可继续流程")
                try:
                    sim = self.pipeline.similar_index()
                    if sim is not None and sim.groups:
                        self.extract.stats_label.setText(
                            self.extract.stats_label.text() + "\n相似文本：%d 组（覆盖 %d 条）" % (
                                len(sim.groups), sum(len(g) for g in sim.groups)))
                except Exception:
                    pass
            else:
                self._set_state(AppState.LOADED, "已载入工程，可提取文本")
        except Exception as e:
            self.logpage.append("打开工程失败: %s" % e)
            self._set_state(AppState.ERROR, "打开工程失败: %s" % e)

    # ---------- 流程步骤（按钮 key 与功能一一对应）----------
    def _step(self, key):
        if key == "extract":
            self._run_extract()
        elif key == "glossary":
            if not self.pipeline:
                QMessageBox.warning(self, "提示", "请先载入 ISO")
                return
            self._goto(2)
        elif key == "settings":
            self._goto(3)
        elif key == "translate":
            self._run_translate()
        elif key == "review":
            self._goto(4)
        elif key == "logs":
            self._goto(5)
        elif key == "run":
            self._run_all()

    # ---------- 载入 ISO ----------
    def _load_iso(self, iso_path):
        self._iso_path = iso_path
        if not self.project_dir:
            from .. import get_app_root
            tool_root = get_app_root()
            name = Path(iso_path).stem
            self.project_dir = str(tool_root / "projects" / name)
        from ..core import Pipeline
        from ..project import Project
        self.pipeline = Pipeline(Project(Path(self.project_dir)))
        self.pipeline.project.ensure_dirs()
        self._set_state(AppState.LOADING, "开始载入：%s" % Path(iso_path).name)
        self.home.set_progress("正在载入 ISO 并整盘提取（耗时取决于光盘大小）…")
        self._start_worker(self._task_load, self._on_loaded, "载入")

    def _task_load(self, pl, emit):
        # Project.load_iso 的进度回调是单参字符串（"提取 i/total path"），
        # 解析 i/total 转成结构化进度；re 在模块级已导入
        import re as _re
        def cb(msg):
            m = _re.match(r"提取 (\d+)/(\d+)", msg)
            if m:
                emit(msg, int(m.group(1)), int(m.group(2)))
            else:
                emit(msg, -1, -1)
        info = pl.load_iso(self._iso_path, cb)
        emit("识别完成", -1, -1)
        return info

    def _on_loaded(self, info):
        self.pipeline.prepare_glossary(auto_seed=True)
        self.settings.load_cfg(self.pipeline.project.load_settings().get("engine", {}))
        self.home.set_detected("已识别：%s（%s）｜插件：%s\n工程目录：%s" % (
            info.get("name", ""), info.get("slpm", ""),
            self.pipeline.plugin.display_name, self.project_dir))
        self._set_state(AppState.LOADED, "载入完成，请点击「① 提取文本」")
        self._goto(1)

    # ---------- 提取 ----------
    def _run_extract(self):
        if not self.pipeline:
            QMessageBox.warning(self, "提示", "请先载入 ISO")
            return
        self._set_state(AppState.EXTRACTING, "开始提取文本…")
        self.home.set_progress("正在提取文本…")
        self._start_worker(self._task_extract, self._on_extracted, "提取")

    def _task_extract(self, pl, emit):
        # 插件 extract 的进度回调是单参文本 → 桥接为不确定进度
        stats = pl.extract(lambda m: emit(m, -1, -1))
        pl.prepare_glossary(auto_seed=True)
        emit("提取完成", -1, -1)
        return stats

    def _on_extracted(self, stats):
        self.extract.refresh(self.pipeline.result, self.pipeline.glossary)
        self.glossary_page.set_glossary(self.pipeline.glossary)
        self.review.set_result(self.pipeline.result)
        uniq = stats.get("unique_entries", stats["total_entries"])
        dup = stats.get("duplicate_entries", 0)
        # 相似文本检测（部分相同文本簇，翻译时提供参考译文）
        sim_msg = ""
        try:
            sim = self.pipeline.similar_index()
            if sim is not None and sim.groups:
                ng = len(sim.groups)
                nc = sum(len(g) for g in sim.groups)
                sim_msg = "检测到 %d 组相似文本（覆盖 %d 条，翻译时自动参考已有译文）。" % (ng, nc)
                self.extract.stats_label.setText(
                    self.extract.stats_label.text() + "\n%s" % sim_msg)
        except Exception as e:
            self.logpage.append("相似文本检测失败（不影响流程）: %s" % e)
        self._set_state(AppState.EXTRACTED, "提取完成：%d 条 / %d 字符" % (
            stats["total_entries"], stats["total_chars"]))
        self._goto(1)
        dup_msg = "其中重复文本 %d 条（翻译时会自动复用译文）。" % dup if dup else ""
        QMessageBox.information(self, "提取完成",
                                "提取到 %d 条文本（%d 字符），唯一文本 %d 条。\n%s\n%s\n"
                                "请到「② 确认术语表 / 术语管理」确认术语，"
                                "再点「④ 开始翻译」。" % (
                                    stats["total_entries"], stats["total_chars"],
                                    uniq, dup_msg, sim_msg))

    # ---------- 翻译 ----------
    def _run_translate(self, cfg=None):
        if not self.pipeline or not self.pipeline.result:
            QMessageBox.warning(self, "提示", "请先提取文本")
            return
        if cfg is None:
            cfg = self.pipeline.project.load_settings().get("engine", {})
        if not cfg.get("base_url") or not cfg.get("model"):
            QMessageBox.information(self, "提示", "请先到「③ 翻译设置」配置翻译引擎")
            self._goto(3)
            return
        self.pipeline.project.set("engine", cfg)
        self._set_state(AppState.TRANSLATING, "开始翻译（引擎 %s / %s）…" % (
            cfg.get("kind", "openai"), cfg.get("model", "")))
        # 翻译进度：translate_batch 回调 (done, total) → emit(msg, done, total)
        self._start_worker(
            lambda pl, emit: pl.translate(
                cfg, lambda d, t: emit("已翻译 %d/%d 条" % (d, t), d, t)),
            self._on_translated, "翻译")

    def _on_translated(self, r):
        self.review.set_result(self.pipeline.result)
        ok_n = r.get("translated", 0)
        reused = r.get("reused", 0)
        ref_used = r.get("ref_used", 0)
        err_n = len(r.get("errors", {}))
        self._set_state(AppState.TRANSLATED,
                        "翻译完成：唯一 %d 条，复用重复 %d 条，相似参考 %d 条，失败 %d 条" % (
                            ok_n, reused, ref_used, err_n))
        self._goto(4)
        reuse_msg = "其中 %d 条重复文本直接复用了译文；%d 条使用了相似文本参考。" % (
            reused, ref_used) if (reused or ref_used) else ""
        QMessageBox.information(self, "翻译完成",
                                "翻译完成：翻译 %d 条唯一文本，复用重复 %d 条，"
                                "相似参考 %d 条，失败 %d 条。\n%s\n"
                                "可到「文本校对」页查看/修改译文，"
                                "然后回首页点「一键全流程」或直接开始回写打包。" % (
                                    ok_n, reused, ref_used, err_n, reuse_msg))

    # ---------- 术语 ----------
    def _glossary_changed(self):
        if self.pipeline:
            self.pipeline.save_glossary()

    def _glossary_online(self):
        if not self.pipeline or not self.pipeline.result:
            QMessageBox.warning(self, "提示", "请先提取文本")
            return
        import collections
        import re
        # 候选1：说话人名（「 前 1~8 字，如 二宮「…）
        names = collections.Counter()
        for f in self.pipeline.result.files.values():
            for e in f.entries:
                m = re.match(r"^([^\n「」]{1,8})「", e.original)
                if m:
                    names[m.group(1)] += 1
                # 候选2：独立短行（2~6 字、纯假名/汉字、无标点）——
                # 游戏中的名字/地名选择列表常为这种格式（如“きたやま”“もりなが”）
                for line in e.original.split("\n"):
                    line = line.strip()
                    if (2 <= len(line) <= 6
                            and re.fullmatch(r"[ぁ-んァ-ヶ一-龥]{2,6}", line)
                            and "ー" not in line):
                        names[line] += 1
        # 按出现次数取高频未知术语（≤15 个，避免检索过多）
        unknown = [n for n, c in names.most_common()
                   if n not in self.pipeline.glossary.terms][:15]
        if not unknown:
            QMessageBox.information(self, "联网搜索", "没有需要检索的新术语（名字已在术语表）")
            return
        from ..translate.glossary_search import suggest_terms
        self._set_state(self.state, "联网检索 %d 个术语…" % len(unknown))
        self.home.set_busy(True)
        self._start_worker(
            lambda pl, emit: suggest_terms(pl.glossary, unknown),
            self._on_glossary_online, "术语搜索")

    def _on_glossary_online(self, hits):
        self.home.set_busy(False)
        if not hits:
            QMessageBox.information(self, "联网搜索",
                                    "未检索到可用结果（可能网络不通），请用「AI 抽取术语」或手动添加")
            self._set_state(self.state)
            return
        # 统计每个术语在原文中的出现次数（辅助用户判断重要性）
        counts = {}
        if self.pipeline and self.pipeline.result:
            for f in self.pipeline.result.files.values():
                for e in f.entries:
                    for t in hits:
                        if t in e.original:
                            counts[t] = counts.get(t, 0) + 1
        dlg = TermCandidateDialog(hits, title="联网搜索术语候选（勾选采纳）",
                                  counts=counts, parent=self)
        if dlg.exec():
            picked = dlg.get_result()
            n = self._adopt_terms(picked, source="网络搜索")
            QMessageBox.information(self, "采纳完成", "已采纳 %d 条术语。" % n)
        self._set_state(self.state)

    def _glossary_ai(self):
        if not self.pipeline or not self.pipeline.result:
            QMessageBox.warning(self, "提示", "请先提取文本")
            return
        cfg = self.pipeline.project.load_settings().get("engine", {})
        if not cfg.get("base_url") or not cfg.get("model"):
            QMessageBox.information(self, "提示", "AI 抽取需要翻译引擎，请先到「③ 翻译设置」配置")
            self._goto(3)
            return
        entries = self.pipeline.result.all_entries()
        # 抽样：去重后取前若干条文本（按长度排序取有信息量的）
        texts = sorted({e.original for e in entries if len(e.original) > 4},
                       key=len, reverse=True)[:240]
        from ..translate.engines import create_engine
        from ..translate.glossary_search import ai_extract
        self._set_state(AppState.TRANSLATING, "AI 术语抽取中（调用翻译引擎，可能需要一些时间）…")
        self._start_worker(
            lambda pl, emit: ai_extract(
                create_engine(cfg.get("kind", "openai"), cfg), texts,
                progress_cb=lambda done, total: emit(
                    "AI 抽取 %d/%d" % (done, total), done, total)),
            self._on_glossary_ai, "AI术语抽取")

    def _on_glossary_ai(self, terms):
        if not terms:
            QMessageBox.information(self, "AI 抽取", "未抽取到可用术语（检查引擎配置/日志）")
            self._set_state(self.state)
            return
        # 转成候选格式 {term: [(zh, "AI抽取", note)]}
        candidates = {t: [(v[0], "AI抽取", "%s｜%s" % (v[1], v[2]))]
                      for t, v in terms.items() if t and v[0]}
        dlg = TermCandidateDialog(candidates, title="AI 抽取术语候选（勾选采纳）", parent=self)
        if dlg.exec():
            picked = dlg.get_result()
            n = self._adopt_terms(picked, source="AI抽取")
            QMessageBox.information(self, "采纳完成", "已采纳 %d 条术语。" % n)
        self._set_state(self.state)

    def _adopt_terms(self, picked, source="网络搜索"):
        n = 0
        for term, zh in picked.items():
            if term and zh:
                if self.pipeline.glossary.add(term, zh, source=source):
                    n += 1
                else:
                    self.pipeline.glossary.update(term, zh=zh, source=source)
                    n += 1
        self.pipeline.save_glossary()
        self.glossary_page.set_glossary(self.pipeline.glossary)
        return n

    # ---------- 引擎测试/设置 ----------
    def _test_engine(self, cfg):
        self._start_worker(
            lambda pl, emit: pl.engine_test(cfg),
            lambda ok: self.settings.test_result.setText(
                "✅ 连接成功" if ok[0] else "❌ %s" % ok[1]), "引擎测试")

    def _save_settings(self, cfg):
        if self.pipeline:
            self.pipeline.project.set("engine", cfg)
        QMessageBox.information(self, "设置", "翻译设置已保存")

    # ---------- 一致性报告 ----------
    def _consistency_report(self):
        if not self.pipeline or not self.pipeline.result:
            QMessageBox.warning(self, "提示", "请先提取并翻译")
            return
        issues = self.pipeline.consistency_report()
        if not issues:
            self.logpage.set_report("未发现术语不一致问题。")
        else:
            lines = ["共发现 %d 处疑似不一致：" % len(issues)]
            for eid, jp, zh, why in issues[:200]:
                lines.append("  %s ｜ 术语 %s→%s ｜ %s" % (eid, jp, zh, why))
            self.logpage.set_report("\n".join(lines))

    # ---------- 一键全流程 ----------
    def _run_all(self):
        if not self.pipeline:
            QMessageBox.warning(self, "提示", "请先载入 ISO")
            return
        if not self.pipeline.result:
            self._run_extract()
            QTimer.singleShot(200, self._run_all)
            return
        cfg = self.pipeline.project.load_settings().get("engine", {})
        if not cfg.get("base_url") or not cfg.get("model"):
            QMessageBox.information(self, "提示", "请先到「③ 翻译设置」配置翻译引擎")
            self._goto(3)
            return
        self._set_state(AppState.TRANSLATING, "一键流程开始…")
        self._start_worker(self._task_run_all, self._on_run_done, "汉化")

    def _task_run_all(self, pl, emit):
        emit("→ 翻译…", -1, -1)
        cfg = pl.project.load_settings().get("engine", {})
        r = pl.translate(cfg, lambda d, t: emit("已翻译 %d/%d 条" % (d, t), d, t))
        emit("→ 术语统一…", -1, -1)
        pl.unify_terms()
        emit("→ 回写文件…", -1, -1)
        wb = pl.writeback(lambda m: emit(m, -1, -1))
        if wb.get("unmapped_chars"):
            emit("未映射字符: %s" % wb["unmapped_chars"], -1, -1)
        emit("→ 生成字库…", -1, -1)
        try:
            bf, _ = pl.build_font(size=16)
            font_info = pl.inject_font(bf)
            emit("字库方案: %s" % font_info.get("note", "")[:60], -1, -1)
        except Exception as e:
            emit("字库生成失败（可继续打包）: %s" % e, -1, -1)
        emit("→ 重新打包 ISO…", -1, -1)
        out = pl.rebuild(lambda i, t, rel: emit("打包 %d/%d %s" % (i, t, rel), i, t))
        return out

    def _on_run_done(self, out):
        self.logpage.append("✅ 汉化完成，输出：%s" % out)
        self._set_state(AppState.DONE, "汉化完成，输出：%s" % out)
        self._goto(5)
        QMessageBox.information(self, "汉化完成",
                                "汉化 ISO 已生成：\n%s\n\n可在 PCSX2 中加载测试。" % out)

    # ---------- 通用 worker ----------
    def _start_worker(self, task, on_done, label):
        if self.worker and self.worker.isRunning():
            QMessageBox.information(self, "提示", "已有任务在执行")
            return
        self.worker = PipelineWorker(self.pipeline, task, self)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished_ok.connect(on_done)
        self.worker.failed.connect(lambda e: self._on_task_fail(label, e))
        self.worker.start()

    def _on_progress(self, msg, done=-1, total=-1):
        self.logpage.append(msg)
        if done >= 0 and total > 0:
            # 确定进度：进度条 + 状态横幅（"已翻译 X/Y (Z%)"）
            pct = min(100, int(done * 100 / total))
            self.home.update_progress(done, total, pct, msg)
            self.statusBar().showMessage("进度：%s（%d%%）" % (msg, pct), 8000)
        else:
            self.statusBar().showMessage(msg, 8000)

    def _on_task_fail(self, label, err):
        self.logpage.append("❌ %s失败：%s" % (label, err))
        self.home.set_detected("任务失败：%s" % err)
        self._set_state(AppState.ERROR, "%s失败：%s" % (label, err))
        QMessageBox.warning(self, "任务失败", "%s失败：\n%s" % (label, err))

    def closeEvent(self, ev):
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(3000)
            if self.worker.isRunning():
                # 线程仍在跑：移交给“僵尸列表”持有引用，避免 QThread 对象被销毁时
                # 触发 “QThread: Destroyed while thread is still running” fatal（abort 闪退）。
                self._detached_workers.append(self.worker)
                self.worker.setParent(None)
                self.worker = None
        super().closeEvent(ev)


def run_gui(project_dir=None):
    app = QApplication(sys.argv)
    win = MainWindow(project_dir)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run_gui()
