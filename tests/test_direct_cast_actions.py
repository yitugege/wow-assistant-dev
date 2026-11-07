"""完整原模块与独立施法核心的离线调用轨迹对照；不发送真实游戏输入。"""
from pathlib import Path
import itertools
import unittest
from lupa.lua51 import LuaRuntime
from tests import test_original_direct_cast as original

ROOT=Path(__file__).resolve().parents[1]
HOST='''
calls={}; slotsMode='existing'; pickupMode='ok'; placeMode='ok'; useMode='ok'; castMode='ok'
nameKnown=true; messages={}; SlashCmdList=SlashCmdList or {}
function print(message) table.insert(messages,message) end
function wipe(t) for k in pairs(t) do t[k]=nil end end
function GetSpellInfo(name)
  return 'Frostbolt',nil,nil,2000,nil,nil,nameKnown and 116 or nil
end
function GetActionInfo(slot)
  if slotsMode=='existing' and slot==1 then return 'spell',116 end
  if slotsMode=='full' then return 'macro',17 end
end
function PickupSpell(id)
  table.insert(calls,'pickup:'..id)
  if pickupMode=='error' then error('fixture denied') end
  if pickupMode=='false' then return false end
end
function PlaceAction(slot)
  table.insert(calls,'place:'..slot)
  if placeMode=='error' then error('fixture denied') end
  if placeMode=='false' then return false end
end
function UseAction(slot,unit)
  table.insert(calls,'use:'..slot..':'..unit)
  if useMode=='error' then error('fixture denied') end
  if useMode=='false' then return false end
end
function CastSpellByID(id,unit)
  table.insert(calls,'cast:'..id..':'..unit)
  if castMode=='error' then error('fixture denied') end
  if castMode=='false' then return false end
end
'''


