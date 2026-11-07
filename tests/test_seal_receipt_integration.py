"""真实插件成功事件→色块→桌面圣印记忆；游戏 API 为显式替身。"""
import sys
import unittest
from tests import test_addon_full_load as full_load
ROOT=full_load.ROOT
sys.path.insert(0,str(ROOT/'desktop'))
from wowbuddy.assets import Assets
from wowbuddy.pixel_geometry import RGBImage
from wowbuddy.scheduler import SealMemory


class SealReceiptIntegrationTests(unittest.TestCase):
    def test_events_duplicates_and_judgement_reach_desktop_memory(self):
        lua=full_load.AddonFullLoadTests().world_fixture('PALADIN',2,1486)
        g=lua.globals();g.EmitFixtureEvent('PLAYER_ENTERING_WORLD',True,False)
        g.AdvanceFixtureTime(15)
        lua.execute('''function IsSpellKnown() return false end
          combat=true;WowBuddyDev.DB.masterSwitch=true
          found=0
          for _,frame in ipairs(frames) do
            local cb=frame.scripts.OnUpdate
            if cb and debug.getinfo(cb,'S').source=='@PixelBar.lua' then
              found=found+1;renderReceipt=function() cb(frame,1) end
            end
          end
          assert(found==1)''')
        pipeline=Assets.load(ROOT/'assets').pipeline();memory=SealMemory()
        def observe(generation,spell):
            g.renderReceipt()
            pixels=[[0x0d0d0d]*24 for _ in range(1200)]
            for rect in g.visiblePixelRectangles().values():
                color=(round(rect.r*255)<<16)|(round(rect.g*255)<<8)|round(rect.b*255)
                for y in range(int(rect.y),int(rect.y+rect.height)):
                    for x in range(int(rect.x),int(rect.x+rect.width)):
                        self.assertTrue(0<=x<24 and 0<=y<1200)
                        pixels[y][x]=color
            frame=pipeline.prepare(RGBImage(pixels)).frame
            self.assertTrue(frame.ok,frame.status)
            self.assertEqual(frame.spec_id,'1486')
            fields=frame.values
            self.assertEqual(int(fields['player_succeeded_generation']),generation)
            self.assertEqual(int(fields['player_succeeded_spell_id']),spell)
            return memory.observe(fields,round(g.now*1000))
        observe(1,0)
        g.now+=1;g.EmitFixtureEvent('UNIT_SPELLCAST_SUCCEEDED','player','Cast-seal',20154)
        fields=observe(2,20154)
        self.assertEqual(fields['seal_righteousness'],'ON')
        self.assertEqual(fields['seal_command'],'OFF')
        deadline=memory.until_ms
        # 相同GUID不重复递增回执，桌面也不能刷新圣印有效期。
        g.now+=1;g.EmitFixtureEvent('UNIT_SPELLCAST_SUCCEEDED','player','Cast-seal',20154)
        observe(2,20154);self.assertEqual(memory.until_ms,deadline)
        g.EmitFixtureEvent('UNIT_SPELLCAST_SUCCEEDED','target','Cast-other',20271)
        observe(2,20154);self.assertEqual(memory.until_ms,deadline)
        g.now+=1;g.EmitFixtureEvent('UNIT_SPELLCAST_SUCCEEDED','player','Cast-judge',20271)
        fields=observe(3,20271)
        self.assertEqual([fields[k] for k in ('seal_fury','seal_righteousness','seal_command')],['OFF']*3)
        self.assertEqual(memory.seal,'')
        self.assertEqual(memory.judgement_ms,round(g.now*1000))


if __name__=='__main__':unittest.main()
