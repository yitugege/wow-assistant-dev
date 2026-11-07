"""移动意图与原模块计时器调用轨迹对照，不执行游戏输入。"""
import unittest
from tests import test_direct_cast_actions as actions
from tests import test_direct_cast_integration as integration

HOST='''
now=10;speed=1;dead=false;casting=false;channel=false;cdStart=0;cdDuration=0;castTime=2000
function GetTime() return now end
function GetUnitSpeed() return speed end
function GetSpellInfo(name) return name,nil,nil,castTime,nil,nil,nameKnown and 116 or nil end
function GetSpellCooldown() return cdStart,cdDuration end
function UnitIsDeadOrGhost() return dead end
function UnitCastingInfo() if casting then return 'cast' end end
function UnitChannelInfo() if channel then return 'channel' end end
'''


class DirectCastMovementTests(unittest.TestCase):
    def hosts(self):
        a,b=actions.DirectCastActionsTests().hosts()
        for lua in (a,b): lua.execute(HOST)
        b.execute('tickers={};C_Timer={NewTicker=function(period,fn) table.insert(tickers,{period=period,fn=fn}) end}')
        b.execute((actions.ROOT/'addon/WowBuddyDev/DirectCastMovement.lua').read_text('utf8'))
        self.assertEqual(len(b.globals().tickers),1)
        self.assertEqual(b.globals().tickers[1].period,0.1)
        return a,b

    def gate(self,a,b):
        expected=a.globals().P07483180.DirectCast.MovementGate('spell_116')
        actual=b.globals().WowBuddyDev.DirectCast.MovementGate('spell_116')
        self.assertEqual(actual,expected)
        return actual

    def tick(self,a,b,count=1):
        for _ in range(count):
            a.globals().tickers[2].fn();b.globals().tickers[1].fn()
            self.assertEqual(list(b.globals().calls.values()),list(a.globals().calls.values()))

    def test_expiry_and_character_state_boundaries(self):
        for elapsed,flag in ((8,None),(8.001,None),(1,'dead'),(1,'casting'),
                             (1,'channel'),(1,'cooldown'),(1,'off')):
            with self.subTest(elapsed=elapsed,flag=flag):
                a,b=self.hosts();self.assertTrue(self.gate(a,b))
                for lua in (a,b):
                    g=lua.globals();g.now=10+elapsed;g.speed=0
                    if flag=='cooldown':g.cdStart=10;g.cdDuration=5
                    elif flag=='off':g.SlashCmdList.DIRECTCAST('off')
                    elif flag:setattr(g,flag,True)
                self.tick(a,b,2)
                if flag=='casting':
                    for lua in (a,b):lua.globals().casting=False
                    self.tick(a,b,2)
                    self.assertEqual(list(b.globals().calls.values()),['use:1:target'])

    def test_two_stationary_ticks_restart_after_moving_and_intent_only_fires_once(self):
        a,b=self.hosts();self.assertTrue(self.gate(a,b))
        for speed in (0,1,0):
            for lua in (a,b):lua.globals().speed=speed
            self.tick(a,b)
            self.assertEqual(list(b.globals().calls.values()),[])
        self.tick(a,b,3)
        self.assertEqual(list(b.globals().calls.values()),['use:1:target'])

    def test_instant_disabled_unknown_name_and_still_gates(self):
        for condition in ('instant','off','unknown','still'):
            with self.subTest(condition=condition):
                a,b=self.hosts()
                for lua in (a,b):
                    g=lua.globals()
                    if condition=='instant':g.castTime=0
                    elif condition=='off':g.SlashCmdList.DIRECTCAST('off')
                    elif condition=='unknown':g.nameKnown=False
                    else:g.speed=0
                self.gate(a,b)
                for lua in (a,b):lua.globals().speed=0
                self.tick(a,b,3)
                self.assertEqual(list(b.globals().calls.values()),[])

    def test_use_error_falls_back_and_false_return_does_not(self):
        for mode in ('error','false'):
            with self.subTest(mode=mode):
                a,b=self.hosts();self.gate(a,b)
                for lua in (a,b):lua.globals().useMode=mode;lua.globals().speed=0
                self.tick(a,b,2)
                self.assertEqual(len(b.globals().calls),2 if mode=='error' else 1)

    def test_real_class_macro_lookup_can_supply_movement_intent(self):
        lua=integration.DirectCastIntegrationTests().fixture()
        lua.execute(HOST)
        lua.globals().nameKnown=True
        dc=lua.globals().WowBuddyDev.DirectCast
        self.assertTrue(dc.MovementGate('class_numpad5'))
        lua.globals().speed=0
        candidates=[]
        for _,ticker in lua.globals().loadTickers.items():
            info=lua.eval('debug.getinfo')(ticker.callback)
            if info.source=='@DirectCastMovement.lua':candidates.append(ticker)
        self.assertEqual(len(candidates),1)
        candidates[0].callback();candidates[0].callback()
        self.assertEqual(len(lua.globals().directCalls),1)
        self.assertEqual(lua.globals().directCalls[1].slot,7)


if __name__=='__main__':unittest.main()
