"""实际Core.lua安全按钮生命周期，游戏API替身在战斗中拒绝修改。"""
from pathlib import Path
import json,unittest
from lupa.lua51 import LuaRuntime
SOURCE=Path(__file__).resolve().parents[1]/'addon/WowBuddyDev/Core.lua'


class BindingLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.lua=LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute('''
        combat=false; writes=0; rejected=nil; queue={}; bound={}; frames={}; errors={}
        UIParent={}
        function InCombatLockdown() return combat end
        function wipe(t) for k in pairs(t) do t[k]=nil end end
        function migrateChijiMacro() end
        function changed()
          local owner=frames.WowBuddyDevOverrideOwner
          if owner and owner.scripts.OnEvent then owner.scripts.OnEvent(owner,'UPDATE_BINDINGS') end
        end
        function mutation() assert(not combat,'战斗中修改安全按钮');writes=writes+1 end
        function CreateFrame(kind,name,parent,template)
          mutation()
          local f={attributes={},scripts={},events={},name=name}
          function f:SetAttribute(key,value) mutation();self.attributes[key]=value end
          function f:GetAttribute(key) return self.attributes[key] end
          function f:SetScript(key,value) self.scripts[key]=value end
          function f:RegisterEvent(name) self.events[name]=true end
          function f:RegisterUnitEvent(name) self.events[name]=true end
          function f:SetSize() end
          function f:SetPoint() end
          function f:RegisterForClicks() end
          function f:Show() end
          if name then frames[name]=f;_G[name]=f end
          return f
        end
        function ClearOverrideBindings(owner)
          mutation()
          for key,entry in pairs(bound) do if entry.owner==owner then bound[key]=nil end end
          changed()
        end
        function SetOverrideBindingClick(owner,priority,key,name,button)
          mutation()
          if key==rejected then return false end
          bound[key]={owner=owner,action='CLICK '..name..':'..button}
          changed();return true
        end
        function GetBindingAction(key) return bound[key] and bound[key].action or '' end
        C_Timer={After=function(delay,fn) queue[#queue+1]={delay=delay,fn=fn} end}
        function flush()
          local pending=queue;queue={}
          for _,item in ipairs(pending) do item.fn() end
        end
        function event(name)
          local f=frames.WowBuddyDevOverrideOwner;f.scripts.OnEvent(f,name)
        end
        WowBuddyDev={ACTION_TO_KEY={first='F1'},
          GetDefaultMacro=function(action) return '/cast '..action end,
          GetUserMacro=function() return false end,
          AddErrorLog=function(category,message) errors[#errors+1]=message end}
        ''')
        source=SOURCE.read_text('utf8')
        start=source.index('local secureButtons = {}')
        end=source.index('SLASH_PMBIND1 =',start)
        self.lua.execute(source[start:end])

    def test_spec_switch_removes_old_keys_and_deactivates_old_button(self):
        g=self.lua.globals();g.WowBuddyDev.RefreshMacroBindings()
        self.assertEqual(g.bound.F1.action,'CLICK WBD_BTN_first:LeftButton')
        self.lua.execute("WowBuddyDev.ACTION_TO_KEY={second='F2'};WowBuddyDev.RefreshMacroBindings()")
        self.assertIsNone(g.bound.F1)
        self.assertIsNone(g.frames.WBD_BTN_first.attributes.type)
        self.assertIsNone(g.frames.WBD_BTN_first.attributes.macrotext)
        self.assertEqual(g.bound.F2.action,'CLICK WBD_BTN_second:LeftButton')
        ok,passed,total,failures=g.WowBuddyDev.CheckMacroBindings()
        self.assertTrue(ok);self.assertEqual((passed,total),(1,1))

    def test_combat_defers_rebuild_until_regen_and_keeps_old_keys_until_then(self):
        g=self.lua.globals();g.WowBuddyDev.RefreshMacroBindings();before=g.writes
        self.lua.execute("combat=true;WowBuddyDev.ACTION_TO_KEY={second='F2'};WowBuddyDev.RefreshMacroBindings()")
        self.assertEqual(g.writes,before);self.assertIsNotNone(g.bound.F1);self.assertIsNone(g.bound.F2)
        ok,_,_,failures=g.WowBuddyDev.CheckMacroBindings()
        self.assertFalse(ok);self.assertIn('pending combat end',list(failures.values()))
        self.lua.execute("combat=false;event('PLAYER_REGEN_ENABLED')")
        self.assertIsNone(g.bound.F1);self.assertIsNotNone(g.bound.F2)
        self.assertTrue(g.WowBuddyDev.CheckMacroBindings()[0])

    def test_update_events_coalesce_and_rebuild_does_not_schedule_itself(self):
        g=self.lua.globals()
        self.lua.execute("event('UPDATE_BINDINGS');event('UPDATE_BINDINGS')")
        self.assertEqual(len(g.queue),1)
        g.flush()
        self.assertEqual(len(g.queue),0)
        self.assertTrue(g.WowBuddyDev.CheckMacroBindings()[0])

    def test_rejected_action_reports_failure_while_other_actions_survive(self):
        g=self.lua.globals()
        self.lua.execute("rejected='F1';WowBuddyDev.ACTION_TO_KEY={first='F1',second='F2'};WowBuddyDev.RefreshMacroBindings()")
        self.assertIsNone(g.bound.F1);self.assertIsNotNone(g.bound.F2)
        ok,passed,total,failures=g.WowBuddyDev.CheckMacroBindings()
        self.assertFalse(ok);self.assertEqual((passed,total),(1,2))
        self.assertTrue(any('first' in message for message in failures.values()))
        self.assertTrue(any('rejected' in message for message in g.errors.values()))

    def test_all_classes_build_actual_buttons_and_switch_without_stale_keys(self):
        addon=SOURCE.parent;g=self.lua.globals()
        self.lua.execute('''
        WowBuddyDev.classes={}
        function WowBuddyDev.RegisterPixelStripV2() end
        function WowBuddyDev.RegisterClass(id,data) WowBuddyDev.classes[id]=data end
        function UnitClass() return '测试',CURRENT_CLASS end
        function WowBuddyDev.LocalizeMacroBody(text) return text end
        ''')
        self.lua.execute((addon/'Bindings.lua').read_text('utf8'))
        rules=json.loads((addon.parents[1]/'assets/rules.json').read_text('utf8'))
        checked=0
        for source in sorted((addon/'classes').glob('*/class_forever.lua')):
            before=set(g.WowBuddyDev.classes.keys())
            self.lua.execute(source.read_text('utf8'))
            spec=next(iter(set(g.WowBuddyDev.classes.keys())-before))
            self.lua.execute((source.parent/(source.parent.name+'-Bindings.lua')).read_text('utf8'))
            g.CURRENT_CLASS=source.parent.name.upper()
            actions=rules['specs'][str(spec)]['actions']
            g.WowBuddyDev.ACTION_TO_KEY=self.lua.table_from({a['name']:a['key'] for a in actions})
            g.WowBuddyDev.RefreshMacroBindings()
            ok,passed,total,failures=g.WowBuddyDev.CheckMacroBindings()
            with self.subTest(spec=spec):
                self.assertTrue(ok,list(failures.values()))
                self.assertEqual(passed,total)
                used=set(g.WowBuddyDev.GetClassMacroKeys().values())
                self.assertEqual(set(g.bound.keys()),used)
                for action in actions:
                    entry=g.bound[action['key']]
                    self.assertIsNotNone(entry)
                    self.assertEqual(entry.owner.attributes.type,'macro')
                    self.assertEqual(entry.owner.attributes.macrotext,g.WowBuddyDev.GetClassDefaultMacro(action['key']))
                    checked+=1
        self.assertEqual(checked,241)
        self.assertEqual(len(g.errors),0)

    def test_extension_exception_is_visible_and_successful_refresh_clears_it(self):
        g=self.lua.globals()
        self.lua.execute('''
        WowBuddyDev.ApplyRaidFocusBindings=function() error('focus fixture') end
        WowBuddyDev.ApplyAutoTargetBinding=function() error('target fixture') end
        WowBuddyDev.RefreshMacroBindings()
        ''')
        ok,passed,total,failures=g.WowBuddyDev.CheckMacroBindings()
        self.assertFalse(ok);self.assertEqual((passed,total),(1,1))
        self.assertTrue(any('raid_focus' in s for s in failures.values()))
        self.assertTrue(any('auto_target' in s for s in failures.values()))
        self.lua.execute('''
        WowBuddyDev.ApplyRaidFocusBindings=function() end
        WowBuddyDev.ApplyAutoTargetBinding=function() return false end
        WowBuddyDev.RefreshMacroBindings()
        ''')
        self.assertTrue(g.WowBuddyDev.CheckMacroBindings()[0])

    def test_actual_raid_extension_preserves_failed_slot_and_continues_others(self):
        g=self.lua.globals()
        self.lua.execute('''
        function isRaidFocusEnabled() return true end
        function isInCombatLockdown() return combat end
        WowBuddyDev.GetRaidFocusKeys=function() return {'F3','F4'} end
        local original=WowBuddyDev.CreateSecureFocusButton
        WowBuddyDev.CreateSecureFocusButton=function(id,key,unit)
          if key=='F3' then error('secure focus setup failed') end
          return original(id,key,unit)
        end
        ''')
        source=(SOURCE.parent/'RaidFocus.lua').read_text('utf8')
        self.lua.execute(source[source.index('function WowBuddyDev.ApplyRaidFocusBindings()'):source.index('local raidFocusEventFrame')])
        g.WowBuddyDev.RefreshMacroBindings()
        ok,_,_,failures=g.WowBuddyDev.CheckMacroBindings()
        self.assertFalse(ok)
        self.assertTrue(any('raid_focus_1' in s for s in failures.values()))
        self.assertIsNotNone(g.bound.F4)

    def test_actual_auto_target_extension_records_inner_creation_exception(self):
        g=self.lua.globals()
        self.lua.execute('''
        function callBoolSafe(fn) return fn() end
        autoTargetState={};secureButtonName='auto_fixture';autoTargetMacroText='/targetenemy'
        function findFirstFreeKey() return 'F5',5 end
        WowBuddyDev.classData={};WowBuddyDev.NormalizeActionKey=function(k) return k end
        local original=WowBuddyDev.CreateSecureButton
        WowBuddyDev.CreateSecureButton=function(id,key,body)
          if id=='auto_fixture' then error('secure target setup failed') end
          return original(id,key,body)
        end
        ''')
        source=(SOURCE.parent/'AutoTarget.lua').read_text('utf8')
        self.lua.execute(source[source.index('function WowBuddyDev.ApplyAutoTargetBinding()'):])
        g.WowBuddyDev.RefreshMacroBindings()
        ok,_,_,failures=g.WowBuddyDev.CheckMacroBindings()
        self.assertFalse(ok);self.assertFalse(g.autoTargetState.bound)
        self.assertTrue(any('auto_fixture' in s for s in failures.values()))


if __name__=='__main__':unittest.main()
