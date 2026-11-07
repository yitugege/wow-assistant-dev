"""候选生成边界及原版 --selftest 已观察到的端到端用例。"""

import copy
import unittest

from wowbuddy.auto_target import PACKET_BASE
from wowbuddy.candidates import (
    Action, CandidateEngine, OFF_GCD_SPELL_IDS, collect_expect_off, focus_unit,
    infer_role, parse_rules,
)
from wowbuddy.expressions import EvaluationContext, UnsupportedSemantics


def document(actions=None, rotations=None, generic=None, role=None):
    return {
        "sentinel": {"masterSwitchField": "master_switch", "combatTimeField": "combat_time",
                     "stopTag": "总开关", "stopLabel": "总开关已关闭", "stopReason": "原始停发理由"},
        "roles": {"1": role} if role is not None else {},
        "specs": {"1": {"actions": actions or [], "rotations": rotations or {},
                         "genericFill": generic or [], "actionAvailSpellIDs": [116, 2565, 6572]}},
    }


def action(name="a", key="F1", spell_id=116, label=""):
    return {"name": name, "key": key, "spellId": spell_id, "label": label}


def rule(name="a", when=None, **extra):
    return {"action": name, "when": ["always"] if when is None else when, **extra}


class CandidateEngineTests(unittest.TestCase):
    def test_native_focus_integer_boundaries(self):
        self.assertEqual(focus_unit('focus_party' + '0'*5000 + '2'), 'party2')
        self.assertEqual(focus_unit('focus_party2\0ignored'), 'party2')
        self.assertIsNone(focus_unit('focus_party\u00a02\u00a0'))
        self.assertIsNone(focus_unit('focus_party' + '9'*5000))

    def test_native_talent_integer_boundaries(self):
        config = {'token':'mage','groups':['a','b','c']}
        state = infer_role(config, EvaluationContext({'mage_talents':'0'*5000+'2/1/0'}))
        self.assertEqual((state.status,state.group,state.points),(2,'a',(2,1,0)))
        state = infer_role(config, EvaluationContext({'mage_talents':'2\0ignored/1/0'}))
        self.assertEqual(state.points,(2,1,0))
        self.assertEqual(infer_role(config, EvaluationContext({'mage_talents':'2/\u00a01/0'})).status,0)
        self.assertEqual(infer_role(config, EvaluationContext({'mage_talents':'9'*5000+'/1/0'})).status,0)

    def test_unknown_spec_and_action(self):
        engine = CandidateEngine(document([action()]))
        self.assertEqual(engine.generate("404", {}), [])
        self.assertEqual(engine.generate("1", {}, selected_rules=[rule("missing")]), [])

    def test_rule_parser_missing_is_different_from_null(self):
        rules = parse_rules([{}, {"action": "a"}, {"action": "a", "when": None},
                             {"action": "", "when": ["always"]}, rule("a", holdMs=True, offGcd=1)])
        self.assertEqual(len(rules), 2)
        self.assertIsNone(rules[0].when)
        self.assertEqual(rules[1].hold_ms, 0)
        self.assertFalse(rules[1].off_gcd)
        self.assertEqual(Action.from_json({"spellId": None}).spell_id, -1)

    def test_priority_all_matches_and_nonmatching_rules_count(self):
        engine = CandidateEngine(document([action("a"), action("b"), action("c")]))
        output = engine.generate(1, {}, selected_rules=[rule("a"), rule("b", ["unknown"]), rule("c")])
        self.assertEqual([(c.action, c.priority) for c in output], [("a", 1000), ("c", 990)])
        self.assertEqual([c.priority for c in engine.generate(1, {}, selected_rules=[{}, rule("a")])], [1000])

    def test_missing_and_disabled_actions_skip_expression_but_consume_priority(self):
        engine = CandidateEngine(document([action('a'), action('disabled',key=''), action('b')]))
        # 未提供未知可用性策略，若执行avail将抛UnsupportedSemantics。
        rules = [rule('missing',['avail',999]), rule('a'),
                 rule('disabled',['avail',999]), rule('b')]
        output = engine.generate(1, {}, selected_rules=rules)
        self.assertEqual([(c.action,c.priority) for c in output],[('a',995),('b',985)])
        output = engine.generate(1, {}, selected_rules=rules,key_overrides={'a':''})
        self.assertEqual([(c.action,c.priority) for c in output],[('b',985)])

    def test_missing_pre_action_keeps_main_candidate_and_pre_identity(self):
        engine = CandidateEngine(document([action('heal')]))
        output = engine.generate(1, {}, selected_rules=[rule('heal',pre='focus_party2')])
        self.assertEqual(len(output),1)
        self.assertEqual((output[0].action,output[0].pre_action,output[0].pre_key),
                         ('heal','focus_party2',''))

    def test_key_overrides_empty_disables_and_duplicate_actions_last_wins(self):
        engine = CandidateEngine(document([action(key="old"), action(key="new")]))
        self.assertEqual(engine.generate(1, {}, selected_rules=[rule()])[0].key, "new")
        self.assertEqual(engine.generate(1, {}, selected_rules=[rule()], key_overrides={"a": ""}), [])
        self.assertEqual(engine.generate(1, {}, selected_rules=[rule()], key_overrides={"a": "F6"})[0].key, "F6")
        with self.assertRaises(UnsupportedSemantics):
            engine.generate(1, {}, selected_rules=[rule()], key_overrides={"a": 1})

    def test_rule_fields_and_pre_key_lookup(self):
        engine = CandidateEngine(document([action(label="技能"), action("focus_party1", "CTRL-F1")]))
        output = engine.generate(1, {"aura": "OFF"}, selected_rules=[rule(when=["flag", "aura", False],
            reason="理由", tag="档位", holdMs=30000, pre="focus_party1")], key_overrides={"focus_party1": "ALT-F1"})
        candidate = output[0]
        self.assertEqual((candidate.label, candidate.reason, candidate.tag, candidate.hold_ms), ("技能", "理由", "档位", 30000))
        self.assertEqual((candidate.pre_action, candidate.pre_key, candidate.expect_off), ("focus_party1", "ALT-F1", ("aura",)))
        unknown = engine.generate(1, {}, selected_rules=[rule(pre="missing")])[0]
        self.assertEqual((unknown.pre_action, unknown.pre_key), ("missing", ""))

    def test_expect_off_native_selftest_cases(self):
        cases = [
            (["and", ["flag", "corruption", False], ["flag", "known", True]], ("corruption",)),
            (["flag", "aura", True], ()),
            (["and", ["flag", "seal_command", False], ["flag", "seal_righteousness", False]], ("seal_command", "seal_righteousness")),
            (["and", ["and", ["flag", "rend", False]]], ("rend",)),
            (["or", ["flag", "aura", False]], ()),
            (["not", ["flag", "aura", False]], ()),
            (["and", ["flag", "sw_hp", False], ["flag", "fortitude", False]], ("fortitude",)),
            (["and", ["flag", "corruption", False], ["flag", "corruption", False]], ("corruption",)),
            (["avail", 116], ()),
            (["flag", "aura", 0], ()),
        ]
        for expression, expected in cases:
            with self.subTest(expression=expression):
                self.assertEqual(collect_expect_off(expression), expected)
        engine = CandidateEngine(document([action()]))
        for hold in (0, -1):
            self.assertEqual(engine.generate(1, {"aura": "OFF"}, selected_rules=[rule(when=["flag", "aura", False], holdMs=hold)])[0].expect_off, ())

    def test_auto_target_native_selftest_candidates(self):
        engine = CandidateEngine(document())
        for key_index, expected in ((1, "F6"), (81, "ALT-END"), (28, "CTRL-F6")):
            ttd = PACKET_BASE + key_index * 8192 + 1024 + 7 * 32 + 1
            candidate = engine.generate(1, {"ttd": str(ttd)})[0]
            self.assertEqual((candidate.action, candidate.key, candidate.priority, candidate.hold_ms), ("auto_target", expected, 9000, 400))
            self.assertIn("回执7", candidate.reason)
        ttd = str(PACKET_BASE + 5 * 8192 + 1024 + 1)
        candidate = engine.generate(1, {"ttd": ttd, "gcd": "ON"})[0]
        self.assertEqual((candidate.key, candidate.priority, candidate.gcd_blocked), ("F10", 8950, True))
        self.assertEqual(engine.generate(1, {"ttd": ttd, "player_casting": "读条中: 116"}), [])

    def test_auto_target_non_request_states_and_invalid_packets(self):
        engine = CandidateEngine(document())
        for state in (0, 2, 3, 4):
            self.assertEqual(engine.generate(1, {"ttd": str(PACKET_BASE + 8192 + state * 1024 + 1)}), [])
        for value in (0, 16777215, PACKET_BASE - 1, PACKET_BASE + 1024 + 1, PACKET_BASE + 82 * 8192 + 1024 + 1):
            self.assertEqual(engine.generate(1, {"ttd": str(value)}), [])

    def test_off_gcd_native_selftest_registration(self):
        self.assertEqual(len(OFF_GCD_SPELL_IDS), 23)
        cases = [(2565, True), (6572, False), (23922, False), (20271, True),
                 (5277, True), (2139, True), (133, False), (116, False), (999999, False)]
        for spell_id, retained in cases:
            engine = CandidateEngine(document([action(spell_id=spell_id)]))
            self.assertEqual(bool(engine.generate(1, {"gcd": "ON"}, selected_rules=[rule()])), retained)
        for name in ("start_attack", "pet_attack", "auto_target"):
            engine = CandidateEngine(document([action(name, spell_id=-1)]))
            self.assertTrue(engine.generate(1, {"gcd": "ON"}, selected_rules=[rule(name)])[0].off_gcd)

    def test_off_gcd_native_selftest_end_to_end(self):
        engine = CandidateEngine(document([action("spell_6572", spell_id=6572), action("spell_2565", spell_id=2565)]))
        rules = [rule("spell_6572"), rule("spell_2565")]
        self.assertEqual([c.action for c in engine.generate(1, {"gcd": "OFF"}, selected_rules=rules)], ["spell_6572", "spell_2565"])
        self.assertEqual([c.action for c in engine.generate(1, {"gcd": "ON"}, selected_rules=rules)], ["spell_2565"])
        rules[0]["offGcd"] = True
        self.assertEqual([(c.action, c.priority) for c in engine.generate(1, {"gcd": "ON"}, selected_rules=rules)], [("spell_6572", 950), ("spell_2565", 945)])

    def test_casting_clears_all_even_off_gcd_but_sentinel_returns_first(self):
        engine = CandidateEngine(document([action(spell_id=2565)]))
        for value in ("读条中", "读条中 116", "引导", "引导中"):
            self.assertEqual(engine.generate(1, {"player_casting": value}, selected_rules=[rule()]), [])
        for value in ("空闲", "UNKNOWN", " 读条中", "casting"):
            self.assertEqual(len(engine.generate(1, {"player_casting": value}, selected_rules=[rule()])), 1)
        output = engine.generate(1, {"master_switch": "OFF", "player_casting": "读条中"})
        self.assertTrue(output[0].stop)

    def test_master_unknown_is_not_off(self):
        engine = CandidateEngine(document([action()]))
        for fields in ({}, {"master_switch": "UNKNOWN"}):
            self.assertEqual(engine.generate(1, fields, selected_rules=[rule()])[0].action, "a")
        output = engine.generate(1, {"master_switch": "OFF"}, selected_rules=[rule()])
        self.assertEqual((output[0].priority, output[0].label, output[0].reason), (1000000, "总开关已关闭", "原始停发理由"))

    def test_healer_master_exception_only_out_of_combat(self):
        role = {"token": "priest", "groups": ["戒律", "神圣", "暗影"], "roles": {"戒律": "HEALER", "神圣": "HEALER", "暗影": "RANGED"}}
        engine = CandidateEngine(document([action()], role=role))
        fields = {"master_switch": "OFF", "priest_talents": "10/0/0"}
        for combat in (None, "0", "—"):
            current = dict(fields)
            if combat is not None:
                current["combat_time"] = combat
            self.assertEqual(engine.generate(1, current, selected_rules=[rule()])[0].action, "a")
        self.assertTrue(engine.generate(1, dict(fields, combat_time="1"), selected_rules=[rule()])[0].stop)

    def test_role_unknown_gate_bypassed_by_loaded_rotation(self):
        role = {"token": "druid", "groups": ["平衡", "野性", "恢复"], "roles": {"平衡": "RANGED", "野性": "MELEE", "恢复": "HEALER"}}
        engine = CandidateEngine(document([action()], role=role))
        self.assertEqual(engine.generate(1, {})[0].label, "职责未读到")
        self.assertEqual(engine.generate(1, {}, selected_rules=[rule()])[0].action, "a")
        self.assertTrue(engine.generate(1, {}, selected_rules=[])[0].stop)
        engine = CandidateEngine(document([action()], rotations={"恢复": []}, role=role))
        self.assertEqual(engine.generate(1, {}), [])  # 非空 rotations map 即可跳过职责闸门。

    def test_role_parser_ties_zero_unknown_and_fallback_label(self):
        config = {"token": "mage", "groups": ["奥术", "火焰", "冰霜"]}
        self.assertEqual(infer_role(config, EvaluationContext({"mage_talents": "10/10/9"})).group, "奥术")
        self.assertEqual(infer_role(config, EvaluationContext({"mage_talents": "0/0/0"})).status, 1)
        self.assertEqual(infer_role(config, EvaluationContext({"mage_talents": "UNKNOWN"})).status, 0)
        self.assertEqual(infer_role({"token": "mage"}, EvaluationContext({"mage_talents": "0/0/1"})).group, "第3系")
        self.assertEqual(infer_role(config, EvaluationContext({"mage_talents": "1/2"})).status, 0)

    def test_builtin_selection_default_group_and_zero_single_role_fallback(self):
        role = {"token": "mage", "groups": ["奥术", "火焰", "冰霜"], "roles": {"奥术": "RANGED", "火焰": "RANGED", "冰霜": "RANGED"}}
        data = document([action("a"), action("b")], {"奥术": [rule("a")], "冰霜": [rule("b")]}, role=role)
        engine = CandidateEngine(data)
        self.assertEqual(engine.generate(1, {"mage_talents": "0/0/10"})[0].action, "b")
        self.assertEqual(engine.generate(1, {"mage_talents": "0/0/0"})[0].action, "a")
        self.assertEqual(engine.generate(1, {}), [])  # status0 不允许同职责回退。
        data["specs"]["1"]["rotations"][""] = [rule("a")]
        self.assertEqual(CandidateEngine(data).generate(1, {"mage_talents": "0/0/10"})[0].action, "a")
        self.assertEqual(CandidateEngine(data).generate(1, {}, selected_rules=[rule("b")])[0].action, "b")

    def test_focus_same_band_lowest_health_stable_ties(self):
        engine = CandidateEngine(document([action(), action("focus_party1"), action("focus_party2"), action("focus_party3")]))
        rules = [rule(pre="focus_party1", tag="same"), rule(pre="focus_party2", tag="same"), rule(pre="focus_party3", tag="same")]
        output = engine.generate(1, {"health_party1": "54", "health_party2": "20", "health_party3": "20"}, selected_rules=rules)
        self.assertEqual([c.pre_action for c in output], ["focus_party2", "focus_party3", "focus_party1"])
        self.assertEqual([c.priority for c in output], [1000, 995, 990])

    def test_focus_group_all_or_nothing_and_health_fallback(self):
        engine = CandidateEngine(document([action()]))
        rules = [rule(pre="focus_party1", tag="same"), rule(pre="focus_party2", tag="same")]
        for invalid in (None, "—", "-1", "16777215"):
            fields = {"health_party1": "54"}
            if invalid is not None:
                fields["health_party2"] = invalid
            self.assertEqual(engine.generate(1, fields, selected_rules=rules)[0].pre_action, "focus_party1")
        fields = {"health_party1": "54", "party2_health_pct": "20"}
        self.assertEqual(engine.generate(1, fields, selected_rules=rules)[0].pre_action, "focus_party2")
        rules[1]["tag"] = "different"
        self.assertEqual(engine.generate(1, fields, selected_rules=rules)[0].pre_action, "focus_party1")

    def test_focus_unit_native_integer_suffix(self):
        self.assertEqual(focus_unit("focus_player"), "player")
        for text in ("focus_party1", "focus_party01", "focus_party+1", "focus_party 1 "):
            self.assertEqual(focus_unit(text), "party1")
        for text in ("focus_party0", "focus_party5", "focus_partyX", "spell_633_focus", ""):
            self.assertIsNone(focus_unit(text))

    def test_generic_fill_first_available_no_override_no_off_gcd(self):
        engine = CandidateEngine(document([action("a", spell_id=116), action("b", key="F2", spell_id=2565)], generic=["missing", "a", "b"]))
        fields = {"action_avail": "4"}
        candidate = engine.generate(1, fields, key_overrides={"b": "F8"})[0]
        self.assertEqual((candidate.action, candidate.key, candidate.priority, candidate.hold_ms), ("b", "F2", 150, 1500))
        self.assertFalse(candidate.off_gcd)
        self.assertEqual(engine.generate(1, dict(fields, gcd="ON")), [])
        self.assertEqual(engine.generate(1, fields, selected_rules=[rule("a", ["unknown"])]), [])

    def test_generic_fill_disabled_for_healer(self):
        role = {"token": "priest", "groups": ["戒律", "神圣", "暗影"], "roles": {"戒律": "HEALER", "神圣": "HEALER", "暗影": "RANGED"}}
        engine = CandidateEngine(document([action()], generic=["a"], role=role))
        self.assertEqual(engine.generate(1, {"priest_talents": "10/0/0", "action_avail": "2"}), [])

    def test_does_not_mutate_supplied_rules(self):
        data = document([action()])
        rules = [rule(pre="missing", holdMs=100)]
        before = copy.deepcopy((data, rules))
        CandidateEngine(data).generate(1, {}, selected_rules=rules)
        self.assertEqual((data, rules), before)


if __name__ == "__main__":
    unittest.main()
