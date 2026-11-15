"""完整TOC登录后的真实色块回调到桌面解码；游戏API仍为显式替身。"""
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import Mock, call

from tests import test_addon_full_load as full_load

ROOT = full_load.ROOT
sys.path.insert(0, str(ROOT / 'desktop'))
from wowbuddy.assets import Assets
from wowbuddy.dispatch import ActionDispatcher
from wowbuddy.pixel_geometry import RGBImage
from wowbuddy.dev_protocol import DEV_VERSION
from wowbuddy.scheduler import Scheduler
from wowbuddy.windows_keys import CtypesWin32Backend, KeySender


class AddonRenderIntegrationTests(unittest.TestCase):
    def test_official_frost_rotation_resumes_after_target_change(self):
        sender=Mock(status='fixture',channel='fixture')
        sender.send.return_value=True
        self.check_frost_rotation(sender,10)
        self.assertEqual(sender.send.call_args_list,
            [call(key,bypass_interval=False) for key in ('NUMPAD5','F6','NUMPAD5','F6','NUMPAD5')])

    def test_opt_in_frost_rotation_resumes_after_two_out_of_combat_kills(self):
        sender=Mock(status='fixture',channel='fixture')
        sender.send.return_value=True
        self.check_frost_rotation(sender,10,post_kill=True)
        self.assertEqual(sender.send.call_args_list,
            [call(key,bypass_interval=False) for key in ('NUMPAD5','F6','F6','NUMPAD5','F6','NUMPAD5')])

    @unittest.skipUnless(sys.platform=='win32','需要 Windows 跨进程消息投递')
    def test_frost_rotation_reaches_an_owned_background_process(self):
        for post_kill in (False, True):
            with self.subTest(post_kill=post_kill):
                self.check_background_process(post_kill)

    def check_background_process(self, post_kill):
        from ctypes import POINTER, WinDLL, byref
        from ctypes.wintypes import DWORD, HWND

        with TemporaryDirectory() as temp:
            ready = Path(temp) / 'receiver.json'
            environment = dict(os.environ, QT_QPA_PLATFORM='windows', PYTHONIOENCODING='utf-8')
            expected_keys = (0x65, 0x75, 0x75, 0x65, 0x75, 0x65) if post_kill else (0x65, 0x75, 0x65, 0x75, 0x65)
            command = [sys.executable, '-m', 'tests.test_addon_render_integration',
                       '--receiver', str(ready), str(2 * len(expected_keys))]
            with subprocess.Popen(command, cwd=ROOT, env=environment,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8',
                    creationflags=subprocess.CREATE_NO_WINDOW) as child:
                try:
                    deadline = time.monotonic() + 12
                    while not ready.is_file() and child.poll() is None and time.monotonic() < deadline:
                        time.sleep(0.025)
                    self.assertTrue(ready.is_file(), '接收子进程未创建专用窗口')
                    receiver = json.loads(ready.read_bytes())
                    hwnd = receiver['hwnd']
                    # Windows venv 启动器可能另起实际解释器。
                    self.assertIn(child.pid, (receiver['pid'], receiver['parent_pid']))
                    user = WinDLL('user32', use_last_error=True)
                    user.GetWindowThreadProcessId.argtypes = [HWND, POINTER(DWORD)]
                    user.GetWindowThreadProcessId.restype = DWORD
                    pid = DWORD()
                    self.assertTrue(user.GetWindowThreadProcessId(hwnd, byref(pid)))
                    self.assertEqual(pid.value, receiver['pid'])
                    user.IsWindowVisible.argtypes = [HWND]
                    self.assertFalse(user.IsWindowVisible(hwnd))
                    backend = CtypesWin32Backend()
                    backend.SendInput = Mock(side_effect=AssertionError('不应发送全局输入'))
                    backend.SetForegroundWindow = Mock(side_effect=AssertionError('不应激活窗口'))
                    sender = KeySender(backend, hwnd=hwnd, force_background=True,
                                       allow_activation=False, interval_ms=30, hold_ms=50)
                    self.check_frost_rotation(sender, hwnd, post_kill=post_kill)
                    self.assertEqual(sender.success_count, len(expected_keys))
                    self.assertEqual(sender.failure_count, 0)
                    self.assertEqual(sender.channel, '后台投递')
                    stdout, stderr = child.communicate(timeout=10)
                    self.assertEqual(child.returncode, 0, stderr)
                    expected = []
                    for vk in expected_keys:
                        expected.extend(([0x100, vk, 1], [0x101, vk, 0xc0000001]))
                    self.assertEqual(json.loads(stdout), expected)
                finally:
                    if child.poll() is None:
                        try:
                            child.communicate(timeout=16)
                        except subprocess.TimeoutExpired:
                            child.kill()

    def check_frost_rotation(self,sender,hwnd,*,post_kill=False):
        prelude=(ROOT/'tests/addon_login_host.lua').read_text('utf8')+'''
            -- 在模块加载前提供Core会缓存的技能接口。只有寒冰箭837已学。
            function IsSpellKnown(id) return id==837 end
            function IsUsableSpell(id) return id==837,false end
            function GetSpellCooldown(id)
                if fixtureGcd and id==837 then return now-0.1,1.5,1 end
                return 0,0,1
            end
            C_Spell={IsSpellInRange=function(id,unit) return id==837 and unit=='target' and targetAlive end}
        '''
        lua,_=full_load.AddonFullLoadTests().load(full_load.SOURCE,'WowBuddyDev',prelude)
        g=lua.globals()
        g.EmitFixtureEvent('ADDON_LOADED','WowBuddyDev')
        g.EmitFixtureEvent('PLAYER_LOGIN')
        addon=g.WowBuddyDev
        addon.DB.masterSwitch=True
        addon.SetAutoTargetEnabled(True)
        if post_kill:
            lua.execute("fixtureTargetGUID='Creature-1'; function UnitGUID() return fixtureTargetGUID end")
            checkbox=g.WowBuddyDevPostKillAutoTargetCheck
            self.assertFalse(checkbox.GetChecked(checkbox))
            # 兼容返回数值 1 的勾选控件，沿用同页「自动寻怪」的归一逻辑。
            checkbox.SetChecked(checkbox,1)
            checkbox.scripts.OnClick(checkbox)
            self.assertTrue(addon.DB.autoTargetAfterKill)
            self.assertEqual(addon.GetSecureButton('auto_target').attributes.macrotext,
                             '/targetenemy [nochanneling,noexists][nochanneling,dead]'
                             '[nocombat,nochanneling,exists,noharm]')
        g.combat=True
        addon.RebuildPixelBars()
        addon.debugFrame.Hide(addon.debugFrame)
        render=lua.execute('''
            local chosen
            for _,frame in ipairs(frames) do
                local callback=frame.scripts.OnUpdate
                if callback and debug.getinfo(callback,'S').source=='@PixelBar.lua' then
                    assert(not chosen)
                    chosen=function(delta) now=now+delta;callback(frame,delta) end
                end
            end
            return assert(chosen)
        ''')
        def clock():
            return round(g.now*1000)

        sender.backend.now_ms=clock
        dispatcher=ActionDispatcher(sender)
        scheduler=Scheduler(Assets.load(ROOT/'assets').pipeline(),dispatcher,clock)
        profile=next(p for p in json.loads((ROOT/'assets/rotations.json').read_bytes())['rotations'] if p['id']==1)

        def tick(alive, delta=0.2, *, gcd=False):
            g.targetAlive,g.fixtureGcd=alive,gcd
            if post_kill and not alive and g.combat:
                g.combat=False
                g.EmitFixtureEvent('PLAYER_REGEN_ENABLED')
            render(delta)
            pixels=[[0x0d0d0d]*24 for _ in range(1200)]
            for rect in g.visiblePixelRectangles().values():
                rgb=(round(rect.r*255)<<16)|(round(rect.g*255)<<8)|round(rect.b*255)
                for y in range(int(rect.y),int(rect.y+rect.height)):
                    for x in range(int(rect.x),int(rect.x+rect.width)):
                        pixels[y][x]=rgb
            result=scheduler.tick(RGBImage(pixels),hwnd=hwnd,send_interval_ms=100,selected_profile=profile)
            self.assertTrue(result.decision.frame.ok,result.status)
            self.assertEqual(result.decision.fields['known_116'],'ON')
            self.assertEqual(result.decision.fields['range_116'],'ON' if alive else 'OFF')
            self.assertEqual(result.decision.fields['gcd'],'ON' if gcd else 'OFF')
            return result

        self.assertEqual(tick(True).selected.key,'NUMPAD5')
        first_death=tick(False)
        self.assertEqual(first_death.selected.key,'F6')
        self.assertTrue(first_death.local_gcd_active)
        self.assertIsNone(tick(False).selected)
        button=addon.GetSecureButton('auto_target')
        button.scripts.OnClick(button,'LeftButton',True)
        if post_kill:
            # 首次按键有回执，但没有选中活怪。
            pending=tick(False,delta=0.1)
            self.assertEqual(pending.auto_gate,1)
            self.assertIsNone(pending.selected)
            retry=tick(False,delta=0.15)
            self.assertEqual(retry.selected.key,'F6')
            button.scripts.OnClick(button,'LeftButton',True)
            g.fixtureTargetGUID='Creature-2'
        new_target=tick(True)
        self.assertEqual(new_target.selected.key,'NUMPAD5')
        events={name for name,_ in new_target.events}
        self.assertTrue({'new_target_gcd_clear','new_target_clear','auto_target_clear'}<=events)

        if post_kill:
            self.assertEqual(new_target.decision.fields['player_in_combat'],'OFF')
            g.combat=True
            self.assertIsNone(tick(True,gcd=True).selected)
        self.assertEqual(tick(False).selected.key,'F6')
        button.scripts.OnClick(button,'LeftButton',True)
        if post_kill:
            g.fixtureTargetGUID='Creature-3'
        deadline=dispatcher.state.local_gcd_until_ms
        busy=tick(True,gcd=True)
        self.assertIsNone(busy.selected)
        self.assertEqual(dispatcher.state.local_gcd_until_ms,deadline)
        self.assertNotIn('new_target_gcd_clear',[name for name,_ in busy.events])
        self.assertIsNone(tick(True).selected)
        self.assertEqual(tick(True,delta=1.1).selected.key,'NUMPAD5')

    def test_spec_query_fault_closes_render_gate_and_recovers(self):
        lua=full_load.AddonFullLoadTests().world_fixture('MAGE',8,1482)
        g=lua.globals()
        g.EmitFixtureEvent('PLAYER_ENTERING_WORLD',True,False)
        g.AdvanceFixtureTime(15)
        lua.execute('''
          function IsSpellKnown() return false end
          savedSpecialization=GetSpecialization
          combat=true;WowBuddyDev.DB.masterSwitch=true;WowBuddyDev.DB.autoTarget=true
          local found=0
          for _,frame in ipairs(frames) do
            local callback=frame.scripts.OnUpdate
            if callback and debug.getinfo(callback,'S').source=='@PixelBar.lua' then
              found=found+1
              RenderFaultFixture=function() now=now+1;callback(frame,1) end
            end
          end
          assert(found==1)
        ''')
        pipeline=Assets.load(ROOT/'assets').pipeline()
        def render():
            g.RenderFaultFixture()
            pixels=[[0x0d0d0d]*24 for _ in range(1200)]
            for rect in g.visiblePixelRectangles().values():
                rgb=(round(rect.r*255)<<16)|(round(rect.g*255)<<8)|round(rect.b*255)
                for y in range(int(rect.y),int(rect.y+rect.height)):
                    for x in range(int(rect.x),int(rect.x+rect.width)):
                        self.assertTrue(0<=x<24 and 0<=y<1200)
                        pixels[y][x]=rgb
            result=pipeline.prepare(RGBImage(pixels))
            self.assertTrue(result.frame.ok,result.frame.status)
            self.assertEqual(result.frame.spec_id,'1482')
            return result.frame
        from wowbuddy.auto_target import parse_auto_target
        initial=render()
        self.assertEqual(initial.values['master_switch'],'ON')
        self.assertEqual(parse_auto_target(float(initial.values['ttd'])).state,2)
        for body in ('error("fixture specialization unavailable",0)','return "unknown"'):
            with self.subTest(body=body):
                lua.execute('function GetSpecialization() '+body+' end')
                failed=render()
                self.assertEqual(failed.values['master_switch'],'OFF')
                # 完整Core职责查询先被callBoolSafe拦截，返回合法的停发包，
                # 并非隔离AutoTarget测试中“固定远程职责”下的直接取包异常。
                stopped=parse_auto_target(float(failed.values['ttd']))
                self.assertIsNotNone(stopped)
                self.assertEqual(stopped.state,0)
                # 存储的用户开关保持开启；关闭的是发给桌面的当帧门控。
                self.assertTrue(g.WowBuddyDev.DB.masterSwitch)
                lua.execute('GetSpecialization=savedSpecialization')
                recovered=render()
                self.assertEqual(recovered.values['master_switch'],'ON')
                self.assertEqual(parse_auto_target(float(recovered.values['ttd'])).state,2)

    def test_nine_classes_full_load_render_and_decode_state_transitions(self):
        assets = Assets.load(ROOT / 'assets')
        for token, class_id, spec, _ in full_load.AddonFullLoadTests.CLASS_CASES:
            with self.subTest(class_name=token):
                lua = full_load.AddonFullLoadTests().world_fixture(token, class_id, spec)
                g = lua.globals()
                g.EmitFixtureEvent('PLAYER_ENTERING_WORLD', True, False)
                g.AdvanceFixtureTime(15)
                # 显式选择“未学技能”场景；不替换任何插件方法或字段表。
                lua.execute('''
                    function IsSpellKnown() return false end
                    renderCallbacks={}
                    for _,frame in ipairs(frames) do
                        local callback=frame.scripts.OnUpdate
                        if callback and debug.getinfo(callback,'S').source=='@PixelBar.lua' then
                            table.insert(renderCallbacks,{frame=frame,callback=callback})
                        end
                    end
                    assert(#renderCallbacks==1,'应唯一定位实际色块主回调')
                    function RenderFullAddonFixture()
                        now=now+1
                        local entry=renderCallbacks[1]
                        entry.callback(entry.frame,1)
                    end
                ''')
                pipeline = assets.pipeline()
                # 顺序执行，验证聊天门控及总开关关闭后的恢复，而非每帧重新加载。
                states = ((False, True, False, True), (True, True, False, True),
                          (True, False, False, True), (True, True, True, True),
                          (False, True, False, False), (False, True, False, True))
                for combat, alive, typing, enabled in states:
                    with self.subTest(combat=combat, alive=alive, typing=typing, enabled=enabled):
                        g.combat, g.targetAlive, g.typing = combat, alive, typing
                        g.WowBuddyDev.DB.masterSwitch = enabled
                        g.RenderFullAddonFixture()
                        pixels = [[0x0d0d0d] * 24 for _ in range(1200)]
                        rectangles = list(g.visiblePixelRectangles().values())
                        self.assertTrue(rectangles)
                        for rect in rectangles:
                            rgb = (round(rect.r*255)<<16) | (round(rect.g*255)<<8) | round(rect.b*255)
                            for y in range(int(rect.y), int(rect.y+rect.height)):
                                for x in range(int(rect.x), int(rect.x+rect.width)):
                                    self.assertTrue(0 <= x < 24 and 0 <= y < 1200)
                                    pixels[y][x] = rgb
                        frame = pipeline.prepare(RGBImage(pixels)).frame
                        self.assertTrue(frame.ok, frame.status)
                        self.assertEqual(frame.spec_id, str(spec))
                        self.assertEqual(frame.version_code, DEV_VERSION)
                        self.assertEqual(frame.values['master_switch'], 'ON' if enabled and not typing else 'OFF')
                        self.assertEqual(frame.values['target_valid'], 'ON' if alive else 'OFF')
                        self.assertEqual(frame.values['player_in_combat'], 'ON' if combat else 'OFF')
                        self.assertEqual(int(frame.values['ttd']), g.PermesValues.ttd)
                self.assertEqual(len(g.WowBuddyDev.errorLogs), 0)

    def test_warlock_leveling_profiles_use_real_macro_and_aura_bindings(self):
        from tests.test_panel_presence_integration import PROBE

        prelude = "fixtureClass='WARLOCK';fixtureClassID=9;fixtureSpecID=1490\n"
        prelude += '\n'.join((ROOT/'tests'/name).read_text('utf8')
                             for name in ('addon_login_host.lua', 'addon_world_host.lua'))
        prelude += '''
            fixturePet=false;fixturePetEngaged=false;fixtureRange=true
            local known={[688]=true,[6222]=true,[1014]=true,[707]=true,[1454]=true,
                         [695]=true,[1293817]=true}
            function IsSpellKnown(id) return known[id] or false end
            function IsUsableSpell(id) return known[id] or false,false end
            function GetSpellCooldown(id)
                if fixtureCooldown==id then return now-1,12,1 end
                return 0,0,1
            end
            function UnitExists(unit) return unit=='player' or unit=='target' or (unit=='pet' and fixturePet) end
            function UnitIsUnit(a,b)
                return a==b or (a=='pettarget' and b=='target' and fixturePetEngaged)
            end
            function UnitAffectingCombat(unit) return unit=='pet' and fixturePetEngaged or unit~='pet' and combat end
            C_Spell={IsSpellInRange=function(id,unit) return fixtureRange and unit=='target' and targetAlive end}
            Enum={LuaCurveType={Step=1}}
            C_CurveUtil={CreateColorCurve=function()
                return {SetType=function() end, AddPoint=function(self,x,color) self.last=color end}
            end}
            function UnitHealthPercent(unit,useMax,curve) return curve.last end
        '''
        original_macros = {
            'NUMPAD3': '/cast [@player,nochanneling] 召唤小鬼',
            'NUMPAD4': '/cast [harm,nodead,nochanneling] 痛苦灾祸',
            'NUMPAD5': '/cast [harm,nodead,nochanneling] 腐蚀术',
            'NUMPAD6': '/cast [harm,nodead,nochanneling] 献祭',
            'NUMPAD7': '/cast [harm,nodead,nochanneling] 暗影箭',
            'NUMPAD9': '/cast [@player,nochanneling] 生命分流',
            'CTRL-NUMPAD3': '/cast [harm,nodead,nochanneling] 燃烧',
            'CTRL-NUMPAD0': '/petattack [@target,harm,nodead,pet]',
        }
        profiles = json.loads((ROOT/'assets/rotations.json').read_bytes())['rotations']
        for profile_id in (10, 23):
            with self.subTest(profile=profile_id):
                lua, _ = full_load.AddonFullLoadTests().load(full_load.SOURCE, 'WowBuddyDev', prelude)
                g = lua.globals()
                g.EmitFixtureEvent('ADDON_LOADED', 'WowBuddyDev')
                g.EmitFixtureEvent('PLAYER_LOGIN')
                g.EmitFixtureEvent('PLAYER_ENTERING_WORLD', True, False)
                g.AdvanceFixtureTime(15)
                lua.execute(PROBE)
                lua.execute('''
                    fixtureAuras={}
                    function C_UnitAuras.GetPlayerAuraBySpellID() return nil end
                    function C_UnitAuras.GetAuraDataBySpellID(id,filter,unit)
                        if unit=='target' and fixtureAuras[id] then return {spellId=id} end
                    end
                    function C_UnitAuras.GetAuraDataByIndex(unit,index,filter)
                        if unit~='target' then return nil end
                        local found=0
                        for _,id in ipairs({6222,1014,707}) do
                            if fixtureAuras[id] then
                                found=found+1
                                if found==index then return {spellId=id} end
                            end
                        end
                    end
                ''')
                addon = g.WowBuddyDev
                addon.DB.masterSwitch = True
                addon.SetAutoTargetEnabled(False)
                g.combat = True
                addon.RebuildPixelBars()
                addon.debugFrame.Hide(addon.debugFrame)
                render = lua.execute('''
                    local chosen
                    for _,frame in ipairs(frames) do
                        local callback=frame.scripts.OnUpdate
                        if callback and debug.getinfo(callback,'S').source=='@PixelBar.lua' then
                            assert(not chosen)
                            chosen=function(delta) now=now+delta;callback(frame,delta) end
                        end
                    end
                    return assert(chosen)
                ''')
                sender = Mock(status='fixture', channel='fixture')
                sender.send.return_value = True
                def clock():
                    return round(g.now*1000)

                sender.backend.now_ms = clock
                scheduler = Scheduler(Assets.load(ROOT/'assets').pipeline(), ActionDispatcher(sender), clock)
                profile = next(item for item in profiles if item['id'] == profile_id)

                def paint(pixels, x, y, width, height, red, green, blue):
                    rgb = (round(red*255)<<16) | (round(green*255)<<8) | round(blue*255)
                    for row in pixels[y:y+height]:
                        row[x:x+width] = [rgb]*width

                def step(action=None, key=None):
                    g.refreshPanelFixture(2)
                    render(.25)
                    pixels = [[0x0d0d0d]*24 for _ in range(1200)]
                    for rect in g.visiblePixelRectangles().values():
                        paint(pixels, int(rect.x), int(rect.y), int(rect.width), int(rect.height),
                              rect.r, rect.g, rect.b)
                    # 普通色条采集不包含 PanelV2 单独绘制的光环底衬。
                    for presence in g.fixturePresenceRows.values():
                        row = presence.row
                        if presence.luaDriven and row.shown and row.parent.shown:
                            color = row.dimTex.color
                            paint(pixels, int(row.point[4]), -int(row.point[5]),
                                  int(row.width), int(row.height), color[1], color[2], color[3])
                    result = scheduler.tick(RGBImage(pixels), hwnd=10, send_interval_ms=100,
                                            selected_profile=profile)
                    self.assertTrue(result.decision.frame.ok, result.status)
                    self.assertEqual(result.decision.frame.spec_id, '1490')
                    if action is None:
                        self.assertIsNone(result.selected)
                    else:
                        observed = {name: result.decision.fields[name] for name in
                                    ('corruption', 'agony', 'immolate', 'player_health_pct', 'mana_pct')}
                        self.assertIsNotNone(result.selected, observed)
                        self.assertEqual((result.selected.action, result.selected.key), (action, key), observed)
                        self.assertTrue(result.dispatch.success)
                        button = addon.GetSecureButton('class_'+key)
                        self.assertEqual(button.attributes.macrotext, original_macros[key])
                    return result.decision.fields

                self.assertEqual(step('spell_688', 'NUMPAD3')['pet_valid'], 'OFF')
                g.fixturePet = True
                self.assertEqual(step('pet_attack', 'CTRL-NUMPAD0')['pet_on_target'], 'OFF')
                g.fixturePetEngaged = True
                first = ('spell_172', 'NUMPAD5', 6222) if profile_id == 10 else ('spell_348', 'NUMPAD6', 707)
                self.assertEqual(step(*first[:2])['pet_on_target'], 'ON')
                g.fixtureAuras[first[2]] = True
                step('spell_980', 'NUMPAD4')
                g.fixtureAuras[1014] = True
                if profile_id == 10:
                    step('spell_348', 'NUMPAD6')
                    g.fixtureAuras[707] = True
                else:
                    step('spell_1293817', 'CTRL-NUMPAD3')
                    g.fixtureCooldown = 1293817
                g.powerValue = 15
                self.assertEqual(step('spell_1454', 'NUMPAD9')['mana_pct'], '15')
                g.powerValue = 75
                self.assertEqual(step('spell_686', 'NUMPAD7')['range_686'], 'ON')
                before = sender.send.call_count
                g.fixtureRange = False
                self.assertEqual(step()['range_686'], 'OFF')
                self.assertEqual(sender.send.call_count, before)
                g.fixturePetEngaged = False
                g.fixtureRange = True
                g.fixtureAuras = lua.table()
                g.EmitFixtureEvent('PLAYER_TARGET_CHANGED')
                g.AdvanceFixtureTime(30)
                self.assertEqual(step('pet_attack', 'CTRL-NUMPAD0')['pet_on_target'], 'OFF')
                g.fixturePetEngaged = True
                fields = step(*first[:2])
                self.assertEqual([fields[key] for key in ('corruption', 'agony', 'immolate')], ['OFF']*3)
                self.assertEqual(len(addon.errorLogs), 0)


def receive_test_keys(ready, expected_messages):
    from ctypes.wintypes import MSG
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QGuiApplication, QWindow

    app = QGuiApplication([])
    messages = []

    class Receiver(QWindow):
        def nativeEvent(self, event_type, message):
            msg = MSG.from_address(int(message))
            if msg.message in (0x100, 0x101):
                messages.append([msg.message, msg.wParam, msg.lParam])
                if len(messages) == expected_messages:
                    QTimer.singleShot(0, app.quit)
                return True, 0
            return super().nativeEvent(event_type, message)

    window = Receiver()
    window.create()
    temporary = ready.with_suffix('.tmp')
    temporary.write_text(json.dumps({'hwnd': int(window.winId()), 'pid': os.getpid(),
                                    'parent_pid': os.getppid()}), 'utf-8')
    temporary.replace(ready)
    QTimer.singleShot(15000, lambda: app.exit(2))
    code = app.exec()
    print(json.dumps(messages))
    return code


if __name__ == '__main__':
    if len(sys.argv)==4 and sys.argv[1]=='--receiver':
        raise SystemExit(receive_test_keys(Path(sys.argv[2]), int(sys.argv[3])))
    unittest.main()
