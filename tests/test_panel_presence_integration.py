"""完整插件初始化后的面板周期刷新；对照原PanelV2，游戏API为替身。"""
import hashlib
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
import unittest

from tests import test_addon_full_load as full_load

ROOT = full_load.ROOT
sys.path.insert(0, str(ROOT/'desktop'))
from wowbuddy.packages import read_addon

PROBE = '''
function findPanelUpvalue(fn,wanted,seen)
  seen=seen or {};if seen[fn] then return end;seen[fn]=true
  for i=1,100 do
    local name,value=debug.getupvalue(fn,i);if not name then break end
    if name==wanted then return value end
    if type(value)=='function' then
      local found=findPanelUpvalue(value,wanted,seen);if found then return found end
    end
  end
end
function isPanelDriver(callback)
  for i=1,100 do
    local name=debug.getupvalue(callback,i)
    if not name then return false end
    if name=='presenceTicks' then return true end
  end
  return false
end
for _,frame in ipairs(frames) do
  local callback=frame.scripts.OnUpdate
  if callback and debug.getinfo(callback,'S').source=='@PanelV2.lua' and isPanelDriver(callback) then
    local rows=findPanelUpvalue(callback,'presenceRows')
    if rows then
      assert(not fixturePanelDriver,'面板主驱动应唯一')
      fixturePanelDriver=callback;fixturePanelFrame=frame;fixturePresenceRows=rows
    end
  end
end
assert(fixturePanelDriver)
auraMode='present'
C_UnitAuras={
  GetPlayerAuraBySpellID=function(id)
    if auraMode=='unknown' then error('fixture restricted') end
    if auraMode=='present' then return {spellId=id} end
  end,
  GetAuraDataBySpellID=function(id,filter,unit)
    assert(unit=='target' or unit=='player')
    if auraMode=='unknown' then error('fixture restricted') end
    if auraMode=='present' then return {spellId=id} end
  end,
  GetAuraDataByIndex=function()
    if auraMode=='unknown' then error('fixture restricted') end
    return nil
  end
}
function refreshPanelFixture(seconds)
  now=now+seconds
  -- 五次50毫秒主回调触发一次presence刷新；先前跳过时间不补跑。
  for i=1,5 do fixturePanelDriver(fixturePanelFrame,.05) end
end
'''


class PanelPresenceIntegrationTests(unittest.TestCase):
    def fixture(self, source, token, cid, spec):
        prelude=f"fixtureClass='{token}';fixtureClassID={cid};fixtureSpecID={spec}\n"
        prelude+='\n'.join((ROOT/'tests'/name).read_text('utf8')
                          for name in ('addon_login_host.lua','addon_world_host.lua'))
        lua,_=full_load.AddonFullLoadTests().load(source,'WowBuddyDev',prelude)
        g=lua.globals()
        g.EmitFixtureEvent('ADDON_LOADED','WowBuddyDev')
        g.EmitFixtureEvent('PLAYER_LOGIN')
        g.EmitFixtureEvent('PLAYER_ENTERING_WORLD',True,False)
        g.AdvanceFixtureTime(15)
        lua.execute(PROBE)
        return lua

    def exercise(self, source, token, cid, spec):
        lua=self.fixture(source,token,cid,spec);g=lua.globals()
        rows=[row for row in g.fixturePresenceRows.values() if row.luaDriven]
        self.assertTrue(rows)
        snapshots=[]
        def refresh(seconds, expected):
            g.refreshPanelFixture(seconds)
            snapshot=[]
            for row in rows:
                color=tuple(row.row.dimTex.color[i] for i in range(1,5))
                green=color==(0,1,0,1)
                self.assertEqual(green,expected(row) and bool(g.UnitExists(row.unit)),row.key)
                snapshot.append((row.key,color,row.green,row.staleOut))
            snapshots.append(snapshot)
        refresh(.25,lambda row:True)
        g.auraMode='unknown'
        refresh(2,lambda row:True)
        refresh(1,lambda row:True)
        refresh(.25,lambda row:False)
        g.auraMode='present'
        refresh(.25,lambda row:True)
        g.combat=True;g.auraMode='unknown'
        refresh(.25,lambda row:True)
        refresh(20,lambda row:True)
        refresh(.25,lambda row:not row.key.startswith('seal_'))
        g.auraMode='absent'
        refresh(.25,lambda row:False)
        g.auraMode='present';g.combat=False
        refresh(.25,lambda row:True)
        self.assertEqual(len(g.WowBuddyDev.errorLogs),0)
        return snapshots

    def test_nine_classes_present_absent_unknown_and_recovery(self):
        for token,cid,spec,_ in full_load.AddonFullLoadTests.CLASS_CASES:
            with self.subTest(class_name=token):
                self.exercise(full_load.SOURCE,token,cid,spec)

    def test_original_panel_matches_druid_and_paladin_history(self):
        path=Path('D:/reverse-analysis/wow-assistant/unpacked/addon.bin')
        if not path.is_file():self.skipTest('需要原addon.bin')
        payload=path.read_bytes()
        self.assertEqual(hashlib.sha256(payload).hexdigest(),
                         '361134bc9f2dd0b2c8cd8849b3741bd88d09c55ec371de9abc7b6f79502ebbed')
        original={m.name:m.data for m in read_addon(payload)}['PanelV2.lua']
        with TemporaryDirectory() as folder:
            source=Path(folder)/'WowBuddyDev'
            shutil.copytree(full_load.SOURCE,source)
            # 仅增加旧全局名称别名，原PanelV2正文原样执行；其余依赖保持同一宿主。
            (source/'PanelV2.lua').write_text('P07483180=WowBuddyDev\n'+original.decode('utf-8-sig'),encoding='utf8')
            for token,cid,spec in (('DRUID',11,1484),('PALADIN',2,1486)):
                with self.subTest(class_name=token):
                    self.assertEqual(self.exercise(source,token,cid,spec),
                                     self.exercise(full_load.SOURCE,token,cid,spec))


if __name__=='__main__':unittest.main()
