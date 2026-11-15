"""Core.lua 拆分结构：标记、TOC 顺序与模块登记一致；状态只经状态表访问；拼回文本不含拆分新增行。"""
import re
import unittest

from addon_sources import ADDON, BODY, MARKER, rebuilt_core

ORDER = ['Modules.lua', 'CoreSettings.lua', 'CoreState.lua', 'CoreCooldownLedger.lua', 'CoreConsumables.lua',
         'CoreClassData.lua', 'Core.lua', 'CoreCastState.lua', 'CoreLocale.lua',
         'CoreButtons.lua', 'CoreEvents.lua', 'CoreControls.lua', 'CoreMovement.lua', 'CoreDiagnostics.lua']
# 原 Core.lua 文件级 local 状态，拆分后只经状态表 coreState 访问。
STATE = ['forceAvailableRules', 'consumableCooldownStart', 'consumableStateKnown', 'consumableByItemSpell',
         'pendingItemDataIDs', 'trinketCooldownStart', 'lastTrinketCooldownDuration', 'lastCastTimeBySpell',
         'cooldownEndBySpell', 'lastSucceededSpellID', 'lastSucceededCastGUID', 'lastSpellID', 'lastSucceededTime',
         'succeededGeneration', 'healingStoneBlockedInCombat', 'applyTalentCooldownGates']


def toc_files():
    return [line.strip() for line in (ADDON / 'WowBuddyDev.toc').read_text('utf-8-sig').splitlines()
            if line.strip() and not line.startswith('#')]


class CoreSplitTests(unittest.TestCase):
    def test_toc_loads_split_files_in_original_order(self):
        files = toc_files()
        self.assertEqual(files[0], 'Modules.lua')
        start = files.index('CoreSettings.lua')
        self.assertEqual(files[start:start + len(ORDER) - 1], ORDER[1:])

    def test_every_addon_file_takes_namespace_from_registry(self):
        tag = '-- @@注册表命名空间@@'
        for name in toc_files():
            if not name.endswith('.lua') or name.startswith('Libs/') or name == 'Modules.lua':
                continue
            with self.subTest(file=name):
                lines = (ADDON / name).read_text('utf-8-sig').split('\n')
                declarations = [line for line in lines if line.endswith(tag)]
                self.assertEqual(len(declarations), 1)
                self.assertIn('WowBuddyDev.Namespace("' + name[:-4] + '"', declarations[0])
                for line in lines:
                    # 只允许创建全局表的语句（_G.WowBuddyDev = ...）直接写 _G.WowBuddyDev。
                    if line.endswith(tag) or re.match(r'^\s*_G\.WowBuddyDev\s*=[^=]', line):
                        continue
                    self.assertIsNone(re.search(r'_G\.WowBuddyDev(?![A-Za-z0-9_])', line), line)

    def test_declared_module_uses_match_static_analysis(self):
        import sys
        sys.path.insert(0, str(ADDON.parents[1] / 'tools'))
        import addon_module_deps
        expected, actual = addon_module_deps.analyse(), addon_module_deps.declared()
        self.assertEqual(len(expected), len([f for f in toc_files() if f.endswith('.lua')
                                             and not f.startswith('Libs/') and f != 'Modules.lua']))
        for module, uses in expected.items():
            with self.subTest(module=module):
                self.assertEqual(actual[module], (module, uses))
        # 运行时边界检查使用的字段归属表须与同一份静态分析一致（tools/addon_module_deps.py --write 生成）。
        text, start, end = addon_module_deps.current_owners_block()
        self.assertEqual(text[start:end], addon_module_deps.owners_block())

    def test_every_marker_names_a_split_file(self):
        markers = [m.group(1) for line in (ADDON / 'Core.lua').read_text('utf-8').split('\n')
                   if (m := MARKER.match(line))]
        self.assertEqual(sorted(markers), sorted(set(ORDER) - {'Modules.lua', 'Core.lua'}))
        for name in markers:
            with self.subTest(file=name):
                lines = (ADDON / name).read_text('utf-8').rstrip('\n').split('\n')
                self.assertIn(BODY, lines)
                self.assertRegex(lines[-1], r'^WowBuddyDev\.RegisterModule\("' + re.escape(name[:-4]) + '"')

    def test_required_modules_load_earlier_and_no_global_side_channel(self):
        files = toc_files()
        for name in ORDER:
            with self.subTest(file=name):
                text = (ADDON / name).read_text('utf-8')
                self.assertNotIn('_coreShared', text)
                for required in re.findall(r'WowBuddyDev\.Require\("([A-Za-z]+)"\)', text):
                    self.assertTrue(files.index(required + '.lua') < files.index(name), (name, required))

    def test_core_state_is_only_reached_through_state_table(self):
        bare = re.compile(r'(?<![.:A-Za-z0-9_])(' + '|'.join(STATE) + r')(?![A-Za-z0-9_])')
        for name in ORDER[1:]:
            with self.subTest(file=name):
                for line in (ADDON / name).read_text('utf-8').split('\n'):
                    code = re.sub(r'"[^"]*"', '""', line.split('--', 1)[0])
                    self.assertIsNone(bare.search(code), line)
        state = (ADDON / 'CoreState.lua').read_text('utf-8')
        for field in STATE[:-1]:
            self.assertIn('coreState.' + field + ' = ', state)

    def test_rebuilt_core_has_no_split_artifacts(self):
        text = rebuilt_core()
        for token in ('RegisterModule(', '_coreShared', '@@拆分：', '@@原行：', '@@拆分新增@@', '@@状态表@@', 'coreState', BODY):
            self.assertNotIn(token, text)
        self.assertIn('local castGenerationCounter = 1', text)
        self.assertIn('function WowBuddyDev.InitDB()', text)


if __name__ == '__main__':
    unittest.main()
