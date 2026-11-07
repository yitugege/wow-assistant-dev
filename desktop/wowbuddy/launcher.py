"""由原始内存取证恢复的外层核心，以及显式有界调试观察器。

launch_core 只调用显式注入的后端。run_debug_probe 是独立观察入口：其子进程
均在创建调试事件暂停点截获，采集后终止 Job。Job 不是文件/网络沙箱。
"""
from __future__ import annotations

import ctypes as C
from ctypes import wintypes as W
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import time
from dataclasses import dataclass, field
from typing import Protocol, Callable


BUILD_ID = "1.0.38-ad7e89b9"
APPLICATION_NAME = "WOW战斗助手"
BUSINESS_EXE = APPLICATION_NAME + ".exe"


class LauncherUnsupported(ValueError):
    """没有证明的原生异常行为，不能静默代用。"""


class LauncherFileSystem(Protocol):
    def attributes_exist(self, path: str) -> bool: ...
    def create_directory(self, path: str) -> None: ...
    def create_always(self, path: str): ...
    def write(self, handle, data: bytes) -> int: ...
    def close(self, handle) -> None: ...


@dataclass(frozen=True)
class LauncherContext:
    module_path: str
    raw_command_line: str | None
    local_app_data: str | None
    temp_path: str | None
    environment: dict[str, str] = field(default_factory=dict)
    # 原外层首次查询模块路径用于 HOME，释放后再次查询用于 EXE，不能混为同一次读取。
    home_directory: str | None = None


@dataclass(frozen=True)
class ChildLaunch:
    application: str
    command_line: str
    cwd: str
    environment: dict[str, str]
    inherit_handles: bool = False
    creation_flags: int = 0


class LauncherProcess(Protocol):
    def create(self, request: ChildLaunch): ...
    def close_thread(self, process) -> None: ...
    def close_process(self, process) -> None: ...


@dataclass(frozen=True)
class LauncherResult:
    exit_code: int
    release_directory: str
    reused: bool
    extracted_members: tuple[str, ...]
    request: ChildLaunch | None
    error: str | None = None
    gaps: tuple[str, ...] = ()

    @property
    def dialog_text(self) -> str | None:
        if self.exit_code == 2:
            return ("解包失败：" + (self.error or "") + "\n\n缓存目录：\n" +
                    self.release_directory + "\n\n官网：https://wowbuddy.cn")
        if self.exit_code == 3:
            return (self.error or "") + "\n\n官网：https://wowbuddy.cn"
        return None


def release_directory(local_app_data: str | None, temp_path: str | None) -> str:
    """RVA 0x1d50，输入是成功 WinAPI 读取的缓冲区，不自动规范化。"""
    base = local_app_data or temp_path or "."
    # 原生 MAX_PATH 缓冲区过短时并未正确检查返回长度，不能猜测缓冲区结果。
    if len(base.encode("utf-16le", "surrogatepass")) // 2 >= 260:
        raise LauncherUnsupported("原生 260 字符路径缓冲区溢出返回行为未复原")
    return base + "\\" + APPLICATION_NAME + "\\app-" + BUILD_ID


def module_directory(module_path: str) -> str:
    """RVA 0x2280，取最后一个正/反斜杠之前的文本；没有则 '.'。"""
    index = max(module_path.rfind("\\"), module_path.rfind("/"))
    return module_path[:index] if index >= 0 else "."


def command_line_tail(raw: str | None) -> str:
    """RVA 0x31d0:3a55，按原算法跳过 argv[0]；保留原空白和引号。"""
    raw = (raw or "").split("\0", 1)[0]
    if raw.startswith('"'):
        end = raw.find('"', 1)
        return raw[end + 1:] if end >= 0 else ""
    for index, character in enumerate(raw):
        if character in " \t":
            return raw[index:]
    return ""


def child_launch(context: LauncherContext, directory: str) -> ChildLaunch:
    executable = directory + "\\" + BUSINESS_EXE
    environment = dict(context.environment)
    # Windows 环境键大小写不敏感；不留下同名异大小写副本。
    for key in tuple(environment):
        if key.upper() in {"WOWBUDDY_HOME", "WOWBUDDY_EXE"}:
            del environment[key]
    environment["WOWBUDDY_HOME"] = (module_directory(context.module_path)
                                   if context.home_directory is None else context.home_directory)
    environment["WOWBUDDY_EXE"] = context.module_path or "."
    return ChildLaunch(executable, '"' + executable + '"' + command_line_tail(context.raw_command_line),
                       directory, environment)


