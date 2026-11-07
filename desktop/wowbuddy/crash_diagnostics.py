"""01ce40..01d851异常日志与当前进程handler；不生成原版没有的minidump。"""
from __future__ import annotations
import ctypes as C
import os
import sys
import struct


EXCEPTION_NAMES = {
    0xC0000005: "访问冲突 ACCESS_VIOLATION", 0xC00000FD: "栈溢出 STACK_OVERFLOW",
    0xC0000094: "整数除零", 0xC0000096: "特权指令", 0xC000001D: "非法指令",
    0xC0000409: "fail-fast（/GS 栈检查失败或 __fastfail）", 0xC0000374: "堆损坏 HEAP_CORRUPTION",
    0xC0000006: "页入失败（DLL/文件读不到）", 0x80000003: "断点", 0xE06D7363: "C++ 异常未捕获",
}
CRT_MESSAGES = {"abort": "收到 SIGABRT（abort）", "invalid": "CRT 无效参数（invalid parameter handler）",
                "purecall": "调用了纯虚函数"}


class NativeSehRecord(Exception):
    """当前异常为非C++ SEH；原terminate重抛后转abort且防重入禁止第二条日志。"""


def raw(value):
    return value if isinstance(value, bytes) else str(value).encode("utf-8", "replace")


def seh_message(code, address, module, thread_id, information, last):
    code &= 0xFFFFFFFF
    suffix = b""
    if code == 0xC0000005 and len(information) >= 2:
        kind = "读" if information[0] == 0 else "写" if information[0] == 1 else "执行"
        suffix = raw(f" {kind}地址=0x{information[1] & 0xFFFFFFFFFFFFFFFF:X}")[:191]
    return (raw(f"异常码=0x{code:08X}（{EXCEPTION_NAMES.get(code, '未知异常码')}） "
                f"出错地址=0x{address & 0xFFFFFFFFFFFFFFFF:X} 模块=")
            + raw(module or "(未取到)") + suffix
            + raw(f" 线程={thread_id & 0xFFFFFFFF} 最后记录=「") + raw(last) + raw("」"))[:2199]


def terminate_message(description, last):
    return (raw("未捕获异常 → terminate：") + raw(description)[:399]
            + raw(" 最后记录=「") + raw(last) + raw("」"))[:699]


class CrashDiagnostics:
    """共享防重入字节；terminate由宿主注入，纯测试不会结束当前测试进程。"""
    def __init__(self, log, terminate):
        self.log, self.terminate = log, terminate
        self.entered = False

    def seh(self, record):
        if self.entered:
            return 0
        self.entered = True  # 原版即使空EXCEPTION_POINTERS也置位。
        if record is not None:
            message = seh_message(*record, self.log.last_record_bytes)
            self.log.last_record_bytes = message[:599]
            self.log.write_event("崩溃", message)
        return 0  # EXCEPTION_CONTINUE_SEARCH，不吞掉操作系统异常。

    def fatal(self, kind, description=None):
        if not self.entered:
            self.entered = True
            if kind == "terminate":
                message = terminate_message(description or "非 std::exception 类型（或 terminate 无活动异常）",
                                            self.log.last_record_bytes)
                self.log.last_record_bytes = message[:599]
            else:
                message = raw(CRT_MESSAGES[kind])
            self.log.write_event("崩溃", message)
        self.terminate(3)

    def python_exception(self, kind, value, traceback):
        # 重建语言适配：Python业务异常映射至原terminate的可观察记录/退出路径。
        description = "std::bad_alloc（内存不足）" if issubclass(kind, MemoryError) else "std::exception: " + str(value)
        self.fatal("terminate", description)


class ExceptionRecord(C.Structure):
    _fields_ = [("code", C.c_uint32), ("flags", C.c_uint32), ("nested", C.c_void_p),
                ("address", C.c_void_p), ("number_parameters", C.c_uint32),
                ("information", C.c_size_t * 15)]


class ExceptionPointers(C.Structure):
    _fields_ = [("record", C.POINTER(ExceptionRecord)), ("context", C.c_void_p)]


