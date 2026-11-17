"""循环打怪：边走边找怪、路点少转圈（docs/design/20261117-patrol-scan.md）。"""
from dataclasses import replace
import math
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'desktop'), str(ROOT / 'tests')]

from wowbuddy.automation.arrival_pull import ArrivalPull  # noqa: E402
from wowbuddy.automation.navigation import MapDestination  # noqa: E402
from wowbuddy.core.old_protocol import OldFrame  # noqa: E402
from wowbuddy.engine.character_state import NavigationState  # noqa: E402
from wowbuddy.engine.pipeline import Decision  # noqa: E402
from wowbuddy.engine.scheduler import TickResult  # noqa: E402
from test_leveling_route import PACKET_BASE  # noqa: E402


def tick(*, target='OFF', combat='OFF', ack=0, ready=True, rejection=None, gate=0, far=False, health=100, mana=100):
    fields = {'ttd': str(PACKET_BASE + 8192 + 1024 * gate + 32 * ack + 1), 'target_valid': target,
              'player_valid': 'ON', 'player_in_combat': combat, 'distance': '37.5' if far else '17.5',
              'player_health_pct': str(health), 'mana_pct': str(mana)}
    frame = OldFrame('ok', values=fields)
    return TickResult('stopped', Decision(frame, fields, (), recovery_ready=ready, target_rejection=rejection,
                                          attack_blocked_by_range=far),
                      display_now_ms=10_000)


POSITION = NavigationState('alive', 0, 1433, 30.0, 30.0, 0, 2171, 1448, (87, 65, 68), 1, continuous=True,
                           moving=True)


class TravelScanTests(unittest.TestCase):
    """R1：循环行走中每 2.5 秒按一次选怪键；不满足条件时不按。"""

    def setUp(self):
        from wowbuddy.automation.patrol_scan import TravelScan
        self.dispatcher = Mock()
        self.dispatcher.state.last_sent_ms = 0
        self.dispatcher.dispatch.return_value.success = True
        self.scan = TravelScan(self.dispatcher)
        self.session = (10, 1)

    def step(self, now, *, segment=0, walking=True, **kwargs):
        return self.scan.observe(self.session, (self.session, segment), walking=walking, position=POSITION,
                                 tick=tick(**kwargs), now_ms=now, send_interval_ms=100)

    def test_presses_every_interval_while_walking(self):
        for now in range(0, 6001, 250):
            self.step(now)
        self.assertEqual(self.dispatcher.dispatch.call_count, 3)       # 0、2500、5000
        candidate = self.dispatcher.dispatch.call_args.args[0]
        self.assertEqual(candidate.action, 'auto_target')
        self.assertTrue(self.scan.scanned((self.session, 0)))
        self.assertFalse(self.scan.scanned((self.session, 1)))

    def test_no_press_when_not_walking_in_combat_with_target_or_recovering(self):
        # 2026-11-17 01:12：血量 71% 时行走中开怪，连拉 4 只死亡；行走中只在血量与法力充足时找怪。
        for kwargs in (dict(walking=False), dict(combat='ON'), dict(target='ON'), dict(ready=False),
                       dict(health=79), dict(mana=49)):
            with self.subTest(**kwargs):
                self.setUp()
                for now in range(0, 6001, 250):
                    self.step(now, **kwargs)
                self.dispatcher.dispatch.assert_not_called()

    def test_selected_target_engages_until_combat_ends(self):
        self.step(0)
        self.assertEqual(self.step(400, target='ON'), '行走中选到目标，停下交战')
        self.assertTrue(self.scan.engaged_for(self.session))
        self.assertIsNone(self.step(800, target='ON', combat='ON'))
        self.assertIsNone(self.step(5000, target='OFF', combat='ON'))
        self.assertIsNone(self.step(5500, target='OFF'))
        self.assertTrue(self.scan.engaged_for(self.session))           # 等 1.5 秒确认脱战
        self.assertEqual(self.step(7100, target='OFF'), '途中交战结束')
        self.assertFalse(self.scan.engaged_for(self.session))
        self.assertEqual(self.scan.rejections, 0)
        self.dispatcher.dispatch.reset_mock()
        self.step(7200)
        self.assertEqual(self.dispatcher.dispatch.call_count, 1)        # 继续行走找怪

    def test_targets_that_never_fight_count_as_rejections_and_stop_after_three(self):
        now = 0
        for _ in range(3):
            self.step(now)
            self.step(now + 300, target='ON')
            self.step(now + 600, target='OFF')
            self.assertIn('未能开始战斗', self.step(now + 2200, target='OFF'))
            now += 3000
        self.assertEqual(self.scan.rejections, 3)
        self.dispatcher.dispatch.reset_mock()
        for t in range(now, now + 6000, 250):
            self.step(t)
        self.dispatcher.dispatch.assert_not_called()
        # 换下一段后重新开始
        self.step(now + 7000, segment=1)
        self.assertEqual(self.dispatcher.dispatch.call_count, 1)

    def test_engagement_times_out_without_combat(self):
        self.step(0)
        self.step(300, target='ON')
        self.assertIsNone(self.step(20_000, target='ON'))
        self.assertIn('30 秒', self.step(30_400, target='ON'))
        self.assertFalse(self.scan.engaged_for(self.session))

    def test_out_of_range_target_keeps_walking_until_it_comes_into_range(self):
        # 2026-11-17 01:11：选到 37.5 码外的怪，经典版没有怪物方位、无法接近，停下等了 25 秒后放弃又重选。
        self.step(0)
        self.assertIsNone(self.step(400, target='ON', far=True))
        self.assertFalse(self.scan.engaged_for(self.session))
        for now in range(500, 6000, 250):
            self.assertIsNone(self.step(now, target='ON', far=True))
        self.assertEqual(self.dispatcher.dispatch.call_count, 1)        # 已有目标时不再按选怪键
        self.assertEqual(self.step(6250, target='ON'), '行走中选到目标，停下交战')
        self.assertTrue(self.scan.engaged_for(self.session))

    def test_out_of_range_target_lost_allows_new_press(self):
        self.step(0)
        self.step(400, target='ON', far=True)
        self.step(3000)
        self.assertEqual(self.dispatcher.dispatch.call_count, 2)
        self.assertEqual(self.scan.rejections, 0)

    def test_no_selection_within_wait_allows_next_press(self):
        self.step(0)
        self.assertIsNone(self.step(2100))
        self.assertFalse(self.scan.engaged_for(self.session))
        self.step(2600)
        self.assertEqual(self.dispatcher.dispatch.call_count, 2)


