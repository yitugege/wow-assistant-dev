"""发送执行器与真实 KeySender 逻辑联测，后端只记录事件。"""
import unittest

from test_windows_keys import FakeWin32
from wowbuddy.candidates import Candidate
from wowbuddy.dispatch import ActionDispatcher
from wowbuddy.windows_keys import KeySender


class AdvancingWin32(FakeWin32):
    def Sleep(self, milliseconds):
        self.calls.append(("Sleep", milliseconds))
        self.clock += milliseconds


class DispatchTests(unittest.TestCase):
    def setUp(self):
        self.backend = AdvancingWin32()
        self.sender = KeySender(self.backend, hwnd=99, force_background=False,
                                allow_activation=True, interval_ms=30, hold_ms=100)
        self.dispatcher = ActionDispatcher(self.sender)
        self.candidate = Candidate(action="spell_116", key="NUMPAD5", hold_ms=1000)

    def test_success_uses_main_window_route_and_completion_time(self):
        result = self.dispatcher.dispatch(self.candidate, hwnd=10, fields={})
        self.assertTrue(result.success)
        self.assertEqual(result.channel_path, "后台投递")
        self.assertEqual((self.sender.hwnd, self.sender.force_background, self.sender.allow_activation, self.sender.interval_ms),
                         (10, True, False, 30))
        self.assertEqual(self.sender.hold_ms, 100)
        self.assertFalse(self.backend.of("SendInput"))
        self.assertFalse(self.backend.of("SetForegroundWindow"))
        self.assertEqual(result.sent_at_ms, 1010)
        state = self.dispatcher.state
        self.assertEqual((state.last_sent_ms, state.success_count, state.local_gcd_until_ms), (1010, 1, 2510))
        self.assertEqual(state.auras.suppression_until, {"spell_116": 2010})

    def test_successful_pre_waits_and_only_main_increments_action_count(self):
        candidate = Candidate(action="heal", key="F1", pre_key="CTRL-F2", pre_action="focus_party1",
                              hold_ms=30000, expect_off=("renew",))
        result = self.dispatcher.dispatch(candidate, hwnd=10, fields={"player_succeeded_generation": "8"})
        self.assertTrue(result.pre_success)
        self.assertTrue(result.success)
        self.assertEqual(self.backend.of("Sleep"), [("Sleep", 10), ("Sleep", 40), ("Sleep", 10)])
        state = self.dispatcher.state
        self.assertEqual(state.focus.last_switch_ms, 1000)
        self.assertEqual((state.success_count, self.sender.success_count), (1, 2))
        self.assertEqual(state.auras.check_at["heal"], 1460)
        self.assertEqual(state.auras.sent_generation["heal"], 8)

    def test_confirmed_focus_skips_pre_and_refreshes_memory(self):
        candidate = Candidate(action="heal", key="F1", pre_key="CTRL-F2", pre_action="focus_party1")
        result = self.dispatcher.dispatch(candidate, hwnd=10, fields={}, focus_known=True, observed_focus=1)
        self.assertTrue(result.pre_skipped)
        self.assertIsNone(result.pre_success)
        self.assertEqual(self.backend.of("Sleep"), [("Sleep", 10)])
        self.assertEqual(self.dispatcher.state.focus.skipped_count, 1)
        self.assertEqual(self.dispatcher.state.focus.last_action, "focus_party1")

    def test_pre_failure_clears_focus_but_does_not_abort_main(self):
        self.dispatcher.state.focus.last_action = "focus_player"
        candidate = Candidate(action="heal", key="F1", pre_key="INVALID-KEY", pre_action="focus_party1")
        result = self.dispatcher.dispatch(candidate, hwnd=10, fields={})
        self.assertFalse(result.pre_success)
        self.assertTrue(result.success)
        self.assertEqual(self.dispatcher.state.focus.last_action, "")

    def test_main_window_resets_interval_before_pre_and_main(self):
        self.sender.interval_ms = 100
        candidate = Candidate(action="heal", key="F1", pre_key="F2", pre_action="focus_party1", hold_ms=500)
        result = self.dispatcher.dispatch(candidate, hwnd=10, fields={})
        self.assertTrue(result.pre_success)
        self.assertTrue(result.success)
        self.assertEqual(self.sender.interval_ms, 30)
        self.assertEqual(self.dispatcher.state.success_count, 1)
        self.assertEqual(self.dispatcher.state.auras.suppression_until, {"heal": 1560})
        self.assertEqual(self.dispatcher.state.focus.last_action, "focus_party1")

    def test_main_rate_limit_failure_does_not_overwrite_bookkeeping(self):
        first = self.dispatcher.dispatch(self.candidate, hwnd=10, fields={})
        second = self.dispatcher.dispatch(self.candidate, hwnd=10, fields={})
        self.assertTrue(first.success)
        self.assertFalse(second.success)
        self.assertIn("限速跳过", second.channel_status)
        self.assertEqual(self.dispatcher.state.success_count, 1)
        self.assertEqual(self.dispatcher.state.auras.suppression_until, {"spell_116": 2010})

    def test_failed_main_and_off_gcd_preserve_previous_gcd(self):
        self.dispatcher.state.local_gcd_until_ms = 900
        failure = self.dispatcher.dispatch(self.candidate, hwnd=999, fields={})
        self.assertFalse(failure.success)
        self.assertEqual(self.dispatcher.state.last_sent_ms, 0)
        candidate = Candidate(action="auto_target", key="F1", off_gcd=True, hold_ms=400)
        success = self.dispatcher.dispatch(candidate, hwnd=10, fields={})
        self.assertTrue(success.success)
        self.assertEqual(self.dispatcher.state.local_gcd_until_ms, 900)

    def test_missing_sender_or_key_does_not_inject(self):
        self.assertEqual(ActionDispatcher(None).dispatch(self.candidate, hwnd=10, fields={}).status, "no_sender")
        self.assertEqual(self.dispatcher.dispatch(Candidate(), hwnd=10, fields={}).status, "no_key")
        self.assertEqual(self.backend.calls, [])


if __name__ == "__main__":
    unittest.main()
