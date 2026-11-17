"""地图格子寻路（docs/design/20261116-walk-grid-pathing.md）：规划、导航器绕行、灵魂跑尸。

全部使用合成格子，不含游戏数据。R1、R2 为复现用例：修复前导航器只会固定侧移、跑尸只会直线与尸体旁探点。
"""
from dataclasses import replace
import math
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'desktop'), str(ROOT / 'tests')]

from wowbuddy.automation.navigation import MapDestination, MapNavigator  # noqa: E402
from wowbuddy.engine.character_state import DeathState, NavigationState  # noqa: E402


def grid_module():
    from wowbuddy.core import walk_grid
    return walk_grid


def make_grid(size, blocked, *, map_id=52, cells=None):
    """size 码见方的地图，每格 size/cells 码；blocked(x码, y码) 为真的格子是墙。"""
    walk_grid = grid_module()
    cells = cells or size
    unit = size / cells
    walls = {(r, c) for r in range(cells) for c in range(cells) if blocked((c + .5) * unit, (r + .5) * unit)}
    return walk_grid.WalkGrid.from_blocked(map_id=map_id, rows=cells, cols=cells, width=size, height=size,
                                           blocked=walls)


def segment_clear(grid, a, b, *, allow_near_wall=True):
    """a、b 为地图百分比；按 0.25 格采样，不得进入原始受阻格（以及可选的外扩格）。"""
    (x1, y1), (x2, y2) = a, b
    r1, c1 = grid.cell_of(x1, y1)
    r2, c2 = grid.cell_of(x2, y2)
    steps = max(1, int(max(abs(r2 - r1), abs(c2 - c1)) * 4))
    for k in range(steps + 1):
        r = int(r1 + (r2 - r1) * k / steps)
        c = int(c1 + (c2 - c1) * k / steps)
        value = grid.cost_at(r, c)
        if value == 0 or (not allow_near_wall and value == 255):
            return False
    return True


# 一道 80 码长的南北向墙（超过局部绕行 18/24 码范围），墙北端再接一段向西的短墙，形成墙角。
def long_wall(x, y):
    return (110 <= x <= 112 and 60 <= y <= 140) or (96 <= x <= 112 and 60 <= y <= 62)