class CurrentProcessDiagnostics:
    """只在显式install时注册当前进程SEH/CRT/Python钩子，close恢复旧钩子。

    外部C++活动异常的what()尚未跨语言恢复；其terminate按原未知类型分支记录。
    Python callback不能保证原生栈耗尽/堆损坏时仍能运行；不冒称该极端路径等价。
    """
    def __init__(self, log):
        if os.name != "nt":
            raise NotImplementedError("当前原生诊断后端只支持Windows")
        self.k = C.WinDLL("kernel32", use_last_error=True)
        self.crt = C.CDLL("ucrtbase")
        self.vcrt = C.CDLL("vcruntime140")
        self.k.GetCurrentProcess.argtypes, self.k.GetCurrentProcess.restype = [], C.c_void_p
        self.k.TerminateProcess.argtypes, self.k.TerminateProcess.restype = [C.c_void_p, C.c_uint32], C.c_int
        self.k.GetCurrentThreadId.argtypes, self.k.GetCurrentThreadId.restype = [], C.c_uint32
        self.k.GetModuleHandleExW.argtypes, self.k.GetModuleHandleExW.restype = [C.c_uint32, C.c_void_p, C.POINTER(C.c_void_p)], C.c_int
        self.k.GetModuleFileNameW.argtypes, self.k.GetModuleFileNameW.restype = [C.c_void_p, C.c_wchar_p, C.c_uint32], C.c_uint32
        self.state = CrashDiagnostics(log, self._terminate)
        self.callbacks, self.restore = [], []
        self.previous_hook = None
        self.installed = False

    def _terminate(self, code):
        self.k.TerminateProcess(self.k.GetCurrentProcess(), code)
        os._exit(code)

    def _seh(self, pointer):
        try:
            value = None
            if pointer:
                pointers = C.cast(pointer, C.POINTER(ExceptionPointers)).contents
                if pointers.record:
                    record = pointers.record.contents
                    module, name = C.c_void_p(), ""
                    if self.k.GetModuleHandleExW(6, record.address, C.byref(module)):
                        buffer = C.create_unicode_buffer(260)
                        self.k.GetModuleFileNameW(module, buffer, 260)
                        name = buffer.value
                        if len(name.encode("utf-8")) >= 780:
                            name = ""
                    value = (record.code, record.address or 0, name, self.k.GetCurrentThreadId(),
                             tuple(record.information[:min(record.number_parameters, 15)]))
            return self.state.seh(value)
        except BaseException:
            return 0

    def _register(self, function, callback):
        function.argtypes, function.restype = [C.c_void_p], C.c_void_p
        previous = function(C.cast(callback, C.c_void_p))
        self.callbacks.append(callback)
        self.restore.append(lambda: function(previous))

    def _native_terminate(self):
        description = None
        if not self.state.entered:
            try:
                # 原current_exception为空仍执行rethrow，实际捕获bad_exception。
                description = native_exception_description()
            except NativeSehRecord:
                self.state.entered = True
                self.crt.abort()
                return
            except (OSError, AttributeError):
                pass  # 查询不可用时保留未知类型，仍完成致命错误退出。
        self.state.fatal("terminate", description)

    def install(self):
        if self.installed:
            return self
        try:
            self._register(self.k.SetUnhandledExceptionFilter, C.WINFUNCTYPE(C.c_long, C.c_void_p)(self._seh))
            self._register(self.crt.set_terminate, C.CFUNCTYPE(None)(self._native_terminate))
            self._register(self.crt._set_invalid_parameter_handler,
                C.CFUNCTYPE(None, C.c_void_p, C.c_void_p, C.c_void_p, C.c_uint32, C.c_size_t)(
                    lambda *args: self.state.fatal("invalid")))
            self._register(self.vcrt._set_purecall_handler, C.CFUNCTYPE(None)(lambda: self.state.fatal("purecall")))
            callback = C.CFUNCTYPE(None, C.c_int)(lambda signum: self.state.fatal("abort"))
            self.crt.signal.argtypes, self.crt.signal.restype = [C.c_int, C.c_void_p], C.c_void_p
            old_signal = self.crt.signal(22, C.cast(callback, C.c_void_p))
            if old_signal == C.c_void_p(-1).value:
                raise OSError("SIGABRT handler注册失败")
            self.callbacks.append(callback)
            self.restore.append(lambda: self.crt.signal(22, old_signal))
            self.previous_hook, sys.excepthook = sys.excepthook, self.state.python_exception
            self.installed = True
            return self
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.previous_hook is not None:
            sys.excepthook = self.previous_hook
            self.previous_hook = None
        for restore in reversed(self.restore):
            restore()
        self.restore.clear()
        self.callbacks.clear()
        self.installed = False


