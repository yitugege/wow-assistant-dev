from pathlib import Path
import unittest
from lupa.lua51 import LuaRuntime

ADDON=Path(__file__).resolve().parents[1]/'addon/WowBuddyDev'


class NamespaceTests(unittest.TestCase):
    def test_all_lua_files_compile(self):
        lua=LuaRuntime(unpack_returned_tuples=True)
        compile_lua=lua.eval('function(source,name) local fn,err=loadstring(source,name); return fn~=nil,err end')
        for path in ADDON.rglob('*.lua'):
            ok,error=compile_lua(path.read_text('utf-8-sig'),'@'+path.relative_to(ADDON).as_posix())
            self.assertTrue(ok,error)

    def test_runtime_references_do_not_use_legacy_namespace(self):
        for path in ADDON.rglob('*.lua'):
            for number,line in enumerate(path.read_text('utf-8-sig').splitlines(),1):
                if line.lstrip().startswith('--'): continue
                for token in ('P07483180','SemrepDB','MKL_BTN_'):
                    self.assertNotIn(token,line,f'{path.name}:{number}')
        toc=(ADDON/'WowBuddyDev.toc').read_text('utf8')
        self.assertIn('## SavedVariables: WowBuddyDevDB, WowBuddyDevDiagnostics',toc)

    def test_secure_button_uses_own_name_and_defers_combat_mutation(self):
        source=(ADDON/'Core.lua').read_text('utf8')
        start=source.index('function WowBuddyDev.CreateSecureButton(')
        end=source.index('\nend\n',start)+5
        lua=LuaRuntime(unpack_returned_tuples=True)
        lua.execute('''
        WowBuddyDev={}; P07483180={marker="old"}; SemrepDB={marker="old"}
        secureButtons={}; macroBindingRegistry={}; macroBindingErrors={}; overrideOwnerFrame={}
        combat=false; created=0; attributes=0; boundName=nil; UIParent={}
        function InCombatLockdown() return combat end
        function normalizeBindingKey(key) return key end
        function ClearOverrideBindings(button) end
        function SetOverrideBindingClick(owner,priority,key,name,mouse) boundName=name; return true end
        function reportMacroBindingError() error("unexpected binding failure") end
        function CreateFrame(kind,name,parent,template)
          created=created+1
          return {SetSize=function() end,SetPoint=function() end,RegisterForClicks=function() end,
                  Show=function() end,SetAttribute=function() attributes=attributes+1 end}
        end
        ''')
        lua.execute(source[start:end])
        self.assertTrue(lua.eval('WowBuddyDev.CreateSecureButton("spell_116","NUMPAD5","/cast 寒冰箭")'))
        self.assertEqual(lua.globals().boundName,'WBD_BTN_spell_116')
        self.assertEqual(lua.globals().P07483180['marker'],'old')
        count=lua.globals().attributes
        lua.execute('combat=true')
        self.assertFalse(lua.eval('WowBuddyDev.CreateSecureButton("spell_116","NUMPAD6","/cast 寒冰箭")'))
        self.assertEqual(lua.globals().attributes,count)
        self.assertEqual(lua.globals().created,1)
        self.assertTrue(lua.globals().overrideOwnerFrame['pendingMacroBindings'])


if __name__=='__main__':unittest.main()
