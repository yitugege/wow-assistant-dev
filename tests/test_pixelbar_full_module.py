"""整个PixelBar文件和真实回调；游戏API及UI纹理用显式替身。"""
from pathlib import Path
import sys
import unittest
from lupa.lua51 import LuaRuntime

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
from wowbuddy.auto_target import parse_auto_target
from wowbuddy.dev_protocol import DEV_VERSION


class PixelBarModuleTests(unittest.TestCase):
    def test_full_module_rebuild_and_onupdate_write_auto_target_texture(self):
        lua=LuaRuntime(unpack_returned_tuples=True)
        lua.execute((ROOT/'tests/pixelbar_host.lua').read_text('utf8'))
        lua.globals().WowBuddyDev.addonVersionCode=DEV_VERSION
        source=(ROOT/'addon/WowBuddyDev/Core.lua').read_text('utf8')
        start=source.index('WowBuddyDev.COMMON_PIXEL_DATA = {')
        lua.execute(source[start:source.index('\n}',start)+2])
        for name in ('ActionKeyCheck.lua','AutoTarget.lua','PixelBar.lua'):
            lua.execute((ROOT/'addon/WowBuddyDev'/name).read_text('utf8'),'WowBuddyDev')
        lua.execute('WowBuddyDev.ApplyAutoTargetBinding(); WowBuddyDev.RebuildPixelBars()')
        g=lua.globals()
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


if __name__=='__main__':unittest.main()
