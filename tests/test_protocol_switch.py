"""双向切换、反复切换与原缓存行为对比；合成图像，不发送按键。"""
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'));sys.path.insert(0,str(ROOT/'tests/core'))
from test_old_protocol import render_old
from test_pipeline import render_readable
from wowbuddy.assets import Assets
from wowbuddy.pipeline import DecisionPipeline
from wowbuddy.controller import FrameController
from wowbuddy.rotation_selection import HubState
from wowbuddy.readable_protocol import UnverifiedDescriptorTable

class ProtocolSwitchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.assets=Assets.load(ROOT/'assets')

    def test_repeated_bidirectional_switch_matches_fresh_controller(self):
        assets=self.assets
        controller=FrameController(assets.pipeline(),HubState())
        for spec in sorted(set(assets.contract['specs']) & set(assets.readable_contract['specs'])):
            old,_=render_old(int(spec))
            readable=render_readable(int(spec))
            for index,image in enumerate((old,readable,old,readable)):
                with self.subTest(spec=spec,index=index):
                    actual=controller.prepare(image).frame
                    expected=FrameController(assets.pipeline(),HubState()).prepare(image).frame
                    self.assertTrue(actual.ok)
                    self.assertEqual(actual.rows,expected.rows)
                    self.assertEqual(actual,expected)

    def test_legacy_mage_short_table_remains_reproducible_for_comparison(self):
        a=self.assets
        pipeline=DecisionPipeline(a.contract,a.readable_contract,a.rules,a.readable_rules,legacy_descriptor_cache=True)
        controller=FrameController(pipeline,HubState())
        controller.prepare(render_old(1482)[0])
        with self.assertRaises(UnverifiedDescriptorTable):controller.prepare(render_readable(1482))

    def test_gui_switch_rebuilds_field_metadata_and_cached_values(self):
        from types import SimpleNamespace
        from wowbuddy.capture import CaptureResult
        from test_dev_tray import TrayTests
        def exercise(window):
            current={}
            window.loop.capture=SimpleNamespace(capture=lambda hwnd:CaptureResult('ok',current['image'],'printwindow'))
            window.dispatcher.sender=None
            window.toggle_monitor()
            for spec in sorted(set(self.assets.contract['specs']) & set(self.assets.readable_contract['specs'])):
                old,_=render_old(int(spec));readable=render_readable(int(spec))
                for index,image in enumerate((old,readable,old,readable)):
                    with self.subTest(spec=spec,index=index):
                        current['image']=image
                        result=window.poll_once()
                        expected=FrameController(self.assets.pipeline(),HubState()).prepare(image).frame
                        self.assertTrue(result.tick.decision.frame.ok)
                        self.assertEqual(window._field_rows,expected.rows)
                        self.assertEqual(len(window.session.state.field_values),len(expected.rows))
                        self.assertEqual(window.session.state.field_values,
                            [r.decoded.value_text+(' '+r.decoded.detail if r.decoded.detail else '') for r in expected.rows])
        TrayTests.run_window(self,False,exercise)

    def test_class_change_keeps_dispatch_ledgers_like_original(self):
        from types import SimpleNamespace
        from wowbuddy.capture import CaptureResult
        from test_dev_tray import TrayTests
        def exercise(window):
            current={}
            window.loop.capture=SimpleNamespace(capture=lambda hwnd:CaptureResult('ok',current['image'],'printwindow'))
            window.dispatcher.sender=None
            window.scheduler.clock_ms=lambda:1000
            window.toggle_monitor()
            state=window.dispatcher.state
            state.success_count=7;state.last_sent_ms=900;state.local_gcd_until_ms=2400
            state.focus.last_action='focus_party2';state.focus.last_switch_ms=800
            ledger=state.auras
            ledger.suppression_until['sentinel']=9000
            ledger.check_at['sentinel']=8000
            ledger.expect_off['sentinel']=('test_aura',)
            ledger.failures['sentinel']=2
            ledger.original_hold_ms['sentinel']=10000
            ledger.sent_generation['sentinel']=4
            maps=('suppression_until','check_at','expect_off','failures','original_hold_ms','sent_generation')
            before={name:dict(getattr(ledger,name)) for name in maps}
            for spec in (1482,1487,1484,1482):
                current['image']=render_old(spec,{'player_valid':0x00ff00,'target_valid':0xff0000})[0]
                result=window.poll_once()
                with self.subTest(spec=spec):
                    self.assertTrue(result.tick.decision.frame.ok)
                    self.assertEqual(window.controller.spec_id,str(spec))
                    self.assertEqual(window.session.state.current_spec,str(spec))
                    self.assertEqual((state.success_count,state.last_sent_ms,state.local_gcd_until_ms),(7,900,2400))
                    self.assertEqual((state.focus.last_action,state.focus.last_switch_ms),('focus_party2',800))
                    self.assertEqual({name:dict(getattr(ledger,name)) for name in maps},before)
        TrayTests.run_window(self,False,exercise)
