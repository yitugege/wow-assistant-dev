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
