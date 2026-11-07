"""连续帧调度与假Win32后端联测；保留原生顺序、边界和失败分支。"""
import unittest

from test_dispatch import AdvancingWin32
from test_old_protocol import CONTRACT, RULES, render_old
from test_pipeline import READABLE, READABLE_RULES
from wowbuddy.auto_target import PACKET_BASE
from wowbuddy.candidates import Rule
from wowbuddy.dispatch import ActionDispatcher
from wowbuddy.old_protocol import OldFrame
from wowbuddy.pipeline import DecisionPipeline, PreparedFrame
from wowbuddy.scheduler import Scheduler, SealMemory, SEAL_IDS, self_buff_actions
from wowbuddy.windows_keys import KeySender


def packet(state, seq=1, ack=0):
    return str(PACKET_BASE + 8192 + state * 1024 + ack * 32 + seq)


class SelfBuffTests(unittest.TestCase):
    def test_preservation_requires_tag_hold_and_no_target_aura(self):
        def rule(action, expression, tag="增益", hold=1000):
            return Rule(action, expression, tag=tag, hold_ms=hold)
        self.assertEqual(self_buff_actions([
            rule("keep", ["flag", "armor", False]),
            rule("target", ["and", ["flag", "armor", False], ["flag", "dot_target", False]]),
            rule("heal", ["flag", "a", False], tag="治疗"),
            rule("zero", ["flag", "a", False], hold=0),
            rule("or", ["or", ["flag", "a", False], ["flag", "b", False]]),
            rule("party", ["flag", "a_party1", False]),
        ]), frozenset({"keep", "party"}))


