"""原生反编译边界用例；这些不是原进程差分测试。"""

import unittest
import math

from wowbuddy.expressions import EvaluationContext, UnsupportedSemantics, evaluate


class ExpressionsTest(unittest.TestCase):
    def test_unknown_flag_is_not_off(self):
        context = EvaluationContext({"x": "UNKNOWN", "y": " off extra"})
        self.assertFalse(evaluate(["flag", "missing", False], context))
        self.assertFalse(evaluate(["flag", "x", False], context))
        self.assertTrue(evaluate(["flag", "y", False], context))
        self.assertTrue(evaluate(["not", ["flag", "missing", True]], context))

    def test_json_bool_conversion_does_not_use_truthiness(self):
        context = EvaluationContext({"off": "OFF", "on": "ON", "": "OFF"})
        for wrong_type in (None, 1, "true", [], {}):
            self.assertTrue(evaluate(["flag", "off", wrong_type], context))
            self.assertFalse(evaluate(["flag", "on", wrong_type], context))
        self.assertTrue(evaluate(["flag", 123, False], context))

    def test_literal_space_separator(self):
        context = EvaluationContext({"on": "ON note", "tab": "ON\tnote", "n": " 12.5 秒 "})
        self.assertEqual(context.flag("on"), 1)
        self.assertEqual(context.flag("tab"), -1)
        self.assertEqual(context.number("n"), 12.5)

    def test_missing_and_invalid_numeric_fields(self):
        context = EvaluationContext({"dash": "—", "suffix": "20%", "zero": "0", "bad": "garbage"})
        for key in ("missing", "dash", "suffix", "bad"):
            self.assertFalse(evaluate(["num_below", key, 100], context))
            self.assertFalse(evaluate(["ready", key], context))
        self.assertTrue(evaluate(["num_at_least", "zero", "99"], context))
        self.assertFalse(evaluate(["num_below", "zero", True], context))

    def test_short_circuit_and_empty_logic(self):
        context = EvaluationContext({})
        self.assertTrue(evaluate(["and"], context))
        self.assertFalse(evaluate(["or"], context))
        self.assertFalse(evaluate(["not"], context))
        self.assertFalse(evaluate(["and", ["unknown"], ["avail", 116]], context))
        self.assertTrue(evaluate(["or", ["always"], ["avail", 116]], context))
        self.assertTrue(evaluate(["not", [], ["always"]], context))
        for invalid in (None, {}, True, [], [True], "always", ["ALWAYS"]):
            self.assertFalse(evaluate(invalid, context))

    def test_availability_bit_zero_reserved_and_fallback(self):
        context = EvaluationContext({"action_avail": "5", "ready_116": "ON", "spell_120_ready": "OFF"}, (116, 133))
        self.assertFalse(evaluate(["avail", 116], context))  # bit 1 is zero; do not fallback.
        self.assertTrue(evaluate(["avail", 133], context))
        self.assertFalse(evaluate(["avail", 120], context))
        context = EvaluationContext({"action_avail": "bad", "ready_116": "UNKNOWN", "spell_116_ready": "ON"}, (116,))
        self.assertTrue(evaluate(["avail", 116], context))

    def test_availability_policy_is_explicit(self):
        with self.assertRaises(UnsupportedSemantics):
            evaluate(["avail", 116], EvaluationContext({}))
        self.assertFalse(evaluate(["avail", 116], EvaluationContext({}, allow_unknown_availability=False)))
        self.assertTrue(evaluate(["avail", 116], EvaluationContext({}, allow_unknown_availability=True)))
        context = EvaluationContext({"ready_0": "ON"})
        for invalid_id in (True, "116", 116.5, None, 2**40):
            self.assertTrue(evaluate(["avail", invalid_id], context))

    def test_long_availability_text_keeps_native_parse_and_fallback(self):
        fields = {'action_avail': '0'*5000+'2', 'ready_116': 'OFF'}
        self.assertEqual(EvaluationContext(fields, (116,)).availability(116), 1)
        fields['action_avail'] = '-'+'0'*5000+'2'
        self.assertEqual(EvaluationContext(fields, (116,)).availability(116), 1)
        fields['action_avail'] = '9'*5000
        self.assertEqual(EvaluationContext(fields, (116,)).availability(116), 0)
        fields.pop('ready_116')
        fields['spell_116_ready'] = 'ON'
        self.assertEqual(EvaluationContext(fields, (116,)).availability(116), 1)

    def test_readiness_boundary_and_enemy_fallback(self):
        context = EvaluationContext({"cd": "0.05", "active_enemies": "2.9 个"})
        self.assertTrue(evaluate(["ready", "cd"], context))
        self.assertFalse(evaluate(["num_below", "cd", 0.05], context))
        self.assertTrue(evaluate(["num_at_least", "cd", 0.05], context))
        self.assertFalse(evaluate(["enemies_at_least", 3], context))
        self.assertTrue(evaluate(["enemies_at_least", 0], EvaluationContext({})))

    def test_injured_strict_threshold_and_friendly_gate(self):
        context = EvaluationContext({"health_player": "50", "player_health_pct": "10", "friendly_party1": "ON", "party1_health_pct": "49", "health_party2": "1"})
        self.assertTrue(evaluate(["injured_at_least", 50, 1], context))
        self.assertFalse(evaluate(["injured_at_least", 50, 2], context))
        self.assertTrue(evaluate(["injured_at_least", 0, 0], context))
        self.assertTrue(evaluate(["injured_at_least", 51, 2], context))

    def test_interruptible_color_mask(self):
        for value, expected in (("#00ff00", True), ("#00FFFF", True), ("#01ff00", False), (" #00ff00", False), ("ON", False)):
            with self.subTest(value=value):
                self.assertEqual(evaluate(["interruptible", "cast"], EvaluationContext({"cast": value})), expected)

    def test_interruptible_native_hex_conversion(self):
        for value in ('#+0ff00', '# 0ff00', '#0ff00 ', '#\t0ff00', '#0xff00', '#0Xff00', '#ff00\0x'):
            with self.subTest(value=value):
                self.assertTrue(evaluate(['interruptible', 'cast'], EvaluationContext({'cast': value})))
        for value in ('#-0ff00', '#++ff00', '#0xgg00', '#00ff0_', '#0ff00', '#\u00a00ff00', '#ff00\0😀'):
            with self.subTest(value=value):
                self.assertFalse(evaluate(['interruptible', 'cast'], EvaluationContext({'cast': value})))

    def test_unresolved_or_non_native_inputs_are_not_silently_accepted(self):
        with self.assertRaises(UnsupportedSemantics):
            EvaluationContext({"x": True}).flag("x")

    def test_native_special_numbers_and_enemy_conversion(self):
        self.assertTrue(math.isnan(EvaluationContext({'n': 'NaN'}).number('n')))
        for text in ('+nan', '-nan', 'infinity', '+infinity', '-infinity'):
            self.assertIsNone(EvaluationContext({'n': text}).number('n'))
        for text in ('nan', 'inf', '-inf', '2147483648', '-2147483649'):
            context = EvaluationContext({'active_enemies': text})
            self.assertFalse(evaluate(['enemies_at_least', 0], context))
            self.assertTrue(evaluate(['enemies_at_least', -2147483648], context))
        context = EvaluationContext({'active_enemies': '-2147483648.9'})
        self.assertTrue(evaluate(['enemies_at_least', -2147483648], context))
        for op in ('ready', 'num_at_least', 'num_below'):
            args = ['n'] if op == 'ready' else ['n', 0]
            self.assertFalse(evaluate([op, *args], EvaluationContext({'n': 'nan'})))
        self.assertTrue(evaluate(['num_at_least', 'n', 100], EvaluationContext({'n': 'inf'})))
        self.assertTrue(evaluate(['ready', 'n'], EvaluationContext({'n': '-inf'})))

    def test_native_numeric_range_failure_is_unknown_not_exception(self):
        for text in ('1e999', '-1e999', '1e-999', '-1e-999', '2e-324',
                     '1.7976931348623159e308'):
            context = EvaluationContext({'n': text})
            with self.subTest(text=text):
                self.assertIsNone(context.number('n'))
                self.assertFalse(evaluate(['ready', 'n'], context))
                self.assertFalse(evaluate(['num_below', 'n', 1], context))
                self.assertFalse(evaluate(['num_at_least', 'n', 0], context))
        self.assertEqual(EvaluationContext({'n': '5e-324'}).number('n'), 5e-324)
        self.assertEqual(EvaluationContext({'n': '0e-999'}).number('n'), 0)


if __name__ == "__main__":
    unittest.main()
