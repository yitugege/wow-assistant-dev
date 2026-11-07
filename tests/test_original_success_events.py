"""原Core成功事件回调的状态历史对照；持久化及职业副作用使用记录器。"""
import hashlib
from pathlib import Path
import sys
import unittest
from lupa.lua51 import LuaRuntime, lua_type

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
from wowbuddy.packages import read_addon


class OriginalSuccessEventsTests(unittest.TestCase):
    def test_deduplication_pet_alias_consumables_and_rollover(self):
        path=Path('D:/reverse-analysis/wow-assistant/unpacked/addon.bin')
        if not path.exists():self.skipTest('需要原addon.bin')
        data=path.read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(),'361134bc9f2dd0b2c8cd8849b3741bd88d09c55ec371de9abc7b6f79502ebbed')
        sources=[next(m.data.decode('utf-8-sig') for m in read_addon(data) if m.name=='Core.lua'),
                 (ROOT/'addon/WowBuddyDev/Core.lua').read_text('utf8')]
        runtimes=[]
        for source_index,source in enumerate(sources):
            lua=LuaRuntime(unpack_returned_tuples=True)
            lua.execute('''WowBuddyDev={};P07483180=WowBuddyDev;now=10;combat=false;calls={}
            function GetTime() return now end
            function InCombatLockdown() return combat end
            function CreateFrame() return {SetScript=function(self,k,fn) self[k]=fn end,
              RegisterUnitEvent=function(self,event,...) self.event=event end} end
            function recordPersistentCooldownStart(id) calls[#calls+1]={'persist',id} end
            function recordBurstPotionUse(id,cd,time) calls[#calls+1]={'consume',id,cd,time} end
            function WowBuddyDev.IsRaidFocusFeedbackEnabled() return true end
            function WowBuddyDev.RecordRaidFocusFeedback(kind)
              if feedbackFails then error('fixture feedback') end
              calls[#calls+1]={'feedback',kind}
            end
            WowBuddyDev.classData={cooldownEventAliases={[205]=116,[900]=901},
              petSpells={[901]=true},HEAL_FOCUS_SPELL_IDS={[116]=true},
              forceAvailableRules={[205]={setAvailable=116,clearAvailable=117}},
              OnSpellCast=function(id,item) calls[#calls+1]={'class',id,item} end}
            WowBuddyDev.consumableItems={{id='item_healing_stone',cooldown=120}}
            ''')
            state=source[source.index('local consumableCooldownStart = {}'):source.index('-- 功能：取玩家自己的 GUID')]
            namespace='P07483180' if source_index==0 else 'WowBuddyDev'
            start=source.index('function '+namespace+'.IsPetSpell(spellID)')
            helpers=source[start:source.index(namespace+'.COMMON_PIXEL_DATA = {',start)]
            start=source.index('local eventFrame = CreateFrame("Frame")')
            event=source[start:source.index('local healingStoneResetFrame',start)]
            lua.execute(state+helpers+event+'''
            consumableByItemSpell[1000]='item_healing_stone';consumableByItemSpell[1001]='trinketCD'
            function fire(unit,guid,id) eventFrame.OnEvent(eventFrame,'UNIT_SPELLCAST_SUCCEEDED',unit,guid,id) end
            function snapshot() return {generation=WowBuddyDev.playerSucceededGeneration,
              spell=WowBuddyDev.playerSucceededSpellID,last=WowBuddyDev.lastCastSpellID,
              times=lastCastTimeBySpell,consumables=consumableCooldownStart,trinket=trinketCooldownStart,
              blocked=healingStoneBlockedInCombat,forced=WowBuddyDev.forceAvailableState,calls=calls} end
            ''')
            runtimes.append(lua)
        def plain(v):return {k:plain(x) for k,x in v.items()} if lua_type(v)=='table' else v
        def step(time,unit,guid,spell,expected_generation):
            results=[]
            for lua in runtimes:
                lua.globals().now=time;lua.globals().fire(unit,guid,spell)
                results.append(plain(lua.globals().snapshot()))
            self.assertEqual(*results)
            self.assertEqual(results[0]['generation'],expected_generation)
            return results[0]
        first=step(10,'player','a',116,2)
        self.assertEqual(step(11,'player','a',205,2),first) # 同GUID即使技能不同仍去重。
        alias=step(12,'player','b',205,3)
        self.assertEqual(alias['times'][116],12)
        self.assertEqual(alias['forced'],{116:True,117:False})
        pet=step(13,'pet','pet',900,3)
        self.assertEqual(pet['times'][901],13)
        self.assertEqual(pet['calls'],alias['calls'])
        self.assertEqual(step(14,'target','ignored',116,3),pet)
        first=step(16,'player',None,116,4)
        self.assertEqual(step(16.049,'player',None,116,4),first)
        step(16.051,'player',None,116,5)
        for lua in runtimes:lua.globals().combat=True
        stone=step(17,'player','stone',1000,6)
        self.assertTrue(stone['blocked']);self.assertEqual(stone['consumables']['item_healing_stone'],17)
        self.assertEqual(step(18,'player','trinket',1001,7)['trinket'],18)
        for lua in runtimes:lua.globals().feedbackFails=True
        self.assertEqual(step(19,'player','feedback-error',116,8)['times'][116],19)
        generation=8
        for index in range(120):
            generation=generation%99+1
            step(20+index,'player','rollover-'+str(index),116,generation)


if __name__=='__main__':unittest.main()
