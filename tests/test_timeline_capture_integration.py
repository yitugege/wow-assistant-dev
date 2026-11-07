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

    def test_unknown_schema_is_preserved_without_capture(self):
        lua=self.fixture(full_load.SOURCE);g=lua.globals();addon=g.WowBuddyDev
        lua.execute('WowBuddyDev.DB.timelinePlannerCapture={schemaVersion=99,marker="keep"}')
        addon.SetTimelinePlannerArmed(True)
        g.EmitFixtureEvent('ENCOUNTER_START',9999,'fixture',1)
        g.EmitFixtureEvent('ENCOUNTER_TIMELINE_EVENT_REMOVED',1)
        g.EmitFixtureEvent('ENCOUNTER_END',9999,'fixture',1)
        self.assertEqual(plain(addon.DB.timelinePlannerCapture),{'schemaVersion':99,'marker':'keep'})


if __name__=='__main__':unittest.main()
