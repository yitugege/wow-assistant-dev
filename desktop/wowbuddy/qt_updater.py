"""Qt transport and local QFile adapter for Updater; no replacement or restart.

Construction has no network/file side effects. Call check()/download() explicitly.
All client methods and callbacks belong to the client's Qt thread. Verification
is synchronous on that thread, matching the original; HTTP itself is asynchronous.
"""
from dataclasses import dataclass, field
from typing import Callable

from PySide6.QtCore import (QObject, Signal, QUrl, QTimer, QDateTime, QTime,
                           QFile, QFileInfo, QIODevice, QFileDevice, QThread)
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest

from .updater import Updater, UpdateResponse, CURRENT_VERSION


def _number(value):
    return int(getattr(value, "value", value))


class QtUpdateFile:
    """Translate QFile's error-return convention to Updater's OSError contract."""

    def __init__(self, file):
        self.file = file

    def write(self, data):
        # 原readyRead不检查返回值或文件错误，统一在finished的flush之后读取错误。
        return self.file.write(data)

    def flush(self):
        self.file.flush()
        if self.file.error() != QFileDevice.FileError.NoError:
            raise OSError(self.file.errorString())

    def close(self):
        self.file.close()


class QtLocalUpdateFS:
    """Actual filesystem I/O, invoked only by explicitly called update operations.

    probe_write creates/truncates the specified native write-test filename, then
    closes/removes it. remove is non-recursive. No executable replacement method
    is exposed. Supplying this adapter authorizes only the paths given by Updater.
    """

    def read_first_line(self, path):
        file = QFile(str(path))
        if not file.open(QIODevice.OpenModeFlag.ReadOnly | QIODevice.OpenModeFlag.Text):
            raise OSError(file.errorString())
        try:
            result = bytes(file.readLine())
            if file.error() != QFileDevice.FileError.NoError:
                raise OSError(file.errorString())
            return result
        finally:
            file.close()

    def is_file(self, path):
        info = QFileInfo(str(path))
        return info.exists() and info.isFile()

    def probe_write(self, path):
        file = QFile(str(path))
        if not file.open(QIODevice.OpenModeFlag.WriteOnly):
            return False
        file.close()
        QFile.remove(str(path))
        # Native returns success after open, regardless of remove's return value.
        return True

    def remove(self, path):
        return QFile.remove(str(path))

    def open_write(self, path):
        file = QFile(str(path))
        if not file.open(QIODevice.OpenModeFlag.WriteOnly | QIODevice.OpenModeFlag.Truncate):
            raise OSError(file.errorString())
        return QtUpdateFile(file)

    def size(self, path):
        return QFileInfo(str(path)).size()

    def read_chunks(self, path, chunk_size):
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        file = QFile(str(path))
        if not file.open(QIODevice.OpenModeFlag.ReadOnly):
            raise OSError(file.errorString())
        try:
            while True:
                chunk = bytes(file.read(chunk_size))
                if file.error() != QFileDevice.FileError.NoError:
                    raise OSError(file.errorString())
                if not chunk:
                    return
                yield chunk
        finally:
            file.close()


class _ObservedUpdater(Updater):
    """Observe every existing state assignment without duplicating core policy."""

    def __init__(self, *args, on_ui, **kwargs):
        self._on_ui = None
        super().__init__(*args, **kwargs)
        self._on_ui = on_ui

    @property
    def ui(self):
        return self._ui

    @ui.setter
    def ui(self, value):
        self._ui = value
        if self._on_ui is not None:
            self._on_ui(value)


@dataclass
class _Pending:
    request: object
    manager: object = None
    reply: object = None
    timer: object = None
    connections: list = field(default_factory=list)


