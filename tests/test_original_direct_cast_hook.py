"""直接执行原hookButton闭包。默认处理先于挂钩为显式宿主假设，不代替游戏取证。"""
import hashlib
from pathlib import Path
import unittest
from unittest.mock import Mock, call
from lupa.lua51 import LuaRuntime
from tests import test_addon_full_load as full_load
from tests import test_original_direct_cast as original
from wowbuddy.engine.assets import Assets
from wowbuddy.core.auto_target import PACKET_BASE, parse_auto_target
from wowbuddy.engine.dispatch import ActionDispatcher
from wowbuddy.addons.packages import read_addon
from wowbuddy.core.pixel_geometry import RGBImage
from wowbuddy.engine.scheduler import Scheduler


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


class DirectCastAutoTargetLoginTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        package = Path('D:/reverse-analysis/wow-assistant/unpacked/addon.bin')
        if not package.is_file():
            raise unittest.SkipTest('需要原内置 addon.bin')
        payload = package.read_bytes()
        if hashlib.sha256(payload).hexdigest() != '361134bc9f2dd0b2c8cd8849b3741bd88d09c55ec371de9abc7b6f79502ebbed':
            raise AssertionError('原插件包摘要不一致')
        cls.members = {member.name: member.data for member in read_addon(payload)}

    def original_login(self, token, class_id, spec):
        name = 'P07483180'
        lua = LuaRuntime(unpack_returned_tuples=True, register_eval=False, register_builtins=False)
        for host in ('pixelbar_host.lua', 'addon_load_host.lua', 'addon_login_host.lua'):
            lua.execute((full_load.ROOT/'tests'/host).read_text('utf8'))
        g = lua.globals()
        g.fixtureClass, g.fixtureClassID, g.fixtureSpecID = token, class_id, spec
        shared = lua.table()
        for line in self.members[name+'.toc'].decode('utf-8-sig').splitlines():
            entry = line.strip().replace('\\', '/')
            if entry and not entry.startswith('#'):
                lua.execute(self.members[entry].decode('utf-8-sig'), name, shared, name='@'+entry)
        g.EmitFixtureEvent('ADDON_LOADED', name)
        g.EmitFixtureEvent('PLAYER_LOGIN')
        return lua

    def test_original_button_exists_but_key_packet_is_unusable_after_login(self):
        for token, class_id, spec, _ in full_load.AddonFullLoadTests.CLASS_CASES:
            with self.subTest(token=token):
                old = self.original_login(token, class_id, spec).globals()
                new = full_load.AddonFullLoadTests().login_fixture(token, class_id, spec).globals()
                original_addon, rebuilt = old.P07483180, new.WowBuddyDev
                old_button = original_addon.GetSecureButton('auto_target')
                new_button = rebuilt.GetSecureButton('auto_target')
                key, = old_button.bindings.keys()
                self.assertEqual(list(new_button.bindings.keys()), [key])
                self.assertEqual(old_button.attributes.macrotext, new_button.attributes.macrotext)
                self.assertIsNone(old_button.scripts.OnClick)
                self.assertIsNotNone(new_button.scripts.OnClick)
                self.assertFalse(original_addon.ApplyAutoTargetBinding())
                self.assertTrue(rebuilt.ApplyAutoTargetBinding())

                for g, addon in ((old, original_addon), (new, rebuilt)):
                    addon.DB.masterSwitch = True
                    addon.SetAutoTargetEnabled(True)
                    g.combat, g.targetAlive = True, True
                target = parse_auto_target(rebuilt.GetAutoTargetPacket())
                self.assertEqual((target.key, target.state, target.ack), (key, 2, 0))
                old.targetAlive = new.targetAlive = False
                raw = original_addon.GetAutoTargetPacket()
                self.assertEqual((raw-PACKET_BASE)//8192, 0)
                self.assertIsNone(parse_auto_target(raw))
                lost = parse_auto_target(rebuilt.GetAutoTargetPacket())
                self.assertEqual((lost.key, lost.state, lost.ack), (key, 1, 0))
                # 只执行回执回调，替身宿主不会执行安全宏或改变目标。
                new_button.scripts.OnClick(new_button, 'LeftButton', True)
                self.assertEqual(parse_auto_target(rebuilt.GetAutoTargetPacket()).ack, 1)

    def test_unwrapping_only_original_factory_recovers_the_packet(self):
        lua = self.original_login('MAGE', 8, 1482)
        g = lua.globals()
        addon = g.P07483180
        self.assertIsNone(parse_auto_target(addon.GetAutoTargetPacket()))
        # 独立原包对照运行时，取出包装器持有的真实 Core 函数。
        lua.execute('''
            local wrapped=P07483180.CreateSecureButton
            for index=1,20 do
                local name,value=debug.getupvalue(wrapped,index)
                if name=='origCreate' then P07483180.CreateSecureButton=value; break end
            end
            assert(P07483180.CreateSecureButton~=wrapped)
        ''')
        self.assertTrue(addon.ApplyAutoTargetBinding())
        packet = parse_auto_target(addon.GetAutoTargetPacket())
        self.assertEqual((packet.key, packet.state, packet.ack), ('F6', 0, 0))

    def test_full_login_pixel_frames_drive_two_recorded_target_requests(self):
        assets = Assets.load(full_load.ROOT/'assets')
        runtimes = (('P07483180', self.original_login('MAGE', 8, 1482)),
                    ('WowBuddyDev', full_load.AddonFullLoadTests().login_fixture('MAGE', 8, 1482)))
        for name, lua in runtimes:
            with self.subTest(addon=name):
                g = lua.globals()
                addon = g[name]
                # 宿主的纹理收集器只按此名字查找 PixelBar 容器。
                g.WowBuddyDev = addon
                addon.DB.masterSwitch = True
                addon.SetAutoTargetEnabled(True)
                g.combat = True
                addon.RebuildPixelBars()
                addon.debugFrame.Hide(addon.debugFrame)
                lua.execute('function IsSpellKnown() return false end')
                tick_pixel_bar = lua.eval('''function()
                    now = now + 1
                    local count = 0
                    for _,frame in ipairs(frames) do
                        local callback = frame.scripts.OnUpdate
                        if callback and debug.getinfo(callback,'S').source == '@PixelBar.lua' then
                            callback(frame,1)
                            count = count + 1
                        end
                    end
                    return count
                end''')
                def clock():
                    return int(g.now*1000)
                sender = Mock(status='fixture', channel='fixture')
                sender.backend.now_ms = clock
                sender.send.return_value = True
                scheduler = Scheduler(assets.pipeline(), ActionDispatcher(sender), clock)
                expected = name == 'WowBuddyDev'
                for index, alive in enumerate((True, False, True, False, True)):
                    g.targetAlive = alive
                    self.assertEqual(tick_pixel_bar(), 1)
                    pixels = [[0x0d0d0d]*24 for _ in range(1200)]
                    for rect in g.visiblePixelRectangles().values():
                        color = (round(rect.r*255)<<16) | (round(rect.g*255)<<8) | round(rect.b*255)
                        for y in range(int(rect.y), int(rect.y+rect.height)):
                            for x in range(int(rect.x), int(rect.x+rect.width)):
                                pixels[y][x] = color
                    result = scheduler.tick(RGBImage(pixels), hwnd=10, send_interval_ms=100)
                    self.assertTrue(result.decision.frame.ok, result.status)
                    self.assertEqual(result.decision.fields['target_valid'], 'ON' if alive else 'OFF')
                    self.assertEqual(result.auto_gate, (2 if alive else 1) if expected else None)
                    if expected and not alive:
                        self.assertEqual(result.status, 'sent')
                        self.assertEqual((result.selected.action, result.selected.key), ('auto_target', 'F6'))
                        button = addon.GetSecureButton('auto_target')
                        button.scripts.OnClick(button, 'LeftButton', True)
                    else:
                        self.assertIsNone(result.selected)
                    if expected and alive and index > 0:
                        self.assertIn('auto_target_clear', [event for event, _ in result.events])
                self.assertEqual(sender.send.call_args_list, [call('F6', bypass_interval=False)]*2 if expected else [])


if __name__=='__main__':unittest.main()