class ArrivalPullSectorTests(unittest.TestCase):
    """R2：开关打开且本段已边走边找时，路点只扫正前、左、右三个方向。"""

    def setUp(self):
        self.session = (10, 1)
        self.dispatcher = Mock()
        self.dispatcher.state.last_sent_ms = 0
        self.dispatcher.dispatch.return_value.success = True
        self.foreground = Mock()
        self.pull = ArrivalPull(self.dispatcher, self.foreground)
        self.position = NavigationState('alive', 0, 52, 32.12, 36.15, 0, 1000, 800, (87, 65, 68), 1,
                                        continuous=True)
        self.destination = MapDestination(52, 32.12, 36.15, 'alive', '练级据点')

    def step(self, sequence, now, *, ack=0, heading=0):
        fields = {'ttd': str(PACKET_BASE + 8192 + 32 * ack + 1), 'target_valid': 'OFF', 'player_valid': 'ON',
                  'player_in_combat': 'OFF'}
        frame = OldFrame('ok', values=fields)
        result = TickResult('stopped', Decision(frame, fields, (), recovery_ready=True), display_now_ms=10_000)
        position = replace(self.position, sequence=sequence, heading=heading, retarget_key=9)
        return self.pull.observe(self.session, self.destination, position, result, now, 100)

    def test_three_sectors_skip_the_direction_behind(self):
        self.pull.sectors = 3
        self.step(1, 0)
        self.assertIn('已发出', self.step(2, 250))
        headings = [0, math.pi / 2, -math.pi / 2]
        for sector in (1, 2):
            sequence, time = 3 + (sector - 1) * 4, 2250 + (sector - 1) * 2750
            old_heading, heading = headings[sector - 1], headings[sector]
            self.step(sequence, time, ack=sector, heading=old_heading)
            self.assertIn(f'第 {sector + 1} 个方向', self.step(sequence + 1, time + 250, ack=sector,
                                                              heading=old_heading))
            self.step(sequence + 2, time + 500, ack=sector, heading=heading)
            self.assertIn('已发出', self.step(sequence + 3, time + 750, ack=sector, heading=heading))
        self.assertIn('三个方向', self.step(11, 8000, ack=3, heading=-math.pi / 2))
        self.assertEqual(self.dispatcher.dispatch.call_count, 3)
        self.assertTrue(self.pull.empty)

    def test_default_is_four_sectors(self):
        self.assertEqual(self.pull.sectors, 4)


class WindowSwitchTests(unittest.TestCase):
    def test_switch_saves_and_controls_travel_pause_and_scout(self):
        import test_dev_settings_restart

        def exercise(window):
            session = (1, 2, 0)
            self.assertFalse(window._patrol_scan_enabled())
            self.assertTrue(window._camp_scout_allowed())
            window._toggle_patrol_scan(True)
            self.assertTrue(window.settings.patrol_travel_scan_enabled())
            self.assertTrue(window._patrol_scan_enabled())
            self.assertFalse(window._camp_scout_allowed())
            self.assertIn('已开启边走边找怪', window.ui.log_view.toPlainText())
            scan = window._travel_scan_for()
            scan.engaged = session, 0
            self.assertTrue(window._travel_engaged(session))
            self.assertIsNotNone(window._status_document(0)['patrol_scan'])
            window._toggle_patrol_scan(False)
            self.assertFalse(window._travel_engaged(session))
            self.assertTrue(window._camp_scout_allowed())

        with TemporaryDirectory() as directory:
            test_dev_settings_restart.RestartSettingsTests().window(directory, exercise, auto_grind=True)


