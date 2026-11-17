"""战斗中被拒绝的目标不能让角色一直不还手（docs/design/20261117-loop-issues.md L9）。"""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'desktop'))


def override(now):
    from wowbuddy.engine.pipeline import CombatRejectionOverride
    item = CombatRejectionOverride()
    item.clock = lambda: now[0]
    return item


class CombatRejectionOverrideTests(unittest.TestCase):
    def fields(self, **kwargs):
        return dict({'player_in_combat': 'ON', 'player_health_pct': '90'}, **kwargs)

    def test_waits_three_seconds_then_fights_back(self):
        now = [100.0]
        item = override(now)
        self.assertFalse(item.fight_back(self.fields(), '当前怪物已被其他玩家占有'))
        now[0] = 102.9
        self.assertFalse(item.fight_back(self.fields(), '当前怪物已被其他玩家占有'))
        now[0] = 103.0
        self.assertTrue(item.fight_back(self.fields(), '当前怪物已被其他玩家占有'))

    def test_low_health_fights_back_at_once(self):
        item = override([0.0])
        self.assertTrue(item.fight_back(self.fields(player_health_pct='45'), '当前怪物等级过低'))

    def test_players_and_out_of_combat_are_never_overridden(self):
        now = [0.0]
        item = override(now)
        item.fight_back(self.fields(), '当前目标是玩家或玩家控制的单位')
        now[0] = 60
        self.assertFalse(item.fight_back(self.fields(player_health_pct='10'), '当前目标是玩家或玩家控制的单位'))
        self.assertFalse(item.fight_back(self.fields(player_in_combat='OFF'), '当前怪物已被其他玩家占有'))
        self.assertIsNone(item.since)                 # 脱战即重置

    def test_reset_when_rejection_clears(self):
        now = [0.0]
        item = override(now)
        item.fight_back(self.fields(), '当前怪物已被其他玩家占有')
        item.reset()
        now[0] = 5
        self.assertFalse(item.fight_back(self.fields(), '当前怪物已被其他玩家占有'))


if __name__ == '__main__':
    unittest.main()
