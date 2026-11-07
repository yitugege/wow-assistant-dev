"""执行实际Lua设置回调，保留原清除绑定后的保存调用顺序。"""
from pathlib import Path
import unittest
from lupa.lua51 import LuaRuntime
SOURCE=Path(__file__).resolve().parents[1]/'addon/WowBuddyDev/SettingsUI.lua'


class ControlKeyTests(unittest.TestCase):
    def setUp(self, source_path=SOURCE):
        self.lua=LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute('''
        combat=false; calls=0; refreshes=0;bindingSet=2;savedSets={};events={}
        function InCombatLockdown() return combat end
        function SaveBindings(value)
          calls=calls+1;savedSets[#savedSets+1]=value;events[#events+1]='save'
          if saveError then error('保存失败') end
        end
        function GetCurrentBindingSet() events[#events+1]='bindingSet';return bindingSet end
        function widget()
          return setmetatable({scripts={},hooks={}}, {__index=function(t,k)
            if k=='SetScript' then return function(self,name,fn) self.scripts[name]=fn end end
            if k=='HookScript' then return function(self,name,fn) self.hooks[name]=fn end end
            if k=='SetText' then return function(self,text) self.text=text;events[#events+1]='text' end end
            if k=='Show' then return function(self) self.shown=true end end
            if k=='CreateFontString' then return function() return widget() end end
            if k:match('^Set') or k:match('^Register') then return function() end end
          end})
        end
        parent=widget();captureHintText=widget();keyCaptureOverlay=widget()
        WowBuddyDevDB={masterKey='F6',burstKey='F7',aoeKey='F8'}
        WowBuddyDev={DB=WowBuddyDevDB,L=function(s) return s end,
          GetKeyDisplayText=function(key) return key or '未设置' end,
          CreateStyledButton=function() return widget() end,
          GetControlBindingConflict=function() if conflict then return 'action','test' end end,
          ACTION_LABELS={test='测试动作'},configFrame={}}
        for _,key in ipairs({'masterUpdate','burstUpdate','aoeUpdate'}) do
          WowBuddyDev.configFrame[key]=function() refreshes=refreshes+1 end
        end
        P07483180=WowBuddyDev
        ''')
        source=source_path.read_text('utf8')
        start=source.index('local function getKeyConflictText(')
        end=source.index('keyCaptureOverlay:SetScript("OnKeyDown"',start)
        row_start=source.index('local function createKeyBindingRow(')
        row_end=source.index('.InitDB()',row_start)
        row_end=source.rfind('\n',row_start,row_end)
        self.lua.execute(source[start:end]+source[row_start:row_end]+'''
        createRowForTest=createKeyBindingRow
        captureForTest=applyCapturedKey
        ''')

    def test_clear_each_control_key_keeps_other_saved_keys_and_refreshes_text(self):
        for combat in (False,True):
            for action,field in [('master','masterKey'),('burst','burstKey'),('aoe','aoeKey')]:
                with self.subTest(combat=combat,action=action):
                    self.setUp();g=self.lua.globals();g.combat=combat
                    button,_=g.createRowForTest(g.parent,'标签',action,0)
                    button.scripts.OnClick(button,'RightButton')
                    self.assertIsNone(g.WowBuddyDevDB[field]);self.assertEqual(button.text,'未设置')
                    self.assertEqual(list(g.savedSets.values()),[2])
                    self.assertEqual(list(g.events.values())[-3:],['text','bindingSet','save'])
                    for other,value in [('masterKey','F6'),('burstKey','F7'),('aoeKey','F8')]:
                        if other!=field:self.assertEqual(g.WowBuddyDevDB[other],value)

    def test_capture_still_writes_saved_variables_without_game_binding_calls(self):
        for action,field in [('master','masterKey'),('burst','burstKey'),('aoe','aoeKey')]:
            g=self.lua.globals();button,_=g.createRowForTest(g.parent,'标签',action,0)
            button.scripts.OnClick(button,'LeftButton')
            self.assertEqual(g.WowBuddyDev.waitingForKey,action)
            self.assertTrue(g.keyCaptureOverlay.shown)
            self.assertTrue(g.captureForTest('CTRL-F9'))
            self.assertEqual(g.WowBuddyDevDB[field],'CTRL-F9')
        self.assertEqual(g.refreshes,3)
        self.assertEqual(g.calls,0)

    def test_original_clear_callback_matches_current(self):
        original=Path('D:/reverse-analysis/wow-assistant/addon-source/SettingsUI.lua')
        if not original.is_file():self.skipTest('需要原插件源码')
        for combat in (False,True):
            for action,field in [('master','masterKey'),('burst','burstKey'),('aoe','aoeKey')]:
                for binding_set in (1,2):
                    with self.subTest(combat=combat,action=action,binding_set=binding_set):
                        snapshots=[]
                        for path in (original,SOURCE):
                            self.setUp(path);g=self.lua.globals();g.combat=combat;g.bindingSet=binding_set
                            button,_=g.createRowForTest(g.parent,'标签',action,0)
                            button.scripts.OnClick(button,'RightButton')
                            snapshots.append((dict(g.WowBuddyDevDB),button.text,list(g.events.values()),list(g.savedSets.values())))
                        self.assertEqual(*snapshots)

    def test_save_failure_keeps_preceding_db_and_display_changes(self):
        from lupa.lua51 import LuaError
        g=self.lua.globals();g.saveError=True
        button,_=g.createRowForTest(g.parent,'标签','master',0)
        with self.assertRaises(LuaError):button.scripts.OnClick(button,'RightButton')
        self.assertIsNone(g.WowBuddyDevDB.masterKey)
        self.assertEqual(button.text,'未设置')
        self.assertEqual(list(g.events.values())[-3:],['text','bindingSet','save'])

    def test_conflict_does_not_replace_existing_control_key(self):
        g=self.lua.globals();g.conflict=True;g.WowBuddyDev.waitingForKey='master'
        self.assertFalse(g.captureForTest('F1'))
        self.assertEqual(g.WowBuddyDevDB.masterKey,'F6')
        self.assertIn('测试动作',g.captureHintText.text)


if __name__=='__main__':unittest.main()
