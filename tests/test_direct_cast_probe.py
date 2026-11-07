"""EnvCloakCast原文对照；只调用内存替身，不加载游戏或解锁器。"""
import unittest
from lupa.lua51 import LuaRuntime
from tests import test_original_direct_cast as original


class DirectCastProbeTests(unittest.TestCase):
    def hosts(self):
        ref=original.OriginalDirectCastTests();ref.setUp();a=ref.lua
        b=LuaRuntime(unpack_returned_tuples=True)
        b.execute('WowBuddyDev={DirectCast={}}')
        b.execute((original.ROOT/'addon/WowBuddyDev/DirectCastProbe.lua').read_text('utf8'))
        for lua in (a,b):
            lua.execute('''
                probeCalls={};apiMode='normal'
                function CastSpellByID(id,unit)
                    table.insert(probeCalls,{id=id,unit=unit})
                    if apiMode=='denied' then error('fixture denied',0) end
                    if apiMode=='false' then return false end
                    return 'fixture result'
                end
            ''')
        return a,b

    def compare(self,a,b,spell_id,unit=None):
        expected=a.globals().P07483180.DirectCast.EnvCloakCast(spell_id,unit)
        actual=b.globals().WowBuddyDev.DirectCast.EnvCloakCast(spell_id,unit)
        self.assertEqual(actual,expected)
        def calls(lua):return [(v.id,v.unit) for v in lua.globals().probeCalls.values()]
        self.assertEqual(calls(b),calls(a))
        return actual

    def test_default_target_unit_quoting_and_api_results(self):
        for mode in ('normal','false','denied'):
            for unit in (None,'player','focus','x"; error("injected") --','line\nnext'):
                with self.subTest(mode=mode,unit=unit):
                    a,b=self.hosts()
                    for lua in (a,b):lua.globals().apiMode=mode
                    outcome=self.compare(a,b,116,unit)
                    self.assertEqual(outcome,(None,'fixture denied') if mode=='denied' else (True,116))
                    self.assertEqual(len(b.globals().probeCalls),1)

    def test_compile_failure_reports_without_api_call(self):
        a,b=self.hosts()
        for lua in (a,b):lua.execute("loadstring=function() return nil,'fixture compile failure' end")
        self.assertEqual(self.compare(a,b,116),(None,'compile: fixture compile failure'))
        self.assertEqual(len(b.globals().probeCalls),0)

    def test_optional_environment_apis_absent_and_current_environment_used(self):
        for mode in ('no_getfenv','no_setfenv','explicit_environment'):
            with self.subTest(mode=mode):
                a,b=self.hosts()
                for lua in (a,b):
                    if mode=='no_getfenv':lua.execute('getfenv=nil')
                    elif mode=='no_setfenv':lua.execute('setfenv=nil')
                    else:lua.execute('''
                        local environment={CastSpellByID=CastSpellByID}
                        getfenv=function() return environment end
                    ''')
                self.assertEqual(self.compare(a,b,116,'player'),(True,116))

    def test_formatting_error_and_numeric_conversion_match_original(self):
        for spell_id in (116.9,'116',None,'invalid'):
            with self.subTest(spell_id=spell_id):
                a,b=self.hosts()
                if spell_id is None or spell_id=='invalid':
                    result=[]
                    for lua,namespace in ((a,'P07483180'),(b,'WowBuddyDev')):
                        ok,err=lua.eval('function(id) return pcall('+namespace+'.DirectCast.EnvCloakCast,id) end')(spell_id)
                        result.append(ok);self.assertIn('format',err)
                        self.assertEqual(len(lua.globals().probeCalls),0)
                    self.assertEqual(result,[False,False])
                else:self.compare(a,b,spell_id)


if __name__=='__main__':unittest.main()
