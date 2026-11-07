"""原外层 Windows 宿主接线及 SDK 调用方状态机。

证据来自原始内存映像 RVA 0x1d50/0x25a0/0x2750/0x2fd0/0x31d0。
没有导入即执行、默认启动、SDK 加载、默认终止宿主或隐式弹窗。
"""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
from dataclasses import dataclass, replace
import operator
import os
from typing import Callable, Mapping, NamedTuple, Protocol

from .launcher import (APPLICATION_NAME, LauncherContext, LauncherFileSystem,
                       LauncherProcess, LauncherResult, LauncherUnsupported,
                       launch_core, module_directory)


@dataclass(frozen=True)
class WideBufferResult:
    """WinAPI 返回长度与缓冲区是两项不同证据；长度单位为 UTF-16 code unit。"""
    returned: int
    text: str
    terminated: bool = True


class ResourcePayload(NamedTuple):
    data: bytes | None
    error: str | None = None


class LauncherHostAPI(Protocol):
    def module_file_name(self, capacity: int) -> WideBufferResult: ...
    def environment_variable(self, name: str, capacity: int) -> WideBufferResult: ...
    def temp_path(self, capacity: int) -> WideBufferResult: ...
    def command_line(self) -> str | None: ...
    def environment_snapshot(self) -> dict[str, str]: ...
    def find_resource(self, module, name: int, kind: int): ...
    def load_resource(self, module, resource): ...
    def lock_resource(self, resource): ...
    def sizeof_resource(self, module, resource) -> int: ...
    def copy_resource(self, pointer, size: int) -> bytes: ...
    def message_box(self, owner, text: str, title: str, flags: int) -> int: ...


def _buffer_text(result: WideBufferResult, capacity: int) -> str:
    if not result.terminated:
        raise LauncherUnsupported("原 API 成功分支的缓冲区没有终止符，不能模拟越界 wcslen")
    text = result.text.split("\0", 1)[0]
    if len(text.encode("utf-16le", "surrogatepass")) // 2 >= capacity:
        raise LauncherUnsupported("缓冲区文本超出原 WinAPI 容量")
    return text


def read_module_path(api: LauncherHostAPI, *, max_capacity: int = 1 << 20) -> str:
    """0x25a0：1024 起步；返回值 >= capacity-1 即翻倍；返回 0 则 '.'。

    max_capacity 是显式防止坏后端无限增长的重建限制；原生没有该上限分支。
    """
    capacity = 1024
    while True:
        if capacity > max_capacity:
            raise LauncherUnsupported("模块路径重试超过显式 max_capacity")
        value = api.module_file_name(capacity)
        if value.returned == 0:
            return "."
        if value.returned < 0:
            raise ValueError("WinAPI DWORD 返回长度不能为负")
        if value.returned < capacity - 1:
            return _buffer_text(value, capacity)
        capacity *= 2


def capture_path_context(api: LauncherHostAPI) -> LauncherContext:
    """首次模块查询和缓存来源；尚不读取命令行、环境快照或业务资源。"""
    module = read_module_path(api)
    local = api.environment_variable("LOCALAPPDATA", 260)
    if local.returned >= 260:
        raise LauncherUnsupported("LOCALAPPDATA 超出原生 260 字符缓冲区")
    if local.returned < 0:
        raise ValueError("WinAPI DWORD 返回长度不能为负")
    if local.returned:
        local_path, temporary = _buffer_text(local, 260), None
        if not local_path:
            raise LauncherUnsupported("LOCALAPPDATA 返回非零但缓冲区为空")
    else:
        local_path = None
        temp = api.temp_path(260)
        if temp.returned >= 260:
            raise LauncherUnsupported("GetTempPathW 超出原生 260 字符缓冲区")
        if temp.returned < 0:
            raise ValueError("WinAPI DWORD 返回长度不能为负")
        temporary = _buffer_text(temp, 260) if temp.returned else None
        if temp.returned and not temporary:
            raise LauncherUnsupported("GetTempPathW 返回非零但缓冲区为空")
    return LauncherContext(module, None, local_path, temporary, {}, module_directory(module))


EnvironmentSource = Mapping[str, str] | Callable[[], Mapping[str, str]] | None


def prepare_child_context(context: LauncherContext, api: LauncherHostAPI,
                          inherited_environment: EnvironmentSource = None) -> LauncherContext:
    """释放/复用之后再次查询模块路径，随后取原命令行及待传给子进程的环境。

    原程序此时改自身环境；这里由 child_launch 只改子环境，保留 Python 宿主配置。
    """
    second_module = read_module_path(api)
    command_line = api.command_line()
    if inherited_environment is None:
        environment = api.environment_snapshot()
    elif callable(inherited_environment):
        environment = inherited_environment()
    else:
        environment = inherited_environment
    home = context.home_directory
    if home is None:
        home = module_directory(context.module_path)
    return replace(context, module_path=second_module, raw_command_line=command_line,
                   environment=dict(environment), home_directory=home)