def _mkdir_chain(fs: LauncherFileSystem, path: str) -> None:
    # RVA 0x1ff0，逐分隔符创建；跳过 X: / X:\，忽略 CreateDirectory 返回值。
    for index, character in enumerate(path):
        if character in "\\/" or index == len(path) - 1:
            prefix = path[:index + 1]
            if len(prefix) in (2, 3) and prefix[1] == ":":
                continue
            try:
                fs.create_directory(prefix)
            except OSError:
                pass


def _write_native(fs: LauncherFileSystem, path: str, data: bytes) -> bool:
    # RVA 0x30e0；CREATE_ALWAYS，1 MiB 分块，允许短写，零写/错误失败，不回滚。
    try:
        handle = fs.create_always(path)
    except OSError:
        return False
    try:
        offset = 0
        while offset < len(data):
            count = fs.write(handle, data[offset:offset + 0x100000])
            if count <= 0:
                return False
            if count > min(0x100000, len(data) - offset):
                raise ValueError("后端 WriteFile 返回了超过请求大小的写入量")
            offset += count
        return True
    except OSError:
        return False
    finally:
        fs.close(handle)


def _decode_native_name(data: bytes) -> str:
    """原外层 RVA 0x2ef0：CP_UTF8/flags=0，显式有符号 int 长度。"""
    if not data or len(data) >= 0x80000000:
        return ""
    if os.name != "nt":
        # 有效 UTF-8 可移植；异常序列不能用 Python replace 冒充 Windows。
        try:
            return data.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise LauncherUnsupported("畸形 UTF-8 成员名称需要 Windows 原生转换") from exc
    convert = C.WinDLL("kernel32", use_last_error=True).MultiByteToWideChar
    convert.argtypes = [W.UINT, W.DWORD, C.c_char_p, C.c_int, C.c_void_p, C.c_int]
    convert.restype = C.c_int
    count = convert(65001, 0, data, len(data), None, 0)
    if count == 0:
        return ""
    output = (C.c_ushort * count)()
    convert(65001, 0, data, len(data), output, count)
    return bytes(output).decode("utf-16le", errors="surrogatepass")


def _unpack_native(data: bytes, directory: str, fs: LauncherFileSystem,
                   written: list[str]) -> str | None:
    # 有意按成员解析并立即写入；packages.read_bundle 的整包预校验会改变失败时的部分写入。
    if len(data) < 12:
        return "负载为空"
    if data[:4] != b"WBD1":
        return "负载头非法"
    count, = struct.unpack_from("<I", data, 4)
    offset = 8
    for _ in range(count):
        if len(data) - offset < 4:
            return "负载截断（名字长度）"
        length, = struct.unpack_from("<I", data, offset)
        offset += 4
        if len(data) - offset < length:
            return "负载截断（名字）"
        name = _decode_native_name(data[offset:offset + length]).replace("/", "\\")
        offset += length
        if len(data) - offset < 8:
            return "负载截断（大小）"
        size, = struct.unpack_from("<Q", data, offset)
        offset += 8
        if len(data) - offset < size:
            return "负载截断（数据）"
        path = directory + "\\" + name
        _mkdir_chain(fs, path[:path.rfind("\\")])
        if not _write_native(fs, path, data[offset:offset + size]):
            return "写入失败: " + name
        written.append(name)
        offset += size
    # 原生不检查尾随字节，也不检查重复名称；最后一次写入覆盖。
    return None


