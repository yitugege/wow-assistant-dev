"""录制循环打怪路线与沿轨迹回放（docs/design/20261115-recorded-patrol.md 阶段 1：P1–P3）。"""
from math import hypot
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'desktop'), str(ROOT / 'tests')]

from wowbuddy.automation import patrol_recording as recording  # noqa: E402
from wowbuddy.automation.manual_routes import parse_manual_route, parse_patrol_route, patrol_leg  # noqa: E402

WIDTH, HEIGHT = 2000.0, 1000.0   # 地图码数：x 方向 1% = 20 码，y 方向 1% = 10 码


def pos(x, y, map_id=1433, life='alive', sequence=1):
    return NS(map_id=map_id, x=x, y=y, life=life, width=WIDTH, height=HEIGHT, sequence=sequence)


def yards(a, b):
    return hypot((a[0] - b[0]) * WIDTH / 100, (a[1] - b[1]) * HEIGHT / 100)


def walk(recorder, points, step=0.1):
    """沿折线每 step% 观察一次，返回最后的提示。"""
    notice = None
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        steps = max(1, int(max(abs(x1 - x0), abs(y1 - y0)) / step))
        for index in range(1, steps + 1):
            t = index / steps
            notice = recorder.observe(pos(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t)) or notice
    return notice


