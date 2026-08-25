# -*- coding: utf-8 -*-
"""GUI 状态机全流程集成测试（offscreen + mock 翻译服务器）。"""
import sys
import time
import threading
import json
import traceback
sys.path.insert(0, r"E:/桌面/心跳回忆/ps2-translator")

from http.server import BaseHTTPRequestHandler, HTTPServer
from PySide6.QtWidgets import QApplication
from ps2hantool.ui.main_window import MainWindow
from ps2hantool.state import AppState

LOG = r"E:/桌面/心跳回忆/ps2-translator/flowtest.txt"


def log(msg):
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(str(msg) + "\n")


class H(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n))
        user = body["messages"][-1]["content"]
        out = "（模拟译文）" + user[:12]
        resp = json.dumps({"choices": [{"message": {"content": out}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resp)))
        self.end_headers()
        self.wfile.write(resp)

    def log_message(self, *a):
        pass


def main():
    srv = HTTPServer(("127.0.0.1", 18082), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    app = QApplication([])
    w = MainWindow()
    ISO = r"E:/桌面/心跳回忆/Tokimeki Memorial 3 [Japan][SLPM-65080]心跳回忆3/Tokimeki Memorial 3 [NTSC-J] [SLPM-65080].iso"

    def pump_until(cond, timeout=300):
        t0 = time.time()
        while not cond() and time.time() - t0 < timeout:
            app.processEvents()
            time.sleep(0.05)
        return cond()

    w._load_iso(ISO)
    log("载入完成? %s state=%s" % (pump_until(lambda: w.state == AppState.LOADED), w.state.name))
    log("识别: %s" % ("心跳回忆3" in w.home.detect_label.text()))

    w._step("extract")
    log("提取完成? %s state=%s" % (pump_until(lambda: w.state == AppState.EXTRACTED), w.state.name))
    log("条数: %d" % w.pipeline.result.stats()["total_entries"])

    w._step("glossary")
    log("术语页可进入: %s" % (w.stack.currentIndex() == 2))

    cfg = {"kind": "openai", "base_url": "http://127.0.0.1:18082/v1", "api_key": "",
           "model": "mock", "temperature": 0.3, "max_tokens": 1024,
           "rpm": 5000, "concurrency": 8}
    # 限制测试规模：只翻译前 60 条，避免限流导致测试时间过长
    entries = w.pipeline.result.all_entries()
    for e in entries:
        e.translation = ""
        e.status = "untranslated"
    keep = set(e.id for e in entries[:60])
    for e in entries[60:]:
        e.translation = "（跳过）"
        e.status = "skipped"
    w._run_translate(cfg)
    ok = pump_until(lambda: w.state == AppState.TRANSLATED, timeout=180)
    tr = sum(1 for e in w.pipeline.result.all_entries()
             if e.translation and e.status == "translated")
    log("翻译完成? %s state=%s 已译=%d" % (ok, w.state.name, tr))
    assert ok and tr == 60
    log("状态栏: %s" % w.statusBar().currentMessage()[:36])
    log("横幅: %s" % w.home.state_label.text()[:32])
    srv.shutdown()
    log("DONE-OK")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("EXC:\n" + traceback.format_exc())
        sys.exit(1)
