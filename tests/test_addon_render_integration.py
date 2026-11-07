"""完整TOC登录后的真实色块回调到桌面解码；游戏API仍为显式替身。"""
import sys
import unittest

from tests import test_addon_full_load as full_load

ROOT = full_load.ROOT
sys.path.insert(0, str(ROOT / 'desktop'))
from wowbuddy.assets import Assets
from wowbuddy.pixel_geometry import RGBImage
from wowbuddy.dev_protocol import DEV_VERSION


class AddonRenderIntegrationTests(unittest.TestCase):
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


if __name__ == '__main__':
    unittest.main()