class WalkGridCoreTests(unittest.TestCase):
    def test_path_goes_around_a_long_wall_without_crossing_it(self):
        grid = make_grid(200, long_wall)
        path, reason = grid.find_path((50, 50), (75, 50))
        self.assertIsNotNone(path, reason)
        self.assertEqual(path.points[0], (50, 50))
        self.assertEqual(path.points[-1], (75, 50))
        for a, b in zip(path.points, path.points[1:]):
            self.assertTrue(segment_clear(grid, a, b), (a, b))
            self.assertLessEqual(math.hypot((a[0] - b[0]) * 2, (a[1] - b[1]) * 2), 20.5)
        self.assertGreater(path.yards, 50)

    def test_corner_cut_from_arrival_radius_stays_clear(self):
        grid = make_grid(200, long_wall)
        path, _ = grid.find_path((50, 50), (75, 50))
        points = path.points
        for before, corner, after in zip(points, points[1:], points[2:]):
            dx, dy = (corner[0] - before[0]) * 2, (corner[1] - before[1]) * 2
            length = math.hypot(dx, dy)
            cut = min(5, length)
            early = (corner[0] - dx / length * cut / 2, corner[1] - dy / length * cut / 2)
            self.assertTrue(segment_clear(grid, early, after), (early, corner, after))

    def test_unreachable_goal_reports_reason(self):
        def box(x, y):
            return 140 <= x <= 160 and 90 <= y <= 110 and not (144 <= x <= 156 and 94 <= y <= 106)
        grid = make_grid(200, box)
        path, reason = grid.find_path((50, 50), (75, 50))
        self.assertIsNone(path)
        self.assertIn('无路', reason)

    def test_expansion_cap(self):
        grid = make_grid(200, long_wall)
        path, reason = grid.find_path((50, 50), (75, 50), max_expansions=50)
        self.assertIsNone(path)
        self.assertIn('上限', reason)

    def test_start_inside_a_wall_cell_snaps_to_the_side_it_can_see(self):
        # 墙在 y=100–101 码；角色在 y=101.3（墙格内、偏南），只能吸附到南侧。
        grid = make_grid(200, lambda x, y: 60 <= x <= 140 and 100 <= y <= 102)
        path, reason = grid.find_path((50, 50.65), (50, 40))
        self.assertIsNotNone(path, reason)
        self.assertGreater(path.points[1][1], 50.65)      # 第一段往南（地图 y 增大），先绕出墙

    def test_start_deep_inside_its_own_obstacle_cell_can_leave_toward_a_free_neighbor(self):
        # 2026-11-17 00:53 实测：角色在 (29.27, 24.78)，精确位置在受阻格内 0.76 码，北侧相邻格可走。
        grid = make_grid(200, lambda x, y: 98 <= x <= 104 and 100 <= y <= 102)
        start = (100.6 / 2, 100.76 / 2)          # 两格厚障碍的北侧格 (100, 100) 内，距北边界 0.76 码
        self.assertIsNotNone(grid.snap(*start))
        # 相邻格就是墙时仍不能穿过：墙两格厚，角色在南侧那格里，不能吸附到北侧。
        thick = make_grid(200, lambda x, y: 60 <= x <= 140 and 100 <= y <= 102)
        cell = thick.snap(50, 50.65)
        self.assertGreater(cell[0], 101)

    def test_prefer_breaks_ties_toward_the_walked_side(self):
        grid = make_grid(200, lambda x, y: 60 <= x <= 140 and 100 <= y <= 101)
        start = (50, 50.25)          # 墙格正中，两侧等距
        north = grid.snap(*start, prefer=(50, 48))
        south = grid.snap(*start, prefer=(50, 53))
        self.assertLess(north[0], 100)
        self.assertGreater(south[0], 101)

    def test_temporary_obstacle_forces_the_other_way(self):
        # 中间一堵墙，北、南各留一个口；北口被临时堵住后改走南口。
        def wall(x, y):
            return 99 <= x <= 101 and not (40 <= y <= 50 or 150 <= y <= 160)
        grid = make_grid(200, wall)
        path, _ = grid.find_path((40, 25), (60, 25))
        self.assertTrue(any(p[1] < 30 for p in path.points[1:-1]))
        marked = grid.block_ahead(49.0, 22.5, 3 * math.pi / 2, near=0, far=4, half_width=8)
        self.assertGreater(marked, 0)
        path, _ = grid.find_path((40, 25), (60, 25))
        crossing = [p for p in path.points if 48 <= p[0] <= 52]
        self.assertTrue(crossing and all(p[1] > 70 for p in crossing), path.points)   # 改从南口穿墙
        grid.clear_temporary()
        path, _ = grid.find_path((40, 25), (60, 25))
        self.assertTrue(any(p[1] < 30 for p in path.points[1:-1]))

    def test_round_trip_bytes(self):
        walk_grid = grid_module()
        grid = make_grid(100, lambda x, y: 40 <= x <= 42, cells=50)
        again = walk_grid.WalkGrid.from_bytes(grid.to_bytes())
        self.assertEqual((again.map_id, again.rows, again.cols, again.width, again.height),
                         (52, 50, 50, 100, 100))
        self.assertEqual(again.cost_at(10, 20), grid.cost_at(10, 20))
        with self.assertRaises(ValueError):
            walk_grid.WalkGrid.from_bytes(b'nope')


