"""整个PixelBar文件和真实回调；游戏API及UI纹理用显式替身。"""
from pathlib import Path
import sys
import unittest
from lupa.lua51 import LuaRuntime

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
from wowbuddy.auto_target import parse_auto_target
from wowbuddy.dev_protocol import DEV_VERSION
from wowbuddy.assets import Assets
from wowbuddy.pixel_geometry import RGBImage


class PixelBarModuleTests(unittest.TestCase):
    def test_full_module_rebuild_and_onupdate_write_auto_target_texture(self):
        self.exercise(False)

    def test_mage_registered_layout_to_desktop_decoder(self):
        self.exercise(True)

    def exercise(self,include_mage):
        lua=LuaRuntime(unpack_returned_tuples=True)
        lua.execute((ROOT/'tests/pixelbar_host.lua').read_text('utf8'))
        lua.globals().WowBuddyDev.addonVersionCode=DEV_VERSION
        source=(ROOT/'addon/WowBuddyDev/Core.lua').read_text('utf8')
        start=source.index('WowBuddyDev.COMMON_PIXEL_DATA = {')
        lua.execute(source[start:source.index('\n}',start)+2])
        if include_mage:
            lua.execute('''
            function WowBuddyDev.RegisterPixelStripV2() end
            function WowBuddyDev.RegisterClass(id,data) registeredClass=data end
            function IsSpellKnown() return false end
            WowBuddyDev.forceAvailableState={}
            function WowBuddyDev.FillForeverExtraValues(values)
              values.target_valid=targetAlive;values.player_valid=true
              values.player_in_combat=combat;values.mana_pct=75
            end
            ''')
            lua.execute((ROOT/'addon/WowBuddyDev/classes/Mage/class_forever.lua').read_text('utf8'))
            lua.execute('''WowBuddyDev.classData=registeredClass
            WowBuddyDev.pixelData=registeredClass.pixelData
            WowBuddyDev.actionAvailSpellIDs=registeredClass.actionAvailSpellIDs
            WowBuddyDev.testSpells=registeredClass.testSpells''')
        for name in ('ActionKeyCheck.lua','AutoTarget.lua','PixelBar.lua'):
            lua.execute((ROOT/'addon/WowBuddyDev'/name).read_text('utf8'),'WowBuddyDev')
        lua.execute('WowBuddyDev.ApplyAutoTargetBinding(); WowBuddyDev.RebuildPixelBars()')
        lua.execute('WowBuddyDev.debugFrame:Hide()')
        g=lua.globals()
        assets=Assets.load(ROOT/'assets')
        pipeline=assets.pipeline()
        if include_mage:
            actual=[g.WowBuddyDev.pixelData[i]['id'] for i in range(1,len(g.WowBuddyDev.pixelData)+1)]
            expected=[field['id'] for field in assets.contract['specs']['1482']['fields']]
            self.assertEqual(actual,expected)
            for index in range(len(g.WowBuddyDev.COMMON_PIXEL_DATA)+len(actual)):
                slot=g.pixelAt(0,-index*4)
                self.assertIsNotNone(slot)
                self.assertEqual((slot.width,slot.height),(4,4))
        def captured_frame():
            # 固定背景画布，只按真实Lua纹理记录绘制；不按桌面契约排列字段。
            pixels=[[0x0d0d0d]*24 for _ in range(1200)]
            for rect in g.visiblePixelRectangles().values():
                rgb=(round(rect.r*255)<<16)|(round(rect.g*255)<<8)|round(rect.b*255)
                for y in range(int(rect.y),int(rect.y+rect.height)):
                    for x in range(int(rect.x),int(rect.x+rect.width)):
                        self.assertTrue(0<=x<24 and 0<=y<1200)
                        pixels[y][x]=rgb
            return pipeline.prepare(RGBImage(pixels)).frame
        texture=g.pixelAt(0,-76)
        self.assertEqual((texture.width,texture.height),(4,4))
        marker=g.pixelAt(4,-128)
        color=lambda obj:tuple(obj.color[i] for i in range(1,5))
        self.assertEqual(color(marker),(1,0,1,1))
        def tick():
            g.tickPixelBar(1)
            r,bg,b,a=color(texture)
            value=(round(r*255)<<16)|(round(bg*255)<<8)|round(b*255)
            self.assertEqual(value,g.PermesValues.ttd)
            self.assertEqual(a,1)
            frame=captured_frame()
            if g.WowBuddyDev.pixelContainer.shown:
                self.assertTrue(frame.ok,frame.status)
                self.assertEqual(frame.protocol,'old')
                self.assertEqual(frame.spec_id,'1482')
                self.assertEqual(frame.version_code,DEV_VERSION)
                self.assertEqual(int(frame.values['ttd']),value)
                self.assertEqual(frame.values['master_switch'],'ON' if g.PermesValues.master_switch else 'OFF')
                if include_mage:
                    self.assertEqual(frame.values['target_valid'],'ON' if g.targetAlive else 'OFF')
                    self.assertEqual(frame.values['player_valid'],'ON')
                    self.assertEqual(frame.values['mana_pct'],'75')
            else:
                self.assertFalse(frame.ok)
            return parse_auto_target(value)
        self.assertEqual(tick().state,0)
        lua.execute('combat=true')
        self.assertEqual(tick().state,2)
        lua.execute('targetAlive=false')
        dead=tick()
        self.assertEqual(dead.state,1)
        lua.execute("WowBuddyDev.GetSecureButton().scripts.OnClick()")
        receipt=tick()
        self.assertEqual(receipt.ack,1)
        self.assertNotEqual(receipt.sequence,dead.sequence)
        lua.execute('typing=true')
        self.assertEqual(tick().state,0)
        self.assertEqual(color(g.pixelAt(0,0)),(1,0,0,1))
        lua.execute('typing=false; combat=false')
        self.assertEqual(tick().state,0)
        # 完整回调捕获取包异常后继续画其余字段，不沿用上一帧包。
        lua.execute('WowBuddyDev.GetAutoTargetPacket=function() error("fixture") end')
        self.assertIsNone(tick())
        self.assertEqual(g.PermesValues.ttd,0)
        before=texture.writes
        lua.execute('WowBuddyDev.ToggleAllOverlayVisibility()')
        self.assertFalse(g.WowBuddyDev.pixelContainer.shown)
        self.assertFalse(g.WowBuddyDev.DB.masterSwitch)
        tick()
        self.assertGreater(texture.writes,before)
        self.assertEqual(color(g.pixelAt(0,0)),(1,0,0,1))
        lua.execute('WowBuddyDev.ToggleAllOverlayVisibility()')
        self.assertTrue(g.WowBuddyDev.pixelContainer.shown)
        tick()


if __name__=='__main__':unittest.main()
