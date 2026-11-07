"""Native main-window behavior, with external actions explicitly injected.

The Qt subclass calls handle_change_event/handle_show_event AFTER its base
implementation. There is deliberately no closeEvent or resizeEvent override.
"""
from dataclasses import dataclass
import math

WINDOW_TITLE = "WOW战斗助手"
WEBSITE_URL = "https://wowbuddy.cn"
TRAY_TOOLTIP = "WOW战斗助手（运行中）"
TOPMOST_HINT = 0x40000
INITIAL_FLAGS = 0x801 | TOPMOST_HINT
MINIMUM_SIZE = (1160, 740)
INITIAL_SIZE = (1330, 830)
TITLEBAR_HEIGHT = 48
TRAY_ACTION_LABELS = ("显示主界面", "停止/开始监控", "退出", "切换置顶")


@dataclass
class NoticeState:
    title_minimize_shown: bool = False
    window_minimize_shown: bool = False


_PROCESS_NOTICES = NoticeState()


@dataclass(frozen=True)
class ScreenRect:
    left: int
    top: int
    width: int
    height: int


def round_global_coordinate(value):
    """0a1fc0: nearest, ties away from zero; saturating signed 32-bit."""
    value = float(value)
    if math.isnan(value):
        return 2147483647
    adjusted = value - 0.5 if value < 0 else value + 0.5
    return int(max(-2147483648, min(2147483647, adjusted)))


def clamp_drag_position(position, window_size, available):
    """0880d0 uses QRect's INCLUSIVE right/bottom; height is irrelevant."""
    if available is None:
        return tuple(position)
    x, y = position
    right = available.left + available.width - 1
    bottom = available.top + available.height - 1
    return (max(available.left - 60, min(x, right + 60 - window_size[0])),
            max(available.top, min(y, bottom - 48)))


def _integer(value):
    return int(value.value) if hasattr(value, "value") else int(value)


def _xy(point):
    return (point.x(), point.y())


def _qt_available(probe):
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QGuiApplication
    screen = QGuiApplication.screenAt(QPoint(*probe)) or QGuiApplication.primaryScreen()
    if screen is None:
        return None
    rect = screen.availableGeometry()
    return ScreenRect(rect.left(), rect.top(), rect.width(), rect.height())


