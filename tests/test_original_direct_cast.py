"""只执行原DirectCast的隔离诊断；游戏API为替身，不加载解锁器。"""
from pathlib import Path
import sys
import unittest
from lupa.lua51 import LuaRuntime, LuaError

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
from wowbuddy.packages import read_addon


class OriginalDirectCastTests(unittest.TestCase):
    def setUp(self):
        path=Path('D:/reverse-analysis/wow-assistant/unpacked/addon.bin')
        if not path.is_file():self.skipTest('需要原addon.bin')
        members={m.name:m.data for m in read_addon(path.read_bytes())}
        self.assertIn('DirectCast.lua',members)
        self.assertIn(b'DirectCast.lua',members['P07483180.toc'])
        self.lua=LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute('''
        calls={};tickers={};speed=0;now=10;placeFails=false;hasSlot=true
        SlashCmdList={};function print() end
        function wipe(t) for k in pairs(t) do t[k]=nil end end
        P07483180={classData={DEFAULT_MACROS={spell_116='/cast Frostbolt'}},
          CreateSecureButton=function() calls[#calls+1]='create';return true end}
        C_Timer={NewTicker=function(period,fn) tickers[#tickers+1]={period=period,fn=fn} end,
          After=function() error('unexpected After') end}
        function GetSpellInfo(name) return 'Frostbolt',nil,nil,2000,nil,nil,116 end
        function GetUnitSpeed() return speed end
        function GetTime() return now end
        function GetSpellCooldown() return 0,0 end
        function GetActionInfo(slot) if hasSlot and slot==1 then return 'spell',116 end end
        function UseAction(slot,unit) calls[#calls+1]='use:'..slot..':'..unit end
        function CastSpellByID(id,unit) calls[#calls+1]='cast:'..id..':'..unit end
        function PickupSpell(id) calls[#calls+1]='pickup:'..id end
        function PlaceAction(slot) calls[#calls+1]='place:'..slot;if placeFails then error('denied') end end
        ''')
        self.lua.execute(members['DirectCast.lua'].decode('utf-8-sig'))

    def test_load_registers_two_timers_and_commands_without_casting(self):
        g=self.lua.globals()
        self.assertTrue(g.P07483180.DirectCast.enabled)
        self.assertEqual([x.period for x in g.tickers.values()],[1,0.1])
        self.assertIsNotNone(g.SlashCmdList.DIRECTCAST)
        self.assertIsNotNone(g.SlashCmdList.DCBIND)
        self.assertEqual(list(g.calls.values()),[])

    def test_true_return_from_core_breaks_button_hook_after_creation(self):
        g=self.lua.globals()
        with self.assertRaisesRegex(LuaError,'boolean'):
            g.P07483180.CreateSecureButton('spell_116','F1','/cast Frostbolt')
        self.assertEqual(list(g.calls.values()),['create'])

    def test_off_does_not_cancel_preexisting_movement_intent(self):
        g=self.lua.globals();g.speed=1
        self.assertTrue(g.P07483180.DirectCast.MovementGate('spell_116'))
        g.SlashCmdList.DIRECTCAST('off')
        self.assertFalse(g.P07483180.DirectCast.enabled)
        g.speed=0
        g.tickers[2].fn();self.assertEqual(list(g.calls.values()),[])
        g.tickers[2].fn()
        self.assertEqual(list(g.calls.values()),['use:1:target'])

    def test_failed_place_is_still_cached_as_successful_slot(self):
        g=self.lua.globals();g.hasSlot=False;g.placeFails=True
        self.assertEqual(g.P07483180.DirectCast.EnsureSlotForSpell(116),1)
        self.assertEqual(list(g.calls.values()),['pickup:116','place:1'])
        self.assertEqual(g.P07483180.DirectCast.EnsureSlotForSpell(116),1)
        self.assertEqual(list(g.calls.values()),['pickup:116','place:1'])

    def test_manual_cast_remains_callable_when_off(self):
        g=self.lua.globals();g.SlashCmdList.DIRECTCAST('off')
        self.assertEqual(g.P07483180.DirectCast.Cast('spell_116'),(True,'slot1'))
        self.assertEqual(list(g.calls.values()),['use:1:target'])


if __name__=='__main__':unittest.main()
