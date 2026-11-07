"""Recovered update protocol. Injected transports only; stops before replacement.

HTTP.start(request) starts an asynchronous request; its callbacks call finish_check,
download_data, download_progress, finish_download using the request id. HTTP.abort
only requests cancellation. This module creates no network client or real files.
"""
from dataclasses import dataclass, replace
from typing import Protocol, Iterable, Mapping
import hashlib
import math
import ntpath
import re

from .expressions import _trim
from .qt_utf8 import decode_qt_utf8

CURRENT_VERSION = "1.0.38"
DEFAULT_UPDATE_URL = "https://wowbuddy.cn/data/latest.json"
USER_AGENT = "WOWBattleAssistant"
CHECK_TIMEOUT_MS = 15000
DEVELOPMENT_ERROR = "当前是开发模式（没有通过单文件引导器启动），无法自动替换程序；请到官网下载新版安装包"
TIMEOUT_ERROR = "检查更新超时（网络不通或站点无响应）"


class UpdateFS(Protocol):
    def read_first_line(self, path: str) -> bytes: ...
    def is_file(self, path: str) -> bool: ...
    def probe_write(self, path: str) -> bool: ...
    def remove(self, path: str) -> bool: ...
    def open_write(self, path: str): ...  # write(bytes), flush(), close(); OSError on failure
    def size(self, path: str) -> int: ...
    def read_chunks(self, path: str, chunk_size: int) -> Iterable[bytes]: ...


@dataclass(frozen=True)
class UpdateRequest:
    id: int
    kind: str
    url: str
    headers: Mapping[str, str]
    qt_attributes: Mapping[int, int]
    timeout_ms: int | None


class UpdateHTTP(Protocol):
    def start(self, request: UpdateRequest) -> None: ...
    def abort(self, request_id: int) -> None: ...


@dataclass(frozen=True)
class UpdateResponse:
    body: bytes = b""
    error_code: int = 0  # Qt NetworkError; 5 == OperationCanceledError
    error_text: str = ""


@dataclass(frozen=True)
class UpdateInfo:
    ok: bool = False
    error: str = ""
    current_version: str = CURRENT_VERSION
    version: str = ""
    date: str = ""
    size: int = 0
    sha256: str = ""
    download_url: str = ""
    channel: str = ""
    note: str = ""

    @property
    def has_update(self):
        return self.ok and bool(self.version) and compare_versions(self.version, self.current_version) > 0


@dataclass(frozen=True)
class UpdateUIState:
    phase: str = "idle"
    text: str = ""
    color: str = "#7c8ba8"
    check_enabled: bool = True
    update_enabled: bool = True
    update_visible: bool = False
    update_text: str = ""
    update_tooltip: str = ""
    progress_visible: bool = False
    progress_value: int = 0
    progress_range: tuple[int, int] = (0, 100)
    auto_download_requested: bool = False
    last_check_ms: int | None = None
    logs: tuple[str, ...] = ()


@dataclass(frozen=True)
class VerifiedDownload:
    part_path: str
    target_path: str
    info: UpdateInfo
    actual_size: int
    actual_sha256: str | None


def resolve_update_url(env, application_dir, fs):
    override = env.get("WOWBUDDY_UPDATE_URL", "")
    if override:
        return override  # Native does not trim this override.
    try:
        line = fs.read_first_line(ntpath.join(application_dir, "update_url.txt"))
    except OSError:
        line = b""
    line = _trim(decode_qt_utf8(line))
    if line and not line.startswith("#"):
        return line
    return DEFAULT_UPDATE_URL


def resolve_target_path(env):
    if env.get("WOWBUDDY_EXE", ""):
        return env["WOWBUDDY_EXE"].replace("/", "\\")
    if env.get("WOWBUDDY_HOME", ""):
        return ntpath.join(env["WOWBUDDY_HOME"], "WOW战斗助手.exe").replace("/", "\\")
    return ""


def replacement_blocker(target_path, fs):
    if not target_path:
        return DEVELOPMENT_ERROR
    if not fs.is_file(target_path):
        return f"找不到要替换的程序文件：{target_path}"
    directory = ntpath.dirname(ntpath.abspath(target_path))
    try:
        writable = fs.probe_write(ntpath.join(directory, "wowbuddy_write_test.tmp"))
    except OSError:
        writable = False
    if not writable:
        # 原QFileInfo.absolutePath在Windows也使用正斜杠显示目录。
        display_directory = directory.replace("\\", "/")
        return f"程序所在目录不可写，无法自动更新：{display_directory}\n请手动下载新版"
    return ""


