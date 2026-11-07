"""会话生命周期和日志；所有定时器/文本显示/文件写入均显式注入。

0a2070 开始重置与 098ea0 专精字段重建不同，不能整体替换 SchedulerState。
本模块不发送按键、不捕获窗口，不隐式创建线程或 GUI。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
import os
from typing import Callable, Mapping, Protocol

from .dispatch import ActionDispatcher
from .scheduler import SchedulerState


class LogView(Protocol):
    def append_plain_text(self, line: str) -> None: ...
    def clear(self) -> None: ...


class LogFile(Protocol):
    path: str
    def is_open(self) -> bool: ...
    def write(self, data: bytes) -> int: ...
    def flush(self) -> bool: ...
    def close(self) -> None: ...


class LogStore(Protocol):
    def make_directory(self, path: Path) -> bool: ...
    def open_append_text(self, path: Path) -> LogFile: ...


class Timer(Protocol):
    def is_active(self) -> bool: ...
    def start(self, interval_ms: int) -> None: ...
    def stop(self) -> None: ...


class FileLog:
    """显式文件实现，按原 Windows QFile Append|Text 写 UTF-8/CRLF。

    打开或写入失败返回状态，不伪装抛异常后停止整个监控；原调用方忽略
    write/flush 返回值。不存在 BOM，重复秒级文件名使用追加，不截断。
    """
    def __init__(self, path: Path):
        self.path = str(path)
        self._file = None
        self.error = ''
        try:
            # 原 Windows QFile Append 仅在打开时定位末尾；后续保留句柄位置。
            # CRT O_APPEND 每次写入都重新定位，外部截断/追加时与原版不同。
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | getattr(os, 'O_BINARY', 0), 0o666)
            try:
                self._file = os.fdopen(descriptor, 'wb')
            except BaseException:
                os.close(descriptor)
                raise
            self._file.seek(0, os.SEEK_END)
        except OSError as error:
            self.error = str(error)

    def is_open(self) -> bool:
        return self._file is not None and not self._file.closed

    def write(self, data: bytes) -> int:
        if not self.is_open():
            return -1
        try:
            self._file.write(data.replace(b'\n', b'\r\n'))
            return len(data)
        except OSError as error:
            self.error = str(error)
            return -1

    def flush(self) -> bool:
        if not self.is_open():
            return False
        try:
            self._file.flush()
            return True
        except OSError as error:
            self.error = str(error)
            return False

    def close(self) -> None:
        if self._file is not None:
            try:
                self._file.close()
            except OSError as error:
                self.error = str(error)


class FileLogStore:
    def make_directory(self, path: Path) -> bool:
        try:
            path.mkdir(parents=True, exist_ok=True)
            return True
        except OSError:
            return False

    def open_append_text(self, path: Path) -> FileLog:
        return FileLog(path)


class SessionLogger:
    """080d60/088280：无文本控件时只缓冲，连已打开的文件也不写。"""
    def __init__(self, now: Callable[[], datetime], *, view: LogView | None = None):
        self.now, self.view = now, view
        self.buffer = ''
        self.file: LogFile | None = None

    def append(self, message: str) -> str:
        moment = self.now()
        stamp = moment.strftime('%H:%M:%S') + f'.{moment.microsecond // 1000:03d}'
        line = f'[{stamp}] {message}'
        if self.view is None:
            if self.buffer:
                self.buffer += '\n'
            self.buffer += line
        else:
            self.view.append_plain_text(line)
            if self.file is not None and self.file.is_open():
                self.file.write(line.encode('utf-8', errors='replace'))
                self.file.write(b'\n')
                self.file.flush()
        return line

    def clear(self) -> None:
        self.buffer = ''
        if self.view is not None:
            self.view.clear()
        # 原 clear 没有关闭、清空或重新打开日志文件。


@dataclass
class SessionState:
    hwnd: int = 0
    frame_count: int = 0             # 主窗 +0xc0 低32位
    frame_auxiliary: int = 0         # +0xc4：逐字段展示字符串变更次数，沿用旧接口名
    elapsed_started_ms: int = 0      # +0xb0 的 elapsed timer 之纯源码基点
    current_spec: str = ''           # +0x70
    field_values: list[str] = field(default_factory=list)  # +0x88
    decoded_fields: dict[str, str] = field(default_factory=dict)  # +0xa0
    render_fingerprint: int = 0      # +0x398
    status: str = ''


def reset_for_start(state: SessionState, dispatcher: ActionDispatcher,
                    scheduler: SchedulerState, *, now_ms: int) -> None:
    """0a2070:156–174；只原地清已证实的状态，不替换对象。"""
    state.frame_count = state.frame_auxiliary = 0
    dispatch = dispatcher.state
    dispatch.success_count = 0
    for name in ('suppression_until', 'check_at', 'expect_off', 'failures',
                 'original_hold_ms', 'sent_generation'):
        getattr(dispatch.auras, name).clear()
    dispatch.local_gcd_until_ms = 0
    dispatch.last_sent_ms = 0
    scheduler.target_valid = -1
    dispatch.focus.last_action = ''
    dispatch.focus.last_switch_ms = 0
    dispatch.focus.skipped_count = 0
    scheduler.observed_focus = -1
    scheduler.focus_known = False
    state.elapsed_started_ms = now_ms
    # 保留 current_spec、字段缓存、auto_waiting、auto_protocol_active、seals、
    # KeySender 内部时间/计数/通道配置；这些不在此原生重置列表内。


def observe_spec(state: SessionState, spec: str | None, *, protocol: str,
                 field_count: int = 0) -> bool:
    """092c90/095410→098ea0 的字段缓存重建；不清施法压制或焦点/GCD。

    调用者先完成协议/行表校验，并负责规则方案、字段行/UI、设置恢复。
    readable 无有效行表时保留旧专精；legacy 未识别转为空专精。
    """
    if protocol not in ('legacy', 'readable'):
        raise NotImplementedError(f'未恢复协议: {protocol}')
    if field_count < 0:
        raise ValueError('field_count 必须非负')
    if protocol == 'readable' and not spec:
        return False
    new_spec = spec or ''
    if new_spec == state.current_spec:
        return False
    state.current_spec = new_spec
    state.field_values[:] = [''] * field_count
    state.decoded_fields.clear()
    state.render_fingerprint = 0
    return True


class SessionRuntime:
    """可作为 game_windows.MonitorRuntime；依赖显式定时器和日志存储。

    应由外层顺序调用（Qt 原版在 GUI 线程执行）。start/stop 是分开的
    幂等接口，toggle 语义留给 WindowMonitor，不暗中操作任何用户窗口。
    """
    def __init__(self, dispatcher: ActionDispatcher, scheduler_state: SchedulerState,
                 timer: Timer, logger: SessionLogger, store: LogStore, *,
                 application_dir: Path, environment: Mapping[str, str],
                 monotonic_ms: Callable[[], int], state: SessionState | None = None,
                 window_label: Callable[[int], str] | None = None):
        self.dispatcher, self.scheduler_state = dispatcher, scheduler_state
        self.timer, self.logger, self.store = timer, logger, store
        self.application_dir, self.environment = Path(application_dir), environment
        self.monotonic_ms = monotonic_ms
        self.state = state if state is not None else SessionState()
        self.window_label = window_label

    def is_active(self) -> bool:
        return self.timer.is_active()

    def start(self, hwnd: int, interval_ms: int = 25) -> None:
        if self.is_active():
            return
        if not hwnd:
            self.state.status = '请先选择一个目标窗口'
            return
        self.state.hwnd = hwnd
        reset_for_start(self.state, self.dispatcher, self.scheduler_state, now_ms=self.monotonic_ms())
        home = self.environment.get('WOWBUDDY_HOME', '')
        root = self.application_dir
        if home and self.store.make_directory(Path(home)):
            root = Path(home)
        logs = root / 'logs'
        self.store.make_directory(logs)  # 原版忽略此返回值，继续尝试 open。
        if self.logger.file is not None:
            self.logger.file.close()
            self.logger.file = None
        filename = 'monitor_' + self.logger.now().strftime('%Y%m%d_%H%M%S') + '.log'
        self.logger.file = self.store.open_append_text(logs / filename)
        if self.logger.file.is_open():
            self.logger.append(f'=== 日志文件：{self.logger.file.path} ===')
        else:
            self.logger.append(f'!! 日志文件打不开：{self.logger.file.path}')
        self.timer.start(interval_ms)
        # 完整原版启动行需要 UI 下拉框 currentText。无显式标签时不猜测。
        if self.window_label is not None:
            self.logger.append(f'已开始监控 · 目标窗口 {self.window_label(hwnd)}（0x{hwnd:x}）')

    def stop(self) -> None:
        if not self.is_active():
            return
        self.timer.stop()
        if self.logger.file is not None:
            self.logger.append('已停止监控')
            self.logger.file.close()
            self.logger.file = None
        self.state.status = '已停止'
        # 停止不清 HWND/账本/计数/焦点/专精，只有再次 start 才执行上述重置。
