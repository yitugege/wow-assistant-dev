"""满包且没有可用商人时继续打怪、不再拾取（docs/design/20261117-loop-issues.md L1 兜底）。

现状：赤脊山没有绑定商人，满包后“普通背包已满，当前没有可用的补给商人绑定，暂停练级。”，循环停止。
"""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'desktop'), str(ROOT / 'tests')]

from wowbuddy.core.old_protocol import OldFrame  # noqa: E402
from wowbuddy.engine.character_state import CharacterState, NavigationState, VendorState  # noqa: E402
from wowbuddy.engine.pipeline import Decision  # noqa: E402
from wowbuddy.engine.scheduler import TickResult  # noqa: E402

PAUSE = '普通背包已满，当前没有可用的补给商人绑定，暂停练级。'


def poll(window, free):
    session = (123, 1, 0)
    fields = {'player_valid': 'ON', 'player_in_combat': 'OFF', 'target_valid': 'OFF'}
    frame = OldFrame('ok', values=fields)
    result = SimpleNamespace(tick=TickResult('no_candidates', Decision(frame, fields, (), recovery_ready=True)),
                             capture=SimpleNamespace(client_rect=None))
    character = CharacterState('alive', True, True, 'alliance', 24, 1433, '赤脊山', 30.0, 30.0)
    position = NavigationState('alive', 1, 1433, 30.0, 30.0, 0, 2171, 1448, (87, 65, 68))
    reading = VendorState(1, free, 0, False, False, False, False, '', 0x76, None, catalog=False,
                          repair_needed=False)
    with (patch('wowbuddy.engine.character_state.decode_vendor_state', return_value=reading),
          patch('wowbuddy.engine.character_state.decode_navigation_state', return_value=position)):
        window._poll_vendor(session, object(), frame, result, character)
    return session


class BagFullGrindingTests(unittest.TestCase):
    def run_window(self, exercise):
        import test_dev_tray
        test_dev_tray.TrayTests().run_window(False, exercise)

    def test_switch_off_keeps_pausing(self):
        def exercise(window):
            window.grind_check.setChecked(True)
            poll(window, 0)
            self.assertIn(PAUSE, window.ui.log_view.toPlainText())
            self.assertIsNotNone(window._vendor_wait)
            self.assertFalse(window._skip_loot_for_full_bag())

        self.run_window(exercise)

    def test_switch_on_keeps_grinding_without_loot_until_space_returns(self):
        def exercise(window):
            window.grind_check.setChecked(True)
            window._toggle_bag_full_grinding(True)
            self.assertTrue(window.settings.bag_full_grinding_enabled())
            session = poll(window, 0)
            log = window.ui.log_view.toPlainText()
            self.assertNotIn(PAUSE, log)
            self.assertIn('背包已满且没有可用的商人，继续打怪，暂不拾取', log)
            self.assertIsNone(window._vendor_wait)
            self.assertTrue(window._skip_loot_for_full_bag())
            poll(window, 0)
            self.assertEqual(window.ui.log_view.toPlainText().count('继续打怪，暂不拾取'), 1)
            poll(window, 2)
            self.assertFalse(window._skip_loot_for_full_bag())
            self.assertEqual(session, (123, 1, 0))

        self.run_window(exercise)


if __name__ == '__main__':
    unittest.main()