def launch_core(context: LauncherContext | Callable[[], LauncherContext], bundle: bytes | None, *,
                filesystem: LauncherFileSystem, process: LauncherProcess,
                protection_start: Callable[[], None] | None = None,
                resource_error: str | None = None,
                bundle_loader: Callable[[], tuple[bytes | None, str | None]] | None = None,
                prepare_child_context: Callable[[LauncherContext], LauncherContext] | None = None) -> LauncherResult:
    """恢复 RVA 0x31d0 的释放/复用/启动核心；只调用显式注入的后端。

    不加载保护 DLL。调用者可注入保护线程启动事件；未提供时在 result.gaps 中标记。
    resource_error 可表述 FindResource/LoadResource 失败；正常 bundle 是资源 10/200 内容。
    """
    gaps = () if protection_start else ("未执行原生 SProtectSDK64 保护监控线程",)
    if protection_start:
        protection_start()
    if callable(context):
        context = context()
    directory = release_directory(context.local_app_data, context.temp_path)
    executable = directory + "\\" + BUSINESS_EXE
    ready = directory + "\\.ready"
    reused = (filesystem.attributes_exist(executable)
              and filesystem.attributes_exist(ready))
    written: list[str] = []
    if not reused:
        _mkdir_chain(filesystem, directory)
        if bundle_loader is not None:
            bundle, resource_error = bundle_loader()
        error = resource_error or ("内嵌负载缺失（资源 200 找不到）" if bundle is None else None)
        if error is None:
            error = _unpack_native(bundle, directory, filesystem, written)
        if error:
            return LauncherResult(2, directory, False, tuple(written), None, error, gaps)
        # .ready 创建/写入失败不阻止启动；不会删除之前存在的 .ready。
        _write_native(filesystem, ready, BUILD_ID.encode("ascii"))
    if prepare_child_context is not None:
        context = prepare_child_context(context)
    request = child_launch(context, directory)
    try:
        child = process.create(request)
    except OSError as exc:
        code = getattr(exc, "winerror", None) or exc.errno or 0
        return LauncherResult(3, directory, reused, tuple(written), request,
                              "无法启动主程序：\n" + request.application + "\n\n错误码 " + str(code), gaps)
    process.close_thread(child)
    process.close_process(child)
    # 没有 wait、退出码转发、缓存清理或删除旧版本。
    return LauncherResult(0, directory, reused, tuple(written), request, gaps=gaps)


class WindowsLauncherFiles:
    """显式真实 FS 适配器：WinAPI 共享模式/CREATE_ALWAYS，写入限定 root。

    限定 root 是本地测试边界，原程序未做此检查。没有默认实例或隐式磁盘操作。
    进程后端仍必须由调用者提供；此适配器不会执行 EXE。
    """
    def __init__(self, root: Path):
        if os.name != "nt":
            raise OSError("WindowsLauncherFiles requires Windows")
        self.root = root.resolve(strict=True)
        if not self.root.is_dir():
            raise ValueError("root 必须是已存在目录")
        self.k = C.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "GetFileAttributesW": ([W.LPCWSTR], W.DWORD),
            "CreateDirectoryW": ([W.LPCWSTR, C.c_void_p], W.BOOL),
            "CreateFileW": ([W.LPCWSTR, W.DWORD, W.DWORD, C.c_void_p, W.DWORD, W.DWORD, W.HANDLE], W.HANDLE),
            "WriteFile": ([W.HANDLE, C.c_void_p, W.DWORD, C.POINTER(W.DWORD), C.c_void_p], W.BOOL),
            "CloseHandle": ([W.HANDLE], W.BOOL),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self.k, name)
            function.argtypes, function.restype = args, result

    def _path(self, path: str, *, allow_existing_ancestor=False) -> str | None:
        if "\0" in path:
            raise OSError("本地测试后端拒绝 NUL 路径")
        resolved = Path(path).resolve()
        if resolved == self.root or self.root in resolved.parents:
            return str(resolved)
        if allow_existing_ancestor and resolved in self.root.parents and resolved.is_dir():
            return None
        raise OSError("写入范围超出显式 root")

    def attributes_exist(self, path: str) -> bool:
        return self.k.GetFileAttributesW(self._path(path)) != 0xffffffff

    def create_directory(self, path: str) -> None:
        target = self._path(path, allow_existing_ancestor=True)
        if target is not None:
            self.k.CreateDirectoryW(target, None)

    def create_always(self, path: str):
        handle = self.k.CreateFileW(self._path(path), 0x40000000, 0, None, 2, 0x80, None)
        if handle == C.c_void_p(-1).value:
            raise C.WinError(C.get_last_error())
        return handle

    def write(self, handle, data: bytes) -> int:
        written = W.DWORD()
        buffer = C.create_string_buffer(data)
        if not self.k.WriteFile(handle, buffer, len(data), C.byref(written), None):
            raise C.WinError(C.get_last_error())
        return written.value

    def close(self, handle) -> None:
        self.k.CloseHandle(handle)


