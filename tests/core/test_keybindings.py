"""原生按键边界、包内绑定覆盖与已运行原版自测的差分；不发送按键。"""

from pathlib import Path
import json
import re
import unittest

from wowbuddy.keybindings import KeyBinding, KEY_VKS, is_extended_key, parse_keybinding


ROOT = Path(__file__).resolve().parents[2]
NATIVE_REPORT = Path("D:/reverse-analysis/wow-assistant/reconstruction/evidence/native-selftests/original-48sb9f0n/runtime/_selftest.txt")


class KeyBindingTests(unittest.TestCase):
    def test_letters_digits_function_and_numpad_ranges(self):
        for key, expected in (("A", 65), ("Z", 90), ("0", 48), ("9", 57),
                              ("F1", 112), ("F12", 123),
                              ("NUMPAD0", 96), ("NUMPAD9", 105)):
            with self.subTest(key=key):
                self.assertEqual(parse_keybinding(key), KeyBinding(expected, (), True))

    def test_complete_named_and_punctuation_table(self):
        # 独立列出 PE 构造器中的固定项，避免只检查当前使用的 NUMPAD。
        vectors = {
            ";": 186, ":": 186, "=": 187, ",": 188, "-": 189, ".": 190,
            "/": 191, "`": 192, "[": 219, "\\": 220, "]": 221, "'": 222,
            "INSERT": 45, "DELETE": 46, "HOME": 36, "END": 35,
            "PAGEUP": 33, "PAGEDOWN": 34, "UP": 38, "DOWN": 40,
            "LEFT": 37, "RIGHT": 39,
            "NUMPADPLUS": 107, "NUMPADMINUS": 109, "NUMPADMULTIPLY": 106,
            "NUMPADDIVIDE": 111, "NUMPADDECIMAL": 110,
            "SPACE": 32, "TAB": 9, "ENTER": 13, "ESCAPE": 27,
            "BACKSPACE": 8, "CAPSLOCK": 20,
        }
        for key, expected in vectors.items():
            with self.subTest(key=key):
                self.assertEqual(parse_keybinding(key), KeyBinding(expected, (), True))
        self.assertEqual(len(KEY_VKS), 91)

    def test_supported_prefix_subsequences(self):
        vectors = {
            "": (), "ALT-": (18,), "CTRL-": (17,), "SHIFT-": (16,),
            "ALT-CTRL-": (18, 17), "ALT-SHIFT-": (18, 16),
            "CTRL-SHIFT-": (17, 16), "ALT-CTRL-SHIFT-": (18, 17, 16),
        }
        for prefix, expected in vectors.items():
            with self.subTest(prefix=prefix):
                self.assertEqual(parse_keybinding(prefix + "F6"),
                                 KeyBinding(117, expected, True))

    def test_aliases_and_case(self):
        self.assertEqual(parse_keybinding(" alt-ctrl-shift-numpadadd \r\n"),
                         KeyBinding(107, (18, 17, 16), True))
        self.assertEqual(parse_keybinding("shift-numpadsubtract"),
                         KeyBinding(109, (16,), True))
        self.assertEqual(parse_keybinding("a"), KeyBinding(65, (), True))

    def test_reversed_or_repeated_modifiers_are_not_normalized(self):
        for original, remaining, modifiers in (
            ("CTRL-ALT-A", "ALT-A", (17,)),
            ("SHIFT-CTRL-A", "CTRL-A", (16,)),
            ("ALT-ALT-A", "ALT-A", (18,)),
            ("ALT-SHIFT-CTRL-A", "CTRL-A", (18, 16)),
            ("CTRL-CTRL-A", "CTRL-A", (17,)),
        ):
            with self.subTest(original=original):
                self.assertEqual(parse_keybinding(original), KeyBinding(
                    0, modifiers, False, f"未知主键名：{remaining}（原始 {original}）"))

    def test_no_internal_whitespace_trimming_or_implicit_shift(self):
        result = parse_keybinding(" ctrl- a ")
        self.assertEqual(result, KeyBinding(0, (17,), False,
                                           "未知主键名： A（原始  ctrl- a ）"))
        self.assertEqual(parse_keybinding(":"), KeyBinding(186, (), True))
        self.assertEqual(parse_keybinding("SHIFT-;"), KeyBinding(186, (16,), True))

    def test_empty_input_differs_from_empty_main_key(self):
        for value in ("", " \t\r\n", "\u3000\xa0\u2028"):
            self.assertEqual(parse_keybinding(value), KeyBinding(error="绑定键名为空"))
        self.assertEqual(parse_keybinding("ALT-"), KeyBinding(
            0, (18,), False, "未知主键名：（原始 ALT-）"))

    def test_qt_whitespace_boundary(self):
        self.assertTrue(parse_keybinding("\u3000A\xa0").valid)
        # Python str.strip() 会错误地接受 U+001C–001F，Qt isSpace 不属于此集合。
        for delimiter in ("\x1c", "\x1f", "\u200b", "\ufeff"):
            with self.subTest(delimiter=repr(delimiter)):
                self.assertFalse(parse_keybinding(delimiter + "A" + delimiter).valid)

    def test_unsupported_names_are_not_silently_added(self):
        for key in ("F0", "F13", "F24", "NUMPAD10", "NUMPADENTER", "NUMLOCK",
                    "ESC", "RETURN", "DEL", "INS", "PGUP", "PGDN", "CONTROL-A",
                    "CTRL+A", "ALT+A", "SHIFT+A", "NUMPAD_ADD", "KP_1", "VK_65",
                    "!", "+", "_", "?", "{", "}", "~", "\"", "BUTTON1", "鼠标1"):
            with self.subTest(key=key):
                self.assertFalse(parse_keybinding(key).valid)

    def test_extended_vk_set_is_precise(self):
        expected = {33, 34, 35, 36, 37, 38, 39, 40, 45, 46, 111}
        self.assertEqual({vk for vk in range(256) if is_extended_key(vk)}, expected)
        self.assertTrue(parse_keybinding("ALT-NUMPADDIVIDE").extended)
        self.assertFalse(parse_keybinding("ENTER").extended)
        self.assertFalse(parse_keybinding("NUMPAD0").extended)

    def test_non_string_boundary(self):
        for value in (None, 0, True, [], {}, b"F1"):
            with self.subTest(value=repr(value)):
                with self.assertRaises(TypeError):
                    parse_keybinding(value)

    @unittest.skipUnless(NATIVE_REPORT.is_file(), "未提供原版自测报告")
    def test_native_report_43_binding_differential(self):
        text = NATIVE_REPORT.read_text(encoding="utf-8")
        section = text.split("== 绑定键解析（共 43 个）==", 1)[1]
        section = section.split("== 阈值滑条", 1)[0]
        rows = re.findall(r"^(.+?)\s+-> vk=(\d+) mods=\[([^\]]*)\](.*)$",
                          section, flags=re.MULTILINE)
        self.assertEqual(len(rows), 43)
        for raw_key, raw_vk, raw_modifiers, status in rows:
            modifiers = tuple(int(x) for x in raw_modifiers.split(",") if x)
            with self.subTest(key=raw_key.strip()):
                self.assertFalse(status.strip(), "原版报告中的绑定不是成功结果")
                self.assertEqual(parse_keybinding(raw_key.strip()),
                                 KeyBinding(int(raw_vk), modifiers, True))

    def test_all_packaged_action_keys(self):
        paths = [ROOT / "assets" / name
                 for name in ("rules.json", "rules_readable.json")]
        for path in paths:
            self.assertTrue(path.is_file(), f"独立版缺少动作表：{path}")
        keys = []

        def collect(value):
            if isinstance(value, dict):
                if isinstance(value.get("key"), str) and value["key"]:
                    keys.append(value["key"])
                for child in value.values():
                    collect(child)
            elif isinstance(value, list):
                for child in value:
                    collect(child)

        collect(json.loads(paths[0].read_text(encoding="utf-8")))
        self.assertEqual(len(keys), 241)
        self.assertTrue(all(parse_keybinding(key).valid for key in keys))
        keys.clear()
        collect(json.loads(paths[1].read_text(encoding="utf-8")))
        self.assertEqual(len(keys), 562)
        # 原包 readable 表有 10 个解 JSON 后仍含四个反斜杠的绑定。
        # 原生解析器没有再次反转义，不能为通过语料检查而放宽主键规则。
        failures = [key for key in keys if not parse_keybinding(key).valid]
        self.assertCountEqual(failures, ["CTRL-" + "\\" * 4] * 8
                              + ["ALT-" + "\\" * 4] * 2)


if __name__ == "__main__":
    unittest.main()
