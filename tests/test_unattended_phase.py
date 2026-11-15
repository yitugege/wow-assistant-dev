"""无人托管阶段判定：与拆分前 DevWindow.poll_once 中布尔表达式逐项对照。"""
from itertools import product
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'desktop'))
from wowbuddy.automation.unattended import (UnattendedController, UnattendedPhase, UnattendedSnapshot, classify,
                                            delegated)

SESSION = (1, 2, 0)
OTHER = (9, 9, 9)


def legacy(s, session):
    """拆分前的原表达式（去掉总开关与监控状态两项前置条件）。"""
    active, fixed, revival, quest_trip = s.leveling_trip, s.fixed_camp_route, s.automatic_revival, s.quest_trip
    traveling = active and active[2].session == session and not active[2].complete
    waiting_for_fixed = fixed is not None and (not active or active[2].session != session)
    waiting_for_upgrade = s.leveling_upgrade_wait == session
    waiting_for_vendor = s.vendor_wait is not None and s.vendor_wait[0] == session
    waiting_for_revival = (s.post_revival_session == session
                           or (revival is not None and revival.session == session
                               and revival.life in ('dead', 'ghost')))
    supply_trip = s.online_vendor is not None and s.online_vendor[0][0] == session
    return bool(traveling or waiting_for_fixed or waiting_for_upgrade or waiting_for_vendor
                or waiting_for_revival or supply_trip
                or (quest_trip and quest_trip.session == session)
                or (s.vendor_run.session == session and s.vendor_run.active))


class UnattendedPhaseTests(unittest.TestCase):
    def test_idle_without_any_trip(self):
        snapshot = UnattendedSnapshot(vendor_run=NS(session=None, active=False))
        self.assertIs(classify(snapshot, SESSION), UnattendedPhase.IDLE)
        self.assertFalse(classify(snapshot, SESSION).is_travel)

    def test_death_states_take_priority(self):
        for life, phase in (('dead', UnattendedPhase.DEAD), ('ghost', UnattendedPhase.GHOST)):
            snapshot = UnattendedSnapshot(automatic_revival=NS(session=SESSION, life=life),
                                          quest_trip=NS(session=SESSION),
                                          vendor_run=NS(session=SESSION, active=True))
            self.assertIs(classify(snapshot, SESSION), phase)

    def test_trips_from_another_session_are_ignored(self):
        snapshot = UnattendedSnapshot(leveling_trip=(None, None, NS(session=OTHER, complete=False)),
                                      vendor_wait=(OTHER,), online_vendor=((OTHER,),),
                                      quest_trip=NS(session=OTHER), leveling_upgrade_wait=OTHER,
                                      post_revival_session=OTHER,
                                      automatic_revival=NS(session=OTHER, life='ghost'),
                                      vendor_run=NS(session=OTHER, active=True))
        self.assertIs(classify(snapshot, SESSION), UnattendedPhase.IDLE)

    def test_matches_legacy_expression_exhaustively(self):
        trips = [None, (None, None, NS(session=SESSION, complete=False)),
                 (None, None, NS(session=SESSION, complete=True)), (None, None, NS(session=OTHER, complete=False))]
        revivals = [None, NS(session=SESSION, life='dead'), NS(session=SESSION, life='ghost'),
                    NS(session=SESSION, life='alive'), NS(session=OTHER, life='dead')]
        keys = [None, SESSION, OTHER]
        runs = [NS(session=SESSION, active=True), NS(session=SESSION, active=False), NS(session=OTHER, active=True)]
        count = 0
        for trip, fixed, upgrade, wait, revival, post, online, quest, run in product(
                trips, [None, object()], keys, [None, (SESSION,), (OTHER,)], revivals, keys,
                [None, ((SESSION,),), ((OTHER,),)], [None, NS(session=SESSION), NS(session=OTHER)], runs):
            snapshot = UnattendedSnapshot(trip, fixed, upgrade, wait, revival, post, online, quest, run)
            self.assertEqual(classify(snapshot, SESSION).is_travel, legacy(snapshot, SESSION), snapshot)
            count += 1
        self.assertGreater(count, 10000)