class ProbeError(RuntimeError):
    pass


class StartupInfo(C.Structure):
    _fields_ = [("cb", W.DWORD), ("reserved", W.LPWSTR), ("desktop", W.LPWSTR),
                ("title", W.LPWSTR), ("x", W.DWORD), ("y", W.DWORD),
                ("xsize", W.DWORD), ("ysize", W.DWORD), ("xchars", W.DWORD),
                ("ychars", W.DWORD), ("fill", W.DWORD), ("flags", W.DWORD),
                ("show", W.WORD), ("reserved_size", W.WORD), ("reserved2", C.c_void_p),
                ("stdin", W.HANDLE), ("stdout", W.HANDLE), ("stderr", W.HANDLE)]


class ProcessInfo(C.Structure):
    _fields_ = [("process", W.HANDLE), ("thread", W.HANDLE), ("pid", W.DWORD), ("tid", W.DWORD)]


class CreateProcessInfo(C.Structure):
    _fields_ = [("file", W.HANDLE), ("process", W.HANDLE), ("thread", W.HANDLE),
               ("image_base", C.c_void_p), ("debug_offset", W.DWORD), ("debug_size", W.DWORD),
               ("tls", C.c_void_p), ("start", C.c_void_p), ("image_name", C.c_void_p),
               ("unicode", W.WORD)]


class EventData(C.Union):
    _fields_ = [("create", CreateProcessInfo), ("raw", C.c_ubyte * 160), ("alignment", C.c_uint64)]


class DebugEvent(C.Structure):
    _fields_ = [("code", W.DWORD), ("pid", W.DWORD), ("tid", W.DWORD), ("data", EventData)]


class WindowsLauncherProcess:
    """显式真实 CreateProcess 适配器；没有构造即执行或等待子进程。

    发布入口显式启用inherit_current_environment：设置原生两个宿主变量，
    再用NULL环境及原flags创建。其他嵌入调用保留独立Unicode环境块模式。
    """
    def __init__(self, *, inherit_current_environment=False):
        if os.name != "nt":
            raise OSError("WindowsLauncherProcess requires Windows")
        self.k, _ = _apis()
        self.inherit_current_environment = inherit_current_environment
        if inherit_current_environment:
            self.k.SetEnvironmentVariableW.argtypes = [W.LPCWSTR, W.LPCWSTR]
            self.k.SetEnvironmentVariableW.restype = W.BOOL

    def create(self, request: ChildLaunch):
        if any("\0" in key or "\0" in value for key, value in request.environment.items()):
            raise ValueError("环境变量不能包含 NUL")
        startup, process = StartupInfo(), ProcessInfo()
        startup.cb = C.sizeof(startup)
        command = C.create_unicode_buffer(request.command_line)
        flags = request.creation_flags
        if getattr(self, 'inherit_current_environment', False):
            # 原外层只设置这两个值，忽略SetEnvironmentVariableW返回值；
            # CreateProcess传NULL环境继承宿主，而不是重放早先的环境快照。
            for name in ('WOWBUDDY_HOME', 'WOWBUDDY_EXE'):
                self.k.SetEnvironmentVariableW(name, request.environment[name])
            environment = None
        else:
            environment = C.create_unicode_buffer("\0".join(
                key + "=" + value for key, value in sorted(request.environment.items(), key=lambda kv: kv[0].upper())
            ) + "\0\0")
            flags |= 0x400
        if not self.k.CreateProcessW(request.application, command, None, None,
                                     request.inherit_handles, flags,
                                     environment, request.cwd, C.byref(startup), C.byref(process)):
            raise C.WinError(C.get_last_error())
        return process

    def close_thread(self, process: ProcessInfo) -> None:
        self.k.CloseHandle(process.thread)

    def close_process(self, process: ProcessInfo) -> None:
        self.k.CloseHandle(process.process)


