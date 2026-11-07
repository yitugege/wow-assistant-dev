"""01ba50/01cd40/01ad90：启动取证日志；不安装 Qt 或异常处理器。"""
from __future__ import annotations
import ctypes
from ctypes import wintypes
from datetime import datetime
import ntpath
import os
from pathlib import Path
import sys
import time

HEADER = "WOW战斗助手 启动取证日志（这份文件专门用来抓「别人机器上闪退」）"
ENV_END = "以下按时间顺序记录启动过程；最后一行就是「死之前那一步」"
MAIN_ENTER = "main() 进入，准备构造 QApplication"
QT_READY = "QApplication 构造完成（Qt 运行库与平台插件均已加载）"
STYLE_READY = "全局样式表就绪"
ROTATE_BYTES = 0x100000


def candidate_directories(environment, executable: str, temp_path: str) -> tuple[str, ...]:
    """保留原序和重复项；HOME/LOCALAPPDATA 的 Win32 缓冲为1024个UTF16字符。"""
    def fits(value):
        return value and len(value.encode("utf-16-le", errors="surrogatepass")) // 2 < 1024
    result = []
    if fits(environment.get("WOWBUDDY_HOME", "")):
        result.append(environment["WOWBUDDY_HOME"])
    result.append(ntpath.dirname(executable) or ".")
    if fits(environment.get("LOCALAPPDATA", "")):
        result.append(environment["LOCALAPPDATA"] + "\\WOW战斗助手")
    result.append(temp_path or ".")
    return tuple(result)


class LocalLogFiles:
    """可移植临时测试后端；只操作给定目录的 startup.log/.old。"""
    def mkdir_local(self, directory):
        try: Path(directory).mkdir()
        except OSError: pass

    def open_append(self, directory):
        path = Path(directory) / "startup.log"
        try:
            if path.stat().st_size > ROTATE_BYTES:
                try: os.replace(path, path.with_name("startup.log.old"))
                except OSError: pass
        except OSError: pass
        return str(path), path.open("ab", buffering=0)

    def write(self, stream, payload): return stream.write(payload)
    def flush(self, stream): os.fsync(stream.fileno())
    def close(self, stream): stream.close()


class Win32LogFiles:
    """真实FILE_APPEND_DATA/FILE_SHARE_READ/OPEN_ALWAYS；构造不读写文件。"""
    def __init__(self):
        k = self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        definitions = {
            "CreateFileW": ([wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE], wintypes.HANDLE),
            "WriteFile": ([wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p], wintypes.BOOL),
            "FlushFileBuffers": ([wintypes.HANDLE], wintypes.BOOL),
            "CloseHandle": ([wintypes.HANDLE], wintypes.BOOL),
            "MoveFileExW": ([wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD], wintypes.BOOL),
            "CreateDirectoryW": ([wintypes.LPCWSTR, ctypes.c_void_p], wintypes.BOOL),
        }
        for name, (args, result) in definitions.items():
            fn = getattr(k, name); fn.argtypes = args; fn.restype = result

    def mkdir_local(self, directory): self.api.CreateDirectoryW(directory, None)

    def open_append(self, directory):
        path = directory + "\\startup.log"
        try:
            if Path(path).stat().st_size > ROTATE_BYTES:
                old = directory + "\\startup.log.old"
                # 忠实保留原调用；MoveFileEx(old,NULL,1)可能失败，随后仍尝试替换。
                self.api.MoveFileExW(old, None, 1)
                self.api.MoveFileExW(path, old, 1)
        except OSError: pass
        handle = self.api.CreateFileW(path, 4, 1, None, 4, 0x80, None)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        return path, handle

    def write(self, handle, payload):
        written = wintypes.DWORD()
        if not self.api.WriteFile(handle, payload, len(payload), ctypes.byref(written), None):
            raise ctypes.WinError(ctypes.get_last_error())
        return written.value

    def flush(self, handle): self.api.FlushFileBuffers(handle)
    def close(self, handle): self.api.CloseHandle(handle)


