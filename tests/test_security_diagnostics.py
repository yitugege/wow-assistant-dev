"""隔离Lua执行：仅验证诊断记录，不模拟WoW安全执行环境。"""
from pathlib import Path
import unittest
import sys,tempfile,zipfile
from lupa.lua51 import LuaRuntime

class SecurityDiagnosticsTests(unittest.TestCase):
    def test_random_release_records_actual_addon_identity(self):
        root=Path(__file__).resolve().parents[1]
        sys.path.insert(0,str(root))
        from tools.build_addon import build
        with tempfile.TemporaryDirectory() as directory:
            package=Path(directory)/'addon.zip'
            manifest=build(root/'addon/WowBuddyDev',package,random_names=True)
            name=manifest['addon_directory']
            with zipfile.ZipFile(package) as archive:
                source=(root/'addon/WowBuddyDev/SecurityDiagnostics.lua').read_bytes()
                matches=[member for member in archive.namelist()
                         if member.endswith('.lua') and archive.read(member)==source]
                self.assertEqual(len(matches),1)
                toc=archive.read(name+'/'+name+'.toc').decode('utf8')
                self.assertIn(matches[0].split('/',1)[1],toc.splitlines())
                self.assertIn('WowBuddyDevDiagnostics',toc)
                lua=LuaRuntime(unpack_returned_tuples=True)
                lua.execute('''function CreateFrame() return {
                    RegisterEvent=function() end,SetScript=function(_,_,fn) callback=fn end} end
                    function print() end''')
                lua.execute(archive.read(matches[0]).decode('utf8'),name)
                callback=lua.globals().callback
                callback(None,'ADDON_ACTION_FORBIDDEN','WowBuddyDev','wrong identity')
                self.assertIsNone(lua.globals().WowBuddyDevDiagnostics)
                callback(None,'ADDON_ACTION_FORBIDDEN',name,'SetAttribute')
                record=lua.globals().WowBuddyDevDiagnostics[1]
                self.assertEqual(record.addon,name)
                self.assertEqual(record.operation,'SetAttribute')
                self.assertEqual(record.event,'ADDON_ACTION_FORBIDDEN')

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
