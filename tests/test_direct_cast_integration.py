"""真实完整插件登录后的 Core 注册表与 DirectCast 接入回归。"""
import unittest
from tests import test_addon_full_load as full_load


class DirectCastIntegrationTests(unittest.TestCase):
    def test_real_compat_shim_accepts_names_and_reaches_action_slot(self):
        prelude=(full_load.ROOT/'tests/addon_login_host.lua').read_text('utf8')
        prelude+='''
            GetSpellInfo=nil;compatQueries={};directCalls={}
            C_Spell={GetSpellInfo=function(identifier)
                table.insert(compatQueries,identifier)
                if identifier==116 or identifier=='寒冰箭' then
                    return {name='寒冰箭',spellID=116,castTime=2000,iconID=1,minRange=0,maxRange=30}
                end
            end}
            function GetActionInfo(slot) if slot==7 then return 'spell',116 end end
            function UseAction(slot,unit) table.insert(directCalls,{slot=slot,unit=unit}) end
        '''
        lua,_=full_load.AddonFullLoadTests().load(full_load.SOURCE,'WowBuddyDev',prelude)
        g=lua.globals();g.EmitFixtureEvent('ADDON_LOADED','WowBuddyDev');g.EmitFixtureEvent('PLAYER_LOGIN')
        self.assertEqual(g.GetSpellInfo(116)[6],116)
        self.assertEqual(g.WowBuddyDev.DirectCast.Cast('class_numpad5'),(True,'slot7'))
        self.assertEqual(len(g.directCalls),1)
        self.assertEqual(g.directCalls[1].unit,'target')
        self.assertIn('寒冰箭',list(g.compatQueries.values()))
        self.assertIsNone(g.GetSpellInfo('unknown'))
        before=len(g.compatQueries)
        self.assertIsNone(g.GetSpellInfo(lua.table()))
        self.assertEqual(len(g.compatQueries),before)
        lua.execute("C_Spell.GetSpellInfo=function() error('fixture unavailable') end")
        self.assertIsNone(g.GetSpellInfo('寒冰箭'))

    def fixture(self, token='MAGE', class_id=8, spec=1482):
        lua=full_load.AddonFullLoadTests().login_fixture(token,class_id,spec)
        lua.execute('''
            directCalls={};spellQueries={}
            function GetSpellInfo(name)
                table.insert(spellQueries,name)
                return name,nil,nil,2000,nil,nil,116
            end
            function GetActionInfo(slot) if slot==7 then return 'spell',116 end end
            function UseAction(slot,unit) table.insert(directCalls,{slot=slot,unit=unit}) end
        ''')
        return lua

    def test_nine_class_bound_macro_accessor_matches_actual_buttons(self):
        for token,cid,spec,_ in full_load.AddonFullLoadTests.CLASS_CASES:
            with self.subTest(token=token):
                lua=self.fixture(token,cid,spec)
                a=lua.globals().WowBuddyDev
                self.assertIsNone(a.macroBindingRegistry)
                for key in a.GetClassMacroKeys().values():
                    action='class_'+key
                    text=a.GetSecureButton(action).attributes.macrotext
                    self.assertEqual(a.GetBoundMacro(action),text)
                    self.assertEqual(a.GetBoundMacro(action.lower()),text)
                self.assertIsNone(a.GetBoundMacro(None))
                self.assertIsNone(a.GetBoundMacro('unknown'))
                self.assertEqual(list(lua.globals().directCalls.values()),[])

    def test_class_action_and_lowercased_command_reach_action_api(self):
        lua=self.fixture();g=lua.globals();a=g.WowBuddyDev
        self.assertEqual(a.DirectCast.Cast('class_NUMPAD5'), (True,'slot7'))
        expected_name,expected_unit=a.DirectCast.ResolveMacro(a.GetBoundMacro('class_NUMPAD5'))
        self.assertEqual(g.spellQueries[1],expected_name)
        self.assertEqual(g.directCalls[1].unit,expected_unit)
        g.SlashCmdList.DIRECTCAST('test class_NUMPAD5')
        self.assertEqual(len(g.directCalls),2)
        self.assertEqual(g.directCalls[2].slot,7)
        self.assertEqual(g.directCalls[2].unit,expected_unit)

    def test_successfully_rebound_macro_is_used_and_failed_rebind_is_not_cached(self):
        lua=self.fixture();g=lua.globals();a=g.WowBuddyDev
        self.assertTrue(a.CreateSecureButton('class_NUMPAD5','NUMPAD5','/cast [@player] Changed'))
        self.assertEqual(a.GetBoundMacro('class_numpad5'),'/cast [@player] Changed')
        self.assertEqual(a.DirectCast.Cast('class_numpad5'),(True,'slot7'))
        self.assertEqual(g.directCalls[1].unit,'player')
        self.assertEqual(g.spellQueries[1],'Changed')
        lua.execute('''
            function SetOverrideBindingClick() return false end
            rebindOK=pcall(WowBuddyDev.CreateSecureButton,'class_NUMPAD5','NUMPAD5','/cast Rejected')
        ''')
        self.assertFalse(g.rebindOK)
        self.assertIsNone(a.GetBoundMacro('class_NUMPAD5'))
        self.assertEqual(a.DirectCast.Cast('class_NUMPAD5'),(None,'no-macro'))
        self.assertEqual(len(g.directCalls),1)

    def test_combat_deferred_rebind_keeps_current_registered_macro(self):
        lua=self.fixture();g=lua.globals();a=g.WowBuddyDev
        previous=a.GetBoundMacro('class_NUMPAD5')
        g.combat=True
        self.assertFalse(a.CreateSecureButton('class_NUMPAD5','NUMPAD5','/cast Deferred'))
        self.assertEqual(a.GetBoundMacro('class_NUMPAD5'),previous)


if __name__=='__main__': unittest.main()
