"""新旧版本隔离和24位边界；完整Lua编码往返另由专项工具覆盖。"""
from pathlib import Path
import sys
import unittest
from lupa.lua51 import LuaRuntime
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'));sys.path.insert(0,str(ROOT/'tests/core'))
from wowbuddy.assets import Assets
from wowbuddy.dev_protocol import DEV_VERSION, MAX_AVAILABILITY_SPELLS
from wowbuddy.expressions import EvaluationContext
from wowbuddy.old_protocol import OldDecoder
from test_old_protocol import render_old
from test_pipeline import render_readable

class AvailabilityProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.assets=Assets.load(ROOT/'assets')

    def test_lua_and_desktop_version_and_capacity_agree(self):
        line=next(line for line in (ROOT/'addon/WowBuddyDev/Core.lua').read_text('utf8').splitlines()
                  if line.startswith('local addonVersionCode ='))
        self.assertEqual(LuaRuntime().execute(line+'\nreturn addonVersionCode'),DEV_VERSION)
        for spec in self.assets.rules['specs'].values():
            self.assertLessEqual(len(spec['actionAvailSpellIDs']),MAX_AVAILABILITY_SPELLS)

    def test_zero_all_and_highest_bit_in_both_protocols(self):
        ids=tuple(self.assets.rules['specs']['1484']['actionAvailSpellIDs'])
        for wire,ready in ((0,set()),(0xffffff,set(ids)),(0x800000,{17056})):
            for render in (lambda data:render_old(1484,data)[0],lambda data:render_readable(1484,data)):
                frame=self.assets.pipeline().prepare(render({'addon_version_code':DEV_VERSION,'action_avail':wire})).frame
                self.assertTrue(frame.ok)
                context=EvaluationContext(frame.values,ids,allow_unknown_availability=frame.allow_unknown_availability)
                self.assertEqual([context.availability(sid) for sid in ids],[int(sid in ready) for sid in ids])
                row=next(row for row in frame.rows if row.key=='action_avail')
                self.assertEqual(row.decoded.raw_value,wire)
                self.assertEqual(row.decoded.value_text,frame.values['action_avail'])

    def test_same_spec_version_switch_does_not_reinterpret_legacy_white(self):
        pipeline=self.assets.pipeline()
        legacy=self.assets.contract['constants']['expectedVersion']
        for version,expected in ((legacy,'—'),(DEV_VERSION,'33554431'),(legacy,'—')):
            frame=pipeline.prepare(render_old(1484,{'addon_version_code':version,'action_avail':0xffffff})[0]).frame
            self.assertTrue(frame.ok)
            self.assertEqual(frame.values['action_avail'],expected)

    def test_legacy_decoder_default_does_not_accept_new_old_layout_version(self):
        frame=OldDecoder(self.assets.contract).decode(render_old(1484,{'addon_version_code':DEV_VERSION})[0])
        self.assertEqual(frame.status,'version_mismatch')