class UnattendedControllerTests(unittest.TestCase):
    def test_travel_requires_switch_and_monitoring(self):
        controller = UnattendedController(vendor_run=NS(session=None, active=False))
        controller.quest_trip = NS(session=SESSION)
        self.assertTrue(controller.travel_active(SESSION, unattended=True, monitoring=True))
        self.assertIs(controller.last_phase, UnattendedPhase.QUEST)
        self.assertFalse(controller.travel_active(SESSION, unattended=False, monitoring=True))
        self.assertFalse(controller.travel_active(SESSION, unattended=True, monitoring=False))
        controller.quest_trip = None
        self.assertFalse(controller.travel_active(SESSION, unattended=True, monitoring=True))

    def test_frame_plan_matches_legacy_switch_rule(self):
        for unattended, revive, leveling, navigate in product((False, True), repeat=4):
            plan = UnattendedController.frame_plan(unattended, auto_revive=revive, auto_leveling=leveling,
                                                   auto_navigate=navigate)
            self.assertEqual((plan.revive, plan.leveling, plan.navigate),
                             (unattended or revive, unattended or leveling, unattended or navigate))

    def test_loot_phase_is_reported_but_never_counts_as_travel(self):
        controller = UnattendedController(vendor_run=NS(session=None, active=False))
        controller.loot_approach_session = SESSION
        self.assertIs(controller.phase(SESSION), UnattendedPhase.LOOT)
        self.assertFalse(controller.travel_active(SESSION, unattended=True, monitoring=True))
        controller.quest_trip = NS(session=SESSION)
        self.assertIs(controller.phase(SESSION), UnattendedPhase.QUEST)
        self.assertIs(controller.phase(OTHER), UnattendedPhase.IDLE)

    def drive(self, controller, frame, plan, quest_result):
        """模拟窗口：逐步执行 run_frame 产出的动作，QUEST 回传 quest_result。"""
        from wowbuddy.automation.unattended import FrameAction
        steps, reply, actions = controller.run_frame(frame, plan), None, []
        while True:
            try:
                step = steps.send(reply)
            except StopIteration:
                return actions
            actions.append(step)
            reply = quest_result if step is FrameAction.QUEST else None

    def test_run_frame_matches_legacy_branches(self):
        from wowbuddy.automation.unattended import FrameAction, FrameInput, FramePlan
        alive, dead = NS(life='alive'), NS(life='dead')
        count = 0
        for unattended, revive, leveling, navigate, frame_ok, image_ok in product((False, True), repeat=6):
            for character, vendor_active, post_revival, quest_result in product(
                    (None, alive, dead), (False, True), (None, SESSION), (None, 'trip')):
                controller = UnattendedController(vendor_run=NS(session=SESSION, active=vendor_active))
                controller.quest_trip = stale = NS(session=OTHER)
                controller.post_revival_session = post_revival
                frame = FrameInput(session=SESSION, unattended=unattended, frame_ok=frame_ok, image_ok=image_ok,
                                   character=character)
                plan = FramePlan(revive=revive, leveling=leveling, navigate=navigate)
                actions = self.drive(controller, frame, plan, quest_result)
                # 拆分前：_observe_quest_route 在门槛不满足时清空行程并返回 None。
                gate = (image_ok and frame_ok and character is alive and not vendor_active
                        and post_revival != SESSION)
                quest_called = unattended and navigate
                quest = quest_result if quest_called and gate else None
                expected = ([FrameAction.REVIVAL] if revive else [])                     + ([FrameAction.VENDOR] if unattended and navigate and frame_ok else [])                     + ([FrameAction.QUEST] if quest_called and gate else [])                     + ([FrameAction.LEVELING] if leveling and quest is None else []) + [FrameAction.NAVIGATION]
                self.assertEqual(actions, expected)
                self.assertIs(controller.quest_trip, None if quest_called and not gate else stale)
                count += 1
        self.assertEqual(count, 64 * 24)

    def test_run_frame_derives_phase_from_frame_death_state(self):
        from wowbuddy.automation.unattended import FrameInput, FramePlan
        controller = UnattendedController(vendor_run=NS(session=None, active=False))
        character, death = NS(life='ghost'), NS(life='ghost')
        self.drive(controller, FrameInput(session=SESSION, unattended=True, frame_ok=True,
                                          character=character, death=death),
                   FramePlan(revive=True, leveling=True, navigate=True), None)
        self.assertIs(controller.last_phase, UnattendedPhase.GHOST)
        self.assertIs(controller.last_character, character)
        self.assertIs(controller.last_death, death)
        # 帧内死亡状态只影响记录的阶段，不改变按行程判定的托管赶路。
        self.assertFalse(controller.travel_active(SESSION, unattended=True, monitoring=True))
        self.drive(controller, FrameInput(session=SESSION, unattended=False, frame_ok=True, death=NS(life='alive')),
                   FramePlan(revive=False, leveling=False, navigate=False), None)
        self.assertIs(controller.last_phase, UnattendedPhase.IDLE)

    def test_controller_owns_phase_handlers(self):
        from wowbuddy.automation.unattended_phases import LevelingPhase, RevivalPhase, VendorPhase
        controller = UnattendedController()
        self.assertIsInstance(controller.revival, RevivalPhase)
        self.assertIsInstance(controller.vendor, VendorPhase)
        self.assertIsInstance(controller.leveling, LevelingPhase)
        logged = []
        host = NS(_vendor_wait=None, logger=NS(append=logged.append))
        controller.vendor.wait(host, SESSION, '背包已满')
        controller.vendor.wait(host, SESSION, '背包已满')
        self.assertEqual((host._vendor_wait, logged), ((SESSION, '背包已满'), ['背包已满']))

    def test_window_attributes_delegate_to_controller(self):
        class Window:
            _quest_trip = delegated('quest_trip')

            def __init__(self):
                self.unattended = UnattendedController()

        window = Window()
        self.assertIsNone(getattr(window, '_quest_trip', 'missing'))
        window._quest_trip = trip = NS(session=SESSION)
        self.assertIs(window.unattended.quest_trip, trip)
        del window._quest_trip
        self.assertIsNone(window.unattended.quest_trip)


if __name__ == '__main__':
    unittest.main()
