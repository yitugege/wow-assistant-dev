"""Qt桌面集成与显式限定测试程序范围的更新交接；不是最终完整验收。"""
from __future__ import annotations

from datetime import datetime
from dataclasses import replace
from pathlib import Path
import ntpath
import sys
import time

from PySide6.QtCore import Qt, QTimer, QSignalBlocker, QUrl, QDateTime
from PySide6.QtGui import QDesktopServices, QPainter
from PySide6.QtWidgets import (QWidget, QLabel, QFrame, QVBoxLayout, QSlider,
    QSystemTrayIcon, QMenu, QApplication, QStyle)

from .assets import Assets
from .controller import FrameController
from .display_schema import blank_schema
from .old_protocol import OldFrame
from .dispatch import ActionDispatcher
from .game_windows import WindowMonitor, find_game_window
from .hub_sync import HubSynchronizer, LocalFileBackend, REFRESH_INTERVAL_MS
from .expressions import EvaluationContext
from .presentation import (availability, candidate_text, send_display, frame_status,
                           DiagnosticThrottle, NoFiducialThrottle, success_count_text, statistics_text, fps_text)
from .qt_network import QtHubClient
from .runtime import MonitoringLoop
from .scheduler import Scheduler
from .session import SessionRuntime, SessionLogger, FileLogStore
from .threshold_widgets import ThresholdPanel
from .swatch_strip import SwatchItem, frame_color_hash
from .field_cell import FieldCell, field_tooltip, field_grid_columns
from .ui_layout import build_ui
from .updater import CURRENT_VERSION
from .windows_keys import KeySender


class QtTimerAdapter:
    def __init__(self, timer): self.timer = timer
    def is_active(self): return self.timer.isActive()
    def start(self, interval_ms): self.timer.start(interval_ms)
    def stop(self): self.timer.stop()


class QtLogView:
    def __init__(self, widget): self.widget = widget
    def append_plain_text(self, text): self.widget.appendPlainText(text)
    def clear(self): self.widget.clear()


class QuietTray:
    """离屏验证时的显式托盘替身，不创建系统图标。"""
    def __init__(self): self.notices = []
    def showMessage(self, *args): self.notices.append(args)


def clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().hide()
            item.widget().deleteLater()
        elif item.layout():
            clear_layout(item.layout())


