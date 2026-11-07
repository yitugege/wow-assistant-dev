"""循环库请求与离线缓存生命周期，HTTP/文件系统必须由调用者注入。

不在导入或构造时联网。原生证据见 evidence/循环同步.md。
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import os
from pathlib import Path
import tempfile
from typing import Callable, Mapping, Protocol

from .expressions import _trim
from .rotation_selection import HubState, load_snapshot

DEFAULT_HUB_URL = "https://wowbuddy.cn/library/rotations.json"
HUB_URL_ENV = "WOWBUDDY_HUB_URL"
HOME_ENV = "WOWBUDDY_HOME"
REFRESH_INTERVAL_MS = 1_800_000


def snapshot_error_text(error: str, payload: bytes) -> str:
    """04E250用户文案；保留HubState.error分类，通知前完成格式化。"""
    if error == "wrong_format":
        return "这个地址返回的不是循环库快照"
    if error == "invalid_json":
        from PySide6.QtCore import QJsonDocument, QJsonParseError
        parsed = QJsonParseError()
        QJsonDocument.fromJson(payload, parsed)
        return "快照不是合法 JSON：" + parsed.errorString()
    return error


class AtomicWriter(Protocol):
    def write(self, data: bytes) -> int: ...
    def commit(self) -> bool: ...
    def cancel(self) -> None: ...


class FileBackend(Protocol):
    def read_bytes(self, path: str) -> bytes: ...
    def read_first_line(self, path: str) -> bytes: ...
    def mkdirs(self, path: str) -> bool: ...
    def begin_atomic(self, path: str) -> AtomicWriter: ...


@dataclass(frozen=True)
class Request:
    url: str
    method: str = "GET"
    headers: tuple[tuple[str, str], ...] = (("User-Agent", "WOWBattleAssistant"),)
    # QNetworkRequest: RedirectPolicyAttribute=22 -> NoLessSafeRedirectPolicy=1;
    # CacheLoadControlAttribute=4 -> AlwaysNetwork=0。
    qt_attributes: tuple[tuple[int, int], ...] = ((22, 1), (4, 0))
    transfer_timeout_ms: int | None = None   # 原循环库请求没有 setTransferTimeout。


@dataclass(frozen=True)
class Response:
    body: bytes = b""
    network_error: int = 0                 # 后端已完成 Qt 等价错误分类；0才解析。
    error_string: str = ""
    http_status: int | None = None         # 原回调不直接读取此值。


class HttpBackend(Protocol):
    def get(self, request: Request) -> Response: ...


@dataclass(frozen=True)
class SyncResult:
    hub: HubState
    status: str
    accepted: bool
    cache_path: str | None = None
    cache_written: bool | None = None


def _join(base: str, suffix: str) -> str:
    # 原生 QString::append，保留路径原文，不偷偷规范化相对目录。
    return base + suffix


def resolve_url(explicit: str, environment: Mapping[str, str], application_dir: str,
                files: FileBackend) -> str:
    if explicit:
        return explicit
    override = environment.get(HUB_URL_ENV, "")
    if override:
        return override
    try:
        first = files.read_first_line(_join(application_dir, "/hub_url.txt"))
    except OSError:
        first = b""
    text = _trim(first.decode("utf-8", errors="replace"))
    if text and not text.startswith("#"):
        return text
    return DEFAULT_HUB_URL


def cache_path(environment: Mapping[str, str], application_dir: str, files: FileBackend) -> str:
    base = environment.get(HOME_ENV, "")
    if base:
        try:
            made = files.mkdirs(base)
        except OSError:
            made = False
        if not made:
            base = application_dir
    else:
        base = application_dir
    return _join(base, "/hub/rotations.json")


class HubSynchronizer:
    """04f960/04f340/04d8c0；允许异步 begin/finish 和同步注入测试。

    原生没有循环库 in-flight 锁或“最新请求代次”检查，完成顺序决定内存状态。
    on_changed 对应信号；可返回已被消费者清除 changed_pending 的 HubState。
    """
    def __init__(self, files: FileBackend, *, application_dir: str,
                 environment: Mapping[str, str] | None = None, hub: HubState | None = None,
                 on_changed: Callable[[HubState, str], HubState | None] | None = None):
        self.files = files
        self.application_dir = application_dir
        self.environment = environment if environment is not None else {}
        self.hub = hub or HubState()
        self.status = "尚未拉取"
        self.on_changed = on_changed

    def _notify(self) -> None:
        if self.on_changed is not None:
            state = self.on_changed(self.hub, self.status)
            if state is not None:
                self.hub = state

    def load_cache(self) -> SyncResult:
        path = cache_path(self.environment, self.application_dir, self.files)
        try:
            payload = self.files.read_bytes(path)
        except OSError:
            return SyncResult(self.hub, self.status, False, path)
        result = load_snapshot(payload, self.hub, from_cache=True)
        self.hub = result.state
        if result.accepted:
            self.status = f"本地快照 {self.hub.generated_at}（正在联网检查更新…）"
            self._notify()
        elif payload.strip():
            # 解析器更新错误状态，但 04f960 的失败路径不发 changed 信号。
            self.status = snapshot_error_text(self.hub.error, payload)
        return SyncResult(self.hub, self.status, result.accepted, path)

    def begin_request(self, explicit_url: str = "") -> Request:
        url = resolve_url(explicit_url, self.environment, self.application_dir, self.files)
        self.status = "正在检查循环库更新…"
        self._notify()
        return Request(url)

    def _save(self, path: str, payload: bytes) -> bool:
        writer = None
        try:
            # Qt QFileInfo.absolutePath 在 FS 后端解析；slash 路径的父目录与此一致。
            parent = path.rsplit("/", 1)[0]
            if not self.files.mkdirs(parent):
                return False
            writer = self.files.begin_atomic(path)
            if writer.write(payload) != len(payload):
                writer.cancel()
                return False
            return writer.commit()
        except OSError:
            if writer is not None:
                writer.cancel()
            return False

    def finish_response(self, response: Response) -> SyncResult:
        if response.network_error != 0:
            self.hub = replace(self.hub, valid=bool(self.hub.profiles))
            self.status = (f"离线：联网失败（{response.error_string}），继续用本地快照（{self.hub.generated_at}）"
                           if self.hub.profiles else f"拉取失败：{response.error_string}")
            self._notify()
            return SyncResult(self.hub, self.status, False)
        loaded = load_snapshot(response.body, self.hub, from_cache=False)
        self.hub = loaded.state
        if not loaded.accepted:
            self.hub = replace(self.hub, valid=bool(self.hub.profiles))
            self.status = snapshot_error_text(self.hub.error, response.body)
            self._notify()
            return SyncResult(self.hub, self.status, False)
        # 成功解析已经替换内存；落盘失败不恢复旧库。
        path = cache_path(self.environment, self.application_dir, self.files)
        saved = self._save(path, response.body)
        verb = "已更新" if self.hub.changed_pending else "已是最新"
        self.status = f"循环库{verb}（快照 {self.hub.generated_at}）"
        if not saved:
            self.status += " · 本地写入失败"
        self._notify()
        return SyncResult(self.hub, self.status, True, path, saved)

    def sync(self, http: HttpBackend, explicit_url: str = "") -> SyncResult:
        """后端应返回 Response 错误值；未分类异常原样抛出，不伪造 Qt 错误码。"""
        return self.finish_response(http.get(self.begin_request(explicit_url)))

    def startup(self, http: HttpBackend) -> tuple[SyncResult, SyncResult]:
        """构造函数原生顺序：缓存→立即请求；30分钟定时由上层调度。"""
        cached = self.load_cache()
        return cached, self.sync(http)


class _LocalAtomicWriter:
    def __init__(self, destination: str):
        self.destination = Path(destination)
        fd, path = tempfile.mkstemp(prefix=".hub-", dir=self.destination.parent)
        self.temporary = Path(path)
        self.stream = os.fdopen(fd, "wb")

    def write(self, data: bytes) -> int:
        return self.stream.write(data)

    def commit(self) -> bool:
        try:
            self.stream.flush()
            os.fsync(self.stream.fileno())
            self.stream.close()
            os.replace(self.temporary, self.destination)
            return True
        except OSError:
            self.cancel()
            return False

    def cancel(self) -> None:
        self.stream.close()
        self.temporary.unlink(missing_ok=True)


class LocalFileBackend:
    """显式可选的标准库文件适配器；构造不会读写，测试使用内存后端。"""
    def read_bytes(self, path: str) -> bytes:
        return Path(path).read_bytes()

    def read_first_line(self, path: str) -> bytes:
        with Path(path).open("rb") as stream:
            return stream.readline()

    def mkdirs(self, path: str) -> bool:
        try:
            Path(path).mkdir(parents=True, exist_ok=True)
            return True
        except OSError:
            return False

    def begin_atomic(self, path: str) -> AtomicWriter:
        return _LocalAtomicWriter(path)
