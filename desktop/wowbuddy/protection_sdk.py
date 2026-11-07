"""原外层0x2fd0的Win32 SDK加载后端；显式调用才加载，不主动卸载。"""
from __future__ import annotations

import ctypes as C
import os
from .launcher_host import SDKExports, run_protection_worker


class WindowsSDKLoader:
    """保持LoadLibraryW裸名称、三个导出查找顺序和模块引用生命周期。"""
    def __init__(self):
        if os.name != 'nt':
            raise OSError('保护SDK加载仅支持Windows')
        self.kernel = C.WinDLL('kernel32', use_last_error=True)
        self.kernel.LoadLibraryW.argtypes = [C.c_wchar_p]
        self.kernel.LoadLibraryW.restype = C.c_void_p
        self.kernel.GetProcAddress.argtypes = [C.c_void_p, C.c_char_p]
        self.kernel.GetProcAddress.restype = C.c_void_p
        self.module = None
        self.addresses = ()
        self._loaded = False

    def load(self) -> SDKExports | None:
        if self._loaded:
            raise RuntimeError('每个保护线程只加载一次SDK')
        self._loaded = True
        # 不使用ctypes.WinDLL(文件名)：其现代默认加载标志与原LoadLibraryW不同。
        self.module = self.kernel.LoadLibraryW('SProtectSDK64.dll')
        if not self.module:
            return None
        self.addresses = tuple(self.kernel.GetProcAddress(self.module, name) for name in
                               (b'SPIsProtected', b'SPCheckDebugger', b'SPCrc'))
        prototype = C.WINFUNCTYPE(C.c_uint64)
        return SDKExports(*(prototype(address) if address else None for address in self.addresses))


def run_windows_protection_worker(*, sleep_ms, terminate):
    """线程调用入口；终止/休眠由宿主提供。加载失败按原版正常返回。"""
    loader = WindowsSDKLoader()
    return run_protection_worker(loader.load(), sleep_ms=sleep_ms, terminate=terminate)
