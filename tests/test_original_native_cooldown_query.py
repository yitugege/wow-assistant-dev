"""原包/独立版原生冷却适配器对照，覆盖现代和旧版接口选择。"""
import hashlib
from pathlib import Path
import sys
import unittest
from lupa.lua51 import LuaRuntime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'desktop'))
from wowbuddy.packages import read_addon


class NativeCooldownQueryParityTests(unittest.TestCase):
    def test_modern_legacy_values_and_error_propagation(self):
        path = Path('D:/reverse-analysis/wow-assistant/unpacked/addon.bin')
        if not path.exists():
            self.skipTest('需要原addon.bin')
        data = path.read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(),
                         '361134bc9f2dd0b2c8cd8849b3741bd88d09c55ec371de9abc7b6f79502ebbed')
        sources = [next(m.data.decode('utf-8-sig') for m in read_addon(data) if m.name == 'Core.lua'),
                   (ROOT / 'addon/WowBuddyDev/Core.lua').read_text('utf8')]
        cases = [
            ('return {startTime=90,duration=20,isEnabled=true}', 10),
            ("return {startTime='90.25',duration='20',isEnabled=true}", 10.25),
            ('return {startTime=90,duration=20,isEnabled=false}', 0),
            ('return {startTime=90,duration=20,isEnabled=0}', 10),
            ('return {startTime=90,duration=20}', 10),
            ('return {startTime=90,duration=-1,isEnabled=true}', 0),
            ('return {startTime=90,duration=10,isEnabled=true}', 0),
            ('return {startTime=90,duration=9,isEnabled=true}', 0),
            ("return {startTime='bad',duration=110,isEnabled=true}", 10),
            ('return {duration=110}', 10),
            ('return {startTime=90}', 0),
            ('return {}', 0),
            ('return nil', 0),
            ('return false,20,true', 0),
            ('return 90,20,true', 10),
            ('return 90,20,false', 0),
            ('return 90,20,nil', 0),
            ('return 90,20,0', 10),
            ("return '90.125','20',1", 10.125),
            ('return 0,110,true', 10),
            ('return 90,nil,true', 0),
            ("error('fixture unavailable')", None),
        ]
        for modern in (False, True):
            runtimes = []
            for index, source in enumerate(sources):
                namespace = 'P07483180' if index == 0 else 'WowBuddyDev'
                lua = LuaRuntime(unpack_returned_tuples=True)
                lua.execute('''WowBuddyDev={cooldowns={},persistentCooldowns={}}
                  P07483180=WowBuddyDev;calls=0
                  function GetTime() return 100 end
                  function dispatch(id) assert(id==777);calls=calls+1;return answer() end
                  GetSpellCooldown=dispatch
                ''')
                if modern:
                    lua.execute("C_Spell={GetSpellCooldown=dispatch};GetSpellCooldown=function() error('wrong API') end")
                begin = source.index('function '+namespace+'.SafeNumber(value)')
                adapter = source[begin:source.index('local libSharedMedia', begin)]
                begin = source.index('function '+namespace+'.GetSpellCooldownRemaining(spellID)')
                query = source[begin:source.index(namespace+'.lastCastTime = lastCastTimeBySpell', begin)]
                lua.execute(adapter + query + '''
                  function checked(id)
                    local ok,result=pcall(WowBuddyDev.GetSpellCooldownRemaining,id)
                    if ok then return true,result end
                    return false
                  end
                ''')
                runtimes.append(lua)
            for body, expected in cases:
                with self.subTest(modern=modern, body=body):
                    actual = []
                    for lua in runtimes:
                        lua.execute('function answer() '+body+' end')
                        actual.append(lua.globals().checked(777))
                    self.assertEqual(actual[0], actual[1])
                    self.assertEqual(actual[0], False if expected is None else (True, expected))
            for lua in runtimes:
                before = lua.globals().calls
                self.assertEqual(lua.globals().checked(None), (True, 0))
                self.assertEqual(lua.globals().calls, before)


if __name__ == '__main__':
    unittest.main()