class RecorderTests(unittest.TestCase):
    # P1
    def test_p1_samples_at_least_eight_yards_and_merges_straight_lines(self):
        recorder = recording.PatrolRecorder()
        recorder.observe(pos(10, 10))
        walk(recorder, [(10, 10), (12, 10), (12, 13)])   # 40 码向东，再 30 码向南
        points = recorder.points
        self.assertEqual(points[0], (10.0, 10.0))
        self.assertTrue(any(yards(p, (12, 10)) <= 8 for p in points))   # 拐角附近保留一点（与跑尸录制同一规则）
        straight = [p for p in points if p[1] == 10.0]
        self.assertEqual(len(straight), 2)   # 直线段合并为首尾两点
        for a, b in zip(points, points[1:]):
            self.assertGreaterEqual(yards(a, b), 8 - 1e-6)

    def test_p1_crossing_loop_is_not_truncated(self):
        recorder = recording.PatrolRecorder()
        recorder.observe(pos(10, 10))
        figure_eight = [(10, 10), (14, 14), (14, 10), (10, 14), (10, 10.5)]
        walk(recorder, figure_eight)
        self.assertGreaterEqual(len(recorder.points), 5)
        for corner in ((14, 14), (14, 10), (10, 14)):   # 交叉的环线各拐角都保留，没有被折返截断
            self.assertTrue(any(yards(p, corner) <= 8 for p in recorder.points), corner)

    def test_p1_position_jump_or_map_change_stops_recording(self):
        recorder = recording.PatrolRecorder()
        recorder.observe(pos(10, 10))
        walk(recorder, [(10, 10), (11, 10)])
        notice = recorder.observe(pos(20, 10))   # 跳变 180 码
        self.assertTrue(recorder.stopped)
        self.assertIn('定位中断', notice)
        other = recording.PatrolRecorder()
        other.observe(pos(10, 10))
        notice = other.observe(pos(10.5, 10, map_id=1436))
        self.assertTrue(other.stopped)
        self.assertIn('地图', notice)

    def test_p1_dead_or_ghost_positions_are_ignored(self):
        recorder = recording.PatrolRecorder()
        recorder.observe(pos(10, 10))
        recorder.observe(pos(12, 10, life='ghost'))
        self.assertEqual(recorder.points, ((10.0, 10.0),))
        self.assertFalse(recorder.stopped)

    def test_p1_returning_near_start_after_sixty_yards_suggests_finishing(self):
        recorder = recording.PatrolRecorder()
        recorder.observe(pos(10, 10))
        notice = walk(recorder, [(10, 10), (13, 10), (13, 13), (10, 13), (10, 10.8)])
        self.assertTrue(recorder.near_start)
        self.assertIn('回到起点', notice)
        short = recording.PatrolRecorder()
        short.observe(pos(10, 10))
        walk(short, [(10, 10), (10.5, 10), (10.2, 10)])
        self.assertFalse(short.near_start)

    def test_p1_fewer_than_three_points_cannot_be_saved(self):
        recorder = recording.PatrolRecorder()
        recorder.observe(pos(10, 10))
        walk(recorder, [(10, 10), (11, 10)])
        with self.assertRaises(ValueError):
            recorder.encode()

    # P2
    def test_p2_encode_and_parse_round_trip(self):
        recorder = recording.PatrolRecorder()
        recorder.observe(pos(10, 10))
        walk(recorder, [(10, 10), (14, 10), (14, 14), (10, 14), (10, 10.5)])
        text = recorder.encode()
        self.assertTrue(text.startswith('WBDLOOP1|1433|'))
        route = parse_patrol_route(text)
        self.assertTrue(route.recorded)
        self.assertEqual(route.map_id, 1433)
        self.assertEqual(route.path, recorder.points)
        self.assertEqual(route.points[-1], route.path[-1])   # 末点是停留点
        self.assertTrue(set(route.points) <= set(route.path))
        # 停留点沿轨迹间隔约 40 码
        stops = list(route.stop_indices)
        self.assertEqual([route.path[i] for i in stops], list(route.points))
        self.assertEqual(stops, sorted(stops))
        self.assertGreaterEqual(len(route.points), 3)

    def test_p2_long_recordings_up_to_256_points_parse(self):
        points = '|'.join(f'{1000 + i * 30},{1000 + (i % 2) * 50}' for i in range(256))
        route = parse_patrol_route(f'WBDLOOP1|1433|{WIDTH:.1f},{HEIGHT:.1f}|{points}')
        self.assertEqual(len(route.path), 256)
        with self.assertRaises(ValueError):
            parse_patrol_route(f'WBDLOOP1|1433|{WIDTH:.1f},{HEIGHT:.1f}|{points}|9999,9999')

    def test_p2_plain_manual_routes_still_parse_unchanged(self):
        text = 'WBDROUTE1|1433|1000,1000|1200,1000|1200,1200'
        self.assertEqual(parse_patrol_route(text), parse_manual_route(text))
        self.assertFalse(parse_patrol_route(text).recorded)

    # P3
    def test_p3_leg_follows_recorded_path_and_wraps_to_start(self):
        recorder = recording.PatrolRecorder()
        recorder.observe(pos(10, 10))
        walk(recorder, [(10, 10), (14, 10), (14, 14), (10, 14), (10, 10.5)])
        route = parse_patrol_route(recorder.encode())
        path, stops = route.path, list(route.stop_indices)
        for index in range(len(route.points)):
            with self.subTest(stop=index):
                leg = patrol_leg(route, index)
                self.assertEqual(leg[-1], route.points[index])
                previous = stops[index - 1]
                expected = (path[previous + 1:stops[index] + 1] if index
                            else path[previous + 1:] + path[:stops[0] + 1])
                self.assertEqual(leg, expected)

    def test_p3_manual_route_leg_is_single_point(self):
        route = parse_patrol_route('WBDROUTE1|1433|1000,1000|1200,1000|1200,1200')
        self.assertEqual(patrol_leg(route, 1), ((12.0, 10.0),))


# 方形录制路线：路点 0..7，停留点下标 (1, 2, 4, 5, 6, 7)
SQUARE = ('WBDLOOP1|1433|2000.0,1000.0|1000,1000|1200,1000|1400,1000|1400,1200|1400,1400|'
          '1200,1400|1000,1400|1000,1200')


