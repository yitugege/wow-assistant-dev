"""时间轴采集事件生命周期及存档上限；不模拟真实首领机制。"""
import hashlib
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
import unittest
from lupa.lua51 import lua_type
from tests import test_addon_full_load as full_load

ROOT=full_load.ROOT
sys.path.insert(0,str(ROOT/'desktop'))
from wowbuddy.packages import read_addon


def plain(value):
    if lua_type(value)=='table':return {k:plain(v) for k,v in value.items()}
    return value


class TimelineCaptureIntegrationTests(unittest.TestCase):
    def surface_history(self,source):
        lua=self.fixture(source);g=lua.globals()
        lua.execute('''timelineStates={};timelineRemaining={}
          C_EncounterTimeline={GetEventState=function(id) return timelineStates[id] end,
            GetEventTimeRemaining=function(id) return timelineRemaining[id] end}
        ''')
        g.EmitFixtureEvent('ENCOUNTER_START',3379,'fixture',15)
        def rgb(texture):
            return sum(round(texture.color[i]*255) << shift for i,shift in ((1,16),(2,8),(3,0)))
        markers=[t for t in g.textures.values() if t.color and rgb(t)==3260648]
        self.assertEqual(len(markers),1)
        g.fixtureAlertParent=markers[0].parent
        cells=lua.eval('''function() local out={}
          for _,t in ipairs(textures) do if t.parent==fixtureAlertParent then out[#out+1]=t end end
          table.sort(out,function(a,b) return a.point[5]>b.point[5] end)
          return out end''')()
        self.assertEqual(len(cells),8)
        traces=[]
        def snapshot(event_id,mechanic,state,remaining):
            words=[rgb(cells[i]) for i in range(1,9)]
            self.assertEqual(words[0],3260648)
            self.assertEqual(words[1],words[7])
            self.assertEqual(words[1]%2,0)
            self.assertEqual(words[2:7],[337915,1,event_id,mechanic,state*8192+remaining+1])
            traces.append(words)
            return words
        snapshot(0,0,5,0)
        # 同一44秒机制的四次事件必须按原轮转1、6、4、1识别，次数按机制累计。
        for eid,code,occurrence in ((11,1,1),(12,6,1),(13,4,1),(14,1,2)):
            g.now+=1
            g.timelineStates[eid]=0;g.timelineRemaining[eid]=44
            payload=lua.table_from({'id':eid,'source':0,'duration':44})
            g.EmitFixtureEvent('ENCOUNTER_TIMELINE_EVENT_ADDED',payload)
            before=snapshot(eid,code*65536+4096+occurrence,0,440)
            # 同ID重复添加不可推进轮转，也不可产生新发布序列。
            g.EmitFixtureEvent('ENCOUNTER_TIMELINE_EVENT_ADDED',payload)
            self.assertEqual([rgb(cells[i]) for i in range(1,9)],before)
        # 不足150毫秒的新事件先排队；运行真实OnUpdate后按流逝时间投影剩余值。
        g.now+=.05;g.timelineStates[15]=0;g.timelineRemaining[15]=18
        g.EmitFixtureEvent('ENCOUNTER_TIMELINE_EVENT_ADDED',
                          lua.table_from({'id':15,'source':0,'duration':18}))
        self.assertEqual([rgb(cells[i]) for i in range(1,9)],before)
        def tick():
            lua.execute('''for _,frame in ipairs(frames) do
              if frame.events and frame.events.ENCOUNTER_TIMELINE_EVENT_ADDED
                 and frame.scripts.OnUpdate then frame.scripts.OnUpdate(frame,.05) end
            end''')
        g.now+=.05;tick()
        self.assertEqual([rgb(cells[i]) for i in range(1,9)],before)
        g.now+=.2;tick()
        snapshot(15,2*65536+4096+1,0,178)
        g.now+=1;g.timelineStates[14]=2
        g.EmitFixtureEvent('ENCOUNTER_TIMELINE_EVENT_STATE_CHANGED',14)
        snapshot(14,65536+4096+2,2,0)
        g.now+=1
        g.EmitFixtureEvent('ENCOUNTER_TIMELINE_EVENT_REMOVED',14)
        # 原实现不为已暂停的事件发布移除帧；保留上次暂停画面。
        snapshot(14,65536+4096+2,2,0)
        g.now+=1
        g.EmitFixtureEvent('ENCOUNTER_TIMELINE_EVENT_REMOVED',13)
        snapshot(13,4*65536+4096+1,4,0)
        g.EmitFixtureEvent('ENCOUNTER_END',3379,'fixture',15)
        self.assertFalse(g.fixtureAlertParent.shown)
        return traces,plain(g.WowBuddyDev.DB.timelinePlannerCapture)

    def test_real_timeline_events_publish_eight_cell_alerts(self):
        self.surface_history(full_load.SOURCE)

    def fixture(self,source):
        prelude='\n'.join((ROOT/'tests'/name).read_text('utf8') for name in
                          ('addon_login_host.lua','addon_world_host.lua'))
        prelude+='\nfunction issecretvalue() return false end'
        lua,_=full_load.AddonFullLoadTests().load(source,'WowBuddyDev',prelude)
        g=lua.globals()
        g.EmitFixtureEvent('ADDON_LOADED','WowBuddyDev')
        g.EmitFixtureEvent('PLAYER_LOGIN')
        g.EmitFixtureEvent('PLAYER_ENTERING_WORLD',True,False)
        return lua

    def exercise(self,source):
        lua=self.fixture(source);g=lua.globals();addon=g.WowBuddyDev
        keys=sorted(addon.TimelinePlannerEncounters.keys())
        self.assertEqual(len(keys),41)
        traces=[]
        for index,key in enumerate(keys,1):
            g.EmitFixtureEvent('ENCOUNTER_START',key//100,'fixture',key%100)
            capture=addon.DB.timelinePlannerCapture
            run=capture.runs[len(capture.runs)]
            self.assertEqual(run.encounterId,key//100)
            self.assertEqual(run.difficultyId,key%100)
            self.assertFalse(run.observationOnly)
            self.assertIsNone(run.endReason)
            self.assertIsNone(run.captureFailed)
            g.EmitFixtureEvent('ENCOUNTER_END',key//100,'fixture',key%100)
            self.assertEqual(run.endReason,'encounter_end')
            self.assertEqual(len(capture.runs),min(index,3))
            self.assertEqual(capture.droppedRuns,max(0,index-3))
            traces.append(plain(run))
        # 未手动武装时，不在目录的首领不得开启新记录。
        before=capture.nextRunId
        g.EmitFixtureEvent('ENCOUNTER_START',9999,'fixture',1)
        self.assertEqual(capture.nextRunId,before)
        self.assertTrue(addon.SetTimelinePlannerArmed(True))
        g.EmitFixtureEvent('ENCOUNTER_START',9999,'fixture',1)
        run=capture.runs[len(capture.runs)]
        self.assertTrue(run.observationOnly)
        for i in range(1030):
            g.EmitFixtureEvent('ENCOUNTER_TIMELINE_EVENT_REMOVED',i+1)
        self.assertEqual(run.eventsSeen,1030)
        self.assertEqual(run.eventsDropped,6)
        self.assertEqual(len(run.events),1024)
        self.assertEqual(run.events[1].eventId,1)
        self.assertEqual(run.events[1024].eventId,1024)
        self.assertFalse(addon.SetTimelinePlannerArmed(False))
        self.assertEqual(run.endReason,'disarmed')
        g.EmitFixtureEvent('ENCOUNTER_TIMELINE_EVENT_REMOVED',2000)
        self.assertEqual(run.eventsSeen,1030)
        before=capture.nextRunId
        key=keys[0]
        g.EmitFixtureEvent('ENCOUNTER_START',key//100,'fixture',key%100)
        self.assertEqual(capture.nextRunId,before)
        traces.append(plain(capture))
        return traces

    def test_all_catalog_lifecycles_and_capture_limits(self):
        self.exercise(full_load.SOURCE)

    def test_original_planner_capture_matches_independent(self):
        package=Path('D:/reverse-analysis/wow-assistant/unpacked/addon.bin')
        if not package.is_file():self.skipTest('需要原addon.bin')
        payload=package.read_bytes()
        self.assertEqual(hashlib.sha256(payload).hexdigest(),
                         '361134bc9f2dd0b2c8cd8849b3741bd88d09c55ec371de9abc7b6f79502ebbed')
        original={m.name:m.data for m in read_addon(payload)}['TimelinePlanner.lua']
        with TemporaryDirectory() as folder:
            source=Path(folder)/'WowBuddyDev'
            shutil.copytree(full_load.SOURCE,source)
            (source/'TimelinePlanner.lua').write_text('P07483180=WowBuddyDev\n'+original.decode('utf-8-sig'),encoding='utf8')
            self.assertEqual(self.exercise(source),self.exercise(full_load.SOURCE))
            self.assertEqual(self.surface_history(source),self.surface_history(full_load.SOURCE))

    def test_unknown_schema_is_preserved_without_capture(self):
        lua=self.fixture(full_load.SOURCE);g=lua.globals();addon=g.WowBuddyDev
        lua.execute('WowBuddyDev.DB.timelinePlannerCapture={schemaVersion=99,marker="keep"}')
        addon.SetTimelinePlannerArmed(True)
        g.EmitFixtureEvent('ENCOUNTER_START',9999,'fixture',1)
        g.EmitFixtureEvent('ENCOUNTER_TIMELINE_EVENT_REMOVED',1)
        g.EmitFixtureEvent('ENCOUNTER_END',9999,'fixture',1)
        self.assertEqual(plain(addon.DB.timelinePlannerCapture),{'schemaVersion':99,'marker':'keep'})


if __name__=='__main__':unittest.main()
