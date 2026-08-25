# -*- coding: utf-8 -*-
"""相似（部分相同）文本检测 + 翻译参考注入测试。

验证：
1. find_similar_groups 正确聚类“部分相同/大部分相同”文本；
2. 翻译时同相似组内已翻译条目的译文被注入 prompt 作参考（fuzzy-match 思路）；
3. SimilarIndex 保存/加载往返一致。

运行：python tests/test_similar.py
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
from ps2hantool.text.model import (ExtractResult, TextEntry, TextFile, CAT_DIALOG)
from ps2hantool.text.similar import find_similar_groups, SimilarIndex, similar_stats

PORT = 18089
PROMPTS = []   # 记录 mock 收到的每条 system prompt


class H(BaseHTTPRequestHandler):
    def do_POST(self):
        n = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(n))
        messages = body.get("messages", [])
        PROMPTS.append(messages[0]["content"] if messages else "")
        user = messages[-1]["content"] if messages else ""
        out_lines = []
        for ln in user.split("\n"):
            ln = ln.strip()
            if not ln:
                continue
            head, _, text = ln.partition("=")
            out_lines.append("%s=【译】%s" % (head, text[:12]))
        resp = json.dumps({"choices": [{"message": {"content": "\n".join(out_lines)}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(resp)))
        self.end_headers()
        self.wfile.write(resp)

    def log_message(self, *a):
        pass


def make_result():
    """构造：3 条共享前缀、仅差 1 字的相似对话（相似度≈0.93）+ 1 条无关文本。"""
    spec = [
        "明日は一緒に映画に行かない？",
        "明日は一緒に映画に行かないよ？",
        "明日は一緒に映画に行かないな？",
        "この本は面白いね。",
    ]
    res = ExtractResult()
    res.detected_game = {"name": "相似测试", "slpm": "SIM-001"}
    tf = TextFile(path="SIM.BIN")
    for i, text in enumerate(spec):
        e = TextEntry(file="SIM.BIN", offset=i * 20,
                      length=len(text.encode("cp932")),
                      category=CAT_DIALOG, original=text)
        tf.add(e)
    res.files["SIM.BIN"] = tf
    return res


def main():
    srv = HTTPServer(("127.0.0.1", PORT), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    root = Path(__file__).resolve().parents[1]
    tmp = root / "demo" / "similar_test_project"
    (tmp / "data").mkdir(parents=True, exist_ok=True)

    # 1) 纯检测
    entries = make_result().all_entries()
    groups = find_similar_groups(entries, threshold=0.85)
    ng, nc = similar_stats(groups)
    print("① 相似组: %d 组（覆盖 %d 条）" % (ng, nc))
    assert ng == 1 and nc == 3, "应只有 1 组相似（3 条），无关文本不混入"
    assert groups[0][0].original.startswith("明日は"), "组内应为共享前缀的句子"

    # 2) SimilarIndex 保存/加载
    idx = SimilarIndex(groups)
    path = tmp / "data" / "similar.json"
    idx.save(path)
    by_id = {e.id: e for e in entries}
    idx2 = SimilarIndex().load(path, by_id)
    assert len(idx2.groups) == 1 and len(idx2.groups[0]) == 3
    print("② SimilarIndex 保存/加载往返 ✓")

    # 3) 翻译参考注入：先翻译全部（第一条先译），再模拟第二次翻译时参考生效
    pl = Pipeline(Project(tmp))
    pl.result = make_result()
    pl.prepare_glossary(auto_seed=False)
    cfg = {"kind": "openai", "base_url": "http://127.0.0.1:%d/v1" % PORT,
           "api_key": "", "model": "mock", "rpm": 1000, "concurrency": 8}
    r1 = pl.translate(cfg, progress_cb=lambda d, t: None)
    print("③ 首次翻译: 唯一 %d, 参考 %d" % (r1["translated"], r1.get("ref_used", 0)))
    assert r1["translated"] == 4
    # 首次翻译：4 条都未译，参考数应为 0（同组内无已译成员）
    assert r1.get("ref_used", 0) == 0

    # 再造一个新工程：翻译前先注入 1 条已译参考，再翻译相似文本
    pl2 = Pipeline(Project(tmp))
    pl2.result = make_result()
    pl2.prepare_glossary(auto_seed=False)
    # 模拟断点续传：预译第一条
    all_e = pl2.result.all_entries()
    all_e[0].translation = "明天一起去看电影吧？"
    all_e[0].status = "translated"
    pl2.project.translated_path().write_text(
        json.dumps(pl2._result_payload(), ensure_ascii=False), "utf-8")
    r2 = pl2.translate(cfg, progress_cb=lambda d, t: None)
    print("④ 续传翻译: 唯一 %d, 参考 %d" % (r2["translated"], r2.get("ref_used", 0)))
    assert r2["translated"] == 3
    assert r2.get("ref_used", 0) >= 1, "相似文本翻译时应获得参考译文"
    # mock 收到的 prompt 应包含参考译文
    any_ref = any("相似文本参考译文" in p and "明天一起去看电影吧" in p for p in PROMPTS)
    assert any_ref, "system prompt 应注入相似文本参考译文"
    print("⑤ 参考注入验证 ✓（prompt 含『相似文本参考译文』与已有译文）")

    # 4) 全量数据性能与效果（TM3 demo）
    from ps2hantool.text.model import ExtractResult as ER
    demo = ER.load_json(str(root / "demo" / "tm3_project" / "data" / "extracted.json"))
    import time
    t0 = time.time()
    g_all = find_similar_groups(demo.all_entries(), threshold=0.85)
    dt = time.time() - t0
    ng_all, nc_all = similar_stats(g_all)
    print("⑥ TM3 全量: %d 组（覆盖 %d 条），耗时 %.1fs" % (ng_all, nc_all, dt))
    assert dt < 60, "相似检测不应过慢"

    try:
        shutil.rmtree(tmp, ignore_errors=True)
    except Exception:
        pass
    srv.shutdown()
    print("\n✅ 相似文本检测与参考注入测试全部通过")


if __name__ == "__main__":
    main()