class StartupLog:
    """显式生命周期；初始化只执行一次。失败时保留disabled状态，不影响业务退出码。"""
    def __init__(self, *, files=None, wall_clock=datetime.now, monotonic_ms=None):
        self.files = files if files is not None else LocalLogFiles()
        self.wall_clock = wall_clock
        self.monotonic_ms = monotonic_ms or (lambda: int(time.perf_counter() * 1000))
        self.started_ms = 0
        self.initialized = False
        self.path = ""
        self.stream = None
        self.last_record_bytes = b""
        self.qt_handler_installed = False
        self.exception_handlers_installed = False

    def initialize(self, version, *, environment, executable, temp_path, environment_fields=()):
        if self.initialized: return self.path
        self.started_ms = self.monotonic_ms()
        directories = candidate_directories(environment, str(executable), temp_path)
        local = environment.get("LOCALAPPDATA", "")
        if local and len(local.encode("utf-16-le")) // 2 < 1024:
            self.files.mkdir_local(local + "\\WOW战斗助手")
        for directory in directories:
            stream = None
            try:
                path, stream = self.files.open_append(directory)
                if self.files.write(stream, b"\r\n") > 0:
                    self.path, self.stream = path, stream
                    break
            except OSError: pass
            if stream is not None: self.files.close(stream)
        self.initialized = True
        self.write_event("=====", HEADER)
        if self.stream is not None:
            self.environment("启动时间", self.wall_clock().strftime("%Y-%m-%d %H:%M:%S") + "（本地时间）")
            self.environment("程序版本", version)
            self.environment("日志文件", self.path)
            for key, value in (environment_fields() if callable(environment_fields) else environment_fields):
                self.environment(key, value)
            self.write_event("=====", ENV_END)
        return self.path

    def write_event(self, level, message):
        if not self.initialized or self.stream is None: return False
        now = self.wall_clock()
        prefix = f"[{now:%H:%M:%S}.{now.microsecond // 1000:03d} +{self.monotonic_ms() - self.started_ms}ms] "
        label = (level if isinstance(level, bytes) else str(level).encode("utf-8")).split(b"\0", 1)[0]
        body = (message if isinstance(message, bytes) else str(message).encode("utf-8")).split(b"\0", 1)[0]
        payload = (prefix.encode("ascii") + label.ljust(4, b" ") + b" " + body + b"\r\n")[:2599]
        try:
            count = self.files.write(self.stream, payload)
            self.files.flush(self.stream)
            return count == len(payload)
        except OSError: return False

    def record(self, message):
        if self.initialized:
            self.set_last_record_bytes(message)
        return self.write_event("记录", message)

    def set_last_record_bytes(self, message):
        raw = message if isinstance(message, bytes) else str(message).encode("utf-8")
        self.last_record_bytes = raw.split(b"\0", 1)[0][:599]

    def environment(self, key, value): return self.write_event("环境", f"{key} = {value}")

    def qt_environment(self, fields=None):
        if not self.initialized: return
        for key, value in (collect_qt_environment() if fields is None else fields):
            self.environment(key, value)

    def finish(self, exit_code):
        text = f"运行结束（正常退出，返回码 {int(exit_code)}）—— 看到这一行说明不是崩溃"
        if self.initialized: self.last_record_bytes = text.encode("utf-8")[:599]
        return self.write_event("=====", text)

    def close(self):
        if self.stream is not None:
            self.files.close(self.stream)
            self.stream = None


def collect_qt_environment():
    """01ad90，只读Qt环境；不抓屏、不注册消息处理器。"""
    from PySide6.QtCore import QCoreApplication, QDir, qVersion
    from PySide6.QtGui import QGuiApplication, QFontDatabase
    if not isinstance(QCoreApplication.instance(), QGuiApplication):
        raise RuntimeError("Qt环境记录要求已有QGuiApplication/QApplication")
    fields = [("Qt 版本", qVersion()), ("Qt 平台插件", QGuiApplication.platformName()),
              ("Qt 应用目录", QCoreApplication.applicationDirPath()), ("Qt 当前目录", QDir.currentPath()),
              ("字体库", f"{len(QFontDatabase.families())} 个字体族（字体库异常也是启动阶段崩溃的常见原因）")]
    screens = QGuiApplication.screens()
    for i, screen in enumerate(screens):
        rect = screen.geometry()
        fields.append(("屏幕", f"#{i} {screen.name()}  {rect.width()}x{rect.height()}  DPR={screen.devicePixelRatio():.2f}  "
                       f"{int(screen.logicalDotsPerInch())} DPI  刷新率={screen.refreshRate():.0f}Hz"))
    if not screens: fields.append(("屏幕", "★ 一个屏幕都没有 —— 这种情况建窗口必崩"))
    return fields


