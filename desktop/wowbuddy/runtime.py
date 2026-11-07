"""监控单次轮询，把显式抓屏、方案控制器、调度和会话接通。

由外部计时器顺序调用 poll；没有隐式线程、DLL、游戏进程或键盘后端。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from .capture import CaptureResult
from .controller import FrameController
from .readable_protocol import UnverifiedDescriptorTable
from .scheduler import Scheduler, TickResult
from .session import SessionRuntime, observe_spec
from .presentation import (capture_backend_text, legacy_spec_text, readable_spec_text,
    talent_group_text, FieldChangeThrottle, scheduler_event_text, probe_event_text)


class CaptureSource(Protocol):
    def capture(self, hwnd: int) -> CaptureResult: ...


@dataclass(frozen=True)
class PollResult:
    status: str
    capture: CaptureResult | None = None
    tick: TickResult | None = None
    elapsed_ms: int | None = None
    displayed_success_count: int | None = None


class MonitoringLoop:
    def __init__(self, session: SessionRuntime, capture: CaptureSource,
                 controller: FrameController, scheduler: Scheduler, *,
                 is_window: Callable[[int], bool], send_interval_ms: Callable[[], int]):
        if (controller.pipeline is not scheduler.pipeline
                or session.dispatcher is not scheduler.dispatcher
                or session.scheduler_state is not scheduler.state):
            raise ValueError("监控链必须共享引擎、调度和发送状态")
        self.session, self.capture = session, capture
        self.controller, self.scheduler = controller, scheduler
        self.is_window, self.send_interval_ms = is_window, send_interval_ms
        self._display_revision = controller.display_revision
        self.field_change_throttle = FieldChangeThrottle()
        self._descriptor_error = None

    def synchronize_display_cache(self):
        """098EA0/08CFE0：布局完成时同步清缓存，勿推迟至后续采样。"""
        state = self.session.state
        display = self.controller.display_frame
        state.current_spec = self.controller.spec_id
        state.field_values[:] = [""] * (len(display.rows) if display is not None else 0)
        state.decoded_fields.clear()
        state.render_fingerprint = 0
        self._display_revision = self.controller.display_revision

    def _scheduler_event(self, name, value, *, gate=None):
        message = scheduler_event_text(name, value, gate=gate)
        if message is not None:
            self.session.logger.append(message)

    def _probe_event(self, event, *, now_ms):
        message = probe_event_text(event, now_ms=now_ms)
        if message is not None:
            self.session.logger.append(message)

    def poll(self) -> PollResult:
        if not self.session.is_active():
            return PollResult("inactive")
        state = self.session.state
        if not state.hwnd or not self.is_window(state.hwnd):
            self.session.logger.append("目标窗口已关闭，自动停止")
            self.session.stop()
            return PollResult("window_closed")
        capture = self.capture.capture(state.hwnd)
        if capture.status == "minimized":
            state.status = "游戏窗口已最小化，恢复后自动继续"
            return PollResult("minimized", capture)
        if capture.image is None or capture.image.width <= 0 or capture.image.height <= 0:
            state.status = "抓屏失败"
            return PollResult("capture_failed", capture)
        # 092c90：非空图像便计帧，即使没有标记或解码失败。
        state.frame_count = ((state.frame_count + 1 + 2**31) % 2**32) - 2**31
        if state.frame_count == 1:
            self.session.logger.append(capture_backend_text(
                capture.backend_status if capture.backend_status is not None else capture.backend or ""))
        event_cursor = len(self.controller.events)
        # 原092C90先恢复身份方案，再记录字段，最后按读到的天赋过滤。
        # _change_spec清last_frame；完整帧设置last_frame后产生的方案提示
        # 必须延后，即使本次prepare也发生了身份重建。
        initial_revision = self.controller.display_revision
        original_message = self.controller.on_message
        deferred_messages = []
        def prepare_message(message):
            if (self.controller.display_revision == initial_revision
                    or self.controller.last_frame is not None):
                deferred_messages.append(message)
            elif original_message is not None:
                original_message(message)
        self.controller.on_message = prepare_message
        try:
            prepared = self.controller.prepare(capture.image)
        except UnverifiedDescriptorTable as error:
            # 重建尚未支持的路径，不伪装成原程序正常结果，也不继续旧帧调度。
            state.status = "当前协议切换尚未还原，已跳过本帧发送：" + str(error)
            if state.status != self._descriptor_error:
                self.session.logger.append(state.status)
            self._descriptor_error = state.status
            return PollResult("descriptor_unverified", capture)
        finally:
            self.controller.on_message = original_message
        self._descriptor_error = None
        if self.controller.display_revision != self._display_revision:
            # 原生字段重建先于完整采样；layout_only不得用于发送或增加变更数。
            display = self.controller.display_frame
            self.synchronize_display_cache()
            if self.controller.spec_id and display is not None:
                if prepared.frame.protocol == "old":
                    message = legacy_spec_text(len(display.rows),
                        restored_selection_nonempty=bool(self.controller.spec_pending_key))
                else:
                    presence = sum(row.type == "presence" for row in display.rows)
                    message = readable_spec_text(self.controller.spec_id, len(display.rows) - presence, presence)
                self.session.logger.append(message)
        if prepared.frame.ok:
            frame = prepared.frame
            observe_spec(state, frame.spec_id,
                         protocol="legacy" if frame.protocol == "old" else "readable",
                         field_count=len(frame.rows))
            state.decoded_fields.clear()
            state.decoded_fields.update(frame.values)
            # 092c90:854–922 / 095410:669–750：按槽比较“值 说明”，不是RGB或整帧。
            for index, row in enumerate(frame.rows):
                text = row.decoded.value_text
                if row.decoded.detail:
                    text += " " + row.decoded.detail
                if index >= len(state.field_values):
                    state.field_values.append("")
                if state.field_values[index] != text:
                    state.field_values[index] = text
                    state.frame_auxiliary = ((state.frame_auxiliary + 1 + 2**31) % 2**32) - 2**31
                    if frame.protocol == "old":
                        message = self.field_change_throttle.emit(row.key, row.index, row.label, text,
                            row.decoded.raw_rgb,
                            elapsed_ms=self.session.monotonic_ms() - state.elapsed_started_ms)
                        if message is not None:
                            self.session.logger.append(message)
        # 092c90/095410统计显示在0a2d70发键之前；保留该时点，不能把
        # 后续按键hold/sleep耗时算入当前帧的fps/运行秒显示。
        elapsed_ms = max(0, self.session.monotonic_ms() - state.elapsed_started_ms) if prepared.frame.ok else None
        displayed_success_count = self.scheduler.dispatcher.state.success_count if prepared.frame.ok else None
        if original_message is not None:
            for message in deferred_messages:
                original_message(message)
        for kind, value in self.controller.events[event_cursor:]:
            if kind == "talent":
                self.session.logger.append(talent_group_text(value))
        tick = self.scheduler.process(prepared, hwnd=state.hwnd,
                                      send_interval_ms=self.send_interval_ms(),
                                      on_event=self._scheduler_event, on_probe=self._probe_event)
        return PollResult(tick.status, capture, tick, elapsed_ms, displayed_success_count)
