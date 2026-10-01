"""Runs blocking API calls off the Qt UI thread. Every page uses run_async(...) instead
of calling api_client methods directly, so a slow/unreachable backend never freezes the
window."""

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal, Slot


class WorkerSignals(QObject):
    finished = Signal(object)
    error = Signal(object)


class Worker(QRunnable):
    def __init__(self, fn, *args, **kwargs):
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()
        # Python owns the lifetime (via _running below), not the thread pool.
        self.setAutoDelete(False)

    @Slot()
    def run(self):
        try:
            result = self.fn(*self.args, **self.kwargs)
        except Exception as e:  # noqa: BLE001 — must reach the UI as a signal, never crash the thread
            self._emit(self.signals.error, e)
        else:
            self._emit(self.signals.finished, result)

    @staticmethod
    def _emit(signal, payload) -> None:
        try:
            signal.emit(payload)
        except RuntimeError:
            pass  # the app is shutting down and the receiving side is already gone


# Callers rarely keep the Worker returned by run_async, and without another reference Python
# can collect it — and its WorkerSignals — while the request is still in flight. Its result
# signal then never arrives ("Signal source has been deleted"), silently stalling whatever was
# waiting on it: a MAYA conversation that asks a question and never starts listening.
_running: set[Worker] = set()


def _release_later(worker: Worker) -> None:
    # Deferred: dropping the last reference from inside the worker's own signal emission
    # would delete the object that is still emitting.
    QTimer.singleShot(0, lambda: _running.discard(worker))


def run_async(fn, *args, on_success=None, on_error=None, **kwargs) -> Worker:
    worker = Worker(fn, *args, **kwargs)
    _running.add(worker)
    if on_success:
        worker.signals.finished.connect(on_success)
    if on_error:
        worker.signals.error.connect(on_error)
    worker.signals.finished.connect(lambda _result: _release_later(worker))
    worker.signals.error.connect(lambda _err: _release_later(worker))
    QThreadPool.globalInstance().start(worker)
    return worker