class WindowTravelEngageTests(unittest.TestCase):
    """F3：循环行走中选到目标 → 停住行程、技能循环不暂停 → 战斗结束 → 回到原停留点（不跳点）。"""

    def test_engage_mid_walk_and_resume_same_stop(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from wowbuddy.automation.patrol_scan import TravelScan
        from wowbuddy.engine.character_state import CharacterState, MobState
        import test_dev_tray

        text = 'WBDROUTE2|1439|黑海岸|4029,5567|3851,6999|3966,6044|3966,5185'

        def exercise(window):
            window.grind_check.setChecked(True)
            window.settings.save_manual_routes([text])
            with patch('PySide6.QtWidgets.QInputDialog.getItem',
                       return_value=('1 · 黑海岸 · 4 点 · 39.66, 51.85', True)):
                window._edit_patrol_route()
            window._toggle_patrol_scan(True)
            dispatcher = Mock()
            dispatcher.state.last_sent_ms = 0
            dispatcher.dispatch.return_value.success = True
            window._travel_scan = TravelScan(dispatcher)
            session = (123, 1, 0)
            x, y = window._patrol_route.points[0]
            far = NavigationState('alive', 1, 1439, x - 3, y, 0, 6550, 4367, (87, 65, 68), 1, continuous=True)
            character = CharacterState('alive', True, True, 'alliance', 19, 1439, '黑海岸', far.x, far.y)
            window._poll_leveling(session, character, True)
            trip = window._leveling_trip[2]
            self.assertFalse(trip.complete)
            window._map_navigator = navigator = Mock(blocked=False)
            navigator.observe.return_value = None
            window._arrival_pull = pull = Mock(empty=False)
            pull.observe.return_value = None
            clock = [0]

            def poll(sequence, *, target='OFF', combat='OFF', distant=False):
                fields = {'player_valid': 'ON', 'player_in_combat': combat, 'target_valid': target,
                          'ttd': str(PACKET_BASE + 8192 + 1), 'enemies_8yd': '0',
                          'distance': '37.5' if distant else '17.5', 'player_health_pct': '100', 'mana_pct': '100'}
                frame = OldFrame('ok', values=fields)
                result = SimpleNamespace(
                    tick=TickResult('stopped' if distant else 'no_candidates',
                                    Decision(frame, fields, (), recovery_ready=True,
                                             attack_blocked_by_range=distant),
                                    display_now_ms=10_000),
                    capture=SimpleNamespace(client_rect=None))
                at = replace(far, sequence=sequence)
                with (patch('wowbuddy.engine.character_state.decode_navigation_state', return_value=at),
                      patch('wowbuddy.engine.character_state.decode_mob_state',
                            return_value=MobState(1, 1, 0, '', 1, False)),
                      patch.object(window, '_observe_local_access', return_value=(None, None)),
                      patch.object(window, 'monotonic_ms', return_value=clock[0])):
                    window._poll_navigation(result, session, object(), frame, character, None, navigate=True)

            poll(2)
            self.assertEqual(dispatcher.dispatch.call_count, 1)
            walking_destination = navigator.observe.call_args.args[3]
            self.assertIsNotNone(walking_destination)
            # 射程外的目标：不停下，继续走（2026-11-17 01:11 实测问题）
            clock[0] = 300
            poll(20, target='ON', distant=True)
            self.assertFalse(window._travel_engaged(session))
            clock[0] = 350
            poll(21, target='ON', distant=True)
            self.assertIs(navigator.observe.call_args.args[2].sequence, 21)   # 仍把定位交给导航（继续走）
            self.assertIsNotNone(navigator.observe.call_args.args[3])
            clock[0] = 400
            poll(3, target='ON')
            log = window.ui.log_view.toPlainText()
            self.assertIn('行走中选到目标，停下交战（原停留点：循环路点 1/4）', log)
            self.assertTrue(window._travel_engaged(session))
            clock[0] = 800
            poll(4, target='ON', combat='ON')
            self.assertTrue(window._travel_engaged(session))
            clock[0] = 6000
            poll(5)
            clock[0] = 7600
            poll(6)
            self.assertIn('途中交战结束，继续前往循环路点 1/4', window.ui.log_view.toPlainText())
            self.assertFalse(window._travel_engaged(session))
            self.assertEqual(window._patrol_index, 0)
            self.assertIs(window._leveling_trip[2], trip)
            clock[0] = 8000
            poll(7)
            self.assertIsNotNone(navigator.observe.call_args.args[3])      # 继续前往同一停留点

        test_dev_tray.TrayTests().run_window(False, exercise)


if __name__ == '__main__':
    unittest.main()
