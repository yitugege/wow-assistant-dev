"""窗口抓屏策略及显式 Win32 后端；导入模块不会抓屏或调用 Win32。

原生路径 01ec80 -> 02f4e0/0300e0 (DXGI) -> 01eed0 (PrintWindow)。
策略可注入 fake 后端；真实后端只有调用者显式创建并 capture 时才工作。
"""
from __future__ import annotations

import ctypes as C
from dataclasses import dataclass
import os
import time
from typing import Callable, Protocol
import uuid

from .pixel_geometry import RGBImage, find_fiducial
from .capture_backend_text import capture_backend_text


DXGI_ERROR_NOT_FOUND = 0x887A0002
DXGI_ERROR_WAIT_TIMEOUT = 0x887A0027
DXGI_RESET_ERRORS = frozenset((0x887A0026, 0x887A0005, 0x887A0006, 0x887A0007))


def failed(hr: int) -> bool:
    return bool(hr & 0x80000000)


@dataclass(frozen=True)
class Rect:
    """Win32 式半开矩形；width/height可以为非正，用于表示原生无效输入。"""
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self):
        return self.right - self.left

    @property
    def height(self):
        return self.bottom - self.top

    @property
    def empty(self):
        return self.width <= 0 or self.height <= 0

    def intersect(self, other: Rect) -> Rect:
        return Rect(max(self.left, other.left), max(self.top, other.top),
                    min(self.right, other.right), min(self.bottom, other.bottom))


def bgra_image(data: bytes, width: int, height: int, row_pitch: int) -> RGBImage:
    """顶向下BGRA字节转RGB24，忽略alpha，支持DXGI行尾padding。"""
    if width <= 0 or height <= 0 or row_pitch < width * 4:
        raise ValueError("无效BGRA尺寸或行跨度")
    if len(data) < (height - 1) * row_pitch + width * 4:
        raise ValueError("BGRA缓冲区长度不足")
    return RGBImage([[int.from_bytes(data[y * row_pitch + x * 4:y * row_pitch + x * 4 + 3], "little")
                      for x in range(width)] for y in range(height)])


def printwindow_crop(window: Rect, client_origin: tuple[int, int],
                     client_width: int, client_height: int) -> Rect | None:
    """01eed0：从完整窗口DIB裁出客户端左48列。"""
    x = max(client_origin[0] - window.left, 0)
    y = max(client_origin[1] - window.top, 0)
    width = min(client_width, window.width - x, 48)
    height = min(client_height, window.height - y)
    return Rect(x, y, x + width, y + height) if width > 0 and height > 0 else None


def _nonempty(image: RGBImage | None) -> bool:
    return image is not None and image.width > 0 and image.height > 0


def _has_capture_marker(image: RGBImage | None) -> bool:
    if not _nonempty(image):
        return False
    # 原生QPoint()=(0,0)兼作没找到；在(0,0)找到也不能通过。
    found = find_fiducial(image, 24, 2)
    return found is not None and found != (0, 0)


class WindowAPI(Protocol):
    def is_iconic(self, hwnd: int) -> bool: ...
    def window_rect(self, hwnd: int) -> Rect | None: ...
    def client_rect(self, hwnd: int) -> Rect | None: ...
    def client_to_screen(self, hwnd: int) -> tuple[int, int] | None: ...


class PrintBackend(Protocol):
    def capture(self, hwnd: int, window: Rect, origin: tuple[int, int],
                width: int, height: int) -> RGBImage | None: ...


@dataclass(frozen=True)
class DxgiInitialization:
    # ok / factory_failed / rotated / unsupported_format / duplicate_failed / no_output
    status: str
    desktop: Rect | None = None
    retry_after_ms: int | None = None


class DxgiBackend(Protocol):
    def monitor_from_rect(self, rect: Rect) -> int | None: ...
    def reset(self) -> None: ...
    def initialize(self, monitor: int) -> DxgiInitialization: ...
    def create_staging(self, width: int, height: int) -> bool: ...
    def acquire(self, timeout_ms: int) -> tuple[int, object | None]: ...
    def read_region(self, resource: object, box: Rect) -> RGBImage | None: ...
    def release_frame(self) -> None: ...
    def release_resource(self, resource: object) -> None: ...


