"""运行真实职业绑定注册，覆盖桌面动作到实际安全按钮创建请求。"""
import json
from pathlib import Path
import unittest
from lupa.lua51 import LuaRuntime

ROOT=Path(__file__).resolve().parents[1]
ADDON=ROOT/'addon/WowBuddyDev'

class ClassRegistrationTests(unittest.TestCase):
    def test_all_desktop_actions_have_nonempty_registered_macro(self):
        lua=LuaRuntime(unpack_returned_tuples=True)
        lua.execute('''
        WowBuddyDev={classes={}}
        function WowBuddyDev.RegisterPixelStripV2() end
        function WowBuddyDev.RegisterClass(id,data) WowBuddyDev.classes[id]=data end
        function CreateFrame() return {RegisterUnitEvent=function() end,
          RegisterEvent=function() end,SetScript=function() end} end
        function UnitClass() return '测试', CURRENT_CLASS end
        function WowBuddyDev.LocalizeMacroBody(text) return text end
        function WowBuddyDev.CreateSecureButton(action,key,body)
          assert(registered[key]==nil,'duplicate actual key')
          registered[key]=body
          return true
        end
        ''')
        lua.execute((ADDON/'Bindings.lua').read_text('utf8'))
        rules=json.loads((ROOT/'assets/rules.json').read_text('utf8'))
        checked=0
        for source in sorted((ADDON/'classes').glob('*/class_forever.lua')):
            before=set(lua.globals().WowBuddyDev.classes.keys())
            lua.execute(source.read_text('utf8'))
            spec=next(iter(set(lua.globals().WowBuddyDev.classes.keys())-before))
            lua.execute((source.parent/(source.parent.name+'-Bindings.lua')).read_text('utf8'))
            lua.globals().CURRENT_CLASS=source.parent.name.upper()
            lua.execute('registered={}; assert(WowBuddyDev.ApplyClassMacros())')
            for action in rules['specs'][str(spec)]['actions']:
                with self.subTest(spec=spec,action=action['name']):
                    self.assertTrue(lua.globals().registered[action['key']])
                    checked+=1
            if spec==1484:
                self.assertEqual(lua.globals().registered['SHIFT-F2'],
                    lua.globals().WowBuddyDev.classes[spec].DEFAULT_MACROS['spell_17056'])
        self.assertEqual(checked,241)
