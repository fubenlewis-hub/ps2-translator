# -*- coding: utf-8 -*-
"""去重复用翻译测试：相同原文 + 相同类型的条目只调一次翻译 API，译文广播复用。

构造 10 条文本：
  - "こんにちは"(对话) ×3        → 1 次调用
  - "はい"(菜单) ×2              → 1 次调用
  - "こんにちは"(菜单) ×1        → 同原文但不同类型 → 单独 1 次调用
  - "さようなら"(对话)、"おはよう"(对话) ×2 → 各 1 次
预期：10 条 → 6 组唯一 → API 调用 6 次；reused=4；同组条目译文一致。

运行：python tests/test_dedup.py
"""
import json
import shutil
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ps2hantool.core import Pipeline
from ps2hantool.project import Project
from ps2hantool.text.model import (ExtractResult, TextEntry, TextFile,
                                   CAT_DIALOG, CAT_MENU)

PORT = 18088
CALLS = []          # 记录 mock 收到的每条原文请求


class H(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n))
        user = body["messages"][-1]["content"]
        out_lines = []
        for ln in user.split("\n"):
            ln = ln.strip()
            if not ln:
                continue
            head, _, text = ln.partition("=")
            CALLS.append(text)                       # 记录被翻译的原文
            out_lines.append("%s=【译】%s" % (head, text[:10]))
        resp = json.dumps({"choices": [{"message": {"content": "\n".join(out_lines)}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resp)))
        self.end_headers()
        self.wfile.write(resp)

    def log_message(self, *a):
        pass


def make_result():
    """构造含重复的提取结果（10 条 / 6 组唯一）。"""
    spec = [
        ("こんにちは", CAT_DIALOG), ("こんにちは", CAT_DIALOG), ("こんにちは", CAT_DIALOG),
        ("はい", CAT_MENU), ("はい", CAT_MENU),
        ("こんにちは", CAT_MENU),
        ("さようなら", CAT_DIALOG),
        ("おはよう", CAT_DIALOG), ("おはよう", CAT_DIALOG),
        ("ただいま", CAT_DIALOG),
    ]
    res = ExtractResult()
    res.detected_game = {"name": "测试游戏", "slpm": "TEST-001"}
    tf = TextFile(path="TEST.BIN")
    for i, (text, cat) in enumerate(spec):
        e = TextEntry(file="TEST.BIN", offset=i * 10, length=len(text.encode("cp932")),
                      category=cat, original=text)
        tf.add(e)
    res.files["TEST.BIN"] = tf
    return res


def main():
    srv = HTTPServer(("127.0.0.1", PORT), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    root = Path(__file__).resolve().parents[1]
    tmp = root / "demo" / "dedup_test_project"
    (tmp / "data").mkdir(parents=True, exist_ok=True)

    pl = Pipeline(Project(tmp))
    pl.result = make_result()
    pl.prepare_glossary(auto_seed=False)
    cfg = {"kind": "openai", "base_url": "http://127.0.0.1:%d/v1" % PORT,
           "api_key": "", "model": "mock", "rpm": 1000, "concurrency": 8}

    progress = []
    res = pl.translate(cfg, progress_cb=lambda d, t: progress.append((d, t)))
    print("① 翻译结果: 唯一 %d 条, 复用 %d 条, 失败 %d" % (
        res["translated"], res["reused"], len(res["errors"])))
    assert res["translated"] == 6, "应只翻译 6 组唯一文本"
    assert res["reused"] == 4, "应复用 4 条重复文本"

    print("② mock 实际收到请求次数: %d（应=6，重复文本不再翻译第二遍）" % len(CALLS))
    assert len(CALLS) == 6, "重复文本被重复翻译了！"

    print("③ 进度 total = 唯一数:", progress[-1] if progress else None)
    assert progress and progress[-1][1] == 6

    # 验证同组条目译文一致（复用正确）
    entries = pl.result.all_entries()
    by_text = {}
    for e in entries:
        by_text.setdefault((e.original, e.category), []).append(e)
    for (text, cat), members in by_text.items():
        zh_set = {m.translation for m in members}
        assert len(zh_set) == 1, "同组条目译文应一致: %r" % (text,)
    print("④ 同组条目译文一致 ✓（%d 组全部复用正确）" % len(by_text))
    assert all(e.status == "translated" for e in entries), "所有条目应为已翻译状态"

    # 验证 translated.json 落盘 + 断点续传跳过
    tj = tmp / "data" / "translated.json"
    assert tj.exists()
    res2 = pl.translate(cfg, progress_cb=lambda d, t: None)
    assert res2.get("message") == "没有待翻译条目"
    print("⑤ 译文落盘 + 断点续传 ✓")

    try:
        shutil.rmtree(tmp, ignore_errors=True)
    except Exception:
        pass
    srv.shutdown()
    print("\n✅ 去重复用测试全部通过：重复文本只翻译一次，译文自动复用")


if __name__ == "__main__":
    main()
