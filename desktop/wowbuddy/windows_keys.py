"""原生三路按键发送恢复；仅显式构造 CtypesWin32Backend 后才连接 Win32。

KeySender 不自动创建后端。测试应注入 fake backend。原版部分 SendInput
失败时不补发释放事件，本模块保留该行为，详见 evidence/按键通道.md。
"""
from __future__ import annotations

import ctypes as C
from dataclasses import dataclass
import os
import time
from typing import Protocol

from .keybindings import KeyBinding, is_extended_key, parse_keybinding


class Unsupported(NotImplementedError):
    """未恢复或目标 ABI 不支持的调用路径。"""


@dataclass(frozen=True, slots=True)
class KeyboardInput:
    vk: int
    scan: int
    flags: int


class Win32Backend(Protocol):
    def now_ms(self) -> int: ...
    def Sleep(self, milliseconds: int) -> None: ...
    def MapVirtualKeyW(self, vk: int, mapping: int) -> int: ...
    def SendInput(self, events: tuple[KeyboardInput, ...]) -> int: ...
    def PostMessageW(self, hwnd: int, msg: int, vk: int, lparam: int) -> int: ...
    def IsWindow(self, hwnd: int) -> int: ...
    def GetForegroundWindow(self) -> int: ...
    def GetAncestor(self, hwnd: int, flags: int) -> int: ...
    def GetCurrentThreadId(self) -> int: ...
    def GetWindowThreadProcessId(self, hwnd: int) -> int: ...
    def AttachThreadInput(self, source: int, target: int, attach: bool) -> int: ...
    def IsIconic(self, hwnd: int) -> int: ...
    def ShowWindow(self, hwnd: int, command: int) -> int: ...
    def BringWindowToTop(self, hwnd: int) -> int: ...
    def SetForegroundWindow(self, hwnd: int) -> int: ...
    def SetActiveWindow(self, hwnd: int) -> int: ...
    def SetFocus(self, hwnd: int) -> int: ...


# 固定宽度类型，避免非 Windows 主机的 c_ulong 尺寸改变布局。
class KEYBDINPUT(C.Structure):
    _fields_ = [('wVk', C.c_uint16), ('wScan', C.c_uint16),
                ('dwFlags', C.c_uint32), ('time', C.c_uint32),
                ('dwExtraInfo', C.c_size_t)]


class MOUSEINPUT(C.Structure):
    _fields_ = [('dx', C.c_int32), ('dy', C.c_int32),
                ('mouseData', C.c_uint32), ('dwFlags', C.c_uint32),
                ('time', C.c_uint32), ('dwExtraInfo', C.c_size_t)]


class HARDWAREINPUT(C.Structure):
    _fields_ = [('uMsg', C.c_uint32), ('wParamL', C.c_uint16), ('wParamH', C.c_uint16)]


class INPUTUNION(C.Union):
    _fields_ = [('ki', KEYBDINPUT), ('mi', MOUSEINPUT), ('hi', HARDWAREINPUT)]


class INPUT(C.Structure):
    _anonymous_ = ('data',)
    _fields_ = [('type', C.c_uint32), ('data', INPUTUNION)]