class DxgiCapture:
    """02f4e0缓存/退避状态机；backend负责显式底层COM操作。"""
    def __init__(self, backend: DxgiBackend, clock_ms: Callable[[], int] | None = None):
        self.backend = backend
        self.clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)
        self.permanent_factory_failure = False
        self.permanent_format_failure = False
        self.retry_after_ms = 0
        self.monitor: int | None = None
        self.desktop: Rect | None = None
        self.staging_size: tuple[int, int] | None = None
        self.cached_image: RGBImage | None = None
        self.cached_rect: Rect | None = None
        self.last_rect: Rect | None = None
        self.frame_count = 0
        self.last_error = ""

    def reset(self, reason: str = "重建中") -> None:
        """02fff0不清除永久禁用、退避期限或累计帧数。"""
        self.backend.reset()
        self.monitor = None
        self.desktop = None
        self.staging_size = None
        self.cached_image = None
        self.cached_rect = None
        self.last_error = reason

    def _backoff(self, reason: str):
        self.last_error = reason
        self.retry_after_ms = self.clock_ms() + 1500

    def capture(self, client: Rect, strip_width: int = 48) -> RGBImage | None:
        if (self.permanent_factory_failure or self.permanent_format_failure
                or self.clock_ms() < self.retry_after_ms or client.empty or strip_width <= 0):
            return None
        monitor = self.backend.monitor_from_rect(client)
        if not monitor:
            return None
        if self.monitor != monitor:
            self.reset()
            init = self.backend.initialize(monitor)
            if init.status == "factory_failed":
                self.permanent_factory_failure = True
                self.last_error = init.status
                return None
            if init.status in {"rotated", "unsupported_format"}:
                self.permanent_format_failure = True
                self.last_error = init.status
                return None
            if init.status in {"duplicate_failed", "no_output"}:
                if init.retry_after_ms is None:
                    self._backoff(init.status)
                else:
                    self.last_error = init.status
                    self.retry_after_ms = init.retry_after_ms
                return None
            if init.status != "ok" or init.desktop is None:
                raise ValueError(f"未恢复的DXGI初始化结果：{init.status}")
            self.monitor, self.desktop = monitor, init.desktop
            self.last_error = ""
        crop = Rect(client.left, client.top, client.left + min(client.width, strip_width),
                    client.bottom).intersect(self.desktop)
        self.last_rect = crop
        if crop.empty:
            return None
        size = (crop.width, crop.height)
        if self.staging_size != size:
            if not self.backend.create_staging(*size):
                self.reset("staging 贴图创建失败")
                self._backoff("staging 贴图创建失败")
                return None
            self.staging_size = size
            self.cached_image = None
            self.cached_rect = None
        hr, resource = self.backend.acquire(50 if not _nonempty(self.cached_image) else 0)
        hr &= 0xFFFFFFFF
        try:
            if hr == DXGI_ERROR_WAIT_TIMEOUT:
                return self.cached_image if self.cached_rect == crop else None
            if hr in DXGI_RESET_ERRORS:
                self.reset("duplication 访问丢失")
                self._backoff("duplication 访问丢失（模式切换/全屏转换）")
                return None
            if failed(hr):
                return None
            try:
                if resource is None:
                    raise RuntimeError("DXGI成功但未返回资源；不能伪造捕获帧")
                box = Rect(crop.left - self.desktop.left, crop.top - self.desktop.top,
                           crop.right - self.desktop.left, crop.bottom - self.desktop.top)
                image = self.backend.read_region(resource, box)
                if _nonempty(image):
                    if (image.width, image.height) != size:
                        raise ValueError("DXGI后端返回图像尺寸与裁剪区域不一致")
                    self.cached_image, self.cached_rect = image, crop
                    self.frame_count += 1
                return image
            finally:
                self.backend.release_frame()
        finally:
            if resource is not None:
                self.backend.release_resource(resource)


@dataclass(frozen=True)
class CaptureResult:
    status: str
    image: RGBImage | None = None
    backend: str | None = None
    client_rect: Rect | None = None
    marker_found: bool = False
    backend_status: str | None = None


