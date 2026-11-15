import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'desktop'))
from wowbuddy.dev_library import seed_library, profile_action_gaps, read_local_library
import json
from types import SimpleNamespace
from wowbuddy.engine.rotation_selection import load_snapshot,SelectionState,apply_selection,refresh_library


class LocalLibraryTests(unittest.TestCase):
    def test_duplicate_key_selects_first_record_and_reload_uses_new_order(self):
        payload=json.loads((ROOT/'assets/rotations.json').read_bytes())
        hub=load_snapshot(json.dumps(payload).encode()).state
        duplicate=[p for p in hub.profiles if p.id in (130,131)]
        self.assertEqual([p.id for p in duplicate],[130,131])
        self.assertEqual([len(p.rules) for p in duplicate],[5,6])
        self.assertEqual(duplicate[0].key,duplicate[1].key)
        key=duplicate[0].key
        result=apply_selection(hub,SelectionState(spec_id='1487',current_key=key),{})
        self.assertEqual(result.state.active_profile.id,130)
        first_rules=result.state.active_profile.to_json()['rules']
        left=next(i for i,p in enumerate(payload['rotations']) if p['id']==130)
        right=next(i for i,p in enumerate(payload['rotations']) if p['id']==131)
        payload['rotations'][left],payload['rotations'][right]=payload['rotations'][right],payload['rotations'][left]
        changed=load_snapshot(json.dumps(payload).encode(),hub).state
        changed,applied=refresh_library(changed,result.state,result.settings,'1487')
        self.assertEqual(applied.state.current_key,key)
        self.assertEqual(applied.state.active_profile.id,131)
        self.assertEqual(len(applied.state.active_profile.rules),6)
        self.assertNotEqual(applied.state.active_profile.to_json()['rules'],first_rules)
        self.assertFalse(changed.changed_pending)
        # 无新快照变化时不重复重建或重新应用。
        _,unchanged=refresh_library(changed,applied.state,applied.settings,'1487')
        self.assertEqual(unchanged.effect,'preserved')
        self.assertFalse(unchanged.refresh_thresholds)
        self.assertEqual(unchanged.state.active_profile.id,131)

    def test_reload_rejects_invalid_file_and_recognizes_updated_rules(self):
        previous=load_snapshot((ROOT/'assets/rotations.json').read_bytes()).state
        with TemporaryDirectory() as directory:
            path=Path(directory)/'rotations.json'
            path.write_text('{broken','utf8')
            with self.assertRaises(ValueError):read_local_library(path,previous)
            self.assertEqual(len(previous.profiles),41)
            payload=json.loads((ROOT/'assets/rotations.json').read_bytes())
            payload['rotations'][0]['rules'][0]['reason']='本地编辑测试'
            path.write_text(json.dumps(payload),'utf8')
            loaded=read_local_library(path,previous)
            self.assertEqual(loaded.profiles[0].rules[0].reason,'本地编辑测试')
            self.assertNotEqual(previous.profiles[0].rules[0].reason,'本地编辑测试')

    def test_missing_main_and_pre_actions_are_reported_without_duplicates(self):
        profile=SimpleNamespace(spec_id=1482,rules=[
            SimpleNamespace(action='shoot_wand',pre='missing_pre'),
            SimpleNamespace(action='shoot_wand',pre=''),
            SimpleNamespace(action='spell_116',pre='focus_party1'),
            SimpleNamespace(action='auto_target',pre='')])
        rules={'specs':{'1482':{'actions':[{'name':'spell_116'}]}}}
        self.assertEqual(profile_action_gaps(profile,rules),('shoot_wand','missing_pre'))
        self.assertEqual(profile_action_gaps(None,rules),())

    def test_warlock_double_dot_rule_uses_wand_only_in_development(self):
        from dataclasses import replace
        from wowbuddy.engine.assets import Assets
        from wowbuddy.core.dev_protocol import DEV_VERSION
        from wowbuddy.core.old_protocol import OldFrame

        hub = load_snapshot((ROOT/'assets/rotations.json').read_bytes()).state
        profile = next(profile for profile in hub.profiles if profile.id == 33)
        pipeline = Assets.load(ROOT/'assets').pipeline()
        self.assertEqual(profile_action_gaps(profile, pipeline.rules), ('start_attack', 'shoot_wand'))
        self.assertEqual(profile_action_gaps(profile, pipeline.engine.document), ())
        fields = {'master_switch': 'ON', 'player_valid': 'ON', 'target_valid': 'ON', 'player_in_combat': 'ON',
                  'player_moving': 'OFF', 'player_casting': '空闲', 'gcd': 'OFF', 'player_health_pct': '75',
                  'mana_pct': '75', 'agony': 'ON', 'corruption': 'ON', 'pet_valid': 'OFF', 'shoot_wand_key': 'F8'}
        frame = OldFrame('ok', version_code=DEV_VERSION, spec_id='1490', values=fields)

        def wands(observed):
            prepared = pipeline.prepare_frame(observed, selected_profile=profile.to_json())
            return [(c.key, c.hold_ms) for c in pipeline.generate(prepared).candidates if c.action == 'shoot_wand']

        self.assertEqual(wands(frame), [('F8', 800), ('F8', 1500)])
        self.assertEqual(wands(replace(frame, values=dict(fields, corruption='OFF'))), [('F8', 1500)])
        self.assertEqual(wands(replace(frame, values=dict(fields, shoot_wand_key=''))), [])
        self.assertEqual(wands(replace(frame, version_code=0)), [])
        self.assertEqual(profile.rules[5].action, 'start_attack')

    def test_initial_library_loads_and_preserves_user_changes(self):
        with TemporaryDirectory() as directory:
            self.assertTrue(seed_library(ROOT/'assets', directory))
            target = Path(directory)/'hub/rotations.json'
            parsed = load_snapshot(target.read_bytes())
            self.assertTrue(parsed.accepted)
            self.assertEqual(len(parsed.state.profiles), 41)
            target.write_bytes(b'user-owned snapshot')
            self.assertFalse(seed_library(ROOT/'assets', directory))
            self.assertEqual(target.read_bytes(), b'user-owned snapshot')

    def test_invalid_bundle_does_not_create_user_snapshot(self):
        with TemporaryDirectory() as directory:
            base = Path(directory)
            (base/'rotations.json').write_bytes(b'{}')
            with self.assertRaises(ValueError):
                seed_library(base, base/'user')
            self.assertFalse((base/'user/hub/rotations.json').exists())
