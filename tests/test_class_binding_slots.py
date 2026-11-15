"""职业宏槽位：Bindings.lua 的 CLASS_MACRO_SLOTS 为 192 个不重复键；各职业文件只为有宏的键调用 BindKey，
且这些键都在槽位表中、按槽位顺序出现（与原插件职业文件的声明顺序一致）。只做静态解析，不执行 Lua。"""
from pathlib import Path
import re
import unittest

ADDON = Path(__file__).resolve().parents[1] / 'addon/WowBuddyDev'
CALL = re.compile(r'^\s*WowBuddyDev\.BindKey\("((?:[^"\\]|\\.)+)", "(.*)"\)\s*$', re.M)


def slots():
    text = (ADDON / 'Bindings.lua').read_text('utf-8-sig')
    body = text[text.index('local CLASS_MACRO_SLOTS = {'):]
    body = body[:body.index('\n}')]
    return re.findall(r'"((?:[^"\\]|\\.)+)"', body)


class ClassBindingSlotTests(unittest.TestCase):
    def test_slot_table_has_192_unique_keys(self):
        keys = slots()
        self.assertEqual(len(keys), 192)
        self.assertEqual(len(set(keys)), 192)

    def test_class_files_bind_only_non_empty_keys_in_slot_order(self):
        index = {key: number for number, key in enumerate(slots())}
        files = sorted((ADDON / 'classes').glob('*/*-Bindings.lua'))
        self.assertEqual(len(files), 9)
        for path in files:
            with self.subTest(file=path.name):
                calls = CALL.findall(path.read_text('utf-8-sig'))
                self.assertTrue(calls)
                self.assertTrue(all(body for _, body in calls), '空槽位不再逐个声明')
                positions = [index[key] for key, _ in calls]
                self.assertEqual(positions, sorted(set(positions)))


if __name__ == '__main__':
    unittest.main()
