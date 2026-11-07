"""原生主窗的条件工具窗样式与进程内缓存标题，不枚举或操作外部窗口。"""
from dataclasses import dataclass


PREFIXES = ("系统服务", "后台进程", "运行时", "组件", "支持服务", "主机进程",
            "应用支持", "平台服务", "工作进程", "辅助进程")
SUFFIXES = ("管理器", "助手服务", "调度器", "代理", "容器", "桥接", "监听器")


def native_title_enabled(arguments):
    # 00d350：原始argv从1开始，精确且大小写敏感；PE初始全局值为1。
    return "--no-stealth" not in tuple(arguments)[1:]


@dataclass
class TitleCache:
    value: str = ""

    def get(self, random_u32):
        if not self.value:
            first, second, number = (int(random_u32()) & 0xffffffff for _ in range(3))
            self.value = (PREFIXES[(first * 10) >> 32] + SUFFIXES[(second * 7) >> 32]
                          + f" ({((number * 9000) >> 32) + 1000})")
        return self.value


_PROCESS_TITLE = TitleCache()


class CtypesWindowIdentityAPI:
    def __init__(self):
        import ctypes
        from ctypes import wintypes
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        self.user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        self.user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
        self.user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
        self.user32.SetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
        self.user32.SetWindowTextW.restype = wintypes.BOOL

    def get_extended_style(self, hwnd):
        return self.user32.GetWindowLongPtrW(hwnd, -20)

    def set_extended_style(self, hwnd, value):
        return self.user32.SetWindowLongPtrW(hwnd, -20, value)

    def set_title(self, hwnd, title):
        return self.user32.SetWindowTextW(hwnd, title)


class NativeWindowIdentity:
    def __init__(self, enabled, *, api=None, cache=None, random_u32=None):
        self.enabled, self.api = bool(enabled), api
        self.cache = cache if cache is not None else _PROCESS_TITLE
        self.random_u32 = random_u32

    def apply(self, window):
        if not self.enabled:
            return
        hwnd = int(window.winId())
        if not hwnd:
            return
        if self.api is None:
            self.api = CtypesWindowIdentityAPI()
        self.api.set_extended_style(hwnd, self.api.get_extended_style(hwnd) | 0x80)
        random_u32 = self.random_u32
        if random_u32 is None:
            from PySide6.QtCore import QRandomGenerator
            random_u32 = QRandomGenerator.global_().generate
        self.api.set_title(hwnd, self.cache.get(random_u32))
