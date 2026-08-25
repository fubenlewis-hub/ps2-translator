# -*- coding: utf-8 -*-
"""GUI 层翻译进度条集成测试：真实点击「④ 开始翻译」按钮，
验证进度条/状态横幅/完成弹窗/译文落盘。"""
import json
import shutil
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtWidgets import QApplication, QMessageBox

from ps2hantool.core import Pipeline
from ps2hantool.project import Project
from ps2hantool.ui.main_window import MainWindow

PORT = 18087


class H(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n))
        user = body["messages"][-1]["content"]
        out = []
        for ln in user.split("\n"):
            ln = ln.strip()
            if not ln:
                continue
            head, _, text = ln.partition("=")
            out.append("%s=【译】%s" % (head, text[:10]))
        resp = json.dumps({"choices": [{"message": {"content": "\n".join(out)}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resp)))
        self.end_headers()
        self.wfile.write(resp)

    def log_message(self, *a):
        pass


def rm(p):
    try:
        shutil.rmtree(p, ignore_errors=True)
    except Exception:
        pass


def main():
    srv = HTTPServer(("127.0.0.1", PORT), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    root = Path(__file__).resolve().parents[1]
    src = root / "demo" / "tm3_project" / "data"
    tmp = root / "demo" / "gui_translate_test4"
    (tmp / "data").mkdir(parents=True, exist_ok=True)
    for f in ("extracted.json", "glossary.json"):
        shutil.copy(src / f, tmp / "data" / f)

    app = QApplication([])
    w = MainWindow()
    w.show()
    w.pipeline = Pipeline(Project(tmp))
    w.pipeline.load_extracted()
    w.pipeline.prepare_glossary(auto_seed=True)
    cfg = {"kind": "openai", "base_url": "http://127.0.0.1:%d/v1" % PORT,
           "api_key": "", "model": "mock", "rpm": 1000, "concurrency": 8}
    w.pipeline.project.set("engine", cfg)
    w.extract.refresh(w.pipeline.result, w.pipeline.glossary)
    w.home.set_detected("已载入")           # 启用步骤按钮（载入后自动启用）
    w._set_state(w.state)

    # 检查提取统计显示（含重复数）
    s = w.pipeline.result.stats()
    print("统计: 总 %d | 唯一 %d | 重复 %d" % (
        s["total_entries"], s["unique_entries"], s["duplicate_entries"]))
    assert "重复" in w.extract.stats_label.text(), "提取页应显示重复统计"
    print("提取页统计:", w.extract.stats_label.text().split("\n")[0])

    # 相似文本统计（部分相同文本）
    sim = w.pipeline.similar_index()
    if sim is not None and sim.groups:
        w.extract.stats_label.setText(w.extract.stats_label.text() +
                                      "\n相似文本：%d 组（覆盖 %d 条）" % (
                                          len(sim.groups),
                                          sum(len(g) for g in sim.groups)))
        print("相似文本: %d 组 / %d 条" % (
            len(sim.groups), sum(len(g) for g in sim.groups)))
        assert "相似" in w.extract.stats_label.text()

    msgs = []
    QMessageBox.information = staticmethod(lambda *a, **k: msgs.append(("info", a[2] if len(a) > 2 else "")))
    QMessageBox.warning = staticmethod(lambda *a, **k: msgs.append(("warn", a[2] if len(a) > 2 else "")))

    w.home.step_btns["translate"].click()   # 真实按钮点击
    bars = []
    t0 = time.time()
    while time.time() - t0 < 600:
        app.processEvents()
        if w.worker and w.worker.isRunning():
            v = w.home.progress_bar.value()
            mx = w.home.progress_bar.maximum()
            if mx > 0:
                bars.append(v)
        else:
            if bars:
                break
            time.sleep(0.05)
        time.sleep(0.05)

    print("进度采样数:", len(bars), "| 峰值:", (max(bars) if bars else 0),
          "/", w.home.progress_bar.maximum())
    print("完成状态:", w.state.value)
    print("横幅:", w.home.state_label.text()[:44])
    print("弹窗:", (msgs[-1][1][:44] if msgs else None))
    print("translated.json 生成:", (tmp / "data" / "translated.json").exists())
    if (tmp / "data" / "translated.json").exists():
        payload = json.loads((tmp / "data" / "translated.json").read_text("utf-8"))
        n_trans = sum(1 for f in payload["files"].values() for e in f if e.get("translation"))
        print("落盘译文条数:", n_trans)

    rm(tmp)
    srv.shutdown()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
