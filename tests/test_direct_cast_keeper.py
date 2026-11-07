"""续挂调度对照原完整模块；游戏接口均为记录替身。"""
import unittest
from tests import test_direct_cast_actions as actions
from tests import test_original_direct_cast as original
from tests import test_direct_cast_integration as integration


class DirectCastKeeperTests(unittest.TestCase):
    def hosts(self):
        a,b=actions.DirectCastActionsTests().hosts()
        b.execute('P07483180=WowBuddyDev;tickers={};C_Timer={NewTicker=function(period,fn) table.insert(tickers,{period=period,fn=fn}) end}')
        for lua in (a,b):
            host=original.OriginalDirectCastTests();host.lua=lua;host.install_aura_host()
            lua.execute('now=10;function GetTime() return now end')
        b.execute((actions.ROOT/'addon/WowBuddyDev/DirectCastKeeper.lua').read_text('utf8'))
        self.assertEqual(len(b.globals().tickers),1)
        self.assertEqual(b.globals().tickers[1].period,1)
        return a,b

    def tick(self,a,b):
        a.globals().tickers[1].fn();b.globals().tickers[1].fn()
        self.assertEqual(list(b.globals().calls.values()),list(a.globals().calls.values()))

    def test_aura_states_and_retry_boundary(self):
        for mode in ('id','name','error','full','absent'):
            with self.subTest(mode=mode):
                a,b=self.hosts()
                for lua in (a,b):lua.globals().auraMode=mode
                for now in (10,14.999,15):
                    for lua in (a,b):lua.globals().now=now
                    self.tick(a,b)
                self.assertEqual(list(b.globals().calls.values()),
                                 ['use:1:player']*2 if mode=='absent' else [])

    def test_dead_cast_channel_cooldown_off_and_unknown_name(self):
        for flag in ('dead','casting','channel','cooldown','off','unknown'):
            with self.subTest(flag=flag):
                a,b=self.hosts()
                for lua in (a,b):
                    g=lua.globals()
                    if flag=='cooldown':g.cdStart=9;g.cdDuration=2
                    elif flag=='off':g.SlashCmdList.DIRECTCAST('off')
                    elif flag=='unknown':g.nameKnown=False
                    else:setattr(g,flag,True)
                self.tick(a,b)
                self.assertEqual(list(b.globals().calls.values()),[])

    def test_both_api_failures_still_delay_retry_and_false_return_suppresses_fallback(self):
        for mode in ('error','false'):
            with self.subTest(mode=mode):
                a,b=self.hosts()
                for lua in (a,b):lua.globals().useMode=mode;lua.globals().castMode=mode
                for now in (10,14.999,15):
                    for lua in (a,b):lua.globals().now=now
                    self.tick(a,b)
                expected=['use:1:player','cast:116:player']*2 if mode=='error' else ['use:1:player']*2
                self.assertEqual(list(b.globals().calls.values()),expected)

    def test_empty_first_snapshot_does_not_refresh_later(self):
        a,b=self.hosts()
        for lua in (a,b):lua.execute('saved=P07483180._pixelStripV2BySpec;P07483180._pixelStripV2BySpec=nil')
        self.tick(a,b)
        for lua in (a,b):lua.execute('P07483180._pixelStripV2BySpec=saved')
        self.tick(a,b)
        self.assertEqual(list(b.globals().calls.values()),[])

    def test_complete_addon_actual_mage_buff_contract_reaches_self_target(self):
        lua=integration.DirectCastIntegrationTests().fixture()
        g=lua.globals();slots=g.WowBuddyDev._pixelStripV2BySpec[1482]
        eligible=[slot for slot in slots.values() if slot.kind=='presence' and slot.unit=='player'
                  and slot.filter=='HELPFUL' and slot.spellIDs]
        self.assertTrue(eligible)
        chosen=eligible[0]
        g.keeperName=chosen.name;g.keeperID=chosen.spellIDs[1];g.keeperRanks=chosen.spellIDs
        lua.execute('''
            function GetSpellInfo(name)
                if name==keeperName then return name,nil,nil,0,nil,nil,keeperID end
            end
            function GetActionInfo(slot) if slot==7 then return 'spell',keeperID end end
            function GetSpellCooldown() return 0,0 end
            C_Spell={GetSpellName=function(id)
                for _,rank in ipairs(keeperRanks) do if id==rank then return keeperName end end
            end}
            C_UnitAuras={GetPlayerAuraBySpellID=function() return nil end,
                        GetAuraDataByIndex=function() return nil end}
        ''')
        callbacks=[]
        for _,ticker in g.loadTickers.items():
            if lua.eval('debug.getinfo')(ticker.callback).source=='@DirectCastKeeper.lua':
                callbacks.append(ticker.callback)
        self.assertEqual(len(callbacks),1)
        callbacks[0]()
        self.assertEqual(len(g.directCalls),1)
        self.assertEqual(g.directCalls[1].slot,7)
        self.assertEqual(g.directCalls[1].unit,'player')


if __name__=='__main__':unittest.main()