class NavigatorGridDetourTests(unittest.TestCase):
    """R1：撞上 80 码长墙。没有格子图时固定侧移绕不过去；有格子图时沿格子路线绕过。"""

    def simulate(self, grid_routes):
        position = NavigationState('ghost', 0, 52, 50.0, 50.0, 3 * math.pi / 2, 200, 200, (87, 65, 68))
        destination = MapDestination(52, 75, 50, 'ghost', '尸体')
        movement = Mock()
        navigator = MapNavigator(movement)
        if grid_routes is not None:
            navigator.grid = grid_routes

        def pulse(_hwnd, key, hold, keys, **_):
            nonlocal position
            duration = hold / 1000
            if key == keys[0]:
                distance = 7 * duration
                x = position.x - 100 * distance * math.sin(position.heading) / position.width
                y = position.y - 100 * distance * math.cos(position.heading) / position.height
                if not long_wall(x * 2, y * 2):
                    position = replace(position, x=x, y=y)
            else:
                direction = 1 if key == keys[1] else -1
                position = replace(position, heading=(position.heading + direction * duration * 3) % math.tau)
            return True

        movement.pulse.side_effect = pulse
        log = []
        for sequence in range(3000):
            sample = replace(position, sequence=sequence % 256, x=round(position.x, 2), y=round(position.y, 2))
            status = navigator.observe('session', 123, sample, destination)
            if status:
                log.append(status)
                if status.startswith(('已到达', '已暂停')):
                    break
        return log

    def test_without_grid_the_fixed_detour_gives_up(self):
        log = self.simulate(None)
        self.assertTrue(log[-1].startswith('已暂停'), log)

    def test_with_grid_the_wall_is_bypassed(self):
        from wowbuddy.automation.grid_route import GridRoutes
        routes = GridRoutes(grids={52: make_grid(200, long_wall)})
        log = self.simulate(routes)
        self.assertTrue(any('按地图格子绕行' in message for message in log), log)
        self.assertTrue(log[-1].startswith('已到达'), log)


CORPSE = (1433, 30.48, 28.24)
SPAWN = NavigationState('ghost', 1, 1433, 23.2, 45.41, 0.8, 2171, 1448, (87, 65, 68))
GHOST = DeathState('ghost', 1, None, False, CORPSE, 'missing')


def house(x, y):
    """出生点东北方一道 120 码长的墙（码，原点为地图左上角）。"""
    sx, sy = 23.2 * 21.71, 45.41 * 14.48
    return sx + 4 <= x <= sx + 7 and sy - 60 <= y <= sy + 60


def poll(window, session, death, position):
    from wowbuddy.core.old_protocol import OldFrame
    from wowbuddy.engine.pipeline import Decision
    from wowbuddy.engine.scheduler import TickResult
    frame = OldFrame('ok', values={'player_valid': 'OFF', 'player_in_combat': 'OFF'})
    result = SimpleNamespace(tick=TickResult('no_candidates', Decision(frame, frame.values, ())))
    with patch('wowbuddy.engine.character_state.decode_navigation_state', return_value=position):
        window._poll_navigation(result, session, object(), frame, None, death, navigate=True)


def write_redridge_grid(directory):
    walk_grid = grid_module()
    rows, cols = 362, 543                       # 每格 4 码
    unit_x, unit_y = 2171 / cols, 1448 / rows
    walls = {(r, c) for r in range(rows) for c in range(cols) if house((c + .5) * unit_x, (r + .5) * unit_y)}
    grid = walk_grid.WalkGrid.from_blocked(map_id=1433, rows=rows, cols=cols, width=2171, height=1448,
                                           blocked=walls)
    folder = Path(directory) / 'walkgrid'
    folder.mkdir(parents=True, exist_ok=True)
    (folder / '1433.wgrid').write_bytes(grid.to_bytes())
    return grid


