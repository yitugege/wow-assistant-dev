"""readable 原生几何、契约选择及整帧转换的离线边界回放。"""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest

from wowbuddy.pixel_geometry import BarGeometry, RGBImage
from wowbuddy.readable_protocol import (
    MARKERS, ReadableDecoder, locate_readable_bar, readable_field_type, sample_readable_rows,
)


def rgb(parts):
    return (parts[0] << 16) | (parts[1] << 8) | parts[2]


def image_with_rows(colors, *, x=20, y=2, pitch=4, height=None, width=64):
    height = height or y + pitch * (max(colors, default=2) + 1)
    pixels = [[0x0D0D0D] * width for _ in range(height)]
    for row, color in {0: rgb(MARKERS[0]), 1: rgb(MARKERS[1]), 2: rgb(MARKERS[2]), **colors}.items():
        for yy in range(int(y + row * pitch), min(height, int(y + (row + 1) * pitch))):
            for xx in range(x, min(width, int(x + pitch))):
                pixels[yy][xx] = color
    return RGBImage(pixels)


def contract():
    keys = ["spec_id", "addon_version_code", "master_switch", "isMoving",
            "player_health_pct", "target_health_pct", "party1_health_pct",
            "party2_health_pct", "party3_health_pct", "party4_health_pct", "druid_form",
            "spell_5221_ready", "ttf", "trinket1_cd", "ttd", "player_casting"]
    spec = {"classicKeys": keys, "classicRows": list(range(8, 8 + len(keys))),
            "presenceRows": [31, 30],
            "presenceFields": [{"key": "aura_first", "row": 30},
                               {"key": "aura_second", "row": 31, "kind": "cd_seconds"},
                               {"key": "ignored", "row": 32, "kind": "text"}]}
    return {"header": {"addonVersionCode": 999}, "specs": {"1489": spec}}


class ReadableGeometryTests(unittest.TestCase):
    def test_native_argb_distinguishes_black_from_missing_and_out_of_bounds(self):
        image=image_with_rows({3:0,4:0x010203})
        geometry=locate_readable_bar(image)
        self.assertEqual(sample_readable_rows(image,geometry,[-1,3,4,999],native_argb=True),
                         [0,0xff000000,0xff010203,0])
        self.assertEqual(sample_readable_rows(image,geometry,[-1,3,4,999]),[0,0,0x010203,0])

    def test_exact_markers_all_native_pitch_limits(self):
        for pitch in range(3, 10):
            with self.subTest(pitch=pitch):
                found = locate_readable_bar(image_with_rows({}, pitch=pitch))
                self.assertEqual(found, BarGeometry(20., 2., pitch, pitch, pitch / 4, 20, 2))

    def test_marker_tolerance_and_spacing_jitter(self):
        pixels = [[0] * 50 for _ in range(140)]
        for (x, y), marker in zip(((47, 119), (45, 123), (46, 128)), MARKERS):
            pixels[y][x] = rgb(tuple(c + 3 for c in marker))
        found = locate_readable_bar(RGBImage(pixels))
        self.assertEqual(found.pitch, 4.5)
        self.assertEqual((found.anchor_x, found.anchor_y), (47, 119))
        pixels[128][46] = rgb((MARKERS[2][0] + 4, *MARKERS[2][1:]))
        self.assertIsNone(locate_readable_bar(RGBImage(pixels)))

    def test_scan_limits_and_invalid_spacing(self):
        for x, y, pitch in ((48, 2, 4), (20, 120, 4), (20, 2, 2), (20, 2, 10)):
            self.assertIsNone(locate_readable_bar(image_with_rows({}, x=x, y=y, pitch=pitch)))
        pixels = [list(row) for row in image_with_rows({}).rows]
        # 第三标记移到 y=12，与第一段4像素、第二段6像素不一致。
        for y in range(10, 12):
            pixels[y][20:24] = [0] * 4
        self.assertIsNone(locate_readable_bar(RGBImage(pixels)))

    def test_first_decoy_is_not_skipped(self):
        pixels = [list(row) for row in image_with_rows({}, y=20).rows]
        pixels[0][0] = rgb(MARKERS[0])
        self.assertIsNone(locate_readable_bar(RGBImage(pixels)))

    def test_empty_truncated_marker(self):
        self.assertIsNone(locate_readable_bar(RGBImage([])))
        self.assertIsNone(locate_readable_bar(RGBImage([[rgb(MARKERS[0])]])))

    def test_sampler_missing_and_outside_rows_keep_zero(self):
        image = image_with_rows({3: 0x010203})
        geometry = locate_readable_bar(image)
        self.assertEqual(sample_readable_rows(image, geometry, [-1, 3, 4, 999]), [0, 0x010203, 0, 0])
        self.assertEqual(sample_readable_rows(image, None, [0]), [])

    def test_sampler_truncates_x_and_y_and_uses_pitch_for_width(self):
        pixels = [[100 * y + x for x in range(8)] for y in range(20)]
        geometry = BarGeometry(1.2, .8, 3.5, 500., 1., 0, 0)
        # x=trunc(1.2+1.75)=2；row1=[4,7)，内部唯一样本 y=5。
        self.assertEqual(sample_readable_rows(RGBImage(pixels), geometry, [1]), [502])
        self.assertEqual(sample_readable_rows(RGBImage(pixels), replace(geometry, origin_x=999), [1]), [507])

    def test_sampler_invalid_input_is_explicit(self):
        image = image_with_rows({})
        geometry = locate_readable_bar(image)
        with self.assertRaises(ValueError):
            sample_readable_rows(image, replace(geometry, pitch=float('nan')), [0])
        with self.assertRaises(TypeError):
            sample_readable_rows(image, geometry, [1.5])


