"""窗口枚举/选择及自动监视核心；不含捕获、UI、启动或关闭进程。

Win32 后端和监视运行时均需显式注入。MonitorRuntime 承接已有监视器的
启动/停止副作用；这里不把日志文件、捕获缓存和 UI 更新伪装成已实现。
"""
from __future__ import annotations

import ctypes as C
from dataclasses import dataclass
import os
from typing import Callable, Protocol


class Unsupported(NotImplementedError):
    pass


@dataclass(frozen=True, slots=True)
class TitleResult:
    succeeded: bool
    text: str = ''


class WindowBackend(Protocol):
    def enum_windows(self, visitor: Callable[[int], None]) -> None: ...
    def is_visible(self, hwnd: int) -> bool: ...
    def is_window(self, hwnd: int) -> bool: ...
    def window_pid(self, hwnd: int) -> int: ...
    def current_pid(self) -> int: ...
    def window_title(self, hwnd: int) -> TitleResult: ...
    def process_path(self, pid: int) -> str: ...


class CtypesWindowBackend:
    """只读 Win32 实现；显式构造才绑定 DLL，不会调用窗口激活接口。"""
    def __init__(self):
        if os.name != 'nt' or C.sizeof(C.c_void_p) != 8:
            raise Unsupported('仅恢复 Windows x64 窗口接口')
        self._user = C.WinDLL('user32', use_last_error=True)
        self._kernel = C.WinDLL('kernel32', use_last_error=True)
        self._enum_proc = C.WINFUNCTYPE(C.c_int32, C.c_void_p, C.c_ssize_t)
        signatures = {
            'EnumWindows': (C.c_int32, [self._enum_proc, C.c_ssize_t]),
            'IsWindowVisible': (C.c_int32, [C.c_void_p]),
            'IsWindow': (C.c_int32, [C.c_void_p]),
            'GetWindowThreadProcessId': (C.c_uint32, [C.c_void_p, C.POINTER(C.c_uint32)]),
            'SendMessageTimeoutW': (C.c_ssize_t, [C.c_void_p, C.c_uint32, C.c_size_t,
                C.c_ssize_t, C.c_uint32, C.c_uint32, C.POINTER(C.c_size_t)]),
        }
        for name, (restype, args) in signatures.items():
            function = getattr(self._user, name)
            function.restype, function.argtypes = restype, args
        signatures = {
            'GetCurrentProcessId': (C.c_uint32, []),
            'OpenProcess': (C.c_void_p, [C.c_uint32, C.c_int32, C.c_uint32]),
            'QueryFullProcessImageNameW': (C.c_int32, [C.c_void_p, C.c_uint32,
                C.POINTER(C.c_wchar), C.POINTER(C.c_uint32)]),
            'CloseHandle': (C.c_int32, [C.c_void_p]),
        }
        for name, (restype, args) in signatures.items():
            function = getattr(self._kernel, name)
            function.restype, function.argtypes = restype, args

    def enum_windows(self, visitor: Callable[[int], None]) -> None:
        errors = []
        @self._enum_proc
        def visit(hwnd, _):
            try:
                visitor(int(hwnd or 0))
            except BaseException as error:
                errors.append(error)
                return 0
            return 1
        # 原入口忽略 EnumWindows 返回值，保留已枚举的前缀。
        self._user.EnumWindows(visit, 0)
        if errors:
            raise errors[0]

    def is_visible(self, hwnd: int) -> bool:
        return bool(self._user.IsWindowVisible(hwnd))

    def is_window(self, hwnd: int) -> bool:
        return bool(self._user.IsWindow(hwnd))

    def window_pid(self, hwnd: int) -> int:
        pid = C.c_uint32(0)
        self._user.GetWindowThreadProcessId(hwnd, C.byref(pid))
        return pid.value

    def current_pid(self) -> int:
        return int(self._kernel.GetCurrentProcessId())

    def window_title(self, hwnd: int) -> TitleResult:
        buffer = C.create_unicode_buffer(512)
        result = C.c_size_t(0)
        succeeded = self._user.SendMessageTimeoutW(
            hwnd, 0x0d, 0x1ff, C.addressof(buffer), 3, 120, C.byref(result))
        return TitleResult(bool(succeeded), buffer.value if succeeded else '')

    def process_path(self, pid: int) -> str:
        handle = self._kernel.OpenProcess(0x1000, 0, pid)
        if not handle:
            return ''
        try:
            buffer = C.create_unicode_buffer(1024)
            length = C.c_uint32(1024)
            if self._kernel.QueryFullProcessImageNameW(handle, 0, buffer, C.byref(length)):
                # 0B80C0 使用 API 返回的 UTF-16 长度，而非首个 NUL。
                return C.string_at(C.addressof(buffer), length.value * 2).decode('utf-16-le', 'surrogatepass')
            return ''
        finally:
            self._kernel.CloseHandle(handle)