class WindowCapture:
    def __init__(self, windows: WindowAPI, dxgi: DxgiCapture, printwindow: PrintBackend):
        self.windows, self.dxgi, self.printwindow = windows, dxgi, printwindow

    def _backend_status(self) -> str | None:
        # 兼容既有只提供capture()的fake；不读取Mock自动生成的动态属性。
        return capture_backend_text(self.dxgi) if isinstance(self.dxgi, DxgiCapture) else None

    def capture(self, hwnd: int) -> CaptureResult:
        if not hwnd:
            return CaptureResult("invalid_window")
        if self.windows.is_iconic(hwnd):
            return CaptureResult("minimized")
        window = self.windows.window_rect(hwnd)
        if window is None or window.empty:
            return CaptureResult("invalid_window_rect")
        client = self.windows.client_rect(hwnd)
        if client is None:
            return CaptureResult("invalid_client_rect")
        origin = self.windows.client_to_screen(hwnd)
        if origin is None:
            return CaptureResult("client_to_screen_failed")
        if client.empty:
            return CaptureResult("invalid_client_rect")
        rect = Rect(origin[0], origin[1], origin[0] + client.width, origin[1] + client.height)
        dxgi = self.dxgi.capture(rect, 48)
        if _has_capture_marker(dxgi):
            return CaptureResult("ok", dxgi, "dxgi", rect, True,
                                 self._backend_status())
        printed = self.printwindow.capture(hwnd, window, origin, client.width, client.height)
        if _nonempty(printed) and (not _nonempty(dxgi) or _has_capture_marker(printed)):
            selected, name = printed, "printwindow"
        elif _nonempty(dxgi):
            selected, name = dxgi, "dxgi"
        else:
            selected, name = printed, "printwindow"
        return CaptureResult("ok" if _nonempty(selected) else "capture_failed",
                             selected, name, rect, _has_capture_marker(selected),
                             self._backend_status() if _nonempty(selected) else None)


# 下列固定宽度结构与Win64 ABI相符；模块导入不会加载DLL。
U32 = C.c_uint32
I32 = C.c_int32
PTR = C.c_void_p


class _RECT(C.Structure):
    _fields_ = [("left", I32), ("top", I32), ("right", I32), ("bottom", I32)]


class _POINT(C.Structure):
    _fields_ = [("x", I32), ("y", I32)]


class _BITMAPINFO(C.Structure):
    _fields_ = [("size", U32), ("width", I32), ("height", I32),
                ("planes", C.c_uint16), ("bit_count", C.c_uint16),
                ("compression", U32), ("image_size", U32), ("xppm", I32), ("yppm", I32),
                ("used", U32), ("important", U32), ("color", U32)]


def _signature(dll, name, result, args):
    function = getattr(dll, name)
    function.restype, function.argtypes = result, args
    return function


class Win32WindowAPI:
    """只在显式构造时加载DLL，查询方法才调用系统。"""
    def __init__(self):
        if os.name != "nt":
            raise OSError("真实抓屏后端只支持Windows")
        self.user32 = C.WinDLL("user32", use_last_error=True)
        _signature(self.user32, "IsIconic", I32, [PTR])
        _signature(self.user32, "GetWindowRect", I32, [PTR, C.POINTER(_RECT)])
        _signature(self.user32, "GetClientRect", I32, [PTR, C.POINTER(_RECT)])
        _signature(self.user32, "ClientToScreen", I32, [PTR, C.POINTER(_POINT)])

    def is_iconic(self, hwnd):
        return bool(self.user32.IsIconic(hwnd))

    def _rect(self, function, hwnd):
        rect = _RECT()
        return Rect(rect.left, rect.top, rect.right, rect.bottom) if function(hwnd, C.byref(rect)) else None

    def window_rect(self, hwnd):
        return self._rect(self.user32.GetWindowRect, hwnd)

    def client_rect(self, hwnd):
        return self._rect(self.user32.GetClientRect, hwnd)

    def client_to_screen(self, hwnd):
        point = _POINT(0, 0)
        return (point.x, point.y) if self.user32.ClientToScreen(hwnd, C.byref(point)) else None


