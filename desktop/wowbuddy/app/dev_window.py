"""独立开发版主窗口：在 AssistantWindow 上叠加无人托管、更新和插件管理。

由 run_dev.launch 构造；启动参数通过 DevLaunchOptions 显式传入，不再依赖闭包。
"""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import sys

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication, QCheckBox, QFileDialog, QInputDialog, QMenu, QPushButton
from wowbuddy.app.qt_app import AssistantWindow
from wowbuddy.dev_library import profile_action_gaps, read_local_library
from wowbuddy.win32.capture import DESKTOP_HOLD_TEXT, WindowCapture
from wowbuddy.engine.character_state import (CharacterFrameFreshness, STALE_FRAME, decode_character_session,
                                      decode_level_progress, decode_travel_identity)
from wowbuddy.automation.manual_routes import (manual_camp_road, parse_fixed_camp, parse_manual_connection,
                                               parse_manual_route, parse_patrol_route)
from wowbuddy.automation.vendor_run import VendorRun
from wowbuddy.automation.unattended import FrameAction, FrameInput, UnattendedController, delegated
from wowbuddy.automation.unattended_phases import _PATROL_RADIUS

_CAMP_DEATH_RADIUS = 150
_PATROL_CROWD_LIMIT = 2
_PATROL_SCOUT_STEP = 10


@dataclass
class DevLaunchOptions:
    """窗口需要的启动参数与程序位置；data_dir 须已解析为绝对路径。"""
    data_dir: Path
    app_root: Path
    package_dir: Path
    frozen: bool = False
    selftest: bool = False
    dump_ui: object = None
    auto_leveling: bool = False
    auto_revive: bool = False
    auto_navigate: bool = False
    auto_grind: bool = False


