"""02FCE0 抓屏诊断文本；不同于最终图像的 dxgi/printwindow 选择。"""
from __future__ import annotations

from dataclasses import dataclass


NATIVE_REASONS = {
    "factory_failed": "CreateDXGIFactory1 失败",
    "rotated": "旋转屏，不支持桌面复制",
    "unsupported_format": "HDR/非常规桌面格式，不支持桌面复制",
    "duplicate_failed": "DuplicateOutput 失败（占用/会话限制）",
    "no_output": "目标显示器挂不到 DXGI 输出",
}


@dataclass(frozen=True)
class CaptureBackendState:
    duplication_active: bool = False
    frame_count: int = 0
    permanent_format_failure: bool = False
    permanent_factory_failure: bool = False
    retry_after_ms: int = 0
    last_error: str = ""


def backend_status_text(state: CaptureBackendState, now_ms: int) -> str:
    """原生顺序：duplication指针→永久禁用→空原因→退避倒计时。

    剩余秒数是 max(0,deadline-now)//1000+1，不是ceil；期限已过仍显示1。
    原生最终以32位int加1，再符号扩展传入QString.arg。
    """
    if state.duplication_active:
        return f"DXGI 桌面复制（已取 {state.frame_count} 帧新桌面帧）"
    reason = NATIVE_REASONS.get(state.last_error, state.last_error)
    if state.permanent_format_failure or state.permanent_factory_failure:
        return f"GDI PrintWindow（{reason}）"
    if not reason:
        return "GDI PrintWindow"
    seconds = max(0, state.retry_after_ms - now_ms) // 1000 + 1
    seconds = (seconds + 0x80000000) % 0x100000000 - 0x80000000
    return f"GDI PrintWindow（{reason}，{seconds} 秒后重试 DXGI）"


def capture_backend_text(dxgi, now_ms: int | None = None) -> str:
    """适配既有DxgiCapture状态，不调用COM/抓屏，不用返回图像来源推断状态。

    DxgiCapture.monitor只在初始化成功后设置，reset清除，对应原duplication
    指针的生命周期。此接口要求完整DxgiCapture状态，不接受动态Mock替代对象。
    """
    state = CaptureBackendState(
        duplication_active=dxgi.monitor is not None,
        frame_count=dxgi.frame_count,
        permanent_format_failure=dxgi.permanent_format_failure,
        permanent_factory_failure=dxgi.permanent_factory_failure,
        retry_after_ms=dxgi.retry_after_ms,
        last_error=dxgi.last_error,
    )
    needs_clock = (not state.duplication_active and not state.permanent_format_failure
                   and not state.permanent_factory_failure and bool(state.last_error))
    if now_ms is None:
        now_ms = dxgi.clock_ms() if needs_clock else 0
    return backend_status_text(state, now_ms)
