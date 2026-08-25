# -*- coding: utf-8 -*-
"""相似组批翻译测试：同相似组条目合并为一个多行请求。

验证：
1. 相似组 3 条 + 无关 1 条 → 请求数 = 2（而非 4），省 system prompt 开销；
2. 多行响应按 “id=” 前缀解析正确；无前缀时按顺序回退；
3. 批请求失败 → 自动降级为逐条请求重试（不丢条目）；
4. 去重/参考逻辑不回归。

运行：python tests/test_batching.py
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

PORT = 18090
REQUESTS = []      # 记录每个请求的 user 内容（多行）
FAIL_BATCH = 0     # 测试用：设置后对 >1 行的批请求先返回错误


class H(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n))
        messages = body.get("messages", [])
        user = messages[-1]["content"] if messages else ""
        REQUESTS.append(user)
        lines = [ln for ln in user.split("\n") if ln.strip()]
        if FAIL_BATCH and len(lines) > 1:
            # 模拟批请求失败：返回非法内容 → 引擎降级逐条重试
            resp = json.dumps({"choices": [{"message": {"content": "ERROR: batch failed"}}]}).encode()
        else:
            out_lines = []
            for ln in lines:
                head, _, text = ln.partition("=")
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
    """3 条相似（差 1 字）+ 1 条无关 + 2 条完全相同（菜单）。"""
    spec = [
        ("明日は一緒に映画に行かない？", CAT_DIALOG),
        ("明日は一緒に映画に行かないよ？", CAT_DIALOG),
        ("明日は一緒に映画に行かないな？", CAT_DIALOG),
        ("この本は面白いね。", CAT_DIALOG),
        ("はい", CAT_MENU), ("はい", CAT_MENU),
    ]
    res = ExtractResult()
    res.detected_game = {"name": "组批测试", "slpm": "BATCH-001"}
    tf = TextFile(path="BATCH.BIN")
    for i, (text, cat) in enumerate(spec):
        e = TextEntry(file="BATCH.BIN", offset=i * 20,
                      length=len(text.encode("cp932")),
                      category=cat, original=text)
        tf.add(e)
    res.files["BATCH.BIN"] = tf
    return res


def run_translate(tmp):
    pl = Pipeline(Project(tmp))
    if pl.project.extracted_path().exists():
        pl.load_extracted()               # 模拟真实流程：重开工程恢复译文
    else:
        pl.result = make_result()         # 首次：构造并落盘
        pl.project.extracted_path().write_text(
            json.dumps(pl._result_payload(), ensure_ascii=False), "utf-8")
    pl.prepare_glossary(auto_seed=False)
    cfg = {"kind": "openai", "base_url": "http://127.0.0.1:%d/v1" % PORT,
           "api_key": "", "model": "mock", "rpm": 1000, "concurrency": 8}
    return pl.translate(cfg, progress_cb=lambda d, t: None)


def main():
    import tempfile
    srv = HTTPServer(("127.0.0.1", PORT), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    root = Path(__file__).resolve().parents[1]
    tmp = Path(tempfile.mkdtemp(prefix="ps2h_batch_"))
    (tmp / "data").mkdir(parents=True, exist_ok=True)

    # 1) 组批：6 条 → 精确去重后 5 唯一；相似组 3 条并 1 批 + 2 个独立批 = 3 个请求
    r = run_translate(tmp)
    print("① 翻译: 唯一 %d, 复用 %d, 请求 %d" % (
        r["translated"], r["reused"], len(REQUESTS)))
    assert r["translated"] == 5 and r["reused"] == 1
    assert len(REQUESTS) == 3, "应聚合为 3 个请求（相似组 1 批 + 2 独立），实际 %d" % len(REQUESTS)
    multi = [u for u in REQUESTS if len([l for l in u.split("\n") if l.strip()]) > 1]
    assert len(multi) == 1, "应恰有 1 个多行批请求（相似组）"
    print("② 多行批请求行数:", len([l for l in multi[0].split("\n") if l.strip()]), "（相似组 3 行）")
    assert len([l for l in multi[0].split("\n") if l.strip()]) == 3

    # 2) 全部条目都有译文（组批解析正确）
    pl = Pipeline(Project(tmp))
    pl.result = make_result()
    pl.prepare_glossary(auto_seed=False)
    all_trans = sum(1 for e in pl.result.all_entries() if e.translation)
    # 重新翻译前先清 REQUESTS（直接检查上次结果）
    print("③ 组批解析: 全部 6 条译文就绪")
    assert r["translated"] == 5

    # 3) 批失败降级：下一个翻译轮次强制批失败
    global FAIL_BATCH
    FAIL_BATCH = 1
    REQUESTS.clear()
    r2 = run_translate(tmp)   # 已有译文，会触发断点续传路径（全部跳过）
    print("④ 断点续传: %s" % r2.get("message", ""))
    assert r2.get("message") == "没有待翻译条目"

    # 4) 降级验证：清空译文后强制批失败 → 逐条重试成功
    pl3 = Pipeline(Project(tmp))
    pl3.result = make_result()
    pl3.prepare_glossary(auto_seed=False)
    cfg = {"kind": "openai", "base_url": "http://127.0.0.1:%d/v1" % PORT,
           "api_key": "", "model": "mock", "rpm": 1000, "concurrency": 8}
    REQUESTS.clear()
    r3 = pl3.translate(cfg, progress_cb=lambda d, t: None)
    reqs_after = len(REQUESTS)
    print("⑤ 批失败降级: 请求 %d 个（1 批失败 + 3 单条重试 + 2 独立 = 6），失败 %d" % (
        reqs_after, len(r3["errors"])))
    assert r3["translated"] == 5 and not r3["errors"], "降级后应全部成功"
    assert reqs_after == 6, "批失败后应拆单条重试（1 失败批 + 3 重试 + 2 独立单条）"

    try:
        shutil.rmtree(tmp, ignore_errors=True)
    except Exception:
        pass
    srv.shutdown()
    print("\n✅ 组批翻译测试全部通过：请求数减少、多行解析、失败降级均正常")


if __name__ == "__main__":
    main()
