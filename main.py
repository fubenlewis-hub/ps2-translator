# -*- coding: utf-8 -*-
"""PS2 游戏一键汉化工具 —— 入口。

用法：
  python main.py                  # 启动图形界面
  python main.py <project_dir>    # 打开已有工程
  PS2汉化工具.exe --selftest      # 无头自检（写入 selftest.txt 后退出）
"""
import logging
import sys
import threading
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ps2hantool import get_app_root


def init_crash_logging():
    """崩溃防护（exe 为 windowed 模式，异常默认无痕消失）：
    1) windowed 下 stdout/stderr 为 None → 重定向到 app.log（防 print 崩、留 traceback 现场）；
    2) sys/threading excepthook → 写 crash.log；
    3) faulthandler → 捕获 C 层致命错误（segfault/abort 前的 Python 回溯）；
    4) Qt 消息 handler → Qt fatal 触发 abort 前留下证据。
    """
    root = get_app_root()
    try:
        crash_fp = open(root / "crash.log", "a", encoding="utf-8")
        import faulthandler
        faulthandler.enable(crash_fp)
    except Exception:
        crash_fp = None

    def _write(tp, val, tb):
        try:
            if crash_fp:
                crash_fp.write("".join(traceback.format_exception(tp, val, tb)))
                crash_fp.flush()
        except Exception:
            pass

    sys.excepthook = _write

    def _thread_hook(args):
        try:
            if crash_fp:
                crash_fp.write("".join(traceback.format_exception(
                    args.exc_type, args.exc_value, args.exc_traceback)))
                crash_fp.flush()
        except Exception:
            pass

    threading.excepthook = _thread_hook

    # windowed 模式：stdout/stderr 是 None，重定向到日志文件
    try:
        if sys.stdout is None:
            sys.stdout = open(root / "app.log", "a", encoding="utf-8", buffering=1)
        if sys.stderr is None:
            sys.stderr = sys.stdout
    except Exception:
        pass

    # Qt 消息（含 QtFatalMsg，默认 abort 闪退）落盘
    try:
        from PySide6.QtCore import qInstallMessageHandler, QtMsgType
        def _qt_msg(msgType, context, msg):
            try:
                if crash_fp:
                    crash_fp.write("[Qt:%s] %s\n" % (msgType, msg))
                    crash_fp.flush()
            except Exception:
                pass
        qInstallMessageHandler(_qt_msg)
    except Exception:
        pass


def selftest():
    """无头自检：验证关键模块与 GUI 可加载，结果写入 exe 目录 selftest.txt。"""
    lines = []
    ok = True

    def check(name, fn):
        nonlocal ok
        try:
            fn()
            lines.append("[OK]   %s" % name)
        except Exception as e:
            ok = False
            lines.append("[FAIL] %s: %s" % (name, e))
            lines.append(traceback.format_exc())

    check("导入核心模块", lambda: __import__("ps2hantool.core", fromlist=["Pipeline"]))
    check("导入插件", lambda: __import__("ps2hantool.plugins", fromlist=["load_builtin_plugins"]))
    check("导入翻译引擎", lambda: __import__("ps2hantool.translate.engines", fromlist=["create_engine"]))
    check("导入字库模块", lambda: __import__("ps2hantool.font.bitmap", fromlist=["BitmapFont"]))
    check("简体→cp932 转换", lambda: (
        __import__("ps2hantool.translate.jp_kanji", fromlist=["to_jis_encodable"])
        .to_jis_encodable("这是测试") .encode("cp932")))
    check("OpenCC 可用", lambda: __import__("opencc"))
    check("pycdlib 可用", lambda: __import__("pycdlib"))
    check("新建工程可用", _new_project_ok)
    check("GUI 主窗口可创建", lambda: _gui_ok())
    lines.append("RESULT: %s" % ("PASS" if ok else "FAIL"))
    out = get_app_root() / "selftest.txt"
    out.write_text("\n".join(lines), "utf-8")
    return 0 if ok else 1


def _new_project_ok():
    """模拟 GUI 首次载入：创建工程目录并验证目录树可写（exe 下 projects 目录必须可用）。"""
    import tempfile
    from pathlib import Path
    from ps2hantool.project import Project
    tmp = Path(tempfile.mkdtemp(prefix="ps2h_proj_"))
    try:
        p = Project(tmp)
        p.ensure_dirs()
        for d in (p.work_dir, p.backup_dir, p.output_dir, p.data_dir, p.log_dir):
            assert d.is_dir(), "目录未创建: %s" % d
        p.set("selftest", True)
        assert p.get("selftest") is True
        p.log("selftest ok")
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def _gui_ok():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from ps2hantool.ui.main_window import MainWindow
    app = QApplication([])
    w = MainWindow()
    w.show()
    app.processEvents()
    assert w.stack.count() == 6
    w.close()
    app.processEvents()


def loadcheck(iso_path):
    """无头载入验证：真实载入指定 ISO（含整盘提取），结果写入 loadcheck.txt。
    用于 exe 打包后的端到端验证与用户自测。"""
    import tempfile
    lines = []
    try:
        from ps2hantool.core import Pipeline
        from ps2hantool.project import Project
        tmp = Path(tempfile.mkdtemp(prefix="ps2h_loadcheck_"))
        pl = Pipeline(Project(tmp))
        info = pl.load_iso(iso_path, lambda m: None)
        lines.append("[OK]   识别游戏: %s (%s)" % (info.get("name"), info.get("slpm")))
        lines.append("[OK]   插件: %s" % pl.plugin.display_name)
        lines.append("[OK]   整盘提取完成，工程: %s" % tmp)
    except Exception as e:
        lines.append("[FAIL] %s" % e)
        lines.append(traceback.format_exc())
    out = get_app_root() / "loadcheck.txt"
    out.write_text("\n".join(lines), "utf-8")
    return 0 if lines[0].startswith("[OK]") else 1


if __name__ == "__main__":
    init_crash_logging()
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    if "--loadcheck" in sys.argv:
        idx = sys.argv.index("--loadcheck")
        iso = sys.argv[idx + 1] if len(sys.argv) > idx + 1 else ""
        if not iso or not Path(iso).exists():
            print("用法: PS2汉化工具.exe --loadcheck <iso路径>")
            sys.exit(2)
        sys.exit(loadcheck(iso))
    proj = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else None
    from ps2hantool.ui.main_window import run_gui
    run_gui(proj)
