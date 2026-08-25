# -*- coding: utf-8 -*-
"""后台工作线程：把耗时流程放到 QThread，界面不卡死，支持取消。

进度协议：progress 信号携带 (消息, 已完成数, 总数)。
- done/total 均 > 0 时表示确定进度（如翻译 120/3000、载入 30/70）；
- 无法量化时传 (-1, -1)（进度条显示不确定动画）。
"""
import traceback

from PySide6.QtCore import QThread, Signal

from ..core import Pipeline


class PipelineWorker(QThread):
    """执行 pipeline 的一个步骤序列。task: callable(pipeline, progress_cb)。"""

    progress = Signal(str, int, int)      # (消息, done, total)；done<0 表示不确定
    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(self, pipeline: Pipeline, task, parent=None):
        super().__init__(parent)
        self.pipeline = pipeline
        self.task = task

    def run(self):
        try:
            result = self.task(self.pipeline, self._emit)
            self.finished_ok.emit(result)
        except InterruptedError:
            self.failed.emit("已取消")
        except Exception as e:
            traceback.print_exc()
            self.failed.emit(str(e))

    def _emit(self, msg, done=-1, total=-1):
        try:
            self.progress.emit(msg, int(done), int(total))
        except Exception:
            # 进度回调绝不允许影响业务线程（历史上参数不匹配曾导致静默丢失进度）
            pass

    def cancel(self):
        self.pipeline.cancel()
