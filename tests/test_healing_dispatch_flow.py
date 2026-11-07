"""完整戒律方案到真实调度/KeySender；Win32仅记录，不投递游戏。"""
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'desktop'),str(ROOT/'tests/core')]
from test_dispatch import AdvancingWin32
from test_old_protocol import CONTRACT,RULES
from test_pipeline import READABLE,READABLE_RULES
from wowbuddy.dispatch import ActionDispatcher
from wowbuddy.old_protocol import OldFrame
from wowbuddy.pipeline import DecisionPipeline,PreparedFrame
from wowbuddy.scheduler import Scheduler
from wowbuddy.windows_keys import KeySender


class HealingDispatchFlowTests(unittest.TestCase):
    def setUp(self):
        profiles=json.loads((ROOT/'assets/rotations.json').read_bytes())['rotations']
        self.profile=next(p for p in profiles if p['id']==20)
        self.backend=AdvancingWin32()
        self.sender=KeySender(self.backend,hwnd=10,force_background=True,allow_activation=False,
                             interval_ms=30,hold_ms=30)
        self.dispatcher=ActionDispatcher(self.sender)
        self.scheduler=Scheduler(DecisionPipeline(CONTRACT,READABLE,RULES,READABLE_RULES),
                                 self.dispatcher,self.backend.now_ms)
        self.scheduler.state.target_valid=1
        self.fields={'master_switch':'ON','player_valid':'ON','target_valid':'ON',
                     'gcd':'OFF','player_casting':'空闲','player_in_combat':'ON',
                     'priest_talents':'31/0/0','health_player':'100','focus_index':'0',
                     'health_party1':'40','health_party2':'10',
                     'friendly_party1':'ON','friendly_party2':'ON'}
        for action in RULES['specs']['1487']['actions']:
            if action.get('spellId'):
                self.fields['ready_'+str(action['spellId'])]='OFF'
        self.fields['ready_2060']='ON'

    def tick(self,**overrides):
        fields=self.fields|overrides
        prepared=PreparedFrame(OldFrame('ok',spec_id='1487',values=fields),fields,
                               selected_rules=self.profile['rules'])
        return self.scheduler.process(prepared,hwnd=10,send_interval_ms=100)

    def test_lowest_health_focus_then_heal_and_gcd(self):
        result=self.tick()
        self.assertEqual(result.status,'sent')
        self.assertEqual((result.selected.action,result.selected.pre_action),
                         ('spell_2060_focus','focus_party2'))
        self.assertTrue(result.dispatch.pre_success)
        self.assertEqual([call[3] for call in self.backend.of('PostMessageW') if call[2]==0x100],
                         [0x12,0x60,0x11,0x68])  # ALT-NUMPAD0切队友2，CTRL-NUMPAD8治疗。
        self.assertEqual(self.backend.of('Sleep'),[('Sleep',10),('Sleep',40),('Sleep',10)])
        self.assertEqual((self.dispatcher.state.success_count,self.sender.success_count),(1,2))
        self.assertEqual(self.dispatcher.state.local_gcd_until_ms,2560)
        self.assertEqual(self.tick().status,'interval')
        self.backend.clock=1200
        self.assertEqual(self.tick().status,'gcd_blocked')

    def test_observed_focus_skips_only_pre_key(self):
        result=self.tick(focus_index='2')
        self.assertEqual(result.status,'sent')
        self.assertEqual(result.selected.pre_action,'focus_party2')
        self.assertTrue(result.dispatch.pre_skipped)
        self.assertEqual(self.backend.of('Sleep'),[('Sleep',10)])
        self.assertEqual(self.sender.success_count,1)
        self.assertEqual([call[3] for call in self.backend.of('PostMessageW') if call[2]==0x100],
                         [0x11,0x68])

    def test_nan_rule_rejected_before_group_sort(self):
        result=self.tick(health_party2='nan')
        self.assertEqual(result.status,'sent')
        self.assertEqual(result.selected.pre_action,'focus_party1')
        self.assertTrue(all(c.pre_action!='focus_party2' for c in result.decision.candidates))

    def test_friendly_gate_prevents_healing(self):
        result=self.tick(friendly_party1='OFF',friendly_party2='OFF')
        self.assertEqual(result.status,'no_candidates')
        self.assertEqual(self.sender.success_count,0)
        self.assertFalse(self.backend.of('PostMessageW'))

    def test_pre_key_failure_still_attempts_main_action(self):
        self.backend.post_results=[0]
        result=self.tick()
        self.assertEqual(result.status,'sent')
        self.assertFalse(result.dispatch.pre_success)
        self.assertEqual(self.dispatcher.state.focus.last_action,'')
        self.assertEqual(self.dispatcher.state.success_count,1)
        self.assertNotIn(('Sleep',40),self.backend.of('Sleep'))

    def test_same_spell_hold_applies_across_focus_targets(self):
        self.assertEqual(self.tick().selected.pre_action,'focus_party2')
        self.backend.clock=2600
        result=self.tick(health_party1='5',health_party2='40')
        self.assertEqual(result.status,'suppressed')
        self.assertEqual(self.dispatcher.state.success_count,1)
        self.backend.clock=4100
        result=self.tick(health_party1='5',health_party2='40')
        self.assertEqual(result.status,'sent')
        self.assertEqual(result.selected.pre_action,'focus_party1')
        self.assertEqual(self.dispatcher.state.success_count,2)


if __name__=='__main__':unittest.main()
