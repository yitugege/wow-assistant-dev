"""直接执行原hookButton闭包。默认处理先于挂钩为显式宿主假设，不代替游戏取证。"""
import unittest
from tests import test_original_direct_cast as original


class OriginalDirectCastHookTests(unittest.TestCase):
    def setUp(self):
        host=original.OriginalDirectCastTests();host.setUp();self.lua=host.lua
        self.lua.execute('''
            -- 绕过已单独证明的布尔返回值问题，只取原挂钩闭包，不修改其函数正文。
            for i=1,20 do
                local name,value=debug.getupvalue(P07483180.CreateSecureButton,i)
                if name=='hookButton' then originalHookButton=value end
            end
            assert(type(originalHookButton)=='function')
            trace={}; after={};combat=false;move=false;castOK=true;castReason='slot1'
            function C_Timer.After(delay,callback) table.insert(after,callback) end
            P07483180.DirectCast.MovementGate=function(key)
                table.insert(trace,'gate:'..key);return move
            end
            P07483180.DirectCast.Cast=function(key)
                table.insert(trace,'cast:'..key);return castOK,castReason
            end
            button={attributes={type='macro'},hooks={},hookCount=0}
            function button:HookScript(event,fn)
                assert(event=='OnClick');self.hookCount=self.hookCount+1
                table.insert(self.hooks,fn)
            end
            function button:SetAttribute(key,value)
                table.insert(trace,'attribute:'..key..':'..value)
                assert(not combat,'fixture combat attribute denied')
                self.attributes[key]=value
            end
            function button:GetAttribute(key) return self.attributes[key] end
            function InvokePostHookFixture(down)
                -- 这是待实机核对的排序假设，不实现WoW原生安全执行机制。
                table.insert(trace,'default:'..button.attributes.type)
                for _,fn in ipairs(button.hooks) do fn(button,'LeftButton',down) end
            end
            function DrainAfter()
                local pending=after;after={}
                for _,fn in ipairs(pending) do fn() end
            end
        ''')

    def test_hook_is_deduplicated_and_repeated_registration_keeps_first_action(self):
        g=self.lua.globals()
        g.originalHookButton(g.button,'spell_116')
        g.originalHookButton(g.button,'other')
        self.assertEqual(g.button.hookCount,1)
        g.InvokePostHookFixture(True)
        self.assertEqual(list(g.trace.values()),['default:macro','gate:spell_116',
                         'cast:spell_116','attribute:type:emptybutton'])
        g.DrainAfter();self.assertEqual(g.button.attributes.type,'macro')

    def test_movement_hook_cannot_retroactively_cancel_prior_default_in_posthook_model(self):
        g=self.lua.globals();g.move=True
        g.originalHookButton(g.button,'spell_116');g.InvokePostHookFixture(True)
        self.assertEqual(list(g.trace.values()),['default:macro','gate:spell_116','attribute:type:emptybutton'])
        # 恢复前的第二次默认处理看见emptybutton，说明修改影响后续事件。
        g.InvokePostHookFixture(False)
        self.assertEqual(g.trace[4],'default:emptybutton')
        g.DrainAfter();self.assertEqual(g.button.attributes.type,'macro')

    def test_combat_attribute_error_occurs_after_cast_attempt(self):
        g=self.lua.globals();g.combat=True
        g.originalHookButton(g.button,'spell_116')
        ok,err=self.lua.eval('function() return pcall(InvokePostHookFixture,true) end')()
        self.assertFalse(ok);self.assertIn('fixture combat attribute denied',err)
        self.assertEqual(list(g.trace.values()),['default:macro','gate:spell_116',
                         'cast:spell_116','attribute:type:emptybutton'])
        self.assertEqual(len(g.after),0)
        self.assertEqual(g.button.attributes.type,'macro')

    def test_off_up_and_cast_failure_leave_default_path(self):
        for scenario in ('off','up','failed'):
            with self.subTest(scenario=scenario):
                self.setUp();g=self.lua.globals()
                if scenario=='off':g.P07483180.DirectCast.enabled=False
                if scenario=='failed':g.castOK=None;g.castReason='no-slot'
                g.originalHookButton(g.button,'spell_116')
                g.InvokePostHookFixture(scenario!='up')
                expected=['default:macro']
                if scenario=='failed':expected+=['gate:spell_116','cast:spell_116']
                self.assertEqual(list(g.trace.values()),expected)
                self.assertEqual(len(g.after),0)


if __name__=='__main__':unittest.main()
