"""源码发布包外层入口：PE资源WBD1→原生释放/启动核心→独立业务EXE。"""
import os
from pathlib import Path
import sys
import tempfile

from .launcher import WindowsLauncherFiles, WindowsLauncherProcess
from .launcher_host import WindowsHostAPI, WideBufferResult, launch_host
from .release_identity import CACHE_NAMESPACE, read_identity_resource
from .protection_thread import start_windows_protection_thread


class SourceReleaseAPI(WindowsHostAPI):
    """只隔离本地测试缓存；资源、命令行、模块路径等仍使用真实WinAPI。"""
    def __init__(self):
        super().__init__()
        self.identity = read_identity_resource(self)
        base = Path(os.environ.get("LOCALAPPDATA") or tempfile.gettempdir())
        self.cache_root = (base / CACHE_NAMESPACE / self.identity.cache_key).absolute()

    def environment_variable(self, name, capacity):
        if name == "LOCALAPPDATA":
            text = str(self.cache_root)
            units = len(text.encode("utf-16le")) // 2
            if units >= capacity:
                raise ValueError("本地测试缓存目录超过原生宿主缓冲区")
            return WideBufferResult(units, text)
        return super().environment_variable(name, capacity)

    def environment_snapshot(self):
        environment = super().environment_snapshot()
        # 不让一个PyInstaller程序的解包状态流入另一个独立单文件程序。
        environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        return environment


def main():
    if not getattr(sys, "frozen", False):
        raise RuntimeError("此外层入口只运行包含资源200/203的独立源码发布包")
    api = SourceReleaseAPI()
    api.cache_root.mkdir(parents=True, exist_ok=True)
    # 本地打包兼容设置必须先进入真实宿主环境，随后按原版NULL环境继承。
    os.environ['PYINSTALLER_RESET_ENVIRONMENT'] = '1'
    result = launch_host(api, filesystem=WindowsLauncherFiles(api.cache_root),
                         process=WindowsLauncherProcess(inherit_current_environment=True),
                         protection_start=start_windows_protection_thread)
    # 忠实外层：成功创建后不等待业务进程，不转发其退出码。
    return result.exit_code
