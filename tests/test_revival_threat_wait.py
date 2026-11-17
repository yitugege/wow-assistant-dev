"""复活点附近有怪时的等待上限（docs/design/20261117-loop-issues.md L7）。

2026-11-17 01:29:38 起：灵魂在 (27.67, 29.38)，尸体 (28.37, 27.30)，8 码内 2 只怪，
两个备选复活点都已试过，“当前复活位置附近刚出现敌人，等待敌人离开”持续 4 分钟以上，没有上限。
"""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'desktop'))

from wowbuddy.automation.death_recovery import AutomaticRevival  # noqa: E402
from wowbuddy.automation.navigation import MapDestination  # noqa: E402
from wowbuddy.engine.character_state import NavigationState  # noqa: E402

POSITION = NavigationState('ghost', 1, 1433, 27.67, 29.38, 0, 2171, 1448, (87, 65, 68))
STATE = SimpleNamespace(button=(5000, 1955), corpse=(1433, 28.37, 27.30), corpse_estimated=False, popup='ready')
THREAT = MapDestination(1433, 27.67, 29.38, 'ghost', '附近出现敌人的位置')


def revival():
    item = AutomaticRevival.__new__(AutomaticRevival)
    item._unsafe_landings = []
    item._probe_clearance = False
    item._reset_landing_search()
    # 两个备选点已用完（现场情况）
    item._tried_landings = [MapDestination(1433, 27.0, 28.0, 'ghost', '备选复活点'),
                            MapDestination(1433, 28.0, 28.9, 'ghost', '备选复活点')]
    return item


class RevivalThreatWaitTests(unittest.TestCase):
    def test_waits_briefly_then_moves_further_then_revives(self):
        item = revival()
        self.assertIn('等待敌人离开', item._position_for_revival(STATE, POSITION, THREAT, now_ms=0))
        self.assertIn('等待敌人离开', item._position_for_revival(STATE, POSITION, THREAT, now_ms=44_000))
        moved = item._position_for_revival(STATE, POSITION, THREAT, now_ms=45_000)
        self.assertIn('更远的备选复活位置', moved)
        self.assertIsNotNone(item.landing_destination)
        self.assertEqual(len(item._tried_landings), 3)

    def test_revives_after_the_total_limit_when_no_spot_is_left(self):
        item = revival()
        item._tried_landings += item._tried_landings          # 4 个都已试过
        self.assertIn('等待敌人离开', item._position_for_revival(STATE, POSITION, THREAT, now_ms=0))
        self.assertIn('等待敌人离开', item._position_for_revival(STATE, POSITION, THREAT, now_ms=60_000))
        self.assertIsNone(item._position_for_revival(STATE, POSITION, THREAT, now_ms=90_000))   # 直接复活

    def test_no_threat_resets_the_wait(self):
        item = revival()
        item._position_for_revival(STATE, POSITION, THREAT, now_ms=0)
        self.assertIsNone(item._position_for_revival(STATE, POSITION, None, now_ms=40_000))
        self.assertIn('等待敌人离开', item._position_for_revival(STATE, POSITION, THREAT, now_ms=50_000))


if __name__ == '__main__':
    unittest.main()
