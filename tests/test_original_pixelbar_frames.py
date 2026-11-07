"""原内置插件与独立插件的完整PixelBar回调差分；游戏API为显式替身。"""
import hashlib
import re
from pathlib import Path
import sys
import unittest
from lupa.lua51 import LuaRuntime, lua_type

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
from wowbuddy.packages import read_addon
from wowbuddy.dev_protocol import DEV_VERSION
from wowbuddy.assets import Assets
from wowbuddy.pixel_geometry import RGBImage


class OriginalPixelBarFramesTests(unittest.TestCase):
    def test_nine_classes_common_fields_and_visible_textures(self):
        package=Path('D:/reverse-analysis/wow-assistant/unpacked/addon.bin')
        if not package.is_file():self.skipTest('需要原内置addon.bin')
        payload=package.read_bytes()
        self.assertEqual(hashlib.sha256(payload).hexdigest(),
                         '361134bc9f2dd0b2c8cd8849b3741bd88d09c55ec371de9abc7b6f79502ebbed')
        original={m.name:m.data.decode('utf-8-sig') for m in read_addon(payload) if m.name.endswith('.lua')}
        original_version=int(re.search(r'local addonVersionCode = (\d+)',original['Core.lua']).group(1))
        pipelines=[Assets.load(ROOT/'assets').pipeline(),Assets.load(ROOT/'assets').pipeline()]
        def create(name,spec,old):
            lua=LuaRuntime(unpack_returned_tuples=True)
            lua.execute((ROOT/'tests/pixelbar_host.lua').read_text('utf8'))
            g=lua.globals();g.fixtureSpec=spec
            lua.execute('''P07483180=WowBuddyDev
            WowBuddyDev.DB.currentSpecID=fixtureSpec
            function GetSpecializationInfo() return fixtureSpec end
            function WowBuddyDev.GetPackedGameIdentity() return fixtureSpec end
            function WowBuddyDev.RegisterPixelStripV2() end
            WowBuddyDev.classes={};WowBuddyDev.forceAvailableState={}
            function WowBuddyDev.RegisterClass(id,data) registeredClass=data;WowBuddyDev.classes[id]=data end
            function IsSpellKnown() return fixtureKnown or false end
            function WowBuddyDev.GetForeverTalentState() return {packet=655360} end
            health=100; speed=0; trinket=0
            function UnitHealth() return health end
            function GetUnitSpeed() return speed end
            function WowBuddyDev.GetTrinketSlotCooldownRemaining() return trinket end
            Enum={LuaCurveType={Step=1}}
            C_CurveUtil={CreateColorCurve=function()
              return {points={},SetType=function() end,
                AddPoint=function(self,x,color) self.points[#self.points+1]={x,color} end}
            end}
            function UnitHealthPercent(unit,useMax,curve)
              if healthUnavailable then error('fixture health API unavailable') end
              local selected=nil
              for _,point in ipairs(curve.points) do
                if point[1]<=health/100 then selected=point[2] end
              end
              return selected
            end''')
            def source(path):return original[path] if old else (ROOT/'addon/WowBuddyDev'/path).read_text('utf8')
            namespace='P07483180' if old else 'WowBuddyDev'
            core=source('Core.lua');start=core.index(namespace+'.COMMON_PIXEL_DATA = {')
            lua.execute(core[start:core.index('\n}',start)+2])
            for path in ('ForeverTalentData.lua','ForeverClassSupport.lua','classes/'+name+'/class_forever.lua'):
                lua.execute(source(path))
            lua.execute('''WowBuddyDev.classData=registeredClass
            WowBuddyDev.pixelData=registeredClass.pixelData
            WowBuddyDev.actionAvailSpellIDs=registeredClass.actionAvailSpellIDs
            WowBuddyDev.testSpells=registeredClass.testSpells''')
            g.WowBuddyDev.addonVersionCode=original_version if old else DEV_VERSION
            for path in ('ActionKeyCheck.lua','AutoTarget.lua','PixelBar.lua'):
                lua.execute(source(path),namespace)
            lua.execute('''function WowBuddyDev.IsSpellUsable() return true end
            function WowBuddyDev.GetSpellCooldownRemaining() return 0 end''')
            lua.execute('WowBuddyDev.ApplyAutoTargetBinding(); WowBuddyDev.RebuildPixelBars(); WowBuddyDev.debugFrame:Hide()')
            return lua
        scripts=['', 'combat=true', 'powerValue=25; health=37; speed=3; WowBuddyDev.isMoving=2',
                 'powerUnavailable=true; healthUnavailable=true; trinket=8.7', 'powerUnavailable=false; healthUnavailable=false; health=0',
                 'targetAlive=false', 'targetAlive=true; typing=true', 'typing=false; fixtureKnown=true',
                 'WowBuddyDev.DB.masterSwitch=false', 'WowBuddyDev.DB.masterSwitch=true; combat=false',
                 'health=100; powerValue=100; speed=0; WowBuddyDev.isMoving=false; trinket=0', 'combat=true']
        frames=0
        for name,spec in [('Mage',1482),('Druid',1484),('Hunter',1485),('Paladin',1486),
                          ('Priest',1487),('Rogue',1488),('Shaman',1489),('Warlock',1490),('Warrior',1491)]:
            old,new=create(name,spec,True),create(name,spec,False)
            for index,script in enumerate(scripts):
                with self.subTest(class_name=name,step=index):
                    snapshots=[]
                    decoded=[]
                    for runtime_index,lua in enumerate((old,new)):
                        lua.execute(script);g=lua.globals();g.tickPixelBar(1)
                        # 两个明确协议变更单独排除，不掩盖其余字段/布局变化。
                        def plain(value):
                            if lua_type(value)=='table' and value['GetRGBA'] is not None:
                                return tuple(value.GetRGBA(value))
                            if lua_type(value)=='table':return {k:plain(v) for k,v in value.items()}
                            self.assertIsInstance(value,(str,int,float,bool,type(None)))
                            return value
                        fields=[field['id'] for field in g.WowBuddyDev.COMMON_PIXEL_DATA.values()]
                        fields += [field['id'] for field in g.WowBuddyDev.pixelData.values()]
                        values={k:plain(g.PermesValues[k]) for k in fields if k not in ('addon_version_code','action_avail')}
                        excluded=set()
                        for position,field in g.WowBuddyDev.COMMON_PIXEL_DATA.items():
                            if field['id'] in ('addon_version_code','action_avail'):excluded.add((0,(position-1)*4))
                        rectangles=[]
                        pixels=[[0x0d0d0d]*24 for _ in range(1200)]
                        for rect in g.visiblePixelRectangles().values():
                            rgb=(round(rect.r*255)<<16)|(round(rect.g*255)<<8)|round(rect.b*255)
                            for y in range(int(rect.y),int(rect.y+rect.height)):
                                for x in range(int(rect.x),int(rect.x+rect.width)):
                                    self.assertTrue(0<=x<24 and 0<=y<1200)
                                    pixels[y][x]=rgb
                            if (rect.x,rect.y) not in excluded:
                                rectangles.append(tuple(rect[key] for key in ('x','y','width','height','r','g','b')))
                        snapshots.append((values,sorted(rectangles),bool(g.WowBuddyDev.pixelContainer.shown)))
                        frame=pipelines[runtime_index].prepare(RGBImage(pixels)).frame
                        self.assertTrue(frame.ok,frame.status)
                        self.assertEqual(frame.protocol,'old')
                        self.assertEqual(frame.spec_id,str(spec))
                        self.assertEqual(frame.version_code,original_version if runtime_index==0 else DEV_VERSION)
                        decoded.append({k:v for k,v in frame.values.items()
                                        if k not in ('addon_version_code','action_avail')})
                    self.assertEqual(snapshots[0],snapshots[1])
                    self.assertEqual(decoded[0],decoded[1])
                    if index==2:
                        self.assertEqual(decoded[1]['player_health_pct'],'37')
                        self.assertEqual(decoded[1]['target_health_pct'],'37')
                        self.assertEqual(decoded[1]['isMoving'],'2')
                    if index==3:
                        self.assertEqual(decoded[1]['player_health_pct'],'255')
                    if index==8:
                        self.assertEqual(decoded[1]['master_switch'],'OFF')
                    self.assertTrue(snapshots[0][1])
                    frames+=1
        self.assertEqual(frames,108)


if __name__=='__main__':unittest.main()
