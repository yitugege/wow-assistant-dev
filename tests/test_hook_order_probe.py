"""诊断工具记录器测试；两种宿主执行顺序均模拟，不作为游戏顺序证据。"""
import unittest
from tests import test_addon_full_load as full


class HookOrderProbeTests(unittest.TestCase):
    def fixture(self):
        lua,_=full.AddonFullLoadTests().load(full.SOURCE,'WowBuddyDev',
                    (full.ROOT/'tests/addon_login_host.lua').read_text('utf8'))
        lua.execute('''
            messages={};mutations=0;defaultFirst=true;runDefault=true
            function print(text) table.insert(messages,text) end
            local methods=getmetatable(UIParent).__index
            local originalAttribute=methods.SetAttribute
            function methods:SetAttribute(key,value)
                assert(not combat,'fixture combat mutation');mutations=mutations+1
                originalAttribute(self,key,value)
            end
            function methods:HookScript(event,fn)
                self.hooks=self.hooks or {};self.hooks[event]=self.hooks[event] or {}
                table.insert(self.hooks[event],fn)
            end
            function methods:Click(button,down)
                if self.scripts.PreClick then self.scripts.PreClick(self,button,down) end
                local function base()
                    if runDefault and self.scripts.OnClick then self.scripts.OnClick(self,button,down) end
                end
                local function hooks()
                    for _,fn in ipairs(self.hooks and self.hooks.OnClick or {}) do fn(self,button,down) end
                end
                if defaultFirst then base();hooks() else hooks();base() end
                if self.scripts.PostClick then self.scripts.PostClick(self,button,down) end
            end
            local originalCreate=CreateFrame
            function CreateFrame(kind,name,parent,template)
                local frame=originalCreate(kind,name,parent,template)
                if template=='SecureActionButtonTemplate' then
                    frame.scripts.OnClick=function(self,button)
                        assert(self.attributes.type=='click')
                        assert(self.attributes.clickbutton.name=='WowBuddyDevHookOrderMarker')
                        self.attributes.clickbutton:Click(button)
                    end
                end
                return frame
            end
            function ForbiddenProbeAction() error('probe must not act on game state') end
            CastSpellByID=ForbiddenProbeAction;UseAction=ForbiddenProbeAction
            SetOverrideBindingClick=ForbiddenProbeAction;RunMacroText=ForbiddenProbeAction
            TargetUnit=ForbiddenProbeAction;PickupSpell=ForbiddenProbeAction
        ''')
        return lua

    def test_opt_in_only_and_record_both_supplied_orders_without_inventing_default(self):
        for first in (True,False):
            with self.subTest(default_first=first):
                lua=self.fixture();g=lua.globals()
                self.assertIsNone(g.WowBuddyDevHookProbe)
                self.assertIsNone(g.WowBuddyDevHookOrderProbe)
                g.defaultFirst=first
                g.SlashCmdList.WBDHOOKPROBE('')
                self.assertEqual(g.mutations,2)
                g.WowBuddyDevHookOrderProbe.Click(g.WowBuddyDevHookOrderProbe,'LeftButton',True)
                phases=[e.phase for e in g.WowBuddyDevHookProbe.events.values()]
                self.assertEqual(phases,['pre','default-marker','hook','post'] if first
                                 else ['pre','hook','default-marker','post'])
                self.assertEqual(g.mutations,2)
                self.assertEqual(g.WowBuddyDevHookProbe.addon,'WowBuddyDev')

    def test_missing_default_and_combat_commands_do_not_modify_probe(self):
        lua=self.fixture();g=lua.globals();g.combat=True
        g.SlashCmdList.WBDHOOKPROBE('')
        self.assertIsNone(g.WowBuddyDevHookOrderProbe)
        g.combat=False;g.SlashCmdList.WBDHOOKPROBE('');g.runDefault=False
        g.WowBuddyDevHookOrderProbe.Click(g.WowBuddyDevHookOrderProbe,'LeftButton',True)
        g.SlashCmdList.WBDHOOKPROBE('report')
        self.assertIn('未观察到默认记录动作',list(g.messages.values())[-1])
        g.combat=True;g.SlashCmdList.WBDHOOKPROBE('hide')
        self.assertTrue(g.WowBuddyDevHookOrderProbe.shown)
        self.assertEqual(g.mutations,2)
        g.combat=False;g.SlashCmdList.WBDHOOKPROBE('hide')
        self.assertFalse(g.WowBuddyDevHookOrderProbe.shown)

    def test_bounded_records_and_reopen_reuses_button_without_duplicate_hooks(self):
        lua=self.fixture();g=lua.globals();g.SlashCmdList.WBDHOOKPROBE('')
        count=len(g.frames)
        for _ in range(20):g.WowBuddyDevHookOrderProbe.Click(g.WowBuddyDevHookOrderProbe,'LeftButton',True)
        self.assertEqual(len(g.WowBuddyDevHookProbe.events),60)
        self.assertEqual(g.WowBuddyDevHookProbe.events[1].sequence,6)
        g.SlashCmdList.WBDHOOKPROBE('')
        self.assertEqual(len(g.frames),count)
        self.assertEqual(len(g.WowBuddyDevHookProbe.events),0)
        self.assertEqual(len(g.WowBuddyDevHookOrderProbe.hooks.OnClick),1)


if __name__=='__main__':unittest.main()
