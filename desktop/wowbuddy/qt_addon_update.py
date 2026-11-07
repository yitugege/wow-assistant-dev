"""插件热更的真实Qt传输与QSaveFile通道；构造不联网、不写盘。"""
from PySide6.QtCore import QObject, Signal, QUrl, QFile, QSaveFile, QIODevice, QThread
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest

from .addon_update import AddonUpdater, AddonUpdateResponse
from .qt_updater import QtLocalUpdateFS


class _AtomicFile:
    def __init__(self, file):
        self.file, self.finished = file, False

    def write(self, data):
        return self.file.write(data)

    def commit(self):
        success = self.file.commit()
        self.finished = True
        return success

    def cancel(self):
        self.file.cancelWriting()

    def close(self):
        # QSaveFile必须commit/cancel；不能调用其被禁用的QFileDevice.close。
        if not self.finished:
            self.file.cancelWriting()
        self.file = None


class QtAddonUpdateFS(QtLocalUpdateFS):
    def read_bytes(self, path):
        file = QFile(str(path))
        if not file.open(QIODevice.OpenModeFlag.ReadOnly):
            raise OSError(file.errorString())
        try:
            return bytes(file.readAll())
        finally:
            file.close()

    def open_atomic(self, path):
        file = QSaveFile(str(path))
        if not file.open(QIODevice.OpenModeFlag.WriteOnly):
            raise OSError(file.errorString())
        return _AtomicFile(file)


class QtAddonUpdaterClient(QObject):
    state_changed = Signal(object)
    log_message = Signal(str)
    adapter_error = Signal(str)

    def __init__(self, parent=None, *, env, application_dir, pending, games,
                 installed_name, install, fs=None, manager_factory=None):
        super().__init__(parent)
        self._closed = False
        self._requests, self._managers = {}, {}
        self._manager_factory = manager_factory or (lambda parent: QNetworkAccessManager(parent))
        self.updater = AddonUpdater(self, fs or QtAddonUpdateFS(), pending,
            env=env, application_dir=application_dir, games=games,
            installed_name=installed_name, install=install,
            on_log=self.log_message.emit, on_state=self.state_changed.emit,
            on_session_end=self._release_manager)

    def _release_manager(self, session_id):
        manager = self._managers.pop(session_id, None)
        if manager is not None:
            manager.deleteLater()

    def refresh(self):
        if self._closed:
            raise RuntimeError("插件更新通道已关闭")
        if QThread.currentThread() != self.thread():
            raise RuntimeError("插件更新必须在所属Qt线程调用")
        return self.updater.start_check()

    def start(self, source):
        if self._closed:
            return
        manager = self._managers.get(source.session_id)
        if manager is None:
            manager = self._manager_factory(self)
            self._managers[source.session_id] = manager
        request = QNetworkRequest(QUrl(source.url))
        request.setTransferTimeout(source.transfer_timeout_ms)
        # 原插件热更没有程序更新通道的UA和额外属性。
        reply = manager.get(request)
        callback = lambda: self._finished(source, reply)
        self._requests[source.id] = (source, reply, callback)
        reply.finished.connect(callback)

    def _finished(self, source, reply):
        if self._closed or source.id not in self._requests:
            return
        item = self._requests.pop(source.id)
        reply.finished.disconnect(item[2])
        # 07FA10/07E5E0在读取回复前调用deleteLater，实际析构由Qt延后。
        reply.deleteLater()
        try:
            error = reply.error()
            response = AddonUpdateResponse(bytes(reply.readAll()),
                int(getattr(error, "value", error)), reply.errorString())
            if source.kind == "metadata":
                self.updater.finish_metadata(source.id, response)
            else:
                self.updater.finish_download(source.id, response)
        except (OSError, ValueError, RuntimeError) as error:
            self.updater._end("adapter_failed", str(error))
            self.adapter_error.emit(f"插件更新适配失败：{error}")
        finally:
            if not any(item[0].session_id == source.session_id for item in self._requests.values()):
                self._release_manager(source.session_id)

    def close(self):
        if self._closed:
            return
        self._closed = True
        for source, reply, callback in tuple(self._requests.values()):
            reply.finished.disconnect(callback)
            reply.abort()
            reply.deleteLater()
        self._requests.clear()
        for manager in self._managers.values():
            manager.deleteLater()
        self._managers.clear()
        self.updater.active = None