def _apis():
    if os.name != "nt" or C.sizeof(C.c_void_p) != 8:
        raise ProbeError("观察器仅支持 Windows x64")
    k = C.WinDLL("kernel32", use_last_error=True)
    signatures = {
        "CreateProcessW": ([W.LPCWSTR, W.LPWSTR, C.c_void_p, C.c_void_p, W.BOOL, W.DWORD,
                            C.c_void_p, W.LPCWSTR, C.POINTER(StartupInfo), C.POINTER(ProcessInfo)], W.BOOL),
        "CreateJobObjectW": ([C.c_void_p, W.LPCWSTR], W.HANDLE),
        "SetInformationJobObject": ([W.HANDLE, C.c_int, C.c_void_p, W.DWORD], W.BOOL),
        "AssignProcessToJobObject": ([W.HANDLE, W.HANDLE], W.BOOL),
        "TerminateJobObject": ([W.HANDLE, W.UINT], W.BOOL),
        "TerminateProcess": ([W.HANDLE, W.UINT], W.BOOL),
        "ResumeThread": ([W.HANDLE], W.DWORD),
        "WaitForDebugEvent": ([C.POINTER(DebugEvent), W.DWORD], W.BOOL),
        "ContinueDebugEvent": ([W.DWORD, W.DWORD, W.DWORD], W.BOOL),
        "ReadProcessMemory": ([W.HANDLE, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)], W.BOOL),
        "CloseHandle": ([W.HANDLE], W.BOOL),
        "WaitForSingleObject": ([W.HANDLE, W.DWORD], W.DWORD),
        "GetExitCodeProcess": ([W.HANDLE, C.POINTER(W.DWORD)], W.BOOL),
        "GetCurrentProcess": ([], W.HANDLE),
        "DuplicateHandle": ([W.HANDLE, W.HANDLE, W.HANDLE, C.POINTER(W.HANDLE), W.DWORD, W.BOOL, W.DWORD], W.BOOL),
    }
    for name, (args, result) in signatures.items():
        fn = getattr(k, name)
        fn.argtypes, fn.restype = args, result
    n = C.WinDLL("ntdll")
    n.NtQueryInformationProcess.argtypes = [W.HANDLE, C.c_int, C.c_void_p, W.ULONG, C.POINTER(W.ULONG)]
    n.NtQueryInformationProcess.restype = C.c_long
    return k, n


def _checked(ok, name):
    if not ok:
        raise ProbeError(f"{name}: WinError={C.get_last_error()}")


def _read(k, process, address, size):
    data = C.create_string_buffer(size)
    count = C.c_size_t()
    _checked(k.ReadProcessMemory(process, address, data, size, C.byref(count)), "ReadProcessMemory")
    if count.value != size:
        raise ProbeError(f"短读 {count.value}/{size}")
    return data.raw


def _startup(k, n, process, expected_environment):
    basic = C.create_string_buffer(48)
    length = W.ULONG()
    status = n.NtQueryInformationProcess(process, 0, basic, 48, C.byref(length))
    if status < 0:
        raise ProbeError(f"NtQueryInformationProcess: {status:#x}")
    peb = struct.unpack_from("<Q", basic.raw, 8)[0]
    parameters = struct.unpack("<Q", _read(k, process, peb + 0x20, 8))[0]
    if not parameters:
        return {"peb": hex(peb), "parameters": None}
    def unicode_at(offset):
        descriptor = _read(k, process, parameters + offset, 16)
        count, _, pointer = struct.unpack("<HH4xQ", descriptor)
        return _read(k, process, pointer, count).decode("utf-16-le", "replace") if count else ""
    result = {"peb": hex(peb), "parameters": hex(parameters), "cwd": unicode_at(0x38),
              "image_path": unicode_at(0x60), "command_line": unicode_at(0x70)}
    pointer = struct.unpack("<Q", _read(k, process, parameters + 0x80, 8))[0]
    data = bytearray()
    if pointer:
        for offset in range(0, 1024 * 1024, 2):
            data += _read(k, process, pointer + offset, 2)
            if len(data) >= 4 and data[-4:] == b"\0\0\0\0":
                break
        else:
            raise ProbeError("环境块超过1MiB")
    environment = {}
    for item in data.decode("utf-16-le", "replace").split("\0"):
        if "=" in item and not item.startswith("="):
            key, value = item.split("=", 1)
            environment[key] = value
    # 不把继承的凭证写入证据；只保留运行目录相关值和其他变更的键名。
    relevant = lambda key: key.upper() in {"TEMP", "TMP", "LOCALAPPDATA", "PATH"} or key.upper().startswith(("WOWBUDDY_", "QT_"))
    baseline = {key.upper(): value for key, value in expected_environment.items()}
    result["environment"] = {key: value for key, value in environment.items() if relevant(key)}
    result["other_changed_environment_keys"] = sorted(key for key, value in environment.items()
        if not relevant(key) and baseline.get(key.upper()) != value)
    return result


