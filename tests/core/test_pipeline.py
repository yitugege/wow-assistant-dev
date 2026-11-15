"""真实资源、合成图像贯穿协议选择、阈值、候选层；不发送按键。"""
from copy import deepcopy
import json
import unittest

from test_old_protocol import CONTRACT, ROOT, RULES, render_old
from test_readable_protocol import image_with_rows
from wowbuddy.engine.pipeline import DecisionPipeline, readable_key_maps
from wowbuddy.core.pixel_geometry import RGBImage

READABLE = json.loads((ROOT / "assets/contract_readable.json").read_bytes())
READABLE_RULES = json.loads((ROOT / "assets/rules_readable.json").read_bytes())


def render_readable(spec_id=1482, overrides=None, *, pitch=4):
    spec = READABLE["specs"][str(spec_id)]
    values = {"spec_id": spec_id, "master_switch": 0x00FF00,
              "player_health_pct": 100, "target_health_pct": 100,
              "player_casting": 0xFF0000, "gcd": 0xFF0000} | (overrides or {})
    colors = {row: values.get(key, 0) for key, row in zip(spec["classicKeys"], spec["classicRows"]) if row >= 0}
    colors.update({entry["row"]: values.get(entry["key"], 0x333333)
                   for entry in spec["presenceFields"] if entry["row"] >= 0})
    return image_with_rows(colors, x=30, pitch=pitch,
                           height=max(1500, 2 + pitch * (max(colors) + 1)))


