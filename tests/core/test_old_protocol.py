import json
from pathlib import Path
import unittest

from wowbuddy.candidates import CandidateEngine
from wowbuddy.old_protocol import OldDecoder, decode_identity
from wowbuddy.pixel_geometry import RGBImage, nearbyint

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = json.loads((ROOT / "assets/contract.json").read_bytes())
RULES = json.loads((ROOT / "assets/rules.json").read_bytes())


def render_old(spec_id, overrides=None, scale=1.0, truncate=None):
    """按原Lua次序写像素，模拟正常旧条；不调用被测decoder构造期望。"""
    spec = CONTRACT["specs"][str(spec_id)]
    definitions = CONTRACT["commonFields"] + spec["fields"] + spec["presenceFields"]
    overrides = {"spec_id": spec_id, "addon_version_code": CONTRACT["constants"]["expectedVersion"]} | (overrides or {})
    colors = []
    for definition in definitions:
        value = overrides.get(definition["id"], {"presence": 0x333333, "validity": 0xFF0000,
                        "switch": 0xFF0000, "playercast": 0xFF0001, "burst": 0xFFFF00}.get(definition["type"], 0))
        colors.append(value)
    rows = [[0x0D0D0D] * 24 for _ in range(nearbyint(max(132, len(colors) * 4 + 8) * scale) + 16)]
    for index, color in enumerate(colors):
        for y in range(nearbyint(index * 4 * scale), nearbyint((index + 1) * 4 * scale)):
            for x in range(nearbyint(4 * scale)):
                rows[y][x] = color
    for y in range(nearbyint(128 * scale), nearbyint(132 * scale)):
        for x in range(nearbyint(4 * scale), nearbyint(8 * scale)):
            rows[y][x] = 0xFF00FF
    return RGBImage(rows[:truncate] if truncate is not None else rows), colors


class OldProtocolTests(unittest.TestCase):
    def setUp(self):
        self.decoder = OldDecoder(CONTRACT)

    def test_all_nine_specs_have_full_ordered_frame(self):
        expected_counts = {1484:183, 1485:84, 1482:98, 1486:129, 1487:171,
                           1488:86, 1489:130, 1490:94, 1491:87}
        for spec, expected_count in expected_counts.items():
            with self.subTest(spec=spec):
                image, colors = render_old(spec)
                frame = self.decoder.decode(image)
                self.assertTrue(frame.ok, frame.status)
                self.assertEqual(frame.spec_id, str(spec))
                self.assertEqual(len(frame.rows), expected_count)
                self.assertEqual(frame.raw_colors, tuple(colors))
                self.assertFalse(frame.allow_unknown_availability)

    def test_identity_quotient_and_remainder_match_native(self):
        for raw, expected in ((0,(-1,-1)), (-1,(-1,-1)), (1482,(1482,-1)),
                              (1482*4096+2,(1482,2)), (1482*4096,(1482*4096,-1))):
            self.assertEqual(decode_identity(raw), expected)
        image, _ = render_old(1482, {"spec_id": 1482*4096+2})
        frame = self.decoder.decode(image)
        self.assertEqual((frame.spec_id, frame.hero_id), ("1482", 2))
        self.assertEqual(frame.values["spec_id"], str(1482*4096+2))

    def test_no_marker_and_wrong_version_request_readable_fallback(self):
        self.assertTrue(self.decoder.decode(RGBImage([[0]*24]*400)).fallback_readable)
        image, _ = render_old(1482, {"addon_version_code": 12345})
        frame = self.decoder.decode(image)
        self.assertEqual(frame.status, "version_mismatch")
        self.assertTrue(frame.fallback_readable)

    def test_unknown_spec_and_short_frame_are_not_silent_success(self):
        image, _ = render_old(1482, {"spec_id": 123})
        self.assertEqual(self.decoder.decode(image).status, "unknown_spec")
        image, _ = render_old(1482, truncate=200)
        frame = self.decoder.decode(image)
        self.assertEqual(frame.status, "out_of_bounds")
        self.assertFalse(frame.fallback_readable)

    def test_non_applicable_fields_stay_in_read_order_and_value_map(self):
        image, _ = render_old(1482, {"rage": 20})
        frame = self.decoder.decode(image)
        rage = next(row for row in frame.rows if row.key == "rage")
        self.assertFalse(rage.applicable)
        self.assertEqual(frame.values["rage"], "20")
        self.assertEqual(frame.values["distance"], "0.0")

    def test_mage_pixel_frame_to_real_rotation_candidates(self):
        hub = json.loads((ROOT / "assets/rotations.json").read_bytes())
        rotation = next(profile for profile in hub["rotations"] if profile["id"] == 1)
        spell_ids = RULES["specs"]["1482"]["actionAvailSpellIDs"]
        bitmap = 1 + sum(1 << (spell_ids.index(spell) + 1) for spell in (168,116))
        data = {"master_switch":0x00FF00, "player_valid":0x00FF00, "target_valid":0x00FF00,
                "target_health_pct":100, "player_health_pct":100, "distance":300,
                "intellect":0x00FF00, "known_168":0x00FF00, "known_116":0x00FF00,
                "range_116":0x00FF00, "action_avail":bitmap}
        engine = CandidateEngine(RULES)
        def candidates(overrides):
            image, _ = render_old(1482, data | overrides)
            frame = self.decoder.decode(image)
            self.assertTrue(frame.ok)
            return engine.generate(frame.spec_id, frame.values, selected_rules=rotation["rules"],
                                   allow_unknown_availability=frame.allow_unknown_availability)
        first = candidates({})
        self.assertEqual((first[0].action, first[0].key), ("spell_168", "NUMPAD2"))
        next_frame = candidates({"frost_armor":0x00FF00})
        self.assertEqual((next_frame[0].action, next_frame[0].key), ("spell_116", "NUMPAD5"))
        stopped = candidates({"target_valid":0xFF0000, "master_switch":0xFF0000})
        self.assertTrue(stopped[0].stop)


if __name__ == "__main__":
    unittest.main()
