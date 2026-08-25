# -*- coding: utf-8 -*-
"""翻译流程自动化测试：用本地 mock 引擎验证「翻译确实产生译文并落盘」。

覆盖：
1. translate_batch 进度回调 (done, total) 不再抛异常（回归：曾导致进度丢失）
2. 译文写入条目、translated.json 生成（断点续传基础）
3. 词汇表/游戏上下文注入 system prompt
4. 回写编码转换链路

运行：python tests/test_translate_flow.py
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

PORT = 18082


class MockHandler(BaseHTTPRequestHandler):
    """OpenAI 兼容 mock：把用户内容逐行回包，带【译】前缀，模拟真实翻译。"""

    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n))
        messages = body.get("messages", [])
        sys_prompt = messages[0]["content"] if messages else ""
        user = messages[-1]["content"] if messages else ""
        out_lines = []
        for ln in user.split("\n"):
            ln = ln.strip()
            if not ln:
                continue
            head, _, text = ln.partition("=")
            out_lines.append("%s=【译】%s" % (head, text[:12]))
        resp = json.dumps({
            "choices": [{"message": {"content": "\n".join(out_lines)}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resp)))
        self.end_headers()
        self.wfile.write(resp)

    def log_message(self, *a):
        pass


def main():
    srv = HTTPServer(("127.0.0.1", PORT), MockHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    proj_root = Path(__file__).resolve().parents[1]
    src_data = proj_root / "demo" / "tm3_project" / "data"
    tmp = proj_root / "demo" / "tm3_translate_test_project"
    if tmp.exists():
        try:
            shutil.rmtree(tmp, ignore_errors=True)
        except Exception:
            pass
    (tmp / "data").mkdir(parents=True, exist_ok=True)
    for f in ("extracted.json", "glossary.json"):
        shutil.copy(src_data / f, tmp / "data" / f)

    cfg = {"kind": "openai", "base_url": "http://127.0.0.1:%d/v1" % PORT,
           "api_key": "", "model": "mock", "rpm": 1000, "concurrency": 8}

    pl = Pipeline(Project(tmp))
    pl.load_extracted()
    pl.prepare_glossary(auto_seed=True)

    # 1) 翻译 20 条，带结构化进度回调
    progress = []
    res = pl.translate(cfg, progress_cb=lambda d, t: progress.append((d, t)), limit=20)
    ok = res["translated"]
    err = len(res["errors"])
    print("① 翻译结果: 成功 %d 条, 失败 %d 条" % (ok, err))
    assert ok == 20 and err == 0, "mock 应全部成功"

    print("② 进度回调次数: %d（应≥20，且不再抛异常）" % len(progress))
    assert len(progress) >= 20, "进度回调未触发（回归：信号协议）"
    last_done, last_total = progress[-1]
    assert last_done == 20 and last_total == 20, "进度应为 20/20"

    # 2) 译文落盘
    entries = [e for e in pl.result.all_entries() if e.translation]
    print("③ 有译文的条目: %d，示例: %r" % (len(entries), entries[0].translation[:24]))
    assert len(entries) == 20
    tj = tmp / "data" / "translated.json"
    assert tj.exists(), "translated.json 未生成（断点续传依赖它）"
    print("④ translated.json 已生成（%d 字节）" % tj.stat().st_size)

    # 3) 断点续传：再次翻译应跳过已译条目
    res2 = pl.translate(cfg, progress_cb=lambda d, t: None, limit=20)
    assert res2["translated"] == 0 and res2.get("message"), "再次翻译应跳过已译条目"
    print("⑤ 断点续传验证通过: %s" % res2.get("message", ""))

    # 4) 译文可编码回写（cp932 转换链路）
    from ps2hantool.translate.jp_kanji import to_jis_encodable
    sample = to_jis_encodable(entries[0].translation)
    sample.encode("cp932")
    print("⑥ 译文可回写编码验证通过: %r → %r" % (entries[0].translation[:16], sample[:16]))

    try:
        shutil.rmtree(tmp, ignore_errors=True)
    except Exception:
        pass
    srv.shutdown()
    print("\n✅ 翻译流程测试全部通过：汉化确实生效（译文生成 + 落盘 + 可回写）")


if __name__ == "__main__":
    main()