class ReadableDecoderTests(unittest.TestCase):
    def setUp(self):
        self.contract = contract()
        self.decoder = ReadableDecoder({}, self.contract)

    def test_all_name_inference_branches(self):
        cases = {"burst": "burst", "distance": "distance", "foo_health_pct": "health",
                 "spell_1_ready": "switch", "aoe_mode": "count", "active_enemies": "count",
                 "enemies_8yd": "count", "trinket1_cd": "cooldown", "trinket2_cd": "cooldown",
                 "isMoving": "switch", "player_casting": "switch", "target_is_enemy_player": "switch",
                 "focus_cast_unreachable": "switch", "_forever_healing_mode": "switch",
                 "mana": "number", "ttd": "number", "cast_remaining": "number",
                 "BURST": "number", "x_Ready": "number", "target_cast_unreachable": "number"}
        for key, expected in cases.items():
            self.assertEqual(readable_field_type(key), expected, key)

    def test_main_values_and_presence_membership_order(self):
        frame = self.decoder.decode(image_with_rows({8: 1489, 9: 123, 10: 0x00FF00,
                                                     11: 0x35D50F, 21: 123, 22: 601,
                                                     23: 0x00FF01, 30: 0x333333, 31: 0x00FF00}))
        self.assertTrue(frame.ok)
        self.assertEqual(frame.version_code, 123)  # 不与header999比较。
        self.assertEqual(frame.values["master_switch"], "ON")
        self.assertEqual(frame.values["isMoving"], "ON")  # 此RGB落入switch绿色阈值；旧type isMoving为—。
        self.assertEqual(frame.values["trinket1_cd"], "12.3")
        self.assertEqual(frame.values["ttd"], "601")
        self.assertEqual(frame.values["player_casting"], "ON")
        self.assertEqual([r.key for r in frame.rows[-2:]], ["aura_first", "aura_second"])
        self.assertEqual(frame.values["aura_first"], "OFF")
        self.assertEqual(frame.values["aura_second"], "ON")  # kind被原生忽略。
        self.assertNotIn("ignored", frame.values)
        self.assertTrue(frame.allow_unknown_availability)

    def test_readable_identity_shifts_even_zero_remainder(self):
        for encoded in (1489, 1489 << 12, (1489 << 12) + 123):
            frame = self.decoder.decode(image_with_rows({8: encoded, 9: 0}))
            self.assertEqual(frame.spec_id, "1489")
            self.assertTrue(frame.ok)
            self.assertIsNone(frame.version_code)

    def test_failure_statuses(self):
        self.assertEqual(self.decoder.decode(RGBImage([[0]])).status, "no_marker")
        self.assertEqual(self.decoder.decode(image_with_rows({8: 0})).status, "unknown_spec")
        self.assertEqual(self.decoder.decode(image_with_rows({8: 777})).status, "unknown_spec")

    def test_generic_identity_uses_1489_layout(self):
        spec = deepcopy(self.contract["specs"]["1489"])
        spec["classicRows"][0] = 40
        self.contract["specs"]["777"] = spec
        frame = ReadableDecoder({}, self.contract).decode(image_with_rows({8: 777, 40: 888}))
        self.assertEqual(frame.spec_id, "777")
        self.assertEqual(frame.values["spec_id"], "888")
        del self.contract["specs"]["1489"]
        self.assertEqual(ReadableDecoder({}, self.contract).decode(image_with_rows({40: 777})).status,
                         "unknown_spec")

    def test_health_and_friendly_conversion(self):
        frame = self.decoder.decode(image_with_rows({8: 1489, 12: 0, 13: 0xFFFFFF,
                                                     14: 0x010000, 15: 0, 16: 0xFFFFFF,
                                                     17: 255, 18: 3}))
        self.assertEqual(frame.values["player_valid"], "OFF")
        self.assertEqual(frame.values["target_valid"], "OFF")
        self.assertNotIn("health_player", frame.values)
        self.assertNotIn("health_target", frame.values)
        self.assertEqual(frame.values["target_health_pct"], "255")
        self.assertEqual(frame.values["health_party1"], "0")
        self.assertEqual(frame.values["friendly_party1"], "ON")
        self.assertEqual(frame.values["health_party2"], "UNKNOWN")
        self.assertEqual(frame.values["friendly_party2"], "OFF")
        self.assertEqual(frame.values["health_party3"], "UNKNOWN")
        self.assertEqual(frame.values["health_party4"], "255")
        self.assertEqual(frame.values["form"], "3")

    def test_positive_player_target_and_configured_no_value(self):
        decoder = ReadableDecoder({"constants": {"noValue": 123}}, self.contract)
        frame = decoder.decode(image_with_rows({8: 1489, 12: 0x010054, 13: 123}))
        self.assertEqual(frame.values["health_player"], "84")
        self.assertEqual(frame.values["player_valid"], "ON")
        self.assertEqual(frame.values["target_valid"], "OFF")

    def test_missing_classic_row_decodes_zero_but_no_derived_alias(self):
        self.contract["specs"]["1489"]["classicRows"][4] = -1
        frame = ReadableDecoder({}, self.contract).decode(image_with_rows({8: 1489}))
        self.assertEqual(frame.values["player_health_pct"], "0")
        self.assertNotIn("player_valid", frame.values)
        self.assertNotIn("health_player", frame.values)
        self.assertEqual(frame.raw_colors[4], 0)

    def test_out_of_window_field_is_zero_without_frame_failure(self):
        # 原生只检查返回数组长度，单行越界补零后仍长度相等。
        frame = self.decoder.decode(image_with_rows({8: 1489}, height=38))
        self.assertTrue(frame.ok)
        self.assertEqual(frame.values["master_switch"], "#000000")
        self.assertEqual(frame.values["aura_first"], "UNKNOWN")

    def test_legacy_overlay_exact_green_overwrites_ready(self):
        image = image_with_rows({8: 1489, 19: 0x00FF00}, height=200)
        pixels = [list(row) for row in image.rows]
        for y in range(192):
            pixels[y][0:4] = [0x00FF01 if y // 4 in (1, 27) else 0x00FF00] * 4
        for y in range(128, 132):
            pixels[y][4:8] = [0xFF00FF] * 4
        frame = self.decoder.decode(RGBImage(pixels))
        self.assertTrue(frame.legacy_overlay)
        self.assertEqual(frame.values["mark_wild"], "ON")
        self.assertEqual(frame.values["thorns"], "OFF")
        self.assertEqual(frame.values["spell_5221_ready"], "OFF")
        self.assertEqual(frame.values["spell_774_ready"], "ON")

    def test_ocr_timeline_receipt_metadata_not_consumed(self):
        self.contract["specs"]["1489"].update(textRow=999, receiptStart=1000,
                                               timeEncoding="unsupported-test")
        frame = ReadableDecoder({}, self.contract).decode(image_with_rows({8: 1489}))
        self.assertTrue(frame.ok)
        self.assertNotIn("receipt", frame.values)
        self.assertNotIn("text", frame.values)

    def test_mismatched_contract_rejected(self):
        self.contract["specs"]["1489"]["classicRows"].pop()
        with self.assertRaisesRegex(ValueError, "行表不一致"):
            ReadableDecoder({}, self.contract)

    def test_every_bundled_spec_decodes_synthetic_frame(self):
        unpacked = Path(__file__).resolve().parents[2] / "assets"
        if not (unpacked / "contract_readable.json").exists():
            self.skipTest("打包后的测试环境不含原始契约")
        readable = json.loads((unpacked / "contract_readable.json").read_text(encoding="utf8"))
        old = json.loads((unpacked / "contract.json").read_text(encoding="utf8"))
        decoder = ReadableDecoder(old, readable)
        common = readable["specs"]["1489"]
        spec_row = common["classicRows"][common["classicKeys"].index("spec_id")]
        for spec_id in readable["specs"]:
            with self.subTest(spec_id=spec_id):
                definitions = decoder.field_definitions(spec_id)
                colors = {r: 0x333333 for _, _, r in definitions if r >= 0}
                colors[spec_row] = int(spec_id)
                frame = decoder.decode(image_with_rows(colors))
                self.assertTrue(frame.ok)
                self.assertEqual(frame.spec_id, spec_id)
                self.assertEqual(len(frame.rows), len(definitions))


if __name__ == "__main__":
    unittest.main()