class Win32PrintWindow:
    """完整窗口top-down 32bit DIB，PrintWindow 2→0，裁出客户端条带。"""
    def __init__(self):
        if os.name != "nt":
            raise OSError("PrintWindow只支持Windows")
        self.user32 = C.WinDLL("user32", use_last_error=True)
        self.gdi32 = C.WinDLL("gdi32", use_last_error=True)
        for name, result, args in (
            ("GetWindowDC", PTR, [PTR]), ("ReleaseDC", I32, [PTR, PTR]),
            ("PrintWindow", I32, [PTR, PTR, U32]),
        ):
            _signature(self.user32, name, result, args)
        for name, result, args in (
            ("CreateCompatibleDC", PTR, [PTR]),
            ("CreateDIBSection", PTR, [PTR, C.POINTER(_BITMAPINFO), U32, C.POINTER(PTR), PTR, U32]),
            ("SelectObject", PTR, [PTR, PTR]), ("DeleteObject", I32, [PTR]), ("DeleteDC", I32, [PTR]),
        ):
            _signature(self.gdi32, name, result, args)

    def capture(self, hwnd, window, origin, width, height):
        if window.empty or width <= 0 or height <= 0:
            return None
        dc = self.user32.GetWindowDC(hwnd)
        if not dc:
            return None
        memory_dc = bitmap = previous = None
        try:
            memory_dc = self.gdi32.CreateCompatibleDC(dc)
            if not memory_dc:
                return None
            info = _BITMAPINFO()
            info.size, info.width, info.height = 40, window.width, -window.height
            info.planes, info.bit_count = 1, 32
            bits = PTR()
            bitmap = self.gdi32.CreateDIBSection(dc, C.byref(info), 0, C.byref(bits), None, 0)
            if not bitmap or not bits.value:
                return None
            previous = self.gdi32.SelectObject(memory_dc, bitmap)
            success = self.user32.PrintWindow(hwnd, memory_dc, 2)
            if not success:
                success = self.user32.PrintWindow(hwnd, memory_dc, 0)
            if not success:
                return None
            crop = printwindow_crop(window, origin, width, height)
            if crop is None:
                return None
            # copy拥有像素，在DeleteObject释放DIB前独立取得输出字节。
            data = b"".join(C.string_at(bits.value + (y * window.width + crop.left) * 4,
                                       crop.width * 4) for y in range(crop.top, crop.bottom))
            return bgra_image(data, crop.width, crop.height, crop.width * 4)
        finally:
            if previous:
                self.gdi32.SelectObject(memory_dc, previous)
            if bitmap:
                self.gdi32.DeleteObject(bitmap)
            if memory_dc:
                self.gdi32.DeleteDC(memory_dc)
            self.user32.ReleaseDC(hwnd, dc)


class _OUTPUT_DESC(C.Structure):
    _fields_ = [("name", C.c_uint16 * 32), ("desktop", _RECT), ("attached", I32),
                ("rotation", U32), ("monitor", PTR)]


class _DUPLICATION_DESC(C.Structure):
    _fields_ = [(name, U32) for name in ("width", "height", "refresh_num", "refresh_den",
                "format", "scanline", "scaling", "rotation", "system_memory")]


class _TEXTURE_DESC(C.Structure):
    _fields_ = [(name, U32) for name in ("width", "height", "mip_levels", "array_size",
                "format", "sample_count", "sample_quality", "usage", "bind_flags", "cpu_access", "misc")]


class _FRAME_INFO(C.Structure):
    _fields_ = [("present_time", C.c_int64), ("mouse_time", C.c_int64),
                ("frames", U32), ("coalesced", I32), ("protected", I32),
                ("pointer", _POINT), ("pointer_visible", I32), ("metadata_size", U32), ("shape_size", U32)]


class _MAPPED(C.Structure):
    _fields_ = [("data", PTR), ("row_pitch", U32), ("depth_pitch", U32)]


class _BOX(C.Structure):
    _fields_ = [(name, U32) for name in ("left", "top", "front", "right", "bottom", "back")]


