"""灵魂出不了墓地（docs/design/20261115-ghost-graveyard-exit.md 复现用例）。

2026-11-15 赤脊山：灵魂在墓地 (23.20, 45.41) 每次直行 2–3 秒即受阻，备选点全部选在尸体旁，
起点不变，四个多小时原地不动。
"""
from dataclasses import replace
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'desktop'), str(ROOT / 'tests')]

from wowbuddy.automation.death_recovery import CorpseTrail  # noqa: E402
from wowbuddy.automation.manual_routes import parse_manual_route  # noqa: E402
from wowbuddy.automation.navigation import MapDestination  # noqa: E402
from wowbuddy.engine.character_state import DeathState, NavigationState  # noqa: E402

CORPSE = (1433, 30.48, 28.24)
SPAWN = NavigationState('ghost', 1, 1433, 23.2, 45.41, 6.2, 2171, 1448, (87, 65, 68))
GHOST = DeathState('ghost', 1, None, False, CORPSE, 'missing')


def poll(window, session, death, position):
    from wowbuddy.core.old_protocol import OldFrame
    from wowbuddy.engine.pipeline import Decision
    from wowbuddy.engine.scheduler import TickResult
    frame = OldFrame('ok', values={'player_valid': 'OFF', 'player_in_combat': 'OFF'})
    result = SimpleNamespace(tick=TickResult('no_candidates', Decision(frame, frame.values, ())))
    with patch('wowbuddy.engine.character_state.decode_navigation_state', return_value=position):
        window._poll_navigation(result, session, object(), frame, None, death, navigate=True)


class ExitBlockedWindowTests(unittest.TestCase):
    def test_blocked_near_spawn_stops_instead_of_trying_corpse_probes(self):
        import test_dev_settings_restart

        def exercise(window):
            session = (123, 456, 0)
            navigator = window._map_navigator = Mock(blocked=False)
            navigator.observe.return_value = None
            poll(window, session, GHOST, SPAWN)
            self.assertEqual(navigator.observe.call_args.args[3].label, '尸体')

            navigator.blocked = True
            navigator.observe.return_value = '已暂停前往「尸体」。绕行各可用方向均受阻。'
            poll(window, session, replace(GHOST, sequence=2), replace(SPAWN, sequence=2, x=23.3))
            log = window.ui.log_view.toPlainText()
            self.assertIn('灵魂未能离开墓地', log)
            self.assertNotIn('尝试从附近接近', log)

            navigator.blocked = False
            navigator.observe.return_value = None
            poll(window, session, replace(GHOST, sequence=3), replace(SPAWN, sequence=3, x=23.3))
            self.assertIsNone(navigator.observe.call_args.args[3])
            self.assertTrue(window._status_document(0)['ghost']['exit_blocked'])
            self.assertEqual(window.ui.log_view.toPlainText().count('灵魂未能离开墓地'), 1)

            # 玩家手动跑出墓地 40 码以外后，继续前往尸体。
            outside = replace(SPAWN, sequence=4, x=SPAWN.x + 2.5)
            poll(window, session, replace(GHOST, sequence=4), outside)
            self.assertIn('灵魂已离开墓地附近', window.ui.log_view.toPlainText())
            self.assertEqual(navigator.observe.call_args.args[3].label, '尸体')
            self.assertFalse(window._status_document(0)['ghost']['exit_blocked'])

        with TemporaryDirectory() as directory:
            test_dev_settings_restart.RestartSettingsTests().window(directory, exercise, auto_grind=True)

    def test_blocked_far_from_spawn_keeps_existing_corpse_probes(self):
        import test_dev_settings_restart

        def exercise(window):
            session = (123, 456, 0)
            navigator = window._map_navigator = Mock(blocked=False)
            navigator.observe.return_value = None
            poll(window, session, GHOST, SPAWN)
            navigator.blocked = True
            navigator.observe.return_value = '已暂停前往「尸体」。绕行各可用方向均受阻。'
            away = replace(SPAWN, sequence=2, x=28.0, y=33.0)
            poll(window, session, replace(GHOST, sequence=2), away)
            log = window.ui.log_view.toPlainText()
            self.assertNotIn('灵魂未能离开墓地', log)
            self.assertIn('尝试从附近接近', log)

        with TemporaryDirectory() as directory:
            test_dev_settings_restart.RestartSettingsTests().window(directory, exercise, auto_grind=True)


class ExitRouteTests(unittest.TestCase):
    def record(self, points):
        trail = CorpseTrail()
        corpse = (1440, *points[-1])
        ghost = DeathState('ghost', 2, None, False, corpse)
        start = NavigationState('ghost', 2, 1440, *points[0], 0, 1000, 1000, (1, 2, 3))
        trail.observe(1, DeathState('dead', 1, None, False, None), None, now_ms=0)
        trail.observe(1, ghost, start, now_ms=100)
        trail.observe(1, ghost, replace(start, sequence=11), now_ms=750)
        trail.observe(1, ghost, replace(start, sequence=12), now_ms=1400)
        now = 1400
        for index, (x, y) in enumerate(points[1:], start=20):
            now += 700
            last = index == len(points) + 18
            state = replace(ghost, button=(100, 100)) if last else ghost
            trail.observe(1, state, replace(start, sequence=index, x=x, y=y), now_ms=now)
        recorded = trail.observe(1, DeathState('alive', 99, None, False, None), None, now_ms=now + 700)
        return trail, recorded

    def test_successful_trail_also_yields_the_graveyard_exit(self):
        # 1 坐标单位 = 10 码：出口段到第一次离出生点 ≥40 码的路点为止（(21, 18) 距出生点 50 码）。
        points = [(18.0, 14.0), (18.0, 16.0), (19.0, 17.5), (21.0, 18.0), (26.0, 18.0), (30.0, 18.0)]
        trail, recorded = self.record(points)
        self.assertIsNotNone(recorded, trail.notice)
        route = parse_manual_route(trail.exit_route)
        self.assertEqual(route.map_id, 1440)
        self.assertEqual(route.points, ((18.0, 14.0), (18.0, 16.0), (19.0, 17.5), (21.0, 18.0)))

    def test_short_trail_does_not_yield_an_exit(self):
        trail, recorded = self.record([(18.0, 14.0), (18.0, 16.0), (18.5, 17.0)])
        self.assertIsNotNone(recorded, trail.notice)
        self.assertIsNone(trail.exit_route)


class ExitSaveWindowTests(unittest.TestCase):
    def test_saved_exit_becomes_a_ghost_start_access_route_once(self):
        import test_dev_settings_restart
        text = 'WBDROUTE1|1433|2320,4541|2330,4560|2380,4600'

        def exercise(window):
            scale = SPAWN.width, SPAWN.height
            window._remember_graveyard_exit(text, scale=scale)
            window._remember_graveyard_exit('WBDROUTE1|1433|2321,4541|2400,4700', scale=scale)   # 同一墓地不重复保存
            self.assertEqual(window.settings.manual_routes(access=True), [text])
            self.assertEqual(window.ui.log_view.toPlainText().count('已从本次跑尸录制保存墓地出口路线'), 1)
            access, destination = window._observe_local_access((1, 2, 0), 'ghost', SPAWN)
            self.assertIsNotNone(access)
            self.assertIsNotNone(destination)

        with TemporaryDirectory() as directory:
            test_dev_settings_restart.RestartSettingsTests().window(directory, exercise, auto_grind=True)


if __name__ == '__main__':
    unittest.main()
