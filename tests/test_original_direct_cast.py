"""只执行原DirectCast的隔离诊断；游戏API为替身，不加载解锁器。"""
from pathlib import Path
import hashlib
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
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),
                         '361134bc9f2dd0b2c8cd8849b3741bd88d09c55ec371de9abc7b6f79502ebbed')
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

    def install_aura_host(self):
        self.lua.execute('''
        auraMode='absent';dead=false;casting=false;channel=false;cdStart=0;cdDuration=0
        P07483180._pixelStripV2BySpec={one={
          {kind='presence',unit='player',filter='HELPFUL',spellIDs={116,117},name='Frostbolt'}}}
        C_Spell={GetSpellName=function() return 'Frostbolt' end}
        C_UnitAuras={
          GetPlayerAuraBySpellID=function() if auraMode=='id' then return {} end end,
          GetAuraDataByIndex=function(unit,index,filter)
            if auraMode=='error' then error('unavailable') end
            if auraMode=='name' then return {name='Frostbolt'} end
            if auraMode=='full' then return {name='unrelated'} end
            return nil
          end}
        function UnitIsDeadOrGhost() return dead end
        function UnitCastingInfo() if casting then return 'cast' end end
        function UnitChannelInfo() if channel then return 'channel' end end
        function GetSpellCooldown() return cdStart,cdDuration end
        ''')

    def test_keeper_requires_confirmed_absence_and_deduplicates_ranks(self):
        for mode in ('id','name','error','full','absent'):
            with self.subTest(mode=mode):
                self.setUp();self.install_aura_host();g=self.lua.globals()
                g.auraMode=mode
                # 显式施法防重只拦“找到”，定时续挂还拦“不确定”。
                self.assertEqual(g.P07483180.DirectCast.GuardBlocked('Frostbolt'),
                                 mode in ('id','name'))
                g.tickers[1].fn()
                self.assertEqual(list(g.calls.values()),
                                 ['use:1:player'] if mode=='absent' else [])

    def test_keeper_state_gates_and_retry_boundary(self):
        for gate in ('dead','casting','channel','cooldown','off'):
            with self.subTest(gate=gate):
                self.setUp();self.install_aura_host();g=self.lua.globals()
                if gate=='cooldown':g.cdStart=9;g.cdDuration=2
                elif gate=='off':g.P07483180.DirectCast.enabled=False
                else:setattr(g,gate,True)
                g.tickers[1].fn();self.assertEqual(list(g.calls.values()),[])
        self.setUp();self.install_aura_host();g=self.lua.globals()
        g.tickers[1].fn();g.now=14.999;g.tickers[1].fn()
        self.assertEqual(list(g.calls.values()),['use:1:player'])
        g.now=15;g.tickers[1].fn()
        self.assertEqual(list(g.calls.values()),['use:1:player']*2)

    def test_keeper_empty_guard_snapshot_does_not_refresh_after_late_registration(self):
        g=self.lua.globals();g.tickers[1].fn()
        self.install_aura_host();g.tickers[1].fn()
        self.assertFalse(g.P07483180.DirectCast.GuardBlocked('Frostbolt'))
        self.assertEqual(list(g.calls.values()),[])

    def test_keeper_failed_both_apis_still_delays_retry(self):
        self.install_aura_host();g=self.lua.globals()
        self.lua.execute('''
        function UseAction() calls[#calls+1]='use-failed';error('denied') end
        function CastSpellByID() calls[#calls+1]='cast-failed';error('denied') end
        ''')
        g.tickers[1].fn();g.now=14.999;g.tickers[1].fn()
        self.assertEqual(list(g.calls.values()),['use-failed','cast-failed'])
        g.now=15;g.tickers[1].fn()
        self.assertEqual(list(g.calls.values()),['use-failed','cast-failed']*2)

    def test_movement_expiry_exact_boundary_and_state_gates(self):
        for elapsed,gate,expected in ((8,None,True),(8.001,None,False),
                                      (1,'dead',False),(1,'casting',False),
                                      (1,'channel',True),(1,'cooldown',False)):
            with self.subTest(elapsed=elapsed,gate=gate):
                self.setUp();self.install_aura_host();g=self.lua.globals();g.speed=1
                self.assertTrue(g.P07483180.DirectCast.MovementGate('spell_116'))
                g.speed=0;g.now=10+elapsed
                if gate=='cooldown':g.cdStart=10;g.cdDuration=5
                elif gate:setattr(g,gate,True)
                g.tickers[2].fn();g.tickers[2].fn()
                self.assertEqual(list(g.calls.values()),['use:1:target'] if expected else [])
                if gate=='casting':
                    g.casting=False;g.tickers[2].fn();g.tickers[2].fn()
                    self.assertEqual(list(g.calls.values()),['use:1:target'])

    def test_slot_index_and_manual_command_actual_contract(self):
        g=self.lua.globals()
        self.assertIsNone(g.P07483180.DirectCast.BindSlot)
        self.lua.execute('''
        function GetActionInfo(slot)
          if slot==1 or slot==144 then return 'spell',116 end
        end
        ''')
        self.assertEqual(g.P07483180.DirectCast.Cast('spell_116'),(True,'slot144'))
        self.lua.execute('function GetActionInfo() return nil end')
        # 非空索引不再刷新：移除动作条技能后仍使用旧槽。
        self.assertEqual(g.P07483180.DirectCast.Cast('spell_116'),(True,'slot144'))
        g.SlashCmdList.DCBIND('spell_116 999')
        self.assertEqual(g.P07483180.DirectCast.slots.spell_116,999)
        g.SlashCmdList.DCBIND('spell_116 0')
        self.assertEqual(g.P07483180.DirectCast.slots.spell_116,0)
        g.SlashCmdList.DCBIND('spell_116 -1')
        self.assertEqual(g.P07483180.DirectCast.slots.spell_116,0)

    def test_false_api_return_is_reported_as_success_without_fallback(self):
        self.lua.execute('''
        function UseAction(slot,unit)
          calls[#calls+1]='false-use:'..slot..':'..unit
          return false
        end
        ''')
        g=self.lua.globals()
        self.assertEqual(g.P07483180.DirectCast.Cast('spell_116'),(True,'slot1'))
        self.assertEqual(list(g.calls.values()),['false-use:1:target'])


if __name__=='__main__':unittest.main()
