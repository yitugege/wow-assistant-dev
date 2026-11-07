"""与原包内闭包比较宏解析及光环判断；全部游戏 API 为离线替身。"""
from pathlib import Path
import unittest
from lupa.lua51 import LuaRuntime
from tests import test_original_direct_cast as original

ROOT = Path(__file__).resolve().parents[1]


class DirectCastGuardsTests(unittest.TestCase):
    def setUp(self):
        host = original.OriginalDirectCastTests()
        host.setUp()
        self.reference = host.lua
        host.install_aura_host()
        self.product = LuaRuntime(unpack_returned_tuples=True)
        self.product.execute('''
            WowBuddyDev={DirectCast={}};P07483180=WowBuddyDev
            function GetSpellInfo(name) return 'Frostbolt',nil,nil,2000,nil,nil,116 end
        ''')
        host.lua = self.product
        host.install_aura_host()
        self.product.execute((ROOT/'addon/WowBuddyDev/DirectCastGuards.lua').read_text('utf8'))
        self.reference.execute('''
            function FindOriginalUpvalue(fn,name,seen)
                seen=seen or {}; if seen[fn] then return nil end; seen[fn]=true
                for i=1,100 do
                    local key,value=debug.getupvalue(fn,i)
                    if not key then break end
                    if key==name then return value end
                end
                for i=1,100 do
                    local key,value=debug.getupvalue(fn,i)
                    if not key then break end
                    if type(value)=='function' then
                        local result=FindOriginalUpvalue(value,name,seen)
                        if result then return result end
                    end
                end
            end
        ''')

    def original_function(self, name, keeper=False):
        g = self.reference.globals()
        entry = g.tickers[1].fn if keeper else g.P07483180.DirectCast.Cast
        result = g.FindOriginalUpvalue(entry, name)
        self.assertIsNotNone(result, name)
        return result

    def test_macro_parser_matches_actual_original_closure(self):
        reference = self.original_function('resolveMacro')
        product = self.product.globals().WowBuddyDev.DirectCast.ResolveMacro
        macros = [None, 1, '', '/cast Frostbolt', '/cast [harm,nodead,nochanneling] Frostbolt',
                  '/cast [@player,nochanneling] Healing Wave', '/cast [noharm] Heal',
                  '/cast [@cursor] Blizzard', '/cast [@focus] Polymorph',
                  '/cast [harm] Frostbolt; Heal', '/cast [harm] Frostbolt; [noharm] Heal',
                  '/cast   寒冰箭  ', '/cast Frostbolt\n/startattack',
                  '/use [@player] 13', '/castsequence reset=target Frostbolt,Fireball',
                  '/CAST Frostbolt', '/cast [@mouseover,help] Healing Wave']
        for macro in macros:
            with self.subTest(macro=macro):
                self.assertEqual(product(macro), reference(macro))

    def test_aura_guard_and_keeper_unknown_semantics_match_original(self):
        for mode in ('id', 'name', 'error', 'full', 'absent'):
            for missing in ('none', 'id', 'scan', 'names', 'all'):
                with self.subTest(mode=mode, missing=missing):
                    self.setUp()
                    for lua in (self.reference, self.product):
                        lua.globals().auraMode = mode
                        if missing=='id': lua.execute('C_UnitAuras.GetPlayerAuraBySpellID=nil')
                        elif missing=='scan': lua.execute('C_UnitAuras.GetAuraDataByIndex=nil')
                        elif missing=='names': lua.execute('C_Spell=nil')
                        elif missing=='all': lua.execute('C_UnitAuras=nil')
                    a = self.reference.globals().P07483180.DirectCast
                    b = self.product.globals().WowBuddyDev.DirectCast
                    self.assertEqual(b.GuardBlocked('Frostbolt'), a.GuardBlocked('Frostbolt'))
                    keeper = self.original_function('KeeperAuraPresent', keeper=True)
                    self.assertEqual(b.KeeperAuraPresent(self.product.table_from([116,117])),
                                     keeper(self.reference.table_from([116,117])))

    def test_spell_name_cache_matches_original_including_failed_lookup_retry(self):
        reference = self.original_function('nameToID')
        product = self.product.globals().WowBuddyDev.DirectCast.SpellIDForName
        for lua in (self.reference, self.product):
            lua.execute('''
                lookupCount=0; lookupFails=true
                function GetSpellInfo(name)
                    lookupCount=lookupCount+1
                    if lookupFails then error('fixture unavailable') end
                    return name,nil,nil,2000,nil,nil,116
                end
            ''')
        for fails in (True, True, False, False):
            for lua in (self.reference, self.product): lua.globals().lookupFails=fails
            self.assertEqual(product('Frostbolt'), reference('Frostbolt'))
            self.assertEqual(self.product.globals().lookupCount, self.reference.globals().lookupCount)
        self.assertEqual(self.product.globals().lookupCount, 3)

    def test_empty_guard_snapshot_retains_original_late_registration_behavior(self):
        for lua in (self.reference, self.product):
            lua.execute('savedSlots=P07483180._pixelStripV2BySpec;P07483180._pixelStripV2BySpec=nil')
        a = self.reference.globals().P07483180.DirectCast
        b = self.product.globals().WowBuddyDev.DirectCast
        self.assertEqual(b.GuardBlocked('Frostbolt'), a.GuardBlocked('Frostbolt'))
        for lua in (self.reference, self.product):
            lua.execute("P07483180._pixelStripV2BySpec=savedSlots;auraMode='id'")
        self.assertFalse(a.GuardBlocked('Frostbolt'))
        self.assertEqual(b.GuardBlocked('Frostbolt'), a.GuardBlocked('Frostbolt'))


if __name__ == '__main__': unittest.main()