class CtypesWin32Backend:
    """真实 Win32 后端；构造仅绑定函数，调用发送方法才产生输入。

    原目标为 Windows x64。其他 OS/位数明确拒绝，不模拟成功。
    """
    def __init__(self):
        if os.name != 'nt' or C.sizeof(C.c_void_p) != 8 or C.sizeof(INPUT) != 40:
            raise Unsupported('仅恢复 Windows x64 INPUT ABI')
        self._user32 = C.WinDLL('user32', use_last_error=True)
        self._kernel32 = C.WinDLL('kernel32', use_last_error=True)
        hwnd, uint, boolean = C.c_void_p, C.c_uint32, C.c_int32
        signatures = {
            'MapVirtualKeyW': (uint, [uint, uint]),
            'PostMessageW': (boolean, [hwnd, uint, C.c_size_t, C.c_ssize_t]),
            'IsWindow': (boolean, [hwnd]), 'GetForegroundWindow': (hwnd, []),
            'GetAncestor': (hwnd, [hwnd, uint]),
            'AttachThreadInput': (boolean, [uint, uint, boolean]),
            'IsIconic': (boolean, [hwnd]), 'ShowWindow': (boolean, [hwnd, C.c_int]),
            'BringWindowToTop': (boolean, [hwnd]),
            'SetForegroundWindow': (boolean, [hwnd]),
            'SetActiveWindow': (hwnd, [hwnd]), 'SetFocus': (hwnd, [hwnd]),
        }
        for name, (result, args) in signatures.items():
            function = getattr(self._user32, name)
            function.restype, function.argtypes = result, args
            setattr(self, name, function)
        self._send = self._user32.SendInput
        self._send.restype, self._send.argtypes = uint, [uint, C.POINTER(INPUT), C.c_int]
        self._thread = self._user32.GetWindowThreadProcessId
        self._thread.restype, self._thread.argtypes = uint, [hwnd, C.POINTER(uint)]
        self.GetCurrentThreadId = self._kernel32.GetCurrentThreadId
        self.GetCurrentThreadId.restype, self.GetCurrentThreadId.argtypes = uint, []
        self.Sleep = self._kernel32.Sleep
        self.Sleep.restype, self.Sleep.argtypes = None, [uint]

    def GetWindowThreadProcessId(self, hwnd: int) -> int:
        return int(self._thread(hwnd, None))

    def SendInput(self, events: tuple[KeyboardInput, ...]) -> int:
        array = (INPUT * len(events))()
        for item, event in zip(array, events):
            item.type = 1
            item.ki = KEYBDINPUT(event.vk, event.scan, event.flags, 0, 0)
        return int(self._send(len(events), array, C.sizeof(INPUT)))

    @staticmethod
    def now_ms() -> int:
        return time.time_ns() // 1_000_000


def is_foreground(backend: Win32Backend, hwnd: int) -> bool:
    """0a99c0：比较 GA_ROOT，而非直接比较传入的 HWND。"""
    foreground = backend.GetForegroundWindow()
    return bool(foreground) and backend.GetAncestor(foreground, 2) == backend.GetAncestor(hwnd, 2)


def send_input(backend: Win32Backend, binding: KeyBinding, hold_ms: int) -> bool:
    """0ab770：两批 INPUT，第一批不足时原版直接返回失败。"""
    if not binding.valid:
        return False
    def event(vk: int, up: bool) -> KeyboardInput:
        return KeyboardInput(vk & 0xffff, backend.MapVirtualKeyW(vk, 0) & 0xffff,
                             int(is_extended_key(vk)) | (2 if up else 0))
    down = tuple(event(vk, False) for vk in (*binding.modifiers, binding.vk))
    up = tuple(event(vk, True) for vk in (binding.vk, *reversed(binding.modifiers)))
    if backend.SendInput(down) != len(down):
        return False
    backend.Sleep(max(20, min(120, C.c_int32(hold_ms).value)))
    return backend.SendInput(up) == len(up)


def post_message(backend: Win32Backend, hwnd: int, binding: KeyBinding) -> bool:
    """0aa7e0：固定 lParam，不包含扫描码、extended 或 ALT context 位。"""
    if not binding.valid or not hwnd or not backend.IsWindow(hwnd):
        return False
    ok = True
    for vk in (*binding.modifiers, binding.vk):
        result = backend.PostMessageW(hwnd, 0x100, vk, 1)
        ok = bool(result) and ok
    backend.Sleep(10)
    for vk in (binding.vk, *reversed(binding.modifiers)):
        result = backend.PostMessageW(hwnd, 0x101, vk, 0xc0000001)
        ok = bool(result) and ok
    return ok


