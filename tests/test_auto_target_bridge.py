"""执行真实Lua选怪状态机，再由桌面解析器解码；不模拟真实游戏施法。"""
import sys
import unittest
from types import SimpleNamespace
from pathlib import Path
from lupa.lua51 import LuaRuntime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'desktop'))
sys.path.insert(0, str(ROOT/'tests/core'))
from wowbuddy.auto_target import parse_auto_target, key_for_index


class AutoTargetBridgeTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute('''
        WowBuddyDev={DB={masterSwitch=true},classData={}}
        combat=false; exists=true; dead=false; focus=false; enabled=true
        button={HookScript=function(self,event,callback) self.callback=callback end}
        function CreateFrame() return {RegisterEvent=function() end,
          SetScript=function(self,event,fn) resetSession=fn end} end
        function UnitAffectingCombat() return combat end
        function InCombatLockdown() return combat end
        function UnitExists() return exists end
        function UnitIsDeadOrGhost(unit) return unit=='target' and dead or false end
        function UnitCanAttack() return true end
        function UnitCanAssist() return false end
        function GetCurrentKeyBoardFocus() if focus then return {} end end
        function GetSpecialization() return 1 end
        function GetSpecializationInfo() return 1491 end
        function WowBuddyDev.IsRangedDamageSpec() return true end
        function WowBuddyDev.IsMeleeSpec() return false end
        function WowBuddyDev.GetAutoTargetEnabled() return enabled end
        function WowBuddyDev.CreateSecureButton(name,key,text)
          boundKey=key; macro=text; return true
        end
        function WowBuddyDev.GetSecureButton() return button end
        ''')
        for name in ('ActionKeyCheck.lua', 'AutoTarget.lua'):
            self.lua.execute((ROOT/'addon/WowBuddyDev'/name).read_text('utf8'))
        self.assertTrue(self.lua.eval('WowBuddyDev.ApplyAutoTargetBinding()'))

    def packet(self):
        packet = parse_auto_target(self.lua.eval('WowBuddyDev.GetAutoTargetPacket()'))
        self.assertIsNotNone(packet)
        self.assertEqual(packet.key, self.lua.globals().boundKey)
        return packet

    def test_all_lua_key_indices_match_desktop(self):
        keys = self.lua.globals().WowBuddyDev.AUTO_TARGET_KEYS
        self.assertEqual(len(keys), 81)
        for index in range(1, 82):
            self.assertEqual(keys[index], key_for_index(index))

    def test_death_in_combat_requests_target_but_combat_exit_stops(self):
        self.assertEqual(self.packet().state, 0)
        self.lua.execute('combat=true')
        self.assertEqual(self.packet().state, 2)
        self.lua.execute('dead=true')
        self.assertEqual(self.packet().state, 1)
        self.lua.execute('combat=false; resetSession()')
        self.assertEqual(self.packet().state, 0)
        self.assertIn('[combat,nochanneling,dead]', self.lua.globals().macro)

    def test_keyboard_focus_switch_and_click_ack(self):
        self.lua.execute('combat=true')
        self.packet()
        self.lua.execute('exists=false')
        self.assertEqual(self.packet().state, 1)
        self.lua.execute('focus=true')
        self.assertEqual(self.packet().state, 0)
        self.lua.execute('focus=false; enabled=false')
        self.assertEqual(self.packet().state, 0)
        self.lua.execute('enabled=true; button.callback()')
        self.assertEqual(self.packet().ack, 1)
        self.lua.execute('WowBuddyDev.DB.masterSwitch=false')
        self.assertEqual(self.packet().state, 0)

    def test_lua_packet_through_pixels_scheduler_and_dispatch(self):
        from test_old_protocol import CONTRACT,RULES,render_old
        from test_pipeline import READABLE,READABLE_RULES,render_readable
        from wowbuddy.pipeline import DecisionPipeline
        from wowbuddy.scheduler import Scheduler
        from wowbuddy.dispatch import ActionDispatcher
        for protocol in ('old','readable'):
            with self.subTest(protocol=protocol):
                self.setUp()
                clock=[10000];sent=[]
                def send(key,**kwargs):sent.append(key);return True
                sender=SimpleNamespace(send=send,status='测试投递',channel='fixture',
                    backend=SimpleNamespace(now_ms=lambda:clock[0],Sleep=lambda ms:None))
                pipeline=DecisionPipeline(CONTRACT,READABLE,RULES,READABLE_RULES)
                dispatcher=ActionDispatcher(sender)
                scheduler=Scheduler(pipeline,dispatcher,lambda:clock[0])
                profile={'specId':1482,'rules':[{'action':'spell_116','when':['flag','target_valid',True]}]}
                def tick(target,advance=500):
                    clock[0]+=advance
                    packed=self.lua.eval('WowBuddyDev.GetAutoTargetPacket()')
                    values={'ttd':packed,'master_switch':0x00ff00,'target_valid':0x00ff00 if target else 0xff0000,
                        'target_health_pct':100 if target else 0,'player_health_pct':100,
                        'player_valid':0x00ff00,'player_casting':0xff0000,'gcd':0xff0000,
                        'player_in_combat':0x00ff00,'mage_talents':0x0a0000}
                    image=render_old(1482,values)[0] if protocol=='old' else render_readable(1482,values)
                    result=scheduler.tick(image,hwnd=123,send_interval_ms=100,selected_profile=profile)
                    self.assertTrue(result.decision.frame.ok)
                    self.assertEqual(pipeline.engine.last_auto_packet,parse_auto_target(packed))
                    return result
                self.lua.execute('combat=true')
                first=tick(True)
                self.assertIsNotNone(first.selected,(first.status,first.decision.fields,first.decision.candidates))
                self.assertEqual(first.selected.action,'spell_116')
                self.lua.execute('dead=true')
                dead=tick(False)
                self.assertEqual((dead.status,dead.selected.action),('sent','auto_target'))
                self.assertEqual(sent[-1],self.lua.globals().boundKey)
                self.assertTrue(dead.selected.off_gcd)
                self.assertTrue(scheduler.state.auto_waiting)
                count=len(sent)
                held=tick(False,150)
                # 原调度器只要本地GCD仍活动，未发送统一报告gcd_blocked。
                self.assertEqual(held.status,'gcd_blocked')
                self.assertGreater(dispatcher.state.auras.suppression_until['auto_target'],clock[0])
                self.assertEqual(len(sent),count)
                self.lua.execute('button.callback(); dead=false')
                acquired=tick(True)
                self.assertEqual(acquired.selected.action,'spell_116')
                self.assertEqual(pipeline.engine.last_auto_packet.ack,1)
                self.assertFalse(scheduler.state.auto_waiting)
                self.assertIn('auto_target_clear',[name for name,_ in acquired.events])
                self.lua.execute('dead=true; focus=true')
                count=len(sent)
                typing=tick(False,2000)
                self.assertEqual(typing.status,'no_candidates')
                self.assertEqual(len(sent),count)
                self.lua.execute('focus=false; WowBuddyDev.DB.masterSwitch=false')
                master_off=tick(False)
                self.assertEqual(master_off.status,'no_candidates')
                self.assertEqual(len(sent),count)
                self.lua.execute('WowBuddyDev.DB.masterSwitch=true')
                self.lua.execute('dead=true; combat=false; resetSession()')
                count=len(sent)
                stopped=tick(False,2000)
                self.assertEqual(stopped.status,'no_candidates')
                self.assertEqual(len(sent),count)
