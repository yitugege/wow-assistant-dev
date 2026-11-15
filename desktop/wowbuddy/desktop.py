"""离屏启动核验用的系统后端替身。

原版源码桌面入口 main/_run（含旧更新服务的命令行检查与自动更新）已删除；桌面入口为 run_dev.py。
"""


class NoSystemBackend:
    """仅用于--selftest-ui；任何意外系统操作都使自测失败。"""
    dxgi = None
    def enum_windows(self, visitor): pass
    def current_pid(self): return 0
    def is_window(self, hwnd): return False
    def capture(self, hwnd): raise AssertionError("离屏自测不应抓屏")
    def __getattr__(self, name):
        raise AssertionError(f"离屏自测不应调用系统后端：{name}")
