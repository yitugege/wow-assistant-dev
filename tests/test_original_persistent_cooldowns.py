"""直接执行原包与独立Core的持久化函数，比较存档和运行时状态。"""
import hashlib
from pathlib import Path
import sys
import unittest
from lupa.lua51 import LuaRuntime, lua_type

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'desktop'))
from wowbuddy.packages import read_addon


class PersistentCooldownParityTests(unittest.TestCase):
    def test_ledger_reload_clock_roles_charges_and_reset(self):
        original = Path('D:/reverse-analysis/wow-assistant/unpacked/addon.bin')
        if not original.exists():
            self.skipTest('需要原addon.bin')
        data = original.read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(),
                         '361134bc9f2dd0b2c8cd8849b3741bd88d09c55ec371de9abc7b6f79502ebbed')
        sources = [next(m.data.decode('utf-8-sig') for m in read_addon(data) if m.name == 'Core.lua'),
                   (ROOT / 'addon/WowBuddyDev/Core.lua').read_text('utf8')]
        runtimes = []
        for index, source in enumerate(sources):
            lua = LuaRuntime(unpack_returned_tuples=True)
            lua.execute('''
              WowBuddyDev={DB={},cooldowns={[116]=60,[117]=120},
                persistentCooldowns={[116]={resetOnGameCooldownReset=true},[117]={}},
                persistentChargeTrackers={blink={maxCharges=2,rechargeSeconds=30,
                  lockoutSeconds=5,resetOnGameCooldownReset=true}},
                consumableItems={{id='item_burst_potion',cooldown=300}}}
              P07483180=WowBuddyDev
              now=100;server=1000;guid='A';instanceType='raid';inInstance=true
              function GetTime() return now end
              function GetServerTime() return server end
              function UnitGUID(unit) assert(unit=='player');return guid end
              function IsInInstance() return inInstance,instanceType end
              function WowBuddyDev.InitDB() WowBuddyDev.DB={} end
              function InCombatLockdown() return false end
              function CreateFrame() return {SetScript=function(self,key,fn) self[key]=fn end,
                RegisterUnitEvent=function() end} end
              WowBuddyDev.classData={cooldownEventAliases={[205]=116,[900]=901},
                petSpells={[901]=true}}
            ''')
            namespace = 'P07483180' if index == 0 else 'WowBuddyDev'
            section = source[source.index('local consumableCooldownStart = {}'):
                             source.index('function '+namespace+'.IsPetSpell(spellID)')]
            helper_start = source.index('function '+namespace+'.IsPetSpell(spellID)')
            helpers = source[helper_start:source.index(namespace+'.COMMON_PIXEL_DATA = {', helper_start)]
            event_start = source.index('local eventFrame = CreateFrame("Frame")')
            event = source[event_start:source.index('local healingStoneResetFrame', event_start)]
            query_start = source.index('function '+namespace+'.GetSpellCooldownRemaining(spellID)')
            query = source[query_start:source.index(namespace+'.lastCastTime = lastCastTimeBySpell', query_start)]
            lua.execute(section + helpers + event + query + '''
              probe={ledger=getPersistentLedger,remaining=ledgerEntryRemaining,
                record=recordPersistentCooldownStart,apply=applyLedgerEntryToRuntime,
                potion=recordBurstPotionUse,clearPotion=clearBurstPotionRuntime,
                resetEvent=shouldResetCooldownsOnEvent}
              function snapshot() return {db=WowBuddyDev.DB,starts=lastCastTimeBySpell,
                ends=cooldownEndBySpell,items=consumableCooldownStart,known=consumableStateKnown} end
              function wipeRuntime() lastCastTimeBySpell={};cooldownEndBySpell={};
                consumableCooldownStart={};consumableStateKnown=false end
              consumableByItemSpell[1000]='item_burst_potion'
              function fire(unit,castGuid,id)
                eventFrame.OnEvent(eventFrame,'UNIT_SPELLCAST_SUCCEEDED',unit,castGuid,id)
              end
            ''')
            runtimes.append(lua)

        def plain(value):
            if lua_type(value) == 'table':
                return {k: plain(v) for k, v in value.items()}
            if isinstance(value, tuple):
                return tuple(plain(v) for v in value)
            return value

        def step(code):
            results = []
            for lua in runtimes:
                result = plain(lua.execute(code))
                results.append((result, plain(lua.globals().snapshot())))
            self.assertEqual(results[0], results[1], code)
            return results[0][0], results[0][1]

        self.assertEqual(step('return probe.ledger(false)')[1]['db'], {})
        self.assertIsNone(step("guid='';return probe.ledger(true)")[0])
        step("guid='A';probe.record(116);probe.record(117)")
        result, state = step('now=110;server=1010;wipeRuntime();WowBuddyDev.RestorePersistentCooldowns()')
        self.assertEqual(state['starts'], {116: 100, 117: 100})
        self.assertEqual(state['ends'], {116: 160, 117: 220})
        # 会话重新起算，回退服务器绝对时间；已记录时长优先于新配置。
        _, state = step('now=5;server=1020;WowBuddyDev.cooldowns[116]=10;wipeRuntime();WowBuddyDev.RestorePersistentCooldowns()')
        self.assertEqual(state['starts'][116], -15)
        self.assertEqual(state['ends'][116], 45)
        self.assertEqual(step("guid='B';wipeRuntime();WowBuddyDev.RestorePersistentCooldowns()")[1]['ends'], {})
        step('probe.record(116)')
        self.assertEqual(step("guid='A';return probe.ledger(false)[116].duration")[0], 60)
        _, state = step('now=45;server=1060;WowBuddyDev.RestorePersistentCooldowns()')
        self.assertNotIn(116, state['db']['persistentCooldownLedger']['A'])
        self.assertEqual(state['ends'], {117: 105})
        # 容差包含3秒端点；超界时用serverExpiresAt。
        for session, expected in [(110, 50), (113, 47), (113.001, 90), (90, 90)]:
            value, _ = step('return probe.remaining({serverRecordedAt=1000,serverExpiresAt=1100,'
                            'sessionRecordedAt=100,sessionExpiresAt=160},1010,'+str(session)+')')
            self.assertAlmostEqual(value, expected)
        self.assertEqual(step("return probe.remaining('1100',1010,1)")[0], 90)
        self.assertIsNone(step('return probe.remaining({},1010,1)')[0])
        # 旧数字格式、无效条目和上限裁剪均走真实恢复函数。
        step('probe.ledger(true)[116]=2000;WowBuddyDev.cooldowns[116]=60')
        self.assertEqual(step('return probe.apply(116)')[0], (True, 60))
        step('probe.ledger(true)[116]={duration=60}')
        self.assertEqual(step('return probe.apply(116)')[0], (False, 0))
        step("now=100;server=2000;probe.potion('item_burst_potion',300,100)")
        _, state = step('now=120;server=2020;wipeRuntime();WowBuddyDev.RestorePersistentConsumableCooldowns()')
        self.assertEqual(state['items'], {'item_burst_potion': 100})
        _, state = step('now=400;server=2300;WowBuddyDev.RestorePersistentConsumableCooldowns()')
        self.assertEqual(state['items'], {})
        self.assertTrue(state['known'])
        self.assertEqual(step("return WowBuddyDev.GetPersistentChargeCount('blink')")[0], 2)
        self.assertEqual(step("return WowBuddyDev.RecordPersistentChargeSuccess('blink')")[0], (True, 1))
        self.assertEqual(step("return WowBuddyDev.GetPersistentChargeCount('blink')")[0], 0)
        # 原记录入口没有拒绝锁定期成功事件；保持这一实际行为。
        self.assertEqual(step("return WowBuddyDev.RecordPersistentChargeSuccess('blink')")[0], (True, 0))
        self.assertEqual(step("return WowBuddyDev.RecordPersistentChargeSuccess('blink')")[0], (False, 0))
        for elapsed, charges in [(5, 0), (30, 1), (59.999, 1), (60, 2)]:
            value, _ = step(f"now={400+elapsed};server={2300+elapsed};return WowBuddyDev.GetPersistentChargeCount('blink')")
            self.assertEqual(value, charges)
        _, state = step("probe.record(116);probe.record(117);WowBuddyDev.RecordPersistentChargeSuccess('blink');"
                        "probe.potion('item_burst_potion',300,now);WowBuddyDev.ClearPersistentCooldownsForGameReset()")
        self.assertEqual(set(state['db']['persistentCooldownLedger']['A']), {117})
        self.assertIn('B', state['db']['persistentCooldownLedger'])
        self.assertEqual(step("return probe.resetEvent('CHALLENGE_MODE_START')")[0], True)
        self.assertEqual(step("return probe.resetEvent('ENCOUNTER_END')")[0], True)
        self.assertEqual(step("instanceType='party';return probe.resetEvent('ENCOUNTER_END')")[0], False)
        self.assertEqual(step("return probe.resetEvent('PLAYER_ENTERING_WORLD')")[0], False)
        # 真正的成功回调 -> 真实账本函数 -> 重载恢复 -> 真实剩余时间查询。
        step("now=500;server=3000;guid='A';WowBuddyDev.DB={};wipeRuntime();fire('player','cast-1',205)")
        value, state = step('now=510.25;server=3010;return WowBuddyDev.GetSpellCooldownRemaining(116)')
        self.assertEqual(value, 49.75)
        self.assertEqual(state['db']['persistentCooldownLedger']['A'][116]['duration'], 60)
        duplicate = step("fire('player','cast-1',205)")[1]
        self.assertEqual(duplicate, state)
        _, state = step("fire('pet','pet-1',900)")
        self.assertEqual(state['starts'][901], 510.25)
        self.assertNotIn(901, state['db']['persistentCooldownLedger']['A'])
        _, state = step("fire('player','potion-1',1000)")
        self.assertEqual(state['db']['persistentCooldownLedger']['A']
                         ['consumable:item_burst_potion']['sessionRecordedAt'], 510.25)
        value, state = step('now=5;server=3020;wipeRuntime();WowBuddyDev.RestorePersistentCooldowns();'
                            'WowBuddyDev.RestorePersistentConsumableCooldowns();'
                            'return WowBuddyDev.GetSpellCooldownRemaining(116)')
        self.assertEqual(value, 40)
        self.assertEqual(state['items']['item_burst_potion'], -5)
        value, state = step('now=45;server=3060;return WowBuddyDev.GetSpellCooldownRemaining(116)')
        self.assertEqual(value, 0)
        self.assertNotIn(116, state['db']['persistentCooldownLedger']['A'])
        self.assertNotIn(116, state['starts'])


if __name__ == '__main__':
    unittest.main()
