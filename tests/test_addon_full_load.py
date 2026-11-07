"""执行源码/发布包 TOC 与指定登录事件；不模拟定时器或受保护执行。"""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import zipfile

from lupa.lua51 import LuaRuntime
from tools.build_addon import build

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'addon/WowBuddyDev'


class AddonFullLoadTests(unittest.TestCase):
    CLASS_CASES = (
        ('MAGE', 8, 1482, 21), ('DRUID', 11, 1484, 42),
        ('HUNTER', 3, 1485, 23), ('PALADIN', 2, 1486, 29),
        ('PRIEST', 5, 1487, 32), ('ROGUE', 4, 1488, 18),
        ('SHAMAN', 7, 1489, 28), ('WARLOCK', 9, 1490, 20),
        ('WARRIOR', 1, 1491, 28),
    )

    def load(self, directory, addon_name, prelude=None):
        lua = LuaRuntime(unpack_returned_tuples=True,
                         register_eval=False, register_builtins=False)
        for host in ('pixelbar_host.lua', 'addon_load_host.lua'):
            lua.execute((ROOT / 'tests' / host).read_text('utf8'))
        if prelude:
            lua.execute(prelude)
        shared = lua.table()
        loaded = []
        for line in (directory / f'{addon_name}.toc').read_text('utf-8-sig').splitlines():
            entry = line.strip()
            if not entry or entry.startswith('#'):
                continue
            self.assertEqual(Path(entry).suffix, '.lua')
            path = (directory / entry.replace('\\', '/')).resolve()
            self.assertTrue(path.is_relative_to(directory.resolve()))
            # 不捕获后继续：任意模块加载失败即使本测试失败。
            lua.execute(path.read_text('utf-8-sig'), addon_name, shared, name='@'+entry)
            loaded.append(entry)
        addon = lua.globals().WowBuddyDev
        self.assertEqual(set(addon.classes.keys()), set(range(1482, 1492)) - {1483})
        for name in ('mainFrame', 'configFrame', 'macroEditorFrame', 'DecisionBridge'):
            self.assertIsNotNone(addon[name], name)
        for name in ('GetAutoTargetPacket', 'GetRaidFocusPacket', 'RebuildPixelBars'):
            self.assertEqual(lua.eval('type')(addon[name]), 'function', name)
        self.assertIsNotNone(lua.globals().LibStub(addon_name+'-RangeCheck-3.0'))
        self.assertEqual(lua.globals().SLASH_DCBIND1, '/dcbind')
        lua.globals().SlashCmdList.DCBIND('spell_116 61')
        self.assertEqual(addon.DirectCast.slots.spell_116, 61)
        for name in ('ResolveMacro', 'SpellIDForName', 'GuardBlocked', 'KeeperAuraPresent',
                     'Cast', 'EnsureSlotForSpell', 'MovementGate', 'EnvCloakCast'):
            self.assertEqual(lua.eval('type')(addon.DirectCast[name]), 'function', name)
        self.assertEqual(addon.DirectCast.ResolveMacro('/cast [@player] Frostbolt'),
                         ('Frostbolt', 'player'))
        self.assertEqual(lua.globals().SLASH_DIRECTCAST1, '/dc')
        self.assertIsNone(lua.globals().WowBuddyDevDiagnostics)
        return lua, loaded

    def test_source_complete_toc_loads(self):
        self.load(SOURCE, 'WowBuddyDev')

    def login_fixture(self, token, class_id, spec, combat=False):
        prelude = (f"fixtureClass='{token}';fixtureClassID={class_id};fixtureSpecID={spec}\n"
                   + (ROOT/'tests/addon_login_host.lua').read_text('utf8'))
        lua, _ = self.load(SOURCE, 'WowBuddyDev', prelude)
        lua.globals().combat = combat
        lua.globals().EmitFixtureEvent('ADDON_LOADED', 'WowBuddyDev')
        lua.globals().EmitFixtureEvent('PLAYER_LOGIN')
        return lua

    def assert_login_bindings(self, lua, token, spec, used_count):
        addon = lua.globals().WowBuddyDev
        self.assertEqual(addon.DB.currentSpecID, spec)
        self.assertEqual(addon.DB.currentClass, token)
        self.assertTrue(addon.isClassActive)
        self.assertGreater(len(addon.pixelData), 0)
        self.assertEqual(addon.GetClassMacroInfo(), (token, 192, used_count))
        self.assertEqual(len(addon.errorLogs), 0)
        keys = list(addon.GetClassMacroKeys().values())
        self.assertEqual(len(keys), used_count)
        for key in keys:
            button = addon.GetSecureButton('class_'+key)
            self.assertIsNotNone(button, key)
            self.assertEqual(button.template, 'SecureActionButtonTemplate')
            self.assertEqual(button.attributes['type'], 'macro')
            expected = addon.LocalizeMacroBody(addon.GetClassDefaultMacro(key))
            self.assertEqual(button.attributes.macrotext, expected)
            self.assertEqual(button.bindings[key].button, button.name)
        auto = addon.GetSecureButton('auto_target')
        self.assertIsNotNone(auto)
        self.assertEqual(auto.attributes.macrotext,
                         '/targetenemy [combat,nochanneling,noexists][combat,nochanneling,dead]')
        auto_keys = list(auto.bindings.keys())
        self.assertEqual(len(auto_keys), 1)
        self.assertNotIn(auto_keys[0], keys)
        self.assertEqual(auto.bindings[auto_keys[0]].button, auto.name)
        # 登录分支已切换为正常事件分发，而非只执行到中途。
        login_receivers = [f for _, f in lua.globals().frames.items()
                           if f.events and f.events['PLAYER_LOGIN']]
        self.assertEqual(login_receivers, [])

    def test_nine_class_login_builds_macros_and_separate_auto_target_binding(self):
        for token, class_id, spec, used_count in self.CLASS_CASES:
            with self.subTest(token=token):
                lua = self.login_fixture(token, class_id, spec)
                self.assert_login_bindings(lua, token, spec, used_count)

    def test_combat_login_defers_binding_until_regen_enabled(self):
        lua = self.login_fixture('MAGE', 8, 1482, combat=True)
        addon = lua.globals().WowBuddyDev
        self.assertIsNone(addon.GetSecureButton('class_NUMPAD5'))
        self.assertIsNone(addon.GetSecureButton('auto_target'))
        self.assertFalse(any(list(f.bindings.keys()) for _, f in lua.globals().frames.items()
                             if f.bindings))
        lua.globals().combat = False
        lua.globals().EmitFixtureEvent('PLAYER_REGEN_ENABLED')
        self.assert_login_bindings(lua, 'MAGE', 1482, 21)

    def world_fixture(self, token, class_id, spec):
        prelude = f"fixtureClass='{token}';fixtureClassID={class_id};fixtureSpecID={spec}\n"
        prelude += '\n'.join((ROOT/'tests'/host).read_text('utf8')
                            for host in ('addon_login_host.lua', 'addon_world_host.lua'))
        lua, _ = self.load(SOURCE, 'WowBuddyDev', prelude)
        lua.globals().EmitFixtureEvent('ADDON_LOADED', 'WowBuddyDev')
        lua.globals().EmitFixtureEvent('PLAYER_LOGIN')
        return lua

    def test_nine_class_enter_world_and_delayed_initialization(self):
        for token, class_id, spec, used_count in self.CLASS_CASES:
            with self.subTest(token=token):
                lua = self.world_fixture(token, class_id, spec)
                g = lua.globals()
                g.EmitFixtureEvent('PLAYER_ENTERING_WORLD', True, False)
                self.assertEqual(g.AdvanceFixtureTime(15), 7)
                self.assertEqual(len(g.pendingAfter), 0)
                self.assert_login_bindings(lua, token, spec, used_count)
                report = g.WowBuddyDevDB.compatReport
                self.assertEqual(report.resolvedSpecID, spec)
                self.assertTrue(report.classDataMatched)
                self.assertEqual(report.registeredSpecCount, 9)
                self.assertEqual(g.fixtureCVars.useUiScale, '0')
                self.assertEqual(g.fixtureCVars.uiScale, '0.75')
                self.assertEqual(list(g.fixturePopups.keys()), [])
                containers = [f for _, f in g.frames.items() if f.kind == 'AuraContainer']
                self.assertTrue(containers)
                self.assertTrue(all(f.unit and f.auraUpdates > 0 for f in containers))

    def test_enter_world_scale_write_rejected_then_manual_recovery(self):
        lua = self.world_fixture('MAGE', 8, 1482)
        g = lua.globals()
        g.fixtureRejectScale = True
        g.EmitFixtureEvent('PLAYER_ENTERING_WORLD', True, False)
        g.AdvanceFixtureTime(15)
        self.assertEqual(g.fixtureCVars.useUiScale, '1')
        self.assertIsNotNone(g.fixturePopups.PERMES_UI_SCALE_WARNING)
        g.fixtureCVars.useUiScale = '0'
        g.EmitFixtureEvent('CVAR_UPDATE', 'useUiScale', '0')
        g.AdvanceFixtureTime(0)
        self.assertIsNone(g.fixturePopups.PERMES_UI_SCALE_WARNING)
        self.assert_login_bindings(lua, 'MAGE', 1482, 21)

    def test_randomized_package_loads_and_records_actual_addon_identity(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = build(SOURCE, root/'addon.zip', random_names=True)
            name = manifest['addon_directory']
            with zipfile.ZipFile(root/'addon.zip') as archive:
                archive.extractall(root/'unpacked')
            lua, loaded = self.load(root/'unpacked'/name, name,
                                    (ROOT/'tests/addon_login_host.lua').read_text('utf8'))
            lua.globals().EmitFixtureEvent('ADDON_LOADED', name)
            lua.globals().EmitFixtureEvent('PLAYER_LOGIN')
            self.assert_login_bindings(lua, 'MAGE', 1482, 21)
            self.assertTrue(all(Path(entry).name.startswith('f') for entry in loaded))
            lua.globals().actualAddonName = name
            lua.execute('''
                local count=0
                for _,frame in ipairs(frames) do
                    if frame.events and frame.events.ADDON_ACTION_BLOCKED then
                        count=count+1
                        frame.scripts.OnEvent(frame,'ADDON_ACTION_BLOCKED','unrelated','Other')
                        assert(WowBuddyDevDiagnostics == nil)
                        for i=1,51 do
                            frame.scripts.OnEvent(frame,'ADDON_ACTION_BLOCKED',actualAddonName,'Operation'..i)
                        end
                        frame.scripts.OnEvent(frame,'ADDON_ACTION_FORBIDDEN',actualAddonName,'Final')
                    end
                end
                assert(count==1)
                assert(#WowBuddyDevDiagnostics==50)
                assert(WowBuddyDevDiagnostics[1].operation=='Operation3')
                assert(WowBuddyDevDiagnostics[50].addon==actualAddonName)
                assert(WowBuddyDevDiagnostics[50].event=='ADDON_ACTION_FORBIDDEN')
                assert(WowBuddyDevDiagnostics[50].operation=='Final')
            ''')


if __name__ == '__main__':
    unittest.main()
