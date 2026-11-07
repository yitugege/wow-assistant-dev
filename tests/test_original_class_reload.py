"""实际九职业注册模块与原Core专精切换函数；持久化调用由记录器替代。"""
import hashlib
from pathlib import Path
import sys
import unittest
from lupa.lua51 import LuaRuntime

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
from wowbuddy.packages import read_addon


class OriginalClassReloadTests(unittest.TestCase):
    def test_switches_replace_registered_tables_and_clear_transient_state(self):
        path=Path('D:/reverse-analysis/wow-assistant/unpacked/addon.bin')
        if not path.exists():self.skipTest('需要原addon.bin')
        data=path.read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(),'361134bc9f2dd0b2c8cd8849b3741bd88d09c55ec371de9abc7b6f79502ebbed')
        original={m.name:m.data.decode('utf-8-sig') for m in read_addon(data) if m.name.endswith('.lua')}
        runtimes=[]
        for old in (True,False):
            lua=LuaRuntime(unpack_returned_tuples=True)
            lua.execute((ROOT/'tests/pixelbar_host.lua').read_text('utf8'))
            lua.execute('''P07483180=WowBuddyDev;WowBuddyDev.classes={};calls={};spec=1482;specIndex=1
            function GetSpecialization() return specIndex end
            function GetSpecializationInfo() return spec end
            function WowBuddyDev.RegisterClass(id,data) WowBuddyDev.classes[id]=data end
            function WowBuddyDev.RegisterPixelStripV2() end
            function applyTalentCooldownGates() calls[#calls+1]='talent' end
            function rebuildConsumableIndex() calls[#calls+1]='index' end
            function WowBuddyDev.RestorePersistentCooldowns() calls[#calls+1]='cooldowns' end
            function WowBuddyDev.RestorePersistentConsumableCooldowns() calls[#calls+1]='consumables' end
            function WowBuddyDev.RefreshStateLogo() calls[#calls+1]='logo' end''')
            def source(name):return original[name] if old else (ROOT/'addon/WowBuddyDev'/name).read_text('utf8')
            for name in ('ForeverTalentData.lua','ForeverClassSupport.lua'):
                lua.execute(source(name))
            for name in ('Mage','Druid','Hunter','Paladin','Priest','Rogue','Shaman','Warlock','Warrior'):
                lua.execute(source('classes/'+name+'/class_forever.lua'))
            core=source('Core.lua');start=core.index('reloadClassData = function()')
            lua.execute(core[start:core.index('local eventFrame = CreateFrame',start)])
            lua.execute('''
            fields={'testSpells','pixelData','ACTION_LABELS','ACTION_TO_KEY','testData','cooldowns',
              'persistentCooldowns','persistentChargeTrackers','actionAvailSpellIDs','extraValueRules','consumableItems'}
            function dirty()
              calls={};cooldownEndBySpell={old=1};consumableCooldownStart={old=1};consumableStateKnown=true
              trinketCooldownStart=1;lastTrinketCooldownDuration=2;WowBuddyDev.forceAvailableState={old=true}
              consumableByItemSpell={old=1};pendingItemDataIDs={old=1}
            end
            function verify(active)
              assert(next(cooldownEndBySpell)==nil and next(consumableCooldownStart)==nil)
              assert(consumableStateKnown==false and trinketCooldownStart==nil and lastTrinketCooldownDuration==nil)
              assert(next(WowBuddyDev.forceAvailableState)==nil and WowBuddyDev.isClassActive==active)
              for _,field in ipairs(fields) do
                local key=field=='extraValueRules' and 'extraValues' or field
                local expected=active and WowBuddyDev.classData[key] or nil
                if expected then assert(WowBuddyDev[field]==expected,field)
                else assert(next(WowBuddyDev[field])==nil,field) end
              end
              if not active then
                assert(WowBuddyDev.classData==nil and WowBuddyDev.trinketItemID==nil)
                assert(next(forceAvailableRules)==nil and next(consumableByItemSpell)==nil and next(pendingItemDataIDs)==nil)
              else assert(WowBuddyDev.classData==WowBuddyDev.classes[spec]) end
            end''')
            runtimes.append(lua)
        sequence=[1482,1487,1484,9999,1485,1486,1488,1489,1490,1491,1482,None,1487]
        for spec in sequence:
            with self.subTest(spec=spec):
                results=[]
                for lua in runtimes:
                    g=lua.globals();g.spec=spec;g.specIndex=0 if spec is None else 1
                    g.dirty();result=g.reloadClassData();active=spec not in (None,9999)
                    self.assertEqual(result,spec);g.verify(active)
                    calls=list(g.calls.values())
                    self.assertEqual(calls[-4:] if active else calls,
                                     ['index','cooldowns','consumables','logo'] if active else [])
                    results.append(calls)
                self.assertEqual(*results)


if __name__=='__main__':unittest.main()
