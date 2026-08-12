from __future__ import annotations

from PyQt6 import QtCore


class WorkerSignals(QtCore.QObject):
    """Signals emitted by background workers.

    finished(object) - called with the result of the function
    error(Exception) - called with any exception raised during execution
    """

    finished = QtCore.pyqtSignal(object)
    error = QtCore.pyqtSignal(Exception)


class Worker(QtCore.QRunnable):
    """Run a function in a background thread and emit result via signals.

    Usage:
        worker = Worker(fn, *args, **kwargs)
        worker.signals.finished.connect(on_ok)
        worker.signals.error.connect(on_err)
        QtCore.QThreadPool.globalInstance().start(worker)
    """

    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

    @QtCore.pyqtSlot()
    def run(self):
        try:
            res = self.fn(*self.args, **self.kwargs)
        except Exception as e:
            # propagate exception to the main thread
            self.signals.error.emit(e)
            return
        self.signals.finished.emit(res)