def part_file_path(target_path):
    # QFileInfo.completeBaseName removes only the final suffix.
    directory, name = ntpath.split(ntpath.abspath(target_path))
    base = name.rsplit(".", 1)[0] if "." in name else name
    return ntpath.join(directory, base + ".update.part")


def version_segments(version):
    # 0x1400b6b50：逐 UTF-16 字元积累数字段，分隔或结尾时 toLongLong。
    # QChar iterates UTF-16 units: supplementary-plane digit codepoints are NOT digits here.
    normalized = "".join(c if ord(c) <= 0xffff and c.isdecimal() else "." for c in version)
    result = []
    for group in re.findall(r"\d+", normalized):
        # QString::toLongLong uses C-locale ASCII parsing; failed/overflow conversion is zero.
        digits = group.lstrip("0") or "0"
        number = int(digits) if group.isascii() and len(digits) <= 19 else 0
        result.append(number if number <= 0x7fffffffffffffff else 0)
    return tuple(result)


def compare_versions(left, right):
    a, b = version_segments(left), version_segments(right)
    for i in range(max(len(a), len(b))):
        x, y = (a[i] if i < len(a) else 0), (b[i] if i < len(b) else 0)
        if x != y:
            return 1 if x > y else -1
    return 0


def download_url(manifest_url, file):
    if file.startswith(("http://", "https://")):
        return file
    suffix = "/data/latest.json"
    if manifest_url.endswith(suffix):
        base = manifest_url[:-len(suffix)]
    else:
        index = manifest_url.rfind("/")
        base = manifest_url[:index] if index > 0 else manifest_url
    return base.rstrip("/") + "/" + file.lstrip("/")


def _string(value, default=""):
    return value if isinstance(value, str) else default


def parse_manifest(body, manifest_url, current_version=CURRENT_VERSION):
    # 0x1400b5340：app 默认项、首个 infinite 覆盖项及清单字段/错误优先级。
    # The installed Qt parser preserves native parse errors and object/array distinction.
    from PySide6.QtCore import QJsonDocument, QJsonParseError, QLocale
    error = QJsonParseError()
    document = QJsonDocument.fromJson(body, error)
    if error.error != QJsonParseError.ParseError.NoError or not document.isObject():
        return UpdateInfo(error="版本清单不是合法 JSON：" + error.errorString(), current_version=current_version)
    root = document.object()
    app = root.get("app")
    app = app if isinstance(app, dict) else {}
    channel = "通用"
    clients = root.get("clients")
    for client in clients if isinstance(clients, list) else []:
        if isinstance(client, dict) and _string(client.get("id")) == "infinite":
            app = client
            channel = _string(client.get("name"), "无限服")
            break
    value = app.get("size", 0)
    number = float(value) if isinstance(value, (float, int)) and not isinstance(value, bool) else 0.0
    size = int(number) if math.isfinite(number) and -2**63 <= number < 2**63 else -2**63
    version = _trim(_string(app.get("version")))
    file = _string(app.get("file"))
    url = download_url(manifest_url, file) if file else ""
    error_text = ""
    if not version:
        error_text = "版本清单里没有 version 字段（地址对吗？）"
    elif not url:
        error_text = "版本清单里没有可下载的文件（file 字段为空）"
    return UpdateInfo(not error_text, error_text, current_version, version,
                      _string(app.get("date")), size, QLocale.c().toLower(_trim(_string(app.get("sha256")))),
                      url, channel, _string(app.get("note")))


def format_size(value):
    from PySide6.QtCore import QLocale
    if value < 1024:
        return f"{value} B"
    if value < 1048576:
        return QLocale.c().toString(value / 1024, "f", 0) + " KB"
    return QLocale.c().toString(value / 1048576, "f", 1) + " MB"