class DirectCastActionsTests(unittest.TestCase):
    def hosts(self, **settings):
        ref=original.OriginalDirectCastTests();ref.setUp()
        a=ref.lua
        b=LuaRuntime(unpack_returned_tuples=True)
        b.execute("WowBuddyDev={classData={DEFAULT_MACROS={spell_116='/cast Frostbolt'}}}")
        for lua in (a,b):
            lua.execute(HOST)
            for key,value in settings.items(): lua.globals()[key]=value
        for name in ('DirectCastSlots.lua','DirectCastGuards.lua','DirectCastActions.lua'):
            b.execute((ROOT/'addon/WowBuddyDev'/name).read_text('utf8'))
        return a,b

    def assert_cast_trace(self,a,b,action='spell_116',unit=None):
        expected=a.globals().P07483180.DirectCast.Cast(action,unit)
        actual=b.globals().WowBuddyDev.DirectCast.Cast(action,unit)
        self.assertEqual(actual,expected)
        self.assertEqual(list(b.globals().calls.values()),list(a.globals().calls.values()))
        self.assertIsNone(b.globals().WowBuddyDev.DirectCast.activeCall)
        return actual

    def test_slot_priority_and_api_error_matrix(self):
        for slots,use,cast,manual in itertools.product(
                ('existing','empty','full'),('ok','error','false'),('ok','error','false'),(False,True)):
            with self.subTest(slots=slots,use=use,cast=cast,manual=manual):
                a,b=self.hosts(slotsMode=slots,useMode=use,castMode=cast)
                if manual:
                    a.globals().SlashCmdList.DCBIND('spell_116 61')
                    b.globals().SlashCmdList.DCBIND('spell_116 61')
                self.assert_cast_trace(a,b,unit='player')
                self.assert_cast_trace(a,b)  # 同一缓存下再次尝试。

    def test_placement_failures_preserve_original_cache_semantics(self):
        for pickup,place in itertools.product(('ok','error','false'),repeat=2):
            with self.subTest(pickup=pickup,place=place):
                a,b=self.hosts(slotsMode='empty',pickupMode=pickup,placeMode=place)
                for _ in range(2):
                    self.assertEqual(b.globals().WowBuddyDev.DirectCast.EnsureSlotForSpell(116),
                                     a.globals().P07483180.DirectCast.EnsureSlotForSpell(116))
                    self.assertEqual(list(b.globals().calls.values()),list(a.globals().calls.values()))

    def test_missing_macro_spell_name_and_registry_fallback(self):
        a,b=self.hosts()
        self.assert_cast_trace(a,b,'missing')
        for lua,namespace in ((a,'P07483180'),(b,'WowBuddyDev')):
            lua.execute(namespace+".classData.DEFAULT_MACROS.spell_116='not a macro'")
        self.assert_cast_trace(a,b)
        for lua,namespace in ((a,'P07483180'),(b,'WowBuddyDev')):
            lua.execute(namespace+".classData=nil;"+namespace+".macroBindingRegistry={spell_116={macroText='/cast Frostbolt'}}")
            lua.globals().nameKnown=False
            lua.globals().SlashCmdList.DCBIND('spell_116 61')
        self.assert_cast_trace(a,b)

    def test_explicit_test_command_still_runs_when_off_as_in_original(self):
        a,b=self.hosts()
        for lua in (a,b):
            lua.globals().SlashCmdList.DIRECTCAST('off')
            lua.execute('messages={}')
            lua.globals().SlashCmdList.DIRECTCAST('test spell_116')
        self.assertFalse(b.globals().WowBuddyDev.DirectCast.enabled)
        self.assertEqual(list(b.globals().calls.values()),list(a.globals().calls.values()))
        self.assertEqual(list(b.globals().messages.values()),list(a.globals().messages.values()))

    def test_present_self_buff_blocks_all_action_apis(self):
        a,b=self.hosts()
        self.assertEqual(list(b.globals().calls.values()), [])
        for lua,namespace in ((a,'P07483180'),(b,'WowBuddyDev')):
            lua.execute(namespace+'''._pixelStripV2BySpec={one={
                {kind='presence',unit='player',filter='HELPFUL',spellIDs={116},name='Frostbolt'}}}
                C_UnitAuras={GetPlayerAuraBySpellID=function() return {} end}
            ''')
        self.assertEqual(self.assert_cast_trace(a,b), (None,'blocked-aura-present'))
        self.assertEqual(list(b.globals().calls.values()), [])

    def test_forbidden_event_without_lua_error_does_not_prove_cast(self):
        # 客户端事件与Lua异常是两条通道；替身只验证处理语义，不模拟安全权限。
        for return_false in (False, True):
            with self.subTest(return_false=return_false):
                a,b=self.hosts(slotsMode='full')
                for lua,identity in ((a,'P07483180'),(b,'WowBuddyDev')):
                    lua.execute('''
                        function CreateFrame() return {
                          RegisterEvent=function() end,
                          SetScript=function(_,_,fn) securityCallback=fn end} end
                    ''')
                    lua.execute((ROOT/'addon/WowBuddyDev/SecurityDiagnostics.lua').read_text('utf8'),identity)
                    lua.globals().testAddonIdentity=identity
                    lua.globals().returnFalse=return_false
                    lua.execute('''
                        appliedCasts=0
                        function CastSpellByID(id,unit)
                          table.insert(calls,'cast:'..id..':'..unit)
                          securityCallback(nil,'ADDON_ACTION_FORBIDDEN',testAddonIdentity,'UNKNOWN()')
                          if returnFalse then return false end
                        end
                    ''')
                self.assertEqual(self.assert_cast_trace(a,b),(True,116))
                for lua in (a,b):
                    self.assertEqual(lua.globals().appliedCasts,0)
                    record=lua.globals().WowBuddyDevDiagnostics[1]
                    self.assertEqual(record.event,'ADDON_ACTION_FORBIDDEN')
                    self.assertEqual(record.operation,'UNKNOWN()')
                    self.assertEqual(list(lua.globals().calls.values()),['cast:116:target'])
                self.assertIsNone(a.globals().WowBuddyDevDiagnostics[1].directCastContext)
                self.assertEqual(b.globals().WowBuddyDevDiagnostics[1].directCastContext,'CastSpellByID')
                self.assertIsNone(b.globals().WowBuddyDev.DirectCast.activeCall)


if __name__=='__main__': unittest.main()
