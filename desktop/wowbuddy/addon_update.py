"""Native addon hot-update/reinstall policy; HTTP, storage and installer injected.

This is separate from executable updates: addonBin metadata, mandatory hash,
QSaveFile-style cache replacement, then selective reinstall/defer. No live game
scan, network client, registry writer or automatic timer is created here.
"""
from dataclasses import dataclass, replace
from typing import Protocol
import hashlib
import ntpath
import struct

from .updater import resolve_update_url  # Native both call exactly 0b4520.

STARTUP_DELAY_MS = 5000
PERIODIC_INTERVAL_MS = 1800000
METADATA_TIMEOUT_MS = 15000
DOWNLOAD_TIMEOUT_MS = 60000
PENDING_KEY = "addonPendingReinstall"
MAGIC = b"WBADDON1\n"


@dataclass(frozen=True)
class AddonUpdateRequest:
    id: int
    session_id: int
    kind: str
    url: str
    transfer_timeout_ms: int
    headers: tuple = ()
    qt_attributes: tuple = ()


@dataclass(frozen=True)
class AddonUpdateResponse:
    body: bytes = b""
    error_code: int = 0
    error_text: str = ""


@dataclass(frozen=True)
class AddonMetadata:
    sha256: str = ""
    file: str = ""

    @property
    def usable(self):
        return bool(self.sha256 and self.file)


@dataclass(frozen=True)
class AddonGame:
    """012730 record projection: label+18, AddOns+48, running+61, installed+68."""
    label: str
    addons_path: str
    running: bool = False
    installed_name: str = ""


@dataclass(frozen=True)
class ReinstallResult:
    ok: bool
    addon_name: str = ""
    error: str = ""


@dataclass(frozen=True)
class GameUpdateAction:
    path: str
    status: str
    addon_name: str = ""
    error: str = ""


@dataclass(frozen=True)
class CacheReplaceResult:
    ok: bool
    error: str = ""


@dataclass(frozen=True)
class AddonUpdateState:
    phase: str = "idle"
    busy: bool = False
    cache_changed: bool = False
    error: str = ""
    actions: tuple[GameUpdateAction, ...] = ()
    pending: tuple[str, ...] = ()


class AddonUpdateFS(Protocol):
    def read_first_line(self, path: str) -> bytes: ...
    def read_bytes(self, path: str) -> bytes: ...
    def open_atomic(self, path: str): ...  # write, commit, cancel, close; described below


class PendingAddons(Protocol):
    def read(self) -> tuple[str, ...]: ...
    def write(self, paths: tuple[str, ...]) -> None: ...


class SettingsPendingAddons:
    """Explicit bridge to the existing SettingsStore; construction does no I/O."""
    def __init__(self, settings):
        self.settings = settings

    def read(self):
        return tuple(self.settings._read(PENDING_KEY, [], "strings"))

    def write(self, paths):
        self.settings.qsettings.setValue(PENDING_KEY, list(paths))


def parse_addon_metadata(body):
    from PySide6.QtCore import QJsonDocument
    root = QJsonDocument.fromJson(body).object()
    value = root.get("addonBin")
    value = value if isinstance(value, dict) else {}
    sha = value.get("sha256")
    file = value.get("file")
    return AddonMetadata(sha.lower() if isinstance(sha, str) else "",
                         file if isinstance(file, str) else "")


def addon_download_url(metadata_url, file):
    from PySide6.QtCore import QUrl
    if not QUrl(file).isRelative():
        return file
    suffix = "/data/latest.json"
    if metadata_url.endswith(suffix):
        base = metadata_url[:-len(suffix)]
    else:
        slash = metadata_url.rfind("/")
        base = metadata_url[:slash] if slash > 0 else metadata_url
    return base.rstrip("/") + "/" + file.lstrip("/")


def cache_header_error(data):
    """016e10 intentionally checks only magic/length/count, not full extraction."""
    if len(data) < 13 or not data.startswith(MAGIC):
        return "下载的插件包损坏（magic 不匹配）"
    count = struct.unpack_from("<I", data, 9)[0]
    if not 1 <= count <= 4096:
        return f"下载的插件包条目数异常：{count}"
    return ""