def executable_name(path: str) -> str:
    """0b8010：仅按反斜杠取最后一段后转小写，不套用宿主路径规则。"""
    return path.rsplit('\\', 1)[-1].lower()


def _left_utf16(value: str, units: int) -> str:
    return value.encode('utf-16-le', 'surrogatepass')[:units * 2].decode('utf-16-le', 'surrogatepass')


@dataclass(frozen=True, slots=True)
class WindowInfo:
    hwnd: int
    title: str
    executable: str

    @property
    def kind(self) -> str:
        if 'wowb' in self.executable:
            return 'wowb'
        if 'wow' in self.executable:
            return 'wow'
        return 'other'

    @property
    def label(self) -> str:
        prefix = {'wowb': '★无限 ', 'wow': '★游戏 ', 'other': ''}[self.kind]
        return f'{prefix}[0x{self.hwnd:x}] {_left_utf16(self.title or self.executable, 42)}'


@dataclass(frozen=True, slots=True)
class Enumeration:
    windows: tuple[WindowInfo, ...]
    title_failures: int = 0

    @property
    def diagnostic(self) -> str:
        if self.title_failures:
            return (f'枚举窗口：{self.title_failures} 个窗口取标题超时（对方进程无响应），'
                    '已按 exe 名兜底、未连坐等待')
        return ''


def enumerate_windows(backend: WindowBackend, *,
                      on_diagnostic: Callable[[str], None] | None = None) -> Enumeration:
    """0b7f00/0b7930：所有可见且标题或 exe 非空的窗口，含自身有标题窗口。"""
    windows = []
    failures = 0
    def visit(hwnd: int) -> None:
        nonlocal failures
        if not backend.is_visible(hwnd):
            return
        pid = backend.window_pid(hwnd)
        result = backend.window_title(hwnd)
        title = result.text if result.succeeded else ''
        failures += not result.succeeded
        executable = ''
        if pid and pid != backend.current_pid():
            executable = executable_name(backend.process_path(pid))
        if title or executable:
            windows.append(WindowInfo(hwnd, title, executable))
    backend.enum_windows(visit)
    result = Enumeration(tuple(windows), failures)
    # 原0B7F00在整次枚举结束后经01CD40写startup日志，非080D60界面日志。
    if result.diagnostic and on_diagnostic is not None:
        on_diagnostic(result.diagnostic)
    return result


def is_own_window(backend: WindowBackend, hwnd: int) -> bool:
    pid = backend.window_pid(hwnd)
    return bool(pid) and pid == backend.current_pid()


def is_valid_window(backend: WindowBackend, hwnd: int) -> bool:
    return bool(hwnd) and backend.is_window(hwnd)


def preferred_game(windows: tuple[WindowInfo, ...]) -> int:
    """0b7af0：优先首个 wowb，否则首个 wow；只匹配 exe 子串。"""
    fallback = 0
    for window in windows:
        if window.kind == 'wowb':
            return window.hwnd
        if not fallback and window.kind == 'wow':
            fallback = window.hwnd
    return fallback


def find_game_window(backend: WindowBackend, *,
                     on_diagnostic: Callable[[str], None] | None = None) -> int:
    return preferred_game(enumerate_windows(backend, on_diagnostic=on_diagnostic).windows)


@dataclass(frozen=True, slots=True)
class WindowChoices:
    windows: tuple[WindowInfo, ...]
    selected_index: int
    title_failures: int = 0


