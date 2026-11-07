"""执行实际Lua设置回调：插件控制键无需修改游戏绑定表。"""
from pathlib import Path
import unittest
from lupa.lua51 import LuaRuntime
SOURCE=Path(__file__).resolve().parents[1]/'addon/WowBuddyDev/SettingsUI.lua'


class ControlKeyTests(unittest.TestCase):
    def setUp(self):
        self.lua=LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute('''
        combat=false; calls=0; refreshes=0
        function InCombatLockdown() return combat end
        function SaveBindings() error('不应调用游戏绑定保存') end
        function GetCurrentBindingSet() error('不应读取游戏绑定集') end
        function widget()
          return setmetatable({scripts={},hooks={}}, {__index=function(t,k)
            if k=='SetScript' then return function(self,name,fn) self.scripts[name]=fn end end
            if k=='HookScript' then return function(self,name,fn) self.hooks[name]=fn end end
            if k=='SetText' then return function(self,text) self.text=text end end
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
        ''')
        source=SOURCE.read_text('utf8')
        start=source.index('local function getKeyConflictText(')
        end=source.index('keyCaptureOverlay:SetScript("OnKeyDown"',start)
        row_start=source.index('local function createKeyBindingRow(')
        row_end=source.index('\nWowBuddyDev.InitDB()',row_start)
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

    def test_conflict_does_not_replace_existing_control_key(self):
        g=self.lua.globals();g.conflict=True;g.WowBuddyDev.waitingForKey='master'
        self.assertFalse(g.captureForTest('F1'))
        self.assertEqual(g.WowBuddyDevDB.masterKey,'F6')
        self.assertIn('测试动作',g.captureHintText.text)


if __name__=='__main__':unittest.main()
