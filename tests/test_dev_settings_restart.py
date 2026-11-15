"""使用同一临时INI重新构造主窗，验证临时控件和方案阈值保存边界。"""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from pathlib import Path
import json
import subprocess
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import ANY, patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'desktop'),str(ROOT/'tests/core')]
from PySide6.QtWidgets import QApplication
from wowbuddy.desktop import NoSystemBackend
from wowbuddy.dev_version import VERSION
from wowbuddy.win32.game_windows import WindowInfo
from wowbuddy.app.qt_app import AssistantWindow
from wowbuddy.engine.runtime import PollResult
from test_old_protocol import render_old
import run_dev


class RestartSettingsTests(unittest.TestCase):
    def window(self,directory,exercise,*,addon_online=False,**options):
        app=QApplication.instance() or QApplication([])
        def loop():
            window=next(w for w in app.topLevelWidgets()
                        if w.windowTitle()==f'WowBuddyDev v{VERSION} — 独立开发版' and not getattr(w,'_closed',True))
            exercise(window)
            return 0
        with patch('wowbuddy.win32.game_windows.CtypesWindowBackend',return_value=NoSystemBackend()),patch('wowbuddy.win32.capture.make_win32_capture',return_value=NoSystemBackend()),patch('wowbuddy.win32.windows_keys.CtypesWin32Backend',return_value=NoSystemBackend()),patch('PySide6.QtWidgets.QSystemTrayIcon.isSystemTrayAvailable',return_value=False),patch.object(QApplication,'exec',side_effect=loop):
            self.assertEqual(run_dev.launch(directory,hub_online=False,client_online=False,
                                            addon_online=addon_online,**options),0)

    def test_unattended_controls_the_running_monitor_and_survives_restart(self):
        def first(window):
            self.assertFalse(window.grind_check.isChecked())
            self.assertFalse(window.pipeline.unattended_grinding)
            self.assertTrue(window.pipeline.probe_attack_range)
            self.assertTrue(window.grind_check.isVisible())
            window.session.start(123)
            result = PollResult('capture_failed')
            with (patch.object(AssistantWindow, 'poll_once', return_value=result),
                  patch.object(window, '_poll_revival') as revive,
                  patch.object(window, '_poll_leveling') as leveling,
                  patch.object(window, '_poll_navigation') as navigation):
                window.poll_once()
                revive.assert_not_called()
                leveling.assert_not_called()
                navigation.assert_called_once()
                self.assertFalse(navigation.call_args.kwargs['navigate'])
                navigation.reset_mock()
                window.grind_check.click()
                self.assertTrue(window.pipeline.unattended_grinding)
                self.assertTrue(window.pipeline.probe_attack_range)
                self.assertIs(window.poll_once(), result)
                session = revive.call_args.args[0]
                self.assertEqual(session[0], 123)
                leveling.assert_called_once_with(session, None, True, navigation=ANY)
                self.assertIsNone(leveling.call_args.kwargs['navigation']())
                navigation.assert_called_once_with(result, session, None, None, None, None, navigate=True)
                window.grind_check.click()
                self.assertFalse(window.pipeline.unattended_grinding)
                self.assertTrue(window.pipeline.probe_attack_range)
                window.poll_once()
                revive.assert_called_once()
                leveling.assert_called_once()
                self.assertEqual(navigation.call_count, 2)
                self.assertFalse(navigation.call_args.kwargs['navigate'])
                window.grind_check.click()
                window.poll_once()
                self.assertNotEqual(revive.call_args.args[0], session)

        def restored(window):
            self.assertTrue(window.grind_check.isChecked())
            self.assertTrue(window.pipeline.unattended_grinding)
            self.assertTrue(window.pipeline.probe_attack_range)
            window.grind_check.click()

        with TemporaryDirectory() as directory:
            self.window(directory, first)
            self.window(directory, restored)
            self.window(directory, lambda window: self.assertFalse(window.grind_check.isChecked()))

    def test_regular_monitor_approaches_without_a_camp_and_releases_before_casting(self):
        from dataclasses import replace
        from unittest.mock import Mock
        from wowbuddy.engine.character_state import NavigationState, TargetBearing
        from wowbuddy.core.old_protocol import OldFrame
        from wowbuddy.engine.pipeline import Decision
        from wowbuddy.engine.scheduler import TickResult

        def exercise(window):
            session = (123, 456, 0)
            position = NavigationState('alive', 1, 1436, 46.1, 38.2, 0, 1000, 800, (87, 65, 68),
                                       continuous=True)
            bearing = TargetBearing(1, 0.5, 42.5, continuous=True)
            frame = OldFrame('ok', values={'target_valid': 'ON', 'player_in_combat': 'OFF'})
            result = SimpleNamespace(tick=TickResult('no_candidates', Decision(
                frame, frame.values, (), attack_blocked_by_range=True)))
            movement = Mock(holding_forward=False)
            movement.keep_forward.return_value = False
            movement.release_forward.return_value = True
            with (patch('wowbuddy.engine.character_state.decode_navigation_state',
                        side_effect=(position, None, replace(position, sequence=2))) as decode,
                  patch('wowbuddy.engine.character_state.decode_target_bearing', return_value=bearing),
                  patch('wowbuddy.win32.windows_keys.is_foreground', return_value=True),
                  patch('wowbuddy.automation.navigation.ForegroundMovement', return_value=movement)):
                window._poll_navigation(result, session, object(), frame, None, None, navigate=False)
                movement.hold_forward.assert_not_called()
                combat_frame = replace(frame, values={**frame.values, 'player_in_combat': 'ON'})
                combat_image = object()
                window._poll_navigation(result, session, combat_image, combat_frame, None, None, navigate=False)
                decode.assert_called_with(combat_image, combat_frame, for_target=True)
                movement.hold_forward.assert_called_once_with(123, position.keys)
            movement.holding_forward = True
            self.assertFalse(window.scheduler.before_dispatch({'player_moving': 'ON'}))
            movement.release_forward.assert_called()
            movement.holding_forward = False
            self.assertFalse(window.scheduler.before_dispatch({'player_moving': 'ON'}))
            self.assertTrue(window.scheduler.before_dispatch({'player_moving': 'OFF'}))

        with TemporaryDirectory() as directory:
            self.window(directory, exercise)

    def test_dispatch_waits_for_fresh_stop_after_forward_pulse_or_watchdog_release(self):
        from unittest.mock import Mock
        from wowbuddy.automation.navigation import ForegroundMovement, MapNavigator

        def exercise(window):
            hwnd, keys = 123, (87, 65, 68)
            keyboard, processes = Mock(), Mock()
            keyboard.GetAncestor.side_effect = lambda window, _: window
            keyboard.GetForegroundWindow.return_value = hwnd
            keyboard.GetAsyncKeyState.return_value = 0
            keyboard.MapVirtualKeyW.return_value = 0x11
            keyboard.SendInput.return_value = 1
            processes.process_path.return_value = r'D:\game\Wow.exe'
            movement = ForegroundMovement(keyboard, processes, on_forward=window._wait_for_navigation_stop)
            window._map_navigator = MapNavigator(movement)
            before_dispatch = window.scheduler.before_dispatch

            def sample(sequence):
                capture = SimpleNamespace(image=object(), backend='printwindow')
                with patch('wowbuddy.engine.character_state.decode_death_state',
                           return_value=SimpleNamespace(sequence=sequence)):
                    window._character_freshness.hold_reason(hwnd, capture, object(), sequence * 250)

            sample(1)
            self.assertTrue(before_dispatch({'player_moving': 'ON'}))
            sample(2)
            with (patch('wowbuddy.automation.navigation.Timer') as timer,
                  patch('wowbuddy.automation.navigation.monotonic', return_value=0.0) as clock):
                self.assertTrue(movement.hold_forward(hwnd, keys))
                clock.return_value = 1.0
                timer.call_args.args[1]()
                self.assertFalse(movement.holding_forward)
                self.assertFalse(before_dispatch({'player_moving': 'OFF'}))
                sample(3)
                self.assertFalse(before_dispatch({'player_moving': 'ON'}))
                self.assertFalse(before_dispatch({'player_moving': 'UNKNOWN'}))
                sample(4)
                self.assertTrue(before_dispatch({'player_moving': 'OFF'}))

                keyboard.SendInput.side_effect = (1, 0, 0, 0, 0, 1)
                self.assertFalse(movement.pulse(hwnd, keys[0], 120, keys))
                self.assertTrue(movement.holding_forward)
                sample(5)
                self.assertFalse(before_dispatch({'player_moving': 'OFF'}))
                timer.call_args.args[1]()
                self.assertFalse(movement.holding_forward)
                self.assertFalse(before_dispatch({'player_moving': 'OFF'}))
                sample(6)
                self.assertFalse(before_dispatch({}))
                self.assertTrue(before_dispatch({'player_moving': 'OFF'}))

                keyboard.SendInput.side_effect = None
                self.assertTrue(movement.pulse(hwnd, keys[0], 120, keys))
                self.assertFalse(movement.holding_forward)
                self.assertFalse(before_dispatch({'player_moving': 'OFF'}))
                sample(7)
                self.assertTrue(before_dispatch({'player_moving': 'OFF'}))

        with TemporaryDirectory() as directory:
            self.window(directory, exercise)

    def test_pending_dispatch_stop_keeps_travel_paused_until_fresh_standstill(self):
        from dataclasses import replace
        from unittest.mock import Mock
        from wowbuddy.engine.character_state import CharacterFrameFreshness, CharacterState, NavigationState
        from wowbuddy.automation.navigation import MapDestination
        from wowbuddy.core.old_protocol import OldFrame
        from wowbuddy.engine.pipeline import Decision
        from wowbuddy.engine.scheduler import TickResult
        from wowbuddy.automation.walking_route import WalkingTrip, plan_walking_route

        def exercise(window):
            session = (123, 456, 0)
            position = NavigationState('alive', 1, 1436, 62.38, 17.83, 0, 3500, 2333, (87, 65, 68))
            character = CharacterState('alive', True, True, 'alliance', 18, 1436, '西部荒野', position.x, position.y)
            goal = MapDestination(1429, 40, 66, 'alive', '练级区')
            legs = plan_walking_route(1436, goal.map_id, 18, 'alive')
            trip = WalkingTrip(session, legs, goal, level=18)
            window._leveling_trip = ('alliance', 18, trip)
            navigator = window._map_navigator = Mock(blocked=False)
            navigator.observe.return_value = None
            navigator.movement.holding_forward = True

            def release_forward():
                navigator.movement.holding_forward = False
                return True

            navigator.movement.release_forward.side_effect = release_forward

            def sample(sequence):
                capture = SimpleNamespace(image=object(), backend='printwindow')
                with patch('wowbuddy.engine.character_state.decode_death_state', return_value=SimpleNamespace(sequence=sequence)):
                    window._character_freshness.hold_reason(session, capture, object(), sequence * 250)

            def poll(status, moving, sequence):
                frame = OldFrame('ok', values={'player_valid': 'ON', 'player_in_combat': 'OFF',
                                                'player_moving': moving, 'target_valid': 'OFF'})
                result = SimpleNamespace(tick=TickResult(status, Decision(frame, frame.values, (), recovery_ready=True)))
                sample_position = replace(position, sequence=sequence, moving=moving == 'ON')
                with patch('wowbuddy.engine.character_state.decode_navigation_state', return_value=sample_position):
                    window._poll_navigation(result, session, object(), frame, character, None, navigate=True)

            sample(1)
            self.assertFalse(window.scheduler.before_dispatch({'player_moving': 'ON'}))
            poll('movement_stopping', 'ON', 1)
            poll('no_candidates', 'OFF', 1)
            navigator.observe.assert_not_called()
            window._character_freshness = CharacterFrameFreshness()
            poll('no_candidates', 'OFF', 2)
            navigator.observe.assert_not_called()
            sample(3)
            poll('no_candidates', 'ON', 3)
            navigator.observe.assert_not_called()
            sample(4)
            poll('no_candidates', 'OFF', 4)
            navigator.observe.assert_called_once()
            self.assertIs(navigator.observe.call_args.kwargs['path'], trip)
            self.assertIsNotNone(navigator.observe.call_args.args[3])

        with TemporaryDirectory() as directory:
            self.window(directory, exercise, auto_grind=True)

    def test_loot_hold_preserves_owned_movement_until_readings_stop_or_interaction_is_ready(self):
        from dataclasses import replace
        from unittest.mock import Mock
        from wowbuddy.win32.capture import CaptureResult
        from wowbuddy.engine.character_state import LevelProgress, MobState, NavigationState, STALE_FRAME, TargetBearing
        from wowbuddy.automation.navigation import MapNavigator
        from wowbuddy.core.old_protocol import OldFrame

        def exercise(window):
            monitor = 123, 456
            position = NavigationState('alive', 1, 1436, 45, 50, 0, 1000, 800, (87, 65, 68),
                                       continuous=True, target_revision=1)
            combat = MobState(1, 1, 1, '', 0, False)
            distant = replace(combat, state=3, bearing=TargetBearing(1, 0.5, 20, continuous=True))
            capture = CaptureResult('ok', object(), 'printwindow')
            freshness = window._character_freshness = SimpleNamespace(hold_reason=Mock(return_value=None), sample=0)
            movement = Mock(holding_forward=False)
            window._map_navigator = MapNavigator(movement)
            movement.can_input.return_value = True
            movement.keep_forward.side_effect = lambda *_: movement.holding_forward

            def hold(*_):
                if not movement.holding_forward:
                    movement.holding_forward = True
                    window._wait_for_navigation_stop()
                return True

            def release():
                movement.holding_forward = False
                return True

            movement.hold_forward.side_effect = hold
            movement.release_forward.side_effect = release

            def poll(mob, sample, now, *, moving=False, in_combat=False):
                freshness.sample = sample
                fields = {'mob_policy': 'ON', 'player_in_combat': 'ON' if in_combat else 'OFF',
                          'player_moving': 'ON' if moving else 'OFF'}
                frame = OldFrame('ok', values=fields)

                def capture_and_guard():
                    reason = window._hold_character_frame(monitor, capture, frame, now)
                    window.session.state.status = reason or ''
                    return PollResult('frame_held' if reason else 'no_candidates', capture)

                with (patch('wowbuddy.engine.character_state.decode_cast_feedback', return_value=None),
                      patch('wowbuddy.engine.character_state.decode_mob_state', return_value=mob),
                      patch('wowbuddy.engine.character_state.decode_navigation_state',
                            return_value=replace(position, sequence=sample, moving=moving)),
                      patch.object(window.loop, 'poll', side_effect=capture_and_guard)):
                    return window.poll_once()

            with patch('wowbuddy.win32.windows_keys.send_input', return_value=True) as send:
                poll(combat, 0, 1000)
                awaiting = replace(combat, state=7)
                self.assertEqual(poll(awaiting, 1, 1050).status, 'frame_held')
                self.assertIn('击杀回执', window.session.state.status)
                self.assertFalse(movement.holding_forward)
                send.assert_not_called()
                poll(distant, 1, 1100)
                distance = replace(distant, sequence=2)
                self.assertEqual(poll(distance, 2, 1200).status, 'frame_held')
                self.assertTrue(movement.holding_forward)
                poll(distance, 2, 1250, moving=True)
                self.assertTrue(movement.holding_forward)
                movement.hold_forward.assert_called_once()
                send.assert_not_called()

                freshness.hold_reason.return_value = STALE_FRAME
                poll(distance, 2, 2300, moving=True)
                self.assertFalse(movement.holding_forward)
                self.assertIsNone(window._loot_approach_session)

                freshness.hold_reason.return_value = None
                poll(replace(distant, sequence=3), 3, 2400)
                poll(replace(distant, sequence=4), 4, 2500)
                self.assertTrue(movement.holding_forward)
                near = replace(distant, sequence=5, key='F7', bearing=None)
                poll(near, 5, 2600, moving=True)
                self.assertFalse(movement.holding_forward)
                send.assert_not_called()
                poll(replace(near, sequence=6), 6, 2700)
                send.assert_called_once()

                progress.return_value = LevelProgress(19, 565, 21300, 65535)
                poll(replace(combat, sequence=7), 7, 4000, in_combat=True)
                progress.return_value = LevelProgress(19, 616, 21300, 0)
                self.assertNotEqual(poll(None, 8, 4100, in_combat=True).status, 'frame_held')
                self.assertEqual(poll(None, 9, 4400).status, 'frame_held')
                self.assertIn('战斗经验回执', window.session.state.status)
                self.assertEqual(poll(replace(combat, sequence=10, state=0), 10, 4750).status, 'frame_held')
                self.assertNotEqual(poll(None, 11, 4900).status, 'frame_held')
                send.assert_called_once()

        with (TemporaryDirectory() as directory,
              patch('wowbuddy.app.dev_window.decode_character_session', return_value=321),
              patch('wowbuddy.app.dev_window.decode_travel_identity', return_value=None),
              patch('wowbuddy.app.dev_window.decode_level_progress', return_value=None) as progress):
            self.window(directory, exercise, auto_grind=True)

    def test_unattended_releases_movement_until_recovery_is_confirmed_out_of_combat(self):
        from dataclasses import replace
        from unittest.mock import Mock
        from wowbuddy.engine.character_state import CharacterState, NavigationState, TargetBearing
        from wowbuddy.automation.navigation import MapDestination
        from wowbuddy.core.old_protocol import OldFrame
        from wowbuddy.engine.pipeline import Decision
        from wowbuddy.engine.scheduler import TickResult

        def exercise(window):
            session = (123, 456, 0)
            position = NavigationState('alive', 0, 1436, 45, 50, 0, 1000, 800, (87, 65, 68),
                                       continuous=True, target_revision=1)
            character = CharacterState('alive', True, True, 'alliance', 15, 1436, '西部荒野', 45, 50)
            camp = MapDestination(1436, 45, 30, 'alive', '练级点')
            window._leveling_destination = session, character.route_key, camp
            movement = Mock(holding_forward=False)
            movement.keep_forward.return_value = False
            movement.release_forward.return_value = True

            def poll(sequence, *, ready=False, disabled=False, target='OFF', combat='OFF'):
                fields = {'target_valid': target, 'player_valid': 'ON', 'player_in_combat': combat}
                frame = OldFrame('ok', values=fields)
                tick = TickResult('no_candidates', Decision(frame, fields, (), recovery_ready=ready,
                                  recovery_disabled=disabled, attack_blocked_by_range=target == 'ON'))
                with (patch('wowbuddy.engine.character_state.decode_navigation_state',
                            return_value=replace(position, sequence=sequence)),
                      patch('wowbuddy.engine.character_state.decode_target_bearing',
                            return_value=TargetBearing(1, 0.5, 40, continuous=True)),
                      patch('wowbuddy.win32.windows_keys.is_foreground', return_value=True),
                      patch('wowbuddy.automation.navigation.ForegroundMovement', return_value=movement)):
                    window._poll_navigation(SimpleNamespace(tick=tick), session, object(), frame,
                                            character if combat == 'OFF' else None, None, navigate=True)

            poll(1, ready=True)
            movement.hold_forward.assert_called_once_with(123, position.keys)
            movement.reset_mock()
            poll(2, disabled=True)
            movement.release_forward.assert_called()
            movement.hold_forward.assert_not_called()
            poll(3)
            movement.hold_forward.assert_not_called()
            poll(4, ready=True, disabled=True)
            movement.hold_forward.assert_called_once_with(123, position.keys)

            movement.reset_mock()
            poll(5, ready=True, target='ON')
            poll(6, ready=True, target='ON')
            movement.hold_forward.assert_called_once_with(123, position.keys)
            movement.reset_mock()
            poll(7, disabled=True, target='ON')
            poll(8, target='ON')
            movement.release_forward.assert_called()
            movement.hold_forward.assert_not_called()
            poll(9, target='ON', combat='ON')
            poll(10, target='ON', combat='ON')
            movement.hold_forward.assert_called_once_with(123, position.keys)

        with TemporaryDirectory() as directory:
            self.window(directory, exercise, auto_grind=True)

    def test_cli_enables_unattended_for_one_launch_and_manual_stop_holds(self):
        def launched(window):
            self.assertTrue(window.grind_check.isChecked())
            window.monitor.windows = (WindowInfo(123, 'Test WoW', 'wow.exe'),)
            window.ui.window_combo.addItem('Test WoW', 123)
            window.ui.window_combo.setCurrentIndex(window.ui.window_combo.findData(123))
            backend = SimpleNamespace(window_pid=lambda hwnd: 321, is_window=lambda hwnd: True,
                                      process_path=lambda pid: r'C:\Game\Wow.exe')
            with patch.object(window.monitor.backend, 'backend', backend):
                window.toggle_monitor()
                self.assertTrue(window.session.is_active())
                window.toggle_monitor()
                self.assertFalse(window.session.is_active())
                with patch('wowbuddy.win32.game_windows.find_game_window', return_value=123) as find:
                    window.watch_once()
                    find.assert_not_called()
                    self.assertFalse(window.session.is_active())
                window.toggle_monitor()
                self.assertTrue(window.session.is_active())
                with patch.object(window.monitor, 'tick') as tick:
                    window.watch_once()
                    tick.assert_called_once_with()

        with TemporaryDirectory() as directory:
            self.window(directory, launched, auto_grind=True)
            self.window(directory, lambda window: self.assertFalse(window.grind_check.isChecked()))

    def test_restarted_monitor_replans_felwood_from_the_current_road_while_offline(self):
        from wowbuddy.engine.character_state import CharacterState, NavigationState
        from wowbuddy.automation.leveling_route import LevelingGuideCache, find_grinding_point
        from tests.test_leveling_route import leg, stage

        source = 'https://forever-tavern.com/npcs/classic/7139-irontree-stomper/'
        guide = stage(1, '54–56', leg('费伍德森林', 'felwood', [('铁木森林', '51.7,24.1')]))
        pins = ('<a data-entity-pin data-zone="1448" data-source-id="7139" '
                'data-source-x="51.775" data-source-y="24.167" data-pin-label="Source spawn"></a>')
        character = CharacterState('alive', True, True, 'horde', 54, 1440, '灰谷', 62.0125, 44.15)

        def resume(window):
            session = (123, 456, 0)
            with (patch('wowbuddy.automation.leveling_route.urlopen', side_effect=OSError('offline')),
                  patch.object(window, 'monotonic_ms', side_effect=(1000, 1300, 1600))):
                window._poll_leveling(session, character, True)
                window._poll_leveling(session, character, True)
                window._leveling_planner._pending[1].result(timeout=3)
                window._poll_leveling(session, character, True)
            trip = window._leveling_trip[2]
            self.assertEqual((trip.goal.map_id, trip.goal.x, trip.goal.y), (1448, 51.775, 24.167))
            self.assertEqual([leg.destination for leg in trip.legs], [1448])
            position = NavigationState('alive', 1, 1440, character.x, character.y, 0, 5767, 3844, (87, 65, 68))
            target, _ = trip.observe(position)
            self.assertEqual((target.x, target.y), (60.85, 42.2))
            report = json.loads((Path(directory)/'leveling-auto.json').read_text('utf8'))
            self.assertIn(source, report['cached_sources'])

        with TemporaryDirectory() as directory:
            cache = LevelingGuideCache(directory=Path(directory)/'leveling-guide-cache')
            original = find_grinding_point('horde', 54, '菲拉斯', 44.461, 11.743,
                                           fetch=lambda url: pins if url == source else guide, cache=cache)
            self.assertTrue(original['cross_zone'])
            self.window(directory, resume, auto_grind=True)

    def test_restart_resumes_cross_map_trip_without_reselecting_previous_camp(self):
        from concurrent.futures import Future
        from dataclasses import replace
        from unittest.mock import Mock
        from wowbuddy.engine.character_state import CharacterState, NavigationState
        from wowbuddy.automation.leveling_route import AutomaticLeveling, read_leveling_travel
        from wowbuddy.core.old_protocol import OldFrame
        from wowbuddy.engine.pipeline import Decision
        from wowbuddy.engine.scheduler import TickResult

        origin = CharacterState('alive', True, True, 'alliance', 18, 1436, '西部荒野', 51.66, 77.11)
        crossing = replace(origin, map_id=1429, zone='艾尔文森林', x=24.18, y=78.35)
        arrival = replace(origin, map_id=1433, zone='赤脊山', x=4.1, y=73.0)
        point = {'zone': '赤脊山', 'name': '赤脊山偷猎者营地', 'x': 23.25, 'y': 79.41}
        online = Future()
        online.set_result({'point': point, 'cross_zone': True})

        def start(window):
            session = (123, 456, 0)
            window._character_session = (session[:2], 42)
            if new_game:
                window._character_travel_identity = window._character_session, (15, 16)
            window._leveling_planner = AutomaticLeveling(Mock(return_value=online))
            with (patch.object(window.monitor.backend, 'backend', SimpleNamespace(window_pid=lambda hwnd: 321)),
                  patch.object(window, 'monotonic_ms', side_effect=(1000, 1300, 1600))):
                for _ in range(3):
                    window._poll_leveling(session, origin, True)
            self.assertEqual(json.loads(checkpoint.read_text('utf8'))['walking_maps'], [1436, 1429, 1433])

        def restart(window):
            session = (124 if new_game else 123, 999, 0)
            window._character_session = (session[:2], 43 if new_game else 42)
            if new_game:
                window._character_travel_identity = window._character_session, (15, 16)
            submit = Mock()
            window._leveling_planner = AutomaticLeveling(submit)
            with patch.object(window.monitor.backend, 'backend', SimpleNamespace(window_pid=lambda hwnd: 322 if new_game else 321)):
                window._poll_leveling(session, crossing, True)
            submit.assert_not_called()
            trip = window._leveling_trip[2]
            self.assertEqual([leg.destination for leg in trip.legs], [1433])
            self.assertEqual((trip.goal.x, trip.goal.y), (23.25, 79.41))
            position = NavigationState('alive', 1, 1429, crossing.x, crossing.y, 0, 3470, 2314, (87, 65, 68))
            waypoint, _ = trip.observe(position)
            self.assertEqual((waypoint.x, waypoint.y), (24.11, 78.66))
            waypoint, _ = trip.observe(replace(position, sequence=2, x=waypoint.x, y=waypoint.y))
            self.assertEqual((waypoint.x, waypoint.y), (24.76, 78.62))
            identity = ['character', 15, 16, 'alliance', 18] if new_game else [123, 321, 42, 'alliance', 18]
            self.assertEqual(read_leveling_travel(checkpoint, identity, 1429)['walking_maps'], [1429, 1433])
            for different in ([*identity[:2], 99, *identity[3:]], [*identity[:-1], 19]):
                self.assertIsNone(read_leveling_travel(checkpoint, different, 1429))
            self.assertIsNone(read_leveling_travel(checkpoint, identity, 1436))
            self.assertEqual(read_leveling_travel(checkpoint, identity, 1433)['point'], point)
            saved = checkpoint.read_bytes()
            os.utime(checkpoint, (0, 0))
            self.assertIsNone(read_leveling_travel(checkpoint, identity, 1429))
            checkpoint.write_bytes(saved)

        def restart_in_destination(window):
            session = (125 if new_game else 123, 1000, 0)
            window._character_session = (session[:2], 44 if new_game else 42)
            if new_game:
                window._character_travel_identity = window._character_session, (15, 16)
            submit = Mock()
            window._leveling_planner = AutomaticLeveling(submit)
            with patch.object(window.monitor.backend, 'backend', SimpleNamespace(window_pid=lambda hwnd: 321)):
                window._poll_leveling(session, arrival, True)
            submit.assert_not_called()
            trip = window._leveling_trip[2]
            self.assertFalse(trip.connecting)
            self.assertEqual((trip.goal.x, trip.goal.y), (23.25, 79.41))
            position = NavigationState('alive', 1, 1433, arrival.x, arrival.y, 0, 2170, 1447, (87, 65, 68))
            frame = OldFrame('ok', values={'target_valid': 'OFF', 'player_in_combat': 'OFF'})
            result = SimpleNamespace(tick=TickResult('no_candidates', Decision(
                frame, frame.values, (), recovery_ready=True)))
            window._map_navigator = Mock(blocked=False)
            window._map_navigator.observe.return_value = None
            with patch('wowbuddy.engine.character_state.decode_navigation_state') as sample:
                for sequence in range(1, 80):
                    sample.return_value = position
                    character = replace(arrival, x=position.x, y=position.y)
                    window._poll_navigation(result, session, object(), frame, character, None, navigate=True)
                    if trip.complete:
                        break
                    self.assertTrue(checkpoint.exists())
                    waypoint = window._map_navigator.observe.call_args.args[3]
                    if sequence == 1:
                        self.assertGreater(waypoint.x, position.x)
                        self.assertNotEqual(waypoint, trip.goal)
                    position = replace(position, sequence=sequence + 1, x=waypoint.x, y=waypoint.y)
            self.assertTrue(trip.complete)
            self.assertEqual(window._leveling_destination, (session, arrival.route_key, trip.goal))
            self.assertFalse(checkpoint.exists())

        for new_game in (False, True):
            with self.subTest(new_game=new_game), TemporaryDirectory() as directory:
                checkpoint = Path(directory)/'leveling-travel.json'
                self.window(directory, start, auto_grind=True)
                self.window(directory, restart, auto_grind=True)
                self.window(directory, restart_in_destination, auto_grind=True)

    def test_restart_replans_the_portal_when_harbor_and_camp_share_the_same_map(self):
        from unittest.mock import Mock
        from wowbuddy.engine.character_state import CharacterState
        from wowbuddy.automation.leveling_route import AutomaticLeveling, write_leveling_result

        harbor = CharacterState('alive', True, True, 'alliance', 10, 1438, '泰达希尔', 58.40098, 93.91529)
        point = {'zone': '泰达希尔', 'name': '高地营地', 'x': 39.91, 'y': 28.687}

        def restart(window):
            session = 123, 999, 0
            window._character_session = session[:2], 42
            window._character_travel_identity = window._character_session, (15, 16)
            submit = Mock()
            window._leveling_planner = AutomaticLeveling(submit)
            window._poll_leveling(session, harbor, True)
            submit.assert_not_called()
            trip = window._leveling_trip[2]
            self.assertTrue(trip.legs[0].portal)
            self.assertEqual([leg.destination for leg in trip.legs], [1457, 1438])
            self.assertIsNone(window._leveling_destination)

        with TemporaryDirectory() as directory:
            write_leveling_result(Path(directory)/'leveling-travel.json', {
                'character': ['character', 15, 16, 'alliance', 10], 'point': point,
                'walking_maps': [1438, 1457, 1438], 'blocked_connections': [],
            })
            self.window(directory, restart, auto_grind=True)

    def test_restart_resumes_same_map_camp_approach_after_revival(self):
        from concurrent.futures import Future
        from dataclasses import replace
        from unittest.mock import Mock
        from wowbuddy.engine.character_state import CharacterState, DeathState, NavigationState
        from wowbuddy.automation.leveling_route import AutomaticLeveling
        from wowbuddy.core.old_protocol import OldFrame
        from wowbuddy.engine.pipeline import Decision
        from wowbuddy.engine.scheduler import TickResult

        origin = CharacterState('alive', True, True, 'alliance', 19, 1439, '黑海岸', 39.8, 70.691)
        point = {'zone': '黑海岸', 'name': '南侧营地', 'x': 38.315, 'y': 77.167}
        frame = OldFrame('ok', values={'target_valid': 'OFF', 'player_in_combat': 'OFF'})

        def identify(window, session):
            window._character_session = session[:2], 42
            window._character_travel_identity = window._character_session, (15, 16)

        def start(window):
            session = (123, 456, 0)
            identify(window, session)
            result = Future()
            result.set_result({'point': point, 'cross_zone': False})
            window._leveling_planner = AutomaticLeveling(Mock(return_value=result))
            with patch.object(window, 'monotonic_ms', side_effect=(1000, 1300, 1600)):
                for _ in range(3):
                    window._poll_leveling(session, origin, True)
            self.assertEqual(window._leveling_trip[2].goal.label, '南侧营地')
            saved = json.loads(checkpoint.read_text('utf8'))
            self.assertEqual(saved['walking_maps'], [1439])
            self.assertEqual(saved['point'], point)

        def restart_off_road(window):
            session = (124, 789, 0)
            identify(window, session)
            off_road = replace(origin, x=46, y=80)
            self.assertFalse(window._resume_leveling_travel(session, off_road))
            self.assertIsNone(getattr(window, '_leveling_destination', None))

        def restart(window):
            session = (124, 789, 0)
            identify(window, session)
            submit = Mock()
            window._leveling_planner = AutomaticLeveling(submit)
            window._poll_leveling(session, None, True)
            self.assertIsNone(getattr(window, '_leveling_trip', None))
            self.assertTrue(checkpoint.is_file())
            character = replace(origin, x=40.91, y=76.9)
            position = NavigationState('alive', 1, 1439, character.x, character.y, 0, 6550, 4367, (87, 65, 68))
            window._poll_leveling(session, character, True)
            submit.assert_not_called()
            trip = window._leveling_trip[2]
            self.assertEqual(trip.goal.label, point['name'])
            navigator = window._map_navigator = Mock(blocked=False)
            navigator.observe.return_value = None
            window._post_revival_session = session

            def poll(sample, ready):
                tick = TickResult('no_candidates', Decision(frame, frame.values, (), recovery_ready=ready))
                with patch('wowbuddy.engine.character_state.decode_navigation_state', return_value=sample):
                    window._poll_navigation(SimpleNamespace(tick=tick), session, object(), frame,
                                            replace(character, x=sample.x, y=sample.y),
                                            DeathState('alive', sample.sequence, None, False, None), navigate=True)
                return navigator.observe.call_args.args[3]

            self.assertIsNone(poll(position, False))
            self.assertTrue(checkpoint.is_file())
            waypoint = poll(replace(position, sequence=2), True)
            self.assertEqual((waypoint.x, waypoint.y), (41.2973, 76.8282))
            for sequence in range(3, 20):
                position = replace(position, sequence=sequence, x=waypoint.x, y=waypoint.y)
                waypoint = poll(position, True)
                if not checkpoint.exists():
                    break
            self.assertTrue(trip.complete)
            self.assertFalse(checkpoint.exists())
            submit.assert_not_called()

        with TemporaryDirectory() as directory:
            checkpoint = Path(directory)/'leveling-travel.json'
            self.window(directory, start, auto_grind=True)
            self.window(directory, restart_off_road, auto_grind=True)
            self.window(directory, restart, auto_grind=True)

    def test_upgrade_during_crossing_finishes_arrival_road_and_requeries_from_that_map(self):
        from concurrent.futures import Future
        from dataclasses import replace
        from unittest.mock import Mock
        from wowbuddy.engine.character_state import CharacterState, NavigationState
        from wowbuddy.automation.leveling_route import AutomaticLeveling
        from wowbuddy.automation.navigation import MapDestination
        from wowbuddy.core.old_protocol import OldFrame
        from wowbuddy.engine.pipeline import Decision
        from wowbuddy.engine.scheduler import TickResult
        from wowbuddy.automation.walking_route import WalkingLeg, WalkingTrip

        def exercise(window):
            session = (123, 456, 0)
            entry = ((24.18, 78.35), (24.76, 78.62))
            legs = (WalkingLeg(1436, 1429, 10, ((61, 20),), arrival_road=entry, manual=True),
                    WalkingLeg(1429, 1433, 15, ((95, 68),)))
            trip = WalkingTrip(session, legs, MapDestination(1433, 23.25, 79.41, 'alive', '旧练级点'), level=18)
            window._leveling_trip = 'alliance', 18, trip
            window._leveling_destination = None
            character = CharacterState('alive', True, True, 'alliance', 19, 1429, '艾尔文森林', *entry[0])
            position = NavigationState('alive', 1, 1429, *entry[0], 0, 3470, 2314, (87, 65, 68))
            frame = OldFrame('ok', values={'target_valid': 'OFF', 'player_in_combat': 'OFF'})
            result = SimpleNamespace(tick=TickResult('no_candidates', Decision(
                frame, frame.values, (), recovery_ready=True)))
            navigator = window._map_navigator = Mock(blocked=False)
            navigator.observe.return_value = None
            new_point = {'zone': '艾尔文森林', 'name': '新练级点', 'x': 45.1, 'y': 63.0}
            online = Future()
            online.set_result({'point': new_point, 'cross_zone': False})
            submit = Mock(return_value=online)
            window._leveling_planner = AutomaticLeveling(submit)

            def poll(sample, current):
                window._poll_leveling(session, current, True)
                with patch('wowbuddy.engine.character_state.decode_navigation_state', return_value=sample):
                    window._poll_navigation(result, session, object(), frame, current, None, navigate=True)
                return navigator.observe.call_args.args[3]

            self.assertIsNone(poll(position, character))
            self.assertIsNone(poll(position, character))
            self.assertEqual(len(trip.legs), 2)
            self.assertIsNone(poll(replace(position, sequence=2), character))
            waypoint = poll(replace(position, sequence=3), character)
            self.assertEqual((waypoint.x, waypoint.y), entry[1])
            at_exit = replace(position, sequence=4, x=waypoint.x, y=waypoint.y)
            character = replace(character, x=at_exit.x, y=at_exit.y)
            self.assertIsNone(poll(at_exit, character))
            submit.assert_not_called()
            self.assertIsNone(window._leveling_destination)
            self.assertEqual([leg.destination for leg in trip.legs], [1433])

            with patch.object(window, 'monotonic_ms', return_value=1000) as clock:
                window._poll_leveling(session, character, True)
                self.assertIs(window._leveling_trip[2], trip)
                clock.return_value = 1300
                window._poll_leveling(session, character, True)
                window._poll_leveling(session, character, True)
            submit.assert_called_once()
            self.assertEqual(submit.call_args.args[1:6], ('alliance', 19, '艾尔文森林', *entry[1]))
            self.assertFalse(checkpoint.exists())
            self.assertEqual(window._leveling_destination[2].label, '新练级点')

        with TemporaryDirectory() as directory:
            checkpoint = Path(directory)/'leveling-travel.json'
            checkpoint.write_text('{}', 'utf8')
            self.window(directory, exercise, auto_grind=True)

    def test_upgrade_requeries_when_the_final_cross_map_approach_is_blocked(self):
        from concurrent.futures import Future
        from dataclasses import replace
        from unittest.mock import Mock
        from wowbuddy.engine.character_state import CharacterState, NavigationState
        from wowbuddy.automation.navigation import MapDestination
        from wowbuddy.core.old_protocol import OldFrame
        from wowbuddy.engine.pipeline import Decision
        from wowbuddy.engine.scheduler import TickResult
        from wowbuddy.automation.walking_route import WalkingTrip, plan_walking_route

        def exercise(window):
            session = (123, 456, 0)
            old_camp = MapDestination(1433, 23.25, 79.41, 'alive', '旧营地')
            legs = plan_walking_route(1429, 1433, 18, 'alive')
            trip = WalkingTrip(session, legs, old_camp, level=18, faction='alliance')
            position = NavigationState('alive', 1, 1433, 4.1, 73, 0, 2170, 1447, (87, 65, 68))
            trip.observe(position)
            trip.observe(replace(position, sequence=2))
            self.assertFalse(trip.connecting)
            self.assertTrue(trip.needs_safe_handoff(1433, 0))
            window._leveling_trip = 'alliance', 18, trip
            character = CharacterState('alive', True, True, 'alliance', 19, 1433, '赤脊山', position.x, position.y)
            frame = OldFrame('ok', values={'target_valid': 'OFF', 'player_in_combat': 'OFF'})
            result = SimpleNamespace(tick=TickResult('no_candidates', Decision(frame, frame.values, (), recovery_ready=True)))
            navigator = window._map_navigator = Mock(blocked=True)
            navigator.observe.return_value = '最后一段接入道路受阻'
            new_point = {'zone': '赤脊山', 'name': '新等级营地', 'x': 30.55, 'y': 57.1}
            future = Future()
            future.set_result({'point': new_point, 'cross_zone': False})
            submit = Mock(return_value=future)
            executor = Mock(submit=submit)
            self.assertIsNone(getattr(window, '_leveling_planner', None))

            with (patch.object(window, 'monotonic_ms', return_value=1000) as clock,
                  patch('concurrent.futures.ThreadPoolExecutor', return_value=executor) as create_executor):
                window._poll_leveling(session, character, True)
                create_executor.assert_not_called()
                submit.assert_not_called()
                with patch('wowbuddy.engine.character_state.decode_navigation_state', return_value=replace(position, sequence=3)):
                    window._poll_navigation(result, session, object(), frame, character, None, navigate=True)
                create_executor.assert_called_once_with(max_workers=1)
                self.assertIs(navigator.observe.call_args.kwargs['path'], trip)
                self.assertIsNotNone(navigator.observe.call_args.args[3])
                self.assertIsNone(window._leveling_trip)
                self.assertFalse(checkpoint.exists())
                clock.return_value = 1250
                window._poll_leveling(session, character, True)
                clock.return_value = 1500
                window._poll_leveling(session, character, True)
                window._poll_leveling(session, character, True)

            submit.assert_called_once()
            self.assertEqual(submit.call_args.args[1:6], ('alliance', 19, '赤脊山', 4.1, 73))
            self.assertIn(('赤脊山', old_camp.x, old_camp.y), submit.call_args.kwargs['excluded'])
            self.assertIsNone(window._leveling_upgrade_wait)
            active = window._leveling_trip
            self.assertEqual((active[2].goal if active else window._leveling_destination[2]).label, '新等级营地')

        with TemporaryDirectory() as directory:
            checkpoint = Path(directory)/'leveling-travel.json'
            checkpoint.write_text('{}', 'utf8')
            self.window(directory, exercise, auto_grind=True)

    def test_restart_continues_only_the_confirmed_crossing_entry(self):
        from concurrent.futures import Future
        from dataclasses import replace
        from unittest.mock import Mock
        from wowbuddy.engine.character_state import CharacterState, NavigationState
        from wowbuddy.automation.leveling_route import AutomaticLeveling
        from wowbuddy.automation.manual_routes import parse_manual_connection
        from wowbuddy.automation.navigation import MapDestination
        from wowbuddy.core.old_protocol import OldFrame
        from wowbuddy.engine.pipeline import Decision
        from wowbuddy.engine.scheduler import TickResult
        from wowbuddy.automation.walking_route import WalkingTrip

        connection = 'WBDROUTE1|1436|6010,2050|6100,2000\nWBDROUTE1|1429|2418,7835|2476,7862'
        onward = 'WBDROUTE1|1429|2476,7862|9500,6800\nWBDROUTE1|1433|1100,6700|1200,6800'
        other_onward = 'WBDROUTE1|1429|2800,8000|9500,6900\nWBDROUTE1|1433|1100,6800|1200,6900'
        legs = tuple(map(parse_manual_connection, (connection, onward)))
        entry = legs[0].arrival_road
        first = NavigationState('alive', 1, 1429, *entry[0], 0, 3470, 2314, (87, 65, 68))
        character = CharacterState('alive', True, True, 'alliance', 18, 1429, '艾尔文森林', *entry[0])
        frame = OldFrame('ok', values={'target_valid': 'OFF', 'player_in_combat': 'OFF'})
        result = SimpleNamespace(tick=TickResult('no_candidates', Decision(frame, frame.values, (), recovery_ready=True)))

        def setup(window, session):
            window._character_session = session[:2], 42
            window._character_travel_identity = window._character_session, (15, 16)
            window._map_navigator = Mock(blocked=False)
            window._map_navigator.observe.return_value = None

        def poll_navigation(window, session, current, position):
            with patch('wowbuddy.engine.character_state.decode_navigation_state', return_value=position):
                window._poll_navigation(result, session, object(), frame, current, None, navigate=True)
            return window._map_navigator.observe.call_args.args[3]

        def save(window):
            session = (123, 456, 0)
            setup(window, session)
            window.settings.save_manual_connections([connection, other_onward, onward])
            trip = WalkingTrip(session, legs[:1] if final_map else legs, goal, level=18, catalog_zone=zone)
            window._leveling_trip = 'alliance', 18, trip
            self.assertIsNone(poll_navigation(window, session, character, first))
            self.assertFalse(checkpoint.exists())
            self.assertIsNone(poll_navigation(window, session, character, first))
            self.assertFalse(checkpoint.exists())
            self.assertIsNone(poll_navigation(window, session, character, replace(first, sequence=2)))
            saved = json.loads(checkpoint.read_text('utf8'))
            self.assertEqual(saved['arrival_connection'], list(legs[0].blocked_key))
            self.assertEqual(saved['walking_maps'], [1429] if final_map else [1429, 1433])

        def resume(window):
            session = (124, 789, 0)
            setup(window, session)
            midway = replace(first, x=24.47, y=78.485)
            current = replace(character, level=level, x=midway.x, y=midway.y)
            original = checkpoint.read_bytes()
            changed = json.loads(original)
            changed['arrival_connection'][-1] = '0' * 64
            checkpoint.write_text(json.dumps(changed), 'utf8')
            navigation = Mock(return_value=midway)
            self.assertFalse(window._resume_leveling_travel(session, current, navigation=navigation))
            navigation.assert_not_called()
            checkpoint.write_bytes(original)
            session = (124, 900, 0)
            setup(window, session)
            off_road = replace(midway, x=30)
            self.assertFalse(window._resume_leveling_travel(session, replace(current, x=30),
                                                            navigation=lambda: off_road))
            # 新监控会话可在确认的位置恢复。
            session = (124, 1000, 0)
            setup(window, session)
            online = Future()
            online.set_result({'point': {'zone': '艾尔文森林', 'name': '新营地', 'x': 45.1, 'y': 63.0},
                               'cross_zone': False})
            submit = Mock(return_value=online)
            window._leveling_planner = AutomaticLeveling(submit)
            window._poll_leveling(session, current, True, navigation=lambda: None)
            submit.assert_not_called()
            self.assertIsNone(getattr(window, '_leveling_trip', None))
            window._poll_leveling(session, current, True, navigation=lambda: midway)
            self.assertEqual(window._leveling_trip[:2], ('alliance', 18))
            trip = window._leveling_trip[2]
            if level == 18:
                self.assertEqual(tuple(trip.legs), () if final_map else legs[1:])
                self.assertEqual(trip.goal, goal)
            target = poll_navigation(window, session, current, midway)
            self.assertEqual((target.x, target.y), entry[-1])
            submit.assert_not_called()
            end = replace(midway, x=target.x, y=target.y, sequence=2)
            current = replace(current, x=end.x, y=end.y)
            target = poll_navigation(window, session, current, end)
            if level == 18:
                saved = json.loads(checkpoint.read_text('utf8'))
                self.assertNotIn('arrival_connection', saved)
                self.assertEqual(saved['point']['name'], '旧营地')
                if final_map:
                    self.assertEqual(window._leveling_destination[2], goal)
                else:
                    self.assertIsNone(target)
                    window._poll_leveling(session, current, True)
                    target = poll_navigation(window, session, current, replace(end, sequence=3))
                    self.assertEqual((target.x, target.y), legs[1].points[-1])
                submit.assert_not_called()
                return
            self.assertIsNone(target)
            self.assertFalse(checkpoint.exists())
            with patch.object(window, 'monotonic_ms', return_value=1000) as clock:
                window._poll_leveling(session, current, True)
                clock.return_value = 1300
                window._poll_leveling(session, current, True)
                window._poll_leveling(session, current, True)
            submit.assert_called_once()
            self.assertEqual(submit.call_args.args[1:6], ('alliance', 19, '艾尔文森林', *entry[-1]))

        for level, final_map in ((18, False), (18, True), (19, False)):
            with self.subTest(level=level, final_map=final_map), TemporaryDirectory() as directory:
                zone = '艾尔文森林' if final_map else '赤脊山'
                goal = (MapDestination(1429, 28.2, 78.8, 'alive', '旧营地') if final_map
                        else MapDestination(1433, 23.25, 79.41, 'alive', '旧营地'))
                checkpoint = Path(directory)/'leveling-travel.json'
                self.window(directory, save, auto_grind=True)
                self.window(directory, resume, auto_grind=True)

    def test_restart_restores_the_same_characters_supply_trip_and_discards_a_stale_popup(self):
        from dataclasses import replace
        from unittest.mock import Mock
        from wowbuddy.engine.character_state import CharacterState, NavigationState, VendorState
        from wowbuddy.automation.navigation import MapDestination
        from wowbuddy.core.old_protocol import OldFrame
        from wowbuddy.engine.pipeline import Decision
        from wowbuddy.engine.scheduler import TickResult

        character = CharacterState('alive', True, True, 'alliance', 18, 1439, '黑海岸', 39.8, 70.691)
        position = NavigationState('alive', 1, 1439, character.x, character.y, 0, 6550, 4367, (87, 65, 68))
        bridge = replace(position, x=41.1705, y=73.542)
        camp = MapDestination(1439, character.x, character.y, 'alive', '原营地')
        reading = VendorState(1, 0, 0, False, False, False, False, ',', 0x76, None, catalog=True)
        frame = OldFrame('ok', values={'target_valid': 'OFF', 'player_in_combat': 'OFF'})
        result = SimpleNamespace(tick=TickResult('no_candidates', Decision(frame, frame.values, (), recovery_ready=True)),
                                 capture=SimpleNamespace(client_rect=None))

        def identify(window, session, identity):
            window._character_session = session[:2], 43
            window._character_travel_identity = window._character_session, identity

        def poll(window, session, at, vendor):
            with (patch('wowbuddy.engine.character_state.decode_navigation_state', return_value=at),
                  patch('wowbuddy.engine.character_state.decode_vendor_state', return_value=vendor),
                  patch.object(window, 'monotonic_ms', return_value=vendor.sequence * 2000)):
                window._poll_vendor(session, object(), frame, result, character)

        def follow(trip, at):
            for _ in range(40):
                target, _ = trip.observe(at)
                if trip.complete:
                    return at
                at = replace(at, sequence=at.sequence + 1, x=target.x, y=target.y)
            self.fail('未走完补给路线')

        def start(window):
            session = (123, 10, 0)
            identify(window, session, (15, 16))
            window._leveling_destination = session, character.route_key, camp
            poll(window, session, position, reading)
            self.assertFalse(json.loads(checkpoint.read_text('utf8'))['returning'])

        def restart_outbound(window):
            session = (456, 20, 0)
            identify(window, session, (15, 17))
            poll(window, session, bridge, reading)
            self.assertIsNone(window._online_vendor)
            identify(window, session, (15, 16))
            poll(window, session, replace(bridge, x=50), reading)
            self.assertIn('重新接入原路线', window._vendor_wait[1])
            poll(window, session, bridge, reading)
            self.assertIsNone(window._vendor_wait)
            trip = window._online_vendor[1]
            target, _ = trip.observe(bridge)
            self.assertGreater(target.y, bridge.y)
            at = follow(trip, bridge)
            shop = replace(reading, merchant_open=True, matched=True, junk=3, hovered=True, sell_point=(2000, 4000))
            with patch.object(window, '_send_travel_ui_action', Mock(return_value=True)) as send:
                poll(window, session, at, replace(shop, sequence=2, confirming=True))
                poll(window, session, at, replace(shop, sequence=3))
                poll(window, session, at, replace(shop, sequence=4, free=3, junk=0))
                poll(window, session, at, replace(reading, sequence=5, free=3))
                self.assertEqual([call.args[-2] for call in send.call_args_list], ['dismiss', 'sell', 'close'])
            self.assertTrue(json.loads(checkpoint.read_text('utf8'))['returning'])

        def restart_return(window):
            session = (789, 30, 0)
            identify(window, session, (15, 16))
            start = replace(position, x=40.29, y=69.88) if off_route else bridge
            if off_route:
                poll(window, session, replace(start, x=50), supplied)
                self.assertIsNone(window._online_vendor)
                self.assertIn('重新接入原路线', window._vendor_wait[1])
                poll(window, session, start, reading)
                self.assertIsNone(window._online_vendor)
            if before_return_commit:
                record = json.loads(checkpoint.read_text('utf8'))
                self.assertFalse(record['returning'])
                self.assertEqual(record['repair'], repair)
                poll(window, session, start, replace(supplied, merchant_open=True))
                self.assertIsNone(window._online_vendor)
                poll(window, session, start, replace(supplied, popup_blocked=True))
                self.assertIsNone(window._online_vendor)
            poll(window, session, start, supplied)
            self.assertTrue(json.loads(checkpoint.read_text('utf8'))['returning'])
            trip = window._online_vendor[2]
            self.assertEqual(trip.goal, camp)
            self.assertFalse(window._vendor_run.active)
            target, _ = trip.observe(start)
            if off_route:
                self.assertEqual((target.x, target.y), (40.583, 70.028))
            elif revive_near_road:
                revived = replace(position, sequence=2, x=41.2389, y=72.2795)
                if scenario == 'revive_after_last_waypoint':
                    follow(trip, start)
                    self.assertTrue(trip.complete)
                else:
                    trip.resume_after_revival()
                window._post_revival_session, window._post_revival_notice = session, False
                self.assertFalse(window._rejoin_camp_after_revival(session, character, replace(revived, moving=True)))
                self.assertFalse(window._rejoin_camp_after_revival(session, character, replace(revived, map_id=1440)))
                self.assertIs(window._leveling_trip[2], trip)
                self.assertTrue(window._rejoin_camp_after_revival(session, character, revived))
                trip = window._online_vendor[2]
                self.assertIs(window._leveling_trip[2], trip)
                self.assertEqual(trip.goal, camp)
                target, _ = trip.observe(revived)
                self.assertAlmostEqual(target.x, 41.155, places=3)
                self.assertAlmostEqual(target.y, 72.275, places=3)
                start = revived
            else:
                self.assertLess(target.y, start.y)
                revived = replace(position, x=40.29, y=69.88)
                window._post_revival_session, window._post_revival_notice = session, False
                self.assertFalse(window._rejoin_camp_after_revival(session, character, replace(revived, x=50)))
                self.assertTrue(window._rejoin_camp_after_revival(session, character, revived))
                trip = window._online_vendor[2]
                target, _ = trip.observe(revived)
                self.assertEqual((target.x, target.y), (40.583, 70.028))
                start = revived
            at = follow(trip, start)
            poll(window, session, at, replace(supplied, sequence=2))
            self.assertIsNone(window._online_vendor)
            self.assertFalse(checkpoint.exists())

        initial = reading
        for scenario in ('on_road', 'off_road', 'revive_near_road', 'revive_after_last_waypoint',
                         'sale_before_return_commit', 'repair_before_return_commit'):
            revive_near_road = scenario.startswith('revive_')
            off_route = scenario != 'on_road' and not revive_near_road
            before_return_commit = scenario.endswith('before_return_commit')
            repair = scenario.startswith('repair')
            reading = replace(initial, free=8, repair_needed=True) if repair else initial
            supplied = replace(reading, repair_needed=False) if repair else replace(reading, free=3)
            with self.subTest(scenario=scenario), TemporaryDirectory() as directory:
                checkpoint = Path(directory)/'vendor-travel.json'
                self.window(directory, start, auto_grind=True)
                if not before_return_commit:
                    self.window(directory, restart_outbound, auto_grind=True)
                self.window(directory, restart_return, auto_grind=True)

    def test_restart_restores_auberdine_flight_and_waits_for_two_ground_samples(self):
        from dataclasses import replace
        from unittest.mock import Mock
        from wowbuddy.win32.capture import CaptureResult
        from wowbuddy.engine.character_state import CharacterState, NavigationState, TaxiState
        from wowbuddy.automation.leveling_route import AutomaticLeveling, write_leveling_result
        from wowbuddy.automation.manual_routes import parse_fixed_camp
        from wowbuddy.core.old_protocol import OldFrame
        from wowbuddy.engine.pipeline import Decision
        from wowbuddy.engine.scheduler import TickResult
        from wowbuddy.automation.walking_route import _AUBERDINE_DESCENT_PROFILE

        point = {'zone': '黑海岸', 'name': '森林陆行雏鸟区', 'x': 38.953, 'y': 48.684}
        identity = ['character', 15, 16, 'alliance', 12]
        deck = CharacterState('alive', True, True, 'alliance', 12, 1439, '黑海岸', 36.3967, 45.6172, 16.29)
        airborne = replace(deck, map_id=None, zone=None, x=None, y=None, elevation=None)

        def restart(window):
            window.session.start(123)
            session = (123, window.session.state.elapsed_started_ms, window._unattended_revision)
            window._character_session = (session[:2], 42)
            window._character_travel_identity = window._character_session, (15, 16)
            submit = Mock()
            if mode == 'flying':
                frame = OldFrame('ok', values={'player_in_combat': 'OFF'})
                reading = TaxiState(1, 0, True, False, False, False, False, '', 0, None)
                tick = TickResult('no_candidates', Decision(frame, frame.values, (), recovery_ready=True))
                result = PollResult('no_candidates', CaptureResult('ok', object(), 'printwindow'), tick)
                with (patch.object(AssistantWindow, 'poll_once', return_value=result),
                      patch.object(window, '_poll_navigation'), patch.object(window, '_poll_revival'),
                      patch('wowbuddy.engine.character_state.route_character', return_value=None),
                      patch('wowbuddy.engine.character_state.decode_death_state', return_value=None),
                      patch('wowbuddy.engine.character_state.decode_taxi_state', return_value=reading),
                      patch('wowbuddy.engine.character_state.decode_character_state',
                            side_effect=[replace(airborne, level=11), replace(airborne, level=13)])):
                    window.poll_once()
                    self.assertIsNone(getattr(window, '_leveling_trip', None))
                    window.poll_once()
                self.assertIsNone(getattr(window, '_leveling_planner', None))
            else:
                window._leveling_planner = AutomaticLeveling(submit)
                if mode == 'fixed':
                    window._fixed_camp_route = parse_fixed_camp('WBDPOINT1|1439|3895,4868')
                window._poll_leveling(session, replace(deck, level=13) if mode == 'deck' else deck, True)
            submit.assert_not_called()
            trip = window._leveling_trip[2]
            self.assertTrue(trip.waiting_for_taxi)
            self.assertEqual((trip.goal.x, trip.goal.y), (38.95, 48.68) if mode == 'fixed' else (38.953, 48.684))
            if mode != 'fixed':
                self.assertEqual(window._leveling_checkpoint_session, session)
                self.assertEqual(window._leveling_trip[1], 12)
                self.assertTrue(trip.needs_safe_handoff(1439, 0))

            send = Mock(return_value=True)
            harbor = NavigationState('alive', 1, 1438, 58.40098, 93.91529, 0, 5092, 3394, (87, 65, 68))
            state = TaxiState(1, 1438, False, True, True, True, False, '', 0, (5000, 5000))
            self.assertEqual(trip.observe(harbor, taxi_reading=state, taxi_send=send), (None, None))
            ramp = replace(harbor, map_id=1439, width=6550, height=4367, position_steps=1_000_000)
            x, y, height = _AUBERDINE_DESCENT_PROFILE[-1]
            ramp = replace(ramp, sequence=2, x=x, y=y, elevation=height)
            state = TaxiState(2, 1439, True, False, False, False, False, '', 0, None)
            self.assertEqual(trip.observe(ramp, taxi_reading=state), (None, None))
            first = replace(state, sequence=3, riding=False)
            self.assertEqual(trip.observe(ramp, taxi_reading=first), (None, None))
            self.assertEqual(trip.observe(replace(ramp, sequence=3), taxi_reading=first), (None, None))
            second = replace(first, sequence=4)
            self.assertIn('落地并接入道路', trip.observe(replace(ramp, sequence=3), taxi_reading=second)[1])
            self.assertFalse(trip.waiting_for_taxi)
            self.assertTrue(trip.needs_safe_handoff(1439, 0))
            destination, _ = trip.observe(replace(ramp, sequence=4))
            self.assertTrue(destination.precision_stop)
            send.assert_not_called()

        for mode in ('flying', 'deck', 'fixed'):
            with self.subTest(mode=mode), TemporaryDirectory() as directory:
                if mode != 'fixed':
                    write_leveling_result(Path(directory)/'leveling-travel.json', {
                        'character': identity, 'walking_maps': [1438, 1457, 1438, 1439],
                        'point': point, 'blocked_connections': [],
                    })
                self.window(directory, restart, auto_grind=True)

    def test_grinding_requeries_if_the_lookup_cannot_be_turned_into_a_land_route(self):
        from concurrent.futures import Future
        from unittest.mock import Mock
        from wowbuddy.engine.character_state import CharacterState
        from wowbuddy.automation.leveling_route import AutomaticLeveling, find_grinding_point

        def exercise(window):
            session = (123, 456, 0)
            character = CharacterState('alive', True, True, 'alliance', 18, 1436, '西部荒野', 46.1, 38.2)
            rejected, alternate = Future(), Future()
            rejected.set_result({'point': {'zone': '黑海岸', 'name': '奥伯丁', 'x': 37, 'y': 44.1},
                                 'cross_zone': True})
            alternate.set_result({'point': {'zone': '赤脊山', 'name': '山丘', 'x': 11.65, 'y': 62.18},
                                  'cross_zone': True})
            submit = Mock(side_effect=(rejected, alternate))
            window._leveling_planner = AutomaticLeveling(submit)
            with patch.object(window, 'monotonic_ms', return_value=1000) as time:
                window._poll_leveling(session, character, True)
                time.return_value = 1300
                window._poll_leveling(session, character, True)
                window._poll_leveling(session, character, True)
                self.assertIsNone(getattr(window, '_leveling_trip', None))
                report = json.loads((Path(directory)/'leveling-auto.json').read_text('utf8'))
                self.assertFalse(report['ok'])
                self.assertEqual(report['point']['name'], '奥伯丁')
                window._poll_leveling(session, character, True)
                time.return_value = 1600
                window._poll_leveling(session, character, True)
                submit.assert_called_with(find_grinding_point, 'alliance', 18, '西部荒野', 46.1, 38.2,
                                          excluded=frozenset({('黑海岸', 37, 44.1)}), current_map_id=1436)
                window._poll_leveling(session, character, True)
                trip = window._leveling_trip[2]
                self.assertEqual(trip.goal.map_id, 1433)
                self.assertEqual([leg.destination for leg in trip.legs], [1429, 1433])

        with TemporaryDirectory() as directory:
            self.window(directory, exercise, auto_grind=True)

    def test_first_exhausted_camp_after_restore_is_excluded_from_the_new_lookup(self):
        from concurrent.futures import Future
        from unittest.mock import ANY, Mock
        from wowbuddy.engine.character_state import CharacterState
        from wowbuddy.automation.leveling_route import find_grinding_point
        from wowbuddy.automation.navigation import MapDestination

        def exercise(window):
            session = (123, 456, 0)
            character = CharacterState('alive', True, True, 'alliance', 18, 1439, '黑海岸', 40.15, 70.49)
            camp = MapDestination(1439, 39.8, 70.691, 'alive', '原营地')
            # 存档返营可直接建好本地计划，此时尚未查询过攻略。
            window._leveling_destination = session, character.route_key, camp
            self.assertIsNone(getattr(window, '_leveling_planner', None))
            future = Future()
            submit = Mock(return_value=future)
            with patch.object(window, 'monotonic_ms', return_value=1000) as time:
                window._advance_grind_camp(session, character, camp, '当前刷怪区未选到怪物')
                self.assertIsNone(window._leveling_destination)
                with patch.object(window._leveling_planner, '_submit', submit):
                    window._poll_leveling(session, character, True)
                    time.return_value = 1300
                    window._poll_leveling(session, character, True)
            submit.assert_called_once_with(find_grinding_point, 'alliance', 18, '黑海岸', 40.15, 70.49,
                                           excluded=frozenset({('黑海岸', 39.8, 70.691)}),
                                           cache=ANY, current_map_id=1439)

        with TemporaryDirectory() as directory:
            self.window(directory, exercise, auto_grind=True)

    def test_grinding_uses_next_camp_only_for_the_current_character_plan(self):
        from concurrent.futures import Future
        from unittest.mock import Mock
        from wowbuddy.engine.character_state import CharacterState
        from wowbuddy.automation.leveling_route import AutomaticLeveling, find_grinding_point
        from wowbuddy.automation.navigation import MapDestination

        def exercise(window):
            session = (123, 456, 0)
            character = CharacterState('alive', True, True, 'alliance', 15, 1436, '西部荒野', 46.1, 38.2)
            first = MapDestination(1436, 46.1, 38.2, 'alive', '摩尔森农场')
            second = MapDestination(1436, 43.97, 39.63, 'alive', '田野')
            online = Future()
            online.set_result({'point': {'zone': '赤脊山', 'name': '山丘', 'x': 11.65, 'y': 62.18}, 'cross_zone': True})
            submit = Mock(return_value=online)
            window._leveling_planner = AutomaticLeveling(submit)
            window._leveling_destination = session, character.route_key, first
            window._leveling_camps = [{'x': second.x, 'y': second.y, 'name': second.label}]
            with patch.object(window, 'monotonic_ms', return_value=1000) as time:
                window._advance_grind_camp((123, 456, 1), character, first, '路线受阻')
                self.assertEqual(window._leveling_destination[-1], first)
                window._advance_grind_camp(session, character, first, '路线受阻')
                self.assertEqual(window._leveling_destination, (session, character.route_key, second))
                self.assertFalse(window._leveling_camps)
                window._poll_leveling(session, character, True)
                submit.assert_not_called()

                window._advance_grind_camp(session, character, second, '未选到怪物')
                self.assertIsNone(window._leveling_destination)
                window._poll_leveling(session, character, True)
                time.return_value = 1300
                window._poll_leveling(session, character, True)
                submit.assert_called_once_with(find_grinding_point, 'alliance', 15, '西部荒野', 46.1, 38.2,
                    excluded=frozenset({('西部荒野', 46.1, 38.2), ('西部荒野', 43.97, 39.63)}), current_map_id=1436)
                window._poll_leveling(session, character, True)
                trip = window._leveling_trip[2]
                self.assertEqual((trip.goal.map_id, trip.goal.x, trip.goal.y), (1433, 11.65, 62.18))
                self.assertEqual([leg.destination for leg in trip.legs], [1429, 1433])

        with TemporaryDirectory() as directory:
            self.window(directory, exercise, auto_grind=True)

    def test_monitor_treats_the_approach_road_as_travel_and_retires_a_blocked_camp(self):
        from dataclasses import replace
        from unittest.mock import Mock
        from wowbuddy.engine.character_state import CharacterState, NavigationState
        from wowbuddy.automation.navigation import MapDestination
        from wowbuddy.core.old_protocol import OldFrame
        from wowbuddy.engine.pipeline import Decision
        from wowbuddy.engine.scheduler import TickResult
        from wowbuddy.automation.walking_route import WalkingTrip, plan_walking_route

        def exercise(window):
            session = (123, 456, 0)
            camp = MapDestination(1434, 35.65, 12.14, 'alive', '猛虎幼崽区')
            position = NavigationState('alive', 3, 1434, 39.47, 4.92, 0, 6381, 4254, (87, 65, 68))
            character = CharacterState('alive', True, True, 'alliance', 30, 1434, '荆棘谷',
                                       position.x, position.y)
            trip = WalkingTrip(session, plan_walking_route(1431, 1434, 30, 'alive'), camp, level=30)
            trip.observe(replace(position, sequence=1))
            trip.observe(replace(position, sequence=2))
            window._leveling_trip = 'alliance', 30, trip
            window._leveling_camps = [{'x': 36.62, 'y': 13.76, 'name': '猎豹幼崽区'}]
            window._leveling_planner = Mock()
            pull = window._arrival_pull = Mock()
            pull.observe.return_value = None
            navigator = window._map_navigator = Mock(blocked=False)
            navigator.observe.return_value = None
            frame = OldFrame('ok', values={'target_valid': 'OFF', 'player_in_combat': 'OFF'})
            result = SimpleNamespace(tick=TickResult('no_candidates', Decision(
                frame, frame.values, (), recovery_ready=True)))
            with patch('wowbuddy.engine.character_state.decode_navigation_state', return_value=position):
                window._poll_navigation(result, session, object(), frame, character, None, navigate=True)
                self.assertIsNone(pull.observe.call_args.args[1])
                self.assertIs(navigator.observe.call_args.kwargs['path'], trip)
                navigator.blocked = True
                navigator.observe.return_value = '过桥道路受阻'
                window._poll_navigation(result, session, object(), frame, character, None, navigate=True)
            self.assertIsNone(window._leveling_trip)
            self.assertIsNone(window._leveling_destination)
            retired = [call.args[2] for call in window._leveling_planner.retire_camp.call_args_list]
            self.assertEqual(retired, [camp, MapDestination(1434, 36.62, 13.76, 'alive', '猎豹幼崽区')])
            window._set_local_camp(session, character, {'x': camp.x, 'y': camp.y, 'name': camp.label})
            local_trip = window._leveling_trip[2]
            self.assertFalse(local_trip.complete)
            waypoint, _ = local_trip.observe(position)
            self.assertEqual((waypoint.x, waypoint.y), (39.37, 6.15))

        with TemporaryDirectory() as directory:
            self.window(directory, exercise, auto_grind=True)

    def test_unattended_idle_suggestions_use_navigation_context(self):
        from dataclasses import replace
        from unittest.mock import Mock
        from wowbuddy.core.candidates import Candidate
        from wowbuddy.engine.character_state import CharacterState, NavigationState
        from wowbuddy.automation.navigation import MapDestination
        from wowbuddy.core.old_protocol import OldFrame
        from wowbuddy.engine.pipeline import Decision
        from wowbuddy.engine.scheduler import TickResult

        def exercise(window):
            session = (123, 456, 0)
            camp = MapDestination(1436, 51.66, 77.21, 'alive', '匕首岭')
            sample = NavigationState('alive', 1, 1436, 51.66, 76.0, 0, 3500, 2333, (87, 65, 68))
            character = CharacterState('alive', True, True, 'alliance', 18, 1436, '西部荒野',
                                       sample.x, sample.y)
            window._leveling_destination = session, character.route_key, camp
            navigator = window._map_navigator = Mock(blocked=False)
            navigator.observe.return_value = None
            window._arrival_pull = Mock()
            window._arrival_pull.observe.return_value = None
            fields = {'target_valid': 'OFF', 'player_valid': 'ON', 'player_in_combat': 'OFF'}
            frame = OldFrame('ok', values=fields)

            def poll(position, *, candidates=(), selected=None):
                tick = TickResult('stopped', Decision(frame, fields, candidates, recovery_ready=True), selected)
                window.ui.suggestions.setPlainText('原始动作建议')
                with patch('wowbuddy.engine.character_state.decode_navigation_state', return_value=position):
                    window._poll_navigation(SimpleNamespace(tick=tick), session, object(), frame,
                                            character, None, navigate=True)
                return window.ui.suggestions.toPlainText()

            navigator.movement.in_foreground.return_value = False
            self.assertIn('等待游戏回到前台，再前往「匕首岭」', poll(sample))
            navigator.movement.in_foreground.return_value = True
            self.assertIn('无人托管：前往「匕首岭」', poll(sample))
            self.assertIn('等待可用的角色定位', poll(None))
            arrived = replace(sample, x=camp.x, y=camp.y)
            self.assertIn('在「匕首岭」寻找目标', poll(arrived))
            food = Candidate(action='recovery_food', label='自动进食', tag='恢复')
            self.assertEqual(poll(arrived, candidates=(food,), selected=food), '原始动作建议')
            window._leveling_destination = None
            self.assertIn('等待可达的练级点', poll(arrived))

        with TemporaryDirectory() as directory:
            self.window(directory, exercise, auto_grind=True)

    def test_empty_camp_checks_one_more_position_on_the_access_road(self):
        from dataclasses import replace
        from unittest.mock import Mock
        from wowbuddy.engine.character_state import CharacterState, NavigationState
        from wowbuddy.automation.navigation import MapDestination
        from wowbuddy.core.old_protocol import OldFrame
        from wowbuddy.engine.pipeline import Decision
        from wowbuddy.engine.scheduler import TickResult
        from wowbuddy.automation.walking_route import camp_scan_waypoint

        def exercise(window, map_id, zone, camp, position, expected=None):
            session = (123, 456, 0)
            character = CharacterState('alive', True, True, 'alliance', 18, map_id, zone,
                                       position.x, position.y)
            window._leveling_destination = session, character.route_key, camp
            window._leveling_planner = Mock()
            navigator = window._map_navigator = Mock(blocked=False)
            navigator.observe.return_value = None
            pull = window._arrival_pull = Mock(empty=True)
            pull.observe.return_value = '四个方向均未读到可攻击目标。'
            frame = OldFrame('ok', values={'target_valid': 'OFF', 'player_in_combat': 'OFF'})

            def poll(sample, *, ready=True):
                tick = TickResult('no_candidates', Decision(frame, frame.values, (), recovery_ready=ready))
                with patch('wowbuddy.engine.character_state.decode_navigation_state', return_value=sample):
                    window._poll_navigation(SimpleNamespace(tick=tick), session, object(), frame,
                                            character, None, navigate=True)

            poll(position)
            scout = window._camp_scout_point(session, camp)
            self.assertIsNotNone(scout)
            self.assertFalse(scout.allow_detour)
            self.assertLess(scout.y, camp.y)
            if expected is not None:
                self.assertEqual((scout.x, scout.y), expected)
            window._leveling_planner.retire_camp.assert_not_called()
            pull.empty = False
            pull.observe.return_value = None
            poll(position, ready=False)
            self.assertIsNone(navigator.observe.call_args.args[2])
            poll(position)
            self.assertEqual(navigator.observe.call_args.args[3], scout)
            self.assertEqual(pull.observe.call_args.args[1], scout)
            arrived = replace(position, sequence=2, x=scout.x, y=scout.y)
            pull.empty = True
            pull.observe.return_value = '补扫未选到怪物。'
            poll(arrived)
            window._leveling_planner.retire_camp.assert_called_once()
            self.assertEqual(window._leveling_planner.retire_camp.call_args.args[2], camp)
            self.assertIsNone(window._camp_scout_point(session, camp))

            window._leveling_destination = session, character.route_key, camp
            window._camp_scout = session, camp, scout
            pull.empty = False
            pull.observe.return_value = None
            poll(replace(position, x=position.x + 0.8))
            self.assertIsNone(navigator.observe.call_args.args[2])
            self.assertIsNone(window._camp_scout_point(session, camp))

            self.assertIsNone(camp_scan_waypoint(camp, replace(position, moving=True)))
            self.assertIsNone(camp_scan_waypoint(camp, replace(position, continuous=False)))
            self.assertIsNone(camp_scan_waypoint(camp, replace(position, x=position.x + 0.5)))
            short_road = ((camp.x, camp.y - 0.2), (camp.x, camp.y))
            self.assertIsNone(camp_scan_waypoint(camp, position, manual_road=short_road))
            with patch('wowbuddy.automation.walking_route._narrow_road_point', return_value=True):
                self.assertIsNone(camp_scan_waypoint(camp, position, manual_road=(
                    (camp.x, camp.y - 2.5), (camp.x, camp.y))))

        cases = (
            (1436, '西部荒野', '匕首岭', (51.66, 77.21), (51.66, 77.11), (3500, 2333), None),
            (1433, '赤脊山', '赤脊山偷猎者营地', (23.25, 79.41), (23.17, 79.31),
             (2171, 1448), (23.03, 78.23)),
        )
        for map_id, zone, label, goal, origin, size, expected in cases:
            with self.subTest(zone=zone), TemporaryDirectory() as directory:
                camp = MapDestination(map_id, *goal, 'alive', label)
                position = NavigationState('alive', 1, map_id, *origin, 0, *size, (87, 65, 68), continuous=True)
                self.window(directory, lambda window: exercise(window, map_id, zone, camp, position, expected),
                            auto_grind=True)

    def test_camp_travel_yields_to_combat_before_and_after_attacker_is_targeted(self):
        from dataclasses import replace
        from unittest.mock import Mock
        from wowbuddy.engine.character_state import CharacterState, NavigationState
        from wowbuddy.core.old_protocol import OldFrame
        from wowbuddy.engine.pipeline import Decision
        from wowbuddy.engine.scheduler import TickResult

        def exercise(window):
            session = (123, 456, 0)
            position = NavigationState('alive', 1, 1433, 27.7, 49.9, 0, 2170, 1448, (87, 65, 68))
            character = CharacterState('alive', True, True, 'alliance', 18, 1433, '赤脊山',
                                       position.x, position.y)
            window._set_local_camp(session, character, {'x': 30.55, 'y': 57.1, 'name': '湖南岸鱼人区'})
            trip = window._leveling_trip[2]
            navigator = window._map_navigator = Mock(blocked=False)
            navigator.observe.return_value = None

            def poll(sequence, combat, target):
                fields = {'target_valid': target, 'player_in_combat': combat}
                frame = OldFrame('ok', values=fields)
                result = SimpleNamespace(tick=TickResult('no_candidates',
                    Decision(frame, fields, (), recovery_ready=True)))
                with patch('wowbuddy.engine.character_state.decode_navigation_state',
                           return_value=replace(position, sequence=sequence)):
                    window._poll_navigation(result, session, object(), frame, character, None, navigate=True)
                return navigator.observe.call_args.args[3]

            waypoint = poll(1, 'OFF', 'OFF')
            self.assertIsNotNone(waypoint)
            self.assertIsNone(poll(2, 'ON', 'OFF'))
            self.assertIsNone(poll(3, 'ON', 'ON'))
            self.assertIs(window._leveling_trip[2], trip)
            self.assertEqual(poll(4, 'OFF', 'OFF'), waypoint)

        with TemporaryDirectory() as directory:
            self.window(directory, exercise, auto_grind=True)

    def test_grinding_skips_an_alternative_behind_the_same_blocked_bridge(self):
        from unittest.mock import Mock
        from wowbuddy.engine.character_state import CharacterState, NavigationState
        from wowbuddy.automation.navigation import MapDestination
        from wowbuddy.core.old_protocol import OldFrame
        from wowbuddy.engine.pipeline import Decision
        from wowbuddy.engine.scheduler import TickResult

        def exercise(window):
            session = (123, 456, 0)
            near = (62.3, 41.35)
            character = CharacterState('alive', True, True, 'horde', 27, 1424, '希尔斯布莱德丘陵', *near)
            position = NavigationState('alive', 1, 1424, *near, 0, 3200, 2133, (87, 65, 68))
            north = {'x': 60.983, 'y': 50.923, 'name': '北侧山地狮'}
            south = {'x': 58.522, 'y': 55.591, 'name': '南侧山地狮'}
            first = window._set_local_camp(session, character, north)
            window._leveling_camps = [south]
            window._leveling_planner = Mock()
            navigator = window._map_navigator = Mock(blocked=True)
            navigator.observe.return_value = '过桥道路受阻'
            frame = OldFrame('ok', values={'target_valid': 'OFF', 'player_in_combat': 'OFF'})
            result = SimpleNamespace(tick=TickResult('no_candidates', Decision(
                frame, frame.values, (), recovery_ready=True)))
            with patch('wowbuddy.engine.character_state.decode_navigation_state', return_value=position):
                window._poll_navigation(result, session, object(), frame, character, None, navigate=True)
            blocked = navigator.observe.call_args.args[3]
            self.assertEqual((blocked.x, blocked.y, blocked.allow_detour), (62.5, 41.51, False))
            self.assertIsNone(window._leveling_trip)
            self.assertIsNone(window._leveling_destination)
            self.assertEqual(window._leveling_camps, [])
            self.assertEqual([call.args[2] for call in window._leveling_planner.retire_camp.call_args_list],
                             [first, MapDestination(1424, south['x'], south['y'], 'alive', south['name'])])

        with TemporaryDirectory() as directory:
            self.window(directory, exercise, auto_grind=True)

    def test_unattended_requeries_from_current_map_after_cross_zone_route_is_exhausted(self):
        from concurrent.futures import Future
        from unittest.mock import Mock
        from test_leveling_route import leg, stage
        from wowbuddy.engine.character_state import CharacterState, NavigationState
        from wowbuddy.automation.leveling_route import AutomaticLeveling, find_grinding_point
        from wowbuddy.automation.manual_routes import parse_manual_route
        from wowbuddy.core.old_protocol import OldFrame
        from wowbuddy.engine.pipeline import Decision
        from wowbuddy.engine.scheduler import TickResult

        redridge = '/zh/zones/eastern-kingdoms/redridge-mountains/'
        westfall = '/zh/zones/eastern-kingdoms/westfall/'
        sources = {'/zh/leveling/alliance/': stage(1, '15–19', leg('赤脊山', 'redridge-mountains',
                                                                  [('湖畔镇', '25.5, 59.4')]))}
        for path, coords in ((redridge, '11.65,62.18'), (westfall, '46.1,38.2')):
            sources[path] = (f'<section id="route-alliance"><a class="route-coords" '
                             f'href="{path}?pin={coords}#map">营地</a></section>')
        fetch = Mock(side_effect=lambda url: sources[url.removeprefix('https://wowhandbook.com')])

        def submit(fn, *args, **options):
            future = Future()
            future.set_result(fn(*args, fetch=fetch, **options))
            return future

        def exercise(window):
            session = (123, 456, 0)
            position = NavigationState('alive', 1, 1429, 50.2, 71.6, 0, 3470, 2314, (87, 65, 68))
            character = CharacterState('alive', True, True, 'alliance', 15, 1429, '艾尔文森林',
                                       position.x, position.y)
            query = Mock(side_effect=submit)
            window._leveling_planner = AutomaticLeveling(query)
            manual_route = 'WBDROUTE1|1433|1100,6200|1160,6250'
            window.settings.save_manual_routes([manual_route])
            frame = OldFrame('ok', values={'target_valid': 'OFF', 'player_in_combat': 'OFF'})
            result = SimpleNamespace(tick=TickResult('no_candidates', Decision(
                frame, frame.values, (), recovery_ready=True)))
            window._map_navigator = Mock(blocked=True)
            window._map_navigator.observe.return_value = '出城道路受阻'

            with patch.object(window, 'monotonic_ms', return_value=1000) as clock:
                window._poll_leveling(session, character, True)
                clock.return_value = 1300
                window._poll_leveling(session, character, True)
                window._poll_leveling(session, character, True)
                first = window._leveling_trip[2]
                blocked_leg = first.legs[0]
                self.assertEqual((first.goal.map_id, first.goal.x, first.goal.y), (1433, 11.6, 62.5))
                with patch('wowbuddy.engine.character_state.decode_navigation_state', return_value=position):
                    window._poll_navigation(result, session, object(), frame, character, None, navigate=True)
                self.assertTrue(first.travel_exhausted)
                self.assertIsNone(window._leveling_trip)
                self.assertIsNone(window._leveling_destination)
                self.assertIn('从当前地图重新查询', window.ui.log_view.toPlainText())

                window._poll_leveling(session, character, True)
                clock.return_value = 1600
                fetch.reset_mock()
                window._poll_leveling(session, character, True)
                window._poll_leveling(session, character, True)
                query.assert_called_with(find_grinding_point, 'alliance', 15, '艾尔文森林',
                                         position.x, position.y, blocked_legs=frozenset({blocked_leg}),
                                         excluded=frozenset({('赤脊山', 11.65, 62.18)}),
                                         camp_routes=(parse_manual_route(manual_route),), current_map_id=1429)
                replacement = window._leveling_trip[2]
                self.assertEqual(replacement.goal.map_id, 1436)
                self.assertNotIn(blocked_leg, replacement.legs)
                self.assertNotIn('https://wowhandbook.com' + redridge,
                                 [call.args[0] for call in fetch.call_args_list])

        with TemporaryDirectory() as directory:
            self.window(directory, exercise, auto_grind=True)

    def test_running_monitor_retargets_at_camp_without_resuming_map_travel(self):
        from dataclasses import replace
        from unittest.mock import Mock
        from wowbuddy.core.auto_target import PACKET_BASE
        from wowbuddy.engine.character_state import CharacterState, NavigationState
        from wowbuddy.automation.navigation import MapDestination
        from wowbuddy.core.old_protocol import OldFrame
        from wowbuddy.engine.pipeline import Decision
        from wowbuddy.engine.scheduler import TickResult

        def exercise(window):
            session = (123, 456, 0)
            character = CharacterState('alive', True, True, 'alliance', 16, 1436, '西部荒野', 45.4, 70.2)
            position = NavigationState('alive', 1, 1436, 45.4, 70.2, 0, 1000, 800, (87, 65, 68),
                                       idle_key_index=1, target_revision=10, retarget_key=9)
            camp = MapDestination(1436, 45.4, 70.2, 'alive', '月溪镇')
            window._leveling_destination = session, character.route_key, camp
            movement = Mock()
            window.dispatcher.dispatch = Mock()
            window.dispatcher.dispatch.return_value.success = True

            def poll(sequence, now, target, revision, ack):
                fields = {'target_valid': target, 'player_valid': 'ON', 'player_in_combat': 'OFF',
                          'ttd': str(PACKET_BASE + 8192 + 32 * ack + 1)}
                frame = OldFrame('ok', values=fields)
                result = SimpleNamespace(tick=TickResult('no_candidates',
                    Decision(frame, fields, (), recovery_ready=True, attack_blocked_by_range=target == 'ON'),
                    display_now_ms=now + 1000))
                with (patch('wowbuddy.engine.character_state.decode_navigation_state',
                            return_value=replace(position, sequence=sequence, target_revision=revision)),
                      patch('wowbuddy.engine.character_state.decode_target_bearing', return_value=None),
                      patch('wowbuddy.automation.navigation.ForegroundMovement', return_value=movement),
                      patch.object(window, 'monotonic_ms', return_value=now)):
                    window._poll_navigation(result, session, object(), frame, character, None, navigate=True)

            poll(1, 0, 'OFF', 10, 0)
            poll(2, 250, 'OFF', 10, 0)
            window.dispatcher.dispatch.assert_called_once()
            poll(3, 500, 'ON', 11, 1)
            for sequence in range(4, 12):
                poll(sequence, 500 + (sequence - 3) * 1000, 'ON', 11, 1)
            movement.pulse.assert_not_called()
            poll(12, 8750, 'ON', 11, 1)
            movement.pulse.assert_called_once_with(123, 9, 35, (87, 65, 68, 9))
            movement.hold_forward.assert_not_called()

        with TemporaryDirectory() as directory:
            self.window(directory, exercise, auto_grind=True)

    def test_unattended_reselects_an_unreachable_target_away_from_the_camp(self):
        from dataclasses import replace
        from unittest.mock import Mock
        from wowbuddy.engine.character_state import CharacterState, NavigationState, TargetBearing
        from wowbuddy.automation.navigation import MapDestination
        from wowbuddy.core.old_protocol import OldFrame
        from wowbuddy.engine.pipeline import Decision
        from wowbuddy.engine.scheduler import TickResult
        from wowbuddy.automation.walking_route import WalkingTrip, plan_walking_route

        def exercise(window):
            session = (123, 456, 0)
            character = CharacterState('alive', True, True, 'alliance', 16, 1436, '西部荒野', 45.4, 70.2)
            position = NavigationState('alive', 1, 1436, 45.4, 70.2, 0, 1000, 800, (87, 65, 68),
                                       target_revision=11, retarget_key=9, discard_key=0x77)
            movement = Mock()
            movement.pulse.return_value = True
            window._leveling_destination = None
            window._leveling_trip = None

            def poll(sequence, *, ready=True, combat='OFF', revision=11, moving=False, target='ON', x=None):
                fields = {'target_valid': target, 'player_valid': 'ON', 'player_in_combat': combat}
                frame = OldFrame('ok', values=fields)
                result = SimpleNamespace(tick=TickResult('no_candidates',
                    Decision(frame, fields, (), recovery_ready=ready, attack_blocked_by_range=target == 'ON'),
                    display_now_ms=10_000))
                with (patch('wowbuddy.engine.character_state.decode_navigation_state',
                            return_value=replace(position, sequence=sequence, target_revision=revision,
                                                 moving=moving, x=position.x if x is None else x)),
                      patch('wowbuddy.engine.character_state.decode_target_bearing',
                            return_value=TargetBearing(revision, 0.5, 37)),
                      patch('wowbuddy.win32.windows_keys.is_foreground', return_value=True),
                      patch.object(window, 'monotonic_ms', return_value=sequence * 250),
                      patch('wowbuddy.automation.navigation.ForegroundMovement', return_value=movement)):
                    window._poll_navigation(result, session, object(), frame, character, None, navigate=True)

            for sequence in range(1, 8):
                poll(sequence)
            self.assertEqual(movement.pulse.call_count, 5)
            self.assertTrue(all(call.args[1] == 87 for call in movement.pulse.call_args_list))
            self.assertIn('距离变化', window.ui.log_view.toPlainText())
            movement.pulse.reset_mock()

            poll(7)  # 重复帧不能触发重选。
            poll(8, ready=False)
            poll(9, combat='ON')
            poll(10, moving=True)
            poll(11)
            poll(11)
            movement.pulse.assert_not_called()
            poll(12)
            poll(13)
            movement.pulse.assert_called_once_with(123, 9, 35, (87, 65, 68, 9))
            self.assertIn('已请求重选一次', window.ui.log_view.toPlainText())

            movement.pulse.reset_mock()
            alternate_x = position.x + 1
            poll(14, revision=12, x=alternate_x)
            poll(15, revision=12, x=alternate_x)
            movement.pulse.assert_called_once_with(123, 87, 120, (87, 65, 68))

            camp = MapDestination(1436, position.x, position.y, 'alive', '月溪镇')
            window._leveling_destination = session, character.route_key, camp
            window._leveling_planner = Mock()
            for sequence in range(16, 21):
                poll(sequence, revision=12, x=alternate_x)
            self.assertNotIn(0x77, [call.args[1] for call in movement.pulse.call_args_list])
            poll(21, revision=12, x=alternate_x)
            poll(22, revision=12, x=alternate_x)
            window._leveling_planner.retire_camp.assert_not_called()
            self.assertEqual(window._leveling_destination[-1], camp)
            self.assertEqual([call.args[1] for call in movement.pulse.call_args_list].count(0x77), 1)
            self.assertNotIn(9, [call.args[1] for call in movement.pulse.call_args_list])
            self.assertIn('重选的目标也无法接近', window.ui.log_view.toPlainText())
            poll(23, revision=13, target='OFF', x=alternate_x)
            window._leveling_planner.retire_camp.assert_called_once_with(session, character, camp, 5750)
            self.assertIsNone(window._leveling_destination)
            self.assertIn('游戏已确认清除', window.ui.log_view.toPlainText())

            goal = MapDestination(1433, 11.65, 62.18, 'alive', '三角路口以东的山丘')
            legs = plan_walking_route(1436, 1433, character.level, 'alive')
            trip = WalkingTrip(session, legs, goal, level=character.level)
            window._leveling_trip = character.faction, character.level, trip
            poll(33, revision=14)
            self.assertIsNotNone(trip.current)
            self.assertEqual(trip.current.map_id, character.map_id)
            self.assertFalse(window._approaching_target)
            poll(34, revision=15, target='OFF')
            self.assertIs(window._leveling_trip[2], trip)
            self.assertEqual(trip.current.map_id, character.map_id)
            window._leveling_planner.retire_camp.assert_called_once()

        with TemporaryDirectory() as directory:
            self.window(directory, exercise, auto_grind=True)

    def test_unattended_retires_camp_after_three_confirmed_rejections(self):
        from dataclasses import replace
        from unittest.mock import Mock
        from wowbuddy.engine.character_state import CharacterState, NavigationState
        from wowbuddy.automation.navigation import MapDestination
        from wowbuddy.core.old_protocol import OldFrame
        from wowbuddy.engine.pipeline import Decision
        from wowbuddy.engine.scheduler import TickResult

        def exercise(window):
            session = (123, 456, 0)
            character = CharacterState('alive', True, True, 'alliance', 16, 1436, '西部荒野', 45.4, 70.2)
            position = NavigationState('alive', 1, 1436, 45.4, 70.2, 0, 1000, 800, (87, 65, 68),
                                       discard_key=0x77)
            camp = MapDestination(1436, position.x, position.y, 'alive', '月溪镇')
            window._leveling_destination = session, character.route_key, camp
            window._leveling_camps = [{'x': 51.66, 'y': 77.21, 'name': '匕首岭'}]
            window._leveling_planner = Mock()
            movement = Mock(holding_forward=False)
            movement.keep_forward.return_value = False

            def poll(sequence, revision, *, rejected):
                fields = {'target_valid': 'ON' if rejected else 'OFF', 'player_valid': 'ON',
                          'player_in_combat': 'OFF'}
                frame = OldFrame('ok', values=fields)
                result = SimpleNamespace(tick=TickResult('no_candidates', Decision(
                    frame, fields, (), recovery_ready=True,
                    target_rejection='当前怪物已被其他玩家占有' if rejected else None), display_now_ms=10_000))
                with (patch('wowbuddy.engine.character_state.decode_navigation_state',
                            return_value=replace(position, sequence=sequence, target_revision=revision)),
                      patch('wowbuddy.win32.windows_keys.is_foreground', return_value=True),
                      patch.object(window, 'monotonic_ms', return_value=sequence * 250),
                      patch('wowbuddy.automation.navigation.ForegroundMovement', return_value=movement)):
                    window._poll_navigation(result, session, object(), frame, character, None, navigate=True)

            for ordinal in range(3):
                sequence, revision = 1 + ordinal * 40, 20 + ordinal * 2
                poll(sequence, revision, rejected=True)
                poll(sequence + 1, revision, rejected=True)
                self.assertEqual(movement.pulse.call_count, ordinal + 1)
                poll(sequence + 2, revision, rejected=False)
                window._leveling_planner.retire_camp.assert_not_called()
                self.assertEqual(window._leveling_destination[-1], camp)
                poll(sequence + 3, revision + 1, rejected=False)
                if ordinal < 2:
                    poll(sequence + 3, revision + 1, rejected=False)
                    window._leveling_planner.retire_camp.assert_not_called()
            window._leveling_planner.retire_camp.assert_called_once_with(session, character, camp, 21_000)
            self.assertEqual(window._leveling_destination[-1].label, '匕首岭')
            self.assertIn('连续遇到不适合练级的目标', window.ui.log_view.toPlainText())

        with TemporaryDirectory() as directory:
            self.window(directory, exercise, auto_grind=True)

    def test_blocked_same_map_corpse_routes_around_and_waits_for_disabled_popup(self):
        from unittest.mock import Mock
        from wowbuddy.engine.character_state import DeathState, NavigationState
        from wowbuddy.core.old_protocol import OldFrame
        from wowbuddy.engine.pipeline import Decision
        from wowbuddy.engine.scheduler import TickResult

        def exercise(window):
            session = (123, 456, 0)
            position = NavigationState('ghost', 1, 1432, 45, 50, 0, 1000, 800, (87, 65, 68))
            corpse = (1432, 50, 50)
            frame = OldFrame('ok', values={'player_valid': 'OFF', 'player_in_combat': 'OFF', 'equipment_red': 'ON'})
            result = SimpleNamespace(tick=TickResult('no_candidates', Decision(frame, frame.values, ())))
            window._vendor_wait = session, '普通背包已满，暂停练级。'
            window._dispatch_stop_session = session
            window._waiting_for_movement_stop = True
            navigator = window._map_navigator = Mock(blocked=True)
            navigator.observe.return_value = '尸体直达受阻'
            with patch('wowbuddy.engine.character_state.decode_navigation_state', return_value=position):
                window._poll_navigation(result, session, object(), frame, None,
                    DeathState('ghost', 1, None, False, corpse, 'missing'), navigate=True)
                self.assertEqual(navigator.observe.call_args.args[3].label, '尸体')
                self.assertIsNone(window._dispatch_stop_session)
                navigator.blocked = False
                navigator.observe.return_value = None
                window._poll_navigation(result, session, object(), frame, None,
                    DeathState('ghost', 2, None, False, corpse, 'missing'), navigate=True)
                probe = navigator.observe.call_args.args[3]
                self.assertNotEqual((probe.x, probe.y), corpse[1:])
                window._poll_navigation(result, session, object(), frame, None,
                    DeathState('ghost', 3, None, False, corpse, 'disabled'), navigate=True)
                self.assertIsNone(navigator.observe.call_args.args[2])
                window._poll_navigation(result, session, object(), frame, None,
                    DeathState('ghost', 4, None, False, corpse, 'missing'), navigate=True)
                self.assertEqual(navigator.observe.call_args.args[3], probe)
                window._poll_navigation(result, session, object(), frame, None,
                    DeathState('ghost', 5, (5000, 6000), False, corpse, 'ready'), navigate=True)
                self.assertIsNone(navigator.observe.call_args.args[2])

        with TemporaryDirectory() as directory:
            self.window(directory, exercise, auto_grind=True)

    def test_blocked_revival_backtrack_restarts_corpse_approach_after_input_returns(self):
        from dataclasses import replace
        from unittest.mock import Mock
        from wowbuddy.win32.capture import Rect
        from wowbuddy.engine.character_state import DeathState, NavigationState
        from wowbuddy.automation.death_recovery import AutomaticRevival, CorpseAccess
        from wowbuddy.automation.navigation import MapDestination
        from wowbuddy.core.old_protocol import OldFrame
        from wowbuddy.engine.pipeline import Decision
        from wowbuddy.engine.scheduler import TickResult
        from wowbuddy.automation.walking_route import WalkingTrip

        def exercise(window):
            session = (123, 456, 0)
            rect = Rect(0, 0, 800, 600)
            position = NavigationState('ghost', 1, 52, 33.2, 36, 0, 1000, 1000, (87, 65, 68))
            popup = DeathState('ghost', 1, (5000, 6000), False, (52, 36, 36), 'ready')
            corpse = MapDestination(*popup.corpse, 'ghost', '尸体')
            frame = OldFrame('ok', values={'player_valid': 'OFF', 'player_in_combat': 'OFF', 'equipment_red': 'ON'})
            result = SimpleNamespace(tick=TickResult('no_candidates', Decision(frame, frame.values, ())))
            mouse = Mock()
            revival = window._automatic_revival = AutomaticRevival(mouse)
            navigator = window._map_navigator = Mock(blocked=False)
            navigator.observe.return_value = None
            window._poll_revival(session, popup, rect, prefer_clearance=True, position=position)
            farther = revival.landing_destination
            at = replace(position, sequence=2, x=farther.x, y=farther.y)
            old_trip = window._corpse_trip = WalkingTrip(session, (), corpse)
            window._corpse_access = CorpseAccess()

            with patch('wowbuddy.engine.character_state.decode_navigation_state', return_value=at):
                blocked = replace(popup, sequence=2, button=None, popup='input_blocked')
                window._poll_navigation(result, session, object(), frame, None, blocked, navigate=True)
                self.assertIsNone(navigator.observe.call_args.args[2])
                self.assertEqual(navigator.observe.call_args.args[3], farther)
                missing = replace(blocked, sequence=3, popup='missing')
                window._poll_revival(session, missing, rect, prefer_clearance=True, position=at)
                self.assertEqual(revival.landing_destination.x, position.x)
                navigator.blocked = True
                navigator.observe.return_value = '返回位置受阻'
                window._poll_navigation(result, session, object(), frame, None, missing, navigate=True)
                self.assertIsNone(revival.landing_destination)
                self.assertIsNone(window._corpse_trip)
                self.assertIsNone(window._corpse_access)

                navigator.blocked = False
                navigator.observe.return_value = None
                window._poll_navigation(result, session, object(), frame, None, replace(missing, sequence=4), navigate=True)
                self.assertEqual(navigator.observe.call_args.args[2], at)
                self.assertEqual(navigator.observe.call_args.args[3], corpse)
                self.assertIsNot(window._corpse_trip, old_trip)
                mouse.click.assert_not_called()

        with TemporaryDirectory() as directory:
            self.window(directory, exercise, auto_grind=True)

    def test_active_quest_turn_in_survives_missing_and_changed_map_pins(self):
        from dataclasses import replace
        from unittest.mock import Mock
        from wowbuddy.win32.capture import Rect
        from wowbuddy.engine.character_state import CharacterState, NavigationState, QuestDialogState, QuestTurnInPin
        from wowbuddy.automation.navigation import MapDestination
        from wowbuddy.core.old_protocol import OldFrame
        from wowbuddy.engine.pipeline import Decision
        from wowbuddy.automation.quest_turn_in import QuestTurnIn
        from wowbuddy.engine.scheduler import TickResult

        def exercise(window):
            session = 123, 456, 0
            pin = QuestTurnInPin(193, 1433, 30, 57)
            character = CharacterState('alive', True, True, 'alliance', 19, 1433, '赤脊山', pin.x, pin.y)
            position = NavigationState('alive', 1, 1433, pin.x, pin.y, 0, 2170, 1447, (87, 65, 68))
            trip = SimpleNamespace(session=session, complete=True,
                                   goal=MapDestination(pin.map_id, pin.x, pin.y, 'alive', '交付点'))
            progress = QuestDialogState(1, pin.quest_id, 3, True, 0, 0, (2000, 7000), 0, 0)
            frame = OldFrame('ok', values={'target_valid': 'OFF', 'player_in_combat': 'OFF'})
            result = SimpleNamespace(tick=TickResult('no_candidates', Decision(frame, frame.values, (), recovery_ready=True)),
                                     capture=SimpleNamespace(client_rect=Rect(0, 0, 800, 600)))
            window._quest_trip, window._quest_route_scope = trip, (session, pin)
            window._quest_job = QuestTurnIn(pin, progress)
            send = window._send_travel_ui_action = Mock(return_value=True)

            def step(reading, map_pin, now):
                with (patch('wowbuddy.engine.character_state.decode_quest_dialog', return_value=reading),
                      patch('wowbuddy.engine.character_state.decode_quest_turn_in_pin', return_value=map_pin),
                      patch.object(window, 'monotonic_ms', return_value=now)):
                    active = window._observe_quest_route(session, object(), frame, character)
                    if active is not None:
                        window._walk_to_quest(result, session, character, position, active)
                    return active

            self.assertIs(step(progress, None, 1000), trip)
            other = replace(pin, quest_id=999)
            reward = replace(progress, sequence=2, stage=4, button=(3000, 7000))
            self.assertIs(step(reward, other, 1500), trip)
            self.assertEqual([call.args[-2:] for call in send.call_args_list],
                             [('quest_click', (2000, 7000)), ('quest_click', (3000, 7000))])
            self.assertIs(step(replace(reward, sequence=3, receipt_quest=999, receipt_generation=1), other, 1800), trip)
            self.assertFalse(window._quest_job.complete)
            received = replace(reward, sequence=4, stage=0, button=None, hovered=False,
                               receipt_quest=pin.quest_id, receipt_generation=2)
            self.assertIsNone(step(received, other, 2000))
            self.assertTrue(window._quest_job.complete)
            self.assertIsNone(window._quest_trip)
            self.assertEqual(send.call_count, 2)

        with TemporaryDirectory() as directory:
            self.window(directory, exercise, auto_grind=True)

    def test_monitor_retains_completed_camp_route_during_quick_border_return(self):
        from dataclasses import replace
        from unittest.mock import Mock
        from wowbuddy.engine.character_state import CharacterState, DeathState, NavigationState
        from wowbuddy.automation.navigation import MapDestination
        from wowbuddy.core.old_protocol import OldFrame
        from wowbuddy.engine.pipeline import Decision
        from wowbuddy.engine.scheduler import TickResult
        from wowbuddy.automation.walking_route import WalkingTrip, plan_walking_route

        def exercise(window):
            session = (123, 456, 0)
            goal = MapDestination(1429, 40, 66, 'alive', '练级区')
            legs = plan_walking_route(1436, goal.map_id, 18, 'alive')
            trip = WalkingTrip(session, legs, goal, level=18)
            window._leveling_trip = ('alliance', 18, trip)
            planner = window._leveling_planner = Mock()
            planner.observe.return_value = None
            navigator = window._map_navigator = Mock(blocked=False)
            navigator.observe.return_value = None
            frame = OldFrame('ok', values={'target_valid': 'OFF', 'player_in_combat': 'OFF'})
            result = SimpleNamespace(tick=TickResult('no_candidates', Decision(frame, frame.values, (),
                                                                            recovery_ready=True)))
            source = NavigationState('alive', 1, 1436, 62.38, 17.83, 0, 3500, 2333, (87, 65, 68))
            arrived = replace(source, map_id=1429, x=20.23, y=81.08, width=3471, height=2315)

            def poll(position, now):
                zone = '西部荒野' if position.map_id == source.map_id else '艾尔文森林'
                character = CharacterState('alive', True, True, 'alliance', 18, position.map_id, zone,
                                           position.x, position.y)
                death = DeathState('alive', position.sequence, None, False, None)
                with patch.object(window, 'monotonic_ms', return_value=now), \
                     patch('wowbuddy.engine.character_state.decode_navigation_state', return_value=position):
                    window._poll_leveling(session, character, True)
                    window._poll_navigation(result, session, object(), frame, character, death, navigate=True)
                return navigator.observe.call_args.args[3]

            self.assertEqual(poll(source, 100).map_id, source.map_id)
            self.assertIsNone(poll(replace(arrived, sequence=2), 300))
            self.assertEqual(poll(replace(arrived, sequence=3), 550), goal)
            self.assertTrue(trip.complete)
            original_plan = window._leveling_destination

            returned = replace(source, sequence=4, x=62.35, y=17.78)
            self.assertIsNone(poll(returned, 2200))
            self.assertIs(window._leveling_trip[2], trip)
            self.assertIs(window._leveling_destination, original_plan)
            self.assertIsNone(poll(returned, 2450))
            self.assertTrue(trip.complete)
            self.assertIsNone(poll(replace(returned, sequence=5), 2700))
            self.assertEqual(tuple(trip.legs), legs)
            self.assertEqual(poll(replace(returned, sequence=6), 2950).map_id, source.map_id)
            self.assertIsNone(poll(replace(arrived, sequence=7), 3400))
            self.assertEqual(poll(replace(arrived, sequence=8), 3650), goal)
            self.assertEqual(window._leveling_destination, original_plan)
            planner.observe.assert_not_called()

        with TemporaryDirectory() as directory:
            self.window(directory, exercise, auto_grind=True)

    def test_monitor_keeps_a_paused_trip_until_a_new_level_plan_is_ready(self):
        from unittest.mock import Mock
        from wowbuddy.engine.character_state import CharacterState, DeathState, NavigationState
        from wowbuddy.automation.navigation import MapDestination
        from wowbuddy.core.old_protocol import OldFrame
        from wowbuddy.engine.pipeline import Decision
        from wowbuddy.engine.scheduler import TickResult
        from wowbuddy.automation.walking_route import WalkingTrip, plan_walking_route

        def exercise(window):
            session = (123, 456, 0)
            goal = MapDestination(1429, 40, 66, 'alive', '旧练级区')
            trip = WalkingTrip(session, plan_walking_route(1436, goal.map_id, 18, 'alive'), goal, level=18)
            window._leveling_trip = ('alliance', 18, trip)
            planner = window._leveling_planner = Mock()
            planner.observe.return_value = None
            navigator = window._map_navigator = Mock(blocked=False)
            navigator.observe.return_value = None
            def poll(sequence, level, *, target=False):
                position = NavigationState('alive', sequence, 1436, 62.38, 17.83, 0, 3500, 2333, (87, 65, 68))
                character = CharacterState('alive', True, True, 'alliance', level, 1436, '西部荒野',
                                           position.x, position.y)
                death = DeathState('alive', sequence, None, False, None)
                frame = OldFrame('ok', values={'target_valid': 'ON' if target else 'OFF', 'player_in_combat': 'OFF'})
                decision = Decision(frame, frame.values, (), recovery_ready=True, attack_blocked_by_range=target)
                result = SimpleNamespace(tick=TickResult('no_candidates', decision))
                with (patch.object(window, 'monotonic_ms', return_value=sequence * 250),
                      patch('wowbuddy.engine.character_state.decode_navigation_state', return_value=position)):
                    window._poll_leveling(session, character, True)
                    window._poll_navigation(result, session, object(), frame, character, death, navigate=True)
                return navigator.observe.call_args.args[2:4]

            position, waypoint = poll(1, 18)
            self.assertEqual(position.map_id, waypoint.map_id)
            self.assertIsNone(poll(2, 19, target=True)[1])
            self.assertFalse(window._approaching_target)
            self.assertEqual(window._leveling_trip, ('alliance', 18, trip))
            self.assertEqual(poll(3, 18)[1], waypoint)
            self.assertIs(window._leveling_trip[2], trip)

            planner.observe.return_value = {'ok': False, 'error': '模拟断网'}
            self.assertIsNone(poll(4, 19)[1])
            self.assertIs(window._leveling_trip[2], trip)
            planner.observe.return_value = {'ok': True, 'cross_zone': True,
                                            'point': {'zone': '无已核对陆路', 'name': '未接入营地', 'x': 41, 'y': 65}}
            self.assertIsNone(poll(5, 19)[1])
            self.assertIs(window._leveling_trip[2], trip)
            planner.observe.return_value = {'ok': True, 'cross_zone': True,
                                            'point': {'zone': '艾尔文森林', 'name': '新练级区', 'x': 41, 'y': 65}}
            position, waypoint = poll(6, 19)
            replacement = window._leveling_trip[2]
            self.assertIsNot(replacement, trip)
            self.assertEqual((window._leveling_trip[1], replacement.goal.label), (19, '新练级区'))
            self.assertEqual(position.map_id, waypoint.map_id)

        with TemporaryDirectory() as directory:
            self.window(directory, exercise, auto_grind=True)

    def test_corpse_route_rejoins_after_leaving_the_confirmed_corpse_map(self):
        from dataclasses import replace
        from unittest.mock import Mock
        from wowbuddy.engine.character_state import DeathState, NavigationState
        from wowbuddy.core.old_protocol import OldFrame
        from wowbuddy.engine.pipeline import Decision
        from wowbuddy.engine.scheduler import TickResult

        def exercise(window):
            session = (123, 456, 0)
            corpse = (1429, 40, 66)
            origin = NavigationState('ghost', 1, 1436, 58, 26, 0, 1000, 800, (87, 65, 68))
            arrived = replace(origin, map_id=corpse[0], x=18.3, y=82.4)
            frame = OldFrame('ok', values={'player_in_combat': 'OFF'})
            result = SimpleNamespace(tick=TickResult('no_candidates', Decision(frame, frame.values, ())))
            navigator = window._map_navigator = Mock(blocked=False)
            navigator.observe.return_value = None

            def poll(position):
                with patch('wowbuddy.engine.character_state.decode_navigation_state', return_value=position):
                    window._poll_navigation(result, session, object(), frame, None,
                        DeathState('ghost', position.sequence, None, False, corpse, 'missing'), navigate=True)
                return navigator.observe.call_args.args[3]

            self.assertEqual(poll(origin).map_id, origin.map_id)
            self.assertIsNone(poll(replace(arrived, sequence=2)))
            self.assertEqual(poll(replace(arrived, sequence=3)).map_id, corpse[0])
            self.assertTrue(window._corpse_trip.complete)

            off_map = replace(origin, sequence=4)
            self.assertIsNone(poll(off_map))
            self.assertIsNone(poll(off_map))
            self.assertEqual(poll(replace(arrived, sequence=5)).map_id, corpse[0])
            self.assertIsNone(poll(replace(off_map, sequence=6)))
            self.assertIsNone(poll(replace(off_map, sequence=7)))
            waypoint = poll(replace(off_map, sequence=8))
            self.assertEqual(waypoint.map_id, off_map.map_id)
            self.assertFalse(window._corpse_trip.complete)
            self.assertIsNone(poll(replace(arrived, sequence=9)))
            self.assertEqual(poll(replace(arrived, sequence=10)).map_id, corpse[0])
            self.assertEqual((window._corpse_trip.goal.x, window._corpse_trip.goal.y), corpse[1:])

        with TemporaryDirectory() as directory:
            self.window(directory, exercise, auto_grind=True)

    def test_revival_rejoins_the_camp_road_after_recovery(self):
        from dataclasses import replace
        from unittest.mock import Mock
        from wowbuddy.engine.character_state import CharacterState, DeathState, NavigationState
        from wowbuddy.automation.navigation import MapDestination
        from wowbuddy.core.old_protocol import OldFrame
        from wowbuddy.engine.pipeline import Decision
        from wowbuddy.engine.scheduler import TickResult

        def exercise(window):
            session = (123, 456, 0)
            character = CharacterState('alive', True, True, 'alliance', 18, 1433, '赤脊山', 23.30, 76.70)
            camp = MapDestination(1433, 23.25, 79.41, 'alive', '赤脊山偷猎者营地')
            position = NavigationState('alive', 1, 1433, character.x, character.y, 0, 2171, 1448, (87, 65, 68))
            popup = DeathState('alive', 1, None, False, None)
            frame = OldFrame('ok', values={'target_valid': 'OFF', 'player_in_combat': 'OFF'})
            navigator = window._map_navigator = Mock(blocked=False)
            navigator.observe.return_value = None
            window._leveling_destination = session, character.route_key, camp
            window._post_revival_session = session

            def poll(recovered, sample):
                tick = TickResult('no_candidates', Decision(frame, frame.values, (), recovery_ready=recovered))
                with patch('wowbuddy.engine.character_state.decode_navigation_state', return_value=sample):
                    window._poll_navigation(SimpleNamespace(tick=tick), session, object(), frame,
                                            character, popup, navigate=True)
                return navigator.observe.call_args.args[2:4]

            self.assertIsNone(poll(False, position)[0])
            self.assertIsNone(getattr(window, '_leveling_trip', None))
            self.assertIsNone(poll(True, None)[0])
            self.assertEqual(window._post_revival_session, session)
            self.assertIsNone(poll(True, replace(position, moving=True))[0])
            self.assertEqual(window._post_revival_session, session)
            _, waypoint = poll(True, position)
            trip = window._leveling_trip[2]
            self.assertIsNone(window._post_revival_session)
            self.assertEqual(trip.goal, camp)
            self.assertIs(navigator.observe.call_args.kwargs['path'], trip)
            self.assertNotEqual(waypoint, camp)
            passed = []
            for sequence in range(2, 25):
                passed.append(waypoint)
                position = replace(position, sequence=sequence, x=waypoint.x, y=waypoint.y)
                _, waypoint = poll(True, position)
                if trip.complete:
                    break
            detour = [(point.x, point.y) for point in passed if not point.allow_detour]
            self.assertIn((23.05, 77.8), detour)
            self.assertIn((23.02, 78.55), detour)
            self.assertTrue(trip.complete)
            self.assertEqual(window._leveling_destination, (session, character.route_key, camp))

        with TemporaryDirectory() as directory:
            self.window(directory, exercise, auto_grind=True)

    def test_revival_rejoins_a_marked_camp_road_or_retires_the_unreachable_plan(self):
        from dataclasses import replace
        from wowbuddy.engine.character_state import CharacterState, NavigationState
        from wowbuddy.automation.manual_routes import parse_fixed_camp, parse_manual_route
        from wowbuddy.automation.navigation import MapDestination
        from wowbuddy.automation.walking_route import WalkingTrip

        route_text = 'WBDROUTE1|1429|3900,6500|3950,6500|3950,6630|4210,6630'
        marked = parse_manual_route(route_text)

        def exercise(window):
            session = (123, 456, 0)
            x, y = (38.8, 69.5) if off_road else (39.25, 65)
            character = CharacterState('alive', True, True, 'alliance', 18, 1429, '艾尔文森林', x, y)
            position = NavigationState('alive', 1, 1429, x, y, 0, 3470, 2314, (87, 65, 68))
            camp = MapDestination(1429, *marked.endpoint, 'alive', '固定打怪点' if fixed else '原营地')
            catalog = MapDestination(1429, 42.0, 66.3, 'alive', '原营地')
            if fixed:
                window._fixed_camp_route = parse_fixed_camp(route_text)
                window._poll_fixed_camp(session, character)
                catalog = camp
            else:
                window.settings.save_manual_routes([route_text])
            plan = session, character.route_key, camp
            window._leveling_destination = plan
            completed = WalkingTrip(session, (), camp, level=18, catalog_goal=catalog)
            window._leveling_trip = 'alliance', 18, completed
            if fixed and off_road:
                self.assertFalse(window._rejoin_camp_after_revival(session, character, position))
                window._poll_leveling(session, character, True)
                self.assertEqual(window._leveling_destination, plan)
                self.assertIs(window._leveling_trip[2], completed)
                position = replace(position, sequence=2, x=39.25, y=65)
                character = replace(character, x=position.x, y=position.y)
                window._poll_leveling(session, character, True)
            self.assertTrue(window._rejoin_camp_after_revival(session, character, position))
            self.assertIsNone(window._leveling_destination)
            if off_road and not fixed:
                self.assertIsNone(window._leveling_trip)
                planner = window._leveling_planner
                excluded = planner._camp_exclusions(session, character, window.monotonic_ms())
                self.assertIn(('艾尔文森林', catalog.x, catalog.y), excluded)
            else:
                trip = window._leveling_trip[2]
                self.assertIsNot(trip, completed)
                self.assertEqual(trip.catalog_goal, catalog)
                self.assertTrue(trip.manual_camp_pending)
                target, _ = trip.observe(position)
                self.assertEqual((target.x, target.y), marked.points[1])

        for fixed, off_road in ((False, False), (False, True), (True, False), (True, True)):
            with self.subTest(fixed=fixed, off_road=off_road), TemporaryDirectory() as directory:
                self.window(directory, exercise, auto_grind=True)

    def test_reviving_and_waiting_to_rejoin_gate_attacks_before_the_scheduler_runs(self):
        def exercise(window):
            window.session.start(123)
            session = (123, window.session.state.elapsed_started_ms, window._unattended_revision)
            observed = []

            def poll():
                observed.append(window.pipeline.unattended_travel)
                return PollResult('capture_failed')

            with (patch.object(AssistantWindow, 'poll_once', side_effect=poll),
                  patch.object(window, '_poll_revival'), patch.object(window, '_poll_navigation'),
                  patch.object(window, '_pause_navigation_feedback')):
                window._automatic_revival = SimpleNamespace(session=None, life='ghost')
                window.poll_once()
                window._automatic_revival.session = session
                window.poll_once()
                window._automatic_revival.life = 'alive'
                window._post_revival_session = session
                window.poll_once()
                window._post_revival_session = None
                window.poll_once()
            self.assertEqual(observed, [False, True, True, False])

        with TemporaryDirectory() as directory:
            self.window(directory, exercise, auto_grind=True)

    def test_revival_off_the_camp_road_retires_the_old_destination(self):
        from concurrent.futures import Future
        from dataclasses import replace
        from unittest.mock import Mock
        from wowbuddy.engine.character_state import CharacterState, DeathState, NavigationState
        from wowbuddy.automation.navigation import MapDestination
        from wowbuddy.core.old_protocol import OldFrame
        from wowbuddy.engine.pipeline import Decision
        from wowbuddy.engine.scheduler import TickResult
        from wowbuddy.automation.walking_route import camp_access_road

        def exercise(window):
            session = (123, 456, 0)
            character = CharacterState('alive', True, True, 'alliance', 18, 1433, '赤脊山', 32, 74)
            camp = MapDestination(1433, 23.25, 79.41, 'alive', '赤脊山偷猎者营地')
            position = NavigationState('alive', 1, 1433, character.x, character.y, 0, 2171, 1448, (87, 65, 68))
            self.assertTrue(camp_access_road(camp))
            self.assertFalse(camp_access_road(camp, origin=position))
            death = DeathState('alive', 1, None, False, None)
            frame = OldFrame('ok', values={'target_valid': 'OFF', 'player_in_combat': 'OFF'})
            decision = Decision(frame, frame.values, (), recovery_ready=True)
            result = SimpleNamespace(tick=TickResult('no_candidates', decision))
            navigator = window._map_navigator = Mock(blocked=False)
            navigator.observe.return_value = None
            window._leveling_destination = session, character.route_key, camp
            window._post_revival_session = session
            window._leveling_camps = [{'zone': '赤脊山', 'name': '另一处旧候选', 'x': 30.55, 'y': 57.1}]

            def poll(sample):
                with patch('wowbuddy.engine.character_state.decode_navigation_state', return_value=sample):
                    window._poll_navigation(result, session, object(), frame, character, death, navigate=True)
                return navigator.observe.call_args.args[2:4]

            self.assertIsNone(poll(replace(position, map_id=1429))[0])
            self.assertEqual(window._post_revival_session, session)
            submit = Mock(return_value=Future())
            with (patch('concurrent.futures.ThreadPoolExecutor', return_value=Mock(submit=submit)),
                  patch.object(window, 'monotonic_ms', return_value=1000) as clock):
                self.assertIsNone(poll(replace(position, sequence=2))[1])
                self.assertIsNone(window._leveling_destination)
                self.assertIsNone(window._post_revival_session)
                window._poll_leveling(session, character, True)
                clock.return_value = 1300
                window._poll_leveling(session, character, True)
            submit.assert_called_once()
            self.assertEqual(submit.call_args.args[1:6], ('alliance', 18, '赤脊山', position.x, position.y))
            self.assertIn(('赤脊山', camp.x, camp.y), submit.call_args.kwargs['excluded'])

        with TemporaryDirectory() as directory:
            self.window(directory, exercise, auto_grind=True)

    def test_revival_in_crossing_entry_resumes_from_the_verified_road(self):
        from concurrent.futures import Future
        from dataclasses import replace
        from unittest.mock import Mock
        from wowbuddy.engine.character_state import CharacterState, DeathState, NavigationState
        from wowbuddy.automation.manual_routes import parse_manual_connection
        from wowbuddy.automation.navigation import MapDestination
        from wowbuddy.core.old_protocol import OldFrame
        from wowbuddy.engine.pipeline import Decision
        from wowbuddy.engine.scheduler import TickResult
        from wowbuddy.automation.walking_route import WalkingTrip

        connection = 'WBDROUTE1|1436|6010,2050|6100,2000\nWBDROUTE1|1429|2418,7835|2476,7862'
        leg = parse_manual_connection(connection)
        entry = leg.arrival_road
        camp = MapDestination(1429, 28.2, 78.8, 'alive', '原营地')
        frame = OldFrame('ok', values={'target_valid': 'OFF', 'player_in_combat': 'OFF'})

        def exercise(window):
            session = (123, 456, 0)
            first = NavigationState('alive', 1, 1429, *entry[0], 0, 3470, 2314, (87, 65, 68))
            trip = WalkingTrip(session, (leg,), camp, level=18, faction='alliance', catalog_zone='艾尔文森林')
            trip.observe(first)
            trip.observe(replace(first, sequence=2))
            self.assertEqual(trip.arrival_connection, leg)
            window._leveling_trip = 'alliance', 18, trip
            trip.resume_after_revival()
            window._post_revival_session = session
            navigator = window._map_navigator = Mock(blocked=False)
            navigator.observe.return_value = None
            position = replace(first, sequence=3, x=30 if off_road else 24.47, y=78.485)
            character = CharacterState('alive', True, True, 'alliance', 18, 1429, '艾尔文森林',
                                       position.x, position.y)
            death = DeathState('alive', 3, None, False, None)

            def poll(sample, *, recovered=True):
                decision = Decision(frame, frame.values, (), recovery_ready=recovered)
                result = SimpleNamespace(tick=TickResult('no_candidates', decision))
                with patch('wowbuddy.engine.character_state.decode_navigation_state', return_value=sample):
                    window._poll_navigation(result, session, object(), frame, character, death, navigate=True)
                return navigator.observe.call_args.args[3]

            self.assertIsNone(poll(position, recovered=False))
            self.assertIsNone(poll(None))
            self.assertIsNone(poll(replace(position, moving=True)))
            if off_road:
                submit = Mock(return_value=Future())
                with (patch('concurrent.futures.ThreadPoolExecutor', return_value=Mock(submit=submit)),
                      patch.object(window, 'monotonic_ms', return_value=1000) as clock):
                    self.assertIsNone(poll(replace(position, sequence=4)))
                    window._poll_leveling(session, character, True)
                    clock.return_value = 1300
                    window._poll_leveling(session, character, True)
                submit.assert_called_once()
                self.assertEqual(submit.call_args.args[1:6], ('alliance', 18, '艾尔文森林', position.x, position.y))
                self.assertIn(('艾尔文森林', camp.x, camp.y), submit.call_args.kwargs['excluded'])
                self.assertIsNone(window._leveling_trip)
                self.assertFalse(checkpoint.exists())
            else:
                target = poll(replace(position, sequence=4))
                self.assertEqual((target.x, target.y), entry[-1])
                self.assertIs(window._leveling_trip[2], trip)

        for off_road in (False, True):
            with self.subTest(off_road=off_road), TemporaryDirectory() as directory:
                checkpoint = Path(directory)/'leveling-travel.json'
                checkpoint.write_text('{}', 'utf8')
                self.window(directory, exercise, auto_grind=True)

    def test_blocked_final_corpse_road_uses_probes_only_near_the_body_on_open_road(self):
        from dataclasses import replace
        from math import hypot
        from unittest.mock import Mock
        from wowbuddy.engine.character_state import DeathState, NavigationState
        from wowbuddy.automation.navigation import MapDestination
        from wowbuddy.core.old_protocol import OldFrame
        from wowbuddy.engine.pipeline import Decision
        from wowbuddy.engine.scheduler import TickResult
        from wowbuddy.automation.walking_route import WalkingTrip

        def exercise(window):
            corpse = (1432, 50, 50)
            goal = MapDestination(*corpse, 'ghost', '尸体')
            frame = OldFrame('ok', values={'player_in_combat': 'OFF'})
            result = SimpleNamespace(tick=TickResult('no_candidates', Decision(frame, frame.values, ())))
            navigator = window._map_navigator = Mock()
            camp = Mock()
            window._advance_grind_camp = camp

            for session_id, (x, narrow) in enumerate(((48.4, False), (45, False), (48.4, True)), 1):
                with self.subTest(x=x, narrow=narrow):
                    session = (123, session_id, 0)
                    position = NavigationState('ghost', 1, 1432, x, 50, 0, 1000, 800, (87, 65, 68))
                    trip = window._corpse_trip = WalkingTrip(session, (), goal, camp_road=((49.9, 49), (50, 50)))
                    popup = DeathState('ghost', 1, None, False, corpse, 'missing')

                    def poll(sample, state):
                        with patch('wowbuddy.engine.character_state.decode_navigation_state', return_value=sample), \
                             patch('wowbuddy.automation.walking_route._on_loch_dam', return_value=narrow):
                            window._poll_navigation(result, session, object(), frame, None, state, navigate=True)
                        return navigator.observe.call_args.args[3]

                    navigator.blocked = True
                    navigator.observe.return_value = '接入路点受阻'
                    waypoint = poll(position, popup)
                    self.assertIs(navigator.observe.call_args.kwargs['path'], trip)
                    self.assertIs(waypoint.allow_detour, not narrow)
                    navigator.observe.return_value = None
                    sample = replace(position, sequence=2)
                    destination = poll(sample, replace(popup, sequence=2))
                    if x == 48.4 and not narrow:
                        self.assertTrue(trip.complete)
                        self.assertIsNone(navigator.observe.call_args.kwargs['path'])
                        self.assertAlmostEqual(hypot(*destination.offset_from(replace(sample, x=50))), 16)
                        poll(sample, replace(popup, sequence=3, popup='disabled'))
                        self.assertIsNone(navigator.observe.call_args.args[2])
                        self.assertEqual(poll(sample, replace(popup, sequence=4)), destination)
                    else:
                        self.assertFalse(trip.complete)
                        self.assertEqual(destination, waypoint)
            camp.assert_not_called()

        with TemporaryDirectory() as directory:
            self.window(directory, exercise, auto_grind=True)

    def test_blocked_travel_replans_through_the_running_monitor(self):
        from unittest.mock import Mock
        from wowbuddy.engine.character_state import CharacterState, DeathState, NavigationState
        from wowbuddy.automation.leveling_route import AutomaticLeveling
        from wowbuddy.automation.navigation import MapDestination
        from wowbuddy.core.old_protocol import OldFrame
        from wowbuddy.engine.pipeline import Decision
        from wowbuddy.engine.scheduler import TickResult
        from wowbuddy.automation.walking_route import WalkingTrip, plan_walking_route

        def exercise(window):
            session = (123, 456, 0)
            window._character_session = (session[:2], 42)
            window._character_travel_identity = window._character_session, (15, 16)
            for life in ('alive', 'ghost'):
                with self.subTest(life=life):
                    legs = plan_walking_route(1436, 1433, 22, life)
                    goal = MapDestination(1433, 25.5, 59.4, life, '目的地' if life == 'alive' else '尸体')
                    trip = WalkingTrip(session, legs, goal, level=22)
                    position = NavigationState(life, 1, 1436, *legs[0].points[0], 0, 1000, 1000, (87, 65, 68))
                    character = None
                    corpse = None
                    if life == 'alive':
                        character = CharacterState(life, True, True, 'alliance', 22, 1436, '西部荒野',
                                                   position.x, position.y)
                        window._leveling_trip = 'alliance', 22, trip
                        window._save_leveling_travel(session, character, trip)
                        self.assertEqual(json.loads(checkpoint.read_text('utf8'))['walking_maps'], [1436, 1429, 1433])
                    else:
                        window._corpse_trip = trip
                        corpse = goal.map_id, goal.x, goal.y
                    death = DeathState(life, 1, None, False, corpse)
                    frame = OldFrame('ok', values={'target_valid': 'OFF', 'player_in_combat': 'OFF'})
                    result = SimpleNamespace(tick=TickResult('no_candidates', Decision(
                        frame, frame.values, (), recovery_ready=life == 'alive')))
                    navigator = window._map_navigator = Mock(blocked=True)
                    navigator.observe.return_value = '路段受阻'
                    with patch('wowbuddy.engine.character_state.decode_navigation_state', return_value=position):
                        window._poll_navigation(result, session, object(), frame, character, death, navigate=True)
                    self.assertIs(navigator.observe.call_args.kwargs['path'], trip)
                    self.assertEqual([leg.destination for leg in trip.legs], [1431, 1433])
                    self.assertEqual(trip.goal, goal)
            saved = json.loads(checkpoint.read_text('utf8'))
            self.assertEqual(saved['walking_maps'], [1436, 1431, 1433])
            original_leg = plan_walking_route(1436, 1433, 22, 'alive')[0]
            self.assertEqual(saved['blocked_connections'], [list(original_leg.blocked_key)])

        def restart(window, *, legacy=False):
            session = (124, 457, 0)
            window._character_session = (session[:2], 43)
            window._character_travel_identity = window._character_session, (15, 16)
            submit = Mock()
            window._leveling_planner = AutomaticLeveling(submit)
            character = CharacterState('alive', True, True, 'alliance', 22, 1431, '暮色森林', 67, 45)
            window._poll_leveling(session, character, True)
            submit.assert_not_called()
            trip = window._leveling_trip[2]
            self.assertEqual([leg.destination for leg in trip.legs], [1433])
            self.assertEqual((trip.goal.x, trip.goal.y), (25.5, 59.4))
            original_leg = plan_walking_route(1436, 1433, 22, 'alive')[0]
            self.assertEqual(trip.excluded_legs, set() if legacy else {original_leg})

        with TemporaryDirectory() as directory:
            checkpoint = Path(directory)/'leveling-travel.json'
            self.window(directory, exercise, auto_grind=True)
            self.window(directory, restart, auto_grind=True)
            saved = json.loads(checkpoint.read_text('utf8'))
            saved['blocked_connections'] = [key[:7] for key in saved['blocked_connections']]
            checkpoint.write_text(json.dumps(saved), 'utf8')
            self.window(directory, lambda window: restart(window, legacy=True), auto_grind=True)

    def test_local_addon_pin_survives_restart_without_disabling_manual_download(self):
        def default(window):
            self.assertTrue(window.addon_startup_timer.isActive())
            self.assertTrue(window._addon_online)

        def pinned(window):
            self.assertFalse(window.addon_startup_timer.isActive())
            self.assertFalse(window._addon_online)
            window._periodic_library_refresh()
            self.assertFalse(window._addon_download_busy())
            self.assertTrue(window.ui.addon_detect_button.isEnabled())

        with TemporaryDirectory() as directory:
            self.window(directory,default,addon_online=True)
            from wowbuddy.settings import open_ini_settings
            settings=open_ini_settings(str(Path(directory)/'settings.ini'))
            settings.qsettings.setValue('addon/autoUpdate',False)
            settings.sync()
            self.window(directory,pinned,addon_online=True)
            self.window(directory,pinned,addon_online=True)

    def identify(self,window,spec):
        frame=window.controller.prepare(render_old(spec)[0]).frame
        self.assertTrue(frame.ok,frame.status)
        window._render_selection()

    def test_intervals_reset_but_auto_update_preference_survives(self):
        def first(window):
            window.poll_timer.start()
            window.ui.poll_interval_spin.setValue(80)
            window.ui.send_interval_spin.setValue(350)
            self.assertTrue(window.poll_timer.isActive())
            self.assertEqual(window.poll_timer.interval(),80)
            self.assertEqual(window.loop.send_interval_ms(),350)
            window.poll_timer.stop()
            window.ui.auto_update_check.setChecked(False)
            window.ui.show_all_check.setChecked(True)
        def second(window):
            self.assertEqual(window.ui.poll_interval_spin.value(),25)
            self.assertEqual(window.ui.send_interval_spin.value(),100)
            self.assertEqual(window.poll_timer.interval(),25)
            self.assertFalse(window.ui.auto_update_check.isChecked())
            self.assertFalse(window.ui.show_all_check.isChecked())
        with TemporaryDirectory() as directory:
            self.window(directory,first)
            self.window(directory,second)

    def test_every_snapshot_profile_and_threshold_group_restores(self):
        profiles=json.loads((ROOT/'assets/rotations.json').read_text('utf8'))['rotations']
        checked_profiles=0;checked_groups=0;persisted_expected={}
        with TemporaryDirectory() as root:
            for ordinal,profile in enumerate(profiles):
                spec=profile['specId'];saved={};selected=[]
                directory=str(Path(root)/str(ordinal))
                def first(window):
                    nonlocal checked_groups
                    self.identify(window,spec)
                    matching=[i for i in range(1,window.ui.rotation_combo.count())
                              if window.ui.rotation_combo.itemData(i)==
                              f"{spec}|{profile['subKey']}|{profile['profileName']}"]
                    self.assertTrue(matching,profile['profileName'])
                    # 原选择键不含ID；重名条目仍按快照首项恢复。
                    window.ui.rotation_combo.setCurrentIndex(matching[-1] if profile['id']==131 else matching[0])
                    selected.append(window.ui.rotation_combo.currentData())
                    self.assertEqual(window.controller.selection.active_profile.key,selected[0])
                    first_match=next(p for p in profiles if (p['specId'],p['subKey'],p['profileName'])==
                                     (spec,profile['subKey'],profile['profileName']))
                    self.assertEqual(window.controller.selection.active_profile.id,first_match['id'])
                    self.assertEqual(len(window.threshold_panel.rows),len(window.controller.groups))
                    for index,(row,group) in enumerate(zip(window.threshold_panel.rows,window.controller.groups)):
                        for value in (0,row.slider.maximum(),0):
                            row.slider.setValue(value)
                            for key in group.keys:
                                self.assertEqual(window.controller.switch_settings[key],value)
                        final=row.slider.maximum() if index%2 else 0
                        row.slider.setValue(final)
                        saved[group.keys]=final
                        checked_groups+=1
                def second(window):
                    self.identify(window,spec)
                    self.assertEqual(window.controller.selection.active_profile.key,selected[0])
                    self.assertEqual(window.ui.rotation_combo.currentData(),selected[0])
                    self.assertEqual(set(saved),{group.keys for group in window.controller.groups})
                    for row,group in zip(window.threshold_panel.rows,window.controller.groups):
                        self.assertEqual(row.slider.value(),saved[group.keys])
                        for key in group.keys:
                            self.assertEqual(window.controller.switch_settings[key],saved[group.keys])
                with self.subTest(profile=profile['profileName'],spec=spec):
                    self.window(directory,first)
                    self.window(directory,second)
                    persisted_expected[str(ordinal)]={'hub/by-spec/'+str(spec):selected[0],
                        **{'switch/'+key:value for keys,value in saved.items() for key in keys}}
                    checked_profiles+=1
            script="from PySide6.QtCore import QSettings; import sys,json; from pathlib import Path; result={}; root=Path(sys.argv[1]); exec('for p in root.iterdir():\\n q=QSettings(str(p/\"settings.ini\"),QSettings.IniFormat)\\n result[p.name]={k:q.value(k) for k in q.allKeys()}'); print(json.dumps(result))"
            loaded=subprocess.run([sys.executable,'-c',script,root],capture_output=True,timeout=15)
            self.assertEqual(loaded.returncode,0,loaded.stderr)
            actual=json.loads(loaded.stdout)
            for ordinal,values in persisted_expected.items():
                for key,value in values.items():
                    got=actual[ordinal][key]
                    self.assertEqual(int(got) if key.startswith('switch/') else got,value)
            self.assertEqual(checked_profiles,41)
            self.assertGreater(checked_groups,41)
            print(f'方案条目={checked_profiles}，唯一选择键=40，阈值组检查={checked_groups}')

    def test_saved_profiles_restore_on_fresh_start_and_preserve_native_switch_edge(self):
        selected={};disabled={}
        specs=(1482,1484,1485,1486,1487,1488,1489,1490,1491)
        def first(window):
            for spec in specs:
                self.identify(window,spec)
                self.assertGreater(window.ui.rotation_combo.count(),1)
                window.ui.rotation_combo.setCurrentIndex(1)
                selected[spec]=window.ui.rotation_combo.currentData()
                self.assertEqual(window.controller.selection.active_profile.key,selected[spec])
                self.assertTrue(window.threshold_panel.rows)
                group=window.controller.groups[0]
                window.threshold_panel.rows[0].slider.setValue(0)
                disabled[spec]=group.keys
                for key in group.keys:
                    self.assertEqual(window.settings._read('switch/'+key,-1,'integer'),0)
        def second(window,spec):
            self.assertIsNone(window.controller.selection.active_profile)
            self.identify(window,spec)
            self.assertEqual(window.ui.rotation_combo.currentData(),selected[spec])
            self.assertEqual(window.controller.selection.active_profile.key,selected[spec])
            for key in disabled[spec]:
                self.assertEqual(window.controller.switch_settings[key],0)
            group_index=next(i for i,g in enumerate(window.controller.groups) if g.keys==disabled[spec])
            self.assertEqual(window.threshold_panel.rows[group_index].slider.value(),0)
        def live_switch(window):
            second(window,1482)
            self.identify(window,1484)
            # 原0999f0优先旧current，失配不回退pending；不擅自修复原行为。
            self.assertEqual(window.ui.rotation_combo.currentData(),'')
            self.assertEqual(window.controller.selection.pending_key,'')
            self.assertIsNone(window.controller.selection.active_profile)
            self.assertEqual(window.settings.load_spec_selection('1484'),selected[1484])
        with TemporaryDirectory() as directory:
            self.window(directory,first)
            # 独立进程读取落盘INI，避免仅由同进程QSettings缓存证明持久化。
            script="from PySide6.QtCore import QSettings; import sys,json; from pathlib import Path; q=QSettings(str(Path(sys.argv[1])/'settings.ini'),QSettings.IniFormat); print(json.dumps({k:q.value(k) for k in q.allKeys()}))"
            loaded=subprocess.run([sys.executable,'-c',script,directory],capture_output=True,timeout=15)
            self.assertEqual(loaded.returncode,0,loaded.stderr)
            persisted=json.loads(loaded.stdout)
            for spec in specs:
                self.assertEqual(persisted['hub/by-spec/'+str(spec)],selected[spec])
                for key in disabled[spec]:self.assertEqual(int(persisted['switch/'+key]),0)
            for spec in specs:
                self.window(directory,lambda window:second(window,spec))
            self.window(directory,live_switch)


if __name__=='__main__':unittest.main()
