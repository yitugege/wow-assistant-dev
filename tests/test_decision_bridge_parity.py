"""原包与独立DecisionBridge的实际周期回调对照，不执行施法。"""
import hashlib
from pathlib import Path
import sys
import unittest

from lupa.lua51 import LuaRuntime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'desktop'))
from wowbuddy.packages import read_addon


HOST = '''
now=10; combat=false; ready={}; present={}; auraQueries={}; readinessQueries={}
function GetTime() return now end
function UnitAffectingCombat(unit) assert(unit=='player'); return combat end
function print() end
function CreateFrame()
  return {SetScript=function(self,event,callback) self[event]=callback end}
end
C_UnitAuras={GetPlayerAuraBySpellID=function(id)
  table.insert(auraQueries,id)
  if auraFails then error('fixture aura unavailable') end
  return present[id] and {} or nil
end}
fixtureAddon={classData={actionAvailSpellIDs={467,116,2136},
  ACTION_TO_KEY={spell_467='F1',spell_116='F2',spell_2136='F3',start_attack='F4'},
  DEFAULT_MACROS={spell_467='/cast [@player] Thorns',spell_116='/cast [harm] Frostbolt',
                 spell_2136='/startattack'}},
  _pixelStripV2BySpec={ [1484]={{kind='presence',unit='player',filter='HELPFUL',spellIDs={467,782}}}},
  IsSpellReady=function(id)
    table.insert(readinessQueries,id)
    if readinessFails then error('fixture readiness unavailable') end
    return ready[id] or false
  end}
P07483180=fixtureAddon; WowBuddyDev=fixtureAddon
function step(delta)
  now=now+delta
  fixtureAddon.DecisionBridge.frame:OnUpdate(delta)
  return DECISION_BRIDGE
end
'''


class DecisionBridgeParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        package = Path('D:/reverse-analysis/wow-assistant/unpacked/addon.bin')
        if not package.is_file():
            raise unittest.SkipTest('需要原addon.bin')
        payload = package.read_bytes()
        if hashlib.sha256(payload).hexdigest() != '361134bc9f2dd0b2c8cd8849b3741bd88d09c55ec371de9abc7b6f79502ebbed':
            raise AssertionError('原包身份不符')
        cls.original = {m.name: m.data for m in read_addon(payload)}['DecisionBridge.lua'].decode('utf-8-sig')

    def pair(self):
        result = []
        for source in (self.original, (ROOT/'addon/WowBuddyDev/DecisionBridge.lua').read_text('utf-8-sig')):
            lua = LuaRuntime(unpack_returned_tuples=True, register_eval=False, register_builtins=False)
            lua.execute(HOST)
            lua.execute(source)
            result.append(lua)
        return result

    def trace(self, commands):
        traces = []
        for lua in self.pair():
            rows = []
            for command in commands:
                rows.append(lua.execute(command))
            traces.append(rows)
        self.assertEqual(traces[0], traces[1])
        return traces[1]

    def test_priority_self_buff_and_same_key_throttle(self):
        rows = self.trace([
            'ready[467]=true;ready[116]=true;ready[2136]=true;return step(.1)',
            'return step(.1)',
            'combat=true;return step(.1)',
            'present[782]=true;return step(.1)',
            'return step(.5)',
            'ready[116]=false;return step(.1)',
            'ready[2136]=false;return step(.1)',
        ])
        expected = [('116','attack'),('116','throttle'),('467','other'),
                    ('116','attack'),('116','attack'),('2136','attack'),('0','idle')]
        for row, (spell, stage) in zip(rows, expected):
            self.assertIn(',spell='+spell+',stage='+stage, row)

    def test_disabled_and_swallowed_error_leave_old_bridge_value(self):
        rows = self.trace([
            'ready[116]=true;return step(.1)',
            'fixtureAddon.DecisionBridge.enabled=false;return step(1)',
            'fixtureAddon.DecisionBridge.enabled=true;readinessFails=true;return step(1)',
            'readinessFails=false;ready[116]=false;return step(1)',
            'fixtureAddon.classData=nil;return step(1)',
        ])
        self.assertEqual(rows[0], rows[1])
        self.assertEqual(rows[0], rows[2])
        self.assertTrue(rows[3].endswith('stage=idle'))
        self.assertTrue(rows[4].endswith('stage=no-classdata'))

    def test_unknown_buff_fallback_key_and_missing_key(self):
        rows = self.trace([
            'combat=true;ready[467]=true;auraFails=true;return step(.1)',
            'C_UnitAuras=nil;return step(.5)',
            'fixtureAddon.classData.ACTION_TO_KEY.spell_467=nil;return step(.1)',
            'fixtureAddon.classData.ACTION_TO_KEY=nil;return step(.5)',
        ])
        for row in rows:
            self.assertTrue(row.endswith('spell=467,stage=other'))
        self.assertIn(',key=F4,', rows[2])
        self.assertIn(',key=,', rows[3])

    def test_interval_accumulation_and_empty_buff_snapshot_not_rebuilt(self):
        rows = self.trace([
            'fixtureAddon._pixelStripV2BySpec=nil;ready[467]=true;return step(.04)',
            'return step(.04)',
            'return step(.04)',
            "fixtureAddon._pixelStripV2BySpec={[1484]={{kind='presence',unit='player',filter='HELPFUL',spellIDs={467}}}};present[467]=true;return step(.5)",
        ])
        self.assertIsNone(rows[0])
        self.assertIsNone(rows[1])
        for row in rows[2:]:
            self.assertTrue(row.endswith('spell=467,stage=other'))

    def test_bridge_does_not_apply_master_switch_or_target_gate(self):
        rows = self.trace([
            '''fixtureAddon.DB={masterSwitch=false};ready[116]=true
            function UnitExists() return false end
            function UnitIsDeadOrGhost() return true end
            return step(.1)''',
            'fixtureAddon.DB.masterSwitch=true;return step(.5)',
        ])
        for row in rows:
            self.assertIn(',combat=0,key=F2,spell=116,stage=attack', row)


if __name__ == '__main__':
    unittest.main()
