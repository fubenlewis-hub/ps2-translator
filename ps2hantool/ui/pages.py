# -*- coding: utf-8 -*-
"""GUI 页面集合（首页/提取结果/术语表/翻译设置/校对/日志报告）。"""
import json
import threading
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QWidget, QLabel, QPushButton, QLineEdit, QComboBox, QTableWidget,
    QTableWidgetItem, QVBoxLayout, QHBoxLayout, QGridLayout, QFormLayout,
    QGroupBox, QFileDialog, QMessageBox, QPlainTextEdit, QProgressBar,
    QHeaderView, QSplitter, QCheckBox, QSpinBox, QDoubleSpinBox,
    QTabWidget, QDialog, QDialogButtonBox, QTextEdit,
)

from ..text.model import export_json, export_csv, export_xliff, import_csv, import_xliff
from ..translate.glossary import Glossary


def _label(text, bold=False):
    l = QLabel(text)
    if bold:
        f = QFont()
        f.setBold(True)
        l.setFont(f)
    return l


# ================= 首页 / 流程页 =================
class HomePage(QWidget):
    loadRequested = Signal(str)          # iso path
    stepRequested = Signal(str)          # 'extract'/'glossary'/'settings'/'translate'/'review'/'logs'/'run'

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.addWidget(_label("通用 PS2 游戏一键汉化工具", bold=True))
        lay.addWidget(_label("载入正版游戏 ISO → 提取文本 → 确认术语表 → 翻译 → 回写打包。仅限个人学习研究使用。"))

        # 当前状态横幅（由状态机驱动）
        self.state_label = _label("当前状态：空闲（请载入 ISO）", bold=True)
        self.state_label.setStyleSheet(
            "background:#EAF2FF; color:#1F4E9C; border:1px solid #BCD3F5;"
            "border-radius:6px; padding:8px;")
        lay.addWidget(self.state_label)

        # 实时进度条（载入/提取/翻译/打包时由状态机驱动）
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)          # 0=忙碌(不确定模式)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setFixedHeight(10)
        self.progress_bar.hide()
        lay.addWidget(self.progress_bar)

        g = QGroupBox("第 1 步：载入 ISO")
        gl = QGridLayout(g)
        self.iso_edit = QLineEdit()
        self.iso_edit.setPlaceholderText("选择 PS2 游戏 ISO（ISO9660，支持 .iso/.cue/.bin）…")
        btn = QPushButton("浏览…")
        btn.clicked.connect(self._browse)
        self.load_btn = QPushButton("载入并检测游戏")
        self.load_btn.clicked.connect(self._load)
        gl.addWidget(self.iso_edit, 0, 0, 1, 2)
        gl.addWidget(btn, 0, 2)
        gl.addWidget(self.load_btn, 1, 0, 1, 3)
        lay.addWidget(g)

        self.detect_label = _label("未载入")
        lay.addWidget(self.detect_label)

        g2 = QGroupBox("流程步骤（按顺序执行）")
        g2l = QGridLayout(g2)
        # 按钮文字与 key 一一对应（key 由 MainWindow._step 处理）
        steps = [("① 提取文本", "extract"), ("② 确认术语表", "glossary"),
                 ("③ 翻译设置", "settings"), ("④ 开始翻译", "translate"),
                 ("⑤ 文本校对", "review"), ("⑥ 日志/报告", "logs")]
        self.step_btns = {}
        for i, (txt, key) in enumerate(steps):
            b = QPushButton(txt)
            b.setEnabled(False)
            b.clicked.connect(lambda _=False, k=key: self.stepRequested.emit(k))
            g2l.addWidget(b, i // 3, i % 3)
            self.step_btns[key] = b
        lay.addWidget(g2)

        self.run_btn = QPushButton("一键全流程（提取→翻译→回写→打包）")
        self.run_btn.setEnabled(False)
        self.run_btn.clicked.connect(lambda: self.stepRequested.emit("run"))
        lay.addWidget(self.run_btn)
        lay.addStretch(1)

    def _browse(self):
        p, _ = QFileDialog.getOpenFileName(self, "选择 PS2 ISO",
                                           "", "PS2 镜像 (*.iso *.bin *.cue);;所有文件 (*)")
        if p:
            self.iso_edit.setText(p)

    def _load(self):
        p = self.iso_edit.text().strip()
        if not p:
            QMessageBox.warning(self, "提示", "请先选择 ISO 文件")
            return
        self.load_btn.setEnabled(False)
        self.loadRequested.emit(p)

    def set_detected(self, text, enabled=True):
        self.detect_label.setText(text)
        for b in self.step_btns.values():
            b.setEnabled(enabled)
        self.run_btn.setEnabled(enabled)
        self.load_btn.setEnabled(True)

    def set_state_text(self, text):
        self.state_label.setText(text)

    def set_busy(self, busy, total=None):
        """状态机驱动：忙时显示进度条（有 total 为确定模式），闲时隐藏。"""
        if busy:
            if total:
                self.progress_bar.setRange(0, total)
                self.progress_bar.setValue(0)
                self.progress_bar.setTextVisible(True)
            else:
                self.progress_bar.setRange(0, 0)      # 不确定模式（动画）
                self.progress_bar.setTextVisible(False)
            self.progress_bar.show()
        else:
            self.progress_bar.hide()

    def update_progress(self, done, total, pct, msg=""):
        """翻译/载入等确定进度：进度条 + 状态横幅实时更新。"""
        if total > 0:
            self.progress_bar.setRange(0, total)
            self.progress_bar.setValue(min(done, total))
            self.progress_bar.setTextVisible(True)
            self.progress_bar.setFormat("%v / %m  (%p%)")
            self.progress_bar.show()
        self.state_label.setText("当前状态：%s" % msg)

    def set_progress(self, msg):
        self.detect_label.setText(msg)


# ================= 提取结果页 =================
class ExtractPage(QWidget):
    glossaryRequested = Signal()
    confirmRequested = Signal()
    translateRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        self.stats_label = _label("尚未提取", bold=True)
        lay.addWidget(self.stats_label)
        self.notes_label = _label("")
        self.notes_label.setWordWrap(True)
        lay.addWidget(self.notes_label)

        g = QGroupBox("术语表预览")
        gl = QVBoxLayout(g)
        self.tbl = QTableWidget(0, 3)
        self.tbl.setHorizontalHeaderLabels(["日文", "中文", "来源"])
        self.tbl.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        gl.addWidget(self.tbl)
        lay.addWidget(g, 1)

        btns = QHBoxLayout()
        b1 = QPushButton("编辑术语表…")
        b1.clicked.connect(self.glossaryRequested.emit)
        b2 = QPushButton("确认术语表并开始翻译")
        b2.clicked.connect(self.translateRequested.emit)
        b3 = QPushButton("直接一键全流程…")
        b3.clicked.connect(self.confirmRequested.emit)
        btns.addWidget(b1)
        btns.addWidget(b2)
        btns.addWidget(b3)
        lay.addLayout(btns)

    def refresh(self, result, glossary):
        if not result:
            self.stats_label.setText("尚未提取")
            self.tbl.setRowCount(0)
            return
        s = result.stats()
        dup = s.get("duplicate_entries", 0)
        uniq = s.get("unique_entries", 0)
        dup_note = "（含重复 %d 条，翻译时将自动复用译文）" % dup if dup else ""
        self.stats_label.setText(
            "文本总条数：%d ｜ 唯一文本：%d ｜ 重复：%d%s\n"
            "总字符数：%d ｜ 文件数：%d\n%s" % (
                s["total_entries"], uniq, dup, dup_note,
                s["total_chars"], s["files"],
                " ｜ ".join("%s：%d" % (k, v) for k, v in s["by_category"].items())))
        self.notes_label.setText("\n".join(result.notes))
        rows = list(glossary.terms.items())[:30]
        self.tbl.setRowCount(len(rows))
        for i, (jp, v) in enumerate(rows):
            self.tbl.setItem(i, 0, QTableWidgetItem(jp))
            self.tbl.setItem(i, 1, QTableWidgetItem(v.get("zh", "")))
            self.tbl.setItem(i, 2, QTableWidgetItem(v.get("source", "")))


# ================= 术语管理页 =================
class GlossaryPage(QWidget):
    glossaryChanged = Signal()
    onlineRequested = Signal()
    aiRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索术语…")
        self.search.textChanged.connect(self._refresh)
        top.addWidget(self.search, 1)
        b_add = QPushButton("添加")
        b_add.clicked.connect(self._add)
        b_del = QPushButton("删除")
        b_del.clicked.connect(self._del)
        b_import = QPushButton("导入 CSV/JSON")
        b_import.clicked.connect(self._import)
        b_export = QPushButton("导出 CSV/JSON")
        b_export.clicked.connect(self._export)
        b_online = QPushButton("联网搜索更新")
        b_online.setToolTip("对检测到的人名/地名等自动检索维基百科/萌娘百科的约定俗成译名")
        b_online.clicked.connect(self.onlineRequested.emit)
        b_ai = QPushButton("AI 抽取术语")
        b_ai.setToolTip("把游戏文本交给翻译引擎，自动抽取专有名词并建议中文译名（借鉴 KeywordGacha 思路）")
        b_ai.clicked.connect(self.aiRequested.emit)
        for b in (b_add, b_del, b_import, b_export, b_online, b_ai):
            top.addWidget(b)
        lay.addLayout(top)

        self.tbl = QTableWidget(0, 4)
        self.tbl.setHorizontalHeaderLabels(["日文原文", "中文译名", "备注", "来源"])
        self.tbl.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.tbl.cellChanged.connect(self._cell_changed)
        lay.addWidget(self.tbl, 1)
        self.glossary = Glossary()
        self._loading = False

    def set_glossary(self, g):
        self.glossary = g
        self._refresh()

    def _refresh(self):
        if not self.glossary:
            return
        kw = self.search.text().strip()
        items = self.glossary.search(kw)
        self._loading = True
        self.tbl.setRowCount(len(items))
        for i, (jp, v) in enumerate(items):
            self.tbl.setItem(i, 0, QTableWidgetItem(jp))
            self.tbl.setItem(i, 1, QTableWidgetItem(v.get("zh", "")))
            self.tbl.setItem(i, 2, QTableWidgetItem(v.get("note", "")))
            self.tbl.setItem(i, 3, QTableWidgetItem(v.get("source", "")))
        self._loading = False

    def _cell_changed(self, row, col):
        if self._loading:
            return
        jp = self.tbl.item(row, 0).text() if self.tbl.item(row, 0) else ""
        if not jp:
            return
        zh = self.tbl.item(row, 1).text() if self.tbl.item(row, 1) else ""
        note = self.tbl.item(row, 2).text() if self.tbl.item(row, 2) else ""
        src = self.tbl.item(row, 3).text() if self.tbl.item(row, 3) else ""
        self.glossary.update(jp, zh or None, note or None, src or None)
        self.glossaryChanged.emit()

    def _add(self):
        jp, ok = self._ask("添加术语", "日文原文", "")
        if not ok or not jp:
            return
        zh, ok2 = self._ask("添加术语", "中文译名", "")
        if not ok2:
            zh = ""
        self.glossary.add(jp, zh, source="手动")
        self._refresh()
        self.glossaryChanged.emit()

    def _del(self):
        rows = sorted({i.row() for i in self.tbl.selectedIndexes()}, reverse=True)
        for r in rows:
            jp = self.tbl.item(r, 0).text() if self.tbl.item(r, 0) else ""
            if jp:
                self.glossary.remove(jp)
        self._refresh()
        self.glossaryChanged.emit()

    def _ask(self, title, label, default=""):
        from PySide6.QtWidgets import QInputDialog
        return QInputDialog.getText(self, title, label, text=default)

    def _import(self):
        p, _ = QFileDialog.getOpenFileName(self, "导入术语表", "", "术语表 (*.csv *.json)")
        if not p:
            return
        try:
            if p.endswith(".json"):
                self.glossary.load_json(p)
            else:
                n = self.glossary.import_csv(p)
                QMessageBox.information(self, "导入", "已导入 %d 条" % n)
            self._refresh()
            self.glossaryChanged.emit()
        except Exception as e:
            QMessageBox.warning(self, "导入失败", str(e))

    def _export(self):
        p, _ = QFileDialog.getSaveFileName(self, "导出术语表", "glossary.csv",
                                           "CSV (*.csv);;JSON (*.json)")
        if not p:
            return
        if p.endswith(".json"):
            self.glossary.save_json(p)
        else:
            self.glossary.export_csv(p)
        QMessageBox.information(self, "导出", "已导出：%s" % p)


# ================= 翻译设置页 =================
class SettingsPage(QWidget):
    testRequested = Signal(dict)
    saved = Signal(dict)
    savedAndTranslateRequested = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        g = QGroupBox("翻译引擎")
        form = QFormLayout(g)
        self.kind = QComboBox()
        self.kind.addItem("云端 API（OpenAI 兼容）", "openai")
        self.kind.addItem("云端 API（Anthropic 格式）", "anthropic")
        self.kind.addItem("本地 AI（Ollama / LM Studio / llama.cpp）", "local")
        form.addRow("引擎类型", self.kind)
        self.base_url = QLineEdit("https://api.openai.com/v1")
        form.addRow("API Base URL", self.base_url)
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.Password)
        form.addRow("API Key（本地可留空）", self.api_key)
        self.model = QLineEdit("gpt-4o-mini")
        form.addRow("模型名称", self.model)
        self.temperature = QDoubleSpinBox()
        self.temperature.setRange(0, 2)
        self.temperature.setSingleStep(0.1)
        self.temperature.setValue(0.3)
        form.addRow("温度", self.temperature)
        self.max_tokens = QSpinBox()
        self.max_tokens.setRange(256, 16384)
        self.max_tokens.setValue(2048)
        form.addRow("最大 Token", self.max_tokens)
        self.rpm = QSpinBox()
        self.rpm.setRange(1, 600)
        self.rpm.setValue(30)
        form.addRow("每分钟请求上限", self.rpm)
        self.concurrency = QSpinBox()
        self.concurrency.setRange(1, 16)
        self.concurrency.setValue(4)
        form.addRow("并发数", self.concurrency)
        lay.addWidget(g)

        hints = QLabel("本地引擎示例：Ollama → http://localhost:11434/v1（模型如 qwen2.5:14b）；"
                       "LM Studio → http://localhost:1234/v1")
        hints.setWordWrap(True)
        lay.addWidget(hints)

        btns = QHBoxLayout()
        b_test = QPushButton("测试连接")
        b_test.clicked.connect(self._test)
        b_save = QPushButton("保存设置")
        b_save.clicked.connect(self._save)
        b_go = QPushButton("保存并开始翻译")
        b_go.clicked.connect(self._save_and_go)
        btns.addWidget(b_test)
        btns.addWidget(b_save)
        btns.addWidget(b_go)
        lay.addLayout(btns)
        self.test_result = _label("")
        lay.addWidget(self.test_result)
        lay.addStretch(1)

    def load_cfg(self, cfg):
        kind = cfg.get("kind", "openai")
        idx = self.kind.findData(kind)
        if idx >= 0:
            self.kind.setCurrentIndex(idx)
        self.base_url.setText(cfg.get("base_url", ""))
        self.api_key.setText(cfg.get("api_key", ""))
        self.model.setText(cfg.get("model", ""))
        self.temperature.setValue(float(cfg.get("temperature", 0.3)))
        self.max_tokens.setValue(int(cfg.get("max_tokens", 2048)))
        self.rpm.setValue(int(cfg.get("rpm", 30)))
        self.concurrency.setValue(int(cfg.get("concurrency", 4)))

    def cfg(self):
        return {
            "kind": self.kind.currentData(),
            "base_url": self.base_url.text().strip(),
            "api_key": self.api_key.text().strip(),
            "model": self.model.text().strip(),
            "temperature": self.temperature.value(),
            "max_tokens": self.max_tokens.value(),
            "rpm": self.rpm.value(),
            "concurrency": self.concurrency.value(),
        }

    def _test(self):
        cfg = dict(self.cfg(), test_only=True)
        self.test_result.setText("测试中…")
        self.testRequested.emit(cfg)

    def _save(self):
        self.saved.emit(self.cfg())

    def _save_and_go(self):
        self.saved.emit(self.cfg())
        self.savedAndTranslateRequested.emit(self.cfg())


