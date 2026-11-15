"""只在目标游戏位于前台且坐标属于该窗口时发送鼠标输入。"""

import ctypes as C
from ctypes import wintypes as W

from .game_windows import GAME_EXECUTABLES, executable_name
from .windows_keys import INPUT, MOUSEINPUT, is_foreground


class Win32Mouse:
    def __init__(self, window_backend, process_backend):
        self.windows = window_backend
        self.processes = process_backend
        self.user = C.WinDLL('user32', use_last_error=True)
        for name, result, args in (
                ('GetCursorPos', W.BOOL, (C.POINTER(W.POINT),)),
                ('SetCursorPos', W.BOOL, (C.c_int, C.c_int)),
                ('WindowFromPoint', W.HWND, (W.POINT,)),
                ('GetAsyncKeyState', C.c_int16, (C.c_int,)),
                ('SendInput', W.UINT, (W.UINT, C.POINTER(INPUT), C.c_int))):
            function = getattr(self.user, name)
            function.restype, function.argtypes = result, args

    def in_foreground(self, hwnd):
        return bool(self.windows.IsWindow(hwnd) and is_foreground(self.windows, hwnd))

    def _can_point(self, hwnd, point):
        if not self.in_foreground(hwnd):
            return False
        pid = self.processes.window_pid(hwnd)
        if not pid or executable_name(self.processes.process_path(pid)) not in GAME_EXECUTABLES:
            return False
        if any(self.user.GetAsyncKeyState(key) & 0x8000 for key in (1, 2, 4, 0x10, 0x11, 0x12)):
            return False
        target = self.user.WindowFromPoint(W.POINT(*point))
        root = self.windows.GetAncestor(hwnd, 2)
        return bool(target and root and self.windows.GetAncestor(target, 2) == root)

    def move(self, hwnd, point):
        return self._can_point(hwnd, point) and bool(self.user.SetCursorPos(*point))

    def click(self, hwnd, point):
        cursor = W.POINT()
        if (not self._can_point(hwnd, point) or not self.user.GetCursorPos(C.byref(cursor))
                or (cursor.x, cursor.y) != point):
            return False
        events = (INPUT * 2)()
        events[0].mi = MOUSEINPUT(0, 0, 0, 0x0002, 0, 0)
        events[1].mi = MOUSEINPUT(0, 0, 0, 0x0004, 0, 0)
        sent = self.user.SendInput(2, events, C.sizeof(INPUT))
        if sent == 1:
            self.user.SendInput(1, C.byref(events[1]), C.sizeof(INPUT))
        return sent == 2