def combined(old_image, readable_image):
    rows = [list(row) for row in readable_image.rows]
    for y, row in enumerate(old_image.rows):
        rows[y][:old_image.width] = row
    return RGBImage(rows)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.pipeline = DecisionPipeline(CONTRACT, READABLE, RULES, READABLE_RULES)
        self.profile = {"specId": 1482, "rules": [{"action": "spell_116", "when": ["always"]}]}

    def test_old_has_priority_when_both_markers_are_present(self):
        old, _ = render_old(1482, {"master_switch": 0x00FF00})
        result = self.pipeline.evaluate(combined(old, render_readable()), selected_profile=self.profile)
        self.assertEqual(result.frame.protocol, "old")
        self.assertIsNone(result.old_attempt)
        self.assertEqual(result.candidates[0].key, "NUMPAD5")

    def test_independent_pause_hint_distinguishes_no_target_from_saved_switch(self):
        from wowbuddy.core.dev_protocol import DEV_VERSION
        fields = {"master_switch": 0xff0000, "player_in_combat": 0xff0000, "target_valid": 0xff0000}
        original, _ = render_old(1482, fields)
        original_stop = self.pipeline.evaluate(original).candidates[0]
        self.assertTrue(original_stop.stop)
        self.assertEqual(original_stop.reason, RULES['sentinel']['stopReason'])
        independent, _ = render_old(1482, fields | {"addon_version_code": DEV_VERSION})
        independent_stop = self.pipeline.evaluate(independent).candidates[0]
        self.assertTrue(independent_stop.stop)
        self.assertIn('已脱战且没有可攻击目标', independent_stop.reason)

        self.pipeline.unattended_travel = True
        traveling_stop = self.pipeline.evaluate(independent).candidates[0]
        self.assertTrue(traveling_stop.stop)
        self.assertEqual(traveling_stop.reason, '无人托管正在执行陆路计划，脱战时暂停技能循环。')
        self.assertEqual(self.pipeline.evaluate(original).candidates[0].reason, original_stop.reason)

    def test_readable_fixture_preserves_all_fields_at_supported_pitches(self):
        for spec in READABLE['specs']:
            baseline=self.pipeline.evaluate(render_readable(int(spec))).frame
            self.assertTrue(baseline.ok)
            for pitch in range(3,10):
                with self.subTest(spec=spec,pitch=pitch):
                    frame=self.pipeline.evaluate(render_readable(int(spec),pitch=pitch)).frame
                    self.assertTrue(frame.ok)
                    self.assertEqual(frame.values,baseline.values)
                    self.assertEqual(frame.spec_id,baseline.spec_id)

    def test_old_bad_header_falls_back_and_readable_only_replaces_key(self):
        old, _ = render_old(1482, {"addon_version_code": 12345})
        result = self.pipeline.evaluate(combined(old, render_readable()), selected_profile=self.profile)
        self.assertEqual(result.frame.protocol, "readable")
        self.assertEqual(result.old_attempt.status, "version_mismatch")
        self.assertEqual(result.candidates[0].label, "寒冰箭")
        expected_key = next(a["key"] for a in READABLE_RULES["specs"]["1482"]["actions"] if a["name"] == "spell_116")
        self.assertEqual(result.candidates[0].key, expected_key)
        self.assertTrue(result.frame.allow_unknown_availability)

    def test_protocol_fallback_keeps_the_verified_target_policy(self):
        from wowbuddy.core.dev_protocol import DEV_VERSION

        readable = render_readable()
        profile = self.profile
        before = self.pipeline.evaluate(readable, selected_profile=profile)
        self.assertEqual(before.candidates[0].action, 'spell_116')
        independent, _ = render_old(1482, {'addon_version_code': DEV_VERSION,
            'master_switch': 0x00ff00, 'player_valid': 0x00ff00, 'target_valid': 0x00ff00,
            'player_casting': 0xff0000, 'action_avail': 0xffffff})
        rows = [list(row) for row in combined(independent, readable).rows]
        for start, packet in (
            (34, (0x574244, 7 * 256, 0xffffff, 0xffffff, 0, 0xffffff, 0xffffff)),
            (132, (0x574251, 7, 1, 1, 0, 0, 0)),
        ):
            checksum = 0
            for word in packet:
                checksum = (checksum * 31 + word) % 0xfefffd
            for index, word in enumerate((*packet, checksum), start):
                for y in range(index * 4, (index + 1) * 4):
                    rows[y][6] = word
        confirmed = self.pipeline.evaluate(RGBImage(rows), selected_profile=profile)
        self.assertEqual(confirmed.fields['mob_policy'], 'ON')
        self.assertEqual(confirmed.candidates[0].action, 'spell_116')

        untrusted_old, _ = render_old(1482, {'addon_version_code': 12345})
        for image in (readable, combined(untrusted_old, readable), render_readable(overrides={'target_health_pct': 0})):
            result = self.pipeline.evaluate(image, selected_profile=profile)
            self.assertEqual(result.frame.protocol, 'readable')
            self.assertTrue(result.frame.ok)
            self.assertEqual(result.fields['mob_policy'], 'ON')
            self.assertIn('当前协议无法确认怪物归属', result.target_rejection)
            self.assertFalse(any(candidate.key for candidate in result.candidates))

        restored = self.pipeline.evaluate(RGBImage(rows), selected_profile=profile)
        self.assertEqual(restored.candidates[0].action, 'spell_116')

    def test_valid_old_header_unknown_spec_does_not_fall_back(self):
        old, _ = render_old(1482, {"spec_id": 123})
        result = self.pipeline.evaluate(combined(old, render_readable()))
        self.assertEqual((result.frame.protocol, result.frame.status), ("old", "unknown_spec"))
        self.assertEqual(result.candidates, ())
        self.assertIsNone(result.old_attempt)

    def test_protocol_changes_do_not_leak_override_or_last_action(self):
        new = self.pipeline.evaluate(render_readable(), selected_profile=self.profile)
        self.assertTrue(new.frame.ok)
        old, _ = render_old(1482, {"master_switch": 0x00FF00})
        result = self.pipeline.evaluate(old, selected_profile=self.profile)
        self.assertEqual(result.candidates[0].key, "NUMPAD5")
        failed = self.pipeline.evaluate(RGBImage([]))
        self.assertEqual(failed.frame.status, "no_marker")
        self.assertEqual((failed.fields, failed.candidates), ({}, ()))

    def test_threshold_settings_control_real_frame_rule(self):
        rules = deepcopy(RULES)
        rules["switchFields"] = [{"field": "player_health_pct", "label": "生命", "max": 100, "unit": "%"}]
        pipeline = DecisionPipeline(CONTRACT, READABLE, rules, READABLE_RULES)
        profile = {"specId": 1482, "rules": [{"action": "spell_116", "when": ["num_below", "player_health_pct", 60]}]}
        image, _ = render_old(1482, {"master_switch": 0x00FF00, "player_health_pct": 50})
        result = pipeline.evaluate(image, selected_profile=profile)
        self.assertEqual(result.candidates[0].action, "spell_116")
        key = result.thresholds[0].key
        self.assertEqual(result.fields[key], "ON")
        self.assertNotIn(key, result.frame.values)
        for threshold in (0, 50):
            disabled = pipeline.evaluate(image, selected_profile=profile, settings={key: threshold})
            self.assertEqual(disabled.fields[key], "OFF")
            self.assertEqual(disabled.candidates, ())

    def test_readable_does_not_install_new_actions_or_rotations(self):
        rules = deepcopy(READABLE_RULES)
        rules["specs"]["1482"]["actions"].append({"name": "invented", "key": "F1", "spellId": 1})
        rules["specs"]["1482"]["rotations"] = {"": [{"action": "invented", "when": ["always"]}]}
        pipeline = DecisionPipeline(CONTRACT, READABLE, RULES, rules)
        profile = {"specId": 1482, "rules": [{"action": "invented", "when": ["always"]}]}
        self.assertEqual(pipeline.evaluate(render_readable(), selected_profile=profile).candidates, ())

    def test_shipped_invalid_readable_bindings_do_not_create_base_actions(self):
        from wowbuddy.core.keybindings import parse_keybinding
        checked=0
        for spec,definition in READABLE_RULES['specs'].items():
            base={a['name'] for a in RULES['specs'][spec]['actions']}
            for action in definition['actions']:
                if parse_keybinding(action['key']).valid:continue
                with self.subTest(spec=spec,action=action['name']):
                    self.assertNotIn(action['name'],base)
                    profile={'specId':int(spec),'rules':[{'action':action['name'],'when':['always']}]}
                    for image in (render_readable(int(spec)),
                                  render_old(int(spec),{'master_switch':0x00ff00})[0]):
                        result=self.pipeline.evaluate(image,selected_profile=profile)
                        self.assertTrue(result.frame.ok)
                        self.assertEqual(result.candidates,())
                    checked+=1
        self.assertEqual(checked,10)

    def test_readable_loader_preserves_literal_keys_and_last_valid_value(self):
        entries = [{"name": "x", "key": "F1"}, {"name": "x", "key": ""}, {"name": "y", "key": 1},
                   {"name": "", "key": "F2"}, {"name": "z", "key": "CTRL-" + "\\" * 4}]
        self.assertEqual(readable_key_maps({"specs": {"1": {"actions": entries}, "2": {}}}),
                         {"1": {"x": "F1", "z": "CTRL-" + "\\" * 4}})


if __name__ == "__main__":
    unittest.main()