class QtUpdaterClient(QObject):
    """GUI bridge. Factories are called per request and returned objects are owned.

    auto_download_requested is a notification, not an implicit download command.
    Connect it to the host's monitor-stop/download flow if automatic updates are
    wanted. verified means a checked .part exists, never that the app was updated.
    """

    ui_changed = Signal(object)
    checked = Signal(object)
    verified = Signal(object)
    log_message = Signal(str)
    auto_download_requested = Signal()
    adapter_error = Signal(str)

    def __init__(self, parent=None, *, env, application_dir, fs=None,
                 current_version=CURRENT_VERSION, manager_factory=None,
                 timer_factory=None, auto_update: Callable[[], bool] | None = None,
                 clock=None):
        super().__init__(parent)
        self._closed = False
        self._pending = {}
        self._manager_factory = manager_factory or (lambda parent: QNetworkAccessManager(parent))
        self._timer_factory = timer_factory or (lambda parent: QTimer(parent))
        self._auto_update = auto_update or (lambda: False)
        self._clock = clock or (lambda: (QDateTime.currentMSecsSinceEpoch(), QTime.currentTime().toString("HH:mm")))
        self.updater = _ObservedUpdater(self, fs if fs is not None else QtLocalUpdateFS(),
                                      env=env, application_dir=application_dir,
                                      current_version=current_version, on_ui=self._state_changed)

    @property
    def ui(self):
        return self.updater.ui

    @property
    def pending_ids(self):
        return tuple(self._pending)

    def _thread_check(self):
        if QThread.currentThread() != self.thread():
            raise RuntimeError("QtUpdaterClient must be used from its owning Qt thread")

    def _ensure_open(self):
        self._thread_check()
        if self._closed:
            raise RuntimeError("QtUpdaterClient is closed")

    def _state_changed(self, state):
        if not self._closed:
            self.ui_changed.emit(state)

    def _publish_logs(self):
        if not self._closed:
            for message in self.updater.ui.logs:
                self.log_message.emit(message)

    def check(self, *, manual=True):
        self._ensure_open()
        return self.updater.start_check(manual=manual)

    def download(self):
        self._ensure_open()
        was_busy = self.updater.busy
        request = self.updater.start_download()
        if request is None and not was_busy:
            self._publish_logs()
        return request

    def cancel(self):
        self._ensure_open()
        self.updater.cancel()

    @staticmethod
    def _connect(pending, signal, slot):
        signal.connect(slot)
        pending.connections.append((signal, slot))

    def start(self, source):
        """Updater's HTTP protocol entry; normally called via check/download."""
        self._thread_check()
        if self._closed:
            self.updater.active = None
            self.updater._close_file()
            return
        pending = _Pending(source)
        self._pending[source.id] = pending
        try:
            request = QNetworkRequest(QUrl(source.url))
            for name, value in source.headers.items():
                if name.lower() == "user-agent":
                    request.setHeader(QNetworkRequest.KnownHeaders.UserAgentHeader, value)
                else:
                    request.setRawHeader(name.encode("ascii"), value.encode("ascii"))
            for attribute, value in source.qt_attributes.items():
                request.setAttribute(QNetworkRequest.Attribute(attribute), value)
            # Do not use setTransferTimeout: native check uses an absolute single-shot.
            pending.manager = self._manager_factory(self)
            pending.reply = pending.manager.get(request)
            if pending.reply is None:
                raise RuntimeError("QNetworkAccessManager.get returned no reply")
            reply = pending.reply
            if source.kind == "download":
                self._connect(pending, reply.readyRead, lambda: self._ready_read(pending))
                self._connect(pending, reply.downloadProgress,
                              lambda received, total: self._progress(pending, received, total))
            self._connect(pending, reply.finished, lambda: self._finished(pending))
            if source.timeout_ms is not None:
                pending.timer = self._timer_factory(reply)
                pending.timer.setSingleShot(True)
                self._connect(pending, pending.timer.timeout, lambda: self._timeout(pending))
                pending.timer.start(source.timeout_ms)
        except (RuntimeError, OSError, TypeError, ValueError) as error:
            text = "Qt更新适配层启动失败：" + str(error)
            self.adapter_error.emit(text)
            # Finish asynchronously so Updater.start_download can finish initial progress.
            QTimer.singleShot(0, self, lambda: self._start_failed(pending, text))

    def _live(self, pending):
        return not self._closed and self._pending.get(pending.request.id) is pending

    def _timeout(self, pending):
        if self._live(pending) and pending.reply.isRunning():
            self.updater.check_timeout(pending.request.id)

    def abort(self, request_id):
        self._thread_check()
        pending = self._pending.get(request_id)
        if pending is not None and pending.reply is not None:
            pending.reply.abort()

    def _ready_read(self, pending):
        if self._live(pending):
            self.updater.download_data(pending.request.id, bytes(pending.reply.readAll()))

    def _progress(self, pending, received, total):
        if self._live(pending):
            self.updater.download_progress(pending.request.id, received, total)

    @staticmethod
    def _disconnect(pending):
        for signal, slot in pending.connections:
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        pending.connections.clear()

    def _release(self, pending, *, abort=False):
        self._pending.pop(pending.request.id, None)
        self._disconnect(pending)
        if pending.timer is not None:
            pending.timer.stop()
            pending.timer.deleteLater()
        if pending.reply is not None:
            if abort and pending.reply.isRunning():
                pending.reply.abort()
            pending.reply.deleteLater()
        if pending.manager is not None:
            pending.manager.deleteLater()

    def _finished(self, pending):
        if not self._live(pending):
            return
        reply = pending.reply
        code = _number(reply.error())
        # Native checks download errors before reading final residual bytes.
        body = bytes(reply.readAll()) if pending.request.kind == "check" or code == 0 else b""
        response = UpdateResponse(body, code, reply.errorString())
        self._release(pending)
        self._finish_response(pending.request, response)

    def _start_failed(self, pending, text):
        if self._live(pending):
            self._release(pending, abort=True)
            self._finish_response(pending.request, UpdateResponse(error_code=99, error_text=text))

    def _finish_response(self, request, response):
        if self._closed:
            return
        if request.kind == "check":
            now_ms, time_text = self._clock()
            info = self.updater.finish_check(request.id, response,
                                           auto_update=bool(self._auto_update()),
                                           now_ms=now_ms, time_text=time_text)
            if info is not None and not self._closed:
                want_download = self.updater.ui.auto_download_requested
                self._publish_logs()
                self.checked.emit(info)
                if want_download and not self._closed and not self.updater.busy:
                    self.auto_download_requested.emit()
        else:
            result = self.updater.finish_download(request.id, response)
            self._publish_logs()
            if result is not None and not self._closed:
                self.verified.emit(result)

    def close(self):
        """Destructor-like cleanup: abort, close files, retain incomplete .part.

        Unlike cancel(), no completion/log/auto-download signal is emitted. Call
        before destroying the host window; this method never calls application quit.
        """
        self._thread_check()
        if self._closed:
            return
        self._closed = True
        for pending in tuple(self._pending.values()):
            self._release(pending, abort=True)
        self.updater.active = None
        self.updater._close_file()