def _dump_image(k, process, base, destination):
    header = _read(k, process, base, 4096)
    pe = struct.unpack_from("<I", header, 0x3c)[0]
    if header[pe:pe+4] != b"PE\0\0":
        raise ProbeError("内存不是PE映像")
    sections, optional_size = struct.unpack_from("<H12xH", header, pe + 6)
    entry = struct.unpack_from("<I", header, pe + 24 + 16)[0]
    result = {"image_base": hex(base), "header_entry_rva": hex(entry), "sections": []}
    for index in range(sections):
        off = pe + 24 + optional_size + 40*index
        name, size, rva, disk_size, disk_offset = struct.unpack_from("<8sIIII", header, off)
        name = name.rstrip(b"\0").decode("ascii", "replace")
        if size > 64*1024*1024:
            raise ProbeError("异常节长度")
        row = {"name": name, "rva": hex(rva), "virtual_size": size,
               "disk_size": disk_size, "disk_offset": disk_offset}
        try:
            data = _read(k, process, base + rva, size)
            file = destination / f"section-{index:02d}.bin"
            file.write_bytes(data)
            row.update(file=file.name, sha256=hashlib.sha256(data).hexdigest(), nonzero=sum(x != 0 for x in data))
        except ProbeError as exc:
            row["error"] = str(exc)
        result["sections"].append(row)
    (destination / "image-header.bin").write_bytes(header)
    return result


