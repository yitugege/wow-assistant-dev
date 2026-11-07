"""原包/独立战士事件历史差分；仅向真实Lua回调提供记录夹具。"""
import hashlib
from pathlib import Path
import sys
import unittest
from lupa.lua51 import LuaRuntime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'desktop'))
from wowbuddy.packages import read_addon


class WarriorFeedbackTests(unittest.TestCase):
    def test_immunity_lifetime_target_identity_and_feedback_pairing(self):
        path = Path('D:/reverse-analysis/wow-assistant/unpacked/addon.bin')
        if not path.is_file():
            self.skipTest('需要原内置插件包')
        payload = path.read_bytes()
        self.assertEqual(hashlib.sha256(payload).hexdigest(),
                         '361134bc9f2dd0b2c8cd8849b3741bd88d09c55ec371de9abc7b6f79502ebbed')
        member = 'classes/Warrior/class_forever.lua'
        original = next(m.data.decode('utf-8-sig') for m in read_addon(payload) if m.name == member)
        rebuilt = (ROOT / 'addon/WowBuddyDev' / member).read_text('utf8')
        def create(source):
            lua = LuaRuntime(unpack_returned_tuples=True)
            lua.execute((ROOT / 'tests/pixelbar_host.lua').read_text('utf8'))
            lua.execute('''P07483180=WowBuddyDev; WowBuddyDev.classes={}
            function WowBuddyDev.RegisterPixelStripV2() end
            function WowBuddyDev.RegisterClass(id,data) WowBuddyDev.classes[id]=data end
            now=100; targetGUID='target-A'; secretValue=nil
            function UnitGUID(unit) if unit=='player' then return 'player-A' end return targetGUID end
            function UnitName(unit) return 'same-name' end
            function issecretvalue(value) return secretValue~=nil and value==secretValue end
            SPELL_FAILED_IMMUNE='immune';SPELL_FAILED_DAMAGE_IMMUNE='damage-immune'
            function CombatLogGetCurrentEventInfo() return unpack(combatEvent,1,15) end''')
            lua.execute(source)
            lua.execute('''WowBuddyDev.classData=WowBuddyDev.classes[1491]
            for _,frame in ipairs(frames) do
              if frame.unitEvents and frame.unitEvents.UNIT_SPELLCAST_SENT then rendFrame=frame end
            end
            assert(rendFrame and rendFrame.scripts.OnEvent)
            function fire(event,...) rendFrame.scripts.OnEvent(rendFrame,event,...) end
            function log(kind,source,target,spell,miss)
              combatEvent={[2]=kind,[4]=source,[8]=target,[12]=spell,[15]=miss}
              fire('COMBAT_LOG_EVENT_UNFILTERED')
            end
            function send(spell) fire('UNIT_SPELLCAST_SENT','player','same-name','cast',spell or 772) end
            function outcome(spell) WowBuddyDev.classData.OnSpellCast(spell or 772) end
            function immune() fire('UI_ERROR_MESSAGE',1,'immune') end
            function blocked() return WowBuddyDev.classData.OverrideIsSpellReady(772)==false end''')
            return lua
        hit = "log('SPELL_MISSED','player-A','target-A',772,'IMMUNE')"
        cases = {
            'expiry': [(hit,True), ('now=129.999',True), ('now=130',False)],
            'guid_not_name': [(hit,True), ("targetGUID='target-B';fire('PLAYER_TARGET_CHANGED')",False),
                              ("targetGUID='target-A';fire('PLAYER_TARGET_CHANGED')",True)],
            'death': [(hit,True), ("log('UNIT_DIED',nil,'target-A',nil,nil)",False)],
            'aura_applied': [(hit,True), ("log('SPELL_AURA_APPLIED','player-A','target-A',772,nil)",False)],
            'aura_refresh': [(hit,True), ("log('SPELL_AURA_REFRESH','player-A','target-A',772,nil)",False)],
            'damage': [(hit,True), ("log('SPELL_PERIODIC_DAMAGE','player-A','target-A',772,nil)",False)],
            'regen': [(hit,True), ("fire('PLAYER_REGEN_ENABLED')",False)],
            'world': [(hit,True), ("fire('PLAYER_ENTERING_WORLD')",False)],
            'foreign_source': [("log('SPELL_MISSED','other','target-A',772,'IMMUNE')",False)],
            'other_spell': [("log('SPELL_MISSED','player-A','target-A',100,'IMMUNE')",False)],
            'other_miss': [("log('SPELL_MISSED','player-A','target-A',772,'DODGE')",False)],
            'secret_guid': [("secretValue='target-A';"+hit,False)],
            'ui_after_outcome': [('send();outcome();now=100.5;immune()',True)],
            'ui_before_outcome': [('send();immune();now=100.5;outcome()',True)],
            'ui_too_far': [('send();outcome();now=100.601;immune()',False)],
            'attempt_expired': [('send();now=102.001;outcome();immune()',False)],
            'target_changed': [("send();fire('PLAYER_TARGET_CHANGED');outcome();immune()",False)],
            'different_cast': [('send();outcome(100);outcome();immune()',False)],
            'error_before_send': [('immune();send();outcome()',False)],
        }
        for rank in (772,6546,6547,6548,11572,11573,11574):
            cases['rank_'+str(rank)] = [(f"log('SPELL_MISSED','player-A','target-A',{rank},'IMMUNE')",True)]
        for name, steps in cases.items():
            old, new = create(original), create(rebuilt)
            for script, expected in steps:
                with self.subTest(scenario=name, script=script):
                    snapshots = []
                    for lua in (old,new):
                        lua.execute(script)
                        g = lua.globals()
                        self.assertEqual(g.blocked(), expected)
                        last = g.WowBuddyDev.rendFeedback.last
                        snapshots.append((g.blocked(),
                                          tuple(last[key] for key in ('targetGUID','source','at','retryAt')) if last else None,
                                          g.WowBuddyDev.rendFeedback.lastUnreadableEvent))
                    self.assertEqual(*snapshots)
        self.assertEqual(len(cases),26)


if __name__ == '__main__':
    unittest.main()