# ================= 文本校对页 =================
class ReviewPage(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        top = QHBoxLayout()
        self.filter = QComboBox()
        self.filter.addItems(["全部", "已翻译", "未翻译"])
        self.filter.currentTextChanged.connect(lambda _: self._refresh())
        self.cnt = _label("")
        top.addWidget(_label("筛选："))
        top.addWidget(self.filter)
        top.addWidget(self.cnt, 1)
        b_export = QPushButton("导出 JSON/CSV/XLIFF")
        b_export.clicked.connect(self._export)
        b_import = QPushButton("导入译文")
        b_import.clicked.connect(self._import)
        top.addWidget(b_export)
        top.addWidget(b_import)
        lay.addLayout(top)

        self.tbl = QTableWidget(0, 3)
        self.tbl.setHorizontalHeaderLabels(["原文", "译文（可编辑）", "类别"])
        self.tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tbl.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tbl.cellChanged.connect(self._changed)
        lay.addWidget(self.tbl, 1)
        self.result = None
        self._loading = False

    def set_result(self, result):
        self.result = result
        self._refresh()

    def _refresh(self):
        if not self.result:
            return
        mode = self.filter.currentText()
        entries = self.result.all_entries()
        if mode == "已翻译":
            entries = [e for e in entries if e.translation]
        elif mode == "未翻译":
            entries = [e for e in entries if not e.translation]
        entries = entries[:5000]
        self.cnt.setText("显示 %d 条（共 %d 条）" % (len(entries), len(self.result.all_entries())))
        self._loading = True
        self.tbl.setRowCount(len(entries))
        self._entries = entries
        for i, e in enumerate(entries):
            self.tbl.setItem(i, 0, QTableWidgetItem(e.original))
            self.tbl.setItem(i, 1, QTableWidgetItem(e.translation))
            self.tbl.setItem(i, 2, QTableWidgetItem(e.category))
        self._loading = False

    def _changed(self, row, col):
        if self._loading or not hasattr(self, "_entries"):
            return
        e = self._entries[row]
        if col == 1:
            item = self.tbl.item(row, 1)
            e.translation = item.text() if item else ""
            e.status = "translated" if e.translation else "untranslated"

    def _export(self):
        if not self.result:
            return
        p, _ = QFileDialog.getSaveFileName(self, "导出文本", "text_export.json",
                                           "JSON (*.json);;CSV (*.csv);;XLIFF (*.xlf)")
        if not p:
            return
        if p.endswith(".csv"):
            export_csv(self.result, p)
        elif p.endswith(".xlf"):
            export_xliff(self.result, p)
        else:
            export_json(self.result, p)
        QMessageBox.information(self, "导出", "已导出：%s" % p)

    def _import(self):
        if not self.result:
            return
        p, _ = QFileDialog.getOpenFileName(self, "导入译文", "", "译文 (*.csv *.xlf *.json)")
        if not p:
            return
        try:
            if p.endswith(".csv"):
                updates = import_csv(p)
            elif p.endswith(".xlf"):
                updates = import_xliff(p)
            else:
                from ..text.model import ExtractResult
                res = ExtractResult.load_json(p)
                updates = {e.id: e for e in res.all_entries()}
            by_id = {e.id: e for e in self.result.all_entries()}
            n = 0
            for eid, e in updates.items():
                if eid in by_id and e.translation:
                    by_id[eid].translation = e.translation
                    by_id[eid].status = "translated"
                    n += 1
            self._refresh()
            QMessageBox.information(self, "导入", "已更新 %d 条" % n)
        except Exception as ex:
            QMessageBox.warning(self, "导入失败", str(ex))


# ================= 日志 / 报告页 =================
class LogPage(QWidget):
    reportRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        lay.addWidget(_label("运行日志"), 0)
        lay.addWidget(self.log, 1)
        b = QPushButton("生成术语一致性报告")
        b.clicked.connect(self.reportRequested.emit)
        lay.addWidget(b)
        self.report = QPlainTextEdit()
        self.report.setReadOnly(True)
        lay.addWidget(_label("报告"), 0)
        lay.addWidget(self.report, 1)

    def append(self, msg):
        self.log.appendPlainText(msg)
        self.log.moveCursor(QTextCursor.End)

    def set_report(self, text):
        self.report.setPlainText(text)


# ================= 术语候选采纳弹窗 =================
class TermCandidateDialog(QDialog):
    """展示术语候选（联网搜索/AI 抽取结果），用户勾选后采纳。

    candidates: {日文: [(候选译名, 来源, 佐证片段), ...]}
    返回: {日文: 采纳的中文}（通过 get_result() 获取）
    """

    def __init__(self, candidates, title="术语候选", counts=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(800, 540)
        self._result = {}
        self._counts = counts or {}
        lay = QVBoxLayout(self)

        hint = QLabel("勾选需要采纳的行（每个日文只采纳一个候选）；不勾选则跳过。双击行可快速采纳。")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        self.tbl = QTableWidget(0, 6)
        self.tbl.setHorizontalHeaderLabels(["采纳", "日文原文", "候选译名", "出现次数", "来源", "佐证"])
        self.tbl.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.tbl.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.tbl.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.tbl.cellDoubleClicked.connect(self._dbl)
        self._rows = []          # (term, zh)
        self._term_rows = {}     # term -> [row...]
        self._populate(candidates)
        lay.addWidget(self.tbl, 1)

        btn = QDialogButtonBox()
        b_ok = btn.addButton("采纳所选", QDialogButtonBox.AcceptRole)
        b_cancel = btn.addButton("取消", QDialogButtonBox.RejectRole)
        b_ok.clicked.connect(self.accept)
        b_cancel.clicked.connect(self.reject)
        lay.addWidget(btn)

    def _populate(self, candidates):
        rows = []
        for term, cands in candidates.items():
            if not cands:
                # 未检索到候选：仍展示一行，用户可直接在“候选译名”列输入中文后勾选采纳
                r = len(rows)
                self.tbl.insertRow(r)
                chk = QTableWidgetItem()
                chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                chk.setCheckState(Qt.Unchecked)
                self.tbl.setItem(r, 0, chk)
                self.tbl.setItem(r, 1, QTableWidgetItem(term))
                it = QTableWidgetItem("（未检索到候选，可直接输入译名）")
                it.setForeground(Qt.gray)
                self.tbl.setItem(r, 2, it)
                cnt = self._counts.get(term)
                self.tbl.setItem(r, 3, QTableWidgetItem(str(cnt) if cnt else ""))
                self.tbl.setItem(r, 4, QTableWidgetItem("手动"))
                self.tbl.setItem(r, 5, QTableWidgetItem(""))
                self._rows.append((term, ""))
                self._term_rows.setdefault(term, []).append(r)
                continue
            first = True
            for zh, src, snip in cands[:4]:
                r = len(rows)
                self.tbl.insertRow(r)
                chk = QTableWidgetItem()
                chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
                chk.setCheckState(Qt.Unchecked if not first else Qt.Checked)
                first = False
                self.tbl.setItem(r, 0, chk)
                self.tbl.setItem(r, 1, QTableWidgetItem(term))
                self.tbl.setItem(r, 2, QTableWidgetItem(zh))
                cnt = self._counts.get(term)
                self.tbl.setItem(r, 3, QTableWidgetItem(str(cnt) if cnt else ""))
                self.tbl.setItem(r, 4, QTableWidgetItem(src))
                snip = (snip or "")[:120]
                self.tbl.setItem(r, 5, QTableWidgetItem(snip))
                self._rows.append((term, zh))
                self._term_rows.setdefault(term, []).append(r)
        # 让“候选译名”列可编辑（允许微调/手动输入）
        self.tbl.cellChanged.connect(self._cell_edited)

    def _cell_edited(self, row, col):
        if col == 2 and 0 <= row < len(self._rows):
            item = self.tbl.item(row, 2)
            if item:
                self._rows[row] = (self._rows[row][0], item.text().strip())

    def _dbl(self, row, col):
        if 0 <= row < len(self._rows):
            self.tbl.item(row, 0).setCheckState(Qt.Checked)

    def get_result(self):
        """按勾选返回 {term: zh}。同一 term 多行勾选时取第一个。"""
        picked = {}
        for i, (term, zh) in enumerate(self._rows):
            if self.tbl.item(i, 0) and self.tbl.item(i, 0).checkState() == Qt.Checked:
                if term not in picked:
                    picked[term] = zh
        return picked
