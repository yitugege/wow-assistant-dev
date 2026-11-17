"""朝向错误后转向失败须说明原因（docs/design/20261115-combat-facing-silent.md 复现用例）。

2026-11-15 18:47：游戏不在前台（用户在看 Claude 终端），奥术冲击 5 次朝向错误，
转向脉冲因前台条件不满足而未发出，日志中没有任何说明。
"""
from pathlib import Path
import sys
import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'desktop'), str(ROOT / 'tests')]

from wowbuddy.automation.navigation import ForegroundMovement  # noqa: E402

KEYS = (87, 65, 68)


def keyboard(foreground=100, pressed=()):
    board, processes = Mock(), Mock()
    board.GetAncestor.side_effect = lambda hwnd, _: hwnd
    board.GetForegroundWindow.return_value = foreground
    board.GetAsyncKeyState.side_effect = lambda key: 0x8000 if key in pressed else 0
    board.MapVirtualKeyW.return_value = 0x11
    board.SendInput.return_value = 1
    processes.process_path.return_value = r'D:\game\Wow.exe'
    return board, processes


class BlockReasonTests(unittest.TestCase):
    def test_reason_when_game_not_in_foreground(self):
        movement = ForegroundMovement(*keyboard(foreground=999))
        self.assertFalse(movement.pulse(100, KEYS[1], 120, KEYS))
        self.assertEqual(movement.blocked_reason, '游戏不在前台')

    def test_reason_when_user_holds_a_movement_key(self):
        movement = ForegroundMovement(*keyboard(pressed=(ord('W'),)))
        self.assertFalse(movement.pulse(100, KEYS[1], 120, KEYS))
        self.assertEqual(movement.blocked_reason, '检测到手动按键')

    def test_reason_cleared_after_success(self):
        board, processes = keyboard(foreground=999)
        movement = ForegroundMovement(board, processes)
        movement.pulse(100, KEYS[1], 120, KEYS)
        board.GetForegroundWindow.return_value = 100
        self.assertTrue(movement.pulse(100, KEYS[1], 120, KEYS))
        self.assertIsNone(movement.blocked_reason)


class WindowFacingTests(unittest.TestCase):
    def test_facing_error_logs_why_turn_was_not_sent(self):
        import test_dev_tray
        feedback = NS(sequence=53, spell=400574, stages=('提交', '失败'), error_code=57, error_kind='朝向')
        sample = NS(revision=1, keys=KEYS, heading=None, target_heading=None, action_spell=None)
        frame = NS(values={'player_in_combat': 'ON'})

        def exercise(window):
            movement = Mock()
            movement.pulse.return_value = False
            movement.blocked_reason = '游戏不在前台'
            window._combat_movement = lambda: movement
            with patch('wowbuddy.engine.character_state.decode_cast_feedback', return_value=feedback), \
                    patch('wowbuddy.engine.character_state.decode_combat_facing', return_value=sample):
                window._observe_combat_feedback((1, 2, 0), object(), frame, 1000)
                window._observe_combat_feedback((1, 2, 0), object(), frame, 1100)   # 同一回执不重复提示
            log = window.ui.log_view.toPlainText()
            self.assertEqual(log.count('朝向错误未能转向：游戏不在前台'), 1, log)

        test_dev_tray.TrayTests.run_window(self, False, exercise)


if __name__ == '__main__':
    unittest.main()