def native_exception_present():
    """通过同版MSVC exception_ptr API查询本线程，保证销毁引用。"""
    runtime = C.CDLL("msvcp140.dll")
    names = ("?__ExceptionPtrCreate@@YAXPEAX@Z",
             "?__ExceptionPtrCurrentException@@YAXPEAX@Z",
             "?__ExceptionPtrToBool@@YA_NPEBX@Z",
             "?__ExceptionPtrDestroy@@YAXPEAX@Z")
    create, current, present, destroy = [getattr(runtime, name) for name in names]
    for function in (create, current, destroy):
        function.argtypes, function.restype = [C.c_void_p], None
    present.argtypes, present.restype = [C.c_void_p], C.c_bool
    pointer = (C.c_void_p * 2)()
    create(pointer)
    try:
        current(pointer)
        return bool(present(pointer))
    finally:
        destroy(pointer)


def native_exception_description():
    runtime = C.CDLL('msvcp140.dll')
    create, current, destroy = [getattr(runtime, name) for name in (
        '?__ExceptionPtrCreate@@YAXPEAX@Z', '?__ExceptionPtrCurrentException@@YAXPEAX@Z',
        '?__ExceptionPtrDestroy@@YAXPEAX@Z')]
    for function in (create, current, destroy):
        function.argtypes, function.restype = [C.c_void_p], None
    pointer = (C.c_void_p * 2)()
    create(pointer)
    try:
        current(pointer)
        if not pointer[0]:
            return b'std::exception: bad exception'
        if struct.unpack('<I', read_current_process(pointer[0], 4))[0] != 0xE06D7363:
            raise NativeSehRecord()
        return describe_msvc_record(pointer[0], read_current_process, native_what)
    finally:
        destroy(pointer)


def describe_msvc_record(address, read, what):
    """解析已确认MSVC x64记录；read和what显式传入便于原记录回放。"""
    record = read(address, 64)
    if struct.unpack_from('<I', record)[0] != 0xE06D7363 or struct.unpack_from('<I', record, 24)[0] != 4:
        return None
    magic, obj, info, base = struct.unpack_from('<4Q', record, 32)
    if magic != 0x19930520 or not all((obj, info, base)):
        return None
    table_rva = struct.unpack_from('<i', read(info, 16), 12)[0]
    if table_rva <= 0:
        return None
    table = base + table_rva
    count = struct.unpack('<i', read(table, 4))[0]
    if not 0 < count <= 256:
        return None
    standard = None
    for rva in struct.unpack('<' + 'i' * count, read(table + 4, count * 4)):
        if rva <= 0:
            return None
        properties, type_rva, member, vbtable, virtual, size, copy = struct.unpack('<7i', read(base + rva, 28))
        if type_rva <= 0:
            return None
        # 仅需识别两个已确认的标准类型，不读取无界RTTI名称。
        name = bytearray()
        for i in range(64):
            byte = read(base + type_rva + 16 + i, 1)
            if byte == b'\0': break
            name.extend(byte)
        if name == b'.?AVbad_alloc@std@@':
            return 'std::bad_alloc（内存不足）'.encode()
        if name == b'.?AVexception@std@@' and vbtable == -1:
            standard = obj + member
    if standard is None:
        return None
    return (b'std::exception: ' + what(standard))[:399]


