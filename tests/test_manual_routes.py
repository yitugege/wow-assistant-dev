from concurrent.futures import Future
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from lupa.lua51 import LuaRuntime

import test_dev_tray
from wowbuddy.automation.arrival_pull import ArrivalPull
from wowbuddy.core.auto_target import PACKET_BASE
from wowbuddy.core.candidates import Candidate
from wowbuddy.engine.character_state import CharacterState, DeathState, NavigationState
from wowbuddy.automation.leveling_route import AutomaticLeveling
from wowbuddy.automation.manual_routes import manual_camp_road, parse_fixed_camp, parse_manual_connection, parse_manual_route
from wowbuddy.automation.navigation import MapDestination, MapNavigator
from wowbuddy.core.old_protocol import OldFrame
from wowbuddy.engine.pipeline import Decision
from wowbuddy.engine.scheduler import TickResult
from wowbuddy.settings import open_ini_settings
from wowbuddy.automation.walking_route import WalkingTrip, plan_walking_route


ROOT = Path(__file__).resolve().parents[1]


class ManualRouteTests(unittest.TestCase):
    def test_corpse_trail_requires_revival_and_matches_a_nearby_corpse(self):
        from wowbuddy.automation.death_recovery import CorpseTrail

        trail = CorpseTrail()
        corpse = (1440, 20.0, 15.0)
        death = DeathState('dead', 1, None, False, None)
        ghost = DeathState('ghost', 2, None, False, corpse)
        start = NavigationState('ghost', 2, 1440, 18.0, 14.0, 0, 2500, 2500, (1, 2, 3))
        corner = replace(start, sequence=3, y=15.0)
        end = replace(corner, sequence=4, x=20.0)
        alive = DeathState('alive', 5, None, False, None)
        trail.observe(1, death, None, now_ms=0)
        self.assertIsNone(trail.observe(1, ghost, start, now_ms=100))
        self.assertTrue(trail.waiting_for_start)
        trail.observe(1, ghost, replace(start, sequence=11), now_ms=750)
        trail.observe(1, ghost, replace(start, sequence=12), now_ms=1400)
        self.assertIn('墓地地图 1440', trail.notice)
        self.assertIsNone(trail.observe(1, ghost, corner, now_ms=2100))
        self.assertIsNone(trail.observe(1, replace(ghost, button=(100, 100)), end, now_ms=2800))
        self.assertIsNone(trail.observe(1, replace(ghost, life='unknown'), None, now_ms=2900))
        recorded = trail.observe(1, alive, None, now_ms=3000)
        shifted = MapDestination(1440, 20.8, 15.0, 'ghost', '尸体')
        self.assertEqual(trail.replay([recorded], start, shifted)[0].points,
                         ((18.0, 14.0), (18.0, 15.0), (20.0, 15.0)))
        self.assertTrue(trail.replay(['WBDROUTE1|1440|1800,1400|2000,1500'], start, shifted))
        self.assertFalse(trail.replay([recorded], start, replace(shifted, x=22.0)))
        self.assertFalse(trail.replay([recorded], replace(start, x=17.0), shifted))
        trail.replay_blocked = True
        self.assertFalse(trail.replay([recorded], start, shifted))
        trail.observe(1, death, None, now_ms=4000)
        trail.observe(1, ghost, start, now_ms=4100)
        trail.observe(1, ghost, replace(start, sequence=11), now_ms=4750)
        trail.observe(1, ghost, replace(start, sequence=12), now_ms=5400)
        trail.observe(1, ghost, replace(start, x=start.x + 5), now_ms=6000)
        self.assertIsNone(trail.observe(1, alive, replace(end, life='alive'), now_ms=6700))
        self.assertIn('两次可用坐标相差 125 码', trail.notice)

    def test_cross_map_corpse_recording_reuses_ordered_border_and_last_segment(self):
        session = (123, 1, 0)
        corpse = (1440, 20.0, 15.0)
        dead = DeathState('dead', 1, None, False, None)
        ghost = DeathState('ghost', 2, None, False, corpse)
        start = NavigationState('ghost', 2, 1439, 40.0, 85.0, 0, 5000, 5000, (1, 2, 3))
        last = replace(start, sequence=3, y=86.0)
        entry = replace(start, sequence=4, map_id=1440, x=18.0, y=15.0, width=2500, height=2500)
        end = replace(entry, sequence=5, x=20.0)
        alive = replace(end, life='alive', sequence=6)

        def exercise(window):
            trail = window._corpse_trail
            living = DeathState('alive', 6, None, False, None)
            trail.observe(session, ghost, entry, now_ms=0)
            trail.observe(session, replace(ghost, button=(100, 100)), end, now_ms=200)
            self.assertIsNone(trail.observe(session, living, alive, now_ms=300))
            self.assertIn('缺少墓地起点', trail.notice)
            trail.observe(session, dead, None, now_ms=400)
            trail.observe(session, ghost, entry, now_ms=500)  # 释放后暂时报灰谷
            self.assertTrue(trail.waiting_for_start)
            for now, position in enumerate((start, replace(start, sequence=21), replace(start, sequence=22),
                                            last, entry, entry, end), start=2):
                state = replace(ghost, button=(100, 100)) if position is end else ghost
                self.assertIsNone(trail.observe(session, state, position, now_ms=now * 650))
            self.assertIn('开始记录第 2 段', trail.notice)
            encoded = trail.observe(session, living, alive, now_ms=6000)
            self.assertIsNotNone(encoded)
            window.settings.save_corpse_trail(encoded)
            saved = open_ini_settings(window.settings.qsettings.fileName()).corpse_trails()
            goal = MapDestination(1440, 20.8, 15.0, 'ghost', '尸体')
            self.assertEqual(tuple(route.map_id for route in trail.replay(saved, start, goal)), (1439, 1440))
            self.assertFalse(trail.replay(saved, start, replace(goal, x=22.0)))
            self.assertFalse(trail.replay(saved, replace(start, x=40.5), goal))
            self.assertTrue(window._start_recorded_corpse_trip(session, start, goal))
            first = window._corpse_route(session, start, goal)
            self.assertEqual(first.map_id, 1439)
            self.assertEqual(first.y, last.y)
            self.assertIsNone(window._corpse_route(session, entry, goal))
            window._corpse_route(session, replace(entry, sequence=5), goal)
            window._corpse_route(session, replace(entry, sequence=6), goal)
            final = window._corpse_route(session, replace(entry, sequence=7), goal)
            self.assertEqual(final.map_id, 1440)
            self.assertEqual(final.x, end.x)
            window._discard_recorded_corpse_trip()
            self.assertFalse(window._start_recorded_corpse_trip(session, start, goal))

        test_dev_tray.TrayTests().run_window(False, exercise)

    def test_four_point_patrol_waits_for_loot_wraps_and_keeps_the_supply_destination(self):
        from wowbuddy.engine.character_state import LevelProgress, MobState, VendorState
        from wowbuddy.automation.walking_route import rejoin_darkshore_patrol_return

        text = 'WBDROUTE2|1439|黑海岸|4029,5567|3851,6999|3966,6044|3966,5185'

        def exercise(window):
            window.grind_check.setChecked(True)
            window.settings.save_manual_routes([text])
            with patch('PySide6.QtWidgets.QInputDialog.getItem',
                       return_value=('1 · 黑海岸 · 4 点 · 39.66, 51.85', True)):
                window._edit_patrol_route()
            route = window._patrol_route
            self.assertEqual(window.settings.patrol_route(), text)
            self.assertIn('4 点', window._manual_camp_button.text())
            session = (123, 1, 0)
            fields = {'player_valid': 'ON', 'player_in_combat': 'OFF', 'target_valid': 'OFF'}
            frame = OldFrame('ok', values=fields)
            result = SimpleNamespace(tick=TickResult('no_candidates', Decision(frame, fields, (), recovery_ready=True)),
                                     capture=SimpleNamespace(client_rect=None))
            window._map_navigator = navigator = Mock()
            navigator.observe.return_value = None
            window._arrival_pull = pull = Mock()
            pull.observe.return_value = None
            pull.empty = False

            def follow(trip, at):
                for _ in range(100):
                    target, _ = trip.observe(at)
                    if trip.complete:
                        return at
                    self.assertIsNotNone(target)
                    at = replace(at, x=target.x, y=target.y, sequence=at.sequence + 1)
                self.fail('未走完循环路点的补给路线')

            def supply(character, position, repairing):
                reading = VendorState(1, 0, 0, False, False, False, False, ',', 0x76, None,
                                      catalog=True, repair_needed=repairing)

                def report(status, at):
                    with (patch('wowbuddy.engine.character_state.decode_vendor_state',
                                side_effect=lambda *_args, repair=False: status if repair == repairing else None),
                          patch('wowbuddy.engine.character_state.decode_navigation_state', return_value=at),
                          patch.object(window, 'monotonic_ms', return_value=status.sequence * 2000)):
                        window._poll_vendor(session, object(), frame, result, character)

                report(reading, position)
                _, outbound, returning = window._online_vendor
                at_vendor = follow(outbound, position)
                shop = replace(reading, sequence=2, merchant_open=True, matched=True, hovered=True,
                               sell_point=(2200, 4400), repair_status=3 if repairing else 0,
                               junk=0 if repairing else 3)
                with patch.object(window, '_send_travel_ui_action', return_value=True) as send:
                    report(shop, at_vendor)
                    report(replace(shop, sequence=3, free=3, junk=0, repair_needed=False, repair_status=0), at_vendor)
                    report(replace(reading, sequence=4, free=3, repair_needed=False), at_vendor)
                    self.assertEqual([call.args[-2] for call in send.call_args_list],
                                     ['repair' if repairing else 'sell', 'close'])
                self.assertIs(window._leveling_trip[2], returning)
                at_waypoint = follow(returning, at_vendor)
                report(replace(reading, sequence=5, free=3, repair_needed=False), at_waypoint)
                self.assertIsNone(window._online_vendor)
                self.assertEqual(window._leveling_destination, (session, character.route_key, returning.goal))

            for index, (x, y) in enumerate(route.points):
                position = NavigationState('alive', index + 1, 1439, x, y, 0, 6550, 4367, (87, 65, 68))
                character = CharacterState('alive', True, True, 'alliance', 19, 1439, '黑海岸', x, y)

                def poll(*, loot_open=False):
                    with (patch('wowbuddy.engine.character_state.decode_navigation_state', return_value=position),
                          patch('wowbuddy.engine.character_state.decode_mob_state',
                                return_value=MobState(1, 1, 4, '', 1, loot_open)),
                          patch.object(window, '_observe_local_access', return_value=(None, None))):
                        window._poll_navigation(result, session, object(), frame, character, None, navigate=True)

                window._poll_leveling(session, character, True)
                active = window._leveling_trip[2]
                self.assertEqual((active.goal.x, active.goal.y), (x, y))
                self.assertEqual(active.goal.arrival_radius, 30)
                if index == 0:
                    fields['enemies_8yd'] = '2'
                    outside = replace(position, x=x - 0.6)
                    with patch('wowbuddy.engine.character_state.decode_navigation_state', return_value=outside):
                        window._poll_navigation(result, session, object(), frame, character, None, navigate=True)
                    self.assertFalse(active.complete)
                    self.assertIn('暂停前往', window.ui.suggestions.toPlainText())
                    fields['enemies_8yd'] = '0'
                    edge = replace(position, x=x - 25 * 100 / position.width, continuous=True)
                    self.assertTrue(window._start_camp_scout(session, active.goal, edge))
                    scout = window._camp_scout_point(session, active.goal)
                    self.assertAlmostEqual((scout.x - edge.x) * position.width / 100, 10)
                    self.assertFalse(scout.allow_detour)
                    self.assertFalse(window._start_camp_scout(session, active.goal, edge))
                    window._camp_scout = None
                poll()
                self.assertTrue(active.complete)
                for repair, expected in ((False, (43.65, 76.65)), (True, (38.17, 41.14))):
                    context, outbound, returning = window._plan_online_vendor(
                        session, character, position, active, catalog=True, repair=repair)
                    self.assertEqual((outbound.goal.x, outbound.goal.y), expected)
                    self.assertEqual(returning.goal, active.goal)
                    self.assertEqual(returning.approach_road[-1], (x, y))
                    window._online_vendor = context, outbound, returning
                    window._poll_leveling(session, character, True)
                    self.assertEqual(window._patrol_index, index)
                    window._online_vendor = None

                if index == 0:
                    before = replace(position, x=40.3379, y=54.4349)
                    _, outbound, returning = window._plan_online_vendor(
                        session, character, before, active, catalog=True)
                    self.assertIn((x, y), outbound.approach_road)
                    self.assertEqual(returning.approach_road.count((x, y)), 1)
                    self.assertEqual(returning.approach_road[-1], (x, y))
                    self.assertNotIn(outbound.approach_road[0], returning.approach_road)
                    revived = replace(position, x=40.59, y=56.696)
                    rejoined = rejoin_darkshore_patrol_return(returning.approach_road, revived, repair=False)
                    self.assertEqual(rejoined[1], (40.65, 57.9))
                    self.assertEqual(rejoined[-1], (x, y))
                    self.assertEqual(rejoin_darkshore_patrol_return(
                        returning.approach_road, replace(revived, moving=True), repair=False), ())
                    blocked = replace(position, x=40.244, y=56.14)
                    self.assertFalse(active.goal.contains(blocked, radius=18))
                    saved = {'camp': [x, y, active.goal.label, None], 'catalog': True,
                             'level': 19, 'free': 0, 'returning': True,
                             'outbound': outbound.approach_road,
                             'inbound': (*outbound.approach_road[::-1], (before.x, before.y), (x, y))}
                    reading = VendorState(1, 2, 0, False, False, False, False, ',', 0x76, None, catalog=True)
                    with (patch.object(window, '_travel_identity', return_value=('法师', 19)),
                          patch('wowbuddy.automation.vendor_run.read_vendor_travel', return_value=saved)):
                        self.assertTrue(window._resume_vendor_travel(session, character, blocked, reading))
                    resumed = window._leveling_trip[2]
                    self.assertEqual(resumed.goal, active.goal)
                    resumed.observe(blocked)
                    self.assertTrue(resumed.complete)
                    with patch('wowbuddy.engine.character_state.decode_navigation_state', return_value=blocked):
                        window._poll_vendor(session, object(), frame, result, character)
                    self.assertIsNone(window._online_vendor)
                    self.assertEqual(window._leveling_destination, (session, character.route_key, active.goal))

                if index == 1:
                    for repair in (False, True):
                        supply(character, position, repair)
                        self.assertEqual(window._patrol_index, index)

                window._observe_level_progress(session, LevelProgress(19, 100 + index * 10, 20000, index * 2))
                window._observe_level_progress(session, LevelProgress(19, 105 + index * 10, 20000, index * 2 + 1))
                poll(loot_open=True)
                self.assertEqual(window._patrol_index, index)
                if index == 0:
                    fields['enemies_8yd'] = '2'
                    poll()
                    self.assertEqual(window._patrol_index, index)
                    self.assertIsNone(window._patrol_kill)
                    pull.observe.assert_called()
                    fields['enemies_8yd'] = '0'
                    pull.observe.return_value = '已完成当前路点选怪扫描'
                    pull.empty = True
                poll()
                pull.observe.return_value = None
                pull.empty = False
                self.assertEqual(window._patrol_index, (index + 1) % 4)

            window._poll_leveling(session, character, True)
            goal = window._leveling_trip[2].goal
            self.assertEqual((goal.x, goal.y), route.points[0])

        test_dev_tray.TrayTests.run_window(self, False, exercise)

    def test_fixed_camp_uses_the_marked_point_without_a_guide_and_keeps_it_when_empty(self):
        def exercise(window):
            window.grind_check.setChecked(True)
            text = 'WBDPOINT1|1429|4210,6630'
            with patch('PySide6.QtWidgets.QInputDialog.getText', return_value=(text, True)):
                window._edit_fixed_camp()
            self.assertEqual(window.settings.fixed_camp(), text)
            self.assertIn('42.10, 66.30', window._manual_camp_button.text())
            window._leveling_planner = planner = Mock()
            session = (123, 1, 0)
            character = CharacterState('alive', True, True, 'alliance', 18, 1429, '艾尔文森林', 41, 66)
            window._poll_leveling(session, character, True)
            trip = window._leveling_trip[2]
            position = NavigationState('alive', 1, 1429, 41, 66, 0, 3471, 2315, (87, 65, 68))
            target, _ = trip.observe(position)
            self.assertEqual((target.x, target.y), (42.1, 66.3))
            self.assertFalse(trip.complete)
            camp, _ = trip.observe(replace(position, x=42.1, y=66.3, sequence=2))
            self.assertEqual(camp, trip.goal)
            window._advance_grind_camp(session, character, camp, '当前刷怪区未选到怪物')
            window._poll_leveling(session, character, True)
            self.assertIs(window._leveling_trip[2], trip)
            window._poll_leveling(session, replace(character, level=19), True)
            self.assertEqual(window._leveling_trip[2].goal, camp)
            self.assertEqual(planner.mock_calls, [])

        self.assertEqual(parse_fixed_camp('WBDPOINT1|1429|4210,6630').endpoint, (42.1, 66.3))
        with self.assertRaises(ValueError):
            parse_manual_route('WBDPOINT1|1429|4210,6630')
        test_dev_tray.TrayTests.run_window(self, False, exercise)

    def test_vendor_trip_waits_for_same_merchant_and_bag_receipt_then_replans_the_fixed_camp(self):
        from wowbuddy.engine.character_state import VendorState

        def exercise(window):
            window.grind_check.setChecked(True)
            window._fixed_camp_route = parse_fixed_camp('WBDPOINT1|1429|4210,6630')
            window._vendor_route = parse_fixed_camp('WBDPOINT1|1429|4250,6630')
            session = (123, 1, 0)
            character = CharacterState('alive', True, True, 'alliance', 18, 1429, '艾尔文森林', 42.1, 66.3)
            run = window._vendor_run
            window._leveling_planner = planner = Mock()
            send = Mock(return_value=True)
            initial = VendorState(1, 2, 3, False, False, False, False, ',', 0x76, None)
            self.assertIsNone(run.observe(session, initial, 0, ready=False, arrived=False, send=send))
            run.observe(session, initial, 200, ready=True, arrived=False, send=send)
            window._poll_leveling(session, character, True)
            self.assertEqual(window._leveling_trip[2].goal.label, '补给商人')
            run.observe(session, replace(initial, sequence=2), 400, ready=True, arrived=False, send=send)
            run.observe(session, replace(initial, sequence=3, merchant_open=True), 600,
                        ready=True, arrived=True, send=send)
            send.assert_not_called()
            for sequence, changes in enumerate(({}, {'selected': True},
                    {'matched': True, 'merchant_open': True, 'sell_point': (5200, 6400),
                     'hovered': True, 'confirming': True},
                    {'matched': True, 'merchant_open': True, 'sell_point': (2200, 4400)},
                    {'matched': True, 'merchant_open': True, 'sell_point': (2200, 4400), 'hovered': True},
                    {'matched': True, 'merchant_open': True, 'popup_blocked': True},
                    {'matched': True, 'merchant_open': True, 'sell_point': (5200, 6400),
                     'confirming': True, 'junk': 2, 'hovered': True},
                    {'matched': True, 'merchant_open': True, 'sell_point': (5200, 6400), 'confirming': True},
                    {'matched': True, 'merchant_open': True, 'sell_point': (5200, 6400),
                     'confirming': True, 'hovered': True},
                    {'matched': True, 'merchant_open': True, 'sell_point': (2200, 4400), 'hovered': True},
                    {'matched': True, 'merchant_open': True, 'junk': 0, 'free': 2},
                    {'matched': True, 'merchant_open': True, 'junk': 0, 'free': 5, 'popup_blocked': True},
                    {'matched': True, 'merchant_open': True, 'junk': 0, 'free': 5},
                    {'junk': 0, 'free': 5}), 4):
                run.observe(session, replace(initial, sequence=sequence, **changes), sequence * 2000,
                            ready=True, arrived=True, send=send)
            self.assertEqual([call.args for call in send.call_args_list],
                             [('select', ','), ('interact', 0x76), ('hover', (2200, 4400)),
                              ('sell', (2200, 4400)), ('hover', (5200, 6400)), ('confirm', (5200, 6400)),
                              ('close', None)])
            self.assertFalse(run.active)
            window._poll_leveling(session, character, True)
            self.assertEqual(window._leveling_trip[2].goal.label, '固定打怪点')
            self.assertEqual(planner.mock_calls, [])

        test_dev_tray.TrayTests.run_window(self, False, exercise)

    def test_online_camp_vendor_uses_marked_road_and_returns_without_requerying(self):
        from wowbuddy.engine.character_state import VendorState
        from wowbuddy.automation.navigation import MapDestination
        from wowbuddy.app.qt_app import AssistantWindow
        from wowbuddy.engine.runtime import PollResult

        def exercise(window):
            window.grind_check.setChecked(True)
            window.session.start(123)
            session = (123, window.session.state.elapsed_started_ms, window._unattended_revision)
            character = CharacterState('alive', True, True, 'alliance', 18, 1429, '艾尔文森林', 42.1, 66.3)
            camp = MapDestination(1429, 42.1, 66.3, 'alive', '联网选中的营地')
            original = session, character.route_key, camp
            window._leveling_destination = original
            window._leveling_planner = planner = Mock()
            alternatives = window._leveling_camps = [{'name': '备用营地'}]
            window._map_navigator = navigator = Mock(blocked=False, holding_forward=False)
            navigator.observe.return_value = None
            position = NavigationState('alive', 1, 1429, 42.1, 66.3, 0, 3471, 2315, (87, 65, 68))
            fields = {'player_valid': 'ON', 'player_in_combat': 'OFF', 'target_valid': 'OFF'}
            frame = OldFrame('ok', values=fields)
            tick = TickResult('no_candidates', Decision(frame, fields, (), recovery_ready=True))
            result = SimpleNamespace(tick=tick, capture=SimpleNamespace(client_rect=None))
            reading = VendorState(1, 2, 3, False, False, False, False, ',', 0x76, None)

            def poll_vendor(reading, at):
                with (patch('wowbuddy.engine.character_state.decode_vendor_state', return_value=reading),
                      patch('wowbuddy.engine.character_state.decode_navigation_state', return_value=at),
                      patch.object(window, 'monotonic_ms', return_value=reading.sequence * 2000)):
                    window._poll_vendor(session, object(), frame, result, character)

            def follow(trip, at):
                visited = []
                for _ in range(6):
                    with (patch('wowbuddy.engine.character_state.decode_navigation_state', return_value=at),
                          patch.object(window, '_observe_local_access', return_value=(None, None))):
                        window._poll_navigation(result, session, object(), frame, character, None, navigate=True)
                    if trip.complete:
                        return visited, at
                    target = navigator.observe.call_args.args[3]
                    visited.append((target.x, target.y))
                    at = replace(at, x=target.x, y=target.y, sequence=at.sequence + 1)
                self.fail('未走完商人路线')

            window._vendor_route = parse_fixed_camp('WBDPOINT1|1429|4250,6630')
            poll_vendor(reading, position)
            self.assertEqual(window._leveling_destination, original)
            window._vendor_route = parse_fixed_camp('WBDROUTE1|1429|4210,6630|4240,6650|4250,6630')
            poll_vendor(reading, replace(position, x=42.39))
            self.assertEqual(window._leveling_destination, original)
            poll_vendor(reading, position)
            self.assertIsNone(window._leveling_destination)
            outbound = window._leveling_trip[2]
            self.assertEqual(outbound.goal.label, '补给商人')
            self.assertIsNone(window._camp_death_target(session, character))
            window._poll_leveling(session, character, True)
            visited, at_vendor = follow(outbound, position)
            self.assertEqual(visited, [(42.4, 66.5), (42.5, 66.3)])
            self.assertIsNone(window._leveling_destination)

            with patch.object(window, '_send_travel_ui_action', return_value=True) as send:
                shop = replace(reading, sequence=2, merchant_open=True, matched=True, hovered=True,
                               sell_point=(2200, 4400))
                poll_vendor(shop, at_vendor)
                poll_vendor(replace(shop, sequence=3, junk=0, free=5), at_vendor)
                self.assertIs(window._leveling_trip[2], outbound)
                poll_vendor(replace(reading, sequence=4, junk=0, free=5), at_vendor)
                self.assertEqual([call.args[-2] for call in send.call_args_list], ['sell', 'close'])

            returning = window._leveling_trip[2]
            self.assertIsNot(returning, outbound)
            self.assertEqual(returning.goal, camp)
            window._poll_leveling(session, character, True)
            visited, at_camp = follow(returning, at_vendor)
            self.assertEqual(visited, [(42.4, 66.5), (42.1, 66.3)])
            supplied = replace(reading, sequence=5, junk=0, free=5)
            displaced = replace(at_camp, sequence=at_camp.sequence + 1, x=42.65)
            with patch.object(window, '_clear_vendor_travel', wraps=window._clear_vendor_travel) as clear:
                poll_vendor(supplied, None)
                poll_vendor(supplied, replace(at_camp, moving=True))
                fields['player_in_combat'] = 'ON'
                poll_vendor(supplied, at_camp)
                fields['player_in_combat'] = 'OFF'
                poll_vendor(supplied, displaced)
                clear.assert_not_called()
                self.assertIs(window._online_vendor[2], returning)
                self.assertIsNone(window._leveling_destination)
                with (patch.object(AssistantWindow, 'poll_once', return_value=PollResult('capture_failed')),
                      patch.object(window.monitor, 'stop_lost_target', return_value=False),
                      patch.object(window, '_poll_navigation')):
                    window.poll_once()
                self.assertTrue(window.pipeline.unattended_travel)
                with (patch('wowbuddy.engine.character_state.decode_navigation_state', return_value=displaced),
                      patch.object(window, '_observe_local_access', return_value=(None, None))):
                    window._poll_navigation(result, session, object(), frame, character, None, navigate=True)
                self.assertEqual(navigator.observe.call_args.args[3], camp)
                self.assertIs(navigator.observe.call_args.kwargs['path'], returning)
                self.assertIsNone(window._leveling_destination)
                poll_vendor(supplied, replace(at_camp, sequence=displaced.sequence + 1))
                clear.assert_called_once()
            self.assertEqual(window._leveling_destination, original)
            self.assertIs(window._leveling_camps, alternatives)
            self.assertIsNone(window._online_vendor)
            self.assertEqual(planner.mock_calls, [])

        test_dev_tray.TrayTests.run_window(self, False, exercise)

    def test_full_bag_uses_darkshore_vendor_without_manual_route_or_wild_junk_count(self):
        from wowbuddy.engine.character_state import VendorState
        from wowbuddy.automation.navigation import MapDestination

        def exercise(window):
            window.grind_check.setChecked(True)
            session = (123, 1, 0)
            character = CharacterState('alive', True, True, 'alliance', 18, 1439, '黑海岸', 40.2, 70.55)
            position = NavigationState('alive', 1, 1439, 40.2, 70.55, 0, 6550, 4367, (87, 65, 68))
            camp = MapDestination(1439, 39.8, 70.691, 'alive', '北侧营地')
            original = session, character.route_key, camp
            window._leveling_destination = original
            frame = OldFrame('ok', values={'player_valid': 'ON', 'player_in_combat': 'OFF', 'target_valid': 'OFF'})
            tick = TickResult('no_candidates', Decision(frame, frame.values, (), recovery_ready=True))
            result = SimpleNamespace(tick=tick, capture=SimpleNamespace(client_rect=None))
            reading = VendorState(1, 0, 0, False, False, False, False, ',', 0x76, None, catalog=True)

            def poll(reading, position):
                with (patch('wowbuddy.engine.character_state.decode_vendor_state', return_value=reading),
                      patch('wowbuddy.engine.character_state.decode_navigation_state', return_value=position),
                      patch.object(window, 'monotonic_ms', return_value=reading.sequence * 2000)):
                    window._poll_vendor(session, object(), frame, result, character)

            poll(replace(reading, catalog=False), position)
            self.assertIn('没有可用的补给商人绑定', window._vendor_wait[1])
            self.assertEqual(window._leveling_destination, original)
            poll(reading, position)
            self.assertIsNone(window._vendor_wait)
            self.assertTrue(window._vendor_run.active)
            _, outbound, returning = window._online_vendor
            self.assertEqual(returning.goal, camp)
            self.assertEqual((outbound.goal.x, outbound.goal.y), (43.65, 76.65))
            window._post_revival_notice = False
            self.assertFalse(window._rejoin_camp_after_revival(session, character, replace(position, x=55)))
            self.assertIs(window._leveling_trip[2], outbound)
            self.assertTrue(window._rejoin_camp_after_revival(session, character, position))
            outbound = window._leveling_trip[2]
            character = replace(character, level=19)
            poll(reading, position)
            self.assertEqual(window._leveling_trip[:2], ('alliance', 19))
            self.assertIs(window._online_vendor[1], outbound)
            visited = []
            for _ in range(30):
                target, _ = outbound.observe(position)
                visited.append((target.x, target.y))
                position = replace(position, x=target.x, y=target.y, sequence=position.sequence + 1)
                if outbound.complete:
                    break
            self.assertTrue(outbound.complete)
            self.assertIn((41.1399, 73.1756), visited)
            self.assertIn((42.605, 76.7149), visited)
            with patch.object(window, '_send_travel_ui_action', return_value=True) as send:
                shop = replace(reading, sequence=2, merchant_open=True, matched=True, hovered=True)
                poll(shop, position)
                self.assertIn('原生商店未列出可售杂物', window._vendor_run.notice)
                send.assert_not_called()
                poll(replace(shop, sequence=3, junk=3, sell_point=(2200, 4400), catalog=False), position)
                send.assert_not_called()
                poll(replace(shop, sequence=4, junk=3, sell_point=(2200, 4400)), position)
                poll(replace(shop, sequence=5, free=3), position)
                poll(replace(reading, sequence=6, free=3), position)
                self.assertEqual([call.args[-2] for call in send.call_args_list], ['sell', 'close'])
            self.assertFalse(window._vendor_run.active)
            self.assertIs(window._leveling_trip[2], returning)
            for _ in range(30):
                target, _ = returning.observe(position)
                position = replace(position, x=target.x, y=target.y, sequence=position.sequence + 1)
                if returning.complete:
                    break
            self.assertTrue(returning.complete)
            poll(replace(reading, sequence=7, free=3), position)
            self.assertIsNone(window._online_vendor)
            self.assertIsNone(window._leveling_trip)
            self.assertIsNone(window._leveling_destination)

        test_dev_tray.TrayTests.run_window(self, False, exercise)

    def test_full_bag_recovery_can_walk_only_the_vendor_leg_when_health_is_safe(self):
        from wowbuddy.engine.character_state import VendorState
        from wowbuddy.core.dev_protocol import DEV_VERSION, RECOVERY_CONFIG_BASE

        def exercise(window):
            window.grind_check.setChecked(True)
            session = (123, 1, 0)
            character = CharacterState('alive', True, True, 'alliance', 18, 1439, '黑海岸', 40.2, 70.55)
            position = NavigationState('alive', 1, 1439, 40.2, 70.55, 0, 6550, 4367, (87, 65, 68))
            camp = MapDestination(1439, 39.8, 70.691, 'alive', '北侧营地')
            window._leveling_destination = session, character.route_key, camp
            navigator = window._map_navigator = Mock(blocked=False, holding_forward=False)
            navigator.observe.return_value = None
            reading = VendorState(1, 0, 0, False, False, False, False, ',', 0x76, None, catalog=True)
            stopped = Candidate(action='recovery_bag_full', tag='恢复', stop=True)

            def poll(sequence, health, *, moving=False, candidate=stopped, free=0):
                base = RECOVERY_CONFIG_BASE + (50 * 128 + 90) * 128
                frame = OldFrame('ok', spec_id='1482', version_code=DEV_VERSION,
                                 values={'player_valid': 'ON', 'player_in_combat': 'OFF', 'target_valid': 'OFF',
                                         'master_switch': 'OFF', 'player_health_pct': str(health),
                                         'ttf': str(base + 82), 'combat_time': str(base + (87 if candidate == stopped else 82))})
                result = SimpleNamespace(tick=TickResult('stopped', Decision(frame, frame.values, (candidate,))),
                                         capture=SimpleNamespace(client_rect=None))
                at = replace(position, sequence=sequence, moving=moving)
                with (patch('wowbuddy.engine.character_state.decode_vendor_state', return_value=replace(reading, sequence=sequence, free=free)),
                      patch('wowbuddy.engine.character_state.decode_navigation_state', return_value=at)):
                    window._poll_vendor(session, object(), frame, result, character)
                    window._poll_navigation(result, session, object(), frame, character, None, navigate=True)
                return navigator.observe.call_args.args[2:4]

            self.assertIsNone(poll(1, 30)[0])
            self.assertIsNone(window._online_vendor)
            at, target = poll(2, 60)
            self.assertEqual(at.sequence, 2)
            self.assertEqual(window._online_vendor[1].goal.label, '补给商人')
            self.assertIn('补给商人', target.label)
            self.assertIsNotNone(poll(3, 60, moving=True, candidate=Candidate(tag='恢复', stop=True))[0])
            self.assertIsNone(poll(4, 60, candidate=Candidate(tag='恢复', stop=True))[1])
            self.assertIsNone(poll(5, 40, moving=True)[1])
            self.assertIsNone(poll(6, 60, free=1, candidate=Candidate(tag='恢复', stop=True))[1])
            self.assertIsNone(window._vendor_recovery_walk)

        test_dev_tray.TrayTests.run_window(self, False, exercise)

    def test_vendor_after_interrupted_confirmation_uses_a_new_shop_receipt(self):
        from wowbuddy.engine.character_state import VendorState
        from wowbuddy.automation.vendor_run import VendorRun

        run = VendorRun()
        session = (123, 1, 0)
        closed = VendorState(1, 0, 0, False, False, False, False, ',', 0x76, None)
        shop = replace(closed, junk=3, merchant_open=True, matched=True, hovered=True, sell_point=(2200, 4400))
        send = Mock(return_value=True)

        def poll(sequence, reading):
            return run.observe(session, replace(reading, sequence=sequence), sequence * 2000,
                               ready=True, arrived=True, send=send)

        poll(1, closed)
        poll(2, shop)
        confirm = replace(shop, confirming=True)
        poll(3, confirm)
        run.interrupt(session)
        self.assertIn('等待原商店关闭', poll(4, confirm))
        self.assertEqual([call.args[0] for call in send.call_args_list], ['sell', 'confirm'])
        self.assertIn('返回打怪点', poll(5, replace(closed, free=3)))
        self.assertFalse(run.active)
        self.assertEqual(send.call_count, 2)

        poll(6, closed)
        poll(7, shop)
        poll(8, confirm)
        run.interrupt(session)
        poll(9, closed)
        poll(10, shop)
        self.assertEqual([call.args[0] for call in send.call_args_list[-4:]],
                         ['sell', 'confirm', 'select', 'sell'])

    def test_vendor_dismisses_stale_sell_dialog_after_space_is_freed(self):
        from wowbuddy.engine.character_state import VendorState
        from wowbuddy.automation.vendor_run import VendorRun

        run = VendorRun()
        send = Mock(return_value=True)
        closed = VendorState(1, 0, 0, False, False, False, False, ',', 0x76, None)
        shop = replace(closed, junk=2, merchant_open=True, matched=True, hovered=True, sell_point=(2200, 4400))

        def poll(sequence, reading):
            return run.observe('session', replace(reading, sequence=sequence), sequence * 2000,
                               ready=True, arrived=True, send=send)

        poll(1, closed)
        poll(2, shop)
        partial = replace(shop, free=1, junk=1, confirming=True)
        self.assertIn('状态不符', poll(3, partial))
        freed = replace(partial, free=2, junk=0, hovered=False, sell_point=None)
        self.assertIn('其他弹窗', poll(4, replace(freed, confirming=False, popup_blocked=True)))
        poll(5, freed)
        poll(5, freed)
        poll(6, replace(freed, confirming=False))
        self.assertIn('返回打怪点', poll(7, replace(closed, free=2)))
        self.assertFalse(run.active)
        self.assertEqual([call.args[0] for call in send.call_args_list], ['sell', 'dismiss', 'close'])

    def test_vendor_reconciles_partial_sale_before_selling_remaining_junk(self):
        from wowbuddy.engine.character_state import VendorState
        from wowbuddy.automation.vendor_run import VendorRun

        run = VendorRun()
        send = Mock(return_value=True)
        closed = VendorState(1, 0, 0, False, False, False, False, ',', 0x76, None)
        shop = replace(closed, junk=3, merchant_open=True, matched=True, hovered=True, sell_point=(2200, 4400))

        def poll(sequence, now, reading):
            return run.observe('session', replace(reading, sequence=sequence), now,
                               ready=True, arrived=True, send=send)

        poll(1, 0, closed)
        poll(2, 300, shop)
        poll(3, 600, replace(shop, confirming=True))
        poll(4, 900, replace(shop, free=1))
        partial = replace(shop, free=1, junk=2)
        self.assertIn('状态不符', poll(5, 2000, replace(partial, confirming=True)))
        poll(6, 2400, partial)
        partial = replace(partial, free=2, junk=1)
        poll(7, 3000, partial)
        poll(8, 4499, partial)
        poll(8, 4500, partial)
        self.assertIn('其他弹窗', poll(9, 4500, replace(partial, popup_blocked=True)))
        poll(10, 4600, partial)
        poll(11, 6099, partial)
        self.assertEqual([call.args[0] for call in send.call_args_list], ['sell', 'confirm'])
        poll(12, 6100, partial)
        self.assertEqual([call.args[0] for call in send.call_args_list], ['sell', 'confirm', 'sell'])
        self.assertTrue(run.active)
        poll(13, 6400, replace(partial, confirming=True))
        poll(14, 6800, replace(shop, free=3, junk=0))
        self.assertIn('返回打怪点', poll(15, 7100, replace(closed, free=3)))
        self.assertFalse(run.active)
        self.assertEqual([call.args[0] for call in send.call_args_list],
                         ['sell', 'confirm', 'sell', 'confirm', 'close'])

    def test_red_equipment_routes_to_auberdine_and_waits_for_repair_before_returning(self):
        from wowbuddy.engine.character_state import VendorState
        from wowbuddy.automation.navigation import MapDestination

        def exercise(window):
            window.grind_check.setChecked(True)
            session = (123, 1, 0)
            position = NavigationState('alive', 1, 1439, 38.315, 77.167, 0, 6550, 4367, (87, 65, 68))
            character = CharacterState('alive', True, True, 'alliance', 19, 1439, '黑海岸', position.x, position.y)
            camp = MapDestination(1439, position.x, position.y, 'alive', '原营地')
            window._leveling_destination = session, character.route_key, camp
            fields = {'player_valid': 'ON', 'player_in_combat': 'OFF', 'target_valid': 'OFF', 'equipment_red': 'ON'}
            frame = OldFrame('ok', values=fields)
            tick = TickResult('suppressed', Decision(frame, fields, (), recovery_ready=True))
            result = SimpleNamespace(tick=tick, capture=SimpleNamespace(client_rect=None))
            red = VendorState(1, 8, 0, False, False, False, False, ',', 0x76, None,
                              catalog=True, repair_needed=True)

            def poll(reading, at):
                with (patch('wowbuddy.engine.character_state.decode_vendor_state',
                            side_effect=lambda *_args, repair=False: reading if repair else None),
                      patch('wowbuddy.engine.character_state.decode_navigation_state', return_value=at),
                      patch.object(window, 'monotonic_ms', return_value=reading.sequence * 2000)):
                    window._poll_vendor(session, object(), frame, result, character)

            poll(red, position)
            self.assertTrue(window._vendor_run.repair)
            _, outbound, returning = window._online_vendor
            self.assertEqual((outbound.goal.x, outbound.goal.y), (38.17, 41.14))
            self.assertIn((41.22, 74.28), outbound.approach_road)
            self.assertIn((37.5369, 42.8092), outbound.approach_road)
            self.assertEqual(returning.goal, camp)
            for _ in range(100):
                target, _ = outbound.observe(position)
                if outbound.complete:
                    break
                self.assertIsNotNone(target)
                position = replace(position, x=target.x, y=target.y, sequence=position.sequence + 1)
            self.assertTrue(outbound.complete)

            shop = replace(red, merchant_open=True, matched=True, sell_point=(2200, 4400), repair_status=3)
            with patch.object(window, '_send_travel_ui_action', return_value=True) as send:
                poll(replace(shop, sequence=2, matched=False), position)
                poll(replace(shop, sequence=3, repair_status=2, sell_point=None), position)
                send.assert_not_called()
                poll(replace(shop, sequence=4), position)
                poll(replace(shop, sequence=5, hovered=True), position)
                self.assertIs(window._leveling_trip[2], outbound)
                poll(replace(shop, sequence=6, repair_needed=False, repair_status=0), position)
                poll(replace(red, sequence=7, repair_needed=False), position)
                self.assertEqual([call.args[-2] for call in send.call_args_list], ['hover', 'repair', 'close'])
            self.assertIs(window._leveling_trip[2], returning)

        test_dev_tray.TrayTests.run_window(self, False, exercise)

    def test_quest_travel_yields_to_repair_and_recovery_and_stops_at_the_pin(self):
        from wowbuddy.engine.character_state import QuestTurnInPin
        from wowbuddy.automation.manual_routes import ManualRoute

        def exercise(window):
            window.grind_check.setChecked(True)
            session = (123, 1, 0)
            position = NavigationState('alive', 1, 52, 32, 36, 0, 3499, 2333, (87, 65, 68))
            character = CharacterState('alive', True, True, 'alliance', 16, 52, '西部荒野', 32, 36)
            pin = QuestTurnInPin(193, 52, 41.23, 56.78)
            route = ManualRoute(52, ((32, 36), (34, 40), (41.23, 56.78)))
            fields = {'player_valid': 'ON', 'player_in_combat': 'OFF'}
            frame = OldFrame('ok', values=fields)
            with (patch('wowbuddy.engine.character_state.decode_quest_turn_in_pin', return_value=pin),
                  patch('wowbuddy.engine.character_state.decode_navigation_state', return_value=position),
                  patch.object(window, '_manual_routes', return_value=(route,))):
                fields['equipment_red'] = 'ON'
                self.assertIsNone(window._observe_quest_route(session, object(), frame, character))
                fields.pop('equipment_red')
                trip = window._observe_quest_route(session, object(), frame, character)
            self.assertIsNotNone(trip)

            waiting = SimpleNamespace(tick=TickResult('no_candidates', Decision(frame, fields, ())))
            with patch.object(window, '_release_navigation_key') as stop:
                window._walk_to_quest(waiting, session, character, position, trip)
            stop.assert_called_once()
            self.assertIsNone(trip.current)

            arrived = replace(position, sequence=3, x=pin.x, y=pin.y)
            trip.observe(position)
            trip.observe(replace(position, sequence=2, x=34, y=40))
            trip.observe(arrived)
            self.assertTrue(trip.complete)
            ready = SimpleNamespace(tick=TickResult('no_candidates', Decision(frame, fields, (), recovery_ready=True)))
            with (patch.object(window, '_release_navigation_key') as stop,
                  patch.object(window, 'monotonic_ms', return_value=100)):
                window._walk_to_quest(ready, session, character, arrived, trip)
            stop.assert_called_once()
            self.assertIn('等待确认任务 NPC', window.ui.suggestions.toPlainText())
            with patch.object(window, 'monotonic_ms', return_value=15100):
                window._walk_to_quest(ready, session, character, arrived, trip)
            self.assertIsNone(window._quest_trip)
            self.assertIn('恢复练级', window.ui.suggestions.toPlainText())
            with (patch('wowbuddy.engine.character_state.decode_quest_turn_in_pin', return_value=pin),
                  patch('wowbuddy.engine.character_state.decode_navigation_state', return_value=arrived),
                  patch.object(window, 'monotonic_ms', return_value=75100) as clock):
                clock.return_value = 75099
                self.assertIsNone(window._observe_quest_route(session, object(), frame, character))
                clock.return_value = 75100
                retry = window._observe_quest_route(session, object(), frame, character)
                self.assertIsNotNone(retry)
                self.assertIsNot(retry, trip)

        test_dev_tray.TrayTests.run_window(self, False, exercise)

    def test_vendor_arrival_never_hands_off_to_camp_scanning(self):
        def exercise(window):
            window.grind_check.setChecked(True)
            window._fixed_camp_route = parse_fixed_camp('WBDPOINT1|1429|4210,6630')
            window._vendor_route = parse_fixed_camp('WBDPOINT1|1429|4250,6630')
            session = (123, 1, 0)
            window._vendor_run.session = session
            window._vendor_run.active = True
            character = CharacterState('alive', True, True, 'alliance', 18, 1429, '艾尔文森林', 42.5, 66.3)
            window._poll_leveling(session, character, True)
            trip = window._leveling_trip[2]
            window._arrival_pull = pull = Mock()
            pull.observe.return_value = None
            window._map_navigator = navigator = Mock()
            navigator.observe.return_value = None
            position = NavigationState('alive', 1, 1429, 42.5, 66.3, 0, 3471, 2315, (87, 65, 68))

            def poll(sample, target):
                fields = {'player_valid': 'ON', 'player_in_combat': 'OFF', 'target_valid': target}
                frame = OldFrame('ok', values=fields)
                tick = TickResult('no_candidates', Decision(frame, fields, (), recovery_ready=True))
                with (patch('wowbuddy.engine.character_state.decode_navigation_state', return_value=sample),
                      patch.object(window, '_observe_local_access', return_value=(None, None))):
                    window._poll_navigation(SimpleNamespace(tick=tick), session, object(), frame,
                                            replace(character, x=sample.x), None, navigate=True)

            self.assertFalse(trip.complete)
            poll(position, 'OFF')
            self.assertTrue(trip.complete)
            self.assertIsNone(window._leveling_destination)
            self.assertIsNone(pull.observe.call_args.args[1])

            # 被引离交互范围后，即使商人仍被选中，也要重新走到商人旁。
            displaced = replace(position, x=42.15, sequence=2)
            poll(displaced, 'ON')
            self.assertEqual(navigator.observe.call_args.args[2:], (displaced, trip.goal))
            self.assertIs(navigator.observe.call_args.kwargs['path'], trip)
            self.assertIsNone(pull.observe.call_args.args[1])

            with patch.object(window, '_release_navigation_key') as release:
                poll(replace(position, sequence=3), 'ON')
                release.assert_called_once()

        test_dev_tray.TrayTests.run_window(self, False, exercise)

    def test_unattended_reselects_and_clears_out_of_range_targets_without_a_bearing(self):
        def exercise(window, idle_status):
            window.grind_check.setChecked(True)
            session = (123, 1, 0)
            movement = Mock(holding_forward=False)
            movement.pulse.return_value = True
            window._map_navigator = MapNavigator(movement)
            fields = {'target_valid': 'ON', 'player_valid': 'ON', 'player_in_combat': 'OFF'}
            position = NavigationState('alive', 1, 1436, 52.8, 54.1, 0, 3500, 2300, (87, 65, 68),
                                       target_revision=10, retarget_key=9, discard_key=119)

            def poll(at, sequence, *, revision=10, valid=True, combat='OFF', sight=False, in_range=False):
                frame = OldFrame('ok', values=dict(fields, target_valid='ON' if valid else 'OFF',
                                                   player_in_combat=combat))
                candidates = (Candidate(action='spell_168', tag='增益'),) if idle_status == 'suppressed' else ()
                tick = TickResult(idle_status, Decision(frame, frame.values, candidates, recovery_ready=True,
                                                             attack_blocked_by_range=valid and not sight and not in_range,
                                                             attack_blocked_by_sight=sight), display_now_ms=at)
                sample = replace(position, sequence=sequence, target_revision=revision)
                with (patch('wowbuddy.engine.character_state.decode_navigation_state', return_value=sample),
                      patch('wowbuddy.engine.character_state.decode_target_bearing', return_value=None),
                      patch('wowbuddy.win32.windows_keys.is_foreground', return_value=True),
                      patch.object(window, 'monotonic_ms', return_value=at)):
                    window._poll_navigation(SimpleNamespace(tick=tick), session, object(), frame,
                                            None, None, navigate=True)

            for seq in range(1, 20):
                poll(seq * 500, seq, combat='ON')
            poll(10000, 20)
            poll(19000, 20)
            movement.pulse.assert_not_called()
            for index in range(1, 17):
                poll(19000 + index * 500, 20 + index)
            movement.pulse.assert_not_called()
            poll(27500, 37)
            movement.pulse.assert_called_once_with(123, 9, 35, (87, 65, 68, 9))
            for index in range(18):
                poll(28000 + index * 500, 38 + index, revision=11)
            self.assertEqual([call.args[1] for call in movement.pulse.call_args_list], [9, 119])
            poll(37000, 56, revision=12, valid=False)
            self.assertIn('游戏已确认清除无法接近的目标', window.ui.log_view.toPlainText())
            self.assertEqual(movement.pulse.call_count, 2)

            movement.pulse.reset_mock()
            poll(37500, 57, revision=13, sight=True)
            poll(37600, 57, revision=13, sight=True)
            movement.pulse.assert_not_called()
            poll(37700, 58, revision=13, sight=True)
            movement.pulse.assert_called_once_with(123, 9, 35, (87, 65, 68, 9))
            self.assertIn('游戏连续回报视线受阻', window.ui.log_view.toPlainText())
            poll(38000, 59, revision=14, in_range=True)
            poll(42000, 60, revision=14, sight=True)
            poll(42300, 61, revision=14, sight=True)
            self.assertEqual([call.args[1] for call in movement.pulse.call_args_list], [9, 119])

        for idle_status in ('no_candidates', 'suppressed'):
            with self.subTest(idle_status=idle_status):
                test_dev_tray.TrayTests.run_window(self, False, lambda window: exercise(window, idle_status))

    def test_parallel_crossings_remain_independent_through_import_planning_and_cooldown(self):
        first = 'WBDROUTE2|1426|丹莫罗|5000,7200|5100,7200\nWBDROUTE2|1432|洛克莫丹|2000,6600|2200,6700'
        second = 'WBDROUTE2|1426|丹莫罗|6000,4000|6200,4000\nWBDROUTE2|1432|洛克莫丹|2100,3500|2300,3600'
        updated = first.replace('5000,7200', '4900,7200')
        other = parse_manual_connection(second)
        near = parse_manual_connection(updated)
        session = (123, 1, 0)

        def exercise(window):
            for text in (second, first, updated):
                with patch('PySide6.QtWidgets.QInputDialog.getMultiLineText', return_value=(text, True)):
                    window._edit_manual_connection(remove=False)
            self.assertEqual(open_ini_settings(window.settings.qsettings.fileName()).manual_connections(),
                             [second, updated])
            character = CharacterState('alive', True, True, 'alliance', 18, 1426, '丹莫罗', 49, 72)
            point = {'zone': '洛克莫丹', 'name': '营地', 'x': 37.9, 'y': 87}
            position = NavigationState('alive', 1, 1426, 49, 72, 0, 1000, 1000, (87, 65, 68))
            window._plan_land_travel(session, character, point, {})
            trip = window._leveling_trip[2]
            self.assertEqual(tuple(trip.legs), (near,))
            goal = trip.goal
            for life in ('alive', 'ghost'):
                with self.subTest(life=life):
                    current = replace(position, life=life)
                    if life == 'ghost':
                        window._corpse_route(session, current, replace(goal, life=life))
                        trip = window._corpse_trip
                    self.assertEqual(tuple(trip.legs), (near,))
                    waypoint, _ = trip.observe(current)
                    self.assertIn('改走经洛克莫丹', trip.avoid_blocked_road(current, waypoint))
                    self.assertEqual(tuple(trip.legs), (other,))
                    self.assertEqual(trip.blocked_legs, {near})
                    next_point, _ = trip.observe(replace(current, sequence=2))
                    self.assertEqual((next_point.x, next_point.y), other.points[0])

            lookup = {'blocked_roads': [(1426, 1432)], 'blocked_connections': [list(near.blocked_key)]}
            window._plan_land_travel(session, character, point, lookup)
            self.assertEqual(tuple(window._leveling_trip[2].legs), (other,))
            self.assertEqual(lookup['walking_maps'], [1426, 1432])

            # 仅修改路中的坐标，进出地图的位置保持不变。
            rerouted = updated.replace('2200,6700', '2250,6750')
            with patch('PySide6.QtWidgets.QInputDialog.getMultiLineText', return_value=(rerouted, True)):
                window._edit_manual_connection(remove=False)
            revised = parse_manual_connection(rerouted)
            self.assertEqual(revised.road_key, near.road_key)
            window._plan_land_travel(session, character, point, lookup)
            self.assertEqual(tuple(window._leveling_trip[2].legs), (revised,))

            label = '丹莫罗 → 洛克莫丹 · 出口 (51.00, 72.00) · 入口 (20.00, 66.00)'
            with patch('PySide6.QtWidgets.QInputDialog.getItem', return_value=(label, True)) as dialog:
                window._edit_manual_connection(remove=True)
            self.assertEqual(len(dialog.call_args.args[3]), 2)
            self.assertEqual(window.settings.manual_connections(), [second])

        test_dev_tray.TrayTests.run_window(self, False, exercise)

    def test_redridge_graveyard_uses_a_narrow_exit_before_resuming_corpse_navigation(self):
        from wowbuddy.automation.manual_routes import GHOST_ACCESS_ROUTES, LocalAccess

        route, = (route for route in GHOST_ACCESS_ROUTES if route.map_id == 1433)
        start = NavigationState('ghost', 1, 1433, *route.points[0], 0, 2170, 1448, (87, 65, 68))

        def exercise(window):
            session = (123, 1, 0)
            frame = OldFrame('ok', values={'target_valid': 'OFF', 'player_in_combat': 'OFF'})
            result = SimpleNamespace(tick=TickResult('stopped', Decision(frame, frame.values, ())))
            navigator = window._map_navigator = Mock(blocked=False)
            navigator.observe.return_value = None
            corpse = (1433, 23.25, 79.41)
            death = DeathState('ghost', 1, None, False, corpse, popup='missing')

            def poll(position):
                with patch('wowbuddy.engine.character_state.decode_navigation_state', return_value=position):
                    window._poll_navigation(result, session, object(), frame, None, death, navigate=True)
                return navigator.observe.call_args.args[3]

            for sequence, (point, next_point) in enumerate(zip(route.points, route.points[1:]), 1):
                waypoint = poll(replace(start, sequence=sequence, x=point[0], y=point[1]))
                self.assertEqual((waypoint.x, waypoint.y), next_point)
                self.assertFalse(waypoint.allow_detour)
                self.assertIsNone(getattr(window, '_corpse_trip', None))
            poll(replace(start, sequence=len(route.points), x=route.endpoint[0], y=route.endpoint[1]))
            self.assertEqual(window._corpse_trip.goal.map_id, 1433)
            self.assertEqual((window._corpse_trip.goal.x, window._corpse_trip.goal.y), corpse[1:])
            self.assertEqual(window._observe_local_access(session, 'alive', replace(start, life='alive')),
                             (None, None))

        test_dev_tray.TrayTests.run_window(self, False, exercise)
        manual = parse_manual_route('WBDROUTE1|1433|1760,5810|1761,5791')
        access = LocalAccess((route, manual))
        waypoint, _ = access.observe(start)
        self.assertEqual((waypoint.x, waypoint.y), manual.points[0])

    def test_sentinel_hill_routes_merge_north_of_the_east_building(self):
        from wowbuddy.automation.manual_routes import GHOST_ACCESS_ROUTES, LocalAccess

        routes = tuple(route for route in GHOST_ACCESS_ROUTES if route.map_id == 1436)
        exit_start = (54.12, 51.95)
        self.assertEqual({route.points[0] for route in routes},
                         {(52.7, 52.8), (52.9, 54), (53.9, 54.4), (53.86, 52.75), (54, 52.3)})
        for route in routes:
            with self.subTest(start=route.points[0]):
                access = LocalAccess(GHOST_ACCESS_ROUTES)
                sample = NavigationState('ghost', 1, 1436, *route.points[0], 0, 3500, 2300, (87, 65, 68))
                for sequence, (point, next_point) in enumerate(zip(route.points, route.points[1:]), 1):
                    waypoint, _ = access.observe(replace(sample, sequence=sequence, x=point[0], y=point[1]))
                    self.assertEqual((waypoint.x, waypoint.y), next_point)
                    self.assertFalse(waypoint.allow_detour)
                waypoint, status = access.observe(replace(sample, sequence=len(route.points),
                                                          x=route.endpoint[0], y=route.endpoint[1]))
                self.assertIsNone(waypoint)
                self.assertIn('继续前往尸体', status)
                north_exit = route.points[route.points.index(exit_start):]
                self.assertTrue(all(x > 55.10 or y < 52.33 for x, y in north_exit))
                self.assertGreater(route.endpoint[0], 56.5)

    def test_ghost_follows_marked_access_then_continues_to_the_corpse(self):
        def exercise(window):
            window.settings.save_manual_routes(['WBDROUTE1|1436|5280,5410|5280,5390|5310,5390'], access=True)
            window.grind_check.setChecked(True)
            session = (123, 1, 0)
            frame = OldFrame('ok', values={'target_valid': 'OFF', 'player_in_combat': 'OFF'})
            result = SimpleNamespace(tick=TickResult('stopped', Decision(frame, frame.values, (), recovery_ready=False)))
            navigator = window._map_navigator = Mock()
            navigator.observe.return_value = None
            ghost = NavigationState('ghost', 1, 1436, 52.8, 54.1, 0, 3500, 2300, (87, 65, 68))
            corpse = (1433, 23.25, 79.41)
            death = DeathState('ghost', 1, None, False, corpse, popup='missing')
            camp = MapDestination(*corpse, 'alive', '练级点')
            leveling_trip = WalkingTrip(session, plan_walking_route(1436, 1433, 18, 'alive'), camp)
            window._leveling_trip = 'alliance', 18, leveling_trip

            def poll(sample, state=death):
                with patch('wowbuddy.engine.character_state.decode_navigation_state', return_value=sample):
                    window._poll_navigation(result, session, object(), frame, None, state, navigate=True)
                return navigator.observe.call_args.args[2:4]

            _, first_turn = poll(ghost)
            self.assertEqual((first_turn.x, first_turn.y, first_turn.life), (52.8, 53.9, 'ghost'))
            self.assertIsNone(getattr(window, '_corpse_trip', None))
            popup = replace(death, popup='ready', button=(500, 400))
            self.assertEqual(poll(replace(ghost, sequence=2), popup), (None, None))
            self.assertEqual(poll(replace(ghost, sequence=2), None)[1], None)
            turn = replace(ghost, sequence=3, y=53.9)
            _, exit_point = poll(turn)
            self.assertEqual((exit_point.x, exit_point.y), (53.1, 53.9))
            self.assertEqual(poll(turn)[1], exit_point)
            _, road = poll(replace(turn, sequence=4, x=53.1))
            trip = window._corpse_trip
            self.assertEqual((road.map_id, road.life), (1436, 'ghost'))
            self.assertEqual((trip.goal.map_id, trip.goal.x, trip.goal.y), corpse)
            self.assertEqual([leg.destination for leg in trip.legs], [1429, 1433])
            self.assertIs(window._leveling_trip[2], leveling_trip)
            self.assertIn('继续前往尸体', window.ui.log_view.toPlainText())

            window._corpse_trip = None
            nearby = replace(death, corpse=(1436, 52.8, 54.1))
            _, close = poll(replace(ghost, sequence=5), nearby)
            self.assertEqual((close.x, close.y, close.label), (52.8, 54.1, '尸体'))

        test_dev_tray.TrayTests.run_window(self, False, exercise)

    def test_local_access_runs_before_camp_and_does_not_skip_the_turn(self):
        self._exercise_local_access(blocked=False)

    def test_blocked_local_access_stops_without_retiring_the_camp(self):
        self._exercise_local_access(blocked=True)

    def test_revival_resumes_only_the_confirmed_living_access_segment(self):
        from wowbuddy.automation.death_recovery import AutomaticRevival

        def exercise(window):
            window.grind_check.setChecked(True)
            window.settings.save_manual_routes([
                'WBDROUTE2|1436|西部荒野|5280,5410|5280,5390|5310,5390',
                'WBDROUTE2|1436|西部荒野|4800,5010|4800,4990|4830,4990',
            ], access=True)
            session = (123, 1, 0)
            character = CharacterState('alive', True, True, 'alliance', 18, 1436, '西部荒野', 52.8, 54.1)
            camp = window._set_local_camp(session, character, {'x': 51.66, 'y': 77.21, 'name': '匕首岭'})
            frame = OldFrame('ok', values={'target_valid': 'OFF', 'player_in_combat': 'OFF'})
            movement = Mock(holding_forward=False)
            navigator = window._map_navigator = MapNavigator(movement)
            window._automatic_revival = AutomaticRevival(Mock())

            def poll(sequence, x, y, *, life='alive', ready=True):
                state = DeathState(life, sequence, None, False, (1436, 53, 54.1) if life == 'ghost' else None)
                position = NavigationState(life, sequence, 1436, x, y, 0, 3500, 2300, (87, 65, 68))
                result = SimpleNamespace(tick=TickResult('stopped', Decision(frame, frame.values, (), recovery_ready=ready)))
                window._poll_revival(session, state, None, recovery_ready=ready)
                with patch('wowbuddy.engine.character_state.decode_navigation_state', return_value=position):
                    window._poll_navigation(result, session, object(), frame,
                                            character if life == 'alive' else None, state, navigate=True)
                return navigator._target[1]

            self.assertEqual(poll(1, 52.8, 54.1).label, '起点接入路点 2')
            exit_point = poll(2, 52.8, 53.9)
            self.assertEqual(exit_point.label, '起点接入路点 3')
            poll(3, 53, 54.1, life='dead', ready=False)
            ghost_point = poll(4, 48, 50.1, life='ghost', ready=False)
            self.assertEqual((ghost_point.life, ghost_point.label), ('ghost', '起点接入路点 2'))
            movement.reset_mock()
            poll(5, 53, 54.1, ready=False)
            self.assertIsNone(poll(6, 53, 54.1))
            self.assertIn('等待靠近已走到的路段', window.ui.log_view.toPlainText())
            movement.pulse.assert_not_called()
            movement.hold_forward.assert_not_called()
            self.assertEqual(poll(7, 52.95, 53.9), exit_point)
            self.assertEqual(poll(8, 53.1, 53.9), camp)
            self.assertEqual(window._leveling_destination, (session, character.route_key, camp))

            poll(9, 53.1, 53.9, life='dead', ready=False)
            self.assertEqual(poll(10, 52.8, 54.1).label, '起点接入路点 2')
            self.assertEqual(poll(11, 52.8, 53.9), exit_point)
            poll(12, 53, 54.1, life='dead', ready=False)
            alternate = poll(13, 48, 50.1)
            self.assertEqual((alternate.life, alternate.x, alternate.y), ('alive', 48, 49.9))

        test_dev_tray.TrayTests.run_window(self, False, exercise)

    def _exercise_local_access(self, *, blocked):
        def exercise(window):
            text = 'WBDROUTE2|1436|西部荒野|5280,5410|5280,5390|5310,5390'
            with patch('PySide6.QtWidgets.QInputDialog.getText', return_value=(text, True)):
                window._import_manual_route(access=True)
            reopened = open_ini_settings(window.settings.qsettings.fileName())
            self.assertEqual(reopened.manual_routes(access=True), [text])
            self.assertEqual(reopened.manual_routes(), [])
            window.grind_check.setChecked(True)
            session = (123, 1, 0)
            character = CharacterState('alive', True, True, 'alliance', 18, 1436, '西部荒野', 52.8, 54.1)
            goal = window._set_local_camp(session, character, {'x': 51.66, 'y': 77.21, 'name': '匕首岭'})
            frame = OldFrame('ok', values={'target_valid': 'OFF', 'player_in_combat': 'OFF'})
            movement = Mock(holding_forward=False)
            movement.pulse.return_value = True
            navigator = window._map_navigator = MapNavigator(movement)
            position = NavigationState('alive', 1, 1436, 52.8, 54.1, 0, 3500, 2300, (87, 65, 68))

            def poll(sequence, *, ready=True, **changes):
                result = SimpleNamespace(tick=TickResult('stopped', Decision(frame, frame.values, (), recovery_ready=ready)))
                sample = replace(position, sequence=sequence, **changes)
                with patch('wowbuddy.engine.character_state.decode_navigation_state', return_value=sample):
                    window._poll_navigation(result, session, object(), frame, character, None, navigate=True)
                return navigator._target[1]

            self.assertEqual(poll(1, ready=False), goal)
            movement.pulse.assert_not_called()
            first_turn = poll(2)
            self.assertEqual((first_turn.x, first_turn.y), (52.8, 53.9))
            self.assertEqual(poll(2), first_turn)
            if blocked:
                for sequence in range(3, 9):
                    poll(sequence)
                self.assertTrue(navigator.blocked)
                self.assertIn('起点接入路线受阻', window.ui.log_view.toPlainText())
                self.assertNotIn('尝试绕行', window.ui.log_view.toPlainText())
                pulses = movement.pulse.call_count
                poll(9)
                self.assertEqual(movement.pulse.call_count, pulses)
                self.assertEqual(window._leveling_destination, (session, character.route_key, goal))
            else:
                self.assertEqual(poll(3, map_id=1429), first_turn)
                self.assertEqual(poll(4, x=53.1, y=53.9), first_turn)
                exit_point = poll(5, y=53.9)
                self.assertEqual((exit_point.x, exit_point.y), (53.1, 53.9))
                self.assertEqual(poll(6, x=53.1, y=53.9), goal)
                self.assertIn('继续原来的练级计划', window.ui.log_view.toPlainText())

        test_dev_tray.TrayTests.run_window(self, False, exercise)

    def test_online_horde_stage_uses_marked_camps_and_retires_failed_points(self):
        from test_leveling_route import leg, stage

        routes = ('WBDROUTE2|1413|贫瘠之地|3800,4000|4000,4000',
                  'WBDROUTE2|1413|贫瘠之地|4600,4000|4800,4000')
        guide = stage(1, '12–17', leg('贫瘠之地', 'the-barrens', [('十字路口', '52.3,31.9')]))

        def submit(fn, *args, **options):
            future = Future()
            try:
                future.set_result(fn(*args, **options, fetch=lambda _: guide))
            except ValueError as error:
                future.set_exception(error)
            return future

        def exercise(window):
            session = (123, 1, 0)
            character = CharacterState('alive', True, True, 'horde', 15, 1413, '贫瘠之地', 39, 40)
            window.grind_check.setChecked(True)
            for text in routes:
                with patch('PySide6.QtWidgets.QInputDialog.getText', return_value=(text, True)):
                    window._import_manual_route()
            window._leveling_planner = AutomaticLeveling(submit)

            with patch.object(window, 'monotonic_ms', return_value=1000) as time:
                window._poll_leveling(session, character, True)
                time.return_value = 1300
                window._poll_leveling(session, character, True)
                window._poll_leveling(session, character, True)
                self.assertIn('自定刷怪点 (40.00, 40.00)', window.ui.log_view.toPlainText())
                for index, text in enumerate(routes, 1):
                    trip = window._leveling_trip[2]
                    marked = parse_manual_route(text)
                    self.assertEqual((trip.goal.x, trip.goal.y), marked.endpoint)
                    position = NavigationState('alive', 1, 1413, *marked.points[0], 0, 1000, 1000, (87, 65, 68))
                    trip.observe(position)
                    self.assertEqual(trip.observe(replace(position, x=marked.endpoint[0], sequence=2))[0], trip.goal)
                    time.return_value = 1300 + index * 100
                    window._advance_grind_camp(session, character, trip.goal, '当前刷怪区未选到怪物')
                self.assertIsNone(window._leveling_destination)
                self.assertIsNone(window._leveling_trip)
                window._poll_leveling(session, character, True)
                time.return_value = 1800
                window._poll_leveling(session, character, True)
                window._poll_leveling(session, character, True)
                self.assertIn('自定营地暂不可达或正在等待重试', window.ui.log_view.toPlainText())

        test_dev_tray.TrayTests.run_window(self, False, exercise)

    def test_same_map_camp_requeries_when_the_character_changes_shores(self):
        from test_leveling_route import GUIDE

        zone_path = '/zh/zones/eastern-kingdoms/loch-modan/'
        markers = ('<section id="route-alliance">' + ''.join(
            f'<a class="route-coords" href="{zone_path}?pin={pin}#map">营地</a>'
            for pin in ('37.5,90.1', '37.9,87.0', '65.4,39.6')) + '</section>')

        def submit(fn, *args, **options):
            future = Future()
            future.set_result(fn(*args, **options, fetch=lambda url: markers if url.endswith(zone_path) else GUIDE))
            return future

        def exercise(window, west_y):
            window.grind_check.setChecked(True)
            request = Mock(side_effect=submit)
            window._leveling_planner = AutomaticLeveling(request)
            session = (123, 1, 0)
            west = CharacterState('alive', True, True, 'alliance', 16, 1432, '洛克莫丹', 37.9, west_y)
            east = replace(west, x=68.0, y=49.38)

            def lookup(character, clock, now):
                clock.return_value = now
                window._poll_leveling(session, character, True)
                clock.return_value += 300
                window._poll_leveling(session, character, True)
                window._poll_leveling(session, character, True)

            def goal():
                active = getattr(window, '_leveling_trip', None)
                return active[2].goal if active else window._leveling_destination[2]

            with patch.object(window, 'monotonic_ms', return_value=1000) as clock:
                lookup(west, clock, 1000)
                original = goal()
                self.assertLess(original.x, 41.5)
                self.assertEqual(bool(window._leveling_trip), west_y < 80)
                lookup(replace(west, x=35), clock, 1500)
                self.assertEqual(goal(), original)
                self.assertEqual(request.call_count, 1)
                clock.return_value = 2000
                window._poll_leveling(session, east, True)
                self.assertIsNone(window._leveling_trip)
                self.assertIsNone(window._leveling_destination)
                lookup(west, clock, 2050)
                self.assertEqual(goal(), original)
                lookup(east, clock, 2500)
                self.assertEqual((goal().x, goal().y), (65.4, 39.6))
                self.assertEqual(request.call_count, 3)
                self.assertTrue(all(not call.kwargs['excluded'] for call in request.call_args_list))

                route = f'WBDROUTE2|1432|洛克莫丹|6800,4938|{round(original.x*100)},{round(original.y*100)}'
                window.settings.save_manual_routes([route])
                window._set_local_camp(session, west, {'x': original.x, 'y': original.y, 'name': original.label})
                manual = window._leveling_trip[2]
                self.assertTrue(manual.manual_camp_pending)
                lookup(east, clock, 3100)
                self.assertIs(window._leveling_trip[2], manual)
                self.assertEqual(request.call_count, 3)

        for west_y in (49.38, 87.0):
            with self.subTest(west_y=west_y):
                test_dev_tray.TrayTests.run_window(self, False, lambda window: exercise(window, west_y))

    def test_displaced_cross_map_plan_requeries_and_uses_a_local_marked_camp(self):
        from test_leveling_route import leg, stage

        loch = '/zh/zones/eastern-kingdoms/loch-modan/'
        wetlands = '/zh/zones/eastern-kingdoms/wetlands/'
        guide = (stage(1, '18–20', leg('洛克莫丹', 'loch-modan', [('塞尔萨玛', '35,48')]))
                 + stage(2, '20–24', leg('湿地', 'wetlands', [('丹奥加兹', '55.8,91.9')])))
        pages = {'/zh/leveling/alliance/': guide,
                 wetlands: f'<section id="route-alliance"><a class="route-coords" '
                           f'href="{wetlands}?pin=60.51,63.71#map">营地</a></section>', loch: ''}

        def submit(fn, *args, **options):
            future = Future()
            future.set_result(fn(*args, **options, fetch=lambda url: pages[url.removeprefix('https://wowhandbook.com')]))
            return future

        def exercise(window):
            window.grind_check.setChecked(True)
            window.settings.save_manual_routes(['WBDROUTE2|1432|洛克莫丹|7800,3500|7850,3520'])
            window._leveling_planner = AutomaticLeveling(submit)
            session = (123, 1, 0)
            character = CharacterState('alive', True, True, 'alliance', 20, 1432, '洛克莫丹', 65.4, 39.6)
            frame = OldFrame('ok', values={'target_valid': 'OFF', 'player_in_combat': 'OFF'})
            tick = TickResult('no_candidates', Decision(frame, frame.values, (), recovery_ready=True))
            movement = Mock(holding_forward=False)
            window._map_navigator = MapNavigator(movement)

            def lookup(character, clock, start):
                clock.return_value = start
                window._poll_leveling(session, character, True)
                clock.return_value += 300
                window._poll_leveling(session, character, True)
                window._poll_leveling(session, character, True)

            def navigate(character, sequence):
                position = NavigationState('alive', sequence, 1432, character.x, character.y,
                                           0, 2758, 1840, (87, 65, 68))
                with patch('wowbuddy.engine.character_state.decode_navigation_state', return_value=position):
                    window._poll_navigation(SimpleNamespace(tick=tick), session, object(), frame,
                                            character, None, navigate=True)

            with patch.object(window, 'monotonic_ms', return_value=1000) as clock:
                lookup(character, clock, 1000)
                original = window._leveling_trip[2]
                self.assertEqual(original.goal.map_id, 1437)
                navigate(character, 1)
                displaced = replace(character, x=78, y=35)
                navigate(displaced, 2)
                navigate(displaced, 2)
                self.assertIs(window._leveling_trip[2], original)
                navigate(displaced, 3)
                self.assertIsNone(window._leveling_trip)
                self.assertFalse(original.blocked_legs)
                lookup(displaced, clock, 1600)
                fallback = window._leveling_trip[2]
                self.assertFalse(fallback.legs)
                self.assertEqual((fallback.goal.map_id, fallback.goal.x, fallback.goal.y), (1432, 78.5, 35.2))
                navigate(displaced, 4)
                self.assertIn('手动路点', fallback.current.label)

        test_dev_tray.TrayTests.run_window(self, False, exercise)

    def test_imported_cross_map_connection_is_used_by_automatic_lookup(self):
        from test_leveling_route import leg, stage

        text = 'WBDROUTE2|1426|丹莫罗|5000,7200|5100,7200\nWBDROUTE2|1432|洛克莫丹|2000,6600|2200,6700'
        connection = parse_manual_connection(text)
        camp_page = '/zh/zones/eastern-kingdoms/loch-modan/'
        guide = stage(1, '15–19', leg('洛克莫丹', 'loch-modan', [('塞尔萨玛', '35,48')]))
        markers = (f'<section id="route-alliance"><a class="route-coords" '
                   f'href="{camp_page}?pin=37.9,87.0#map">营地</a></section>')

        def submit(fn, *args, **options):
            future = Future()
            future.set_result(fn(*args, **options, fetch=lambda url: markers if url.endswith(camp_page) else guide))
            return future

        def exercise(window):
            with patch('PySide6.QtWidgets.QInputDialog.getMultiLineText', return_value=(text, True)):
                window._edit_manual_connection(remove=False)
            reopened = open_ini_settings(window.settings.qsettings.fileName())
            self.assertEqual(reopened.manual_connections(), [text])
            self.assertIn('丹莫罗 → 洛克莫丹', window.ui.log_view.toPlainText())
            self.assertFalse(plan_walking_route(1426, 1432, 16, 'alive')[0].manual)
            self.assertFalse(plan_walking_route(1432, 1426, 16, 'alive', connections=(connection,))[0].manual)
            conflicting = text.replace('1426|丹莫罗', '999|丹莫罗')
            with patch('PySide6.QtWidgets.QInputDialog.getMultiLineText', return_value=(conflicting, True)):
                window._edit_manual_connection(remove=False)
            self.assertEqual(window.settings.manual_connections(), [text])
            self.assertIn('对应多个地图编号', window.ui.log_view.toPlainText())
            window.grind_check.setChecked(True)
            session = (123, 1, 0)
            character = CharacterState('alive', True, True, 'alliance', 16, 1426, '丹莫罗', 51, 72)
            window._leveling_planner = AutomaticLeveling(submit)
            with patch.object(window, 'monotonic_ms', return_value=1000) as time:
                window._poll_leveling(session, character, True)
                time.return_value = 1300
                window._poll_leveling(session, character, True)
                window._poll_leveling(session, character, True)
            trip = window._leveling_trip[2]
            self.assertEqual(tuple(trip.legs), (connection,))
            self.assertEqual((trip.goal.map_id, trip.goal.x, trip.goal.y), (1432, 37.9, 87))
            position = NavigationState('alive', 1, 1426, 51, 72, 0, 1000, 1000, (87, 65, 68))
            first, _ = trip.observe(position)
            self.assertEqual((first.x, first.y), connection.points[0])
            exit_point, _ = trip.observe(replace(position, x=50, sequence=2))
            self.assertEqual((exit_point.x, exit_point.y), connection.points[1])
            arrived = replace(position, map_id=1432, x=22, y=67, sequence=3)
            self.assertEqual(trip.observe(arrived), (None, None))
            self.assertEqual(trip.observe(arrived), (None, None))
            self.assertIn('已确认进入', trip.observe(replace(arrived, sequence=4))[1])
            entry, _ = trip.observe(replace(arrived, sequence=5))
            self.assertEqual((entry.x, entry.y), connection.arrival_road[0])
            second, _ = trip.observe(replace(arrived, x=20, y=66, sequence=6))
            self.assertEqual((second.x, second.y), connection.arrival_road[1])
            self.assertEqual(trip.observe(replace(arrived, sequence=7))[0], trip.goal)
            self.assertTrue(trip.complete)

            corpse = replace(trip.goal, life='ghost')
            window._corpse_route(session, replace(position, life='ghost'), corpse)
            self.assertEqual(tuple(window._corpse_trip.legs), (connection,))
            departure, arrival = text.splitlines()
            reverse_text = arrival + '\n' + departure
            window.settings.save_manual_connections([text, reverse_text])
            other_side = replace(character, map_id=1432, zone='洛克莫丹', x=22, y=67)
            window._plan_land_travel(session, other_side,
                                     {'zone': '丹莫罗', 'name': '攻略地点', 'x': 49, 'y': 70}, {})
            reverse_trip = window._leveling_trip[2]
            self.assertEqual((reverse_trip.goal.map_id, reverse_trip.catalog_zone), (1426, '丹莫罗'))
            self.assertEqual(tuple(reverse_trip.legs), (parse_manual_connection(reverse_text),))
            window.settings.save_manual_connections([text])
            with patch('PySide6.QtWidgets.QInputDialog.getItem', return_value=('丹莫罗 → 洛克莫丹', True)):
                window._edit_manual_connection(remove=True)
            self.assertEqual(window.settings.manual_connections(), [])

        test_dev_tray.TrayTests.run_window(self, False, exercise)

    def test_intermediate_connection_finishes_arrival_before_next_departure(self):
        first = parse_manual_connection('WBDROUTE1|1432|5000,7200|5100,7200\nWBDROUTE2|1426|丹莫罗|2000,6600|2200,6700')
        second = parse_manual_connection('WBDROUTE2|1426|丹莫罗|2500,6600|2600,6700\nWBDROUTE2|1455|铁炉堡|2000,6600|2200,6700')
        connections = (first, second)
        goal = MapDestination(1455, 58, 60, 'alive', '铁炉堡')
        route = plan_walking_route(1432, goal.map_id, 20, 'alive', connections=connections)
        self.assertEqual(route, connections)
        trip = WalkingTrip((123, 1), route, goal, level=20, connections=connections)
        arrived = NavigationState('alive', 1, 1426, 20, 66, 0, 1000, 1000, (87, 65, 68))
        self.assertEqual(trip.observe(arrived), (None, None))
        self.assertIn('已确认进入丹莫罗', trip.observe(replace(arrived, sequence=2))[1])
        waypoint, _ = trip.observe(replace(arrived, sequence=3))
        self.assertEqual((waypoint.x, waypoint.y), first.arrival_road[1])
        done = replace(arrived, x=22, y=67, sequence=4)
        self.assertIn('已走完换图接入道路', trip.observe(done)[1])
        waypoint, _ = trip.observe(replace(done, sequence=5))
        self.assertEqual((waypoint.x, waypoint.y), second.points[0])

    def test_blocked_arrival_uses_another_exit_from_the_confirmed_map(self):
        first = parse_manual_connection('WBDROUTE1|1432|5000,7200|5100,7200\nWBDROUTE2|1426|丹莫罗|2000,6600|2200,6700')
        second = parse_manual_connection('WBDROUTE2|1426|丹莫罗|2500,6600|2600,6700\nWBDROUTE2|1455|铁炉堡|2000,6600|2200,6700')
        connections = (first, second)
        for life in ('alive', 'ghost'):
            for final_map in (False, True):
                with self.subTest(life=life, final_map=final_map):
                    destination = first.destination if final_map else second.destination
                    goal = MapDestination(destination, 58, 60, life, '目的地')
                    route = plan_walking_route(first.source, destination, 20, life, connections=connections)
                    trip = WalkingTrip((123, 1), route, goal, level=20, connections=connections)
                    arrived = NavigationState(life, 1, first.destination, 20, 66, 0, 1000, 1000, (87, 65, 68))
                    self.assertEqual(trip.observe(arrived), (None, None))
                    self.assertIn('已确认进入丹莫罗', trip.observe(replace(arrived, sequence=2))[1])
                    waypoint, _ = trip.observe(replace(arrived, sequence=3))
                    self.assertEqual((waypoint.x, waypoint.y), first.arrival_road[1])
                    self.assertIsNone(trip.avoid_blocked_road(replace(arrived, map_id=first.source), waypoint))
                    status = trip.avoid_blocked_road(arrived, waypoint)
                    self.assertIn('到达路段受阻', status)
                    self.assertEqual(trip.goal, goal)
                    self.assertEqual(trip.blocked_legs, {first})
                    if final_map:
                        self.assertTrue(trip.travel_exhausted)
                        self.assertEqual(trip.observe(replace(arrived, sequence=4)), (waypoint, None))
                    else:
                        self.assertIn('改走经铁炉堡', status)
                        self.assertFalse(trip.travel_exhausted)
                        self.assertEqual(tuple(trip.legs), (second,))
                        next_waypoint, _ = trip.observe(replace(arrived, sequence=4))
                        self.assertEqual((next_waypoint.x, next_waypoint.y), second.points[0])

    def test_loch_east_corpse_revival_crosses_the_dam_from_graveyard_or_wetlands(self):
        from wowbuddy.win32.capture import Rect
        from wowbuddy.automation.death_recovery import AutomaticRevival

        def exercise(window):
            window.grind_check.setChecked(True)
            navigator = window._map_navigator = Mock(blocked=False)
            mouse = Mock()
            window._automatic_revival = AutomaticRevival(mouse)
            rect = Rect(0, 0, 1000, 800)
            fields = {'player_in_combat': 'OFF', 'player_valid': 'OFF', 'target_valid': 'OFF'}
            frame = OldFrame('ok', values=fields)
            result = SimpleNamespace(tick=TickResult('stopped', Decision(frame, fields, ())))
            west = NavigationState('ghost', 1, 1432, 33.83, 46.79, 0, 2758, 1840, (87, 65, 68))
            wetlands = replace(west, map_id=1437, x=60.51, y=63.71, width=4135, height=2756)
            cases = ((west, (64.65, 44.86)), (wetlands, (67.869, 59.098)))
            for session_id, (start, coordinates) in enumerate(cases, 1):
                with self.subTest(start_map=start.map_id):
                    session = (123, session_id, 0)
                    goal = (1432, *coordinates)
                    time = 10000
                    mouse.reset_mock()
                    dead = DeathState('dead', 1, (5000, 5000), False, goal, popup='ready')
                    ghost = DeathState('ghost', 3, None, False, goal, popup='missing')
                    with patch.object(window, 'monotonic_ms', side_effect=lambda: time):
                        window._poll_revival(session, dead, rect)
                        mouse.click.assert_not_called()
                        window._poll_revival(session, replace(dead, sequence=2, hovered=True), rect)
                        mouse.click.assert_called_once_with(123, (500, 400))

                        def poll(sample, state=ghost):
                            nonlocal time
                            time += 250
                            window._poll_revival(session, state, rect, position=sample)
                            with patch('wowbuddy.engine.character_state.decode_navigation_state', return_value=sample):
                                window._poll_navigation(result, session, object(), frame, None, state, navigate=True)
                            return navigator.observe.call_args.args[3]

                        position = start
                        deck = []
                        crossed = False
                        for _ in range(110):
                            waypoint = poll(position)
                            trip = window._corpse_trip
                            if waypoint is None:
                                position = replace(position, sequence=position.sequence + 1)
                                continue
                            if trip.legs and (waypoint.x, waypoint.y) == trip.legs[0].points[-1]:
                                self.assertEqual(waypoint.map_id, 1437)
                                position = replace(west, sequence=position.sequence + 1, x=25.34, y=2.8)
                                self.assertIsNone(poll(position))
                                self.assertIsNone(poll(position))
                                self.assertEqual(len(trip.legs), 1)
                                position = replace(position, sequence=position.sequence + 1)
                                self.assertIsNone(poll(position))
                                self.assertFalse(trip.legs)
                                crossed = True
                                continue
                            if waypoint.map_id == 1432 and not waypoint.allow_detour:
                                self.assertEqual(waypoint.radius, 2)
                                deck.append(waypoint.x)
                            position = replace(position, sequence=position.sequence + 1,
                                               x=waypoint.x, y=waypoint.y)
                            if (waypoint.map_id, waypoint.x, waypoint.y) == goal:
                                break
                        else:
                            self.fail('未走到原尸体位置')
                        self.assertEqual(crossed, start.map_id == 1437)
                        self.assertEqual(len(deck), 35)
                        self.assertEqual(deck, sorted(deck))
                        mouse.click.assert_called_once()
                        popup = replace(ghost, sequence=4, popup='ready', button=(5000, 5000))
                        self.assertIsNone(poll(position, popup))
                        mouse.click.assert_called_once()
                        self.assertIsNone(poll(position, replace(popup, sequence=5, hovered=True)))
                        self.assertEqual(mouse.click.call_count, 2)
                        window._poll_revival(session, DeathState('alive', 6, None, False, None), rect)
                        self.assertEqual(window._post_revival_session, session)
                        self.assertIn('游戏已确认角色复活', window.ui.log_view.toPlainText())

        test_dev_tray.TrayTests.run_window(self, False, exercise)

    def test_ghost_replanning_to_east_shore_requires_a_user_connection(self):
        connection = 'WBDROUTE1|1437|7700,6000|7800,6000\nWBDROUTE1|1432|8000,6000|8200,6200'

        def exercise(window):
            goal = MapDestination(1432, 82, 64, 'ghost', '尸体')
            on_map = NavigationState('ghost', 1, 1432, 80, 62, 0, 1000, 800, (87, 65, 68))
            off_map = replace(on_map, map_id=1437, x=76, y=60, sequence=2)
            for session_id, roads in enumerate(([], [connection]), 1):
                with self.subTest(user_connection=bool(roads)):
                    session = (123, session_id, 0)
                    window.settings.save_manual_connections(roads)
                    self.assertEqual(window._corpse_route(session, on_map, goal), goal)
                    self.assertIsNone(window._corpse_route(session, off_map, goal))
                    self.assertIsNone(window._corpse_route(session, replace(off_map, sequence=3), goal))
                    waypoint = window._corpse_route(session, replace(off_map, sequence=4), goal)
                    trip = window._corpse_trip
                    if roads:
                        self.assertEqual(tuple(trip.legs), (parse_manual_connection(connection),))
                        self.assertEqual((waypoint.map_id, waypoint.x, waypoint.y), (1437, 77, 60))
                    else:
                        self.assertTrue(trip.travel_exhausted)
                        self.assertIsNone(waypoint)

        test_dev_tray.TrayTests.run_window(self, False, exercise)

    def test_revival_reenters_manual_road_at_last_confirmed_point(self):
        points = ((80.7, 61.5), (80, 65.7), (79, 67.5), (77.3, 69.8))
        goal = MapDestination(1432, *points[-1], 'alive', '山鹫区')
        catalog_goal = replace(goal, x=76.8, y=70.5)
        trip = WalkingTrip((123, 1, 0), (), goal, camp_road=points, catalog_goal=catalog_goal)

        def sample(sequence, point, life='alive'):
            return NavigationState(life, sequence, goal.map_id, *point, 0, 2758, 1840, (87, 65, 68))

        def expect(sequence, position, expected):
            waypoint, _ = trip.observe(sample(sequence, position))
            self.assertEqual((waypoint.x, waypoint.y), expected)

        expect(1, points[0], points[1])
        expect(2, points[1], points[2])
        self.assertEqual(trip.observe(sample(3, points[2], 'ghost')), (None, None))
        trip.resume_after_revival()
        # 即使复活位置离第三个点更近，也先接回最后确认通过的第二点。
        expect(4, points[2], points[1])
        # 返回第二点途中再次死亡，检查点仍然是第二点。
        self.assertEqual(trip.observe(sample(5, points[2], 'ghost')), (None, None))
        trip.resume_after_revival()
        expect(6, points[2], points[1])
        expect(7, points[1], points[2])
        expect(8, points[2], points[3])
        destination, status = trip.observe(sample(9, points[3]))
        self.assertEqual(destination, goal)
        self.assertEqual(trip.catalog_goal, catalog_goal)
        self.assertIn('将在这里寻怪', status)
        self.assertTrue(trip.complete)

    def test_unexpected_arrival_in_final_map_discards_the_old_entrance_road(self):
        connection = parse_manual_connection(
            'WBDROUTE2|1426|丹莫罗|5000,7200|5100,7200\nWBDROUTE1|1432|2000,6600|2200,6700')
        legs = plan_walking_route(1426, 1437, 22, 'alive', connections=(connection,))
        self.assertEqual([leg.destination for leg in legs], [1432, 1437])
        catalog = MapDestination(1437, 58.1, 52.2, 'alive', '湿地刷怪区')
        marked = ((47.1, 46.3), (52.5, 49.1), (58, 52))
        arrived = NavigationState('alive', 2, 1437, 45, 46, 0, 4000, 2800, (87, 65, 68))
        for manual in (False, True):
            with self.subTest(manual=manual):
                goal = replace(catalog, x=58, y=52) if manual else catalog
                trip = WalkingTrip((123, 1), legs, goal, level=22, connections=(connection,),
                                   camp_road=marked if manual else (), catalog_goal=catalog if manual else None)
                self.assertIn('非预期地图', trip.observe(arrived)[1])
                self.assertEqual(trip.observe(arrived), (None, None))
                target, status = trip.observe(replace(arrived, sequence=3))
                self.assertIn('重规划陆路', status)
                if manual:
                    self.assertIsNone(target)
                    approach = ((arrived.x, arrived.y), *marked[:-1])
                    for sequence, ((x, y), point) in enumerate(zip(approach, marked), 4):
                        target, _ = trip.observe(replace(arrived, sequence=sequence, x=x, y=y))
                        self.assertEqual((target.x, target.y), point)
                    target, _ = trip.observe(replace(arrived, sequence=7, x=goal.x, y=goal.y))
                self.assertEqual(target, goal)
                self.assertEqual(trip.catalog_goal, catalog)
                self.assertTrue(trip.complete)

    def test_world_map_export_is_imported_and_followed_in_order(self):
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.execute("""
          local function noop() end
          local methods = {
            SetScript = function(self, event, handler) self[event] = handler end,
            SetText = function(self, text)
              self.text = text
              if self.kind == "Button" then controls[text] = self end
            end,
            CreateFontString = function() return CreateFrame("FontString") end,
          }
          controls = {}
          function CreateFrame(kind)
            local frame = setmetatable({ kind = kind }, { __index = function(_, name) return methods[name] or noop end })
            if kind == "EditBox" then edit = frame end
            return frame
          end
          mapID = 1432
          WorldMapFrame = {
            GetMapID = function() return mapID end,
            AddCanvasClickHandler = function(_, handler) onMapClick = handler end,
          }
          C_Map = {
            GetMapInfo = function() return { mapType = 3, name = "洛克莫丹" } end,
            GetBestMapForUnit = function() return 1432 end,
            GetPlayerMapPosition = function()
              return { GetXY = function() return .800, .657 end }
            end,
          }
          WowBuddyDevDB = {}
          function add(x, y, pinMap)
            controls["加入路点"].OnClick()
            assert(not onMapClick(WorldMapFrame, "RightButton", x, y))
            local previous = mapID
            mapID = pinMap or mapID
            local added = onMapClick(WorldMapFrame, "LeftButton", x, y)
            mapID = previous
            return added
          end
        """)
        lua.execute((ROOT / 'addon/WowBuddyDev/ManualRoutes.lua').read_text('utf8'))
        lua.execute("""
          assert(not onMapClick(WorldMapFrame, "LeftButton", .5, .5))
          controls["加入路点"].OnClick()
          controls["加入路点"].OnClick()
          assert(not onMapClick(WorldMapFrame, "LeftButton", .5, .5))
          assert(add(.807, .615))
          assert(add(.807, .615))
          assert(not add(.803, .629, 1433))
          assert(add(-1, .7))
          assert(add(.801, .655))
          controls["撤销路点"].OnClick()
          mapID = 1433
          controls["加入当前位置"].OnClick()
          mapID = 1432
          controls["加入当前位置"].OnClick()
          assert(add(.773, .698))
          controls["复制路线"].OnClick()
        """)
        text = lua.globals().edit.text
        self.assertEqual(text, 'WBDROUTE2|1432|洛克莫丹|8070,6150|8000,6570|7730,6980')
        lua.execute('controls["复制打怪点"].OnClick()')
        self.assertEqual(lua.globals().edit.text, 'WBDPOINT1|1432|7730,6980')

        def exercise(window):
            with patch('PySide6.QtWidgets.QInputDialog.getText', return_value=(text, True)):
                window._import_manual_route()
            self.assertEqual(window.settings.manual_routes(), [text])
            self.assertIn('已导入地图 1432 的 3 个路点', window.ui.log_view.toPlainText())
            character = CharacterState('alive', True, True, 'alliance', 16, 1432, '洛克莫丹', 80.1, 65.7)
            session = (123, 1, 0)
            goal = window._set_local_camp(session, character, {'name': '山鹫区', 'x': 76.8, 'y': 70.5})
            trip = window._leveling_trip[2]
            position = NavigationState('alive', 1, 1432, character.x, character.y, 0, 2758, 1840, (87, 65, 68))
            target, _ = trip.observe(position)
            self.assertEqual((target.x, target.y), (80.7, 61.5))
            for sequence, (x, y) in enumerate(parse_manual_route(text).points, 2):
                target, status = trip.observe(replace(position, x=x, y=y, sequence=sequence))
            self.assertEqual(target, goal)
            self.assertEqual((target.x, target.y), (77.3, 69.8))
            self.assertIn('将在这里寻怪', status)
            self.assertTrue(trip.complete)
            marked_end = replace(position, x=goal.x, y=goal.y, idle_key_index=1)
            original = MapDestination(1432, 76.8, 70.5, 'alive', '山鹫区')
            self.assertFalse(original.contains(marked_end))
            fields = {'ttd': str(PACKET_BASE + 8192 + 1), 'target_valid': 'OFF',
                      'player_valid': 'ON', 'player_in_combat': 'OFF'}
            frame = OldFrame('ok', values=fields)
            tick = TickResult('stopped', Decision(frame, fields, (), recovery_ready=True),
                              display_now_ms=10_000)
            dispatcher = Mock()
            dispatcher.state.last_sent_ms = 0
            pull = ArrivalPull(dispatcher, Mock())
            self.assertIsNone(pull.observe(session, goal, marked_end, tick, 10_000, 100))
            self.assertIn('已发出', pull.observe(session, goal, replace(marked_end, sequence=2),
                                                  tick, 10_250, 100))
            dispatcher.dispatch.assert_called_once()
            window._leveling_planner = Mock()
            window._leveling_destination = session, character.route_key, goal
            window._advance_grind_camp(session, character, goal, '测试无目标')
            self.assertEqual(window._leveling_planner.retire_camp.call_args.args[2], original)
            with patch('PySide6.QtWidgets.QInputDialog.getItem',
                       side_effect=lambda *args: (args[3][0], True)):
                window._remove_manual_route()
            self.assertEqual(window.settings.manual_routes(), [])

        test_dev_tray.TrayTests.run_window(self, False, exercise)

    def test_cross_zone_lookup_uses_the_tunnel_before_the_manual_road(self):
        def exercise(window):
            window.settings.save_manual_routes(['WBDROUTE1|1437|5480,6990|5800,6650|6100,6350'])
            source = CharacterState('alive', True, True, 'alliance', 20, 1432, '洛克莫丹', 25.56, 10.56)
            session = (123, 1, 0)
            result = {'ok': True, 'cross_zone': True, 'point': {
                'zone': '湿地', 'name': '藓皮豺狼人营地', 'x': 60.51, 'y': 63.71}}
            window._leveling_planner = Mock()
            window._leveling_planner.observe.return_value = result
            window._poll_leveling(session, source, True)
            trip = window._leveling_trip[2]
            self.assertEqual(result['walking_maps'], [1432, 1437])
            self.assertEqual((trip.goal.x, trip.goal.y), (61, 63.5))
            self.assertEqual((trip.catalog_goal.x, trip.catalog_goal.y), (60.51, 63.71))
            tunnel = trip.legs[0].arrival_road
            position = NavigationState('alive', 1, 1432, source.x, source.y, 0, 2758, 1840, (87, 65, 68))
            waypoint, _ = trip.observe(position)
            self.assertEqual((waypoint.x, waypoint.y), (25.45, 6.9))
            entered = replace(position, map_id=1437, x=55.84, y=91.93, sequence=2, width=4135, height=2756)
            self.assertEqual(trip.observe(entered), (None, None))
            self.assertEqual(trip.observe(entered), (None, None))
            self.assertIn('确认进入湿地', trip.observe(replace(entered, sequence=3))[1])
            for sequence, (x, y) in enumerate(tunnel, 4):
                waypoint, status = trip.observe(replace(entered, x=x, y=y, sequence=sequence))
                if sequence - 3 < len(tunnel):
                    self.assertEqual((waypoint.x, waypoint.y), tunnel[sequence - 3])
                self.assertFalse(trip.complete)
            self.assertIsNone(waypoint)
            self.assertIn('开始走你标记的路点', status)
            last = replace(entered, x=61, y=63.5, sequence=20)
            waypoint, _ = trip.observe(last)
            self.assertEqual((waypoint.x, waypoint.y), (54.8, 69.9))
            for sequence, (x, y) in enumerate(((54.8, 69.9), (58, 66.5), (61, 63.5)), 21):
                waypoint, status = trip.observe(replace(last, x=x, y=y, sequence=sequence))
            self.assertEqual(waypoint, trip.goal)
            self.assertIn('将在这里寻怪', status)
            self.assertTrue(trip.complete)

        test_dev_tray.TrayTests.run_window(self, False, exercise)

    def test_rejects_invalid_text_and_does_not_match_unrelated_goals(self):
        for bad in ('', 'WBDROUTE1|1432|10,20', 'WBDROUTE1|0|10,20|30,40',
                    'WBDROUTE1|1432|10001,20|30,40', 'WBDROUTE1|1432|10,20|10,20',
                    'WBDROUTE1|1432|nan,20|30,40'):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse_manual_route(bad)
        routes = [parse_manual_route('WBDROUTE1|1432|8050,6110|7680,7050')]
        self.assertEqual(manual_camp_road(routes, MapDestination(1432, 65.4, 39.6, 'alive', '老山猪区')), ())
        self.assertEqual(manual_camp_road(routes, MapDestination(1433, 76.8, 70.5, 'alive', '其他地图')), ())