def run_debug_probe(executable: Path, arguments: list[str], workspace: Path, *,
                    environment: dict[str, str], timeout_seconds: float = 15) -> dict:
    """显式有界运行；首次子进程创建即采集、dump父映像并终止，绝不Continue子创建。

    workspace 必须不存在。调用者负责独立复制原EXE。该观察器不挂接其他进程。
    """
    if not 0 < timeout_seconds <= 30:
        raise ValueError("限时应在0到30秒")
    k, n = _apis()
    workspace = workspace.resolve()
    workspace.mkdir(parents=True, exist_ok=False)
    report = {"kind": "bounded-debug-observation", "executable": str(executable.resolve()),
              "arguments": list(arguments), "started": datetime.now().isoformat(), "events": [],
              "children": [], "not_a_sandbox": True, "outcome": "initializing"}
    job = k.CreateJobObjectW(None, None)
    pi = ProcessInfo()
    handles = set()
    debug_processes = {}
    pending = None
    parent_base = 0
    try:
        _checked(job, "CreateJobObjectW")
        limits = C.create_string_buffer(144)
        struct.pack_into("<I", limits, 16, 0x2000)  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        _checked(k.SetInformationJobObject(job, 9, limits, 144), "SetInformationJobObject")
        si = StartupInfo(); si.cb = C.sizeof(si)
        si.flags, si.show = 1, 0  # STARTF_USESHOWWINDOW/SW_HIDE，仅显示提示，不是安全边界。
        command = C.create_unicode_buffer(subprocess.list2cmdline([str(executable.resolve()), *arguments]))
        env = C.create_unicode_buffer("\0".join(f"{key}={value}" for key, value in sorted(environment.items(), key=lambda x:x[0].upper())) + "\0\0")
        _checked(k.CreateProcessW(str(executable.resolve()), command, None, None, False,
                                  0x1 | 0x4 | 0x400, env, str(workspace), C.byref(si), C.byref(pi)), "CreateProcessW")
        handles.update((pi.process, pi.thread))
        report["parent_pid"] = pi.pid
        _checked(k.AssignProcessToJobObject(job, pi.process), "AssignProcessToJobObject")
        if k.ResumeThread(pi.thread) == 0xffffffff:
            raise ProbeError(f"ResumeThread: WinError={C.get_last_error()}")
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            event = DebugEvent()
            if not k.WaitForDebugEvent(C.byref(event), 100):
                if C.get_last_error() == 121:  # ERROR_SEM_TIMEOUT
                    continue
                raise ProbeError(f"WaitForDebugEvent: WinError={C.get_last_error()}")
            pending = (event.pid, event.tid)
            item = {"code": event.code, "pid": event.pid, "tid": event.tid}
            report["events"].append(item)
            disposition = 0x10002  # DBG_CONTINUE
            if event.code == 3:  # CREATE_PROCESS_DEBUG_EVENT: child hasn't executed entrypoint.
                info = event.data.create
                duplicate = W.HANDLE()
                _checked(k.DuplicateHandle(k.GetCurrentProcess(), info.process, k.GetCurrentProcess(),
                                           C.byref(duplicate), 0, False, 2), "DuplicateHandle")
                debug_processes[event.pid] = duplicate.value
                handles.add(duplicate.value)
                if info.file: handles.add(info.file)
                item["image_base"], item["start"] = hex(info.image_base or 0), hex(info.start or 0)
                try:
                    item["startup"] = _startup(k, n, info.process, environment)
                except ProbeError as exc:
                    item["startup_error"] = str(exc)
                if event.pid == pi.pid:
                    parent_base = info.image_base
                else:
                    report["children"].append(dict(item))
                    report["parent_memory"] = _dump_image(k, pi.process, parent_base, workspace)
                    report["outcome"] = "child_intercepted_before_execution"
                    break
            elif event.code == 1:
                code = struct.unpack_from("<I", bytes(event.data.raw))[0]
                chance = struct.unpack_from("<I", bytes(event.data.raw), 152)[0]
                item.update(exception=hex(code), first_chance=chance)
                if code not in (0x80000003, 0x80000004):
                    disposition = 0x80010001
            elif event.code == 6:  # LOAD_DLL
                handle = struct.unpack_from("<Q", bytes(event.data.raw))[0]
                if handle: handles.add(handle)
            elif event.code == 5 and event.pid == pi.pid:
                report["outcome"] = "parent_exited_without_child"
                report["exit_code"] = struct.unpack_from("<I", bytes(event.data.raw))[0]
                k.ContinueDebugEvent(*pending, disposition)
                pending = None
                break
            _checked(k.ContinueDebugEvent(*pending, disposition), "ContinueDebugEvent")
            pending = None
        else:
            report["outcome"] = "timeout"
    except Exception as exc:
        report["outcome"] = "probe_failed"
        report["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        if job:
            report["terminate_job_ok"] = bool(k.TerminateJobObject(job, 0xE001))
        if pi.process:
            # AssignProcessToJobObject失败时进程仍挂起且未受Job管理。
            k.TerminateProcess(pi.process, 0xE001)
        for handle in debug_processes.values():
            k.TerminateProcess(handle, 0xE001)
        if pending:
            k.ContinueDebugEvent(*pending, 0x10002)
        # 终止请求之后只排空调试退出事件；不允许未终止的子线程运行。
        drain_until = time.monotonic() + 3
        while pi.process and time.monotonic() < drain_until:
            event = DebugEvent()
            if k.WaitForDebugEvent(C.byref(event), 50):
                if event.code == 6:
                    handle = struct.unpack_from("<Q", bytes(event.data.raw))[0]
                    if handle: handles.add(handle)
                k.ContinueDebugEvent(event.pid, event.tid, 0x10002)
            if (k.WaitForSingleObject(pi.process, 0) == 0
                    and all(k.WaitForSingleObject(h, 0) == 0 for h in debug_processes.values())):
                break
        if pi.process:
            report["parent_terminated"] = k.WaitForSingleObject(pi.process, 1000) == 0
        report["observed_processes_terminated"] = {
            str(pid): k.WaitForSingleObject(handle, 1000) == 0
            for pid, handle in debug_processes.items()}
        for handle in handles:
            k.CloseHandle(handle)
        if job:
            k.CloseHandle(job)
        report["finished"] = datetime.now().isoformat()
        (workspace / "observation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