def replace_addon_cache(data, path, fs):
    """Atomic sink contract: failed commit/cancel/close preserves original cache.

    open_atomic returns an opened QSaveFile-like sink or raises OSError. write
    returns its byte count; commit returns bool; cancel discards temporary data;
    close releases it. This function never opens a real file on its own.
    """
    error = cache_header_error(data)
    if error:
        return CacheReplaceResult(False, error)
    try:
        sink = fs.open_atomic(path)
    except OSError:
        return CacheReplaceResult(False, f"本地插件包不可写：{path}")
    try:
        try:
            written = sink.write(data)
        except OSError:
            written = -1
        if written != len(data):
            sink.cancel()
            return CacheReplaceResult(False, "写入插件包不完整")
        try:
            committed = sink.commit()
        except OSError:
            committed = False
        if not committed:
            return CacheReplaceResult(False, f"插件包落盘失败：{path}")
        return CacheReplaceResult(True)
    finally:
        sink.close()


class AddonUpdater:
    def __init__(self, http, fs: AddonUpdateFS, pending: PendingAddons, *,
                 env, application_dir, games, installed_name, install,
                 on_log=None, on_state=None, on_session_end=None):
        """games()->fresh AddonGame sequence; install(path)->ReinstallResult.

        install must use the current addon.bin through the existing installer
        (plan_install/write_install/record/cleanup), not a cached startup payload.
        installed_name(path) is the existing signature-directory fallback scan.
        No implicit success callback/default game enumeration is supplied.
        """
        self.http, self.fs, self.pending = http, fs, pending
        self.env, self.application_dir = env, application_dir
        self.games, self.installed_name, self.install = games, installed_name, install
        self.on_log, self.on_state = on_log, on_state
        self.on_session_end = on_session_end
        self.cache_path = ntpath.abspath(ntpath.join(application_dir, "addon.bin"))
        self.state = AddonUpdateState()
        self.active = None
        self.metadata = AddonMetadata()
        self._request_id = self._session_id = 0

    @property
    def busy(self):
        return self.state.busy

    def _state(self, **changes):
        self.state = replace(self.state, **changes)
        if self.on_state is not None:
            self.on_state(self.state)

    def _log(self, text):
        if self.on_log is not None:
            self.on_log(text)

    def _request(self, kind, url, timeout):
        self._request_id += 1
        request = AddonUpdateRequest(self._request_id, self._session_id, kind, url, timeout)
        self.active = request
        self.http.start(request)
        return request

    def start_check(self):
        if self.busy:
            return None
        self._session_id += 1
        self.metadata = AddonMetadata()
        self._state(phase="checking", busy=True, cache_changed=False, error="", actions=(), pending=())
        url = resolve_update_url(self.env, self.application_dir, self.fs)
        return self._request("metadata", url, METADATA_TIMEOUT_MS)

    def _matches(self, request_id, kind):
        return self.active is not None and self.active.id == request_id and self.active.kind == kind

    def _end(self, phase, error="", **fields):
        # 原完成槽先安排会话管理器释放，再清除忙标记。
        if self.on_session_end is not None:
            self.on_session_end(self._session_id)
        self.active = None
        self._state(phase=phase, busy=False, error=error, **fields)
        return self.state

    def finish_metadata(self, request_id, response):
        if not self._matches(request_id, "metadata"):
            return None
        if response.error_code:
            return self._end("metadata_failed", response.error_text)  # Native silent failure.
        self.metadata = parse_addon_metadata(response.body)
        if not self.metadata.usable:
            return self._end("metadata_unusable")  # No pending retry here.
        try:
            local_hash = hashlib.sha256(self.fs.read_bytes(self.cache_path)).hexdigest()
        except OSError:
            local_hash = ""
        if local_hash == self.metadata.sha256:
            actions, paths = self._retry_pending()
            return self._end("current", actions=actions, pending=paths)
        # Resolve override again, just as 07fa10 calls 0b4520 after metadata arrives.
        url = addon_download_url(resolve_update_url(self.env, self.application_dir, self.fs),
                                 self.metadata.file)
        self._state(phase="downloading")
        return self._request("addon", url, DOWNLOAD_TIMEOUT_MS)

    def _install(self, path):
        result = self.install(path)
        if not isinstance(result, ReinstallResult):
            raise TypeError("install callback must return ReinstallResult; success cannot be inferred")
        return result

    def finish_download(self, request_id, response):
        if not self._matches(request_id, "addon"):
            return None
        if response.error_code:
            text = f"插件热更：下载失败（{response.error_text}），继续用本地版本"
            self._log(text)
            return self._end("download_failed", response.error_text)
        digest = hashlib.sha256(response.body).hexdigest()
        if digest != self.metadata.sha256:
            text = "插件热更：哈希不符（下载损坏），已放弃"
            self._log(text)
            return self._end("hash_mismatch", text)
        result = replace_addon_cache(response.body, self.cache_path, self.fs)
        if not result.ok:
            self._log("插件热更：替换失败——" + result.error)
            return self._end("cache_failed", result.error)
        self._state(phase="reinstalling", cache_changed=True)
        self._log("插件热更：addon.bin 已更新为线上版本，正在重装…")
        actions = []
        for game in self.games():
            path = game.addons_path
            if not path:
                actions.append(GameUpdateAction(path, "skipped_empty_path"))
                continue
            name = game.installed_name or self.installed_name(path)
            if not name:
                actions.append(GameUpdateAction(path, "skipped_not_installed"))
                continue
            if game.running:
                self._log(f"  {game.label} 正在运行，插件下次启动软件时重装")
                paths = tuple(self.pending.read())
                if path not in paths:  # Native QStringList.contains(CaseSensitive).
                    self.pending.write(paths + (path,))
                actions.append(GameUpdateAction(path, "deferred", name))
                continue
            outcome = self._install(path)
            if outcome.ok:
                self._log(f"  {game.label} 已重装 ✓（目录 {outcome.addon_name}）")
                actions.append(GameUpdateAction(path, "installed", outcome.addon_name))
            else:
                self._log(f"  {game.label} 重装失败：{outcome.error}")
                actions.append(GameUpdateAction(path, "install_failed", error=outcome.error))
            # Native neither queues failures here nor clears existing pending on success.
        self._log("插件热更完成（游戏里 /reload 后生效）")
        return self._end("cache_updated", actions=tuple(actions), pending=tuple(self.pending.read()))

    def _retry_pending(self):
        pending = tuple(self.pending.read())
        if not pending:
            return (), ()  # Native does not enumerate games or rewrite the empty setting.
        games = tuple(self.games())
        remaining, actions = [], []
        succeeded = False
        for path in pending:
            game = next((game for game in games if game.addons_path == path), None)
            if game is None:
                actions.append(GameUpdateAction(path, "dropped_not_detected"))
                continue
            if game.running:
                remaining.append(path)
                actions.append(GameUpdateAction(path, "still_running"))
                continue
            outcome = self._install(path)  # No installed-name requirement in pending branch.
            if outcome.ok:
                self._log(f"插件补装：{game.label} 已重装 ✓（目录 {outcome.addon_name}）")
                succeeded = True
                actions.append(GameUpdateAction(path, "installed", outcome.addon_name))
            else:
                self._log(f"插件补装：{game.label} 失败：{outcome.error}")
                remaining.append(path)
                actions.append(GameUpdateAction(path, "install_failed", error=outcome.error))
        self.pending.write(tuple(remaining))
        if succeeded:
            self._log("插件补装完成（游戏里需重启客户端后生效）")
        return tuple(actions), tuple(remaining)

    def retry_pending(self):
        """Explicit standalone 0a05a0 entry; scheduler determines when to invoke it.

        Automatically invoked only for usable metadata whose SHA matches cache.
        This method does not add another native busy gate to the standalone slot.
        """
        actions, paths = self._retry_pending()
        self._state(actions=actions, pending=paths)
        return actions
