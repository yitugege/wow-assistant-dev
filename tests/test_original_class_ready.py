"""原addon.bin与独立插件的实际职业就绪函数差分；不执行游戏API。"""
import hashlib
import itertools
from pathlib import Path
import sys
import unittest
from lupa.lua51 import LuaRuntime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'desktop'))
from wowbuddy.packages import read_addon


class OriginalClassReadyTests(unittest.TestCase):
    def test_all_registered_action_readiness_matches_embedded_original(self):
        package = Path('D:/reverse-analysis/wow-assistant/unpacked/addon.bin')
        if not package.is_file():
            self.skipTest('需要原EXE内置addon.bin')
        payload = package.read_bytes()
        self.assertEqual(hashlib.sha256(payload).hexdigest(),
                         '361134bc9f2dd0b2c8cd8849b3741bd88d09c55ec371de9abc7b6f79502ebbed')
        original = {member.name: member.data.decode('utf-8-sig')
                    for member in read_addon(payload) if member.name.endswith('.lua')}
        def create(name, old):
            lua = LuaRuntime(unpack_returned_tuples=True)
            lua.execute((ROOT / 'tests/pixelbar_host.lua').read_text('utf8'))
            lua.execute('''P07483180=WowBuddyDev
            function WowBuddyDev.RegisterPixelStripV2() end
            WowBuddyDev.classes={};WowBuddyDev.forceAvailableState={}
            function WowBuddyDev.RegisterClass(id,data) registeredClass=data;WowBuddyDev.classes[id]=data end
            function IsSpellKnown(id) return fixtureKnown end
            function WowBuddyDev.GetForeverTalentState() return {packet=655360} end''')
            def source(path):
                return original[path] if old else (ROOT / 'addon/WowBuddyDev' / path).read_text('utf8')
            core = source('Core.lua')
            namespace = 'P07483180' if old else 'WowBuddyDev'
            start = core.index(namespace + '.COMMON_PIXEL_DATA = {')
            lua.execute(core[start:core.index('\n}', start)+2])
            for path in ('ForeverTalentData.lua', 'ForeverClassSupport.lua',
                         'classes/'+name+'/class_forever.lua'):
                lua.execute(source(path))
            lua.execute('''WowBuddyDev.classData=registeredClass
            WowBuddyDev.pixelData=registeredClass.pixelData
            WowBuddyDev.testSpells=registeredClass.testSpells
            WowBuddyDev.actionAvailSpellIDs=registeredClass.actionAvailSpellIDs''')
            lua.execute(source('PixelBar.lua'), namespace)
            lua.execute('''
            function WowBuddyDev.IsSpellUsable(id) return fixtureUsable end
            function WowBuddyDev.GetSpellCooldownRemaining(id) return fixtureCooldown end''')
            return lua
        count = 0
        for name in ('Mage','Druid','Hunter','Paladin','Priest','Rogue','Shaman','Warlock','Warrior'):
            old, new = create(name, True), create(name, False)
            original_ids = list(old.globals().registeredClass.actionAvailSpellIDs.values())
            self.assertEqual(original_ids, list(new.globals().registeredClass.actionAvailSpellIDs.values()))
            for known, usable, cooldown in itertools.product((False,True), (False,True), (None,-1,0,0.01,3)):
                for lua in (old,new):
                    g = lua.globals()
                    g.fixtureKnown, g.fixtureUsable, g.fixtureCooldown = known, usable, cooldown
                for spell in original_ids:
                    with self.subTest(class_name=name, spell=spell, known=known, usable=usable, cooldown=cooldown):
                        for function in ('IsSpellReadyRaw','IsSpellReady'):
                            self.assertEqual(old.globals().WowBuddyDev[function](spell),
                                             new.globals().WowBuddyDev[function](spell))
                        count += 1
            # 强制名单是Raw优先路径，但职业覆盖可在外层优先返回。
            for spell in original_ids:
                for lua in (old,new):
                    g = lua.globals()
                    g.fixtureKnown, g.fixtureUsable, g.fixtureCooldown = False, False, 3
                    g.WowBuddyDev.forceAvailableState = lua.table_from({spell: True})
                with self.subTest(class_name=name, forced=spell):
                    for function in ('IsSpellReadyRaw','IsSpellReady'):
                        self.assertEqual(old.globals().WowBuddyDev[function](spell),
                                         new.globals().WowBuddyDev[function](spell))
                    count += 1
        self.assertEqual(count, 3822)


if __name__ == '__main__':
    unittest.main()
