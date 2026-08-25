# -*- coding: utf-8 -*-
"""定位 GUI 提取阶段崩溃：faulthandler + Qt 消息 + 步骤日志。"""
import faulthandler
import sys
import time
sys.path.insert(0, r"E:/桌面/心跳回忆/ps2-translator")

CRASH = r"E:/桌面/心跳回忆/ps2-translator/gui_crash.log"
fp = open(CRASH, "w", encoding="utf-8")
faulthandler.enable(fp)

from PySide6.QtCore import qInstallMessageHandler
from PySide6.QtWidgets import QApplication
from ps2hantool.ui.main_window import MainWindow
from ps2hantool.state import AppState


def qmsg(t, ctx, m):
    fp.write("[Qt:%s] %s\n" % (t, m))
    fp.flush()


qInstallMessageHandler(qmsg)

app = QApplication([])
w = MainWindow()
ISO = r"E:/桌面/心跳回忆/Tokimeki Memorial 3 [Japan][SLPM-65080]心跳回忆3/Tokimeki Memorial 3 [NTSC-J] [SLPM-65080].iso"


def pump(cond, t=600):
    t0 = time.time()
    while not cond() and time.time() - t0 < t:
        app.processEvents()
        time.sleep(0.05)
    return cond()


t0 = time.time()
w._load_iso(ISO)
ok = pump(lambda: w.state == AppState.LOADED)
fp.write("载入: %s %.1fs\n" % (ok, time.time() - t0))
fp.flush()

t0 = time.time()
w._step("extract")
ok = pump(lambda: w.state == AppState.EXTRACTED)
fp.write("提取: %s %.1fs state=%s\n" % (ok, time.time() - t0, w.state.name))
fp.flush()
fp.write("DONE\n")