def activate_and_send(backend: Win32Backend, hwnd: int, binding: KeyBinding,
                      hold_ms: int) -> tuple[bool, str]:
    """0ab270：临时激活，在仍为前台时恢复旧窗口，按逆序解除线程附加。"""
    if not binding.valid:
        return False, binding.error
    if not hwnd or not backend.IsWindow(hwnd):
        return False, '游戏窗口已失效'
    if is_foreground(backend, hwnd):
        ok = send_input(backend, binding, hold_ms)
        return ok, '前台按键已发送' if ok else '前台按键发送失败'
    previous = backend.GetForegroundWindow()
    current_thread = backend.GetCurrentThreadId()
    target_thread = backend.GetWindowThreadProcessId(hwnd)
    previous_thread = backend.GetWindowThreadProcessId(previous) if previous else 0
    attached_target = attached_previous = False
    try:
        if target_thread and target_thread != current_thread:
            attached_target = bool(backend.AttachThreadInput(current_thread, target_thread, True))
        if previous_thread and previous_thread not in (current_thread, target_thread):
            attached_previous = bool(backend.AttachThreadInput(current_thread, previous_thread, True))
        if backend.IsIconic(hwnd):
            backend.ShowWindow(hwnd, 9)
        backend.BringWindowToTop(hwnd)
        backend.SetForegroundWindow(hwnd)
        backend.SetActiveWindow(hwnd)
        backend.SetFocus(hwnd)
        backend.Sleep(15)
        if not is_foreground(backend, hwnd):
            return False, '无法把游戏窗口激活到前台'
        ok = send_input(backend, binding, hold_ms)
        return ok, '已临时激活游戏窗口并发送真实按键' if ok else '激活成功但按键发送失败'
    finally:
        try:
            if previous and backend.IsWindow(previous) and is_foreground(backend, hwnd):
                backend.BringWindowToTop(previous)
                backend.SetForegroundWindow(previous)
        finally:
            try:
                if attached_previous:
                    backend.AttachThreadInput(current_thread, previous_thread, False)
            finally:
                if attached_target:
                    backend.AttachThreadInput(current_thread, target_thread, False)


class KeySender:
    """0aab70 路由及计数；配置显式传入，不猜测构造器默认值。

    force_background 对应 +0，allow_activation 对应 +1；后者为假时，
    非前台走后台投递。bypass_interval 对应原 param_3（焦点前置键用）。
    """
    def __init__(self, backend: Win32Backend, *, hwnd: int, force_background: bool,
                 allow_activation: bool, interval_ms: int, hold_ms: int):
        self.backend, self.hwnd = backend, hwnd
        self.force_background, self.allow_activation = force_background, allow_activation
        self.interval_ms, self.hold_ms = interval_ms, hold_ms
        self.last_send_ms = 0
        self.success_count = self.failure_count = 0
        self.status = self.channel = ''

    def send(self, value: str, *, bypass_interval: bool = False) -> bool:
        binding = parse_keybinding(value)
        if not binding.valid:
            self.failure_count += 1
            self.status = binding.error
            return False
        now = self.backend.now_ms()
        elapsed = now - self.last_send_ms
        if not bypass_interval and self.last_send_ms and elapsed < self.interval_ms:
            self.status = f'限速跳过（距上次 {elapsed}ms < {self.interval_ms}ms）'
            return False
        if self.force_background:
            route = 'post'
        elif is_foreground(self.backend, self.hwnd):
            route = 'input'
        else:
            route = 'activate' if self.allow_activation else 'post'
        if route == 'post':
            ok = post_message(self.backend, self.hwnd, binding)
            self.status = '后台按键已发送' if ok else '后台按键发送失败'
            self.channel = '后台投递'
        elif route == 'input':
            ok = send_input(self.backend, binding, self.hold_ms)
            self.status = '前台真实按键已发送' if ok else '前台按键发送失败'
            self.channel = '前台真实按键'
        elif route == 'activate':
            ok, self.status = activate_and_send(self.backend, self.hwnd, binding, self.hold_ms)
            self.channel = '临时激活（会闪）'
        else:
            raise Unsupported(route)
        if ok:
            self.last_send_ms = now
            self.success_count += 1
        else:
            self.failure_count += 1
        return ok