class AssistantWindow(QWidget):
    """依赖显式注入，离屏测试不构造真实Windows捕获或发键后端。"""
    def __init__(self, assets: Assets, settings, *, window_backend, capture, key_backend,
                 application_dir: Path, environment=None, clock_ms=None, monotonic_ms=None,
                 now=None, log_store=None, network_enabled=True, automatic=True,
                 tray_enabled=True, hub_files=None, addon_files=None, addon_dialogs=None,
                 update_client=None, update_handoff=None, application_arguments=None,
                 native_window_identity=None, addon_update_client=None, startup_record=None,
                 startup_log_path=""):
        super().__init__()
        self.assets, self.settings = assets, settings
        self.application_dir = Path(application_dir)
        self._closed = False
        self._network_enabled = network_enabled
        self.startup_record = startup_record
        self.startup_diagnostics = []
        self.update_handoff = update_handoff
        self.application_arguments = tuple(application_arguments if application_arguments is not None else sys.argv)
        self._handoff_busy = False
        self.native_window_identity = native_window_identity
        self.clock_ms = clock_ms or (lambda: time.time_ns() // 1_000_000)
        self.monotonic_ms = monotonic_ms or (lambda: time.monotonic_ns() // 1_000_000)
        self._last_result = None
        self._field_identity = None
        self._display_revision = 0
        self._threshold_identity = None
        self._field_widgets = []
        self._swatch_hash = 0
        self._message_cursor = 0
        self.no_fiducial = NoFiducialThrottle()
        self.diagnostics = DiagnosticThrottle()
        snapshot = settings.snapshot()
        self.ui = build_ui(self, app_name="WOW战斗助手", version=CURRENT_VERSION,
                           website="wowbuddy.cn", auto_update=snapshot.update_auto_check)
        self.ui.addon_path.setText(snapshot.addon_last_dir)
        self.ui.poll_interval_spin.setValue(snapshot.poll_interval_ms)
        self.ui.send_interval_spin.setValue(snapshot.send_interval_ms)
        self.poll_timer = QTimer(self)
        self.poll_timer.setTimerType(Qt.PreciseTimer)
        # 原07BF40初始化间隔，08D330在valueChanged中直接更新同一计时器。
        self.poll_timer.setInterval(self.ui.poll_interval_spin.value())
        self.ui.poll_interval_spin.valueChanged.connect(self.poll_timer.setInterval)
        self.watch_timer = QTimer(self)
        self.watch_timer.setInterval(WindowMonitor.watch_interval_ms)
        self.hub_timer = QTimer(self)
        self.hub_timer.setInterval(REFRESH_INTERVAL_MS)
        self.pipeline = assets.pipeline()
        self.sender = KeySender(key_backend, hwnd=0, force_background=True,
                                allow_activation=False, interval_ms=30, hold_ms=30)
        self.dispatcher = ActionDispatcher(self.sender)
        self.scheduler = Scheduler(self.pipeline, self.dispatcher, self.clock_ms)
        self.logger = SessionLogger(now or datetime.now, view=QtLogView(self.ui.log_view))
        self.session = SessionRuntime(self.dispatcher, self.scheduler.state,
            QtTimerAdapter(self.poll_timer), self.logger, log_store or FileLogStore(),
            application_dir=Path(application_dir), environment=environment or {},
            monotonic_ms=self.monotonic_ms,
            window_label=lambda hwnd: self.ui.window_combo.currentText())
        self.monitor = WindowMonitor(window_backend, self.session,
                                     interval_ms=self.ui.poll_interval_spin.value(),
                                     on_selection=self._monitor_selection,
                                     on_diagnostic=self._record_window_diagnostic)
        # 原082920的路径初始化早于循环库缓存读取及首次网络请求。
        self._install_addon_actions(window_backend, environment or {}, addon_files, addon_dialogs)
        self.hub = HubSynchronizer(hub_files or LocalFileBackend(), application_dir=str(application_dir),
                                   environment=environment or {})
        self._hub_transport_status = self.hub.status
        self.controller = FrameController(self.pipeline, self.hub.hub,
            selection_settings=snapshot.selection_settings, switch_settings=snapshot.switch_settings,
            persist=settings.apply_change, load_switches=settings.load_switches,
            load_spec_selection=settings.load_spec_selection,
            on_message=self.logger.append)
        self.threshold_panel = ThresholdPanel(self.ui.threshold_grid, self.ui.threshold_hint,
            self.ui.threshold_host, on_change=self.controller.change_slider)
        self.hub.on_changed = self._hub_changed
        # 07BF40先连接A6A50→09DD90，再04F960读缓存；成功会同步通知。
        cached = self.hub.load_cache()
        if not cached.accepted:
            # 原失败读取不发changed；仍保留同步器的解析状态。
            self.controller.hub = self.hub.hub
            self._hub_transport_status = self.hub.status
        self.hub_client = QtHubClient(self.hub, self) if network_enabled else None
        self.loop = MonitoringLoop(self.session, capture, self.controller, self.scheduler,
            is_window=window_backend.is_window, send_interval_ms=self.ui.send_interval_spin.value)
        self.poll_timer.timeout.connect(self.poll_once)
        self.watch_timer.timeout.connect(self.watch_once)
        self.ui.refresh_button.clicked.connect(self.refresh_windows)
        self.ui.monitor_button.clicked.connect(self.toggle_monitor)
        self.ui.rotation_combo.currentIndexChanged.connect(self.select_rotation)
        self.ui.hub_pull_button.clicked.connect(self.refresh_hub)
        self.hub_timer.timeout.connect(self._periodic_library_refresh)
        self.ui.clear_log_button.clicked.connect(self.logger.clear)
        self.ui.show_all_check.toggled.connect(self._show_all_changed)
        self.ui.auto_update_check.toggled.connect(settings.save_auto_check)
        if network_enabled:
            # 07BF40先发循环库请求，再启动周期计时器、安装插件更新及监视/托盘。
            self.refresh_hub()
            self.hub_timer.start()
        self._install_addon_updates(window_backend, environment or {}, addon_update_client)
        self._install_updates(application_dir, environment or {}, snapshot, update_client)
        self._configure_unfinished_controls()
        self.tray = None
        self.shell = None
        if automatic:
            # 07BF40:660–661：启动5秒监视计时器后立即检查一次，
            # 早于托盘装配和末尾09EE50刷新；不是启动阶段4或--auto的替代。
            self.watch_timer.start()
            self.watch_once()
        self._install_shell(tray_enabled)
        self.refresh_windows()
        # 07BF40:900–918→098BE0：末尾刷新之后无条件建立空专精通用格。
        # 仅用于布局，不制造采样成功帧或候选输入。
        self.controller.display_frame = blank_schema(self.pipeline, OldFrame("layout_only"), "")
        self.controller.display_revision += 1
        self._display_revision = self.controller.display_revision
        self._render_fields(self.controller.display_frame)
        self._render_selection()
        self._render_hub_status()
        self.logger.append("界面就绪。选好目标窗口后点「开始监控」。")
        if startup_log_path:
            self.logger.append(f"启动日志：{startup_log_path}（启动/闪退类问题发这个文件）")

    def _configure_unfinished_controls(self):
        # 这些入口的业务尚未接入；不能让点击表现成虚假的成功。
        self.ui.update_apply_button.setEnabled(False)
        self.ui.update_apply_button.setToolTip(self._update_scope_error())
        self.ui.update_check_button.setEnabled(self.update_client is not None)
        if self.update_client is None:
            self.ui.update_status.setText("程序更新：离线模式")
        self.ui.hub_pull_button.setEnabled(self._network_enabled)

    def _install_updates(self, application_dir, environment, snapshot, client):
        from .qt_updater import QtUpdaterClient
        self.update_client = client
        if client is None and self._network_enabled:
            self.update_client = QtUpdaterClient(self, env=environment,
                application_dir=str(application_dir),
                auto_update=self.ui.auto_update_check.isChecked,
                clock=lambda: (self.clock_ms(), datetime.now().strftime("%H:%M")))
        self.update_timer = QTimer(self)
        self.update_timer.setSingleShot(True)
        self._last_update_check_ms = snapshot.update_last_check_ms
        self.ui.update_check_button.clicked.connect(self.check_update)
        self.ui.update_apply_button.clicked.connect(self.download_update)
        self.update_timer.timeout.connect(lambda: self.check_update(manual=False))
        if self.update_client is not None:
            self.update_client.ui_changed.connect(self._render_update)
            self.update_client.log_message.connect(self.logger.append)
            self.update_client.adapter_error.connect(self._update_adapter_error)
            self.update_client.auto_download_requested.connect(self.download_update)
            self.update_client.verified.connect(self._update_verified)
            delay = snapshot.automatic_update_delay_ms(self.clock_ms())
            from .native_cli import parse_native_cli
            suppress = parse_native_cli(self.application_arguments).suppress_auto_update
            if delay is not None and not suppress:
                self.update_timer.start(delay)

    def check_update(self, checked=False, *, manual=True):
        if self.update_client is not None:
            self.update_client.check(manual=manual)

    def _render_update(self, state):
        self.ui.update_status.setText(state.text)
        self.ui.update_status.setStyleSheet(f"color: {state.color};")
        self.ui.update_check_button.setEnabled(state.check_enabled)
        self.ui.update_apply_button.setVisible(state.update_visible)
        self.ui.update_apply_button.setText(state.update_text)
        blocker = self._update_scope_error()
        self.ui.update_apply_button.setEnabled(state.update_enabled and not blocker and not self._handoff_busy)
        self.ui.update_apply_button.setToolTip(state.update_tooltip or blocker)
        self.ui.update_progress.setVisible(state.progress_visible)
        self.ui.update_progress.setRange(*state.progress_range)
        self.ui.update_progress.setValue(state.progress_value)
        if state.last_check_ms is not None and state.last_check_ms != self._last_update_check_ms:
            self.settings.save_last_check_ms(state.last_check_ms)
            self._last_update_check_ms = state.last_check_ms

    def _update_adapter_error(self, message):
        self.logger.append(message)
        self.ui.update_status.setText(message)

    def _update_scope_error(self):
        if self.update_client is None or self.update_handoff is None:
            return "更新交接未配置：需要明确指定本地测试 EXE"
        from .updater import resolve_target_path
        target = resolve_target_path(self.update_client.updater.env)
        expected = self.update_handoff.scope.executable
        if ntpath.normcase(ntpath.normpath(target)) != ntpath.normcase(ntpath.normpath(expected)):
            return "更新目标不属于此开发预览的测试 EXE 范围"
        return ""

    def download_update(self, checked=False):
        if self._handoff_busy:
            return
        # 原08ffb0先检查更新器busy，早退时不停止监控或修改日志。
        if self.update_client is not None and self.update_client.updater.active is not None:
            return
        blocker = self._update_scope_error()
        if blocker:
            self._update_adapter_error(blocker)
            return
        from .updater import replacement_blocker, resolve_target_path
        updater = self.update_client.updater
        blocker = replacement_blocker(resolve_target_path(updater.env), updater.fs)
        if blocker:
            # 原08ffb0在停监控及改变按钮之前执行目录写入预检。
            self.ui.update_status.setText(blocker)
            self.ui.update_status.setStyleSheet("color:#ffb02e;")
            self.logger.append("自动更新未完成：" + blocker)
            return
        # 090630：进入下载前停止当前监控；5秒窗口监视保持原有生命周期。
        if self.session.is_active():
            self.session.stop()
            self.logger.append("更新前已停止监控")
        self._render_monitor()
        self.update_client.download()

    def _update_verified(self, verified):
        blocker = self._update_scope_error()
        if blocker or self._handoff_busy:
            if blocker:
                self._update_adapter_error(blocker)
            return
        self._handoff_busy = True
        self.ui.update_check_button.setEnabled(False)
        self.ui.update_apply_button.setEnabled(False)
        try:
            result = self.update_handoff.execute(verified,
                application_arguments=self.application_arguments,
                quit_callback=QApplication.quit,
                on_status=self.ui.update_status.setText, on_log=self.logger.append)
            self.ui.update_status.setText(result.text)
            self.ui.update_status.setStyleSheet("color:#ffb02e;" if result.phase == "replacement_failed" else "color:#22e58b;")
        except (OSError, ValueError) as error:
            self._update_adapter_error(f"更新交接失败：{error}")
            self.ui.update_status.setStyleSheet("color:#ffb02e;")
        finally:
            self._handoff_busy = False
            self.ui.update_check_button.setEnabled(True)
            self.ui.update_apply_button.setEnabled(True)
            self.ui.update_progress.hide()

    def _install_addon_actions(self, windows, environment, files, dialogs):
        from .addon_actions import AddonActions, AddonDetector, LocalAddonFiles, QtAddonDialogs
        files = files if files is not None else LocalAddonFiles()
        self.addon_files = files
        dialogs = dialogs if dialogs is not None else QtAddonDialogs(self, self.ui.addon_detect_button)
        self.addons = AddonActions(self.settings, files, dialogs,
            package_provider=self._addon_package,
            on_path=self.ui.addon_path.setText, on_status=self.ui.addon_status.setText,
            on_log=self.logger.append, process_events=QApplication.processEvents)
        def running_executable():
            hwnd = find_game_window(windows, on_diagnostic=self._record_window_diagnostic)
            if not hwnd:
                return ""
            pid = windows.window_pid(hwnd)
            return windows.process_path(pid) if pid else ""
        self.addons.detector = AddonDetector(files, running_executable=running_executable,
            saved_roots=lambda: tuple(self.settings._read("game/roots", [], "strings")),
            installed_name=self.addons.installed_name, environment=environment)
        self.addons.initialize_path(self.ui.addon_path.text())
        self.ui.addon_path.textChanged.connect(self.addons.text_changed)
        self.ui.addon_path.editingFinished.connect(self.addons.finish_edit)
        self.ui.addon_detect_button.clicked.connect(self.addons.detect)
        self.ui.addon_detect_button.customContextMenuRequested.connect(self.addons.recent)
        self.ui.addon_browse_button.clicked.connect(self.addons.browse)
        self.ui.addon_install_button.clicked.connect(self.addons.install)
        self.ui.addon_clean_button.clicked.connect(self.addons.cleanup)

    def _addon_package(self):
        cache = self.application_dir / "addon.bin"
        return (cache if cache.exists() else self.assets.directory / "addon.bin").read_bytes()

    def _install_addon_updates(self, windows, environment, client):
        from .addon_update import SettingsPendingAddons, STARTUP_DELAY_MS
        from .addon_games import build_game_snapshot, scan_installed_name
        from .addon_hot_install import AddonReinstaller
        from .qt_addon_update import QtAddonUpdaterClient
        self.addon_update_client = client
        if client is None and self._network_enabled:
            self.addon_update_client = QtAddonUpdaterClient(self, env=environment,
                application_dir=str(self.application_dir), pending=SettingsPendingAddons(self.settings),
                games=lambda: build_game_snapshot(self.addon_files, windows, self.settings, environment),
                installed_name=lambda path: scan_installed_name(self.addon_files, path),
                install=AddonReinstaller(self.settings, self.addon_files, self._addon_package))
        self.addon_startup_timer = QTimer(self)
        self.addon_startup_timer.setSingleShot(True)
        self.addon_startup_timer.setInterval(STARTUP_DELAY_MS)
        # 原07BF40仅创建一个30分钟定时器；08D660依次刷新循环库和插件。
        self.addon_periodic_timer = self.hub_timer
        if self.addon_update_client is not None:
            self.addon_update_client.log_message.connect(self.logger.append)
            self.addon_update_client.adapter_error.connect(self.logger.append)
            self.addon_startup_timer.timeout.connect(self.addon_update_client.refresh)
            self.addon_startup_timer.start()
            if not self.hub_timer.isActive():
                self.hub_timer.start()

    def _install_shell(self, tray_enabled):
        from .window_shell import WindowShell
        if tray_enabled:
            self.tray = QSystemTrayIcon(self.style().standardIcon(QStyle.SP_ComputerIcon), self)
            self.tray.setToolTip(self.windowTitle())
            menu = QMenu(self)
            self.tray.setContextMenu(menu)
            self.tray.show()
        self.shell = WindowShell(self, monitor_timer=self.poll_timer, tray=self.tray or QuietTray(),
            on_closed=self.shutdown, on_open_url=lambda url: QDesktopServices.openUrl(QUrl(url)),
            on_log=self.logger.append, on_toggle_monitor=self.toggle_monitor, on_quit=QApplication.quit,
            on_native_show=self.native_window_identity.apply if self.native_window_identity else None)
        self.shell.configure_window()
        self.shell.attach_titlebar(self.ui.title_bar)
        self.shell.bind_buttons(website=self.ui.website_button, minimize=self.ui.minimize_button,
                                close=self.ui.close_button)
        if self.tray:
            show, monitor = menu.addAction("显示主界面"), menu.addAction("停止/开始监控")
            menu.addSeparator()
            self.shell.bind_tray(show=show,
                monitor=monitor, quit=menu.addAction("退出"),
                pin=menu.addAction("切换置顶"))

    def _record_window_diagnostic(self, text):
        """0B7F00→01CD40；缺startup sink时保留诊断，不误写发键日志。"""
        self.startup_diagnostics.append(text)
        if self.startup_record is not None:
            self.startup_record(text)

    def refresh_windows(self):
        self.monitor.refresh()
        self._render_windows()
        self._drain_monitor_messages()

    def _render_windows(self):
        with QSignalBlocker(self.ui.window_combo):
            self.ui.window_combo.clear()
            for window in self.monitor.windows:
                self.ui.window_combo.addItem(window.label, window.hwnd)
            self.ui.window_combo.setCurrentIndex(self.monitor.selected_index)

    def _monitor_selection(self, monitor, index):
        self._render_windows()

    def _drain_monitor_messages(self):
        for message in self.monitor.messages[self._message_cursor:]:
            self.logger.append(message)
        self._message_cursor = len(self.monitor.messages)

    def toggle_monitor(self):
        self.monitor.selected_index = self.ui.window_combo.currentIndex()
        self.monitor.interval_ms = self.ui.poll_interval_spin.value()
        self.monitor.toggle()
        self._drain_monitor_messages()
        self._render_monitor()

    def watch_once(self):
        self.monitor.interval_ms = self.ui.poll_interval_spin.value()
        # 原081970直接读取QComboBox；有效活动目标返回时不改用户当前选择。
        self.monitor.selected_index = self.ui.window_combo.currentIndex()
        previous = (self.monitor.windows, self.monitor.selected_index)
        self.monitor.tick()
        if previous != (self.monitor.windows, self.monitor.selected_index):
            self._render_windows()
        self._drain_monitor_messages()
        self._render_monitor()

    def auto_start_once(self):
        """081850：一次性 --auto；不刷新下拉框，不停止已经活动的监控。"""
        hwnd = find_game_window(self.monitor.backend, on_diagnostic=self._record_window_diagnostic)
        if not hwnd:
            self.logger.append("--auto：未找到魔兽窗口，请手动选择")
            return
        index = self.ui.window_combo.findData(hwnd)
        if index >= 0:
            self.ui.window_combo.setCurrentIndex(index)
        # 原生未在现有列表找到句柄也会对当前选择调用开始；不改成watch逻辑。
        if not self.session.is_active():
            self.toggle_monitor()

    def _render_monitor(self):
        self.ui.monitor_button.setText("停止监控" if self.session.is_active() else "开始监控")
        status = self.session.state.status or self.monitor.status
        if status:
            self.ui.status_label.setText(status)

    def select_rotation(self, index):
        key = self.ui.rotation_combo.itemData(index) if index >= 0 else ""
        self.controller.select(key or "")
        self._render_thresholds()
        self._render_hub_status()

    def _render_selection(self):
        selection = self.controller.selection
        with QSignalBlocker(self.ui.rotation_combo):
            self.ui.rotation_combo.clear()
            self.ui.rotation_combo.addItem("未选择（不自动发键）", "")
            for profile in selection.options:
                self.ui.rotation_combo.addItem(profile.display_name, profile.key)
                self.ui.rotation_combo.setItemData(self.ui.rotation_combo.count() - 1,
                                                  profile.summary, Qt.ToolTipRole)
            index = self.ui.rotation_combo.findData(selection.current_key)
            self.ui.rotation_combo.setCurrentIndex(max(index, 0))
            self.ui.rotation_combo.setEnabled(selection.enabled)
        self._render_thresholds()

        self._render_hub_status()

    def _render_hub_status(self):
        controller = self.controller
        hub, selection = controller.hub, controller.selection
        suffix = ""
        if hub.profiles:
            stamp = hub.generated_at
            date = QDateTime.fromString(stamp, Qt.ISODate)
            if date.isValid():
                stamp = date.toLocalTime().toString("MM-dd HH:mm")
            suffix = (f"　［本地快照 {stamp} · 联网检查中］" if hub.from_cache else
                      f"　［已联网 · 快照 {stamp}］")
        style = ""
        if selection.has_external_rules:
            profile = selection.active_profile
            if str(profile.spec_id) == controller.spec_id:
                text, style = f"已套用「{profile.engine_name}」", "color:#22e58b;"
            else:
                text = f"已选「{profile.engine_name}」—— 当前专精不是它，暂不生效"
                style = "color:#ffb02e;"
        else:
            text = controller.selection_status or self._hub_transport_status
        self.ui.hub_status.setText(text + suffix)
        self.ui.hub_status.setStyleSheet(style)

    def _render_thresholds(self):
        self.threshold_panel.render_controller(self.controller)

    def refresh_hub(self):
        if self.hub_client is not None:
            self.hub_client.refresh()

    def _periodic_library_refresh(self):
        self.refresh_hub()
        if self.addon_update_client is not None:
            self.addon_update_client.refresh()

    def _hub_changed(self, hub, status):
        self._hub_transport_status = status
        self.controller.update_hub(hub)
        self._render_selection()
        return self.controller.hub

    def poll_once(self):
        result = self.loop.poll()
        self._last_result = result
        self._render_monitor()
        if result.tick is None:
            if result.status == "descriptor_unverified":
                self.ui.status_label.setText(self.session.state.status)
            elif result.status == "minimized":
                # 092c90 -> 08dbf0：只改展示标签，不清上一有效帧的内部状态。
                self.ui.spec_label.setText("专精：等待有效画面")
            return result
        decision = result.tick.decision
        self._render_frame_headers(decision.frame)
        revision = getattr(self.controller, "display_revision", 0)
        if revision != self._display_revision:
            self._display_revision = revision
            self._field_identity = None
            display_frame = self.controller.display_frame
            if display_frame is not None:
                self._render_fields(display_frame)
                if not display_frame.spec_id:
                    self.ui.field_count_label.setText("字段：仅通用")
            self._render_selection()
            if self.controller.spec_id:
                self._render_spec_name(self.controller.spec_id, include_id=decision.frame.protocol != "readable")
        if not decision.frame.ok:
            status = decision.frame.status
            self.ui.status_label.setText({"no_marker": "未找到插件色块：请确认已进入角色且插件已启用",
                "version_mismatch": "插件版本未匹配", "unknown_spec": "未识别到有效的无限服职业 ID",
                "out_of_bounds": "读取失败：字段条超出窗口"}.get(status, status))
            if status == "no_marker":
                self.ui.spec_label.setText("专精：等待有效画面")
                self.ui.calibration_label.setText("基准标记：未找到，已停发")
                self.ui.calibration_label.setStyleSheet("color:#ffb02e;")
                message = self.no_fiducial.emit(now_ms=self.clock_ms())
                if message is not None:
                    self.logger.append(message)
            elif status == "version_mismatch":
                self.ui.spec_label.setText("专精：等待有效画面")
            elif status == "unknown_spec":
                if decision.frame.protocol == "old":
                    self.ui.spec_label.setText("专精：未识别（已停发）")
                    self.ui.spec_label.setStyleSheet("color:#ff4d4d;font-weight:bold;")
                else:
                    self.ui.spec_label.setText("专精：等待有效画面")
                    self.ui.status_label.setText("readable 行表未匹配")
            elif status == "out_of_bounds" and decision.frame.protocol == "readable":
                self.ui.status_label.setText("读取失败：readable 条超出窗口")
            return result
        self._render_selection()
        self._render_fields(decision.frame)
        self.ui.sent_label.setText(str(result.displayed_success_count))
        elapsed = result.elapsed_ms if result.elapsed_ms is not None else 0
        self.ui.elapsed_label.setText(str(elapsed // 1000))
        self.ui.fps_label.setText(fps_text(self.session.state.frame_count, elapsed))
        self.ui.frame_status_label.setText(statistics_text(self.session.state.frame_count,
                                                          self.session.state.frame_auxiliary, elapsed))
        self.ui.suggestions.setPlainText(candidate_text(decision.candidates,
            now_ms=result.tick.display_now_ms, suppression_until=result.tick.display_suppression_until))
        spec = self.pipeline.engine.specs.get(decision.frame.spec_id)
        available = availability(spec, decision.fields)
        self.ui.available_count.setText(available.summary)
        self.ui.available_details.setText(available.detail_html)
        if result.tick.dispatch is not None:
            if result.tick.dispatch.status in ('sent','failed'):
                self.ui.send_status_label.setText(success_count_text(self.dispatcher.state.success_count))
            display = send_display(result.tick.selected, result.tick.dispatch,
                                   focus_known=self.scheduler.state.focus_known)
            if display.status is not None:
                self.ui.status_label.setText(display.status)
            if display.log is not None:
                self.logger.append(display.log)
        else:
            display = frame_status(result.status, decision.candidates,
                send_interval_ms=self.ui.send_interval_spin.value(),
                local_gcd_active=result.tick.local_gcd_active,
                plugin_gcd=EvaluationContext(decision.fields).flag("gcd"))
            self.ui.status_label.setText(display.status)
            if display.diagnostic_reason:
                token = self.pipeline.engine.roles.get(decision.frame.spec_id, {}).get("token", "")
                message = self.diagnostics.emit(display.diagnostic_reason, decision.frame.spec_id,
                    decision.fields, now_ms=self.clock_ms(), spec=spec,
                    talent_key=token + "_talents" if token else "")
                if message:
                    self.logger.append(message)
        return result

    def _render_spec_name(self, spec_id, *, include_id=True):
        name = self.assets.contract.get("classNames", {}).get(spec_id, spec_id)
        self.ui.spec_label.setText(f"专精：{name}" + (f"（ID {spec_id}）" if include_id else ""))

    def _render_frame_headers(self, frame):
        """原版在完整字段采样前写入的标签；失败不能统一延迟到ok分支。"""
        geometry = frame.geometry
        if geometry is None or frame.status == "no_marker":
            return
        green, red = "color:#22e58b;", "color:#ff4d4d;font-weight:bold;"
        if frame.protocol == "old":
            self.ui.calibration_label.setText(f"基准标记：({geometry.anchor_x},{geometry.anchor_y}) 已校准  缩放×{geometry.scale:.4f}  格距 {geometry.pitch:.2f}px")
            if frame.status == "version_mismatch":
                self.ui.addon_version_label.setText(f"⚠ 插件版本 {frame.version_code} ≠ 读取端期望 {self.pipeline.old.expected_version}（已停发，请在游戏内 /reload）")
                self.ui.addon_version_label.setStyleSheet(red)
            elif frame.ok or frame.status == "unknown_spec" or frame.spec_id:
                self.ui.addon_version_label.setText(f"插件版本 {frame.version_code} ✓ 与读取端一致")
                self.ui.addon_version_label.setStyleSheet(green)
            # 通用字段越界发生在版本显示之前；只更新上面的校准标签。
            if frame.spec_id:
                self.ui.spec_label.setStyleSheet("")
        else:
            self.ui.calibration_label.setText(f"readable 条：pitch {geometry.pitch:.2f}px  锚({geometry.anchor_x},{geometry.anchor_y})")
            if frame.status == "unknown_spec":
                self.ui.addon_version_label.setText("readable 行表未匹配（已停发）")
                self.ui.addon_version_label.setStyleSheet(red)
            else:
                version = self.pipeline.readable.contract.get("header", {}).get("addonVersionCode", 0)
                self.ui.addon_version_label.setText(f"readable 插件 {version} ✓")
                self.ui.addon_version_label.setStyleSheet(green)
                self._render_spec_name(frame.spec_id, include_id=False)
                self.ui.spec_label.setStyleSheet("")
        self.ui.calibration_label.setStyleSheet(green)

    def _show_all_changed(self):
        # 08CFE0→098BE0：按当前专精重新读取旧协议契约，不复用上帧行表。
        # 098EA0清空读数字典、重建空字段格并刷新阈值；等下一帧填入读数。
        self.pipeline.rebuild_old_descriptors(self.controller.spec_id)
        self.controller.fields.clear()
        self.controller.display_frame = blank_schema(
            self.pipeline, OldFrame("layout_only"), self.controller.spec_id)
        self.controller.display_revision += 1
        self.loop.synchronize_display_cache()
        self._display_revision = self.controller.display_revision
        self._field_identity = None
        self._render_fields(self.controller.display_frame)
        if self.controller.spec_id:
            self._render_spec_name(self.controller.spec_id)
            count = len(self.controller.display_frame.rows)
            self.ui.field_count_label.setText(f"字段：{count} / {count} 格")
        else:
            self.ui.spec_label.setText("专精：未识别")
        self.controller.refresh_thresholds()
        self._render_thresholds()

    def _render_fields(self, frame):
        # 095410只更新本次采样到的槽；同身份切换协议不重建098EA0的表。
        # 保留旧表元数据、过滤规则及未被本帧覆盖的尾部读数。
        if self._field_identity is None or getattr(self, "_field_spec", None) != frame.spec_id:
            self._field_rows = tuple(frame.rows)
            self._field_spec = frame.spec_id
        elif frame.ok:
            updates = {row.index: row.decoded for row in frame.rows}
            self._field_rows = tuple(replace(row, decoded=updates[row.index])
                                     if row.index in updates else row for row in self._field_rows)
        rows = [row for row in self._field_rows if row.applicable or self.ui.show_all_check.isChecked()]
        swatches = tuple(SwatchItem(row.decoded.raw_rgb, row.label,
            row.decoded.value_text, row.index + 1) for row in rows)
        identity = tuple((row.index, row.key, row.label, row.type, row.is_common, row.note) for row in rows)
        if identity != self._field_identity:
            clear_layout(self.ui.field_grid)
            self._field_widgets = []
            viewport = self.ui.field_scroll.viewport()
            columns = field_grid_columns(len(rows), viewport.width(), viewport.height())
            for index, row in enumerate(rows):
                tile = FieldCell(row.index + 1, row.label, row.is_common)
                tile.setToolTip(field_tooltip(row.index + 1, row.label, row.key, row.type, row.note))
                self.ui.field_grid.addWidget(tile, index // columns, index % columns)
                self._field_widgets.append(tile)
            self._field_identity = identity
            # 098EA0重建列表时清哈希并主动设置色块条。
            self._swatch_hash = 0
            self.ui.field_canvas.set_items(swatches)
        if frame.ok:
            sampled_argb = getattr(frame, "sampled_argb", ())
            digest = (frame_color_hash(sampled_argb, native_argb=True) if sampled_argb
                      else frame_color_hash(frame.raw_colors))
            if digest != self._swatch_hash:
                self._swatch_hash = digest
                self.ui.field_canvas.set_items(swatches)
        sampled_indices = {row.index for row in frame.rows} if frame.ok else set()
        for widget, row in zip(self._field_widgets, rows):
            if row.index not in sampled_indices:
                continue
            text = row.decoded.value_text
            if row.decoded.detail:
                text += " " + row.decoded.detail
            widget.set_value(row.decoded.raw_rgb, text)
        self.ui.field_count_label.setText(f"字段：{len(rows)} / {len(self._field_rows)} 格" if frame.spec_id else "字段：仅通用")

    def shutdown(self):
        if self._closed:
            return
        self._closed = True
        self.watch_timer.stop()
        self.hub_timer.stop()
        self.update_timer.stop()
        # 原主窗析构不调用监控开关槽，不追加“已停止监控”。
        # 退出只释放资源；手动停止仍由SessionRuntime.stop记录状态和日志。
        if self.poll_timer.isActive():
            self.poll_timer.stop()
        if self.logger.file is not None:
            self.logger.file.close()
            self.logger.file = None
        if self.hub_client:
            self.hub_client.close()
        if self.update_client:
            self.update_client.close()
        self.addon_startup_timer.stop()
        self.addon_periodic_timer.stop()
        if self.addon_update_client:
            self.addon_update_client.close()
        if self.tray:
            self.tray.hide()
        if self.shell:
            self.shell.close()
        close = getattr(getattr(getattr(self.loop.capture, "dxgi", None), "backend", None), "close", None)
        if close:
            close()
        self.settings.sync()

    def closeEvent(self, event):
        self.shutdown()
        super().closeEvent(event)

    def changeEvent(self, event):
        super().changeEvent(event)
        if getattr(self, "shell", None):
            self.shell.handle_change_event(event.type())

    def showEvent(self, event):
        super().showEvent(event)
        if getattr(self, "shell", None):
            self.shell.handle_show_event()

    def paintEvent(self, event):
        super().paintEvent(event)
        if getattr(self, "ui", None) is not None:
            from .window_paint import paint_top_accent
            painter = QPainter(self)
            try:
                paint_top_accent(painter, self.rect())
            finally:
                painter.end()