class GhostGridRouteTests(unittest.TestCase):
    """R2：灵魂出生点被长墙挡住、没有录制轨迹与接入路线时，开局按格子路线出发。"""

    def run_window(self, enabled, exercise):
        import test_dev_settings_restart

        def wrapped(window):
            write_redridge_grid(window.launch_options.data_dir)
            window._toggle_walk_grid(enabled)
            exercise(window)

        with TemporaryDirectory() as directory:
            test_dev_settings_restart.RestartSettingsTests().window(directory, wrapped, auto_grind=True)

    def test_switch_on_plans_the_corpse_run_on_the_grid(self):
        def exercise(window):
            navigator = window._map_navigator = Mock(blocked=False)
            navigator.observe.return_value = None
            poll(window, (1, 2, 0), GHOST, SPAWN)
            log = window.ui.log_view.toPlainText()
            self.assertIn('已按地图格子规划跑尸路线', log)
            first = navigator.observe.call_args.args[3]
            self.assertNotEqual(first.label, '尸体')
            # 从出生点到第一个去处不穿墙
            self.assertTrue(segment_clear(window._walk_grid.grid(1433), (SPAWN.x, SPAWN.y), (first.x, first.y)))
            self.assertIs(navigator.grid, window._walk_grid)
            self.assertEqual(window._status_document(0)['walk_grid']['maps'], [1433])

        self.run_window(True, exercise)

    def test_blocked_grid_trip_falls_back_instead_of_waiting(self):
        def exercise(window):
            navigator = window._map_navigator = Mock(blocked=False)
            navigator.observe.return_value = None
            poll(window, (1, 2, 0), GHOST, SPAWN)
            navigator.blocked = True
            navigator.observe.return_value = '已暂停前往「格子跑尸 2」。绕行各可用方向均受阻。'
            poll(window, (1, 2, 0), replace(GHOST, sequence=2), replace(SPAWN, sequence=2))
            log = window.ui.log_view.toPlainText()
            self.assertIn('本次放弃地图格子路线', log)
            self.assertNotIn('保留原路点，等待重新接入', log)

        self.run_window(True, exercise)

    def test_switch_off_keeps_the_old_corpse_route(self):
        def exercise(window):
            navigator = window._map_navigator = Mock(blocked=False)
            navigator.observe.return_value = None
            poll(window, (1, 2, 0), GHOST, SPAWN)
            log = window.ui.log_view.toPlainText()
            self.assertNotIn('按地图格子规划', log)
            self.assertIsNone(window._status_document(0)['walk_grid'])
            self.assertEqual(navigator.observe.call_args.args[3].label, '尸体')

        self.run_window(False, exercise)


def simulate_grid_corpse_run(test, grid, start, goal, *, size=(2171, 1448), heading=0.8, limit=12000):
    """真实 WalkingTrip（手动路点）+ MapNavigator + 格子：移动撞到原始受阻格即不动，要求最终到达尸体。"""
    from wowbuddy.automation.grid_route import GridRoutes
    from wowbuddy.automation.walking_route import WalkingTrip
    width, height = size
    routes = GridRoutes(grids={grid.map_id: grid})
    position = NavigationState('ghost', 0, grid.map_id, *start, heading, width, height, (87, 65, 68))
    goal_point = MapDestination(grid.map_id, *goal, 'ghost', '尸体')
    points, reason = routes.plan(position, goal_point)
    test.assertIsNotNone(points, reason)
    trip = WalkingTrip('session', (), goal_point, camp_road=points, catalog_goal=goal_point)
    movement = Mock()
    navigator = MapNavigator(movement)
    navigator.grid = routes

    def wall(x, y):
        r, c = grid.cell_of(x, y)
        return grid.cost_at(int(r), int(c)) == 0

    def pulse(_hwnd, key, hold, keys, **_):
        nonlocal position
        duration = hold / 1000
        if key == keys[0]:
            distance = 7 * duration
            x = position.x - 100 * distance * math.sin(position.heading) / position.width
            y = position.y - 100 * distance * math.cos(position.heading) / position.height
            same_cell = [int(v) for v in grid.cell_of(x, y)] == [int(v) for v in grid.cell_of(position.x, position.y)]
            if same_cell or not wall(x, y):
                position = replace(position, x=x, y=y)
        else:
            direction = 1 if key == keys[1] else -1
            position = replace(position, heading=(position.heading + direction * duration * 3) % math.tau)
        return True

    movement.pulse.side_effect = pulse
    log = []
    for sequence in range(limit):
        sample = replace(position, sequence=sequence % 256, x=round(position.x, 2), y=round(position.y, 2))
        destination, status = trip.observe(sample, now_ms=sequence * 100)
        if status:
            log.append(status)
        message = navigator.observe('session', 123, sample, destination, path=trip)
        if message:
            log.append(message)
        if navigator.blocked:
            break
        if goal_point.contains(sample):
            return log, True
    return log, False