class DevWindow(AssistantWindow):
    # 无人托管行程状态集中在 self.unattended（UnattendedController）；这些属性只做委托，
    # 保留原字段名，现有方法与测试的读写方式不变。
    _leveling_trip = delegated('leveling_trip')
    _fixed_camp_route = delegated('fixed_camp_route')
    _leveling_upgrade_wait = delegated('leveling_upgrade_wait')
    _vendor_wait = delegated('vendor_wait')
    _automatic_revival = delegated('automatic_revival')
    _post_revival_session = delegated('post_revival_session')
    _online_vendor = delegated('online_vendor')
    _quest_trip = delegated('quest_trip')
    _vendor_run = delegated('vendor_run')
    _loot_approach_session = delegated('loot_approach_session')

    # 按需建立的运行期状态：类级默认值代替各处的 getattr(self, name, None)。
    _approach_notice = None
    _approaching_target = False
    _arrival_pull = None
    _camp_position = None
    _camp_scout = None
    _cast_feedback = None
    _combat_dispatch = None
    _combat_facing = None
    _corpse_access = None
    _corpse_trip = None
    _ghost_origin = None
    _deferred_quest = None
    _last_profile_gap = None
    _learned_corpse_trip = None
    _walk_grid = None
    _travel_scan = None
    _bag_full_session = None
    _grid_corpse_trip = None
    _grid_corpse_given_up = None
    _level_progress = None
    _leveling_camps = None
    _leveling_checkpoint_session = None
    _leveling_destination = None
    _leveling_planner = None
    _local_access = None
    _loot_approach = None
    _map_navigator = None
    _nova_spacing = None
    _nova_spacing_notice = None
    _post_revival_notice = False
    _quest_route_attempt = None
    _quest_route_scope = None
    _target_approach = None
    _travel_mouse = None
    _travel_restore_attempted = None
    _patrol_recorder = None
    _patrol_record_action = None
    _steering_stats = None
    _patrol_leg = None          # (停留点序号, 本段路点, 接回起点下标)，录制路线规划时记录
    _patrol_replan_ms = None
    _status_timer = None        # MCP：每秒写 status.json、处理信箱（docs/design/20261115-assistant-mcp.md）
    _mcp_control_check = None
    _frame_dumper = None
    _last_mark = None
    _status_character = None    # (时间戳, CharacterState)：最近一次脱战角色读数
    _status_life = None
    _status_failed = False

    def __init__(self, *args, launch_options: DevLaunchOptions, **kwargs):
        # 基类构造期间会调用 _configure_unfinished_controls，须先保存启动参数并建立托管状态。
        self.launch_options = launch_options
        self.unattended = UnattendedController()
        super().__init__(*args, **kwargs)

    def _install_shell(self, tray_enabled):
        super()._install_shell(tray_enabled)
        # 游戏在前台时，让复活和拾取所用的游戏界面保持可见。
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, False)
        self.shell.tray_available = False

    def _quit_development_app(self):
        self.shutdown()
        QApplication.quit()

    def closeEvent(self, event):
        already_closed = self._closed
        super().closeEvent(event)
        if not already_closed and event.isAccepted():
            # 已隐藏的主窗口关闭时，Qt 不一定发出 lastWindowClosed。
            QTimer.singleShot(0, QApplication.instance(), QApplication.instance().quit)

    def _configure_unfinished_controls(self):
        super()._configure_unfinished_controls()
        self.ui.update_check_button.setEnabled(True)
        self.ui.hub_pull_button.setEnabled(True)
        self.ui.hub_pull_button.setText('重载本地方案')
        self.ui.hub_pull_button.setToolTip(str(Path(self.launch_options.data_dir)/'hub/rotations.json'))
        self.ui.export_diagnostics_button.setEnabled(True)
        self.ui.export_diagnostics_button.clicked.connect(self._export_diagnostics)
        self.grind_check = QCheckBox('无人托管')
        self.grind_check.setObjectName('UnattendedGrind')
        self.grind_check.setToolTip('监控时前往固定打怪点；未设置时自动查询练级点。\n'
                                    '战斗沿用当前循环方案，吃喝沿用插件里的恢复设置。\n'
                                    '赶路和复活需要游戏处于前台。')
        layout = self.ui.cards['target'].layout()
        layout.insertWidget(layout.indexOf(self.ui.calibration_label), self.grind_check)
        route_button = QPushButton('地图路线', self.ui.cards['target'])
        self._manual_camp_button = route_button
        route_button.setObjectName('ManualCampRoutes')
        route_button.setToolTip('先停止监控，再粘贴游戏世界地图「复制路线」导出的文本。')
        route_menu = QMenu(route_button)
        route_menu.setToolTipsVisible(True)
        route_menu.addAction('设置固定打怪点…', self._edit_fixed_camp)
        route_menu.addAction('清除固定打怪点', lambda: self._edit_fixed_camp(clear=True))
        route_menu.addAction('启用循环打怪路线…', self._edit_patrol_route)
        self._patrol_record_action = route_menu.addAction('开始录制循环路线', self._toggle_patrol_recording)
        route_menu.addAction('关闭循环打怪路线', lambda: self._edit_patrol_route(clear=True))
        patrol_scan = route_menu.addAction('边走边找怪（实验）')
        patrol_scan.setCheckable(True)
        patrol_scan.setToolTip('循环路线行走中每 2.5 秒按一次选怪键，选到怪就停下来打；空路点只扫三个方向，不再补扫。')
        patrol_scan.setChecked(self.settings.patrol_travel_scan_enabled())
        patrol_scan.toggled.connect(self._toggle_patrol_scan)
        self._patrol_scan_action = patrol_scan
        record_corpse = route_menu.addAction('录制跑尸路线')
        record_corpse.setCheckable(True)
        record_corpse.setChecked(self.settings.corpse_recording_enabled())
        record_corpse.toggled.connect(self._toggle_corpse_recording)
        self._record_corpse_action = record_corpse
        walk_grid = route_menu.addAction('地图格子寻路（实验）')
        walk_grid.setCheckable(True)
        walk_grid.setToolTip('按 .local/walkgrid 中的地图格子规划跑尸路线和撞墙后的绕行。没有对应地图的格子文件时不起作用。')
        walk_grid.setChecked(self.settings.walk_grid_enabled())
        walk_grid.toggled.connect(self._toggle_walk_grid)
        self._walk_grid_action = walk_grid
        if walk_grid.isChecked():
            self._walk_grid = self._new_walk_grid()
        route_menu.addAction('设置商人路线…', lambda: self._edit_fixed_camp(vendor=True))
        route_menu.addAction('关闭自动出售', lambda: self._edit_fixed_camp(clear=True, vendor=True))
        bag_full = route_menu.addAction('满包后继续打怪（不再拾取，实验）')
        bag_full.setCheckable(True)
        bag_full.setToolTip('背包满且没有可用的商人时不暂停练级，继续打怪、暂不拾取；绑定商人后照常去出售。')
        bag_full.setChecked(self.settings.bag_full_grinding_enabled())
        bag_full.toggled.connect(self._toggle_bag_full_grinding)
        self._bag_full_action = bag_full
        route_menu.addAction('导入游戏路线…', self._import_manual_route)
        route_menu.addAction('删除路线（含当前循环）…', self._remove_manual_route)
        route_menu.addAction('导入起点接入路线…', lambda: self._import_manual_route(access=True))
        route_menu.addAction('删除起点接入路线…', lambda: self._remove_manual_route(access=True))
        route_menu.addAction('导入跨图连接…', lambda: self._edit_manual_connection(remove=False))
        route_menu.addAction('删除跨图连接…', lambda: self._edit_manual_connection(remove=True))
        route_button.setMenu(route_menu)
        layout.insertWidget(layout.indexOf(self.ui.calibration_label), route_button)
        enabled = not self.launch_options.selftest and self.launch_options.dump_ui is None and (self.launch_options.auto_grind or self.settings.unattended_enabled())
        self.grind_check.setChecked(enabled)
        self.pipeline.probe_attack_range = not self.launch_options.selftest and self.launch_options.dump_ui is None
        self.pipeline.skip_obstructed_targets = enabled
        self.pipeline.unattended_grinding = enabled
        self.scheduler.before_dispatch = self._stop_before_action
        self._character_freshness = CharacterFrameFreshness()
        self._character_session = None
        self._character_travel_identity = None
        self.loop.frame_hold_reason = self._hold_character_frame
        self.grind_check.toggled.connect(self._set_unattended)
        self._install_mcp_status()
        self._unattended_revision = 0
        self._monitor_paused_by_user = False
        self._waiting_for_movement_stop = False
        self._movement_stop_sample = None
        self._dispatch_stop_session = None
        from wowbuddy.automation.corpse_loot import CorpseLoot
        from wowbuddy.automation.death_recovery import CorpseTrail
        self._corpse_loot = CorpseLoot()
        self._corpse_trail = CorpseTrail()
        self._loot_approach_request = None
        self._loot_approach_session = None
        self._vendor_run = VendorRun()
        self._online_vendor = None
        self._vendor_wait = None
        self._vendor_departure_free = None
        self._vendor_restore_record = None
        self._vendor_recovery_walk = None
        self._fixed_camp_route = None
        self._patrol_route = None
        self._patrol_index = 0
        self._patrol_kill = None
        self._vendor_route = None
        self._fixed_camp_scope = self._fixed_camp_blocked = None
        if text := self.settings.fixed_camp():
            try:
                self._fixed_camp_route = parse_fixed_camp(text)
            except ValueError as error:
                self.logger.append('保存的固定打怪点无法读取。' + str(error))
        if text := self.settings.vendor_route():
            try:
                self._vendor_route = parse_fixed_camp(text)
            except ValueError as error:
                self.logger.append('保存的商人路线无法读取。' + str(error))
        if text := self.settings.patrol_route():
            try:
                self._fixed_camp_route = self._patrol_route = parse_patrol_route(text)
            except ValueError as error:
                self.logger.append('保存的循环打怪路线无法读取。' + str(error))
        self._show_fixed_camp()

    def _export_diagnostics(self):
        """“导出诊断”按钮：发现客户端、打包到 数据目录/diagnostics，并打开所在目录。"""
        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        from wowbuddy import diagnostic_export

        button = self.ui.export_diagnostics_button
        button.setEnabled(False)
        try:
            clients = diagnostic_export.find_clients(self.settings)
            result = diagnostic_export.export_diagnostics(self.launch_options.data_dir, clients)
        except Exception as error:
            self.logger.append(f'诊断导出失败：{error}')
        else:
            count = len([name for name in result.members if name != 'manifest.json'])
            self.logger.append(f'已导出诊断：{result.path}（共 {count} 项，缺少 {len(result.missing)} 项）')
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(result.path).parent)))
        finally:
            button.setEnabled(True)

    # ---- MCP 接口：状态快照与信箱（docs/design/20261115-assistant-mcp.md）----
    def _install_mcp_status(self):
        check = QCheckBox('允许 MCP 控制')
        check.setObjectName('AllowMcpControl')
        check.setToolTip('允许 Claude 经 MCP 停止监控、关闭无人托管、导出诊断。\n'
                         '不允许开始监控或发键；保存当前帧、打标记不受此开关限制。')
        check.setChecked(self.settings.mcp_control_enabled())
        check.toggled.connect(self._set_mcp_control)
        button = self.ui.export_diagnostics_button
        layout = button.parentWidget().layout()
        layout.insertWidget(layout.indexOf(button) + 1, check)
        self._mcp_control_check = check
        if self.launch_options.selftest or self.launch_options.dump_ui is not None:
            return
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(1000)
        self._status_timer.timeout.connect(self._status_tick)
        self._status_timer.start()

    def _set_mcp_control(self, enabled):
        self.settings.save_mcp_control(enabled)
        self.logger.append('已允许 MCP 控制（停止监控、关闭无人托管、导出诊断）。' if enabled else '已关闭 MCP 控制。')

    def _remember_status_character(self, character, death):
        import time
        if character is not None:
            self._status_character = time.time(), character
        self._status_life = death.life if death is not None else character.life

    def _status_tick(self):
        """每秒：先执行信箱请求，再写 status.json；失败只记一次日志。"""
        import time
        from wowbuddy import control_mailbox
        data_dir = self.launch_options.data_dir
        try:
            allow = bool(self._mcp_control_check and self._mcp_control_check.isChecked())
            for request in control_mailbox.take(data_dir, now=time.time(), allow_control=allow):
                self._run_mcp_request(request)
            self._write_status()
        except Exception as error:
            if not self._status_failed:
                self._status_failed = True
                self.logger.append(f'MCP 状态快照写入失败：{error}')

    def _run_mcp_request(self, request):
        import time
        from wowbuddy import control_mailbox, frame_capture_dump
        data_dir = self.launch_options.data_dir
        label = control_mailbox.ACTION_LABELS[request.action]
        extra = {}
        try:
            if request.action == 'stop_monitoring':
                if self.session.is_active():
                    self._release_navigation_key()
                    self.toggle_monitor()
                    ok, message = not self.session.is_active(), '已停止监控'
                else:
                    ok, message = True, '监控本来就未运行'
            elif request.action == 'stop_unattended':
                was = self.grind_check.isChecked()
                self.grind_check.setChecked(False)
                ok, message = True, '已关闭无人托管' if was else '无人托管本来就未开启'
            elif request.action == 'export_diagnostics':
                from wowbuddy import diagnostic_export
                result = diagnostic_export.export_diagnostics(data_dir, diagnostic_export.find_clients(self.settings))
                ok, message, extra = True, f'已导出诊断：{result.path}', dict(path=str(result.path))
            elif request.action == 'capture_frame':
                if self._frame_dumper is None:
                    self._frame_dumper = frame_capture_dump.FrameDumper(data_dir)
                result = getattr(self, '_last_result', None)
                image = getattr(getattr(result, 'capture', None), 'image', None)
                tick = getattr(result, 'tick', None)
                frame = tick.decision.frame if tick is not None else None
                note = str(request.args.get('note', ''))[:200]
                from wowbuddy import status_snapshot
                path = self._frame_dumper.dump(image, frame, dict(note=note, packets=status_snapshot.describe_packets(image, frame),
                                                                  status=self._status_document(time.time())),
                                               now=time.time())
                ok, message, extra = True, f'已保存当前帧：{path}', dict(path=path)
            elif request.action == 'mark':
                text = ' '.join(str(request.args.get('text', '')).split())[:200]
                line = self.logger.append(f'==== 标记：{text} ====')
                self._last_mark = dict(text=text, at=time.time(), line=line)
                ok, message = True, line
        except frame_capture_dump.DumpRefused as error:
            ok, message = False, str(error)
        except Exception as error:
            ok, message = False, f'{type(error).__name__}: {error}'
        if request.action != 'mark':
            self.logger.append(f'MCP 请求：{label}（{"已执行" if ok else "未执行：" + message}）')
        control_mailbox.reply(data_dir, request.id, ok, message, **extra)

    def _status_document(self, now):
        from wowbuddy import status_snapshot
        from wowbuddy.dev_version import VERSION
        result = getattr(self, '_last_result', None)
        tick = getattr(result, 'tick', None)
        decision = status_snapshot.describe_decision(tick.decision, tick.selected) if tick is not None else None
        image = getattr(getattr(result, 'capture', None), 'image', None)
        packets = status_snapshot.describe_packets(image, tick.decision.frame) if tick is not None else None
        remembered = self._status_character
        character = status_snapshot.describe_character(remembered[1], at=remembered[0]) if remembered else None
        stats = self._steering_stats
        document = self.ui.log_view.document()
        count = document.blockCount()
        tail = [document.findBlockByNumber(index).text() for index in range(max(0, count - 20), count)]
        return status_snapshot.build_status(
            now=now, version=VERSION, running=True, monitoring=self.session.is_active(),
            hwnd=self.session.state.hwnd, status_text=self.session.state.status,
            unattended=self.grind_check.isChecked(), phase=self.unattended.last_phase.value,
            patrol=status_snapshot.describe_patrol(self._patrol_route, self._patrol_index),
            character=character, life=self._status_life, decision=decision, log_tail=tail,
            steering=stats.progress(now_ms=self.monotonic_ms()) if stats is not None else None,
            last_mark=self._last_mark, control_allowed=bool(self._mcp_control_check
                                                            and self._mcp_control_check.isChecked()),
            packets=packets, input_block=self._input_block_status(), ghost=self._ghost_status(),
            walk_grid=self._walk_grid_status(), patrol_scan=self._patrol_scan_status())

    def _ghost_status(self):
        origin = self._ghost_origin
        if origin is None or origin.origin is None:
            return None
        point = origin.origin
        return dict(origin=[point.map_id, point.x, point.y], exit_blocked=origin.exit_blocked)

    def _input_block_status(self):
        """前台移动最近一次拒绝发键的原因（MCP 用于区分“不在前台”和真正受阻）。"""
        import time
        movement = getattr(self._map_navigator, 'movement', None)
        reason = getattr(movement, 'blocked_reason', None)
        at = getattr(movement, 'blocked_at', None)
        if not isinstance(reason, str) or not isinstance(at, (int, float)):
            return None
        from time import monotonic
        return dict(reason=reason, seconds_ago=round(monotonic() - at, 1), at=round(time.time() - (monotonic() - at), 1))

    def _write_status(self):
        import time
        from wowbuddy import status_snapshot
        status_snapshot.write_json_atomic(Path(self.launch_options.data_dir) / status_snapshot.STATUS_FILE,
                                          self._status_document(time.time()))

    def _stop_mcp_status(self):
        import time
        from wowbuddy import status_snapshot
        from wowbuddy.dev_version import VERSION
        if self._status_timer is None:
            return
        self._status_timer.stop()
        self._status_timer = None
        try:
            status_snapshot.write_json_atomic(Path(self.launch_options.data_dir) / status_snapshot.STATUS_FILE,
                                              status_snapshot.stopped_status(now=time.time(), version=VERSION))
        except OSError:
            pass

    def _show_fixed_camp(self):
        if self._patrol_route is not None:
            self._manual_camp_button.setText(f'循环打怪（{len(self._patrol_route.points)} 点）')
            return
        route = self._fixed_camp_route
        if route is None:
            self._manual_camp_button.setText('地图路线')
            return
        x, y = route.endpoint
        self._manual_camp_button.setText(f'固定打怪点 ({x:.2f}, {y:.2f})')

    def _bag_full_grinding_enabled(self):
        action = getattr(self, '_bag_full_action', None)
        return bool(action is not None and action.isChecked())

    def _skip_loot_for_full_bag(self):
        return self._bag_full_session is not None and self._bag_full_grinding_enabled()

    def _toggle_bag_full_grinding(self, enabled):
        action = getattr(self, '_bag_full_action', None)
        try:
            self.settings.save_bag_full_grinding(enabled)
        except OSError as error:
            self.logger.append('满包设置保存失败。' + str(error))
            enabled = not enabled
        if action is not None and action.isChecked() != enabled:
            action.blockSignals(True)
            action.setChecked(enabled)
            action.blockSignals(False)
        if not enabled:
            self._bag_full_session = None
        self.logger.append('已开启满包后继续打怪：没有可用商人时不再暂停练级，暂不拾取。'
                           if enabled else '已关闭满包后继续打怪，满包且没有商人时暂停练级。')

    def _patrol_scan_enabled(self):
        action = getattr(self, '_patrol_scan_action', None)
        return bool(action is not None and action.isChecked())

    def _camp_scout_allowed(self):
        """边走边找怪打开时，循环路线空路点不再“短步靠近后再搜一次”。"""
        return not self._patrol_scan_enabled()

    def _travel_scan_for(self):
        from wowbuddy.automation.patrol_scan import TravelScan
        if self._travel_scan is None:
            self._travel_scan = TravelScan(self.dispatcher)
        return self._travel_scan

    def _travel_engaged(self, session):
        scan = self._travel_scan
        return bool(scan is not None and self._patrol_scan_enabled() and scan.engaged_for(session))

    def _toggle_patrol_scan(self, enabled):
        """边走边找怪开关（docs/design/20261117-patrol-scan.md），默认关闭。"""
        action = getattr(self, '_patrol_scan_action', None)
        try:
            self.settings.save_patrol_travel_scan(enabled)
        except OSError as error:
            self.logger.append('边走边找怪设置保存失败。' + str(error))
            enabled = not enabled
        if action is not None and action.isChecked() != enabled:
            action.blockSignals(True)
            action.setChecked(enabled)
            action.blockSignals(False)
        if self._travel_scan is not None:
            self._travel_scan.cancel()
        self.logger.append('已开启边走边找怪：循环路线行走中每 2.5 秒按一次选怪键，空路点只扫三个方向。'
                           if enabled else '已关闭边走边找怪，路点恢复四个方向和补扫。')

    def _patrol_scan_status(self):
        if not self._patrol_scan_enabled():
            return None
        scan = self._travel_scan
        return dict(enabled=True, **(scan.status() if scan is not None else
                                     dict(presses=0, rejections=0, engaged=False)))

    def _new_walk_grid(self):
        from wowbuddy.automation.grid_route import GridRoutes
        return GridRoutes(Path(self.launch_options.data_dir) / 'walkgrid')

    def _toggle_walk_grid(self, enabled):
        """地图格子寻路开关（docs/design/20261116-walk-grid-pathing.md），默认关闭。"""
        action = getattr(self, '_walk_grid_action', None)
        try:
            self.settings.save_walk_grid(enabled)
        except OSError as error:
            self.logger.append('地图格子寻路设置保存失败。' + str(error))
            enabled = not enabled
        if action is not None and action.isChecked() != enabled:
            action.blockSignals(True)
            action.setChecked(enabled)
            action.blockSignals(False)
        if not enabled:
            self._walk_grid = None
            self._grid_corpse_trip = self._grid_corpse_given_up = None
            self.logger.append('已关闭地图格子寻路，撞墙后改回固定绕行。')
            return
        self._walk_grid = self._new_walk_grid()
        maps = self._walk_grid.available_maps()
        if maps:
            from wowbuddy.automation.walking_route import ZONE_MAP_IDS
            names = {map_id: name for name, map_id in ZONE_MAP_IDS.items()}
            listed = '、'.join(f'{names.get(map_id, "地图")}（{map_id}）' for map_id in maps)
            self.logger.append(f'已开启地图格子寻路：已找到 {listed}。')
        else:
            self.logger.append(f'已开启地图格子寻路，但 {self._walk_grid.directory} 中没有格子文件。')

    def _walk_grid_status(self):
        grid = self._walk_grid
        if grid is None:
            return None
        return dict(enabled=True, **grid.status())

    def _grid_corpse_road(self, session, position, goal):
        """同地图跑尸：按地图格子规划整条路线；首点为灵魂当前位置。失败或本次已放弃时返回空。"""
        routes = self._walk_grid
        if routes is None or position is None or self._grid_corpse_given_up == session:
            return ()
        if routes.grid(position.map_id) is None:
            return ()
        self._release_navigation_key()
        points, reason = routes.plan(position, goal)
        if not points:
            self._grid_corpse_given_up = session
            self.logger.append(f'地图格子未能规划跑尸路线（{reason}），改用常规跑尸。')
            return ()
        plan = routes.last_plan or {}
        self.logger.append(f'已按地图格子规划跑尸路线，共 {len(points) - 1} 个路点，约 {plan.get("yards") or 0} 码。')
        return tuple(points)

    def _toggle_corpse_recording(self, enabled):
        try:
            self.settings.save_corpse_recording(enabled)
        except OSError as error:
            self.logger.append('跑尸录制设置保存失败。' + str(error))
            self._record_corpse_action.blockSignals(True)
            self._record_corpse_action.setChecked(not enabled)
            self._record_corpse_action.blockSignals(False)
            return
        self._corpse_trail.cancel_recording()
        self.logger.append('已开启跑尸录制，下一次从墓地跑到尸体并成功复活后保存。'
                           if enabled else '已停止录制；已保存的跑尸路线仍可复用。')

    def _edit_fixed_camp(self, *, clear=False, vendor=False):
        label = '商人路线' if vendor else '固定打怪点'
        if self.session.is_active():
            self.logger.append(f'请先停止监控，再修改{label}。')
            return
        read_setting = self.settings.vendor_route if vendor else self.settings.fixed_camp
        save_setting = self.settings.save_vendor_route if vendor else self.settings.save_fixed_camp
        text, route = '', None
        if not clear:
            instructions = ('先选中商人并打开商店，在游戏输入 /wbdvendor。路线末点应在商人旁。' if vendor
                            else '路线最后一个点为打怪点。')
            text, accepted = QInputDialog.getText(self, f'设置{label}',
                '粘贴世界地图的「复制打怪点」或「复制路线」。' + instructions, text=read_setting())
            if not accepted:
                return
        try:
            if not clear:
                route = parse_fixed_camp(text)
            save_setting(text.strip())
            if not vendor and self._patrol_route is not None:
                self.settings.save_patrol_route('')
        except (OSError, ValueError) as error:
            self.logger.append(f'{label}保存失败。' + str(error))
            return
        if vendor:
            self._vendor_route = route
            self._vendor_run = VendorRun()
            self._online_vendor = None
            self._vendor_wait = None
        else:
            self._fixed_camp_route = route
            self._patrol_route = self._patrol_kill = None
        self._clear_vendor_travel()
        self._fixed_camp_scope = self._fixed_camp_blocked = None
        self._show_fixed_camp()
        self.logger.append(f'已保存{label}。' if route else f'已清除{label}。')

    def _toggle_patrol_recording(self):
        """“地图路线”菜单：开始录制循环路线；录制中再点一次则结束并保存为当前循环路线。"""
        from wowbuddy.automation.patrol_recording import PatrolRecorder

        recorder = self._patrol_recorder
        if recorder is None:
            if not self.session.is_active():
                self.logger.append('请先开始监控并进入游戏，再录制循环路线。')
                return
            self._patrol_recorder = PatrolRecorder()
            self._release_navigation_key()
            if self._patrol_record_action is not None:
                self._patrol_record_action.setText('结束录制并保存循环路线')
            self.logger.append('已开始录制循环路线：自动移动已暂停，请手动沿想要的循环走一圈，回到起点附近后结束录制。')
            return
        self._patrol_recorder = None
        if self._patrol_record_action is not None:
            self._patrol_record_action.setText('开始录制循环路线')
        if recorder.stopped:
            self.logger.append('循环路线录制已停止，本次未保存。' + recorder.reason)
            return
        try:
            text = recorder.encode()
            route = parse_patrol_route(text)
            self.settings.save_recorded_patrol(text)
            self.settings.save_patrol_route(text)
        except (ValueError, OSError) as error:
            self.logger.append('循环路线未保存。' + str(error))
            return
        self._apply_patrol_route(route)
        self.logger.append(f'已保存录制的循环路线：{len(route.path)} 个路点、{len(route.points)} 个停留点，'
                           f'约 {recorder.length:.0f} 码；已设为当前循环打怪路线。')

    def _observe_patrol_recording(self, position):
        recorder = self._patrol_recorder
        if recorder is None:
            return
        notice = recorder.observe(position)
        if notice:
            self.logger.append(notice)
        if recorder.stopped:
            self.ui.suggestions.setPlainText('循环路线录制已停止：' + recorder.reason + ' 请点“结束录制并保存循环路线”收尾。')
        else:
            self.ui.suggestions.setPlainText(f'正在录制循环路线：{len(recorder.points)} 点，约 {recorder.length:.0f} 码；'
                                             '回到起点附近后点“结束录制并保存循环路线”。')

    def _observe_steering(self, session, position):
        """回放录制路线时按段统计转向（偏离轨迹、原地转向、修正、受阻），到达停留点写日志；只读，不影响移动。"""
        from wowbuddy.automation.manual_routes import patrol_leg
        from wowbuddy.automation.steering_stats import SteeringStats

        route, navigator = self._patrol_route, self._map_navigator
        if route is None or not route.recorded or navigator is None or position is None:
            return
        stats = self._steering_stats
        if stats is None:
            stats = self._steering_stats = SteeringStats()
        if getattr(position, 'life', 'alive') != 'alive':
            # 死亡后灵魂位置与本段轨迹无关：作废本段，复活后从下一次规划重新统计。
            if (text := stats.abandon('角色死亡')) is not None:
                self.logger.append(text)
            return
        active = self._leveling_trip
        trip = active[2] if active and active[2].session == session else None
        index = self._patrol_index
        now = self.monotonic_ms()
        if trip is not None and not trip.complete and trip.goal.label == self._patrol_label(index):
            road = (route.points[index - 1],) + tuple(patrol_leg(route, index))
            if stats.segment_key() != (index + 1, road):
                if stats.active:   # 上一段未经“到达”就切换（如受阻后换点），先结算记录
                    for line in (stats.finish(now_ms=now, counters=navigator.counters) or '').splitlines():
                        self.logger.append(line)
                stats.begin(index + 1, len(route.points), road, now_ms=now, counters=navigator.counters)
            stats.observe(position, now_ms=now)
        elif stats.active and trip is not None and trip.complete:
            text = stats.finish(now_ms=now, counters=navigator.counters)
            for line in (text or '').splitlines():
                self.logger.append(line)

    def _recording_plan(self, plan):
        """录制循环路线时由用户手动行走：暂停自动练级与导航，复活处理照常。"""
        from dataclasses import replace
        return plan if self._patrol_recorder is None else replace(plan, leveling=False, navigate=False)

    def _edit_patrol_route(self, *, clear=False):
        if self.session.is_active():
            self.logger.append('请先停止监控，再修改循环打怪路线。')
            return
        text, route = '', None
        if not clear:
            routes = list(self._manual_routes().items())
            for recorded in self.settings.recorded_patrols():
                try:
                    routes.append((parse_patrol_route(recorded), recorded))
                except ValueError:
                    continue
            if not routes:
                self.logger.append('请先导入一条游戏地图路线，或录制一条循环路线。')
                return
            labels = [f'{index} · {"录制 · " if item.recorded else ""}{item.zone or item.map_id} · '
                      f'{len(item.points)} 点 · {item.endpoint[0]:.2f}, {item.endpoint[1]:.2f}'
                      for index, (item, _) in enumerate(routes, 1)]
            selected, accepted = QInputDialog.getItem(self, '启用循环打怪路线',
                '选择已导入的路线。末点会接回首点，请确认这一段也能通行。',
                labels, len(labels)-1, False)
            if not accepted:
                return
            route, text = routes[labels.index(selected)]
        try:
            self.settings.save_patrol_route(text)
        except OSError as error:
            self.logger.append('循环打怪路线保存失败。' + str(error))
            return
        self._apply_patrol_route(route)
        self.logger.append('已关闭循环打怪路线。' if clear else '已启用循环打怪路线，从第 1 点开始。')

    def _apply_patrol_route(self, route):
        self._patrol_route = route
        if route is None and (fixed := self.settings.fixed_camp()):
            try:
                route = parse_fixed_camp(fixed)
            except ValueError as error:
                self.logger.append('保存的固定打怪点无法读取。' + str(error))
        self._fixed_camp_route = route
        self._patrol_index = 0
        self._patrol_kill = None
        self._fixed_camp_scope = self._fixed_camp_blocked = None
        self._leveling_trip = self._leveling_destination = self._camp_scout = None
        self._vendor_run = VendorRun()
        self._online_vendor = self._vendor_wait = self._vendor_recovery_walk = None
        self._clear_vendor_travel()
        self._show_fixed_camp()

    def _manual_routes(self, *, connections=(), access=False):
        from wowbuddy.automation.walking_route import connection_map_ids
        routes = {}
        for text in self.settings.manual_routes(access=access):
            try:
                route = parse_manual_route(text)
                if not access:
                    connection_map_ids(connections, camp_routes=(*routes, route))
            except ValueError:
                continue
            routes[route] = text
        return routes

    def _import_manual_route(self, *, access=False):
        if self.session.is_active():
            self.logger.append('请先停止监控，再导入地图路线。')
            return
        title = '起点接入路线' if access else '游戏路线'
        prompt = ('请从角色的起点开始标，按顺序经过门口或拐角，终点放在开阔路面。'
                  if access else '请从第一个接入点开始标，最后标在刷怪点附近。')
        text, accepted = QInputDialog.getText(self, f'导入{title}', '粘贴世界地图导出的路线。' + prompt)
        if not accepted:
            return
        try:
            from wowbuddy.automation.walking_route import connection_map_ids
            route = parse_manual_route(text)
            index = 0 if access else -1
            routes = {item: saved for item, saved in self._manual_routes(access=access).items()
                      if (item.map_id, item.points[index]) != (route.map_id, route.points[index])}
            routes[route] = text.strip()
            if not access:
                connection_map_ids(self._connection_legs(), camp_routes=tuple(routes))
            self.settings.save_manual_routes(list(routes.values()), access=access)
        except (OSError, ValueError) as error:
            self.logger.append('地图路线导入失败。' + str(error))
            return
        x, y = route.endpoint
        kind = '起点接入路线的 ' if access else ' '
        self.logger.append(f'已导入地图 {route.map_id} 的{kind}{len(route.points)} 个路点，终点 ({x:.2f}, {y:.2f})。')

    def _remove_manual_route(self, *, access=False):
        if access and self.session.is_active():
            self.logger.append('请先停止监控，再删除地图路线。')
            return
        routes = self._manual_routes(access=access)
        route_choices = list(routes)
        if not access and self._patrol_route is not None and self._patrol_route not in routes:
            route_choices.append(self._patrol_route)
        options = {}
        for route in route_choices:
            x, y = route.points[0] if access else route.endpoint
            name = route.zone or f'地图 {route.map_id}'
            active = ' · 当前循环' if not access and route == self._patrol_route else ''
            options[f'{len(options) + 1} · {name} · ({x:.2f}, {y:.2f}) · {len(route.points)} 点{active}'] = route
        if not options:
            self.logger.append('当前没有已导入的地图路线。')
            return
        label, accepted = QInputDialog.getItem(
            self, '删除地图路线', '选择要删除的路线。删除当前循环会停止监控。',
            list(options), 0, False)
        if accepted:
            selected = options[label]
            clear_patrol = not access and selected == self._patrol_route
            if clear_patrol and self.session.is_active():
                self.toggle_monitor()
                self._monitor_paused_by_user = True
            routes.pop(selected, None)
            try:
                self.settings.save_manual_routes(list(routes.values()), access=access,
                                                 clear_patrol=clear_patrol)
            except OSError as error:
                self.logger.append('地图路线删除失败。' + str(error))
            else:
                if clear_patrol:
                    self._apply_patrol_route(None)
                self.logger.append(f'已删除地图路线 {label}。')

    def _manual_connections(self):
        from wowbuddy.automation.walking_route import connection_map_ids
        connections = {}
        for text in self.settings.manual_connections():
            try:
                leg = parse_manual_connection(text)
                proposed = dict(connections)
                proposed[leg.road_key] = leg, text
                connection_map_ids(tuple(item for item, _ in proposed.values()))
            except ValueError:
                continue
            connections = proposed
        return connections

    def _edit_manual_connection(self, *, remove):
        from wowbuddy.automation.walking_route import connection_map_ids
        if self.session.is_active():
            self.logger.append('请先停止监控，再编辑跨图连接。')
            return
        connections = self._manual_connections()

        def label_for(leg, names):
            source = names.get(leg.source, f'地图 {leg.source}')
            target = names.get(leg.destination, f'地图 {leg.destination}')
            return f'{source} → {target}'

        try:
            if remove:
                from collections import Counter
                if not connections:
                    self.logger.append('当前没有已导入的跨图连接。')
                    return
                zones = connection_map_ids(tuple(item for item, _ in connections.values()),
                                           camp_routes=tuple(self._manual_routes()))
                names = {map_id: zone for zone, map_id in zones.items()}
                directions = [label_for(leg, names) for leg, _ in connections.values()]
                counts = Counter(directions)
                options = {}
                for direction, (key, (leg, _)) in zip(directions, connections.items()):
                    if counts[direction] > 1:
                        x, y = leg.points[-1]
                        entry_x, entry_y = leg.arrival_road[0]
                        direction += f' · 出口 ({x:.2f}, {y:.2f}) · 入口 ({entry_x:.2f}, {entry_y:.2f})'
                    options[direction] = key
                label, accepted = QInputDialog.getItem(self, '删除跨图连接', '选择要删除的连接。',
                                                      list(options), 0, False)
                if not accepted:
                    return
                connections.pop(options[label])
                message = f'已删除跨图连接 {label}。'
            else:
                text, accepted = QInputDialog.getMultiLineText(self, '导入跨图连接',
                    '粘贴两段世界地图路线。第一行从出发地图标到出口，第二行从到达地图入口往里标。')
                if not accepted:
                    return
                leg = parse_manual_connection(text)
                connections[leg.road_key] = leg, text.strip()
                zones = connection_map_ids(tuple(item for item, _ in connections.values()),
                                           camp_routes=tuple(self._manual_routes()))
                names = {map_id: zone for zone, map_id in zones.items()}
                message = f'已导入跨图连接 {label_for(leg, names)}。'
            self.settings.save_manual_connections([text for _, text in connections.values()])
        except (OSError, ValueError) as error:
            self.logger.append('跨图连接保存失败。' + str(error))
        else:
            self.logger.append(message)

    def _connection_legs(self):
        return tuple(leg for leg, _ in self._manual_connections().values())

    def _set_unattended(self, enabled):
        self._release_navigation_key()
        self.pipeline.skip_obstructed_targets = enabled
        self.pipeline.unattended_grinding = enabled
        self.settings.save_unattended(enabled)
        self._unattended_revision += 1
        if not enabled:
            self._clear_leveling_travel()
        self.logger.append('已开启无人托管。' if enabled else '已关闭无人托管，常规监控继续。')

    def toggle_monitor(self):
        self._monitor_paused_by_user = self.grind_check.isChecked() and self.session.is_active()
        self._stop_loot_approach()
        super().toggle_monitor()

    def _wait_for_navigation_stop(self):
        self._waiting_for_movement_stop = True
        self._movement_stop_sample = self._character_freshness.sample

    def _release_navigation_key(self):
        navigator = self._map_navigator
        if navigator is None:
            return True
        if navigator.movement.holding_forward:
            self._wait_for_navigation_stop()
        return navigator.movement.release_forward()

    def _pause_navigation_feedback(self, session):
        active = self._leveling_trip
        for trip in (active[2] if active else None, self._corpse_trip,
                     self._quest_trip):
            if trip is not None and trip.session == session:
                trip.observe(None)
        for controller in (self._map_navigator, self._arrival_pull,
                           self._target_approach,
                           self._automatic_revival):
            if controller is not None:
                controller.pause(session)
        corpse_access = self._corpse_access
        if corpse_access is not None:
            corpse_access.pause()

    def _stop_before_action(self, fields):
        if not self._release_navigation_key():
            return False
        capture = self.loop.capture
        if (isinstance(capture, WindowCapture) and capture.desktop_status is not None
                and capture.desktop_status() is not None):
            return False
        sample = self._character_freshness.sample
        if self._waiting_for_movement_stop and (fields.get('player_moving') != 'OFF'
                or (self._movement_stop_sample is not None
                    and (sample is None or sample == self._movement_stop_sample))):
            return False
        self._waiting_for_movement_stop = False
        return True

    def watch_once(self):
        if not self._monitor_paused_by_user:
            was_active = self.session.is_active()
            super().watch_once()
            if was_active and not self.session.is_active():
                self._stop_loot_approach()
                self._release_navigation_key()

    def _hold_character_frame(self, monitor, capture, frame, now_ms):
        token = decode_character_session(capture.image, frame)
        previous = self._character_session
        changed = previous is not None and previous[0] == monitor and previous[1] != token
        if changed and token is None:
            return '角色会话读数暂不可用，已暂停游戏输入'
        self._character_session = (monitor, token) if token is not None else None
        previous_identity = self._character_travel_identity
        if previous_identity is not None and previous_identity[0] != self._character_session:
            self._character_travel_identity = previous_identity = None
        if self.grind_check.isChecked():
            identity = decode_travel_identity(capture.image, frame, token)
            if identity is not None:
                changed = changed or (previous_identity is not None and previous_identity[1] != identity)
                self._character_travel_identity = self._character_session, identity
        reason = self._character_freshness.hold_reason((*monitor, token), capture, frame, now_ms,
                                                       require_sequence=token is not None)
        if changed:
            self._unattended_revision += 1
            self._leveling_trip = self._leveling_destination = self._camp_position = None
            self._leveling_camps = []
            self.pipeline.unattended_travel = False
            self.scheduler.reset_character()
            return '检测到新的角色会话，已清除旧计划，等待游戏画面更新'
        mob_policy = frame.values.get('mob_policy') == 'ON'
        unattended = self.grind_check.isChecked()
        progress = decode_level_progress(capture.image, frame, token) if not reason and (mob_policy or unattended) else None
        if progress is not None and unattended:
            self._observe_level_progress((*monitor, self._unattended_revision), progress)
        if not reason and mob_policy:
            from wowbuddy.engine.character_state import decode_mob_state
            mob = decode_mob_state(capture.image, frame)
            session = *monitor, token, self._unattended_revision
            loot = self._corpse_loot.observe(session, mob, now_ms,
                lambda key: self._send_loot_key(monitor[0], frame.values, key), self.logger.append,
                approach=lambda bearing: self._queue_loot_approach(session, capture.image, frame, bearing, now_ms),
                safe_to_loot=frame.values.get('player_in_combat') == 'OFF' and not self._skip_loot_for_full_bag(),
                combat_notices=progress.combat_notices if progress else None)
            if loot:
                return loot
        if not reason and unattended:
            session = *monitor, self._unattended_revision
            return self._observe_combat_feedback(session, capture.image, frame, now_ms)
        return reason

    def _send_loot_key(self, hwnd, fields, key):
        from wowbuddy.core.keybindings import parse_keybinding
        from wowbuddy.win32.windows_keys import send_input

        binding = parse_keybinding(key)
        if (not binding.valid or not self._stop_before_action(fields)
                or not self._combat_movement().can_input(hwnd, (binding.vk, *binding.modifiers))):
            return False
        return send_input(self.sender.backend, binding, self.sender.hold_ms)

    def _queue_loot_approach(self, session, image, frame, bearing, now_ms):
        self._loot_approach_request = session, image, frame, bearing, now_ms

    def _stop_loot_approach(self):
        if self._loot_approach_session is not None:
            self._loot_approach.pause(self._loot_approach_session)
            self._loot_approach_session = None
        return self._release_navigation_key()

    def _approach_loot_corpse(self, session, image, frame, bearing, now_ms):
        from wowbuddy.engine.character_state import decode_navigation_state
        from wowbuddy.automation.navigation import TargetApproach

        position = decode_navigation_state(image, frame)
        if position is None or position.target_revision != bearing.revision:
            self._stop_loot_approach()
            return
        if self._loot_approach_session != session and not self._stop_loot_approach():
            return
        controller = self._loot_approach
        if controller is None:
            controller = self._loot_approach = TargetApproach(self._combat_movement())
        self._loot_approach_session = session
        controller.observe(session, position, bearing, now_ms=now_ms)

    def _observe_level_progress(self, session, progress):
        previous = self._level_progress
        self._level_progress = session, progress
        total = (f'（{progress.current}/{progress.maximum}）' if progress.current is not None else '')
        if previous is None or previous[0] != session:
            if total:
                self.logger.append(f'游戏经验起点：{progress.level} 级 {progress.current}/{progress.maximum}。')
            return
        old = previous[1]
        if progress.level > old.level:
            self.logger.append(f'游戏确认升级：{old.level} → {progress.level} 级{total}。')
        elif (progress.level == old.level and old.current is not None
              and progress.current is not None and progress.current > old.current):
            self.logger.append(f'游戏经验增加 {progress.current - old.current}{total}。')
        if old.combat_notices is not None and progress.combat_notices is not None:
            received = (progress.combat_notices - old.combat_notices) % 65536
            if 0 < received < 32768:
                self.logger.append(f'游戏新增 {received} 条战斗经验回执。')
                plan = self._leveling_destination
                if (self._patrol_route is not None and plan and plan[0] == session
                        and not self._online_vendor and not self._vendor_run.active):
                    self._patrol_kill = session, plan[2]

    def poll_once(self):
        if self.monitor.stop_lost_target(watching=self.watch_timer.isActive()):
            from wowbuddy.engine.runtime import PollResult
            self._stop_loot_approach()
            self._release_navigation_key()
            self.refresh_windows()
            self._render_monitor()
            self._last_result = PollResult('target_lost')
            return self._last_result
        unattended = self.grind_check.isChecked()
        monitor = self.session.state
        session = monitor.hwnd, monitor.elapsed_started_ms, self._unattended_revision
        # 边走边找怪选到目标时，行程仍在但按交战处理：不暂停技能循环。
        self.pipeline.unattended_travel = (self.unattended.travel_active(
            session, unattended=unattended, monitoring=self.session.is_active())
            and not self._travel_engaged(session))
        self._loot_approach_request = None
        result = super().poll_once()
        desktop_held = result.status in DESKTOP_HOLD_TEXT
        if desktop_held or result.status == 'frame_held':
            if desktop_held:
                self._character_freshness = CharacterFrameFreshness()
            if not desktop_held and self._loot_approach_request is not None:
                self._approach_loot_corpse(*self._loot_approach_request)
            else:
                self._stop_loot_approach()
            self._pause_navigation_feedback(session)
            self.ui.suggestions.setPlainText(self.session.state.status)
            capture = self.loop.capture
            if (not desktop_held and self.session.state.status == STALE_FRAME and result.capture.backend == 'dxgi'
                    and isinstance(capture, WindowCapture) and not capture.prefer_printwindow):
                capture.prefer_printwindow = True
                self.logger.append('桌面抓屏读数停滞，尝试从游戏窗口直接取帧。')
            return result
        if self._loot_approach_session is not None:
            self._stop_loot_approach()
        options = self.launch_options
        plan = self._recording_plan(self.unattended.frame_plan(
            unattended, auto_revive=options.auto_revive, auto_leveling=options.auto_leveling,
            auto_navigate=options.auto_navigate))
        revive, leveling, navigate = plan.revive, plan.leveling, plan.navigate
        if not self.session.is_active():
            self._release_navigation_key()
            return result
        from wowbuddy.engine.character_state import decode_death_state, decode_navigation_state, route_character
        image = result.capture.image if result.capture else None
        frame = result.tick.decision.frame if result.tick else None
        if frame is None or not frame.ok:
            self._pause_navigation_feedback(session)
        if unattended and result.tick and result.tick.dispatch and result.tick.dispatch.success:
            action = result.tick.selected.action
            spell = action[6:] if action.startswith('spell_') else ''
            prior = self._cast_feedback
            sequence = prior[1].sequence if prior and prior[0] == session else None
            self._combat_dispatch = (session, int(spell), sequence, self.monotonic_ms()) if spell.isdecimal() else None
        if self._patrol_recorder is not None and image is not None and frame and frame.ok:
            self._observe_patrol_recording(decode_navigation_state(image, frame))
        death = decode_death_state(image, frame) if image is not None and frame and revive else None
        character = route_character(image, frame) if image is not None and frame and leveling else None
        if character is not None or death is not None:
            self._remember_status_character(character, death)
        steps = self.unattended.run_frame(FrameInput(session=session, unattended=unattended,
                                                     frame_ok=bool(frame and frame.ok), image_ok=image is not None,
                                                     character=character, death=death), plan)
        reply = None
        while True:
            try:
                step = steps.send(reply)
            except StopIteration:
                break
            reply = None
            if step is FrameAction.REVIVAL:
                self._frame_revival(session, result, image, frame, death, navigate=navigate, unattended=unattended)
            elif step is FrameAction.VENDOR:
                self._poll_vendor(session, image, frame, result, character)
            elif step is FrameAction.QUEST:
                reply = self._observe_quest_route(session, image, frame, character)
            elif step is FrameAction.LEVELING:
                self._frame_leveling(session, image, frame, character, navigate=navigate, unattended=unattended)
            elif step is FrameAction.NAVIGATION:
                self._poll_navigation(result, session, image, frame, character, death, navigate=navigate)
        return result

    def _frame_revival(self, session, result, image, frame, death, *, navigate, unattended):
        return self.unattended.revival.frame(self, session, result, image, frame, death, navigate=navigate, unattended=unattended)

    def _frame_leveling(self, session, image, frame, character, *, navigate, unattended):
        return self.unattended.leveling.frame(self, session, image, frame, character, navigate=navigate, unattended=unattended)

    def _observe_quest_route(self, session, image, frame, character):
        from wowbuddy.engine.character_state import decode_navigation_state, decode_quest_dialog, decode_quest_turn_in_pin
        from wowbuddy.automation.quest_turn_in import QuestTurnIn
        from wowbuddy.automation.walking_route import plan_quest_approach

        if (image is None or not frame or not frame.ok or character is None or character.life != 'alive'
                or self._vendor_run.active or self._online_vendor or self._vendor_wait
                or self._post_revival_session == session):
            self._quest_trip = None
            return None
        now = self.monotonic_ms()
        reading = self._quest_dialog_reading = decode_quest_dialog(image, frame)
        trip = self._quest_trip
        if trip and trip.session == session:
            job = self._quest_job
            if job.observe_receipt(reading):
                self.logger.append(f'游戏确认已交付任务 #{job.pin.quest_id}。')
                self._quest_trip = self._quest_route_attempt = None
                return None
            if (trip.complete and character.map_id == job.pin.map_id
                    and (job.native_dialog_active(reading) or job.waiting_for_receipt(now))):
                return trip
        pin = decode_quest_turn_in_pin(image, frame)
        if pin is None:
            self._quest_trip = self._quest_route_attempt = None
            return None
        scope = session, pin
        deferred = self._deferred_quest
        if deferred and deferred[0] == scope and now < deferred[1]:
            return None
        if (trip and (trip.connecting or character.map_id == pin.map_id)
                and self._quest_route_scope == scope):
            return trip
        self._quest_trip = None
        active = self._leveling_trip
        if (frame.values.get('player_in_combat') != 'OFF' or frame.values.get('equipment_red') == 'ON'
                or (active and active[2].session == session and not active[2].complete)):
            return None
        attempt = self._quest_route_attempt
        if attempt and attempt[0] == scope and now - attempt[1] < 3000:
            return None
        self._quest_route_attempt = scope, now
        position = decode_navigation_state(image, frame)
        if position is None:
            return None
        connections = self._connection_legs()
        trip = plan_quest_approach(session, pin, position, character, routes=self._manual_routes(connections=connections),
                                   connections=connections)
        if trip is not None:
            self._quest_route_scope, self._quest_trip = scope, trip
            self._quest_job = QuestTurnIn(pin, reading)
            self.logger.append(f'前往任务 #{pin.quest_id}，地图 {pin.map_id} ({pin.x:.2f}, {pin.y:.2f})。')
        elif not attempt or attempt[0] != scope:
            self.logger.append(f'发现可交任务 #{pin.quest_id}，交付点暂无已接通的道路。')
        return trip

    def _observe_combat_feedback(self, session, image, frame, now_ms):
        from wowbuddy.engine.character_state import decode_cast_feedback, decode_combat_facing, decode_nova_spacing
        from wowbuddy.automation.navigation import CombatFacing, NovaSpacing

        feedback = decode_cast_feedback(image, frame)
        new_feedback = feedback and self._cast_feedback != (session, feedback)
        if new_feedback:
            self._cast_feedback = session, feedback
            message = f"游戏施法回执 #{feedback.sequence} 技能 {feedback.spell} {'、'.join(feedback.stages)}"
            if feedback.error_code is not None:
                message += f"，同期游戏报错 {feedback.error_kind}（编号 {feedback.error_code}）"
            self.logger.append(message)
        sent = self._combat_dispatch
        if (feedback and sent and sent[:2] == (session, 122) and sent[2] != feedback.sequence
                and 0 <= now_ms - sent[3] <= 1700):
            spacing_sample, blockers = decode_nova_spacing(image, frame, feedback)
            if blockers:
                notice = session, feedback.sequence, blockers
                if self._nova_spacing_notice != notice:
                    self._nova_spacing_notice = notice
                    self.logger.append('冰霜新星后暂缓后退。' + '、'.join(blockers) + '。')
            if spacing_sample is not None:
                spacing = self._nova_spacing
                if spacing is None:
                    spacing = self._nova_spacing = NovaSpacing(self._combat_movement())
                if spacing.observe(session, feedback.sequence, spacing_sample):
                    self._wait_for_navigation_stop()
                    method = '战斗日志确认' if spacing_sample.event_only else '光环读数确认'
                    self.logger.append(f'{method}冰霜新星定身，距目标 {spacing_sample.distance:.1f} 码，短步后退。')
                    return '已后退，等待新画面确认站定后继续施法。'
        facing = self._combat_facing
        if frame.values.get('player_in_combat') == 'OFF' and facing is not None:
            facing.reset()
        sample = decode_combat_facing(image, frame, feedback)
        if sample is None:
            if new_feedback and feedback.error_kind == '朝向':
                self.logger.append('本帧未取得同一目标且角色站定的转向读数。')
            return None
        if sample.action_spell is not None:
            if (sent is None or sent[:2] != (session, sample.action_spell) or sent[2] == feedback.sequence
                    or not 0 <= now_ms - sent[3] <= 1600):
                if new_feedback:
                    self.logger.append('朝向回执未匹配助手最近发送的当前目标技能。')
                return None
        if facing is None:
            facing = self._combat_facing = CombatFacing(self._combat_movement())
        if not self._release_navigation_key() or not facing.observe(session, sample, feedback.sequence):
            reason = getattr(facing.movement, 'blocked_reason', None)
            if new_feedback and feedback.error_kind == '朝向' and isinstance(reason, str):
                self.logger.append(f'朝向错误未能转向：{reason}（转向需要游戏窗口在最前面、且不按移动键）。')
            return None
        self._wait_for_navigation_stop()
        method = '按目标方位转向' if sample.heading is not None else '短转后重试'
        self.logger.append(f'收到技能 {feedback.spell} 朝向错误，{method}（第 {facing.attempts} 次）。')
        return '已转向，等待新画面确认站定后继续施法。'

    def _combat_movement(self):
        from wowbuddy.automation.navigation import ForegroundMovement, MapNavigator

        navigator = self._map_navigator
        if navigator is None:
            movement = ForegroundMovement(self.sender.backend, self.monitor.backend,
                                          on_forward=self._wait_for_navigation_stop)
            navigator = self._map_navigator = MapNavigator(movement)
        return navigator.movement

    def _planner_for_character(self, character):
        planner = self._leveling_planner
        if planner is None and character is not None and character.simplified_chinese:
            from concurrent.futures import ThreadPoolExecutor
            from wowbuddy.automation.leveling_route import AutomaticLeveling, LevelingGuideCache

            self._leveling_executor = ThreadPoolExecutor(max_workers=1)
            planner = self._leveling_planner = AutomaticLeveling(self._leveling_executor.submit,
                cache=LevelingGuideCache(directory=self.launch_options.data_dir/'leveling-guide-cache'))
        return planner

    def _poll_leveling(self, session, character, navigate, *, navigation=None):
        return self.unattended.leveling.poll(self, session, character, navigate, navigation=navigation)

    def _poll_fixed_camp(self, session, character):
        return self.unattended.leveling.fixed_camp(self, session, character)

    def _poll_vendor(self, session, image, frame, result, character):
        return self.unattended.vendor.poll(self, session, image, frame, result, character)

    def _wait_for_vendor(self, session, reason):
        return self.unattended.vendor.wait(self, session, reason)

    def _vendor_route_settings(self):
        patrol = self.settings.patrol_route()
        camp = f'patrol:{patrol}' if patrol else self.settings.fixed_camp()
        return [self.settings.vendor_route(), camp]

    def _save_vendor_travel(self, session, character, *, returning):
        from wowbuddy.automation.leveling_route import write_leveling_result

        identity = self._travel_identity(session, character)
        if identity is None:
            return
        context, outbound, inbound = self._online_vendor
        _, level, map_id, zone = context[1]
        camp = inbound.goal
        record = {'character': identity[:-1], 'settings': self._vendor_route_settings(),
                  'level': level, 'map': map_id, 'zone': zone, 'catalog': context[2],
                  'free': self._vendor_departure_free, 'returning': returning, 'repair': self._vendor_run.repair,
                  'camp': [camp.x, camp.y, camp.label, camp.radius],
                  'outbound': outbound.approach_road, 'inbound': inbound.approach_road}
        try:
            write_leveling_result(self.launch_options.data_dir/'vendor-travel.json', record)
            self._vendor_restore_record = None
        except OSError as error:
            self.logger.append('无法保存未完成的补给路线。' + str(error))

    def _remove_data_file(self, name, failure):
        try:
            (self.launch_options.data_dir/name).unlink(missing_ok=True)
        except OSError as error:
            self.logger.append(failure + str(error))

    def _clear_vendor_travel(self):
        self._vendor_restore_record = None
        self._remove_data_file('vendor-travel.json', '无法清除已结束的补给路线。')

    def _resume_vendor_travel(self, session, character, position, reading, repair_reading=None):
        from wowbuddy.automation.navigation import MapDestination
        from wowbuddy.automation.vendor_run import read_vendor_travel
        from wowbuddy.automation.walking_route import (WalkingTrip, rejoin_darkshore_patrol_return,
                                           rejoin_grove_return_road, resume_supply_road)

        identity = self._travel_identity(session, character)
        if identity is None:
            return False
        settings = self._vendor_route_settings()
        key = session, identity[:-1], character.map_id, character.zone, settings
        if self._vendor_restore_record is None or self._vendor_restore_record[0] != key:
            record = read_vendor_travel(self.launch_options.data_dir/'vendor-travel.json', identity[:-1], character, settings)
            self._vendor_restore_record = key, record
        record = self._vendor_restore_record[1]
        if record is None:
            return False
        repair = record.get('repair', False)
        if repair:
            reading = repair_reading
        if reading is None or record['catalog'] != reading.catalog:
            return False
        outbound, inbound = (tuple(map(tuple, record[name])) for name in ('outbound', 'inbound'))
        returning = record['returning']
        supplied = reading.repair_needed is False if repair else reading.free > record['free']
        if returning and reading.merchant_open:
            self._wait_for_vendor(session, '补给返营前等待游戏关闭商店。')
            return True
        x, y, label, radius = record['camp']
        patrol = self._patrol_route is not None
        if patrol:
            index = next((i for i, point in enumerate(self._patrol_route.points)
                          if point == (x, y) and self._patrol_label(i) == label), None)
            if self._patrol_route.map_id != character.map_id or index is None:
                return False
            self._patrol_index = index
            radius = _PATROL_RADIUS
            inbound = self._patrol_return_road(inbound, (x, y))
        camp = MapDestination(character.map_id, x, y, 'alive', label, radius=radius)
        rejoined = False
        at_patrol_waypoint = patrol and supplied and not reading.merchant_open and camp.contains(position)
        if returning or (supplied and not reading.merchant_open):
            road = ((x, y),) if at_patrol_waypoint else resume_supply_road(inbound, position)
            if not road and reading.catalog and not reading.popup_blocked and supplied:
                road = (rejoin_darkshore_patrol_return(inbound, position, repair=repair) if patrol
                        else rejoin_grove_return_road(camp, position))
                rejoined = bool(road)
            returning = returning or bool(road)
        if not returning:
            road = resume_supply_road(outbound, position)
        if not road:
            self._wait_for_vendor(session, '发现未完成的补给行程，等待角色重新接入原路线。')
            return True
        merchant = MapDestination(character.map_id, *outbound[-1], 'alive', '补给商人',
                                  radius=3 if reading.catalog and not repair else 5)
        vendor_trip = WalkingTrip(session, (), merchant, level=character.level, faction=character.faction,
                                  camp_road=outbound if returning else road)
        return_road = (() if at_patrol_waypoint else road) if returning else inbound
        return_trip = WalkingTrip(session, (), camp, level=character.level, faction=character.faction,
                                  camp_road=return_road, finish_in_range=patrol)
        original_key = character.faction, record['level'], character.map_id, character.zone
        self._online_vendor = (session, original_key, reading.catalog), vendor_trip, return_trip
        self._vendor_run = VendorRun(resume_session=None if returning else session, repair=repair)
        self._vendor_departure_free = record['free']
        self._vendor_wait = None
        self._leveling_trip = character.faction, character.level, return_trip if returning else vendor_trip
        self._leveling_destination = self._camp_scout = self._local_access = None
        if returning and not record['returning']:
            self._save_vendor_travel(session, character, returning=True)
        if rejoined:
            self.logger.append('已从当前位置接入黑海岸道路，继续返回原营地。')
        else:
            self.logger.append('已恢复未完成的补给行程，继续返回原营地。' if returning
                               else '已恢复未完成的补给行程，重新核对商店和背包。')
        return True

    @staticmethod
    def _patrol_return_road(road, waypoint):
        return road[:road.index(waypoint) + 1] if waypoint in road else road

    def _plan_online_vendor(self, session, character, position, active, *, catalog=False, repair=False):
        from dataclasses import replace
        from wowbuddy.automation.navigation import MapDestination
        from wowbuddy.automation.walking_route import (WalkingTrip, auberdine_repair_road, camp_access_road,
                                           darkshore_patrol_service_road, grove_supply_road)

        plan = self._leveling_destination
        if plan and plan[:2] == (session, character.route_key):
            camp = plan[2]
        elif catalog and active and not active.connecting and active.goal.map_id == position.map_id:
            camp = active.goal
        elif catalog and self._patrol_route is not None and self._patrol_route.map_id == position.map_id:
            camp = MapDestination(position.map_id, *self._patrol_route.points[self._patrol_index],
                                  'alive', self._patrol_label(self._patrol_index), radius=_PATROL_RADIUS)
        elif catalog and repair:
            camp = MapDestination(position.map_id, position.x, position.y, 'alive', '原补给出发点')
        else:
            return None
        original_goal = active.catalog_goal if active and active.goal == camp else camp
        if catalog:
            service_road = auberdine_repair_road if repair else grove_supply_road
            outward = ()
            if character.faction == 'alliance':
                if self._patrol_route is not None:
                    outward = darkshore_patrol_service_road(position, self._patrol_route.points, repair=repair)
                else:
                    outward = service_road(position)
            if len(outward) < 2 or camp.map_id != position.map_id:
                return None
            merchant = MapDestination(position.map_id, *outward[-1], 'alive', '补给商人', radius=5 if repair else 3)
            if self._patrol_route is not None:
                inward = outward[::-1]
                waypoint = camp.x, camp.y
                if waypoint not in inward:
                    for point in ((position.x, position.y), waypoint):
                        if point != inward[-1]:
                            inward += (point,)
                inward = self._patrol_return_road(inward, waypoint)
            elif camp.contains(position):
                inward = outward[::-1] + ((position.x, position.y),)
            else:
                inward = camp_access_road(camp, origin=replace(position, x=merchant.x, y=merchant.y))
            if len(inward) < 2:
                return None
        else:
            route = self._vendor_route
            if not camp.contains(position) or route.map_id != position.map_id or len(route.points) < 2:
                return None
            x, y = route.points[0]
            entry = MapDestination(route.map_id, x, y, 'alive', '商人路线起点', radius=8)
            if not entry.contains(position) or not camp.contains(replace(position, x=x, y=y)):
                return None
            merchant = MapDestination(route.map_id, *route.endpoint, 'alive', '补给商人', radius=5)
            outward, inward = route.points, route.points[::-1]
        outbound = WalkingTrip(session, (), merchant, level=character.level, faction=character.faction,
                               camp_road=outward, catalog_goal=None if catalog else merchant,
                               arrival_message='已到商人坐标。')
        returning = WalkingTrip(session, (), camp, level=character.level, faction=character.faction,
                                camp_road=inward, catalog_goal=None if catalog else original_goal,
                                catalog_zone=character.zone, arrival_message='已沿商人路线返回原营地。',
                                finish_in_range=self._patrol_route is not None)
        return (session, character.route_key, catalog), outbound, returning

    def _send_travel_ui_action(self, hwnd, fields, rect, action, value):
        from wowbuddy.core.keybindings import parse_keybinding
        from wowbuddy.win32.windows_keys import send_input
        from wowbuddy.win32.windows_mouse import Win32Mouse

        if not self._stop_before_action(fields):
            return False
        movement = self._combat_movement()
        if action in ('hover', 'sell', 'confirm', 'board', 'repair', 'quest_click'):
            if rect is None or rect.empty or not movement.can_input(hwnd, ()):
                return False
            point = (rect.left + round(rect.width * value[0] / 10000),
                     rect.top + round(rect.height * value[1] / 10000))
            mouse = self._travel_mouse
            if mouse is None:
                mouse = self._travel_mouse = Win32Mouse(self.sender.backend, self.monitor.backend)
            if action in ('board', 'quest_click'):
                return mouse.click(hwnd, point)
            return mouse.move(hwnd, point) and (action == 'hover' or mouse.click(hwnd, point))
        if action == 'select':
            key = parse_keybinding(value)
            return (key.valid and movement.can_input(hwnd, (key.vk, *key.modifiers))
                    and send_input(self.sender.backend, key, self.sender.hold_ms))
        vk = 0x1B if action in ('close', 'dismiss') else value
        return movement.pulse(hwnd, vk, 35, (vk,))

    def _wait_for_fixed_camp(self, character, reason):
        self._fixed_camp_blocked = self._fixed_camp_scope, character.map_id
        self._leveling_trip = self._leveling_destination = self._camp_scout = None
        self.logger.append(f'{reason}。固定打怪点已保留，请检查路线后重新开始监控。')

    def _travel_identity(self, session, character, *, flying=False):
        marker = self._character_session
        if (not character or (not flying and (character.x is None or character.y is None))
                or not marker or marker[0] != session[:2] or marker[1] is None):
            return None
        hwnd = session[0]
        stable = self._character_travel_identity
        if stable is not None and stable[0] == marker:
            return ['character', *stable[1], character.faction, character.level]
        pid = self.monitor.backend.window_pid(hwnd)
        if pid:
            return [hwnd, pid, marker[1], character.faction, character.level]

    def _save_leveling_travel(self, session, character, trip):
        from wowbuddy.automation.leveling_route import write_leveling_result

        if self._fixed_camp_route is not None:
            return
        identity = self._travel_identity(session, character)
        if identity is not None:
            self._travel_restore_attempted = session, identity, False
            goal = trip.catalog_goal
            checkpoint = {
                'point': {'zone': trip.catalog_zone, 'name': goal.label, 'x': goal.x, 'y': goal.y},
                'walking_maps': [character.map_id, *(leg.destination for leg in trip.legs)],
                'character': [*identity[:-1], trip.level],
                'blocked_connections': sorted({leg.blocked_key for leg in trip.excluded_legs}),
            }
            arrival = trip.arrival_connection
            if arrival is not None and arrival.destination == character.map_id:
                checkpoint['arrival_connection'] = arrival.blocked_key
            try:
                write_leveling_result(self.launch_options.data_dir/'leveling-travel.json', checkpoint)
                self._leveling_checkpoint_session = session
            except OSError as error:
                self.logger.append('无法保存未完成的练级路线。' + str(error))

    def _clear_leveling_travel(self):
        self._leveling_checkpoint_session = None
        self._remove_data_file('leveling-travel.json', '无法清除已失效的练级路线。')

    def _resume_leveling_travel(self, session, character, *, flying=False, navigation=None):
        identity = self._travel_identity(session, character, flying=flying)
        attempt = session, identity, flying
        if identity is None or self._travel_restore_attempted == attempt:
            return False
        self._travel_restore_attempted = attempt
        from wowbuddy.automation.leveling_route import local_camp_on_current_shore, read_leveling_travel
        from wowbuddy.automation.navigation import MapDestination
        from wowbuddy.automation.walking_route import (WalkingTrip, auberdine_overlapping_floor, camp_access_road,
                                           darkshore_camp_origin, darkshore_south_camp,
                                           redridge_camp_requires_road, walking_legs)

        on_deck = (not flying and character.map_id == 1439 and auberdine_overlapping_floor(character.x, character.y)
                   and not darkshore_camp_origin(character.x, character.y, elevation=character.elevation))
        lookup = read_leveling_travel(self.launch_options.data_dir/'leveling-travel.json', identity, 1439 if flying else character.map_id,
                                      allow_level_increase=True)
        if lookup is None:
            return False
        point = lookup['point']
        saved_flight = (lookup['walking_maps'][-2:] == [1438, 1439] and point['zone'] == '黑海岸'
                        and character.life == 'alive' and character.faction == 'alliance'
                        and character.level is not None and character.level >= 12
                        and darkshore_south_camp(point['x'], point['y']))
        if saved_flight and (flying or on_deck):
            catalog_goal = MapDestination(1439, point['x'], point['y'], 'alive', point['name'])
            goal, custom = self._manual_camp(catalog_goal)
            planned_level = lookup['character'][-1]
            trip = WalkingTrip.resume_auberdine(session, goal, level=planned_level,
                camp_road=custom, catalog_goal=catalog_goal if custom else None,
                connections=self._connection_legs(), catalog_zone=point['zone'], faction=character.faction)
            self._leveling_trip = character.faction, planned_level, trip
            self._leveling_destination = self._camp_scout = None
            self._leveling_checkpoint_session = session
        elif flying:
            return False
        elif lookup['character'] != identity or 'arrival_connection' in lookup:
            key = lookup.get('arrival_connection')
            maps = lookup['walking_maps']
            if (not isinstance(key, list) or len(key) != 8 or character.map_id != maps[0]
                    or character.life != 'alive' or not character.outdoors):
                return False
            roads = walking_legs(self._connection_legs())
            leg = next((road for road in roads if road.blocked_key == tuple(key)), None)
            if leg is None or leg.destination != character.map_id or not leg.arrival_road or leg.taxi:
                return False
            following = (next((road for road in roads
                               if (road.source, road.destination) == (maps[0], maps[1])), None)
                         if len(maps) > 1 else None)
            if len(maps) > 1 and following is None:
                return False
            position = navigation() if navigation is not None else None
            if position is None:
                self._travel_restore_attempted = None
                return True
            if lookup['character'] == identity:
                if not self._plan_land_travel(session, character, point, lookup, arrival=(leg, following, position)):
                    return False
                self._leveling_checkpoint_session = session
                self._leveling_camps = []
                self.logger.append(f"已恢复换图接入段，走完后继续前往「{point['name']}」。")
                return True
            planned_level = lookup['character'][-1]
            trip = WalkingTrip.resume_arrival(session, leg, following, position, level=planned_level,
                                               faction=character.faction)
            if trip is None:
                return False
            self._leveling_trip = character.faction, planned_level, trip
            self._leveling_destination = self._camp_scout = None
            self._leveling_checkpoint_session = session
            self._leveling_camps = []
            self.logger.append(f'已恢复升级前的换图接入段，走完后按 {character.level} 级重新选点。')
            return True
        elif character.map_id == lookup['walking_maps'][-1]:
            goal = MapDestination(character.map_id, point['x'], point['y'], 'alive', point['name'])
            requires_approach = ((character.map_id == 1433 and redridge_camp_requires_road(goal.x, goal.y))
                                  or (len(lookup['walking_maps']) == 1 and bool(camp_access_road(goal))))
            if (character.map_id == 1438 and not local_camp_on_current_shore(character, goal)):
                if not self._plan_land_travel(session, character, point, lookup):
                    return False
                self._save_leveling_travel(session, character, self._leveling_trip[2])
            elif (character.zone != point['zone'] or not local_camp_on_current_shore(character, goal)
                    or (requires_approach and not camp_access_road(goal, origin=character)
                        and not manual_camp_road(self._manual_routes(), goal))):
                return False
            else:
                self._set_local_camp(session, character, point)
                self._leveling_checkpoint_session = session
        elif self._plan_land_travel(session, character, point, lookup):
            self._save_leveling_travel(session, character, self._leveling_trip[2])
        else:
            return False
        self._leveling_camps = []
        self.logger.append(f"已从当前地图恢复未完成的练级路线，继续前往「{point['name']}」。")
        return True

    def _replan_local_camp(self):
        self._leveling_trip = self._leveling_destination = self._camp_position = self._local_access = None
        self._leveling_camps = []
        self._clear_leveling_travel()
        planner = self._leveling_planner
        if planner is not None:
            planner.request_replan()
        self.logger.append('角色已在另一侧湖岸，从当前位置重新查询可达的营地。')

    def _manual_camp(self, catalog_goal):
        from dataclasses import replace
        road = manual_camp_road(self._manual_routes(), catalog_goal)
        if not road:
            return catalog_goal, ()
        x, y = road[-1]
        self.logger.append(f'使用你在世界地图标记的 {len(road)} 个路点，寻怪终点 ({x:.2f}, {y:.2f})。')
        return replace(catalog_goal, x=x, y=y), road

    def _set_local_camp(self, session, character, point):
        from wowbuddy.automation.navigation import MapDestination
        from wowbuddy.automation.walking_route import WalkingTrip, camp_access_road
        self._camp_scout = None
        catalog_goal = MapDestination(character.map_id, point['x'], point['y'], 'alive', point['name'])
        target, custom = self._manual_camp(catalog_goal)
        road = custom or camp_access_road(catalog_goal, origin=character)
        if road:
            trip = WalkingTrip(session, (), target, level=character.level, camp_road=road,
                               catalog_goal=catalog_goal if custom else None,
                               connections=self._connection_legs(), catalog_zone=character.zone)
            self._leveling_trip = character.faction, character.level, trip
            self._leveling_destination = None
        else:
            self._leveling_trip = None
            self._leveling_destination = session, character.route_key, target
        return target

    def _plan_land_travel(self, session, character, point, lookup, *, arrival=None):
        from wowbuddy.automation.navigation import MapDestination
        from wowbuddy.automation.walking_route import (WalkingTrip, connection_map_ids, plan_walking_route,
                                           source_road_blocks, walking_legs)
        blocked_connections = {tuple(road) for road in lookup.get('blocked_connections', ())}
        connections = self._connection_legs()
        zone_ids = connection_map_ids(connections, camp_routes=tuple(self._manual_routes(connections=connections)))
        target_map = zone_ids.get(point['zone'])
        # 旧存档仅记出入口，无法确认受阻的是当前路线，允许重新尝试。
        blocked = frozenset(leg for leg in walking_legs(connections)
                            if blocked_connections and leg.blocked_key in blocked_connections)
        legs = None
        saved_maps = lookup.get('walking_maps')
        origin = (character.x, character.y)
        if arrival is not None:
            arrival_leg, following, position = arrival
            origin = WalkingTrip.connection_arrival_road(arrival_leg, following)[-1]
        if (target_map is not None and zone_ids.get(character.zone) == character.map_id
                and (not saved_maps or target_map == saved_maps[-1])):
            legs = plan_walking_route(character.map_id, target_map, character.level, 'alive',
                                      blocked_legs=blocked | source_road_blocks(
                                          character.map_id, *origin, elevation=character.elevation),
                                      connections=connections, origin=origin,
                                      faction=character.faction, destination_xy=(point['x'], point['y']),
                                      allow_taxi=self.grind_check.isChecked())
        if legs is None or (not legs and arrival is None):
            self.logger.append(f"前往{point['zone']}没有已核对的完整陆路。")
            return False
        if arrival is not None:
            next_leg = legs[0] if legs else None
            if ((next_leg.destination if next_leg else None)
                    != (following.destination if following else None)):
                return False
        catalog_goal = MapDestination(target_map, point['x'], point['y'], 'alive', point['name'])
        goal, custom = self._manual_camp(catalog_goal)
        options = dict(level=character.level, camp_road=custom, catalog_goal=catalog_goal if custom else None,
                       blocked_legs=blocked, connections=connections, catalog_zone=point['zone'],
                       faction=character.faction)
        if arrival is None:
            trip = WalkingTrip(session, legs, goal, **options)
        else:
            trip = WalkingTrip.resume_arrival(session, arrival_leg, next_leg, position,
                                              goal=goal, legs=legs, **options)
            if trip is None:
                return False
        self._camp_scout = None
        self._leveling_trip = character.faction, character.level, trip
        self._leveling_destination = None
        lookup['walking_maps'] = [character.map_id, *(leg.destination for leg in legs)]
        travel = '陆路及飞行航线' if any(leg.taxi for leg in legs) else '陆路'
        self.logger.append(f"已规划前往{point['zone']}的{travel}，等游戏逐段确认。")
        return True

    def _rejoin_camp_after_revival(self, session, character, position):
        """返回是否已完成复活后的接路判断。"""
        from wowbuddy.automation.walking_route import (WalkingTrip, auberdine_repair_road, camp_access_road, grove_supply_road,
                                           rejoin_darkshore_patrol_return, rejoin_grove_return_road, resume_supply_road)

        online = self._online_vendor
        if online and online[0][0] == session and online[0][2]:
            context, outbound, returning = online
            if (character is None or position is None or position.moving or position.life != 'alive'
                    or position.map_id != returning.goal.map_id):
                return False
            active = self._leveling_trip
            if active and active[2] is outbound and not outbound.goal.contains(position):
                service_road = auberdine_repair_road if self._vendor_run.repair else grove_supply_road
                road = service_road(position)
                if not road:
                    if not self._post_revival_notice:
                        self.logger.append('复活点尚未接入商人路线，暂停补给赶路。')
                        self._post_revival_notice = True
                    return False
                outbound = WalkingTrip(session, (), outbound.goal, level=character.level,
                                       camp_road=road, faction=character.faction)
                self._online_vendor = context, outbound, returning
                self._leveling_trip = character.faction, character.level, outbound
                self.logger.append('复活后已从当前位置重新接入商人路线。')
            elif (active and active[2] is returning
                  and (not returning.complete or not returning.goal.contains(position))):
                saved_road = returning.approach_road or ((returning.goal.x, returning.goal.y),)
                road = resume_supply_road(saved_road, position)
                if not road:
                    road = (rejoin_darkshore_patrol_return(saved_road, position, repair=self._vendor_run.repair)
                            if self._patrol_route is not None else rejoin_grove_return_road(returning.goal, position))
                if not road:
                    if not self._post_revival_notice:
                        self.logger.append('复活点尚未接入黑海岸返营道路，暂停补给赶路。')
                        self._post_revival_notice = True
                    return False
                returning = WalkingTrip(session, (), returning.goal, level=character.level,
                                        camp_road=road, faction=character.faction,
                                        catalog_zone=returning.catalog_zone, arrival_message=returning.arrival_message,
                                        finish_in_range=self._patrol_route is not None)
                self._online_vendor = context, outbound, returning
                self._leveling_trip = character.faction, character.level, returning
                self.logger.append('复活后已从当前位置重新接入黑海岸返营道路。')
            return True

        plan = self._leveling_destination
        if plan is None or plan[0] != session:
            return True
        if (character is None or position is None or position.moving or position.life != 'alive'
                or position.map_id != character.map_id):
            return False
        if plan[1] != character.route_key:
            return True
        camp = plan[2]
        if camp.contains(position):
            return True
        fixed = self._fixed_camp_route
        if self._patrol_route is not None:
            points = self._patrol_route.points
            marked = points[self._patrol_index - 1], points[self._patrol_index]
        elif fixed and fixed.map_id == camp.map_id and fixed.endpoint == (camp.x, camp.y):
            marked = fixed.points if len(fixed.points) > 1 else ()
        else:
            marked = manual_camp_road(self._manual_routes(), camp)
        road = resume_supply_road(marked, position) if marked else camp_access_road(camp, origin=position)
        if road:
            catalog_goal = None
            if marked:
                active = self._leveling_trip
                previous = active[2] if active and active[2].session == session else None
                catalog_goal = previous.catalog_goal if previous and previous.goal == camp else camp
            trip = WalkingTrip(session, (), camp, level=character.level, camp_road=road,
                               catalog_goal=catalog_goal, connections=self._connection_legs(),
                               catalog_zone=character.zone, faction=character.faction,
                               finish_in_range=self._patrol_route is not None)
            self._leveling_trip = character.faction, character.level, trip
            self._leveling_destination = None
            self._save_leveling_travel(session, character, trip)
            self.logger.append(f'复活后从当前位置重新接入前往「{camp.label}」的道路。')
        elif marked or camp_access_road(camp):
            if fixed is not None:
                if not self._post_revival_notice:
                    self._post_revival_notice = True
                    self.logger.append('复活点暂未接入固定营地道路，等待新的站定定位。')
                return False
            self._leveling_camps = []
            self._advance_grind_camp(session, character, camp, '复活点无法接入原营地道路', path_blocked=True)
        return True

    def _poll_revival(self, session, state, rect, *, prefer_clearance=False, **readings):
        return self.unattended.revival.poll(self, session, state, rect, prefer_clearance=prefer_clearance, **readings)

    def _render_unattended_idle(self, tick, hwnd, character, position, destination, *, routing, movement):
        if tick is None or tick.selected is not None:
            return
        decision = tick.decision
        fields = decision.frame.values
        if (not decision.frame.ok or fields.get('player_valid') != 'ON'
                or fields.get('player_in_combat') != 'OFF' or fields.get('target_valid') != 'OFF'
                or any(not candidate.stop or candidate.tag == '恢复' for candidate in decision.candidates)):
            return
        if not decision.recovery_ready:
            message = ('自动吃喝已关闭，等待血量和法力达到设置阈值。' if decision.recovery_disabled
                       else '等待游戏确认恢复状态。')
        elif destination is None:
            if routing:
                message = '等待游戏确认当前陆路路段。'
            elif character is None:
                message = '等待游戏确认角色和地图位置。'
            elif self._fixed_camp_route is not None:
                message = '等待可达的固定打怪点。路线详情见运行日志。'
            else:
                message = '等待可达的练级点。查询结果见运行日志。'
        elif position is None:
            message = f'前往「{destination.label}」前，等待可用的角色定位。'
        else:
            activity = (f'在「{destination.label}」寻找目标' if not routing and destination.contains(position)
                        else f'前往「{destination.label}」')
            message = (f'等待游戏回到前台，再{activity}。' if movement and movement.in_foreground(hwnd) is False
                       else f'无人托管：{activity}。')
        self.ui.suggestions.setPlainText(message)

    def _poll_navigation(self, result, session, image, frame, character, death, *, navigate):
        from math import hypot
        from wowbuddy.engine.character_state import decode_mob_state, decode_navigation_state, decode_target_bearing
        from wowbuddy.automation.death_recovery import CorpseAccess
        from wowbuddy.core.dev_protocol import bag_recovery_walk_safe
        from wowbuddy.automation.navigation import ForegroundMovement, MapDestination, MapNavigator, TargetApproach
        from wowbuddy.automation.walking_route import camp_scan_corridor_contains
        from wowbuddy.win32.windows_keys import is_foreground
        stopping = result.tick is not None and result.tick.status == 'movement_stopping'
        if death is not None and death.life in ('dead', 'ghost'):
            self._dispatch_stop_session = None
        elif stopping or self._dispatch_stop_session == session:
            # 等待施法的停步跨越多个画面，即使移动期间规则暂时不再命中。
            self._dispatch_stop_session = session
            if stopping or frame is None or not frame.ok or not self._stop_before_action(frame.values):
                self._release_navigation_key()
                self.ui.suggestions.setPlainText('正在停步，等待游戏确认后施法')
                return
            self._dispatch_stop_session = None
        position = decode_navigation_state(image, frame) if image is not None and frame else None
        unattended = self.grind_check.isChecked()
        vendor_wait = self._vendor_wait
        if (unattended and frame and vendor_wait and vendor_wait[0] == session
                and (death is None or death.life == 'alive') and frame.values.get('player_valid') == 'ON'
                and frame.values.get('player_in_combat') == 'OFF'):
            self._release_navigation_key()
            self.ui.suggestions.setPlainText(vendor_wait[1])
            return
        active = self._leveling_trip
        vendor_trip = (active[2] if unattended and self._vendor_run.session == session
                       and self._vendor_run.active and active and active[2].session == session
                       and active[2].goal.label == '补给商人' else None)
        red_equipment = bool(unattended and frame and frame.values.get('equipment_red') == 'ON'
                             and (death is None or death.life == 'alive')
                             and frame.values.get('player_in_combat') == 'OFF')
        if red_equipment and vendor_trip is None and self._online_vendor is None:
            self._release_navigation_key()
            return
        if (vendor_trip and vendor_trip.complete and position and vendor_trip.goal.contains(position)
                and frame.values.get('player_in_combat') == 'OFF'):
            self._release_navigation_key()
            return
        recovery_ready = bool(result.tick and result.tick.decision.recovery_ready)
        quest = self._quest_trip
        if (unattended and navigate and quest and quest.session == session and frame
                and frame.values.get('player_in_combat') == 'OFF'):
            self._walk_to_quest(result, session, character, position, quest)
            return
        vendor_recovery_walk = bool(vendor_trip and self._vendor_recovery_walk == session and frame
                                    and bag_recovery_walk_safe(frame) and result.tick
                                    and position and (position.moving or any(
                                        item.action == 'recovery_bag_full' for item in result.tick.decision.candidates))
                                    and all(item.stop for item in result.tick.decision.candidates if item.tag == '恢复'))
        travel_ready = not unattended or recovery_ready
        nearby = str(frame.values.get('enemies_8yd', '')) if frame and frame.ok else ''
        patrol_crowded = (unattended and self._patrol_route is not None
                          and nearby.isdecimal() and int(nearby) >= _PATROL_CROWD_LIMIT
                          and frame.values.get('player_in_combat') == 'OFF')
        approach = self._target_approach
        now = self.monotonic_ms()
        if unattended and navigate:
            if death and death.life == 'dead':
                self._observe_camp_death(session, image, frame, now)
            elif death and death.life == 'ghost':
                self._camp_position = None
            elif character is not None and position is not None:
                camp = self._camp_death_target(session, character)
                self._camp_position = ((camp, position)
                                       if camp and camp[2].contains(position, radius=_CAMP_DEATH_RADIUS) else None)
        if unattended and approach is not None and frame is not None:
            target_valid = frame.values.get('target_valid')
            approach.observe_selection(session, position, target_valid, now)
            discard = approach.confirmed_discard(session, position, target_valid, now)
            if discard is not None:
                origin, rejection = discard
                plan = self._leveling_destination
                camp = plan[2] if character and plan and plan[:2] == (session, character.route_key) else None
                search_point = self._camp_scout_point(session, camp) or camp
                if rejection:
                    pull = self._arrival_pull
                    if (pull and camp and origin is not None
                            and pull.record_rejected_target(session, search_point, origin, now)):
                        self._advance_grind_camp(session, character, camp, '当前刷怪区连续遇到不适合练级的目标')
                else:
                    self.logger.append('游戏已确认清除无法接近的目标。')
                    if camp and origin is not None and search_point.contains(origin):
                        if not self._start_camp_scout(session, camp, position):
                            self._advance_grind_camp(session, character, camp, '当前刷怪区的目标无法接近')
        destination = None
        camp = scout = None
        pull_position = None
        approach_position = None
        sight_blocked = bool(result.tick and result.tick.decision.attack_blocked_by_sight)
        target_rejection = result.tick.decision.target_rejection if result.tick else None
        range_blocked = (image is not None and frame and result.tick and result.tick.selected is None
                         and (result.tick.decision.attack_blocked_by_range or sight_blocked
                              or (target_rejection and frame.values.get('player_in_combat') == 'OFF'))
                         and (travel_ready or frame.values.get('player_in_combat') == 'ON'))
        if range_blocked:
            approach_position = position
            if frame.values.get('player_in_combat') == 'ON':
                approach_position = decode_navigation_state(image, frame, for_target=True)
            if approach_position is not None and approach_position.life != 'alive':
                approach_position = None
        walking_leg = False
        finishing_connection = False
        path = None
        access = None
        if not navigate:
            self._local_access = None
        corpse_access = None
        corpse_trip = None
        corpse = None
        near_corpse = False
        revival = self._automatic_revival
        landing = revival.landing_destination if revival and revival.session == session else None
        if navigate and death and death.life == 'ghost' and death.corpse is not None:
            if death.button is None and self._corpse_trail.waiting_for_start:
                self._release_navigation_key()
                self.ui.suggestions.setPlainText('等待释放灵魂后的墓地地图与坐标稳定。')
                return
            if landing is not None:
                destination = landing
                position = (decode_navigation_state(image, frame, for_revival=True)
                            if death.popup in ('legacy', 'missing', 'ready') else None)
            else:
                corpse = MapDestination(*death.corpse, 'ghost', '尸体')
                if death.button is not None or death.popup not in ('legacy', 'missing'):
                    position = None
                if self._ghost_origin is None:
                    from wowbuddy.automation.death_recovery import GhostOrigin
                    self._ghost_origin = GhostOrigin()
                resumed = self._ghost_origin.observe(session, position)
                if resumed:
                    self.logger.append(resumed)
                    self._corpse_access = None
                # 尸体附近交给现有复活探点，避免又被起点路线带走。
                near_corpse = (position is not None and position.map_id == corpse.map_id
                               and hypot(*corpse.offset_from(position)) <= 20)
                if not near_corpse and not self._start_recorded_corpse_trip(session, position, corpse):
                    access, destination = self._observe_local_access(
                        session, 'ghost', position, include_manual=unattended)
                if access is not None:
                    path = access
                else:
                    faction = character.faction if character else None
                    if not faction and active and active[2].session == session:
                        faction = active[0]
                    destination = self._corpse_route(session, position, corpse,
                                                    faction=faction)
                    corpse_trip = self._corpse_trip
                    if corpse_trip is not None and not corpse_trip.complete:
                        path = corpse_trip
                existing = self._corpse_access
                if path is None and (position is None and existing is not None
                                     or position is not None and position.map_id == corpse.map_id):
                    # 直达或备选点已经确定时，缺定位只松键，不切换导航目的地。
                    corpse_access = existing
                    if corpse_access is None:
                        corpse_access = self._corpse_access = CorpseAccess()
                    destination, status = corpse_access.observe(session, position, corpse, now)
                    if status:
                        self.logger.append(status)
                elif existing is not None:
                    existing.pause()
        elif navigate and (not death or death.life == 'alive'):
            if death and death.life == 'alive':
                self._corpse_trip = None
                self._corpse_access = None
                self._grid_corpse_trip = self._grid_corpse_given_up = None
            recovering_from_death = unattended and self._post_revival_session == session
            if recovering_from_death and death and death.life == 'alive' and (recovery_ready or vendor_recovery_walk):
                if self._rejoin_camp_after_revival(session, character, position):
                    self._post_revival_session = None
                    recovering_from_death = False
            if recovering_from_death:
                if (result.tick and result.tick.decision.recovery_disabled
                        and not self._post_revival_notice):
                    self._post_revival_notice = True
                    self.logger.append('自动吃喝已关闭，等待血量和法力达到设置的开始阈值再继续赶路。')
                position = approach_position = None
                range_blocked = False
            active = self._leveling_trip
            trip = active[2] if active and active[2].session == session else None
            finishing_connection = (unattended and trip is not None and character is not None
                                    and character.faction == active[0] and character.level > active[1]
                                    and trip.needs_safe_handoff(character.map_id, now))
            trip_matches_character = (trip is None or (character is not None
                                      and (finishing_connection or (character.faction, character.level) == active[:2])))
            returning = (trip is not None and trip_matches_character
                         and trip.is_recent_crossing_return(character.map_id, now))
            online = self._online_vendor
            supply_return = bool(unattended and online and online[0][0] == session and trip is online[2])
            if trip is not None and trip.complete and not (returning or trip is vendor_trip or supply_return):
                trip = None
            if (patrol_crowded and trip is not None and trip is not vendor_trip
                    and not supply_return and not returning and not finishing_connection
                    and position is not None and position.map_id == trip.goal.map_id
                    and trip.goal.label.startswith('循环路点') and not trip.goal.contains(position)):
                self._release_navigation_key()
                self.ui.suggestions.setPlainText(f'8 码内有 {nearby} 只怪，暂停前往{trip.goal.label}。')
                return
            supply_walk = vendor_recovery_walk and trip is vendor_trip
            ready_to_walk = (character is not None and trip_matches_character and (travel_ready or supply_walk)
                             and frame.values.get('player_in_combat') != 'ON'
                             and result.tick.selected is None
                             and not recovering_from_death
                             and (frame.values.get('target_valid') == 'OFF'
                                  or (unattended and trip is not None and (result.tick.status == 'no_candidates' or supply_walk
                                                                           or (vendor_trip and red_equipment))
                                      and frame.values.get('target_valid') == 'ON'))
                             and (supply_walk or not any(candidate.tag == '恢复' for candidate in result.tick.decision.candidates)))
            patrol_walk = (unattended and self._patrol_scan_enabled() and self._patrol_route is not None
                           and trip is not None and trip is not vendor_trip and not supply_return and not returning
                           and not finishing_connection and trip.goal.label.startswith('循环路点'))
            if patrol_walk and self._travel_engaged(session):
                # 途中交战：停住行程（不跳点），交给循环、射程外接近与清目标逻辑。
                ready_to_walk = False
            elif not patrol_walk and self._travel_scan is not None and self._travel_scan.engaged is not None:
                self._travel_scan.engaged = None
            elif (patrol_walk and not ready_to_walk and self._travel_scan is not None and self._travel_scan.watching
                  and character is not None and trip_matches_character and travel_ready
                  and not recovering_from_death and result.tick.selected is None
                  and frame.values.get('player_in_combat') != 'ON' and frame.values.get('target_valid') == 'ON'
                  and not any(candidate.tag == '恢复' for candidate in result.tick.decision.candidates)):
                # 行走中选到的目标还在射程外：照常赶路，进入射程再停（经典版拿不到怪物方位，停下也无法接近）。
                ready_to_walk = True
            plan = self._leveling_destination
            if unattended and (trip or (plan and character and plan[:2] == (session, character.route_key))):
                access, destination = self._observe_local_access(session, 'alive', position if ready_to_walk else None)
                if access is not None:
                    walking_leg = True
                    path = access
            if not walking_leg and trip is not None:
                replans = trip.replan_count
                arrival = trip.arrival_connection
                taxi_options = {}
                if trip.waiting_for_taxi and image is not None and frame and frame.ok and result.capture:
                    from wowbuddy.engine.character_state import decode_taxi_state
                    taxi_options['taxi_reading'] = decode_taxi_state(image, frame)
                    if ready_to_walk and frame.values.get('player_in_combat') == 'OFF':
                        taxi_options['taxi_send'] = lambda action, value: self._send_travel_ui_action(
                            session[0], frame.values, result.capture.client_rect, action, value)
                destination, status = trip.observe(position if ready_to_walk else None,
                                                   now_ms=self.monotonic_ms(), **taxi_options)
                if status:
                    self.logger.append(status)
                if unattended and trip is not vendor_trip:
                    if finishing_connection and arrival is not None and trip.arrival_connection is None:
                        self._clear_leveling_travel()
                    elif trip.replan_count != replans or trip.arrival_connection != arrival:
                        self._save_leveling_travel(session, character, trip)
                # 补给往返均由补给流程核对实际到达后交接。
                walking_leg = (not trip.complete or returning or trip is vendor_trip
                               or supply_return or finishing_connection)
                if finishing_connection and trip.complete and not returning:
                    destination = None
                if walking_leg:
                    path = trip
                    if unattended and trip_matches_character and trip.travel_exhausted:
                        self._retire_blocked_travel(session, character, trip)
                else:
                    self._leveling_destination = session, character.route_key, trip.goal
            if patrol_walk:
                scan_status = self._travel_scan_for().observe(
                    session, (session, self._patrol_index),
                    walking=walking_leg and ready_to_walk and position is not None and not patrol_crowded,
                    position=position, tick=result.tick, now_ms=now,
                    send_interval_ms=self.ui.send_interval_spin.value())
                if scan_status:
                    if self._travel_engaged(session):
                        self._release_navigation_key()
                        self.logger.append(f'{scan_status}（原停留点：{trip.goal.label}）。')
                        ready_to_walk = False
                    else:
                        self.logger.append(f'{scan_status}，继续前往{trip.goal.label}。')
            if unattended and ((walking_leg and ready_to_walk and position is not None)
                               or (self._leveling_upgrade_wait == session
                                   and frame and frame.values.get('player_in_combat') == 'OFF')
                               or (self._fixed_camp_route is not None and self._fixed_camp_blocked is not None)
                               or (character is not None and not trip_matches_character)):
                # 赶路或等待新等级路线时，跳过脱战时残留的射程外目标。
                approach_position = None
                range_blocked = False
            plan = self._leveling_destination
            if not walking_leg and plan and plan[0] == session:
                camp = plan[2]
                scout = self._camp_scout_point(session, camp) if unattended else None
                destination = scout or camp
                current_plan = character and character.route_key == plan[1]
                if (current_plan and position is not None
                        and self._leveling_checkpoint_session == session
                        and camp.contains(position)):
                    self._clear_leveling_travel()
                if current_plan and not recovering_from_death:
                    pull_position = position
                if not current_plan or not ready_to_walk:
                    position = None
                if scout is not None and position is not None:
                    if self._patrol_route is not None:
                        if patrol_crowded:
                            self._release_navigation_key()
                            position = None
                        elif not camp.contains(position):
                            self._advance_patrol('已离开当前路点补扫范围')
                            return
                    elif not camp_scan_corridor_contains(camp, scout, position):
                        self._advance_grind_camp(session, character, camp, '角色已离开营地补扫道路')
                        destination = pull_position = position = None
        if patrol_crowded and approach_position is not None and range_blocked and not target_rejection:
            target_rejection = f'8 码内有 {nearby} 只怪，放弃追这个射程外的目标'
        bearing = (decode_target_bearing(image, frame, approach_position)
                   if approach_position and not (sight_blocked or target_rejection) else None)
        if range_blocked and approach_position is None:
            delay = '游戏暂未提供可移动的角色定位'
        elif range_blocked and bearing is None and not (sight_blocked or target_rejection):
            delay = '游戏暂未提供目标方位'
        elif range_blocked and not is_foreground(self.sender.backend, session[0]):
            delay = '游戏窗口未在前台'
        else:
            delay = None
        if delay:
            now = self.monotonic_ms()
            last = self._approach_notice
            if last is None or last[0] != session or (last[1] != delay and now - last[2] >= 3000):
                reason = target_rejection or ('目标视线受阻，等待重选' if sight_blocked else '目标在射程外，等待接近')
                self.logger.append(f'{reason}。{delay}。')
                self._approach_notice = session, delay, now
        navigator = self._map_navigator
        if navigator is None and (approach_position is not None or (position is not None and destination is not None)):
            movement = ForegroundMovement(self.sender.backend, self.monitor.backend,
                                          on_forward=self._wait_for_navigation_stop)
            navigator = self._map_navigator = MapNavigator(movement)
        if unattended:
            self._render_unattended_idle(result.tick, session[0], character, position, destination,
                                         routing=walking_leg, movement=navigator.movement if navigator else None)
        if navigator is None:
            return
        navigator.grid = self._walk_grid
        approaching = approach_position is not None
        was_approaching = self._approaching_target
        if was_approaching and not approaching:
            self._release_navigation_key()
            self._target_approach.observe(session, None, None)
        if not approaching or not was_approaching:
            status = navigator.observe(session, session[0], None if approaching else position, destination, path=path)
            self._observe_steering(session, position)
            if status:
                self.logger.append(status)
                if navigator.blocked:
                    if landing is not None and destination is landing:
                        retry = revival.landing_blocked()
                        if retry:
                            self._corpse_trip = self._corpse_access = None
                            self.logger.append(retry)
                    elif corpse_access is not None:
                        origin = self._ghost_origin
                        stuck = origin.blocked(position, corpse) if origin is not None else None
                        if stuck:
                            corpse_access.give_up()
                            self.logger.append(stuck)
                        else:
                            _, retry = corpse_access.observe(session, position, corpse, now, blocked=destination)
                            if retry:
                                self.logger.append(retry)
                    elif path is not None and path is access:
                        access.blocked = True
                        self.logger.append('起点接入路线受阻。请检查标记的通道，或手动通过后重新开始监控。')
                    elif path is not None and path.connecting:
                        replans = path.replan_count
                        reroute = path.avoid_blocked_road(position, destination)
                        if reroute:
                            self.logger.append(reroute)
                        if unattended and path.goal.life == 'alive':
                            if path.travel_exhausted:
                                self._retire_blocked_travel(session, character, path)
                            elif path.replan_count != replans:
                                self._save_leveling_travel(session, character, path)
                    elif corpse_trip is not None and path is corpse_trip:
                        if corpse_trip is self._grid_corpse_trip:
                            # 导航器内部已按格子重算过；不再“保留原路点等待”，回到常规跑尸链。
                            self._grid_corpse_given_up = session
                            self._grid_corpse_trip = self._corpse_trip = None
                            self.logger.append('格子跑尸路线受阻，本次放弃地图格子路线，改用常规跑尸。')
                        elif corpse_trip is self._learned_corpse_trip:
                            self._discard_recorded_corpse_trip()
                        elif near_corpse and destination.allow_detour:
                            corpse_trip.finish_corpse_approach()
                            self._corpse_access = CorpseAccess()
                            _, retry = self._corpse_access.observe(session, position, corpse, now, blocked=corpse)
                            self.logger.append(retry)
                        else:
                            self.logger.append('跑尸接入路段受阻，保留原路点，等待重新接入。')
                    elif unattended:
                        if self._online_vendor and path in self._online_vendor[1:]:
                            self.logger.append('补给路线受阻，保留原营地和商人路点。')
                        elif finishing_connection and path is trip and path is not vendor_trip:
                            self._retire_blocked_travel(session, character, path)
                        elif scout is not None and self._patrol_route is not None:
                            self._advance_patrol('当前路点补扫受阻')
                            return
                        else:
                            blocked_waypoint = destination if path and not destination.allow_detour else None
                            goal = camp if scout is not None else path.goal if path else destination
                            if path is vendor_trip and vendor_trip is not None:
                                reason = '前往补给商人的路线受阻'
                            else:
                                reason = '营地补扫路段受阻' if scout is not None else '前往当前刷怪区的路线受阻'
                            self._advance_grind_camp(session, character, goal, reason, path_blocked=path is not None,
                                                     blocked_waypoint=blocked_waypoint)
                            if scout is not None:
                                destination = pull_position = None
        self._approaching_target = approaching
        pursuing = False
        exhausted = False
        if approaching:
            if approach is None:
                approach = self._target_approach = TargetApproach(navigator.movement)
            tick = result.tick
            can_retarget = (unattended and frame.values.get('player_in_combat') == 'OFF'
                            and frame.values.get('player_valid') == 'ON'
                            and frame.values.get('target_valid') == 'ON'
                            and tick.status in ('no_candidates', 'suppressed') and tick.decision.recovery_ready)
            scan_in_combat = (unattended and frame.values.get('player_in_combat') == 'ON'
                              and frame.values.get('mob_policy') == 'ON'
                              and not (sight_blocked or target_rejection)
                              and tick.status in ('no_candidates', 'suppressed'))
            status = approach.observe(session, approach_position, bearing, now_ms=now,
                                      allow_unlocated=can_retarget, sight_blocked=sight_blocked and can_retarget,
                                      target_rejection=target_rejection if can_retarget else None,
                                      scan_in_combat=scan_in_combat)
            pursuing = approach.pursuing
            if status:
                self.logger.append(status)
            if pursuing:
                self._approach_notice = None
            if unattended:
                exhausted = approach.exhausted_for(session, approach_position)
                ready = (exhausted and can_retarget
                         and tick.display_now_ms - self.dispatcher.state.last_sent_ms
                         >= self.ui.send_interval_spin.value())
                status = approach.retarget(session, approach_position, allowed=ready, now_ms=now,
                                           target_rejection=target_rejection)
                if status:
                    self.logger.append(status)
        if unattended:
            from wowbuddy.automation.arrival_pull import ArrivalPull
            pull = self._arrival_pull
            if pull is None:
                pull = self._arrival_pull = ArrivalPull(self.dispatcher, navigator.movement)
            patrol_ready = (self._patrol_route is not None and camp is not None and not walking_leg
                            and pull_position is not None and not pull_position.moving
                            and travel_ready and frame.values.get('player_valid') == 'ON'
                            and frame.values.get('player_in_combat') == 'OFF'
                            and frame.values.get('target_valid') == 'OFF'
                            and result.tick.selected is None and not self._online_vendor
                            and not self._vendor_run.active
                            and not any(candidate.tag == '恢复' for candidate in result.tick.decision.candidates))
            if patrol_ready:
                mob = decode_mob_state(image, frame)
                patrol_ready = mob is not None and not mob.loot_open
            if patrol_ready and self._patrol_kill == (session, camp):
                if not nearby.isdecimal() or int(nearby) == 0:
                    self._advance_patrol('击杀后的拾取处理已结束，近处未确认还有怪物')
                    return
                self._patrol_kill = None
                self.logger.append(f'恢复和拾取处理结束，8 码内还有 {nearby} 只怪物，继续逐只选怪。')
            approach_waiting = approaching and approach.waiting_for_input_or_bearing
            scan = self._travel_scan
            pull.sectors = (3 if self._patrol_scan_enabled() and scan is not None
                            and scan.scanned((session, self._patrol_index)) else 4)
            status = pull.observe(session, None if walking_leg else destination, pull_position, result.tick,
                                  self.monotonic_ms(), self.ui.send_interval_spin.value(), pursuing=pursuing,
                                  allow_retarget=not (exhausted or approach_waiting))
            if status:
                self.logger.append(status)
                if pull.empty:
                    if patrol_ready:
                        if (not patrol_crowded and self._camp_scout_allowed()
                                and self._start_camp_scout(session, camp, pull_position)):
                            return
                        self._advance_patrol('当前路点未找到可攻击目标')
                    elif self._patrol_route is None and not self._start_camp_scout(session, camp, pull_position):
                        self._advance_grind_camp(session, character, camp or destination, '当前刷怪区未选到怪物')

    def _advance_patrol(self, reason):
        count = len(self._patrol_route.points)
        previous = self._patrol_index
        self._patrol_index = (previous + 1) % count
        self._patrol_kill = None
        self._fixed_camp_scope = self._fixed_camp_blocked = None
        self._leveling_trip = self._leveling_destination = self._camp_scout = None
        self._release_navigation_key()
        self.logger.append(f'第 {previous + 1} 点{reason}，前往第 {self._patrol_index + 1}/{count} 点。')

    def _patrol_label(self, index):
        return f'循环路点 {index + 1}/{len(self._patrol_route.points)}'

    def _walk_to_quest(self, result, session, character, position, trip):
        from wowbuddy.automation.navigation import ForegroundMovement, MapNavigator

        if (not result.tick or result.tick.selected is not None or not result.tick.decision.recovery_ready
                or any(candidate.tag == '恢复' for candidate in result.tick.decision.candidates)):
            self._release_navigation_key()
            return
        if position is None:
            self._release_navigation_key()
            return
        if trip.complete and trip.goal.contains(position):
            self._release_navigation_key()
            now = self.monotonic_ms()
            reading = self._quest_dialog_reading
            reason = self._quest_job.deferral_reason(reading, now)
            if reason:
                self._deferred_quest = self._quest_route_scope, now + 60000
                self._quest_trip = self._quest_route_attempt = None
                message = f'{reason}，恢复练级，稍后重试交付。'
                self.logger.append(message)
                self.ui.suggestions.setPlainText(message)
                return
            status = self._quest_job.observe(reading, now, send=lambda action, value:
                self._send_travel_ui_action(session[0], result.tick.decision.frame.values,
                                            result.capture.client_rect, action, value))
            if status:
                self.logger.append(status)
            self.ui.suggestions.setPlainText(self._quest_job.notice)
            return
        replans = trip.replan_count
        destination, status = trip.observe(position, now_ms=self.monotonic_ms())
        if status:
            self.logger.append(status)
        if trip.replan_count != replans:
            self._quest_trip = None
            self._release_navigation_key()
            self.logger.append('交任务路线已变更，重新核对地图出口与接入点。')
            return
        navigator = self._map_navigator
        if navigator is None:
            navigator = self._map_navigator = MapNavigator(ForegroundMovement(
                self.sender.backend, self.monitor.backend, on_forward=self._wait_for_navigation_stop))
        self._render_unattended_idle(result.tick, session[0], character, position, destination,
                                     routing=True, movement=navigator.movement)
        navigator.grid = self._walk_grid
        status = navigator.observe(session, session[0], position, destination, path=trip)
        if status:
            self.logger.append(status)

    def _start_camp_scout(self, session, camp, position):
        from wowbuddy.automation.walking_route import camp_scan_waypoint

        if camp is None or position is None or self._camp_scout_point(session, camp) is not None:
            return False
        if self._patrol_route is not None:
            from math import hypot
            from wowbuddy.automation.navigation import MapDestination

            if position.moving or not position.continuous or not camp.contains(position):
                return False
            distance = hypot(*camp.offset_from(position))
            if distance <= 5:
                return False
            fraction = min(1.0, _PATROL_SCOUT_STEP / distance)
            scout = MapDestination(camp.map_id, position.x + (camp.x - position.x) * fraction,
                                   position.y + (camp.y - position.y) * fraction, 'alive',
                                   '循环路点补扫点', radius=2, allow_detour=False)
        else:
            road = manual_camp_road(self._manual_routes(), camp)
            scout = camp_scan_waypoint(camp, position, manual_road=road)
        if scout is None:
            return False
        self._camp_scout = session, camp, scout
        self.logger.append('原地未能开始战斗，向当前路点短步靠近后再搜一次。'
                           if self._patrol_route is not None else
                           '原地未能开始战斗，沿营地接入道路移动到补扫点。')
        return True

    def _camp_scout_point(self, session, camp):
        scout = self._camp_scout
        if scout is not None and scout[:2] == (session, camp):
            return scout[2]

    def _observe_local_access(self, session, life, position, *, include_manual=True):
        from wowbuddy.automation.manual_routes import GHOST_ACCESS_ROUTES, LocalAccess
        if position is not None and position.life != life:
            position = None
        cached = self._local_access
        if cached is None or cached[0] != session:
            if position is None:
                return None, None
            cached = self._local_access = session, {}
        access = cached[1].get(life)
        if access is None:
            if position is None:
                return None, None
            routes = tuple(self._manual_routes(access=True)) if include_manual else ()
            if life == 'ghost':
                routes += GHOST_ACCESS_ROUTES
            access = cached[1][life] = LocalAccess(routes)
        destination, status = access.observe(position)
        if status:
            self.logger.append(status)
        return (access if access.active else None), destination

    def _retire_blocked_travel(self, session, character, trip):
        active = self._leveling_trip
        if character is None or active is None or active[2] is not trip or trip.session != session:
            return
        if self._fixed_camp_route is not None:
            self._wait_for_fixed_camp(character, f'前往{trip.goal.label}的路线受阻')
            return
        goal = trip.catalog_goal
        zone = trip.catalog_zone
        planner = self._planner_for_character(character)
        if planner is not None:
            planner.retire_travel(session, character, goal, zone, trip.excluded_legs, self.monotonic_ms())
        self._clear_leveling_travel()
        self._leveling_destination = self._leveling_trip = None
        self._leveling_camps = []
        self.logger.append(f'前往{zone}的路线已走不通，从当前地图重新查询可达的刷怪点。')

    def _camp_death_target(self, session, character):
        if self._online_vendor and self._online_vendor[0][0] == session:
            return None
        plan = self._leveling_destination
        if plan and plan[:2] == (session, character.route_key):
            return plan
        active = self._leveling_trip
        if active and active[:2] == (character.faction, character.level):
            trip = active[2]
            if trip.session == session and not trip.connecting and trip.goal.map_id == character.map_id:
                return session, character.route_key, trip.goal
        return None

    def _observe_camp_death(self, session, image, frame, now_ms):
        from dataclasses import replace
        from wowbuddy.engine.character_state import decode_character_state

        sample = self._camp_position
        if not sample or sample[0][0] != session:
            return
        character = decode_character_state(image, frame)
        if (character is None or character.life != 'dead' or not character.outdoors
                or character.x is None or character.y is None):
            return
        # 每次死亡只消耗一条定位记录。死亡坐标沿用该地图已确认的尺寸。
        self._camp_position = None
        plan = self._camp_death_target(session, character)
        if plan != sample[0]:
            return
        site = replace(sample[1], x=character.x, y=character.y)
        destination = plan[2]
        planner = self._leveling_planner
        if destination.contains(site, radius=_CAMP_DEATH_RADIUS) and planner and planner.record_camp_death(
                session, character, destination, now_ms):
            self._advance_grind_camp(session, character, destination, '当前刷怪区反复阵亡', after_deaths=True)

    def _advance_grind_camp(self, session, character, destination, reason, *, path_blocked=False,
                            blocked_waypoint=None, after_deaths=False):
        from wowbuddy.automation.navigation import MapDestination
        from wowbuddy.automation.walking_route import camp_access_road
        plan = self._leveling_destination
        if not character or destination is None:
            return
        if self._fixed_camp_route is not None:
            if path_blocked or '受阻' in reason or after_deaths:
                self._wait_for_fixed_camp(character, reason)
            else:
                self.logger.append(f'{reason}，保留固定打怪点并等待下一轮寻怪。')
            return
        active = self._leveling_trip
        trip = active[2] if active and active[:2] == (character.faction, character.level) else None
        same_trip = (trip is not None and trip.session == session and not trip.connecting
                     and trip.goal == destination and character.map_id == destination.map_id)
        catalog_goal = trip.catalog_goal if same_trip else destination
        blocked_access = ()
        if plan != (session, character.route_key, destination):
            if not same_trip:
                return
            self._leveling_trip = None
            if path_blocked and not manual_camp_road(self._manual_routes(), catalog_goal):
                blocked_access = camp_access_road(catalog_goal)
        planner = self._planner_for_character(character)
        now_ms = self.monotonic_ms()
        self._camp_scout = None
        self._clear_leveling_travel()
        if planner is not None:
            options = {'after_deaths': True} if after_deaths else {}
            planner.retire_camp(session, character, catalog_goal, now_ms, **options)
        camps = self._leveling_camps or []
        if blocked_access or blocked_waypoint:
            manual_routes = self._manual_routes()
            remaining = []
            for point in camps:
                candidate = MapDestination(character.map_id, point['x'], point['y'], 'alive', point['name'])
                shares_access = blocked_access and camp_access_road(candidate) == blocked_access
                shares_waypoint = (blocked_waypoint and (blocked_waypoint.x, blocked_waypoint.y)
                                   in camp_access_road(candidate, origin=character))
                if not manual_camp_road(manual_routes, candidate) and (shares_access or shares_waypoint):
                    if planner is not None:
                        planner.retire_camp(session, character, candidate, now_ms)
                else:
                    remaining.append(point)
            camps = self._leveling_camps = remaining
        if not camps:
            self._leveling_destination = self._leveling_trip = None
            self.logger.append(f'{reason}，正在重新查询可达的刷怪点。')
            return
        point = camps.pop(0)
        target = self._set_local_camp(session, character, point)
        if self._leveling_trip is not None:
            self._save_leveling_travel(session, character, self._leveling_trip[2])
        self.logger.append(f'{reason}，前往下一处「{target.label}」。')

    def _start_recorded_corpse_trip(self, session, position, goal):
        from wowbuddy.automation.walking_route import WalkingLeg, WalkingTrip

        active = self._corpse_trip
        if active is not None and active.session == session and active.goal == goal:
            return active is self._learned_corpse_trip
        if position is None or position.life != 'ghost':
            return False
        segments = self._corpse_trail.replay(self.settings.corpse_trails(), position, goal)
        if not segments:
            return False
        legs = tuple(WalkingLeg(source.map_id, target.map_id, 0, source.points,
                                arrival_road=target.points[:1], manual=True)
                     for source, target in zip(segments, segments[1:]))
        trip = WalkingTrip(session, legs, goal, camp_road=segments[-1].points, catalog_goal=goal)
        self._corpse_trip = self._learned_corpse_trip = trip
        self.logger.append(f'已匹配墓地和尸体位置，复用已记录的跑尸路线，共 {len(segments)} 段。')
        return True

    def _remember_graveyard_exit(self, text, *, scale):
        """把跑尸录制截出的墓地出口存为灵魂起点接入路线；同一墓地（起点 4 码内）已有路线时不重复保存。"""
        from math import hypot
        from wowbuddy.automation.manual_routes import GHOST_ACCESS_ROUTES
        try:
            route = parse_manual_route(text)
        except ValueError:
            return
        routes = self._manual_routes(access=True)
        x, y = route.points[0]
        width, height = scale
        for existing in (*routes, *GHOST_ACCESS_ROUTES):
            ex, ey = existing.points[0]
            if existing.map_id == route.map_id and hypot((ex - x) * width, (ey - y) * height) / 100 <= 4:
                return
        try:
            self.settings.save_manual_routes([*routes.values(), text], access=True)
        except OSError as error:
            self.logger.append('墓地出口路线保存失败。' + str(error))
            return
        self.logger.append(f'已从本次跑尸录制保存墓地出口路线 ({x:.2f}, {y:.2f})，共 {len(route.points)} 个路点。')

    def _discard_recorded_corpse_trip(self):
        self._corpse_trail.replay_blocked = True
        self._corpse_trip = self._learned_corpse_trip = None
        self.logger.append('已记录的跑尸路线受阻，本次改用常规跑尸。')

    def _corpse_route(self, session, position, goal, *, faction=None):
        from wowbuddy.automation.walking_route import (WalkingTrip, camp_access_road, loch_corpse_road,
                                           plan_walking_route, source_road_blocks, walking_legs)
        trip = self._corpse_trip
        if trip is None or trip.session != session or trip.goal != goal:
            self._corpse_trip = None
            if position is None or position.life != 'ghost':
                return goal
            connections = self._connection_legs()
            # 湿地入口可经水坝到东岸已核对的走廊；其他东岸位置依赖玩家标记。
            blocked = source_road_blocks(position.map_id, position.x, position.y)
            if goal.map_id == 1432 and goal.x > 41.5:
                from_wetlands = bool(loch_corpse_road(goal))
                blocked |= frozenset(leg for leg in walking_legs() if leg.destination == goal.map_id
                                     and (leg.source != 1437 or not from_wetlands))
            legs = plan_walking_route(position.map_id, goal.map_id, 0, 'ghost',
                                      connections=connections, blocked_legs=blocked, origin=(position.x, position.y),
                                      faction=faction)
            if legs is None:
                return goal
            grid_road = () if legs else self._grid_corpse_road(session, position, goal)
            if grid_road:
                # 与录制轨迹相同按“手动路点”从首点（灵魂当前位置）依次走，不按直线距离接入，也不走赤脊山湖边陆路的特殊处理。
                trip = self._corpse_trip = WalkingTrip(session, (), goal, camp_road=grid_road, catalog_goal=goal)
                self._grid_corpse_trip = trip
            else:
                road = () if legs else camp_access_road(goal, origin=position)
                trip = self._corpse_trip = WalkingTrip(session, legs, goal, connections=connections,
                                                      blocked_legs=blocked, camp_road=road, faction=faction)
                self._grid_corpse_trip = None
            if legs:
                self.logger.append('尸体位于其他地图，已规划陆路跑尸。')
        destination, status = trip.observe(position, now_ms=self.monotonic_ms())
        if status:
            self.logger.append(status)
        if trip is self._learned_corpse_trip and trip.travel_exhausted:
            self._discard_recorded_corpse_trip()
            return None
        return destination

    def check_update(self, checked=False, *, manual=True):
        if self._closed or getattr(self,'_handoff',None) or getattr(self,'_outer_installing',False):return
        timer=getattr(self,'_client_update_timer',None)
        if timer is not None and timer.isActive():return
        if not manual and not getattr(self,'_automatic_client_enabled',False):return
        self._client_update_manual=manual
        self._client_auto_chain=False
        self._client_update_staged=None
        if getattr(self,'_outer_update_target',None):
            from wowbuddy.update.github_outer import check_latest
        else:
            from wowbuddy.update.github_client import check_latest
        self._start_client_update_task(check_latest,'正在检查GitHub客户端版本…','check')

    def _configure_automatic_client_update(self, enabled, suppress):
        self._automatic_client_enabled=enabled
        self.ui.auto_update_check.setEnabled(enabled)
        self.update_timer.stop()
        if enabled and not suppress:
            delay=self.settings.snapshot().automatic_update_delay_ms(self.clock_ms())
            if delay is not None:self.update_timer.start(delay)

    def download_update(self, checked=False):
        if self._closed or getattr(self,'_outer_installing',False):return
        if getattr(self,'_client_update_staged',None):
            self._begin_update_handoff()
            return
        if not getattr(self,'_client_update_info',{}).get('has_update'):return
        if self.session.is_active():self.toggle_monitor()
        outer=getattr(self,'_outer_update_target',None)
        if outer:
            from wowbuddy.update.github_outer import download_checked
        else:
            from wowbuddy.update.github_client import download_checked
        from queue import SimpleQueue
        progress=SimpleQueue()
        self._client_download_progress=progress
        workspace=(outer.parent if outer else self.launch_options.app_root.parent)/'WowBuddyDev-updates'
        self._start_client_update_task(lambda:download_checked(self._client_update_info,workspace,progress=lambda received,total:progress.put((received,total))),
                                       '正在下载并校验客户端更新包…','download')

    def _start_client_update_task(self, operation, status, phase):
        if self._closed:return
        if getattr(self,'_client_update_future',None) is not None and not self._client_update_future.done():return
        from concurrent.futures import ThreadPoolExecutor
        self._client_update_phase=phase
        self._client_update_consumed=False
        self._client_update_executor=ThreadPoolExecutor(max_workers=1)
        self._client_update_future=self._client_update_executor.submit(operation)
        self.ui.update_check_button.setEnabled(False)
        self.ui.update_apply_button.setEnabled(False)
        self.ui.update_status.setText(status)
        self.ui.update_progress.setVisible(phase=='download')
        if phase=='download':self.ui.update_progress.setRange(0,0)
        self._client_update_timer=QTimer(self)
        self._client_update_timer.timeout.connect(self._finish_client_update_task)
        self._client_update_timer.start(100)

    def _finish_client_update_task(self):
        if self._closed or getattr(self,'_client_update_consumed',False):return
        if self._client_update_phase=='download':
            from queue import Empty
            progress=getattr(self,'_client_download_progress',None)
            latest=None
            if progress is not None:
                while True:
                    try:latest=progress.get_nowait()
                    except Empty:break
            if latest is not None:
                received,total=latest
                if total>0 and received<=total:
                    self.ui.update_progress.setRange(0,100)
                    self.ui.update_progress.setValue(received*100//total)
                    status=f'已下载 {received/1048576:.1f} / {total/1048576:.1f} MiB'
                    if received==total:status+='，正在校验…'
                else:
                    self.ui.update_progress.setRange(0,0)
                    status=f'已下载 {received/1048576:.1f} MiB（总大小未知）'
                self.ui.update_status.setText(status)
        if not self._client_update_future.done():return
        self._client_update_consumed=True
        self._client_update_timer.stop()
        self._client_update_executor.shutdown(wait=False)
        self.ui.update_progress.hide()
        try:
            result=self._client_update_future.result()
            if self._client_update_phase=='check':
                self._client_update_info=result
                self.settings.save_last_check_ms(self.clock_ms())
                status=f"当前 {result['current_version']} / GitHub {result['version']}："+('发现新版本' if result['has_update'] else '没有更新')
                self.ui.update_apply_button.setText('下载更新包')
                self.ui.update_apply_button.setVisible(result['has_update'])
                self.ui.update_apply_button.setEnabled(result['has_update'])
                self.ui.update_apply_button.setToolTip('下载校验后自动替换并重启' if getattr(self,'_outer_update_target',None)
                                                      else '下载并校验完整客户端，完成后可安装并重启')
                self._client_auto_chain=(result['has_update'] and not self._client_update_manual
                                         and self.ui.auto_update_check.isChecked() and self.launch_options.frozen)
                if self._client_auto_chain:QTimer.singleShot(0,self.download_update)
            elif self._client_update_phase=='handoff':
                from wowbuddy.update.dev_update_notice import remember_handoff
                remember_handoff(self.launch_options.data_dir,self.launch_options.app_root,result)
                self._handoff=result
                import time
                self._handoff_deadline=time.monotonic()+30
                self._handoff_timer=QTimer(self)
                self._handoff_timer.timeout.connect(self._poll_update_handoff)
                self._handoff_timer.start(100)
                status='等待更新交接进程就绪…'
            else:
                self._client_update_staged=result
                status='更新包已校验并暂存：'+result['staged']
                if self.launch_options.frozen:
                    self.ui.update_apply_button.setText('安装并重启')
                    self.ui.update_apply_button.setToolTip('替换自有外层并重新启动，保留稳定设置目录' if getattr(self,'_outer_update_target',None)
                                                          else '退出当前助手后替换整个客户端目录，并保留本地设置')
                    self.ui.update_apply_button.setEnabled(True)
                    if getattr(self,'_outer_update_target',None) or getattr(self,'_client_auto_chain',False):
                        QTimer.singleShot(0,self._begin_update_handoff)
                else:status+='；源码模式请使用打包后的客户端安装更新'
        except Exception as error:
            status='客户端更新失败：'+str(error)
            self._client_auto_chain=False
            if self._client_update_phase=='check':
                self._client_update_info={}
                self.ui.update_apply_button.hide()
            elif self._client_update_phase=='download':
                self.ui.update_apply_button.setText('重试下载')
                self.ui.update_apply_button.setEnabled(bool(getattr(self,'_client_update_info',{}).get('has_update')))
            elif self._client_update_phase=='handoff':
                self.ui.update_apply_button.setText('重试安装')
                self.ui.update_apply_button.setEnabled(bool(getattr(self,'_client_update_staged',None)))
        self.ui.update_status.setText(status)
        self.logger.append(status)
        self.ui.update_check_button.setEnabled(not bool(getattr(self,'_handoff',None)))

    def _begin_update_handoff(self):
        if self._closed or not self.launch_options.frozen or getattr(self,'_outer_installing',False):return
        if self.session.is_active():self.toggle_monitor()
        self.watch_timer.stop()
        if getattr(self,'_outer_update_target',None):
            self._install_outer_update()
            return
        from wowbuddy.update.dev_update_handoff import prepare_handoff
        self._start_client_update_task(lambda:prepare_handoff(self._client_update_staged['staged'],self.launch_options.app_root,sys.argv[1:]),
                                       '正在准备退出后的更新交接…','handoff')

    def _install_outer_update(self):
        from wowbuddy.update.dev_outer_update import install_outer
        self._outer_installing=True
        self._client_auto_chain=False
        self.ui.update_check_button.setEnabled(False)
        self.ui.update_apply_button.setEnabled(False)
        restarting=False
        try:
            staged=getattr(self,'_client_update_staged',None) or {}
            if staged.get('kind')!='outer':raise ValueError('当前外层不能安装目录版更新包')
            result=install_outer(staged['staged'],Path(sys.executable),self._outer_update_target,
                arguments=sys.argv[1:],quit_callback=self._quit_development_app,
                on_status=self.ui.update_status.setText,on_log=self.logger.append)
            self._outer_update_result=result
            self.ui.update_status.setText(result.text)
            restarting=result.restart_started
            if result.phase in ('restart_started','restart_failed','replacement_complete'):
                self._client_update_staged=None
                self.ui.update_apply_button.hide()
            else:
                self.ui.update_apply_button.setText('重试安装')
                self.ui.update_apply_button.setEnabled(True)
        except Exception as error:
            text='外层更新失败：'+str(error)
            self.ui.update_status.setText(text);self.logger.append(text)
            self.ui.update_apply_button.setText('重试安装')
            self.ui.update_apply_button.setEnabled(True)
        finally:
            self._outer_installing=restarting
            self.ui.update_check_button.setEnabled(not restarting)

    def _poll_update_handoff(self):
        import time
        import subprocess
        job=Path(self._handoff['job'])
        if self._handoff.get('cancel_failed') and self._handoff['process'].poll() is None:
            return
        if job.with_suffix('.ready.json').is_file() and self._handoff['process'].poll() is None:
            self._handoff_timer.stop()
            self._quit_development_app()
            return
        if self._handoff['process'].poll() is not None or time.monotonic()>self._handoff_deadline:
            self._handoff_timer.stop()
            from wowbuddy.update.dev_update_handoff import cancel_handoff
            cancel_error=''
            try:
                cancel_handoff(self._handoff,'界面等待交接失败')
            except (OSError,subprocess.TimeoutExpired) as error:
                cancel_error=' 无法保存取消记录：'+str(error)
                if self._handoff['process'].poll() is None:
                    self._handoff['cancel_failed']=True
                    detail='更新交接取消失败，仍在等待交接进程退出；当前助手保持运行。'+cancel_error
                    self.ui.update_status.setText(detail)
                    self.logger.append(detail)
                    self._handoff_timer.start(1000)
                    return
            detail='交接进程未就绪，当前助手保持运行；未替换程序。'
            detail+=cancel_error
            result=job.with_suffix('.result.json')
            if result.is_file():
                try:
                    report=json.loads(result.read_text('utf8'))
                    if not isinstance(report,dict):raise ValueError('交接结果不是对象')
                    error=report.get('error','')
                    if not isinstance(error,str):raise ValueError('交接错误详情不是文本')
                    detail+=' '+error
                except (OSError,ValueError,TypeError) as error:
                    detail+=' 无法读取交接错误详情：'+str(error)
            self.ui.update_status.setText(detail)
            self.logger.append(detail)
            self._handoff=None
            self.ui.update_check_button.setEnabled(True)
            self.ui.update_apply_button.setText('重试安装')
            self.ui.update_apply_button.setEnabled(bool(getattr(self,'_client_update_staged',None)))

    def shutdown(self):
        self._stop_loot_approach()
        if getattr(self,'_native_dump_session',None) is not None:
            self._native_dump_session.close()
        notice_timer=getattr(self,'_update_notice_timer',None)
        if notice_timer is not None:notice_timer.stop()
        addon_timer=getattr(self,'_addon_refresh_timer',None)
        if addon_timer is not None:addon_timer.stop()
        for name in ('_addon_refresh_executor','_download_executor','_leveling_executor'):
            executor=getattr(self,name,None)
            if executor is not None:executor.shutdown(wait=False,cancel_futures=True)
        download_timer=getattr(self,'_download_timer',None)
        if download_timer is not None:download_timer.stop()
        handoff_timer=getattr(self,'_handoff_timer',None)
        if handoff_timer is not None:handoff_timer.stop()
        timer=getattr(self,'_client_update_timer',None)
        if timer is not None:timer.stop()
        executor=getattr(self,'_client_update_executor',None)
        if executor is not None:executor.shutdown(wait=False,cancel_futures=True)
        self._stop_mcp_status()
        super().shutdown()

    def _restore_update_notice(self):
        from wowbuddy.update.dev_update_notice import poll_notice
        notice=poll_notice(self.launch_options.data_dir,self.launch_options.app_root)
        timer=getattr(self,'_update_notice_timer',None)
        if notice is None:
            if timer is not None:timer.stop()
            return
        self.ui.update_status.setText(notice['text'])
        if notice['complete']:
            self.logger.append(notice['text'])
            if timer is not None:timer.stop()
        elif timer is None:
            self._update_notice_attempts=0
            self._update_notice_timer=QTimer(self)
            self._update_notice_timer.timeout.connect(self._restore_update_notice)
            self._update_notice_timer.start(200)
        else:
            self._update_notice_attempts+=1
            if self._update_notice_attempts>=150:
                timer.stop()
                status='上次更新结果尚未返回，记录保留供下次启动检查。'
                self.ui.update_status.setText(status)
                self.logger.append(status)

    def refresh_hub(self):
        try:
            loaded = read_local_library(Path(self.launch_options.data_dir)/'hub/rotations.json', self.hub.hub)
        except (OSError, ValueError) as error:
            self.logger.append('本地方案重载失败，保留当前方案：' + str(error))
            return False
        status = f'本地方案已重载：{len(loaded.profiles)} 套'
        self.hub.hub = self._hub_changed(loaded, status)
        self.hub.status = status
        self.logger.append(status)
        return True

    def _periodic_library_refresh(self):
        self._refresh_online_library()
        self._refresh_addon_release()

    def _configure_addon_refresh(self,enabled):
        self._addon_online=enabled
        if enabled:
            self.addon_startup_timer.timeout.connect(self._refresh_addon_release)
            self.addon_startup_timer.start()
            self.hub_timer.start()

    def _addon_download_busy(self):
        for name in ('_download_timer','_addon_refresh_timer'):
            timer=getattr(self,name,None)
            if timer is not None and timer.isActive():return True
        return False

    def _refresh_addon_release(self):
        if self._closed or not getattr(self,'_addon_online',False):return
        if self._addon_download_busy():return
        from concurrent.futures import ThreadPoolExecutor
        from wowbuddy.update.dev_addon_update import refresh_package
        self._addon_refresh_consumed=False
        self._addon_refresh_executor=ThreadPoolExecutor(max_workers=1)
        self._addon_refresh_future=self._addon_refresh_executor.submit(refresh_package,self.launch_options.data_dir)
        for button in (self.ui.addon_detect_button,self.ui.addon_install_button,self.ui.addon_browse_button,self.ui.addon_clean_button):button.setEnabled(False)
        self._addon_refresh_timer=QTimer(self)
        self._addon_refresh_timer.timeout.connect(self._finish_addon_refresh)
        self._addon_refresh_timer.start(100)

    def _addon_game_snapshot(self):
        from wowbuddy.addons.dev_game_paths import discover_clients,common_roots
        from wowbuddy.addons.addon_games import selected_executable
        from wowbuddy.update.addon_update import AddonGame
        from wowbuddy.update.dev_addon_update import installed_name
        running=selected_executable(self._addon_windows)
        paths=discover_clients(self.settings,running_executable=running,search_roots=common_roots(),environment=os.environ)
        running_dir=str(Path(running).absolute().parent).casefold() if running else ''
        return tuple(AddonGame(path.name,str(path/'Interface/AddOns'),
                     self.session.is_active() or str(path).casefold()==running_dir,
                     installed_name(path/'Interface/AddOns')) for path in paths)

    def _finish_addon_refresh(self):
        if self._closed or getattr(self,'_addon_refresh_consumed',False):return
        if not self._addon_refresh_future.done():return
        self._addon_refresh_consumed=True
        self._addon_refresh_timer.stop()
        self._addon_refresh_executor.shutdown(wait=False)
        try:
            from wowbuddy.update.dev_addon_update import apply_release,installed_name
            from wowbuddy.update.addon_update import SettingsPendingAddons
            release=self._addon_refresh_future.result()
            state=apply_release(release,SettingsPendingAddons(self.settings),games=self._addon_game_snapshot,
                                installed_name=installed_name,on_log=self._record_addon_install)
            status=f"GitHub插件检查完成；待补装 {len(state.pending)} 个客户端。"
        except Exception as error:status='GitHub插件自动更新失败：'+str(error)
        self.ui.addon_status.setText(status)
        self.logger.append(status)
        for button in (self.ui.addon_detect_button,self.ui.addon_install_button,self.ui.addon_browse_button,self.ui.addon_clean_button):button.setEnabled(True)

    def _refresh_online_library(self):
        if self.hub_client is not None:
            from wowbuddy.dev_hub_online import HUB_URL
            self.hub_client.refresh(HUB_URL)

    def _render_hub_status(self):
        super()._render_hub_status()
        # 此入口无网络客户端，不能显示旧版的联网检查状态。
        label = self.ui.hub_status
        label.setText(label.text().replace('正在联网检查更新…', '离线开发版')
                      .replace('联网检查中', '离线开发版'))
        profile = self.controller.selection.active_profile
        missing = profile_action_gaps(profile, self.pipeline.engine.document, self.assets.readable_rules)
        label.setToolTip('')
        if missing:
            detail = '方案含未注册动作，这些规则不会执行：' + '、'.join(missing)
            label.setText(label.text() + '　⚠ 部分动作未注册')
            label.setToolTip(detail)
            label.setStyleSheet('color:#ffb02e;')
            key = (profile.key, missing)
            if self._last_profile_gap != key:
                self.logger.append(detail)
            self._last_profile_gap = key
        else:
            self._last_profile_gap = None

    def _install_addon_actions(self, windows, environment, files, dialogs):
        # 仅安装本工程固定包；不连接旧随机目录安装器或清理入口。
        self.addon_files = None
        self.addons = None
        self.ui.addon_path.setText(self.settings.snapshot().addon_last_dir)
        self.ui.addon_path.setReadOnly(True)
        self.ui.addon_status.setText('选择客户端后安装WowBuddyDev；请先退出游戏，测试前禁用旧插件。')
        self._addon_windows = windows
        self.ui.addon_clean_button.setText('自动检测')
        self.ui.addon_clean_button.setEnabled(True)
        self.ui.addon_clean_button.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.ui.addon_clean_button.setToolTip('检测游戏客户端；右键选择最近目录')
        self.ui.addon_clean_button.clicked.connect(self._detect_development_client)
        self.ui.addon_clean_button.customContextMenuRequested.connect(self._recent_development_clients)
        self.ui.addon_detect_button.setText('安装 GitHub 发布版')
        self.ui.addon_detect_button.setToolTip('从自有GitHub仓库下载最新发布版插件并安装到所选客户端；\n'
                                               '发布版比客户端里已装的版本旧时，会先询问是否覆盖。')
        self.ui.addon_detect_button.clicked.connect(self._download_github_addon)
        self.ui.addon_browse_button.setEnabled(True)
        self.ui.addon_browse_button.clicked.connect(self._browse_development_client)
        from wowbuddy.dev_version import VERSION
        self.ui.addon_install_button.setText(f'安装本地构建（v{VERSION}）')
        self.ui.addon_install_button.setToolTip('安装本机打包的插件：' + str(self.launch_options.package_dir/'WowBuddyDev-dev.zip'))
        self.ui.addon_install_button.clicked.connect(self._install_development_addon)
        self._addon_cleanup_button=QPushButton('清理旧插件')
        self._addon_cleanup_button.setObjectName('Dim')
        self._addon_cleanup_button.setMinimumHeight(30)
        self._addon_cleanup_button.setToolTip('清理所选客户端内含原插件特征文件的目录，保留当前独立插件')
        self.ui.addon_install_button.parentWidget().layout().addWidget(self._addon_cleanup_button)
        self._addon_cleanup_button.clicked.connect(self._cleanup_development_addons)

    def _cleanup_development_addons(self):
        if self.session.is_active():
            self.ui.addon_status.setText('请先停止监控并退出游戏，再清理旧插件。')
            return
        for name in ('_download_timer','_addon_refresh_timer'):
            timer=getattr(self,name,None)
            if timer is not None and timer.isActive():
                self.ui.addon_status.setText('插件更新进行中，请完成后再清理。')
                return
        try:
            from wowbuddy.addons.dev_addon_cleanup import cleanup_old_addons
            from wowbuddy.addons.addon_games import selected_executable
            from wowbuddy.addons.dev_addon_install import client_directory
            selected=client_directory(self.ui.addon_path.text())
            running=selected_executable(self._addon_windows)
            if running and str(Path(running).absolute().parent).casefold()==str(selected).casefold():
                raise ValueError('所选游戏正在运行，请退出游戏后再清理')
            result=cleanup_old_addons(selected)
            status=f'清理完成：删除 {result.deleted} 个旧插件目录。\n{result.notes}'
        except (OSError,ValueError) as error:status='插件清理失败：'+str(error)
        self.ui.addon_status.setText(status)
        self.logger.append(status)

    def _select_development_client(self, selected):
        from wowbuddy.addons.dev_game_paths import normalize_client
        try:
            directory=str(normalize_client(selected))
            self.settings.save_addon_dir(directory)
            self.ui.addon_path.setText(directory)
            self.ui.addon_status.setText('已选择客户端：'+directory)
        except (ValueError,OSError) as error:
            self.ui.addon_status.setText(str(error))

    def _detect_development_client(self):
        if 'WOWBUDDY_NO_GAME_SCAN' in os.environ:
            self.ui.addon_status.setText('当前环境已禁用游戏目录扫描。')
            return
        from wowbuddy.addons.dev_game_paths import discover_clients, common_roots
        from wowbuddy.addons.addon_games import selected_executable
        try:
            paths=discover_clients(self.settings,running_executable=selected_executable(self._addon_windows),
                                   search_roots=common_roots(),environment=os.environ)
            if paths:self._select_development_client(paths[0])
            else:self.ui.addon_status.setText('未检测到游戏客户端，请手动选择目录。')
        except (OSError,ValueError) as error:
            self.ui.addon_status.setText('检测失败：'+str(error))

    def _recent_development_clients(self, position):
        menu=QMenu(self)
        for path in self.settings.snapshot().addon_history:
            action=menu.addAction(path)
            action.triggered.connect(lambda checked=False,p=path:self._select_development_client(p))
        if menu.actions():menu.addSeparator()
        menu.addAction('清空最近目录').triggered.connect(self.settings.clear_addon_history)
        menu.exec(self.ui.addon_clean_button.mapToGlobal(position))

    def _download_github_addon(self):
        if self._closed or self._addon_download_busy():return
        if self.session.is_active() or not self.ui.addon_path.text():
            self.ui.addon_status.setText('请先停止监控、退出游戏并选择客户端目录。')
            return
        from concurrent.futures import ThreadPoolExecutor
        from wowbuddy.update.github_addon import download_latest
        self._download_consumed=False
        self._download_client = self.ui.addon_path.text()
        self._download_executor = ThreadPoolExecutor(max_workers=1)
        self._download_future = self._download_executor.submit(download_latest, self.launch_options.data_dir)
        for button in (self.ui.addon_detect_button,self.ui.addon_install_button,self.ui.addon_browse_button,self.ui.addon_clean_button):
            button.setEnabled(False)
        self.ui.addon_status.setText('正在从GitHub下载并校验插件…')
        self._download_timer = QTimer(self)
        self._download_timer.timeout.connect(self._finish_github_download)
        self._download_timer.start(150)

    def _finish_github_download(self):
        if self._closed or getattr(self,'_download_consumed',False):return
        if not self._download_future.done():
            return
        self._download_consumed=True
        self._download_timer.stop()
        self._download_executor.shutdown(wait=False)
        try:
            from PySide6.QtWidgets import QMessageBox
            from wowbuddy.addons import dev_addon_install
            release = self._download_future.result()
            if self.session.is_active():
                raise ValueError('下载期间监控已启动；请停止监控后重新安装')
            version = (dev_addon_install.package_version(release['package'])
                       or str(release.get('tag', '')).removeprefix('v'))
            try:
                client = dev_addon_install.client_directory(self._download_client)
                current = dev_addon_install.installed_version(client/'Interface'/'AddOns')
            except (OSError, ValueError):
                current = ''  # 客户端目录无效时由安装函数给出原有的错误提示
            confirmed = True
            if version and current and dev_addon_install.is_newer(current, version):
                answer = QMessageBox.question(
                    self, '安装较旧的插件？',
                    f'客户端 {self._download_client} 已装 v{current}，GitHub 发布版为 v{version}（更旧）。\n'
                    '覆盖后会失去已装版本中的改动，仍要安装吗？')
                confirmed = answer == QMessageBox.StandardButton.Yes
            if not confirmed:
                status = f'已取消：客户端已装 v{current}，未用较旧的 GitHub 发布版 v{version} 覆盖。'
            else:
                result = dev_addon_install.install_package(release['package'], self._download_client)
                status = (f"已安装 GitHub 发布版 v{result.get('version') or version or '未知版本'}"
                          f"（{release.get('tag', '')}）到客户端 {self._download_client}：{result['target']}；"
                          "请重新加载游戏插件列表。")
                status += f"\n清理旧目录：{result['cleanup_deleted']} 个；{result['cleanup_notes']}"
        except Exception as error:
            status = 'GitHub插件更新失败：' + str(error)
        self.ui.addon_status.setText(status)
        self._record_addon_install(status)
        for button in (self.ui.addon_detect_button,self.ui.addon_install_button,self.ui.addon_browse_button,self.ui.addon_clean_button):
            button.setEnabled(True)

    def _browse_development_client(self):
        selected = QFileDialog.getExistingDirectory(self, '选择包含Wow.exe的客户端目录', self.ui.addon_path.text())
        if not selected:
            return
        self._select_development_client(selected)

    def _record_addon_install(self, text):
        """插件安装相关结果写入运行日志，并追加到 数据目录/addon-install.log（不论是否在监控，导出诊断会收录）。"""
        from datetime import datetime
        self.logger.append(text)
        try:
            with open(Path(self.launch_options.data_dir)/'addon-install.log', 'a', encoding='utf-8') as stream:
                stream.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {text}\n")
        except OSError:
            pass

    def _install_development_addon(self):
        from wowbuddy.addons.dev_addon_install import install_package
        from zipfile import BadZipFile
        if self.session.is_active():
            self.ui.addon_status.setText('请先停止监控并退出游戏，再安装插件。')
            return
        if not self.ui.addon_path.text():
            self.ui.addon_status.setText('请先浏览选择客户端目录。')
            return
        try:
            result = install_package(self.launch_options.package_dir/'WowBuddyDev-dev.zip', self.ui.addon_path.text())
            version = result.get('version') or '未知版本'
            status = (f"已安装本地构建 v{version}（{result['files']} 个文件）到客户端 {self.ui.addon_path.text()}："
                      f"{result['target']}")
            if result['backup']:
                status += f"；旧开发版备份：{result['backup']}"
            status += f"\n清理旧目录：{result['cleanup_deleted']} 个；{result['cleanup_notes']}"
            self.ui.addon_status.setText(status)
            self._record_addon_install(status)
        except (OSError, ValueError, KeyError, BadZipFile) as error:
            self.ui.addon_status.setText('安装失败：' + str(error))
            self._record_addon_install('本地构建安装失败：' + str(error))