def _iid(text):
    return (C.c_ubyte * 16).from_buffer_copy(uuid.UUID(text).bytes_le)


def _com(pointer, slot, result, argtypes, *args):
    if not pointer:
        raise RuntimeError("COM接口为空")
    table = C.cast(pointer, C.POINTER(C.POINTER(PTR))).contents
    return C.WINFUNCTYPE(result, PTR, *argtypes)(table[slot])(pointer, *args)


def _release(pointer):
    if pointer:
        _com(pointer, 2, U32, [])


class Win32DxgiBackend:
    """原生Win64 COM后端。恢复代码未经本轮真实GPU/抓屏运行验证。"""
    def __init__(self):
        if os.name != "nt" or C.sizeof(PTR) != 8:
            raise OSError("DXGI后端只支持64位Windows")
        self.user32 = C.WinDLL("user32", use_last_error=True)
        self.dxgi = C.WinDLL("dxgi")
        self.d3d11 = C.WinDLL("d3d11")
        _signature(self.user32, "MonitorFromRect", PTR, [C.POINTER(_RECT), U32])
        _signature(self.dxgi, "CreateDXGIFactory1", I32, [PTR, C.POINTER(PTR)])
        _signature(self.d3d11, "D3D11CreateDevice", I32,
                   [PTR, U32, PTR, U32, PTR, U32, U32, C.POINTER(PTR), PTR, C.POINTER(PTR)])
        self.device = self.context = self.duplication = self.staging = None
        self.staging_size = None

    def monitor_from_rect(self, rect):
        # 原版把QRect::right/bottom（含尾像素）直接传给MonitorFromRect。
        native = _RECT(rect.left, rect.top, rect.right - 1, rect.bottom - 1)
        return self.user32.MonitorFromRect(C.byref(native), 2)

    def reset(self):
        for name in ("duplication", "staging"):
            _release(getattr(self, name))
            setattr(self, name, None)
        self.staging_size = None

    def close(self):
        self.reset()
        for name in ("context", "device"):
            _release(getattr(self, name))
            setattr(self, name, None)

    def initialize(self, monitor):
        factory = PTR()
        hr = self.dxgi.CreateDXGIFactory1(_iid("770aae78-f26f-4dba-a829-253c83d1b387"), C.byref(factory))
        if failed(hr):
            _release(factory)
            return DxgiInitialization("factory_failed")
        try:
            adapter_index = 0
            while True:
                adapter = PTR()
                hr = _com(factory, 12, I32, [U32, C.POINTER(PTR)], adapter_index, C.byref(adapter))
                if hr & 0xFFFFFFFF == DXGI_ERROR_NOT_FOUND:
                    _release(adapter)
                    # 原0300e0同样在factory.Release之前设置期限。
                    return DxgiInitialization("no_output", retry_after_ms=int(time.time() * 1000) + 1500)
                if failed(hr):
                    _release(adapter)
                    # 原生未检查NOT_FOUND以外枚举失败，不能照搬空指针解引用。
                    raise OSError(f"未定义的EnumAdapters1失败：0x{hr & 0xFFFFFFFF:08X}")
                try:
                    output_index = 0
                    while True:
                        output = PTR()
                        hr = _com(adapter, 7, I32, [U32, C.POINTER(PTR)], output_index, C.byref(output))
                        if hr & 0xFFFFFFFF == DXGI_ERROR_NOT_FOUND:
                            _release(output)
                            break
                        if failed(hr):
                            _release(output)
                            raise OSError(f"未定义的EnumOutputs失败：0x{hr & 0xFFFFFFFF:08X}")
                        try:
                            desc = _OUTPUT_DESC()
                            hr = _com(output, 7, I32, [C.POINTER(_OUTPUT_DESC)], C.byref(desc))
                            if not failed(hr) and desc.monitor == monitor:
                                if desc.rotation != 1:
                                    return DxgiInitialization("rotated")
                                result = self._initialize_output(adapter, output, desc)
                                if result is not None:
                                    return result
                        finally:
                            _release(output)
                        output_index += 1
                finally:
                    _release(adapter)
                adapter_index += 1
        finally:
            _release(factory)

    def _initialize_output(self, adapter, output, output_desc):
        device, context, output1, duplication = PTR(), PTR(), PTR(), PTR()
        try:
            hr = self.d3d11.D3D11CreateDevice(adapter, 0, None, 0x20, None, 0, 7,
                                             C.byref(device), None, C.byref(context))
            if failed(hr):
                return None  # 原版继续枚举下一个output。
            hr = _com(output, 0, I32, [PTR, C.POINTER(PTR)],
                      _iid("00cddea8-939b-4b83-a340-a685226666cc"), C.byref(output1))
            if failed(hr):
                return None
            hr = _com(output1, 22, I32, [PTR, C.POINTER(PTR)], device, C.byref(duplication))
            if failed(hr):
                # 原0300e0在释放COM引用前设置期限；慢释放不能延后重试时间。
                return DxgiInitialization("duplicate_failed", retry_after_ms=int(time.time() * 1000) + 1500)
            desc = _DUPLICATION_DESC()
            _com(duplication, 7, None, [C.POINTER(_DUPLICATION_DESC)], C.byref(desc))
            if desc.format != 87:
                return DxgiInitialization("unsupported_format")
            for name, value in (("device", device), ("context", context), ("duplication", duplication)):
                _release(getattr(self, name))
                setattr(self, name, value.value)
                value.value = None  # 所有权转给backend，避免finally释放。
            r = output_desc.desktop
            return DxgiInitialization("ok", Rect(r.left, r.top, r.right, r.bottom))
        finally:
            for value in (duplication, output1, context, device):
                _release(value)

    def create_staging(self, width, height):
        _release(self.staging)
        self.staging = None
        self.staging_size = None
        desc = _TEXTURE_DESC(width, height, 1, 1, 87, 1, 0, 3, 0, 0x20000, 0)
        texture = PTR()
        hr = _com(self.device, 5, I32, [C.POINTER(_TEXTURE_DESC), PTR, C.POINTER(PTR)],
                  C.byref(desc), None, C.byref(texture))
        if failed(hr):
            _release(texture)
            return False
        self.staging, self.staging_size = texture.value, (width, height)
        return True

    def acquire(self, timeout_ms):
        frame, resource = _FRAME_INFO(), PTR()
        hr = _com(self.duplication, 8, I32, [U32, C.POINTER(_FRAME_INFO), C.POINTER(PTR)],
                  timeout_ms, C.byref(frame), C.byref(resource))
        return hr, resource.value

    def read_region(self, resource, box):
        texture = PTR()
        try:
            hr = _com(resource, 0, I32, [PTR, C.POINTER(PTR)],
                      _iid("6f15aaf2-d208-4e89-9ab4-489535d34f9c"), C.byref(texture))
            if failed(hr):
                return None
            region = _BOX(box.left, box.top, 0, box.right, box.bottom, 1)
            _com(self.context, 46, None, [PTR, U32, U32, U32, U32, PTR, U32, C.POINTER(_BOX)],
                 self.staging, 0, 0, 0, 0, texture, 0, C.byref(region))
            _com(self.context, 111, None, [])  # Flush
            mapped = _MAPPED()
            hr = _com(self.context, 14, I32, [PTR, U32, U32, U32, C.POINTER(_MAPPED)],
                      self.staging, 0, 1, 0, C.byref(mapped))
            if failed(hr):
                return None
            try:
                if not mapped.data:
                    raise RuntimeError("Map成功但缓冲区为空")
                width, height = self.staging_size
                data = C.string_at(mapped.data, (height - 1) * mapped.row_pitch + width * 4)
                return bgra_image(data, width, height, mapped.row_pitch)
            finally:
                _com(self.context, 15, None, [PTR, U32], self.staging, 0)
        finally:
            _release(texture)

    def release_frame(self):
        _com(self.duplication, 14, I32, [])

    def release_resource(self, resource):
        _release(resource)


def make_win32_capture() -> WindowCapture:
    """显式创建真实后端；调用返回对象.capture(hwnd)才开始抓屏。"""
    return WindowCapture(Win32WindowAPI(), DxgiCapture(Win32DxgiBackend()), Win32PrintWindow())
