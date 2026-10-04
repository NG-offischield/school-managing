"""Run API calls off the UI thread so the window never freezes.

    runner.run(fn, on_success, on_error)

`fn` runs in Qt's thread pool; the callbacks are delivered back on the UI
thread through a queued signal. Tests use ImmediateRunner (same API,
synchronous) to drive the screens deterministically.
"""

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


class _Relay(QObject):
    succeeded = Signal(object)
    failed = Signal(object)


class _Job(QRunnable):
    def __init__(self, fn, relay):
        super().__init__()
        self.fn, self.relay = fn, relay

    def run(self):
        try:
            result = self.fn()
        except Exception as exc:  # delivered to the UI, which decides what to show
            self.relay.failed.emit(exc)
        else:
            self.relay.succeeded.emit(result)


class TaskRunner:
    def __init__(self, pool=None):
        self.pool = pool or QThreadPool.globalInstance()
        self._alive = set()  # keep relays alive until they fire

    def run(self, fn, on_success, on_error):
        relay = _Relay()
        self._alive.add(relay)

        def done(callback):
            def handler(value):
                self._alive.discard(relay)
                callback(value)

            return handler

        relay.succeeded.connect(done(on_success))
        relay.failed.connect(done(on_error))
        self.pool.start(_Job(fn, relay))


class ImmediateRunner:
    """Synchronous runner (tests)."""

    def run(self, fn, on_success, on_error):
        try:
            result = fn()
        except Exception as exc:
            on_error(exc)
        else:
            on_success(result)