def checked_ui(info, previous=None, *, manual, auto_update, blocker="", now_ms=None, time_text=""):
    """0x1400912f0：完成检查后的按钮、状态、时间及自动下载分支。"""
    state = previous or UpdateUIState()
    state = replace(state, check_enabled=True, progress_visible=False,
                    auto_download_requested=False, logs=())
    if not info.ok:
        return replace(state, phase="check_failed", text=info.error, color="#ffb02e",
                       logs=(f"检查更新失败：{info.error}",) if manual else ())
    state = replace(state, last_check_ms=now_ms)
    if not info.has_update:
        return replace(state, phase="current", color="#7c8ba8", update_visible=False,
                       text=f"当前 v{info.current_version} · 已是最新（{time_text}）",
                       logs=(f"已是最新版本（v{info.current_version}）",) if manual else ())
    text = (f"发现新版本 v{info.version}（当前 v{info.current_version} · {info.date} 发布 · {format_size(info.size)}）"
            + ("\n" + blocker if blocker else ""))
    log = f"★ 发现新版本 v{info.version}（当前 v{info.current_version}）" + ("：" + blocker if blocker else "，将自动更新")
    return replace(state, phase="available", text=text, color="#00e5ff", update_visible=True,
                   update_enabled=not blocker, update_text=f"更新到 v{info.version}",
                   update_tooltip=blocker, auto_download_requested=not manual and auto_update and not blocker,
                   logs=(log,))