class RejoinTests(unittest.TestCase):
    """P9：接回录制轨迹。"""

    def setUp(self):
        from wowbuddy.automation.manual_routes import patrol_rejoin
        self.route = parse_patrol_route(SQUARE)
        self.rejoin = patrol_rejoin

    def test_p9_square_route_layout(self):
        self.assertEqual(self.route.stop_indices, (1, 2, 4, 5, 6, 7))
        self.assertEqual(patrol_leg(self.route, 0), ((10.0, 10.0), (12.0, 10.0)))

    def test_p9_on_route_in_another_segment_moves_to_stop_ahead(self):
        index, leg, distance = self.rejoin(self.route, (14.0, 13.0), 0)
        self.assertEqual((index, leg), (2, ((14.0, 14.0),)))
        self.assertAlmostEqual(distance, 0.0)

    def test_p9_ten_yards_off_route(self):
        index, leg, distance = self.rejoin(self.route, (14.5, 13.0), 0)
        self.assertEqual((index, leg), (2, ((14.0, 14.0),)))
        self.assertAlmostEqual(distance, 10.0)

    def test_p9_sixty_yards_away_reports_distance(self):
        index, leg, distance = self.rejoin(self.route, (17.0, 13.0), 0)
        self.assertEqual((index, leg), (2, ((14.0, 14.0),)))
        self.assertAlmostEqual(distance, 60.0)

    def test_p9_at_segment_start_keeps_full_leg(self):
        index, leg, distance = self.rejoin(self.route, (10.0, 10.0), 0)
        self.assertEqual((index, leg), (0, ((12.0, 10.0),)))   # 已在段起点，直接前往下一路点

    def test_p9_inside_current_segment_starts_after_projection(self):
        index, leg, distance = self.rejoin(self.route, (11.0, 10.2), 0)
        self.assertEqual((index, leg), (0, ((12.0, 10.0),)))
        self.assertAlmostEqual(distance, 2.0)

    def test_p9_wraps_from_last_segment_to_first_stop(self):
        index, leg, _ = self.rejoin(self.route, (10.0, 11.0), 3)   # 在 (10,12)→(10,10) 段上
        self.assertEqual((index, leg), (0, ((10.0, 10.0), (12.0, 10.0))))


