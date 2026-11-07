"""将循环库的显式begin/finish协议接入真实异步Qt网络。"""
from PySide6.QtCore import QObject, QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest

from .hub_sync import HubSynchronizer, Response


class QtHubClient(QObject):
    def __init__(self, synchronizer: HubSynchronizer, parent=None, *, manager=None):
        super().__init__(parent)
        self.synchronizer = synchronizer
        # 显式 manager 仅供调用方注入；原 04F340 每次请求新建管理器。
        self.manager = manager
        self._request_managers = {}
        self.pending = set()

    def refresh(self, explicit_url=""):
        source = self.synchronizer.begin_request(explicit_url)
        request = QNetworkRequest(QUrl(source.url))
        for name, value in source.headers:
            request.setRawHeader(name.encode("ascii"), value.encode("ascii"))
        for attribute, value in source.qt_attributes:
            request.setAttribute(QNetworkRequest.Attribute(attribute), value)
        if source.transfer_timeout_ms is not None:
            request.setTransferTimeout(source.transfer_timeout_ms)
        manager = self.manager if self.manager is not None else QNetworkAccessManager(self)
        reply = manager.get(request)
        if self.manager is None:
            self._request_managers[reply] = manager
        self.pending.add(reply)
        reply.finished.connect(lambda: self._finished(reply))
        return reply

    def _finished(self, reply):
        # 原 04D8C0 在读取响应及通知之前对 reply、manager 排队延迟释放。
        reply.deleteLater()
        manager = self._request_managers.pop(reply, None)
        if manager is not None:
            manager.deleteLater()
        # 保留完成顺序；没有额外“仅最后请求可写缓存”的规则。
        try:
            error = reply.error()
            response = Response(bytes(reply.readAll()), getattr(error, "value", error),
                reply.errorString(), reply.attribute(QNetworkRequest.HttpStatusCodeAttribute))
            self.synchronizer.finish_response(response)
        finally:
            self.pending.discard(reply)

    def close(self):
        for reply in tuple(self.pending):
            reply.abort()