class GridCorpseRunSimulationTests(unittest.TestCase):
    def test_synthetic_wall_corpse_run_arrives(self):
        rows, cols = 362, 543
        unit_x, unit_y = 2171 / cols, 1448 / rows
        walls = {(r, c) for r in range(rows) for c in range(cols) if house((c + .5) * unit_x, (r + .5) * unit_y)}
        grid = grid_module().WalkGrid.from_blocked(map_id=1433, rows=rows, cols=cols, width=2171, height=1448,
                                                   blocked=walls)
        log, arrived = simulate_grid_corpse_run(self, grid, (SPAWN.x, SPAWN.y), CORPSE[1:])
        self.assertTrue(arrived, log[-5:])

    def test_temporary_obstacles_expire(self):
        grid = make_grid(100, lambda x, y: False, cells=50)
        grid.block_ahead(50, 50, 0, near=0, far=4, half_width=4, expires=10)
        grid.block_ahead(30, 30, 0, near=0, far=4, half_width=4)
        count = grid.temporary_count
        self.assertGreater(count, 0)
        removed = grid.expire_temporary(11)
        self.assertGreater(removed, 0)
        self.assertEqual(grid.temporary_count, count - removed)
        self.assertGreater(grid.temporary_count, 0)     # 不过期的保留


LOCAL_GRID = ROOT / '.local' / 'walkgrid' / '1433.wgrid'


@unittest.skipUnless(LOCAL_GRID.is_file(), '本机没有赤脊山格子文件（tools/build_walk_grid.py 生成，不随仓库提交）')
class LocalRedridgeGridTests(unittest.TestCase):
    """只在本机有真实格子文件时运行：2026-11-15 卡住的墓地，两处实测位置都应先向南绕出房子。"""

    def test_graveyard_exit_goes_south_first(self):
        grid = grid_module().WalkGrid.from_bytes(LOCAL_GRID.read_bytes())
        for start in ((23.20, 45.41), (23.4547, 45.4594)):
            with self.subTest(start=start):
                path, reason = grid.find_path(start, (30.48, 28.24))
                self.assertIsNotNone(path, reason)
                # 格子图的预测（用户只确认了卡在房子墙角；实际出口方向以游戏验收 G2 为准）
                # 出生点 30 码内的路点：不向北（房子在北侧），且已向南走出 7 码以上
                near = [p for p in path.points
                        if math.hypot((p[0] - start[0]) * 21.71, (p[1] - start[1]) * 14.48) <= 30]
                self.assertGreaterEqual(min(p[1] for p in near), start[1] - 0.1)
                self.assertGreater(max(p[1] for p in near), start[1] + 0.5)
                self.assertLess(path.yards, 600)

    def test_simulated_corpse_run_arrives_from_both_measured_points(self):
        for start in ((23.20, 45.41), (23.4547, 45.4594)):
            with self.subTest(start=start):
                grid = grid_module().WalkGrid.from_bytes(LOCAL_GRID.read_bytes())
                log, arrived = simulate_grid_corpse_run(self, grid, start, (30.48, 28.24))
                self.assertTrue(arrived, log[-6:])


if __name__ == '__main__':
    unittest.main()
