"""隔离Lua执行：仅验证诊断记录，不模拟WoW安全执行环境。"""
from pathlib import Path
import unittest
from lupa.lua51 import LuaRuntime

class SecurityDiagnosticsTests(unittest.TestCase):
    def test_only_own_events_are_recorded_and_history_is_bounded(self):
        lua=LuaRuntime(unpack_returned_tuples=True)
        lua.execute('''
        events={}; prints={}
        function CreateFrame()
          return {RegisterEvent=function(self,e) events[e]=true end,
                  SetScript=function(self,k,fn) callback=fn end}
        end
        function print(message) prints[#prints+1]=message end
        function time() return 123 end
        function InCombatLockdown() return true end
        function debugstack() return "fixture-stack" end
        ''')
        source=(Path(__file__).resolve().parents[1]/'addon/WowBuddyDev/SecurityDiagnostics.lua').read_text('utf8')
        lua.execute(source,'WowBuddyDev')
        lua.execute('callback(nil,"ADDON_ACTION_BLOCKED","AnotherAddon","UseAction")')
        self.assertIsNone(lua.globals().WowBuddyDevDiagnostics)
        lua.execute('for i=1,55 do callback(nil,"ADDON_ACTION_BLOCKED","WowBuddyDev","operation"..i) end')
        records=lua.globals().WowBuddyDevDiagnostics
        self.assertEqual(len(records),50)
        self.assertEqual(records[1]['operation'],'operation6')
        self.assertEqual(records[50]['operation'],'operation55')
        self.assertTrue(records[50]['inCombat'])
        self.assertEqual(records[50]['stack'],'fixture-stack')
        self.assertTrue(lua.globals().events['ADDON_ACTION_FORBIDDEN'])

if __name__=='__main__':unittest.main()
