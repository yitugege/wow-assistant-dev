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
    def setUp(self, source_dir=None):
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
        self.lua.execute('P07483180=WowBuddyDev')
        source_dir=source_dir or ROOT/'addon/WowBuddyDev'
        for name in ('ActionKeyCheck.lua', 'AutoTarget.lua'):
            self.lua.execute((source_dir/name).read_text('utf8'))
        self.assertTrue(self.lua.eval('WowBuddyDev.ApplyAutoTargetBinding()'))

    def test_original_lua_gate_failures_and_recovery(self):
        reference=Path('D:/reverse-analysis/wow-assistant/addon-source')
        if not reference.is_dir():self.skipTest('需要原内置插件参考源码')
        from wowbuddy.packages import read_addon
        members={m.name:m.data for m in read_addon((reference.parent/'unpacked/addon.bin').read_bytes())}
        for name in ('ActionKeyCheck.lua','AutoTarget.lua'):
            self.assertEqual((reference/name).read_bytes(),members[name])
        self.setUp(reference);original=self.lua
        self.setUp();rebuilt=self.lua
        baseline='''combat=true;exists=true;dead=false;focus=false;enabled=true
        WowBuddyDev.DB.masterSwitch=true;WowBuddyDev.DB.masterKey=nil
        function GetCurrentKeyBoardFocus() if focus then return {} end end
        function UnitAffectingCombat() return combat end
        function UnitExists() return exists end
        function UnitIsDeadOrGhost(unit) return unit=='target' and dead or false end
        function UnitCanAttack() return true end
        function GetSpecializationInfo() return 1491 end'''
        cases=[('dead','dead=true'),('absent','exists=false'),
               ('typing','focus=true'),('master_off','WowBuddyDev.DB.masterSwitch=false'),
               ('disabled','enabled=false'),('combat_exit','combat=false;resetSession()'),
               ('key_conflict','WowBuddyDev.DB.masterKey=boundKey'),
               ('spec_switch','exists=false;function GetSpecializationInfo() return 1482 end')]
        for api in ('GetCurrentKeyBoardFocus','UnitAffectingCombat','UnitExists','UnitIsDeadOrGhost','UnitCanAttack'):
            for mode,body in (('nil','return nil'),('error',"error('unreadable')")):
                cases.append((api+'_'+mode,'function '+api+'() '+body+' end'))
        for name,mutation in cases:
            with self.subTest(case=name):
                # 先建立有效战斗会话，再扰动，最后恢复；比较完整包而非仅状态位。
                for lua in (original,rebuilt):lua.execute(baseline+';resetSession()')
                for command in ('',mutation,baseline):
                    packets=[]
                    for lua in (original,rebuilt):
                        lua.execute(command)
                        packets.append(lua.eval('WowBuddyDev.GetAutoTargetPacket()'))
                    self.assertEqual(*packets)
                    self.assertIsNotNone(parse_auto_target(packets[1]))
                self.assertEqual(parse_auto_target(packets[1]).state,2)
        # 验证31次序号与32次回执循环不会使包越界或跨版本不同。
        for _ in range(70):
            packets=[]
            for lua in (original,rebuilt):
                lua.execute('button.callback()')
                packets.append(lua.eval('WowBuddyDev.GetAutoTargetPacket()'))
            self.assertEqual(*packets)
            self.assertEqual(parse_auto_target(packets[1]).state,2)
        self.assertEqual(original.globals().macro,rebuilt.globals().macro)
        self.assertEqual(original.globals().boundKey,rebuilt.globals().boundKey)

    def packet(self):
        packet = parse_auto_target(self.lua.eval('WowBuddyDev.GetAutoTargetPacket()'))
        self.assertIsNotNone(packet)
        self.assertEqual(packet.key, self.lua.globals().boundKey)
        return packet

    def original_pair(self):
        import hashlib
        from wowbuddy.packages import read_addon
        reference=Path('D:/reverse-analysis/wow-assistant/addon-source')
        package=reference.parent/'unpacked/addon.bin'
        if not package.exists():self.skipTest('需要原内置插件包')
        data=package.read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(),
                         '361134bc9f2dd0b2c8cd8849b3741bd88d09c55ec371de9abc7b6f79502ebbed')
        members={m.name:m.data for m in read_addon(data)}
        for name in ('ActionKeyCheck.lua','AutoTarget.lua'):
            self.assertEqual((reference/name).read_bytes(),members[name])
        self.setUp(reference);original=self.lua
        self.setUp()
        return original,self.lua

    def test_original_key_exhaustion_combat_rebind_and_recovery(self):
        histories=[]
        for lua in self.original_pair():
            rows=[]
            lua.execute('''repeatHooks=0
              function button:HookScript(event,callback)
                repeatHooks=repeatHooks+1;error('same button must not be hooked again')
              end''')
            for command in (
                'combat=true; return WowBuddyDev.GetAutoTargetPacket()',
                # 战斗中重绑直接失败，但不得清掉之前可用的绑定。
                'assert(WowBuddyDev.ApplyAutoTargetBinding()==false); return WowBuddyDev.GetAutoTargetPacket()',
                # 脱战重绑时所有候选键占满，清除状态并产生接收端不能解码的keyIndex=0包。
                '''combat=false;WowBuddyDev.ACTION_TO_KEY={}
                for i,key in ipairs(WowBuddyDev.AUTO_TARGET_KEYS) do WowBuddyDev.ACTION_TO_KEY[i]=key end
                assert(WowBuddyDev.ApplyAutoTargetBinding()==false)
                return WowBuddyDev.GetAutoTargetPacket()''',
                # 只释放最后一键，必须选择原第81个索引，而非任意新增按键。
                '''WowBuddyDev.ACTION_TO_KEY[81]=nil
                assert(WowBuddyDev.ApplyAutoTargetBinding()==true)
                combat=true;return WowBuddyDev.GetAutoTargetPacket()''',
                # 相同按钮反复绑定不叠加点击回执。
                '''combat=false;assert(WowBuddyDev.ApplyAutoTargetBinding()==true)
                button.callback();combat=true;return WowBuddyDev.GetAutoTargetPacket()''',
            ):
                rows.append(lua.execute(command))
            self.assertEqual(lua.globals().repeatHooks,0)
            histories.append(rows)
        self.assertEqual(*histories)
        packets=[parse_auto_target(v) for v in histories[1]]
        self.assertEqual((packets[0].key_index,packets[0].state),(1,2))
        self.assertEqual((packets[1].key_index,packets[1].state),(1,2))
        self.assertIsNone(packets[2])
        self.assertEqual((packets[3].key_index,packets[3].key,packets[3].state),(81,'ALT-END',2))
        self.assertEqual(packets[4].ack,1)

    def test_original_spec_query_failure_and_recovery_trace(self):
        histories=[]
        for lua in self.original_pair():
            rows=[]
            lua.execute('combat=true')
            rows.append(lua.eval('WowBuddyDev.GetAutoTargetPacket()'))
            lua.execute('exists=false; function GetSpecializationInfo() error("fixture",0) end')
            rows.append(lua.eval('WowBuddyDev.GetAutoTargetPacket()'))
            lua.execute('exists=true')
            rows.append(lua.eval('WowBuddyDev.GetAutoTargetPacket()'))
            lua.execute('exists=false')
            rows.append(lua.eval('WowBuddyDev.GetAutoTargetPacket()'))
            # 第一层GetSpecialization没有pcall：原代码在抛错或返回非数字时中断。
            for body in ('error("fixture",0)','return "unknown"'):
                lua.execute('function GetSpecialization() '+body+' end')
                ok,error=lua.eval('pcall(WowBuddyDev.GetAutoTargetPacket)')
                self.assertFalse(ok);self.assertIsInstance(error,str)
                rows.append(ok)
            lua.execute('function GetSpecialization() return 1 end; function GetSpecializationInfo() return 1491 end')
            rows.append(lua.eval('WowBuddyDev.GetAutoTargetPacket()'))
            lua.execute('exists=true')
            rows.append(lua.eval('WowBuddyDev.GetAutoTargetPacket()'))
            histories.append(rows)
        self.assertEqual(*histories)
        self.assertEqual([parse_auto_target(histories[1][i]).state for i in (0,1,2,3,6,7)],
                         [2,0,2,1,0,2])

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