def collect_windows_environment(executable, environment):
    """读取当前进程及Win32基础环境，不枚举游戏或采集像素。"""
    k, u, a = ctypes.WinDLL("kernel32"), ctypes.WinDLL("user32"), ctypes.WinDLL("advapi32")
    k.GetCurrentProcess.restype = wintypes.HANDLE
    k.GetCurrentDirectoryW.argtypes = [wintypes.DWORD, wintypes.LPWSTR]
    cwd = ctypes.create_unicode_buffer(520); k.GetCurrentDirectoryW(520, cwd)
    fields = [("进程ID", str(os.getpid())), ("程序路径", str(executable)), ("工作目录", cwd.value),
              ("WOWBUDDY_HOME", environment.get("WOWBUDDY_HOME") or "(未设置 —— 说明不是由引导器拉起)")]
    class Version(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("major", wintypes.DWORD), ("minor", wintypes.DWORD),
                    ("build", wintypes.DWORD), ("platform", wintypes.DWORD), ("service", wintypes.WCHAR * 128)]
    v = Version(); v.size = ctypes.sizeof(v)
    rtl = ctypes.WinDLL("ntdll").RtlGetVersion
    rtl.argtypes = [ctypes.POINTER(Version)]; rtl.restype = wintypes.LONG
    fields.append(("Windows 版本", f"{v.major}.{v.minor} build {v.build}  " + ("(Win10/11)" if v.major >= 10 else "(低于 Win10 —— Qt6 跑不起来)")
                   if rtl(ctypes.byref(v)) == 0 else "(取不到)"))
    token, elevated, length = wintypes.HANDLE(), wintypes.DWORD(), wintypes.DWORD()
    a.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
    a.GetTokenInformation.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    if a.OpenProcessToken(k.GetCurrentProcess(), 8, ctypes.byref(token)):
        try: a.GetTokenInformation(token, 20, ctypes.byref(elevated), 4, ctypes.byref(length))
        finally: k.CloseHandle(token)
    fields.append(("管理员权限", ("是（以管理员身份运行）" if elevated.value else "否") +
                   "；远程桌面会话=" + ("是" if u.GetSystemMetrics(0x1000) else "否")))
    class Memory(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("load", wintypes.DWORD)] + [(name, ctypes.c_ulonglong) for name in
            ("total", "available", "page_total", "page_available", "virtual_total", "virtual_available", "extended")]
    memory = Memory(); memory.size = ctypes.sizeof(memory)
    fields.append(("内存", f"物理内存 共 {memory.total // 1048576} MB / 可用 {memory.available // 1048576} MB（占用 {memory.load}%）"
                   if k.GlobalMemoryStatusEx(ctypes.byref(memory)) else "(取不到)"))
    info = ctypes.create_string_buffer(48); k.GetNativeSystemInfo(info)
    arch = int.from_bytes(info.raw[:2], "little")
    k.GetActiveProcessorCount.argtypes = [wintypes.WORD]; k.GetActiveProcessorCount.restype = wintypes.DWORD
    fields.append(("CPU", f"逻辑核心 {k.GetActiveProcessorCount(0xffff)} / 类型 " + ("x64" if arch == 9 else "非 x64")))
    wow64 = wintypes.BOOL()
    k.IsWow64Process.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.BOOL)]
    k.IsWow64Process(k.GetCurrentProcess(), ctypes.byref(wow64))
    fields.extend([("位数", "本进程 " + ("32 位（跑在 64 位系统上）" if wow64.value else "64 位")),
                   ("主屏", f"{u.GetSystemMetrics(0)} x {u.GetSystemMetrics(1)}（此值受 DPI 感知影响，仅作参考）")])
    locale = ctypes.create_unicode_buffer(128)
    if k.GetUserDefaultLocaleName(locale, 128): fields.append(("区域设置", locale.value))
    language = k.GetUserDefaultUILanguage()
    if language: fields.append(("界面语言ID", f"0x{language:04X}"))
    return fields


def open_local_startup_log(version, *, executable=None, environment=None, files=None,
                           temp_path=None, environment_fields=None, wall_clock=datetime.now, monotonic_ms=None):
    """宿主在QApplication前调用；不会安装任何异常/Qt处理器。"""
    env = dict(os.environ if environment is None else environment)
    if executable is None:
        executable = sys.executable
    if temp_path is None:
        if os.name == "nt":
            buf = ctypes.create_unicode_buffer(261)
            temp_path = buf.value if ctypes.WinDLL("kernel32").GetTempPathW(261, buf) else "."
        else:
            import tempfile
            temp_path = tempfile.gettempdir()
    log = StartupLog(files=files if files is not None else (Win32LogFiles() if os.name == "nt" else LocalLogFiles()),
                     wall_clock=wall_clock, monotonic_ms=monotonic_ms)
    fields = (lambda: collect_windows_environment(executable, env)) if environment_fields is None and os.name == "nt" else (environment_fields or ())
    log.initialize(version, environment=env, executable=executable, temp_path=temp_path, environment_fields=fields)
    return log