class Updater:
    def __init__(self, http: UpdateHTTP, fs: UpdateFS, *, env, application_dir,
                 current_version=CURRENT_VERSION):
        self.http, self.fs, self.env = http, fs, env
        self.application_dir, self.current_version = application_dir, current_version
        self.info = UpdateInfo(current_version=current_version)
        self.ui = UpdateUIState()
        self.active = None
        self._sequence = 0
        self._manual = False
        self._cancelled = False
        self._file = None
        self._write_error = ""
        self.part_path = self.target_path = ""
        self.verified = None

    @property
    def busy(self):
        return self.active is not None

    def _request(self, kind, url):
        self._sequence += 1
        headers = {"User-Agent": USER_AGENT}
        attrs = {22: 1}  # RedirectPolicyAttribute: NoLessSafeRedirectPolicy
        if kind == "check":
            headers.update({"Cache-Control": "no-cache", "Pragma": "no-cache"})
            attrs[4] = 0  # CacheLoadControlAttribute: AlwaysNetwork
        request = UpdateRequest(self._sequence, kind, url, headers, attrs,
                                CHECK_TIMEOUT_MS if kind == "check" else None)
        self.active = request
        self.http.start(request)
        return request

    def start_check(self, *, manual=True):
        if self.busy:
            return None
        self.info = UpdateInfo(current_version=self.current_version)
        self._manual, self._cancelled = manual, False
        self.verified = None
        # Automatic text is immediately replaced by updater status signal, as native does.
        self.ui = replace(self.ui, phase="checking", text="正在检查更新…", color="#00e5ff",
                          check_enabled=False, progress_visible=False if manual else self.ui.progress_visible,
                          auto_download_requested=False, logs=())
        return self._request("check", resolve_update_url(self.env, self.application_dir, self.fs))

    def _matches(self, request_id, kind):
        return self.active is not None and self.active.id == request_id and self.active.kind == kind

    def check_timeout(self, request_id):
        if self._matches(request_id, "check"):
            self.http.abort(request_id)  # Completion error 5 supplies native timeout message.

    def finish_check(self, request_id, response, *, auto_update=False, now_ms=None, time_text=""):
        if not self._matches(request_id, "check"):
            return None
        self.active = None
        if response.error_code:
            error = TIMEOUT_ERROR if response.error_code == 5 else "检查更新失败：" + response.error_text
            self.info = UpdateInfo(error=error, current_version=self.current_version)
        else:
            # Native resolves overrides again during parse, instead of using reply.url().
            url = resolve_update_url(self.env, self.application_dir, self.fs)
            self.info = parse_manifest(response.body, url, self.current_version)
        blocker = replacement_blocker(resolve_target_path(self.env), self.fs) if self.info.has_update else ""
        self.ui = checked_ui(self.info, self.ui, manual=self._manual, auto_update=auto_update,
                             blocker=blocker, now_ms=now_ms, time_text=time_text)
        return self.info

    def start_download(self):
        if self.busy:
            return None
        if not self.info.has_update:
            self._failed("当前没有可用的新版本")
            return None
        self.target_path = resolve_target_path(self.env)
        blocker = replacement_blocker(self.target_path, self.fs)
        if blocker:
            self._failed(blocker)
            return None
        self.part_path = part_file_path(self.target_path)
        self.fs.remove(self.part_path)  # Injected FS only; old .part is not resumed.
        try:
            self._file = self.fs.open_write(self.part_path)
        except OSError as error:
            self._failed(f"无法创建临时文件（{self.part_path}）：{error}")
            return None
        self._cancelled, self._write_error, self.verified = False, "", None
        self.ui = replace(self.ui, phase="downloading", text=f"正在下载 v{self.info.version}…",
                          color="#00e5ff", check_enabled=False, update_enabled=False,
                          progress_visible=True, progress_value=0, auto_download_requested=False, logs=())
        request = self._request("download", self.info.download_url)
        self.download_progress(request.id, 0, self.info.size)
        return request

    def download_data(self, request_id, data):
        if not self._matches(request_id, "download") or self._file is None:
            return False
        try:
            # 原readyRead及finished均忽略write返回长度；由文件错误/最终大小与哈希决定结果。
            self._file.write(data)
        except OSError as error:
            self._write_error = str(error)
        return True

    def download_progress(self, request_id, received, total):
        if not self._matches(request_id, "download"):
            return None
        effective_total = total if total > 0 else self.info.size
        self.ui = replace(self.ui, progress_visible=True)
        if effective_total > 0:
            percent = abs(received * 100) // effective_total * (-1 if received < 0 else 1)
            # QProgressBar rejects out-of-range setValue rather than clamping.
            value = percent if 0 <= percent <= 100 else self.ui.progress_value
            self.ui = replace(self.ui, progress_range=(0, 100), progress_value=value,
                              text=f"正在下载… {format_size(received)} / {format_size(effective_total)}")
        return received, effective_total

    def cancel(self):
        if self.active is not None:
            self._cancelled = True
            self.http.abort(self.active.id)

    def _close_file(self):
        if self._file is not None:
            try:
                self._file.close()
            except OSError as error:
                self._write_error = str(error)
            self._file = None

    def _failed(self, text, *, cleanup=False):
        self._close_file()
        if cleanup and self.part_path:
            self.fs.remove(self.part_path)
        self.active = None
        self._cancelled = False
        self.ui = replace(self.ui, phase="download_failed", text=text, color="#ffb02e",
                          check_enabled=True, update_enabled=True, progress_visible=False,
                          auto_download_requested=False, logs=("自动更新未完成：" + text,))

    def finish_download(self, request_id, response):
        if not self._matches(request_id, "download"):
            return None
        if self._cancelled or response.error_code == 5:
            self._failed("已取消更新", cleanup=True)
            return None
        if response.error_code:
            self._failed("下载失败：" + response.error_text, cleanup=True)
            return None
        self.download_data(request_id, response.body)
        try:
            self._file.flush()
        except OSError as error:
            self._write_error = str(error)
        self._close_file()
        if self._write_error:
            self._failed("写入失败：" + self._write_error, cleanup=True)
            return None
        self.ui = replace(self.ui, phase="verifying", text="正在校验安装包…", color="#00e5ff")
        try:
            size = self.fs.size(self.part_path)
        except OSError:
            size = 0  # QFileInfo::size on an unavailable file.
        if self.info.size > 0 and size != self.info.size:
            self._failed(f"安装包大小不符（期望 {self.info.size} 字节，实际 {size}），已放弃更新", cleanup=True)
            return None
        digest = None
        if self.info.sha256:
            try:
                hash_state = hashlib.sha256()
                for chunk in self.fs.read_chunks(self.part_path, 0x100000):
                    hash_state.update(chunk)
                digest = hash_state.hexdigest()
            except OSError:
                self._failed("无法读取下载的安装包", cleanup=True)
                return None
            if digest.lower() != self.info.sha256.lower():
                self._failed(f"安装包校验值不符（期望 {self.info.sha256[:12]}…，实际 {digest[:12]}…），已放弃更新", cleanup=True)
                return None
        self.verified = VerifiedDownload(self.part_path, self.target_path, self.info, size, digest)
        self.active = None
        # Deliberate reconstruction boundary: no native 'replacing'/'updated' success claim.
        self.ui = replace(self.ui, phase="verified", text="安装包校验完成，尚未替换程序文件",
                          check_enabled=True, update_enabled=False, progress_visible=False, logs=())
        return self.verified