class WindowShell:
    """No tray/browser is created and no quit action occurs without callbacks.

    window, monitor_timer and tray may be duck-typed fakes. A real tray is
    supplied by the caller. close() only releases this adapter's connections.
    """

    def __init__(self, window, *, monitor_timer, tray, on_closed=None,
                 on_open_url=None, on_log=None, notice_state=None,
                 on_toggle_monitor=None, on_quit=None, on_native_show=None,
                 available_screen=None):
        self.window, self.monitor_timer, self.tray = window, monitor_timer, tray
        self.on_closed, self.on_open_url, self.on_log = on_closed, on_open_url, on_log
        self.on_toggle_monitor, self.on_quit = on_toggle_monitor, on_quit
        self.on_native_show = on_native_show
        self.notices = notice_state if notice_state is not None else _PROCESS_NOTICES
        self.available_screen = available_screen or _qt_available
        self.drag_active = False
        self.drag_offset = (0, 0)
        self._connections = []
        self._filtered = []
        self._filter = None
        self.tray_available = True
        self.notice_title = WINDOW_TITLE
        self.website_url = WEBSITE_URL

    def configure_window(self):
        """Explicit setup, before showing; layout remains caller-owned."""
        from PySide6.QtCore import Qt
        self.window.setWindowTitle(WINDOW_TITLE)
        self.window.setWindowFlags(Qt.WindowType(INITIAL_FLAGS))
        self.window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.window.setMinimumSize(*MINIMUM_SIZE)
        self.window.resize(*INITIAL_SIZE)

    def _connect(self, signal, callback):
        # Adapt clicked(bool)/triggered(bool) without leaking their argument.
        def slot(*unused):
            callback()
        signal.connect(slot)
        self._connections.append((signal, slot))

    def bind_buttons(self, *, website=None, minimize=None, close=None, pin=None):
        for button, callback in ((website, self.open_website), (minimize, self.minimize_to_tray),
                                 (close, self.close_button), (pin, self.toggle_topmost)):
            if button is not None:
                self._connect(button.clicked, callback)

    def bind_tray(self, *, show=None, monitor=None, quit=None, pin=None):
        """Bind existing actions. Visibility remains an explicit caller decision."""
        self.tray.setToolTip(TRAY_TOOLTIP)
        self.tray.activated.connect(self.tray_activated)
        self._connections.append((self.tray.activated, self.tray_activated))
        for action, callback in ((show, self.show_main), (monitor, self.toggle_monitor),
                                 (quit, self.request_quit), (pin, self.toggle_topmost)):
            if action is not None:
                self._connect(action.triggered, callback)

    def _log(self, text):
        if self.on_log is not None:
            self.on_log(text)

    def open_website(self):
        if self.on_open_url is None:
            raise RuntimeError("on_open_url callback is required")
        self.on_open_url(self.website_url)
        self._log(f"打开官网 {self.website_url}")

    def _notice(self, text):
        from PySide6.QtWidgets import QSystemTrayIcon
        self.tray.showMessage(self.notice_title, text, QSystemTrayIcon.MessageIcon.Information, 3000)

    def minimize_to_tray(self):
        if not self.tray_available:
            self.window.showMinimized()
            return
        self.window.hide()
        if not self.notices.title_minimize_shown:
            self._notice("已收进托盘。单击托盘图标恢复界面。")
            self.notices.title_minimize_shown = True

    def close_button(self):
        self.monitor_timer.stop()
        self.window.close()
        if self.on_closed is not None:
            self.on_closed()

    def show_main(self):
        self.window.showNormal()

    def toggle_monitor(self):
        if self.on_toggle_monitor is None:
            raise RuntimeError("on_toggle_monitor callback is required")
        self.on_toggle_monitor()

    def request_quit(self):
        if self.on_quit is None:
            raise RuntimeError("on_quit callback is required")
        self.on_quit()

    def tray_activated(self, reason):
        if _integer(reason) in (2, 3):
            if not self.window.isMinimized() and self.window.isVisible():
                self.window.hide()
            else:
                self.window.showNormal()

    def toggle_topmost(self):
        flags = self.window.windowFlags()
        new_value = _integer(flags) ^ TOPMOST_HINT
        self.window.setWindowFlags(type(flags)(new_value))
        self.window.showNormal()
        self._log("窗口置顶：开" if new_value & TOPMOST_HINT else "窗口置顶：关")
        return bool(new_value & TOPMOST_HINT)

    def handle_change_event(self, event_type):
        """Call AFTER super().changeEvent(event), passing event.type()."""
        state = self.window.windowState()
        if self.tray_available and _integer(event_type) == 105 and _integer(state) & 1:
            self.window.setWindowState(type(state)(_integer(state) & ~1))
            self.window.hide()
            if not self.notices.window_minimize_shown:
                self._notice("已最小化到托盘。单击托盘图标恢复界面。")
                self.notices.window_minimize_shown = True

    def _clamp(self, position):
        size = self.window.size()
        width = size.width()
        probe = (position[0] + width // 2, position[1] + 10)
        return clamp_drag_position(position, (width, size.height()), self.available_screen(probe))

    def handle_show_event(self):
        """Call AFTER super().showEvent(event). Optional native hook is explicit."""
        self.window.move(*self._clamp(_xy(self.window.pos())))
        if self.on_native_show is not None:
            self.on_native_show(self.window)

    def handle_mouse(self, *, on_title, event_type, global_position, button=0, buttons=0):
        """08b600 policy. True consumes the event; release returns False."""
        if not on_title:
            return False
        kind = _integer(event_type)
        if kind == 2 and _integer(button) == 1:
            self.drag_active = True
            position = tuple(round_global_coordinate(v) for v in global_position)
            origin = _xy(self.window.frameGeometry().topLeft())
            self.drag_offset = tuple(a - b for a, b in zip(position, origin))
            handle = self.window.windowHandle()
            if handle is not None:
                handle.startSystemMove()
            return True
        if kind == 5 and self.drag_active and _integer(buttons) & 1:
            position = tuple(round_global_coordinate(v) - delta
                             for v, delta in zip(global_position, self.drag_offset))
            self.window.move(*self._clamp(position))
            return True
        if kind == 3:
            self.drag_active = False
        return False

    def attach_titlebar(self, titlebar):
        """Native installs filters on TitleBar and its direct QLabel children."""
        from PySide6.QtCore import QObject
        from PySide6.QtWidgets import QLabel, QPushButton, QWidget
        if self._filter is not None:
            raise RuntimeError("titlebar already attached")
        shell = self

        class TitleFilter(QObject):
            def eventFilter(self, watched, event):
                kind = _integer(event.type())
                if kind not in (2, 3, 5):
                    return False
                on_title = watched is titlebar or (
                    isinstance(watched, QWidget) and watched.parentWidget() is titlebar
                    and not isinstance(watched, QPushButton))
                return shell.handle_mouse(on_title=on_title, event_type=kind,
                                          global_position=_xy(event.globalPosition()),
                                          button=event.button(), buttons=event.buttons())

        self._filter = TitleFilter(self.window)
        self._filtered = [titlebar] + [c for c in titlebar.children() if isinstance(c, QLabel)]
        for widget in self._filtered:
            widget.installEventFilter(self._filter)

    def close(self):
        """Idempotent adapter cleanup; does not close window, stop timer or quit."""
        for signal, slot in self._connections:
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        self._connections.clear()
        for widget in self._filtered:
            try:
                widget.removeEventFilter(self._filter)
            except RuntimeError:
                pass
        self._filtered.clear()
        if self._filter is not None:
            self._filter.deleteLater()
            self._filter = None
        self.drag_active = False