def capture_context(api: LauncherHostAPI,
                    inherited_environment: EnvironmentSource = None) -> LauncherContext:
    """显式完整快照；生命周期中应用 launch_host 的两阶段版本保留读取顺序。"""
    return prepare_child_context(capture_path_context(api), api, inherited_environment)


def read_embedded_bundle(api: LauncherHostAPI, *, module=None,
                         max_payload_bytes: int | None = None) -> ResourcePayload:
    """0x2750：FindResourceW(NULL, 200, RT_RCDATA=10)，不强行选择语言 1033。"""
    info = api.find_resource(module, 200, 10)
    if not info:
        return ResourcePayload(None, "内嵌负载缺失（资源 200 找不到）")
    loaded = api.load_resource(module, info)
    if not loaded:
        return ResourcePayload(None, "负载加载失败")
    pointer = api.lock_resource(loaded)
    size = api.sizeof_resource(module, info)  # 原生即使 LockResource 失败仍查询 SizeofResource。
    if not pointer or size < 12:
        return ResourcePayload(None, "负载为空")
    if max_payload_bytes is not None and size > max_payload_bytes:
        raise LauncherUnsupported("资源超过显式 max_payload_bytes")
    data = api.copy_resource(pointer, size)
    if len(data) != size:
        raise ValueError("资源后端复制长度与 SizeofResource 不一致")
    return ResourcePayload(data)


def show_failure(result: LauncherResult, api: LauncherHostAPI) -> int | None:
    """同步 MessageBoxW(NULL, text, title, MB_ICONERROR)；返回值不改变退出码。"""
    if result.dialog_text is None:
        return None
    return api.message_box(None, result.dialog_text, APPLICATION_NAME, 0x10)


def launch_host(api: LauncherHostAPI, *, filesystem: LauncherFileSystem,
                process: LauncherProcess, inherited_environment: EnvironmentSource = None,
                protection_start: Callable[[], None] | None = None,
                resource_module=None, show_errors: bool = True) -> LauncherResult:
    """显式宿主入口，惰性读资源/二次模块路径。不会默认创建真实后端或 SDK。

    原生 cwd/environment 在创建前取值；当前采用子环境隔离。show_errors=False 是测试选项。
    """
    result = launch_core(lambda: capture_path_context(api), None,
                         filesystem=filesystem, process=process, protection_start=protection_start,
                         bundle_loader=lambda: read_embedded_bundle(api, module=resource_module),
                         prepare_child_context=lambda context: prepare_child_context(
                             context, api, inherited_environment))
    if show_errors:
        show_failure(result, api)
    return result


@dataclass(frozen=True)
class SDKExports:
    """已经由调用者提供的 SDK 导出；None 表示缺失，不在这里加载 DLL。"""
    is_protected: Callable[[], int] | None
    check_debugger: Callable[[], int] | None
    crc: Callable[[], int] | None


@dataclass(frozen=True)
class ProtectionStep:
    state: str  # inactive / sleeping / terminate_requested
    delay_ms: int | None = None
    exit_code: int | None = None
    reason: str | None = None


def _return64(value: int) -> int:
    try:
        return operator.index(value) & 0xffffffffffffffff
    except TypeError as exc:
        raise LauncherUnsupported("SDK 注入接口必须给出原生整数返回值") from exc


class ProtectionMonitor:
    """0x2fd0 调用方状态机；wake 仅由调用者在 5000ms sleep 完成后调用。

    不替代 SDK 检测实现，不读取其他进程，不执行退出/INT3，终止动作只是返回请求。
    """
    def __init__(self, exports: SDKExports | None):
        self.exports = exports
        self.crc_failures = 0
        self.step: ProtectionStep | None = None

    def begin(self) -> ProtectionStep:
        if self.step is not None:
            raise RuntimeError("保护线程调用方只能初始化一次")
        sdk = self.exports
        if sdk is None:
            self.step = ProtectionStep("inactive", reason="module_unavailable")
        elif sdk.is_protected is None or sdk.check_debugger is None or sdk.crc is None:
            self.step = ProtectionStep("inactive", reason="missing_export")
        elif _return64(sdk.is_protected()) & 0xff == 0:
            self.step = ProtectionStep("inactive", reason="not_protected")
        else:
            self.step = ProtectionStep("sleeping", delay_ms=5000)
        return self.step

    def wake(self) -> ProtectionStep:
        if self.step is None:
            raise RuntimeError("先调用 begin")
        if self.step.state != "sleeping":
            return self.step
        sdk = self.exports
        if _return64(sdk.check_debugger()) != 0:
            self.step = ProtectionStep("terminate_requested", exit_code=11, reason="debugger")
        else:
            crc = _return64(sdk.crc()) & 0xff
            self.crc_failures = 0 if crc else self.crc_failures + 1
            self.step = (ProtectionStep("terminate_requested", exit_code=12, reason="crc_twice")
                         if self.crc_failures > 1 else ProtectionStep("sleeping", delay_ms=5000))
        return self.step


