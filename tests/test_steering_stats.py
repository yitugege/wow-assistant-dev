"""转向指标采集（docs/design/20261115-path-steering.md 第 1 步：T1–T3）。"""
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'desktop')]

from wowbuddy.automation.navigation import MapDestination, MapNavigator  # noqa: E402
from wowbuddy.automation.steering_stats import SteeringStats, cross_track_yards  # noqa: E402
from wowbuddy.engine.character_state import NavigationState  # noqa: E402

KEYS = (87, 65, 68)


def state(x, y, heading=0.0, *, sequence=1, continuous=False, moving=False, life='alive'):
    return NavigationState(life, sequence, 1433, x, y, heading, 2000, 1000, KEYS,
                           continuous=continuous, moving=moving)


class CrossTrackTests(unittest.TestCase):
    # T1
    def test_t1_distance_to_polyline_in_yards(self):
        road = ((10.0, 10.0), (12.0, 10.0), (12.0, 12.0))   # x 1% = 20 码，y 1% = 10 码
        self.assertAlmostEqual(cross_track_yards(state(11.0, 10.5), road), 5.0)    # 在第一段正下方 5 码
        self.assertAlmostEqual(cross_track_yards(state(12.25, 11.0), road), 5.0)   # 在第二段右侧 5 码
        self.assertAlmostEqual(cross_track_yards(state(9.0, 10.0), road), 20.0)    # 起点之外按端点算
        self.assertAlmostEqual(cross_track_yards(state(12.0, 10.0), road), 0.0)    # 拐角上
        self.assertIsNone(cross_track_yards(state(11, 10), ()))


class SteeringStatsTests(unittest.TestCase):
    # T2
    def test_t2_segment_summary_and_lap_total(self):
        counters = {'stop_turns': 0, 'steer_pulses': 0, 'stalls': 0}
        stats = SteeringStats()
        road = ((10.0, 10.0), (12.0, 10.0))
        stats.begin(1, 3, road, now_ms=0, counters=counters)
        for index, offset in enumerate((0.0, 0.2, 0.4, 0.2)):   # 偏离 0、2、4、2 码
            stats.observe(state(10.5 + index * 0.2, 10.0 + offset), now_ms=1000 * (index + 1))
        counters.update(stop_turns=2, steer_pulses=7, stalls=1)
        text = stats.finish(now_ms=4000, counters=counters)
        for part in ('转向统计', '第 1/3 段', '用时 4.0 秒', '最大偏离 4.0 码', '平均偏离 2.0 码',
                     '原地转向 2 次', '转向修正 7 次', '受阻 1 次'):
            self.assertIn(part, text)
        self.assertIsNone(stats.finish(now_ms=5000, counters=counters))   # 没有进行中的段
        stats.begin(2, 3, road, now_ms=5000, counters=counters)
        stats.observe(state(11, 10.1), now_ms=6000)
        counters.update(stop_turns=3, steer_pulses=9, stalls=1)
        stats.finish(now_ms=6000, counters=counters)
        stats.begin(3, 3, road, now_ms=6000, counters=counters)
        stats.observe(state(11, 10.0), now_ms=7000)
        text = stats.finish(now_ms=8000, counters=counters)
        self.assertIn('整圈', text)
        self.assertIn('原地转向 3 次', text)   # 整圈累计
        self.assertIn('最大偏离 4.0 码', text)

    def test_t2_begin_restarts_an_unfinished_segment(self):
        counters = {'stop_turns': 0, 'steer_pulses': 0, 'stalls': 0}
        stats = SteeringStats()
        stats.begin(1, 2, ((10.0, 10.0), (12.0, 10.0)), now_ms=0, counters=counters)
        stats.observe(state(11, 10.5), now_ms=500)
        stats.begin(1, 2, ((10.0, 10.0), (12.0, 10.0)), now_ms=1000, counters=counters)
        text = stats.finish(now_ms=2000, counters=counters)
        self.assertIn('用时 1.0 秒', text)
        self.assertIn('最大偏离 0.0 码', text)