def refresh_choices(backend: WindowBackend, *,
                    on_diagnostic: Callable[[str], None] | None = None) -> WindowChoices:
    """09ee50 的数据部分；再次检查 PID 排除本进程，不按 exe 过滤普通窗口。"""
    enumeration = enumerate_windows(backend, on_diagnostic=on_diagnostic)
    windows = tuple(w for w in enumeration.windows if not is_own_window(backend, w.hwnd))
    preferred = preferred_game(windows)
    selected = next((i for i, w in enumerate(windows) if w.hwnd == preferred), -1)
    if selected == -1 and windows:
        selected = 0  # QComboBox clear 后第一次 insert 的默认选择。
    return WindowChoices(windows, selected, enumeration.title_failures)


class MonitorRuntime(Protocol):
    """由集成层提供 0a2070 的实际副作用，核心绝不默认为已启动。

    start 应完成会话缓存重置、日志准备和监控计时器启动；stop 应停止计时器
    并关闭会话日志。UI/捕获如何实现不由这个窗口模块猜测。
    """
    def is_active(self) -> bool: ...
    def start(self, hwnd: int, interval_ms: int) -> None: ...
    def stop(self) -> None: ...


class WindowMonitor:
    """081970 的单次检查；由外部每 5000 ms 调 tick，不创建真实定时器。"""
    watch_interval_ms = 5000

    def __init__(self, backend: WindowBackend, runtime: MonitorRuntime, *,
                 interval_ms: int | None = None,
                 on_selection: Callable[['WindowMonitor', int], None] | None = None,
                 on_diagnostic: Callable[[str], None] | None = None):
        self.backend, self.runtime = backend, runtime
        self.interval_ms = 25 if interval_ms is None else interval_ms
        self.on_selection = on_selection
        self.on_diagnostic = on_diagnostic
        self.diagnostics: list[str] = []
        self.windows: tuple[WindowInfo, ...] = ()
        self.selected_index = -1
        self.target_hwnd = 0
        self.status = ''
        self.messages: list[str] = []

    def select(self, index: int) -> None:
        if not 0 <= index < len(self.windows):
            raise IndexError(index)
        changed = index != self.selected_index
        self.selected_index = index
        if changed and self.on_selection is not None:
            self.on_selection(self, index)

    def refresh(self) -> None:
        choices = refresh_choices(self.backend, on_diagnostic=self._diagnostic)
        self.windows, self.selected_index = choices.windows, choices.selected_index

    def _diagnostic(self, text: str) -> None:
        self.diagnostics.append(text)
        if self.on_diagnostic is not None:
            self.on_diagnostic(text)

    def toggle(self) -> None:
        if self.runtime.is_active():
            self.runtime.stop()
            self.status = '已停止'
            return
        selected = (self.windows[self.selected_index]
                    if 0 <= self.selected_index < len(self.windows) else None)
        if selected is None or not selected.hwnd:
            self.status = '请先选择一个目标窗口'
            return
        # 原手动启动仅拒绝零 HWND，不在此调用 IsWindow。
        self.target_hwnd = selected.hwnd
        self.runtime.start(selected.hwnd, self.interval_ms)
        self.messages.append(f'已开始监控 · 目标窗口 {selected.label}（0x{selected.hwnd:x}）')

    def tick(self) -> None:
        if self.runtime.is_active():
            if not self.target_hwnd or is_valid_window(self.backend, self.target_hwnd):
                return
            self.toggle()
            self.messages.append('自动监视：目标窗口已关闭，自动停止（游戏重启后会自动重连）')
            return  # 同一轮不立即连接另一窗口。
        hwnd = find_game_window(self.backend, on_diagnostic=self._diagnostic)
        if not hwnd:
            return
        index = next((i for i, w in enumerate(self.windows) if w.hwnd == hwnd), -1)
        if index < 0:
            self.refresh()
            index = next((i for i, w in enumerate(self.windows) if w.hwnd == hwnd), -1)
            if index < 0:
                return  # 两次枚举期间窗口可能消失。
        self.select(index)
        if not self.runtime.is_active():
            self.toggle()
        self.messages.append(f'自动监视：找到游戏窗口（0x{hwnd:x}），已自动开始监控')
