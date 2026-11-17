"""录制循环自交处的接回（docs/design/20261117-loop-issues.md L8）。

2026-11-17 01:43:19 起前往第 8 个停留点，5 秒后改为“循环路点 5/12”，重走 5→6→7。
赤脊山录制环线在第 4 段与第 8 段附近几乎相交，全环最近点落在更早的一段。
"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'desktop'))

from wowbuddy.automation.manual_routes import parse_patrol_route, patrol_rejoin  # noqa: E402

REDRIDGE_LOOP = 'WBDLOOP1|1433|2171.0,1448.0|3347,3771|3330,3587|3288,3489|3279,3366|3300,3310|3308,3194|3270,3024|3109,2844|3016,2795|3006,2684|2949,2594|2912,2620|2871,2610|2813,2525|2777,2543|2727,2438|2615,2359|2720,2337|2758,2346|2947,2456|3047,2722|3323,3094|3388,3294|3396,3355|3332,3512|3350,3568|3338,3623|3352,3741|3370,3795|3321,3695|3308,3634'


class PatrolRejoinTests(unittest.TestCase):
    def test_off_leg_near_a_crossing_keeps_the_current_stop(self):
        route = parse_patrol_route(REDRIDGE_LOOP)
        stop8 = route.path[route.stop_indices[7]]
        index, leg, distance = patrol_rejoin(route, (stop8[0] - 0.3, stop8[1]), 7)
        self.assertEqual(index, 7)
        self.assertLess(distance, 25)

    @unittest.expectedFailure   # L12 复现用例，修复待设计确认
    def test_pulled_25_yards_off_by_a_fight_keeps_the_current_stop(self):
        # 2026-11-17 09:20:49：前往第 10 点时被途中交战拉离本段 25.06 码，接回到了第 3 点。
        route = parse_patrol_route(REDRIDGE_LOOP)
        index, _, _ = patrol_rejoin(route, (32.35, 29.82), 9)
        self.assertEqual(index, 9)

    def test_far_from_the_current_leg_still_uses_the_nearest_stop(self):
        route = parse_patrol_route(REDRIDGE_LOOP)
        stop2 = route.path[route.stop_indices[1]]
        index, _, _ = patrol_rejoin(route, stop2, 7)
        self.assertEqual(index, 1)


if __name__ == '__main__':
    unittest.main()