class SealTests(unittest.TestCase):
    def fields(self, generation, spell, combat="ON"):
        return {"player_succeeded_generation": str(generation), "player_succeeded_spell_id": str(spell),
                "player_in_combat": combat, "seal_fury": "UNKNOWN"}

    def test_first_receipt_is_baseline_and_each_rank_maps_correctly(self):
        self.assertEqual(len(SEAL_IDS), 21)
        for spell, expected in SEAL_IDS.items():
            state = SealMemory()
            self.assertEqual(state.observe(self.fields(1, spell), 1000)["seal_fury"], "UNKNOWN")
            output = state.observe(self.fields(2, spell), 1100)
            self.assertEqual(output[expected], "ON")
            self.assertEqual(sum(output[k] == "ON" for k in ("seal_fury", "seal_command", "seal_righteousness")), 1)
            self.assertEqual(state.until_ms, 31100)

    def test_judgement_clears_all_three_then_expires_at_exact_boundary(self):
        state = SealMemory(generation=1)
        state.observe(self.fields(2, 0x4eba), 1000)
        result = state.observe(self.fields(3, 20271), 2000)
        self.assertEqual([result[k] for k in ("seal_fury", "seal_command", "seal_righteousness")], ["OFF"] * 3)
        self.assertEqual(state.observe(self.fields(3, 20271), 31999)["seal_fury"], "OFF")
        self.assertEqual(state.observe(self.fields(3, 20271), 32000)["seal_fury"], "UNKNOWN")

    def test_out_of_combat_does_not_overlay_but_records_receipt(self):
        state = SealMemory(generation=5)
        result = state.observe(self.fields(6, 0x4f97, "OFF"), 1000)
        self.assertNotIn("seal_command", result)
        self.assertEqual(state.observe(self.fields(6, 1), 1001)["seal_command"], "ON")
        state.observe(self.fields(0, 20271), 1100)
        self.assertEqual(state.generation, 6)
        self.assertEqual(state.observe(self.fields(7, 0xFFFFFF), 31000)["seal_fury"], "UNKNOWN")


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.backend = AdvancingWin32()
        self.pipeline = DecisionPipeline(CONTRACT, READABLE, RULES, READABLE_RULES)
        self.sender = KeySender(self.backend, hwnd=10, force_background=True,
                                allow_activation=False, interval_ms=30, hold_ms=30)
        self.dispatcher = ActionDispatcher(self.sender)
        self.scheduler = Scheduler(self.pipeline, self.dispatcher, self.backend.now_ms)
        self.scheduler.state.target_valid = 1
        self.base = {"master_switch": "ON", "target_valid": "ON", "player_valid": "ON",
                     "gcd": "OFF", "player_casting": "空闲", "player_in_combat": "OFF"}

    def prepared(self, fields=None, rules=None):
        values = self.base | (fields or {})
        return PreparedFrame(OldFrame("ok", spec_id="1482", values=values), values,
                             selected_rules=rules if rules is not None else [{"action": "spell_116", "when": ["always"]}])

    def tick(self, fields=None, rules=None, interval=100):
        return self.scheduler.process(self.prepared(fields, rules), hwnd=10, send_interval_ms=interval)

    def test_one_frame_sends_then_interval_then_local_gcd_then_next_send(self):
        first = self.tick()
        self.assertEqual(first.status, "sent")
        self.assertEqual(self.tick().status, "interval")
        self.backend.clock = 1200
        self.assertEqual(self.tick().status, "gcd_blocked")
        self.backend.clock = 2510
        self.assertEqual(self.tick().status, "sent")
        self.assertEqual(self.dispatcher.state.success_count, 2)

    def test_new_target_retains_only_self_buff_in_all_six_maps(self):
        ledger = self.dispatcher.state.auras
        for action in ("spell_168", "spell_116"):
            ledger.record_send(action, success=True, now_ms=900, hold_ms=30000,
                               expect_off=("frost_armor",), fields={"player_succeeded_generation": "1"})
            ledger.failures[action] = 1
        self.dispatcher.state.last_sent_ms = 950
        self.dispatcher.state.local_gcd_until_ms = 2400
        self.scheduler.state.target_valid = 0
        rules = [{"action": "spell_168", "when": ["flag", "frost_armor", False], "tag": "增益", "holdMs": 30000}]
        result = self.tick({"frost_armor": "ON"}, rules)
        self.assertIn(("new_target_clear", 1), result.events)
        self.assertIn(("new_target_gcd_clear", 1400), result.events)
        self.assertLess(result.events.index(("new_target_gcd_clear", 1400)),
                        result.events.index(("new_target_clear", 1)))
        for name in ("suppression_until", "check_at", "expect_off", "failures", "original_hold_ms", "sent_generation"):
            self.assertEqual(set(getattr(ledger, name)), {"spell_168"})
        self.assertEqual(self.dispatcher.state.last_sent_ms, 0)
        self.assertEqual(self.dispatcher.state.local_gcd_until_ms, 0)

    def test_unknown_target_does_not_reset_previous_state(self):
        self.tick({"target_valid": "UNKNOWN"}, rules=[])
        self.assertEqual(self.scheduler.state.target_valid, 1)
        self.dispatcher.state.local_gcd_until_ms = 5000
        result = self.tick()
        self.assertEqual(result.status, "gcd_blocked")
        self.assertNotIn("new_target_clear", [event[0] for event in result.events])

    def test_judgement_log_requires_previously_active_unexpired_seal(self):
        for seal, deadline, expected in (("", 5000, False), ("seal_command", 1000, False),
                                         ("seal_command", 1001, True)):
            with self.subTest(seal=seal, deadline=deadline):
                self.scheduler.state.seals = SealMemory(generation=1, seal=seal, until_ms=deadline)
                observed = []
                result = self.scheduler.process(self.prepared({"player_succeeded_generation": "2",
                    "player_succeeded_spell_id": "20271", "player_in_combat": "ON"}, rules=[]),
                    hwnd=10, send_interval_ms=100,
                    on_event=lambda name, value, **kwargs: observed.append(name))
                self.assertEqual("seal_consumed" in observed, expected)
                self.assertEqual(any(name == "seal_consumed" for name, _ in result.events), expected)
                self.assertEqual(self.scheduler.state.seals.seal, "")
                self.assertEqual(self.scheduler.state.seals.judgement_ms, 1000)

    def test_new_target_unknown_gcd_or_casting_does_not_clear_local_gcd(self):
        for overrides in ({"gcd": "UNKNOWN"}, {"player_casting": "读条中"}):
            self.scheduler.state.target_valid = 0
            self.dispatcher.state.local_gcd_until_ms = 5000
            result = self.tick(overrides)
            self.assertEqual(self.dispatcher.state.local_gcd_until_ms, 5000)
            self.assertNotIn("new_target_gcd_clear", [event[0] for event in result.events])

    def test_auto_gate_completion_clears_suppression_but_not_gcd(self):
        result = self.tick({"ttd": packet(1)})
        self.assertEqual(result.selected.action, "auto_target")
        self.dispatcher.state.auras.suppression_until["spell_116"] = 6000
        self.dispatcher.state.local_gcd_until_ms = 5000
        self.backend.clock = 1100
        complete = self.tick({"ttd": packet(2)})
        self.assertIn(("auto_target_clear", 2), complete.events)
        self.assertEqual(self.dispatcher.state.local_gcd_until_ms, 5000)
        self.assertEqual(complete.status, "gcd_blocked")

    def test_auto_waiting_survives_missing_packet_and_sentinel_early_return(self):
        self.tick({"ttd": packet(1)})
        stopped = self.tick({"master_switch": "OFF", "ttd": packet(2)})
        self.assertEqual(stopped.status, "stopped")
        self.assertTrue(self.scheduler.state.auto_waiting)
        self.tick({"ttd": "10"})
        self.assertFalse(self.scheduler.state.auto_protocol_active)
        self.assertTrue(self.scheduler.state.auto_waiting)
        self.backend.clock = 2000
        complete = self.tick({"ttd": packet(0)})
        self.assertIn("auto_target_clear", [event[0] for event in complete.events])
        self.assertFalse(self.scheduler.state.auto_waiting)

    def test_failed_top_candidate_does_not_attempt_lower_priority(self):
        prepared = self.prepared(rules=[{"action": "spell_116", "when": ["always"]},
                                        {"action": "spell_168", "when": ["always"]}])
        prepared = type(prepared)(prepared.frame, prepared.fields, selected_rules=prepared.selected_rules,
                                  key_overrides={"spell_116": "INVALID-KEY"})
        result = self.scheduler.process(prepared, hwnd=10, send_interval_ms=100)
        self.assertEqual(result.status, "send_failed")
        self.assertEqual(result.selected.action, "spell_116")
        self.assertFalse(self.backend.of("PostMessageW"))

    def test_suppressed_first_candidate_allows_second(self):
        self.dispatcher.state.auras.suppression_until["spell_116"] = 2000
        result = self.tick(rules=[{"action": "spell_116", "when": ["always"]},
                                 {"action": "spell_168", "when": ["always"]}])
        self.assertEqual(result.selected.action, "spell_168")

    def test_seal_override_precedes_candidates_but_probe_reads_original_fields(self):
        self.scheduler.state.seals.generation = 1
        ledger = self.dispatcher.state.auras
        ledger.record_send("spell_20154", success=True, now_ms=500, hold_ms=30000,
                           expect_off=("seal_righteousness",), fields={"player_succeeded_generation": "1"})
        result = self.tick({"player_in_combat": "ON", "player_succeeded_generation": "2",
                            "player_succeeded_spell_id": "20154", "seal_righteousness": "OFF"},
                           rules=[{"action": "spell_116", "when": ["flag", "seal_righteousness", True]}])
        self.assertEqual(result.selected.action, "spell_116")
        self.assertEqual(result.decision.fields["seal_righteousness"], "OFF")
        self.assertEqual(result.probes[0].result.name, "IMMUNE")

    def test_focus_invalid_player_resets_memory_and_observation_allows_index_five(self):
        self.dispatcher.state.focus.last_action = "focus_player"
        self.dispatcher.state.focus.last_switch_ms = 500
        self.tick({"player_valid": "OFF", "focus_index": "5"}, rules=[])
        self.assertEqual(self.dispatcher.state.focus.last_action, "")
        self.assertEqual(self.dispatcher.state.focus.last_switch_ms, 0)
        self.assertTrue(self.scheduler.state.focus_known)
        self.assertEqual(self.scheduler.state.observed_focus, 5)
        self.tick({"focus_index": "6"}, rules=[])
        self.assertFalse(self.scheduler.state.focus_known)

    def test_real_image_to_fake_key_event_and_invalid_frame_stops(self):
        image, _ = render_old(1482, {"master_switch": 0x00FF00, "target_valid": 0x00FF00})
        profile = {"specId": 1482, "rules": [{"action": "spell_116", "when": ["always"]}]}
        result = self.scheduler.tick(image, hwnd=10, send_interval_ms=100, selected_profile=profile)
        self.assertEqual(result.status, "sent")
        self.assertEqual(self.backend.of("PostMessageW"), [("PostMessageW", 10, 0x100, 0x65, 1),
                                                           ("PostMessageW", 10, 0x101, 0x65, 0xC0000001)])
        calls = len(self.backend.of("PostMessageW"))
        from wowbuddy.pixel_geometry import RGBImage
        failed = self.scheduler.tick(RGBImage([]), hwnd=10, send_interval_ms=100)
        self.assertEqual(failed.status, "invalid_frame")
        self.assertEqual(len(self.backend.of("PostMessageW")), calls)


if __name__ == "__main__":
    unittest.main()