class RecordedPatrolWindowTests(unittest.TestCase):
    """P2、P3：窗口中录制、保存、启用与回放规划（离屏真实窗口）。"""

    def run_window(self, exercise):
        import test_dev_tray
        test_dev_tray.TrayTests.run_window(self, False, exercise)

    def test_p2_record_save_and_apply_from_menu(self):
        from unittest.mock import patch

        def exercise(window):
            labels = [action.text() for action in window._manual_camp_button.menu().actions()]
            self.assertTrue(any(text.startswith('开始录制循环路线') for text in labels), labels)
            with patch.object(window.session, 'is_active', return_value=True):
                window._toggle_patrol_recording()
                self.assertIsNotNone(window._patrol_recorder)
                for point in [(10, 10), (14, 10), (14, 14), (10, 14), (10, 10.5)]:
                    for step in range(10):
                        window._observe_patrol_recording(pos(point[0], point[1] - step * 0.05))
                window._toggle_patrol_recording()
            self.assertIsNone(window._patrol_recorder)
            saved = window.settings.patrol_route()
            self.assertTrue(saved.startswith('WBDLOOP1|'))
            self.assertIn(saved, window.settings.recorded_patrols())
            self.assertTrue(window._patrol_route.recorded)
            self.assertIn('已保存录制的循环路线', window.ui.log_view.toPlainText())

        self.run_window(exercise)

    def test_p2_recording_requires_monitoring(self):
        def exercise(window):
            window._toggle_patrol_recording()
            self.assertIsNone(window._patrol_recorder)
            self.assertIn('开始监控', window.ui.log_view.toPlainText())

        self.run_window(exercise)

    def test_p3_recording_pauses_automatic_movement(self):
        from wowbuddy.automation.unattended import FramePlan

        def exercise(window):
            plan = FramePlan(revive=True, leveling=True, navigate=True)
            self.assertEqual(window._recording_plan(plan), plan)
            window._patrol_recorder = recording.PatrolRecorder()
            self.assertEqual(window._recording_plan(plan), FramePlan(revive=True, leveling=False, navigate=False))

        self.run_window(exercise)

    def character(self, x, y):
        return NS(life='alive', map_id=1433, level=20, x=x, y=y, faction='alliance', elevation=None,
                  zone='赤脊山', route_key=None)

    def test_p9_planning_rejoins_nearest_point_and_logs(self):
        def exercise(window):
            route = parse_patrol_route(SQUARE)
            window._apply_patrol_route(route)
            session = (1, 2, 0)
            window._poll_fixed_camp(session, self.character(14.0, 13.0))
            trip = window._leveling_trip[2]
            self.assertEqual(window._patrol_index, 2)
            self.assertEqual((trip.goal.x, trip.goal.y), (14.0, 14.0))
            self.assertEqual(tuple(trip.approach_road), ((14.0, 14.0),))
            self.assertIn('接回录制路线，从第 3 个停留点继续', window.ui.log_view.toPlainText())

        self.run_window(exercise)

    def test_p9_far_from_route_logs_straight_rejoin(self):
        def exercise(window):
            window._apply_patrol_route(parse_patrol_route(SQUARE))
            window._poll_fixed_camp((1, 2, 0), self.character(17.0, 13.0))
            self.assertIn('离录制路线约 60 码，正直线接回', window.ui.log_view.toPlainText())

        self.run_window(exercise)

    def test_p9_displaced_during_trip_replans_but_walking_on_route_does_not(self):
        def exercise(window):
            window._apply_patrol_route(parse_patrol_route(SQUARE))
            session = (1, 2, 0)
            window._poll_fixed_camp(session, self.character(10.0, 10.0))
            first = window._leveling_trip[2]
            self.assertEqual(tuple(first.approach_road), ((12.0, 10.0),))
            window._poll_fixed_camp(session, self.character(10.6, 10.3))     # 沿本段行走、偏 3 码
            self.assertIs(window._leveling_trip[2], first)
            window._poll_fixed_camp(session, self.character(14.6, 13.0))     # 被拉离本段 >12 码
            second = window._leveling_trip[2]
            self.assertIsNot(second, first)
            self.assertEqual(window._patrol_index, 2)
            self.assertEqual(tuple(second.approach_road), ((14.0, 14.0),))
            window._poll_fixed_camp(session, self.character(15.4, 13.0))     # 3 秒内不再重新规划
            self.assertIs(window._leveling_trip[2], second)

        self.run_window(exercise)

    def test_p9_after_finishing_a_stop_does_not_go_back_to_it(self):
        def exercise(window):
            route = parse_patrol_route(SQUARE)
            window._apply_patrol_route(route)
            window._patrol_index = 1                     # 已完成第 1 个停留点 (12,10)，前往 (14,10)
            window._poll_fixed_camp((1, 2, 0), self.character(11.8, 10.1))   # 仍站在第 1 个停留点旁
            self.assertEqual(window._patrol_index, 1)
            self.assertEqual(tuple(window._leveling_trip[2].approach_road), patrol_leg(route, 1))
            self.assertNotIn('接回录制路线', window.ui.log_view.toPlainText())

        self.run_window(exercise)

    def test_p9_manual_coordinate_patrol_is_unchanged(self):
        def exercise(window):
            route = parse_patrol_route('WBDROUTE1|1433|1000,1000|1400,1000|1400,1400')
            window._apply_patrol_route(route)
            window._poll_fixed_camp((1, 2, 0), self.character(14.0, 13.0))
            self.assertEqual(window._patrol_index, 0)
            self.assertEqual(tuple(window._leveling_trip[2].approach_road), ((10.0, 10.0),))

        self.run_window(exercise)

    def test_p3_patrol_leg_uses_recorded_path_as_road(self):
        def exercise(window):
            recorder = recording.PatrolRecorder()
            recorder.observe(pos(10, 10))
            walk(recorder, [(10, 10), (14, 10), (14, 14), (10, 14), (10, 10.5)])
            route = parse_patrol_route(recorder.encode())
            window._apply_patrol_route(route)
            window._patrol_index = 1
            session = (1, 2, 0)
            character = NS(life='alive', map_id=1433, level=20, x=10.2, y=10.0, faction='alliance', elevation=None,
                           zone='赤脊山', route_key=None)
            window._poll_fixed_camp(session, character)
            trip = window._leveling_trip[2]
            self.assertEqual((trip.goal.x, trip.goal.y), route.points[1])
            self.assertEqual(tuple(trip.approach_road), patrol_leg(route, 1))

        self.run_window(exercise)


if __name__ == '__main__':
    unittest.main()