def read_current_process(address, size):
    """ReadProcessMemory避免直接解引用无效诊断记录。"""
    k = C.WinDLL('kernel32', use_last_error=True)
    k.GetCurrentProcess.restype = C.c_void_p
    k.ReadProcessMemory.argtypes = [C.c_void_p, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
    k.ReadProcessMemory.restype = C.c_int
    data, actual = C.create_string_buffer(size), C.c_size_t()
    if not k.ReadProcessMemory(k.GetCurrentProcess(), address, data, size, C.byref(actual)) or actual.value != size:
        raise OSError('无法读取当前进程异常记录')
    return data.raw


def native_what(obj):
    table = struct.unpack('<Q', read_current_process(obj, 8))[0]
    function = struct.unpack('<Q', read_current_process(table + 8, 8))[0]
    text = C.CFUNCTYPE(C.c_void_p, C.c_void_p)(function)(obj)
    data = bytearray()
    for i in range(383):  # 原399字节描述缓冲减去16字节前缀。
        byte = read_current_process(text + i, 1)
        if byte == b'\0': break
        data.extend(byte)
    return bytes(data)


def trigger_cpp_runtime_error():
    """明确--crash-test=throw入口：原生线程真实抛出std::runtime_error。

    使用MSVC运行库导出的_Xruntime_error，避免Python异常到terminate的映射。
    线程直接进入导出函数，异常不穿过ctypes的SEH捕获边界。
    """
    if os.name != "nt" or C.sizeof(C.c_void_p) != 8:
        raise NotImplementedError("C++异常故障注入只支持Windows x64")
    runtime = C.CDLL("msvcp140.dll")
    throw = getattr(runtime, "?_Xruntime_error@std@@YAXPEBD@Z")
    message = C.create_string_buffer(b"crash-test")
    k = C.WinDLL("kernel32", use_last_error=True)
    k.CreateThread.argtypes, k.CreateThread.restype = [C.c_void_p, C.c_size_t, C.c_void_p, C.c_void_p, C.c_uint32, C.POINTER(C.c_uint32)], C.c_void_p
    k.WaitForSingleObject.argtypes, k.WaitForSingleObject.restype = [C.c_void_p, C.c_uint32], C.c_uint32
    k.CloseHandle.argtypes, k.CloseHandle.restype = [C.c_void_p], C.c_int
    thread_id = C.c_uint32()
    handle = k.CreateThread(None, 0, C.cast(throw, C.c_void_p), C.cast(message, C.c_void_p), 0, C.byref(thread_id))
    if not handle:
        raise C.WinError(C.get_last_error())
    try:
        # 正常路径由未捕获原生异常终止进程；无限等待避免释放仍使用中的消息。
        k.WaitForSingleObject(handle, 0xFFFFFFFF)
        raise RuntimeError("C++异常测试没有按预期结束进程")
    finally:
        k.CloseHandle(handle)


def trigger_null_write():
    """只用于明确--crash-test：当前进程新原生线程真实写NULL，不经过ctypes的SEH拦截。"""
    if os.name != "nt" or C.sizeof(C.c_void_p) != 8:
        raise NotImplementedError("空指针故障注入只支持Windows x64")
    k = C.WinDLL("kernel32", use_last_error=True)
    k.VirtualAlloc.argtypes, k.VirtualAlloc.restype = [C.c_void_p, C.c_size_t, C.c_uint32, C.c_uint32], C.c_void_p
    k.VirtualProtect.argtypes, k.VirtualProtect.restype = [C.c_void_p, C.c_size_t, C.c_uint32, C.POINTER(C.c_uint32)], C.c_int
    k.GetCurrentProcess.restype = C.c_void_p
    k.FlushInstructionCache.argtypes, k.FlushInstructionCache.restype = [C.c_void_p, C.c_void_p, C.c_size_t], C.c_int
    k.CreateThread.argtypes, k.CreateThread.restype = [C.c_void_p, C.c_size_t, C.c_void_p, C.c_void_p, C.c_uint32, C.POINTER(C.c_uint32)], C.c_void_p
    k.WaitForSingleObject.argtypes, k.WaitForSingleObject.restype = [C.c_void_p, C.c_uint32], C.c_uint32
    k.CloseHandle.argtypes, k.CloseHandle.restype = [C.c_void_p], C.c_int
    k.VirtualFree.argtypes, k.VirtualFree.restype = [C.c_void_p, C.c_size_t, C.c_uint32], C.c_int
    # x64: mov dword ptr [absolute 0],1 ; ret。仅私有页，没有写入其他进程。
    code = bytes.fromhex("c7 04 25 00 00 00 00 01 00 00 00 c3")
    pointer = k.VirtualAlloc(None, len(code), 0x3000, 4)
    if not pointer:
        raise C.WinError(C.get_last_error())
    handle = None
    try:
        C.memmove(pointer, code, len(code))
        old, thread_id = C.c_uint32(), C.c_uint32()
        if not k.VirtualProtect(pointer, len(code), 0x20, C.byref(old)):
            raise C.WinError(C.get_last_error())
        k.FlushInstructionCache(k.GetCurrentProcess(), pointer, len(code))
        handle = k.CreateThread(None, 0, pointer, None, 0, C.byref(thread_id))
        if not handle:
            raise C.WinError(C.get_last_error())
        result = k.WaitForSingleObject(handle, 5000)
        if result == 258:
            # 仍在执行的线程不能释放其代码页，交由外层Job结束测试进程。
            pointer = None
        raise RuntimeError("空指针测试没有按预期结束进程")
    finally:
        if handle:
            k.CloseHandle(handle)
        if pointer:
            k.VirtualFree(pointer, 0, 0x8000)
