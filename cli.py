# -*- coding: utf-8 -*-
"""
PS2 汉化工具 CLI 入口。

用法示例：
  python cli.py load <iso> <project_dir>          # 载入 ISO 并识别
  python cli.py extract <project_dir>              # 提取文本
  python cli.py stats <project_dir>                # 查看提取统计
  python cli.py export <project_dir> <out.json>    # 导出文本（json/csv/xliff）
  python cli.py import <project_dir> <in.csv>      # 导入译文
  python cli.py translate <project_dir> --cfg cfg.json --limit 50
  python cli.py unify <project_dir>
  python cli.py writeback <project_dir>
  python cli.py font <project_dir> [--size 16]
  python cli.py rebuild <project_dir>
  python cli.py run <iso> <project_dir> [--translate cfg.json] [--limit N]
"""
import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ps2hantool.project import Project
from ps2hantool.core import Pipeline
from ps2hantool.text.model import export_json, export_csv, export_xliff, import_csv, import_xliff

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


def _pipeline(project_dir):
    return Pipeline(Project(Path(project_dir)))


def _progress(msg):
    if isinstance(msg, (tuple, list)):
        msg = " ".join(str(x) for x in msg)
    print("  · %s" % msg)


def cmd_load(args):
    pl = _pipeline(args.project)
    info = pl.load_iso(args.iso, _progress)
    print("识别游戏: %s" % info.get("name"))
    print("插件: %s" % pl.plugin.display_name)


def cmd_extract(args):
    pl = _pipeline(args.project)
    pl.load_extracted()
    stats = pl.extract(_progress)
    print(json.dumps(stats, ensure_ascii=False, indent=2))


def cmd_stats(args):
    pl = _pipeline(args.project)
    res = pl.load_extracted()
    if not res:
        print("未找到提取结果，请先运行 extract")
        return
    stats = res.stats()
    print("游戏: %s" % (res.detected_game or {}).get("name", "未知"))
    print("文本总条数: %d" % stats["total_entries"])
    print("总字符数: %d" % stats["total_chars"])
    for cat, n in stats["by_category"].items():
        print("  %s: %d" % (cat, n))
    for note in res.notes:
        print("  [注] %s" % note)


def cmd_export(args):
    pl = _pipeline(args.project)
    res = pl.load_extracted()
    if not res:
        print("未找到提取结果")
        return
    p = args.out
    if p.endswith(".csv"):
        export_csv(res, p)
    elif p.endswith(".xliff") or p.endswith(".xlf"):
        export_xliff(res, p)
    else:
        export_json(res, p)
    print("已导出: %s" % p)


def cmd_import(args):
    pl = _pipeline(args.project)
    res = pl.load_extracted()
    if not res:
        print("未找到提取结果")
        return
    if args.inp.endswith(".csv"):
        updates = import_csv(args.inp)
    else:
        updates = import_xliff(args.inp)
    by_id = {e.id: e for e in res.all_entries()}
    n = 0
    for eid, e in updates.items():
        tgt = by_id.get(eid)
        if tgt and e.translation:
            tgt.translation = e.translation
            tgt.status = "translated"
            n += 1
    pl.project.translated_path().write_text(
        json.dumps(pl._result_payload(), ensure_ascii=False), "utf-8")
    print("已导入 %d 条译文" % n)


def cmd_translate(args):
    pl = _pipeline(args.project)
    pl.load_extracted()
    pl.prepare_glossary()
    cfg = json.loads(Path(args.cfg).read_text("utf-8")) if args.cfg else {
        "kind": args.kind, "base_url": args.base_url, "api_key": args.api_key,
        "model": args.model}
    if cfg.get("test_only"):
        ok, msg = pl.translate(cfg, _progress, test_only=True)
        print("连接测试:", msg)
        return
    r = pl.translate(cfg, _progress, limit=args.limit)
    print("翻译结果:", r.get("translated"), "成功 /", len(r.get("errors", {})), "失败")


def cmd_unify(args):
    pl = _pipeline(args.project)
    pl.load_extracted()
    pl.prepare_glossary()
    w = pl.unify_terms(auto_fix=not args.preview)
    print("术语统一完成，警告 %d 条" % len(w))
    if args.preview:
        for eid, old, new in w[:10]:
            print("  %s:\n    %s\n  → %s" % (eid, old, new))


def cmd_writeback(args):
    pl = _pipeline(args.project)
    pl.load_extracted()
    r = pl.writeback(_progress)
    print("回写报告:", json.dumps(r, ensure_ascii=False, indent=2))
    if r.get("too_long"):
        print("超长条目 %d 条（未回写，请人工处理）" % len(r["too_long"]))


def cmd_font(args):
    pl = _pipeline(args.project)
    bf, out = pl.build_font(size=args.size)
    print("字库: %s（%d 字，%dpx）" % (out, len(bf.chars), args.size))
    print(pl.inject_font(bf))


def cmd_rebuild(args):
    pl = _pipeline(args.project)
    out = pl.rebuild(lambda i, t, rel: _progress("打包 %d/%d %s" % (i, t, rel)))
    print("已生成: %s" % out)


def cmd_run(args):
    pl = _pipeline(args.project)
    pl.load_iso(args.iso, _progress)
    pl.extract(_progress)
    pl.prepare_glossary()
    if args.translate:
        cfg = json.loads(Path(args.translate).read_text("utf-8"))
        pl.translate(cfg, _progress, limit=args.limit)
        pl.unify_terms()
        pl.writeback(_progress)
    pl.rebuild(_progress)
    print("全流程完成。输出: %s" % pl.project.output_dir)


def main():
    ap = argparse.ArgumentParser(description="PS2 游戏一键汉化工具 CLI")
    sub = ap.add_subparsers(dest="cmd")
    def add(name, fn, *pos):
        p = sub.add_parser(name)
        for a, kw in pos:
            p.add_argument(a, **kw)
        p.set_defaults(fn=fn)
        return p
    add("load", cmd_load, ("iso", {}), ("project", {}))
    add("extract", cmd_extract, ("project", {}))
    add("stats", cmd_stats, ("project", {}))
    add("export", cmd_export, ("project", {}), ("out", {}))
    add("import", cmd_import, ("project", {}), ("inp", {}))
    p = add("translate", cmd_translate, ("project", {}))
    p.add_argument("--cfg"); p.add_argument("--kind", default="openai")
    p.add_argument("--base-url"); p.add_argument("--api-key"); p.add_argument("--model")
    p.add_argument("--limit", type=int)
    p.add_argument("--test-only", action="store_true", dest="test_only")
    p = add("unify", cmd_unify, ("project", {}))
    p.add_argument("--preview", action="store_true")
    add("writeback", cmd_writeback, ("project", {}))
    p = add("font", cmd_font, ("project", {}))
    p.add_argument("--size", type=int, default=16)
    add("rebuild", cmd_rebuild, ("project", {}))
    p = add("run", cmd_run, ("iso", {}), ("project", {}))
    p.add_argument("--translate"); p.add_argument("--limit", type=int)
    args = ap.parse_args()
    if not getattr(args, "fn", None):
        ap.print_help()
        return
    args.fn(args)


if __name__ == "__main__":
    main()