class NavigatorCounterTests(unittest.TestCase):
    # T3
    def movement(self, *, holding):
        movement = Mock(holding_forward=holding)
        movement.keep_forward.return_value = holding
        movement.hold_forward.return_value = True
        movement.release_forward.return_value = True
        movement.pulse.return_value = True
        return movement

    def test_t3_counts_turn_in_place_without_changing_keys(self):
        movement = self.movement(holding=False)
        navigator = MapNavigator(movement)
        destination = MapDestination(1433, 14.0, 10.0, 'alive', '东侧路点')   # 正东，角色朝北
        navigator.observe((1, 2, 0), 123, state(10.0, 10.0, 0.0), destination)
        movement.pulse.assert_called_once()
        self.assertEqual(movement.pulse.call_args.args[1], KEYS[2])   # 向右转，与原行为相同
        self.assertEqual(navigator.counters['stop_turns'], 1)
        self.assertEqual(navigator.counters['steer_pulses'], 0)

    def test_t3_counts_steering_pulse_while_running(self):
        movement = self.movement(holding=True)
        navigator = MapNavigator(movement)
        destination = MapDestination(1433, 10.5, 8.0, 'alive', '前方偏右')   # 约 0.46 弧度（27°），小于原地转向阈值
        navigator.observe((1, 2, 0), 123, state(10.0, 10.0, 0.0, continuous=True, moving=True), destination)
        self.assertEqual(navigator.counters['steer_pulses'], 1)
        self.assertEqual(navigator.counters['stop_turns'], 0)


class WindowSteeringTests(unittest.TestCase):
    """T2：回放录制路线时按段写入转向统计日志（离屏真实窗口）。"""

    def test_t2_window_logs_segment_on_arrival(self):
        from types import SimpleNamespace as NS
        sys.path.insert(0, str(ROOT / 'tests'))
        import test_dev_tray
        from wowbuddy.automation.manual_routes import parse_patrol_route, patrol_leg

        def exercise(window):
            text = 'WBDLOOP1|1433|2000.0,1000.0|1000,1000|1300,1000|1300,1300|1000,1300'
            route = parse_patrol_route(text)
            window._apply_patrol_route(route)
            window._patrol_index = 1
            session = (1, 2, 0)
            trip = NS(session=session, complete=False, goal=NS(label=window._patrol_label(1)))
            window._leveling_trip = ('alliance', 20, trip)
            movement = Mock(holding_forward=False)
            window._map_navigator = MapNavigator(movement)
            leg = (route.points[0],) + patrol_leg(route, 1)
            window._observe_steering(session, state(*leg[0]))
            window._observe_steering(session, state(leg[-1][0], leg[-1][1] + 0.3))
            self.assertNotIn('转向统计', window.ui.log_view.toPlainText())
            trip.complete = True
            window._observe_steering(session, state(*leg[-1]))
            log = window.ui.log_view.toPlainText()
            self.assertIn(f'转向统计 · 第 2/{len(route.points)} 段', log)
            self.assertIn('最大偏离 3.0 码', log)

        test_dev_tray.TrayTests.run_window(self, False, exercise)

    def test_death_abandons_segment_without_counting(self):
        """fixes-2026-11：角色死亡后灵魂位置不计入偏离，本段作废，整圈汇总不受影响。"""
        from types import SimpleNamespace as NS
        sys.path.insert(0, str(ROOT / 'tests'))
        import test_dev_tray
        from wowbuddy.automation.manual_routes import parse_patrol_route, patrol_leg

        def exercise(window):
            route = parse_patrol_route('WBDLOOP1|1433|2000.0,1000.0|1000,1000|1300,1000|1300,1300|1000,1300')
            window._apply_patrol_route(route)
            window._patrol_index = 1
            session = (1, 2, 0)
            trip = NS(session=session, complete=False, goal=NS(label=window._patrol_label(1)))
            window._leveling_trip = ('alliance', 20, trip)
            window._map_navigator = MapNavigator(Mock(holding_forward=False))
            leg = (route.points[0],) + patrol_leg(route, 1)
            window._observe_steering(session, state(*leg[0]))
            window._observe_steering(session, state(30.0, 45.0, life='ghost'))   # 灵魂在墓地
            self.assertFalse(window._steering_stats.active)
            log = window.ui.log_view.toPlainText()
            self.assertIn(f'转向统计 · 第 2/{len(route.points)} 段：角色死亡，本段不计入。', log)
            self.assertNotIn('最大偏离', log)
            window._observe_steering(session, state(31.0, 45.0, life='ghost'))
            self.assertFalse(window._steering_stats.active)

        test_dev_tray.TrayTests.run_window(self, False, exercise)


if __name__ == '__main__':
    unittest.main()
