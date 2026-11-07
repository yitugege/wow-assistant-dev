"""整个PixelBar文件和真实回调；游戏API及UI纹理用显式替身。"""
from pathlib import Path
import json
import sys
import unittest
from types import SimpleNamespace
from lupa.lua51 import LuaRuntime

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
from wowbuddy.auto_target import parse_auto_target
from wowbuddy.dev_protocol import DEV_VERSION
from wowbuddy.assets import Assets
from wowbuddy.pixel_geometry import RGBImage
from wowbuddy.scheduler import Scheduler
from wowbuddy.dispatch import ActionDispatcher


class PixelBarModuleTests(unittest.TestCase):
    def test_full_module_rebuild_and_onupdate_write_auto_target_texture(self):
        self.exercise()

    def test_mage_registered_layout_to_desktop_decoder(self):
        self.exercise('Mage',1482)

    def test_other_class_registered_layouts_to_desktop_decoder(self):
        for name,spec in (('Druid',1484),('Hunter',1485),('Paladin',1486),
                          ('Priest',1487),('Rogue',1488),('Shaman',1489),
                          ('Warlock',1490),('Warrior',1491)):
            with self.subTest(class_name=name,spec_id=spec):
                self.exercise(name,spec)

    def exercise(self,class_name=None,spec_id=1482):
        lua=LuaRuntime(unpack_returned_tuples=True)
        lua.execute((ROOT/'tests/pixelbar_host.lua').read_text('utf8'))
        lua.globals().WowBuddyDev.addonVersionCode=DEV_VERSION
        lua.globals().fixtureSpec=spec_id
        lua.execute('''WowBuddyDev.DB.currentSpecID=fixtureSpec
        function GetSpecializationInfo() return fixtureSpec end
        function WowBuddyDev.GetPackedGameIdentity() return fixtureSpec end''')
        source=(ROOT/'addon/WowBuddyDev/Core.lua').read_text('utf8')
        start=source.index('WowBuddyDev.COMMON_PIXEL_DATA = {')
        lua.execute(source[start:source.index('\n}',start)+2])
        if class_name:
            lua.execute('''
            function WowBuddyDev.RegisterPixelStripV2() end
            WowBuddyDev.classes={}
            function WowBuddyDev.RegisterClass(id,data) registeredClass=data;WowBuddyDev.classes[id]=data end
            function IsSpellKnown() return false end
            WowBuddyDev.forceAvailableState={}
            function WowBuddyDev.GetForeverTalentState() return {packet=655360} end
            ''')
            for name in ('ForeverTalentData.lua','ForeverClassSupport.lua'):
                lua.execute((ROOT/'addon/WowBuddyDev'/name).read_text('utf8'))
            lua.execute((ROOT/'addon/WowBuddyDev/classes'/class_name/'class_forever.lua').read_text('utf8'))
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
        if class_name:
            actual=[g.WowBuddyDev.pixelData[i]['id'] for i in range(1,len(g.WowBuddyDev.pixelData)+1)]
            expected=[field['id'] for field in assets.contract['specs'][str(spec_id)]['fields']]
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
                self.assertEqual(frame.spec_id,str(spec_id))
                self.assertEqual(frame.version_code,DEV_VERSION)
                self.assertEqual(int(frame.values['ttd']),value)
                self.assertEqual(frame.values['master_switch'],'ON' if g.PermesValues.master_switch else 'OFF')
                if class_name:
                    self.assertEqual(frame.values['target_valid'],'ON' if g.targetAlive else 'OFF')
                    self.assertEqual(frame.values['player_valid'],'ON')
                    self.assertEqual(frame.values['player_in_combat'],'ON' if g.combat else 'OFF')
                    # 原number字段保留白色整数；只有特定类型/字段映射无值提示。
                    self.assertEqual(frame.values['mana_pct'],'16777215' if g.powerUnavailable else str(g.powerValue))
                    self.assertEqual(frame.values[class_name.lower()+'_talents'],'10/0/0')
            else:
                self.assertFalse(frame.ok)
            return parse_auto_target(value)
        self.assertEqual(tick().state,0)
        lua.execute('combat=true')
        self.assertEqual(tick().state,2)
        if class_name:
            lua.execute('powerValue=25')
            tick()
            lua.execute('powerUnavailable=true')
            tick()
            self.assertEqual(g.PermesValues.mana_pct,16777215)
            lua.execute('powerUnavailable=false; powerValue=75')
            tick()
        if class_name=='Mage':
            # 仅游戏查询输入可控，保留PixelBar的IsSpellKnown/IsSpellReady及职业采集。
            lua.execute('''knownRank=nil; rangeResult=true; cooldown=0; usable=true
            function IsSpellKnown(id) return id==knownRank end
            C_Spell={IsSpellInRange=function(id,unit)
                rangeQueriedRank=id;return rangeResult
            end}
            function WowBuddyDev.GetSpellCooldownRemaining() return cooldown end
            function WowBuddyDev.IsSpellUsable() return usable end''')
            spell_index=list(g.WowBuddyDev.actionAvailSpellIDs.values()).index(116)
            profiles=json.loads((ROOT/'assets/rotations.json').read_text('utf8'))['rotations']
            profile=next(p for p in profiles if p['id']==1 and p['specId']==1482)
            clock=[10000]
            sent=[]
            def send(key,**kwargs):
                sent.append(key)
                return True
            sender=SimpleNamespace(send=send,status='测试投递',channel='fixture',
                backend=SimpleNamespace(now_ms=lambda:clock[0],Sleep=lambda ms:None))
            scheduler=Scheduler(pipeline,ActionDispatcher(sender),lambda:clock[0])
            def skill_tick(script,known,in_range,ready):
                lua.execute(script)
                tick()
                frame=captured_frame()
                self.assertEqual(frame.values['known_116'],known)
                self.assertEqual(frame.values['range_116'],in_range)
                self.assertEqual(g.PermesValues.ready_116,ready)
                # pipeline已将开发协议位图转换为原引擎保留bit0的格式。
                self.assertEqual(bool(int(frame.values['action_avail']) & (1 << (spell_index+1))),ready)
                # 使用实际完整冰霜练级方案；不为测试另造寒冰箭规则。
                clock[0]+=3000
                sent_before=len(sent)
                result=scheduler.process(pipeline.prepare_frame(frame,selected_profile=profile),
                                         hwnd=123,send_interval_ms=100)
                decision=result.decision
                actions=[candidate.action for candidate in decision.candidates]
                expected=(known=='ON' and in_range!='OFF' and ready and bool(g.targetAlive))
                self.assertEqual('spell_116' in actions,expected,
                                 (script,actions,dict(decision.fields)))
                if expected:
                    self.assertEqual(result.status,'sent')
                    self.assertEqual(result.selected.action,'spell_116')
                    self.assertEqual(sent[sent_before:],[result.selected.key])
                elif not g.targetAlive:
                    self.assertEqual(result.status,'sent')
                    self.assertEqual(result.selected.action,'auto_target')
                    self.assertEqual(sent[sent_before:],[parse_auto_target(g.PermesValues.ttd).key])
                else:
                    self.assertEqual(len(sent),sent_before,(script,result.status,actions))
            skill_tick('knownRank=nil','OFF','OFF',False)
            skill_tick('knownRank=116','ON','ON',True)
            skill_tick('rangeResult=false','ON','OFF',True)
            skill_tick('rangeResult=nil','ON','UNKNOWN',True)
            skill_tick('rangeResult=true; cooldown=3','ON','ON',False)
            skill_tick('cooldown=0; usable=false','ON','ON',False)
            skill_tick('usable=true','ON','ON',True)
            # 只学高等级别名时基础技能仍应被识别；射程必须询问已学等级。
            skill_tick('knownRank=205','ON','ON',True)
            self.assertEqual(g.rangeQueriedRank,205)
            skill_tick('targetAlive=false','ON','OFF',True)
            skill_tick('targetAlive=true; knownRank=nil','OFF','OFF',False)
        if class_name=='Priest':
            lua.execute('''partyHealth={party1=40,party2=10}; partyMissing={};partyDead={};partyHostile={};healthError={}
            focusUnit='party2'
            function UnitExists(unit)
              if unit=='focus' then return focusUnit~=nil end
              if unit=='party1' or unit=='party2' then return not partyMissing[unit] end
              return unit=='player' or unit=='target'
            end
            function UnitIsDeadOrGhost(unit) return (unit=='target' and not targetAlive) or partyDead[unit]==true end
            function UnitCanAssist(_,unit) return unit=='player' or (partyHealth[unit]~=nil and not partyHostile[unit]) end
            function UnitHealth(unit)
              if healthError[unit] then error('fixture health unavailable') end
              return partyHealth[unit] or 100
            end
            function UnitIsUnit(a,b) return a==b or (a=='focus' and b==focusUnit) end
            function IsSpellKnown(id) return id==2060 end
            C_Spell={IsSpellInRange=function() return true end}
            function WowBuddyDev.GetSpellCooldownRemaining() return 0 end
            function WowBuddyDev.IsSpellUsable() return true end''')
            profile=next(p for p in json.loads((ROOT/'assets/rotations.json').read_text('utf8'))['rotations'] if p['id']==20)
            clock=[10000]
            sent=[]
            sender=SimpleNamespace(send=lambda key,**kwargs:sent.append(key) or True,
                status='测试投递',channel='fixture',backend=SimpleNamespace(now_ms=lambda:clock[0],Sleep=lambda ms:None))
            scheduler=Scheduler(pipeline,ActionDispatcher(sender),lambda:clock[0])
            def healing_tick(script,health1,health2,friendly2,selected):
                lua.execute(script)
                tick()
                frame=captured_frame()
                self.assertEqual(frame.values['health_party1'],str(health1))
                self.assertEqual(frame.values['health_party2'],str(health2))
                self.assertEqual(frame.values['friendly_party2'],friendly2)
                self.assertEqual(frame.values['focus_index'],'2')
                clock[0]+=5000
                before=len(sent)
                result=scheduler.process(pipeline.prepare_frame(frame,selected_profile=profile),hwnd=123,send_interval_ms=100)
                if selected:
                    self.assertEqual(result.status,'sent')
                    self.assertEqual((result.selected.action,result.selected.pre_action),('spell_2060_focus','focus_'+selected))
                    expected=['CTRL-NUMPAD8'] if selected=='party2' else ['ALT-NUMPAD9','CTRL-NUMPAD8']
                    self.assertEqual(sent[before:],expected)
                else:
                    self.assertEqual(result.status,'no_candidates')
                    self.assertEqual(sent[before:],[])
            healing_tick('',40,10,'ON','party2')
            healing_tick('partyHealth.party1=5;partyHealth.party2=40',5,40,'ON','party1')
            healing_tick('partyMissing.party2=true',5,16777215,'OFF','party1')
            healing_tick('partyMissing.party2=nil;partyDead.party2=true',5,16777215,'OFF','party1')
            healing_tick('partyDead.party2=nil;partyHostile.party2=true',5,16777215,'OFF','party1')
            healing_tick('partyHostile.party2=nil;healthError.party2=true',5,16777215,'ON','party1')
            healing_tick('healthError.party1=true',16777215,16777215,'ON',None)
            healing_tick('healthError={};partyHealth.party1=40;partyHealth.party2=10',40,10,'ON','party2')
            # 色彩曲线接口返回真实插件构造的颜色；普通血量API设置独立探针。
            lua.execute('''curveMode='color';curveCalls=0;numericHealthCalls=0
            Enum={LuaCurveType={Step=1}}
            C_CurveUtil={CreateColorCurve=function()
              return {points={},SetType=function(self,kind) self.kind=kind end,
                AddPoint=function(self,x,color) self.points[#self.points+1]={x=x,color=color} end}
            end}
            function UnitHealthPercent(unit,useMax,curve)
              if not curve then return nil end
              curveCalls=curveCalls+1
              assert(useMax==true and curve.kind==1 and #curve.points==101)
              if curveMode=='error' and unit=='party2' then error('fixture color inaccessible') end
              if curveMode=='nil' and unit=='party2' then return nil end
              local pct=(partyHealth[unit] or 100)/100
              local selected
              for _,point in ipairs(curve.points) do
                if point.x<=pct then selected=point.color end
              end
              return selected
            end
            function UnitHealth(unit)
              numericHealthCalls=numericHealthCalls+1
              return partyHealth[unit] or 100
            end''')
            healing_tick('',40,10,'ON','party2')
            self.assertGreater(g.curveCalls,0)
            self.assertEqual(g.numericHealthCalls,0)
            healing_tick('partyHealth.party2=12.99',40,12,'ON','party2')
            self.assertEqual(g.numericHealthCalls,0)
            healing_tick("curveMode='error'",40,16777215,'ON','party1')
            self.assertEqual(g.numericHealthCalls,0)
            healing_tick("curveMode='nil'",40,12,'ON','party2')
            self.assertGreater(g.numericHealthCalls,0)
            healing_tick("curveMode='color';numericHealthCalls=0;partyHealth.party2=10",40,10,'ON','party2')
            self.assertEqual(g.numericHealthCalls,0)
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