def run_protection_worker(exports: SDKExports | None, *, sleep_ms: Callable[[int], None],
                          terminate: Callable[[int], None]) -> ProtectionStep:
    """供注入的线程执行；sleep 和 terminate 都必须提供，没有默认系统副作用。"""
    monitor = ProtectionMonitor(exports)
    step = monitor.begin()
    while step.state == "sleeping":
        sleep_ms(step.delay_ms)
        step = monitor.wake()
    if step.exit_code is not None:
        terminate(step.exit_code)
    return step


def start_protection_monitor(exports: SDKExports | None, *,
                              start_thread: Callable[[Callable[[], ProtectionStep]], object],
                              sleep_ms: Callable[[int], None],
                              terminate: Callable[[int], None]) -> object | None:
    """仅注入线程创建；原 CreateThread 失败被忽略，主线程也不 join。"""
    try:
        return start_thread(lambda: run_protection_worker(exports, sleep_ms=sleep_ms, terminate=terminate))
    except OSError:
        return None


class WindowsHostAPI:
    """真实只读上下文/资源 API 与显式 MessageBox；从不加载保护 SDK。"""
    def __init__(self):
        if os.name != "nt":
            raise OSError("WindowsHostAPI requires Windows")
        self.k = C.WinDLL("kernel32", use_last_error=True)
        self.u = C.WinDLL("user32", use_last_error=True)
        signatures = {
            "GetModuleFileNameW": ([W.HMODULE, W.LPWSTR, W.DWORD], W.DWORD),
            "GetEnvironmentVariableW": ([W.LPCWSTR, W.LPWSTR, W.DWORD], W.DWORD),
            "GetTempPathW": ([W.DWORD, W.LPWSTR], W.DWORD),
            "GetCommandLineW": ([], W.LPWSTR),
            "GetEnvironmentStringsW": ([], C.c_void_p),
            "FreeEnvironmentStringsW": ([C.c_void_p], W.BOOL),
            "FindResourceW": ([W.HMODULE, C.c_void_p, C.c_void_p], C.c_void_p),
            "LoadResource": ([W.HMODULE, C.c_void_p], C.c_void_p),
            "LockResource": ([C.c_void_p], C.c_void_p),
            "SizeofResource": ([W.HMODULE, C.c_void_p], W.DWORD),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self.k, name)
            function.argtypes, function.restype = arguments, result
        self.u.MessageBoxW.argtypes = [W.HWND, W.LPCWSTR, W.LPCWSTR, W.UINT]
        self.u.MessageBoxW.restype = C.c_int

    @staticmethod
    def _wide_call(capacity: int, call) -> WideBufferResult:
        buffer = C.create_unicode_buffer(capacity)
        returned = call(buffer)
        raw = buffer[:]
        return WideBufferResult(returned, raw.split("\0", 1)[0], "\0" in raw)

    def module_file_name(self, capacity: int) -> WideBufferResult:
        return self._wide_call(capacity, lambda buf: self.k.GetModuleFileNameW(None, buf, capacity))

    def environment_variable(self, name: str, capacity: int) -> WideBufferResult:
        return self._wide_call(capacity, lambda buf: self.k.GetEnvironmentVariableW(name, buf, capacity))

    def temp_path(self, capacity: int) -> WideBufferResult:
        return self._wide_call(capacity, lambda buf: self.k.GetTempPathW(capacity, buf))

    def command_line(self) -> str | None:
        return self.k.GetCommandLineW()

    def environment_snapshot(self) -> dict[str, str]:
        # 原程序使用隐式继承；枚举仅为独立子环境适配，不是原调用序列中的一项。
        start = self.k.GetEnvironmentStringsW()
        if not start:
            raise C.WinError(C.get_last_error())
        result = {}
        pointer = start
        try:
            while True:
                item = C.wstring_at(pointer)
                if not item:
                    break
                split = item.find("=", 1)  # 保留 Windows 隐藏的 =C: 盘符 cwd 环境键。
                if split < 0:
                    raise LauncherUnsupported("环境块包含缺失等号的条目")
                result[item[:split]] = item[split + 1:]
                pointer += len(item.encode("utf-16le", "surrogatepass")) + 2
        finally:
            self.k.FreeEnvironmentStringsW(start)
        return result

    def find_resource(self, module, name: int, kind: int):
        return self.k.FindResourceW(module, name, kind)

    def load_resource(self, module, resource):
        return self.k.LoadResource(module, resource)

    def lock_resource(self, resource):
        return self.k.LockResource(resource)

    def sizeof_resource(self, module, resource) -> int:
        return self.k.SizeofResource(module, resource)

    def copy_resource(self, pointer, size: int) -> bytes:
        return C.string_at(pointer, size)

    def message_box(self, owner, text: str, title: str, flags: int) -> int:
        return self.u.MessageBoxW(owner, text, title, flags)
