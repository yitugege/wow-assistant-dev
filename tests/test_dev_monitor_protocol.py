"""真实Qt监控入口贯穿抓屏选择、控制器、调度与投递记账；系统后端全部替换。"""
from dataclasses import replace
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'));sys.path.insert(0,str(ROOT/'tests/core'))
import test_dev_tray
from test_old_protocol import render_old
from test_pipeline import render_readable
from wowbuddy.win32.capture import CaptureResult, WindowCapture, Rect
from wowbuddy.core.dev_protocol import DEV_VERSION, RECOVERY_CONFIG_BASE, RECOVERY_DISABLED_BASE
from wowbuddy.core.old_protocol import OldFrame
from wowbuddy.core.pixel_geometry import RGBImage
from wowbuddy.engine.rotation_selection import Profile
from wowbuddy.core.candidates import parse_rules


class MonitorProtocolTests(unittest.TestCase):
    def test_unattended_combat_recovery_revival_and_level_change_share_one_session(self):
        self._exercise_unattended_camp_handoff('level_change')

    def test_unattended_level_44_leaves_cooled_camp_without_level_change(self):
        self._exercise_unattended_camp_handoff('target_rejections')

    def test_unattended_repeated_deaths_leave_camp_after_revival(self):
        self._exercise_unattended_camp_handoff('repeated_deaths')

    def test_unattended_death_on_final_approach_counts_before_camp_arrival(self):
        self._exercise_unattended_camp_handoff('approach_death')

    def _exercise_unattended_camp_handoff(self, reason):
        from concurrent.futures import Future
        from tests.test_addon_recovery import RecoveryTests
        from wowbuddy.core.auto_target import parse_auto_target
        from wowbuddy.engine.character_state import decode_mob_state, decode_navigation_state
        from wowbuddy.automation.death_recovery import AutomaticRevival
        from wowbuddy.automation.leveling_route import AutomaticLeveling

        game = RecoveryTests()
        game.setUp()
        game.configure()
        self.assertTrue(game.addon.SetPostKillAutoTargetEnabled(True))
        game.lua.execute('''
            fixtureLife='alive'; fixtureLevel=44; fixtureMap=1435
            fixtureX=0.271; fixtureY=0.567; fixtureFacing=0
            fixtureTargetExists=false; fixtureHovered=false
            fixtureTargetPlayer=false; fixtureTargetTapped=false; fixtureTargetTrivial=false
            fixtureTargetClassification='normal'
            fixtureOldTargetOutOfRange=false
            local targetDead=UnitIsDeadOrGhost
            function UnitIsDeadOrGhost(unit)
                if unit=='player' then return fixtureLife~='alive' end
                return targetDead(unit)
            end
            function UnitIsGhost() return fixtureLife=='ghost' end
            function UnitLevel(unit)
                if unit=='target' then return fixtureTargetLevel or fixtureLevel-4 end
                return fixtureLevel
            end
            function UnitFactionGroup() return 'Alliance','联盟' end
            function UnitExists(unit) return unit=='player' or (unit=='target' and fixtureTargetExists) end
            function UnitCanAttack(_,unit) return unit=='target' and fixtureTargetExists end
            function UnitIsPlayer(unit) return unit=='player' or (unit=='target' and fixtureTargetPlayer) end
            function UnitPlayerControlled(unit) return UnitIsPlayer(unit) end
            function UnitIsTapDenied(unit) return unit=='target' and fixtureTargetTapped end
            function UnitIsTrivial(unit) return unit=='target' and fixtureTargetTrivial end
            function UnitClassification(unit) return unit=='target' and fixtureTargetClassification end
            local unitIsUnit=UnitIsUnit
            function UnitIsUnit(unit, other)
                if unit=='targettarget' then return other=='player' and fixtureTargetAttacksPlayer==true end
                return unitIsUnit(unit, other)
            end
            local spellInRange=C_Spell.IsSpellInRange
            function C_Spell.IsSpellInRange(id,unit)
                if unit=='target' and fixtureOldTargetOutOfRange then return false end
                return spellInRange(id,unit)
            end
            function GetPlayerFacing() return fixtureFacing end
            C_Map={
                GetBestMapForUnit=function() return fixtureMap end,
                GetMapInfo=function(id) return {name=id==1435 and '悲伤沼泽' or '诅咒之地',mapType=3} end,
                GetMapWorldSize=function(id) if id==1435 then return 2294,1529 end return 3350,2233 end,
                GetPlayerMapPosition=function()
                    if fixtureNavigationUnavailable then return nil end
                    return {GetXY=function() return fixtureX,fixtureY end}
                end,
            }
            C_DeathInfo={GetCorpseMapPosition=function(id)
                if id==1435 then return {GetXY=function() return 0.271,0.567 end} end
            end}
            local button={IsVisible=function() return true end,IsEnabled=function() return true end,
                GetCenter=function() return 50,37.5 end,GetEffectiveScale=function() return 1 end}
            function StaticPopup_FindVisible(which)
                if popupType==which then
                    return {which=which,IsVisible=function() return true end,GetButton1=function() return button end}
                end
            end
            function GetMouseFoci() return fixtureHovered and {button} or {} end
            function CannotBeResurrected() return nil end
            local keys={W='MOVEFORWARD',A='TURNLEFT',D='TURNRIGHT',TAB='TARGETNEARESTENEMY'}
            function GetBindingKey(action)
                for key,value in pairs(keys) do if value==action then return key end end
            end
            function GetBindingAction(key, overrides)
                if keys[key] then return keys[key] end
                if overrides then
                    for _,frame in ipairs(frames) do
                        local binding=frame.bindings and frame.bindings[key]
                        if binding then return 'CLICK '..binding.button..':LeftButton' end
                    end
                end
                return ''
            end
            WowBuddyDev.RefreshMacroBindings()
            local target=WowBuddyDev.GetSecureButton('auto_target')
            function target:GetName() return self.name end
            local discard=WowBuddyDev.GetSecureButton('discard_unreachable_target')
            function discard:GetName() return self.name end
        ''')
        game.addon.RebuildPixelBars()
        g = game.g
        swamp = '/zh/zones/eastern-kingdoms/swamp-of-sorrows/'
        blasted = '/zh/zones/eastern-kingdoms/blasted-lands/'
        pages = {
            '/zh/leveling/alliance/': (
                '<article class="lvs" data-step="1"><p class="lvs-meta">44–48</p>'
                f'<div class="lvs-leg__text"><h4><a href="{blasted}">诅咒之地</a></h4>'
                '<ol class="lvs-hubs"><li><span class="lvs-hub-name">守望堡</span>'
                '<code>66.9, 19.47</code></li></ol></div></article>'),
            swamp: f'<section id="route-alliance"><a class="route-coords" href="{swamp}?pin=27.1,55.13#map">鳄鱼</a></section>',
            blasted: f'<section id="route-alliance"><a class="route-coords" href="{blasted}?pin=50.2,17.2#map">秃鹫</a></section>',
        }

        def submit(function, *args, **kwargs):
            future = Future()
            try:
                future.set_result(function(*args, fetch=lambda url: pages[url.removeprefix('https://wowhandbook.com')],
                                           **kwargs))
            except Exception as error:
                future.set_exception(error)
            return future

        def exercise(window):
            window.grind_check.setChecked(True)
            window._leveling_planner = AutomaticLeveling(submit)
            mouse = Mock()
            window._automatic_revival = AutomaticRevival(mouse)
            rect = Rect(20, 30, 1020, 830)
            window.sender = window.dispatcher.sender = game.sender
            window.monotonic_ms = window.session.monotonic_ms = window.scheduler.clock_ms = game.sender.backend.now_ms
            window.session.start(123)
            movement = Mock(holding_forward=False)
            movement.keep_forward.return_value = False
            window.loop.capture = SimpleNamespace(capture=lambda hwnd: CaptureResult('ok', image, 'dxgi', rect))

            def poll(delta=0.35):
                nonlocal image
                image = game.game_image(delta)
                result = window.poll_once()
                self.assertIsNotNone(result.tick, result.status)
                self.assertTrue(result.tick.decision.frame.ok, result.status)
                return result.tick

            def sent_keys():
                return [call.args[0] for call in game.sender.send.call_args_list]

            def set_target(present, guid):
                g.fixtureTargetExists, g.targetAlive, g.fixtureTargetGUID = present, present, guid
                g.EmitFixtureEvent('PLAYER_TARGET_CHANGED')

            image = None
            with (patch('wowbuddy.automation.navigation.ForegroundMovement', return_value=movement),
                  patch('wowbuddy.win32.windows_keys.is_foreground', return_value=True)):
                image = game.game_image()
                self.assertEqual(window.poll_once().status, 'frame_held')
                poll()
                window.controller.select('1482|冰霜|官方 · 练级（冰霜 · 单体+AOE）')
                for _ in range(5):
                    poll()
                    if sent_keys():
                        break
                self.assertEqual(sent_keys(), ['F6'])
                game.addon.RecordAutoTargetAttempt()
                g.fixtureTargetPlayer = True
                set_target(True, 'Player-1')
                rejected = poll()
                self.assertIn('玩家控制', rejected.decision.target_rejection)
                self.assertEqual(rejected.decision.candidates, ())
                poll()
                movement.pulse.assert_called_with(123, 9, 35, (87, 65, 68, 9))
                g.fixtureTargetPlayer, g.fixtureTargetTapped = False, True
                set_target(True, 'Creature-tapped')
                rejected = poll()
                self.assertIn('已被其他玩家占有', rejected.decision.target_rejection)
                navigation = decode_navigation_state(image, rejected.decision.frame)
                self.assertNotEqual(navigation.discard_key, 0)
                poll()
                movement.pulse.assert_called_with(123, navigation.discard_key, 35,
                                                  (*navigation.keys, navigation.discard_key))
                self.assertEqual(sent_keys(), ['F6'])
                set_target(False, 'Creature-cleared')
                g.fixtureTargetTapped = False
                camp = window._leveling_destination
                poll()
                self.assertEqual(window._leveling_destination, camp)
                movement.pulse.reset_mock()
                for _ in range(8):
                    poll()
                    if movement.pulse.called:
                        break
                movement.pulse.assert_called_once_with(123, 65, 120, (87, 65, 68))
                self.assertEqual(sent_keys(), ['F6'])
                g.fixtureFacing = 1.5708
                for _ in range(5):
                    if len(sent_keys()) > 1:
                        break
                    poll()
                self.assertEqual(sent_keys(), ['F6', 'F6'])
                game.addon.RecordAutoTargetAttempt()
                set_target(True, 'Creature-1')
                g.combat = True
                self.assertEqual(poll().selected.action, 'spell_116')
                g.targetAlive, g.health, g.powerValue = False, 60, 48
                game.lua.execute('function CanLootUnit() return true, true end')
                under_attack = poll(2)
                self.assertEqual(decode_mob_state(image, under_attack.decision.frame).state, 3)
                self.assertEqual(under_attack.status, 'stopped')
                g.CanLootUnit = None
                g.combat = False
                g.EmitFixtureEvent('PLAYER_REGEN_ENABLED')
                self.assertEqual(poll().selected.action, 'recovery_food')
                game.click_item('food')
                g.inventory[5349] = 2
                self.assertEqual(poll().selected.action, 'recovery_water')
                game.click_item('water')
                g.inventory[5350] = 3
                self.assertEqual(poll(2).status, 'stopped')
                g.health, g.powerValue = 87, 92
                resumed = poll()
                self.assertIsNotNone(resumed.selected, (resumed.status, resumed.decision.candidates, sent_keys()))
                self.assertEqual(resumed.selected.action, 'auto_target')
                game.addon.RecordAutoTargetAttempt()
                set_target(True, 'Creature-2')
                self.assertEqual(poll(2).selected.action, 'spell_116')

                sent_before_death = sent_keys()
                g.fixtureLife, g.popupType, g.fixtureHovered = 'dead', 'DEATH', False
                poll()
                mouse.click.assert_not_called()
                g.fixtureHovered = True
                poll()
                mouse.click.assert_called_once_with(123, (520, 530))
                g.fixtureLife, g.popupType, g.fixtureHovered, g.fixtureY = 'ghost', None, False, 0.60
                g.fixtureFacing = 0
                # 释放灵魂后先等墓地坐标稳定（CorpseTrail 起点确认约 1.2 秒），期间只松键不前进。
                movement.hold_forward.reset_mock()
                poll()
                self.assertEqual(window.ui.suggestions.toPlainText(), '等待释放灵魂后的墓地地图与坐标稳定。')
                self.assertIsNone(window._corpse_trip)
                movement.hold_forward.assert_not_called()
                for _ in range(8):
                    poll()
                    if window._corpse_trip is not None:
                        break
                self.assertIsNotNone(window._corpse_trip)
                movement.hold_forward.assert_called_with(123, (87, 65, 68))
                g.fixtureY, g.popupType = 0.567, 'RECOVER_CORPSE'
                poll()
                self.assertEqual(mouse.click.call_count, 1)
                g.fixtureHovered = True
                poll()
                self.assertEqual(mouse.click.call_count, 2)
                self.assertEqual(sent_keys(), sent_before_death)

                settings = game.addon.GetRecoverySettings()
                settings.enabled = False
                self.assertTrue(game.addon.SaveRecoverySettings(settings))
                g.fixtureLife, g.popupType = 'alive', None
                g.health, g.powerValue = 50, 40
                revived = poll(2)
                self.assertTrue(revived.decision.recovery_disabled)
                self.assertEqual(revived.status, 'stopped')
                self.assertEqual(sent_keys(), sent_before_death)
                self.assertIsNotNone(window._post_revival_session)
                settings.enabled = True
                self.assertTrue(game.addon.SaveRecoverySettings(settings))
                self.assertEqual(poll().selected.action, 'recovery_food')
                game.click_item('food')
                g.inventory[5349] = 1
                self.assertEqual(poll().selected.action, 'recovery_water')
                game.click_item('water')
                g.inventory[5350] = 2
                g.health, g.powerValue = 87, 92
                handoff = poll(2)
                self.assertTrue(handoff.decision.recovery_ready)
                self.assertIsNone(handoff.selected)
                self.assertIsNone(window._post_revival_session)
                self.assertEqual(poll().selected.action, 'spell_116')

                if reason == 'target_rejections':
                    keys_before_cooldown = sent_keys()
                    g.fixtureTargetTrivial = True
                    for index in range(3):
                        set_target(True, f'Creature-trivial-{index}')
                        rejected = poll()
                        self.assertEqual(rejected.decision.target_rejection, '当前怪物等级过低')
                        poll()
                        movement.pulse.assert_called_with(123, 9, 35, (87, 65, 68, 9))
                        set_target(True, f'Creature-trivial-alternate-{index}')
                        rejected = poll()
                        navigation = decode_navigation_state(image, rejected.decision.frame)
                        poll()
                        movement.pulse.assert_called_with(123, navigation.discard_key, 35,
                                                          (*navigation.keys, navigation.discard_key))
                        set_target(False, f'Creature-cleared-{index}')
                        poll()
                    self.assertEqual(sent_keys(), keys_before_cooldown)
                    self.assertIn('当前刷怪区连续遇到不适合练级的目标', window.ui.log_view.toPlainText())
                    g.fixtureTargetTrivial = False
                elif reason in ('repeated_deaths', 'approach_death'):
                    self.assertEqual(window._leveling_destination, camp)
                    self.assertNotIn('当前刷怪区反复阵亡', window.ui.log_view.toPlainText())
                    if reason == 'approach_death':
                        from wowbuddy.automation.walking_route import WalkingTrip

                        session, _, goal = camp
                        g.fixtureY = (goal.y + 5) / 100
                        road = ((goal.x, goal.y + 5.1), (goal.x, goal.y + 3), (goal.x, goal.y))
                        trip = WalkingTrip(session, (), goal, level=44, camp_road=road)
                        window._leveling_trip = 'alliance', 44, trip
                        window._leveling_destination = None
                        still_traveling = poll()
                        self.assertFalse(trip.complete)
                        self.assertFalse(goal.contains(decode_navigation_state(image, still_traveling.decision.frame)))
                        g.combat = True
                        poll()
                    g.fixtureLife, g.popupType, g.fixtureHovered = 'dead', 'DEATH', False
                    g.combat = False
                    poll()
                    self.assertIn('当前刷怪区反复阵亡', window.ui.log_view.toPlainText())
                    g.fixtureHovered = True
                    poll()
                    self.assertEqual(mouse.click.call_count, 3)
                    set_target(False, 'Creature-after-death')
                    g.fixtureY = 0.567
                    g.fixtureLife, g.popupType, g.fixtureHovered = 'ghost', 'RECOVER_CORPSE', False
                    poll()
                    poll()
                    g.fixtureHovered = True
                    poll()
                    self.assertEqual(mouse.click.call_count, 4)
                    g.fixtureLife, g.popupType = 'alive', None
                    g.health, g.powerValue = 50, 40
                    g.inventory[5349] = 2
                    movement.hold_forward.reset_mock()
                    self.assertEqual(poll(2).selected.action, 'recovery_food')
                    game.click_item('food')
                    g.inventory[5349] = 1
                    self.assertEqual(poll().selected.action, 'recovery_water')
                    game.click_item('water')
                    g.inventory[5350] = 1
                    self.assertIsNotNone(window._post_revival_session)
                    movement.hold_forward.assert_not_called()
                    g.health, g.powerValue = 87, 92
                else:
                    g.fixtureOldTargetOutOfRange = True
                    set_target(True, 'Creature-3')
                    g.fixtureLevel = 45
                for _ in range(4):
                    tick = poll()
                trip = window._leveling_trip[2]
                self.assertEqual((trip.legs[0].source, trip.legs[0].destination), (1435, 1419))
                self.assertEqual((trip.goal.x, trip.goal.y), (50.2, 17.2))
                if reason == 'level_change':
                    self.assertEqual(tick.decision.frame.values['target_valid'], 'ON')
                    self.assertTrue(tick.decision.attack_blocked_by_range)
                    self.assertFalse(window._approaching_target)
                self.assertIsNotNone(trip.current)
                self.assertEqual(trip.current.map_id, 1435)
                if reason == 'level_change':
                    keys_before_travel = sent_keys()
                    g.fixtureOldTargetOutOfRange = False
                    in_range = poll(2)
                    self.assertEqual(in_range.decision.frame.values['target_valid'], 'ON')
                    self.assertEqual(in_range.decision.frame.values['range_116'], 'ON')
                    self.assertIsNone(in_range.selected)
                    self.assertEqual(sent_keys(), keys_before_travel)
                    route_point = trip.current
                    g.fixtureOldTargetOutOfRange, g.combat = False, True
                    self.assertEqual(poll(2).selected.action, 'spell_116')
                    self.assertEqual(trip.current, route_point)
                    g.targetAlive, g.health, g.powerValue = False, 60, 48
                    poll(2)
                    g.combat = False
                    g.EmitFixtureEvent('PLAYER_REGEN_ENABLED')
                    g.inventory[5349], g.inventory[5350] = 2, 2
                    movement.hold_forward.reset_mock()
                    self.assertEqual(poll().selected.action, 'recovery_food')
                    game.click_item('food')
                    g.inventory[5349] = 1
                    self.assertEqual(poll().selected.action, 'recovery_water')
                    game.click_item('water')
                    g.inventory[5350] = 1
                    movement.hold_forward.assert_not_called()
                    g.health, g.powerValue = 87, 92
                    keys_before_travel = sent_keys()
                    resumed = poll()
                    self.assertEqual(parse_auto_target(int(resumed.decision.fields['ttd'])).state, 1)
                    self.assertIsNone(resumed.selected)
                    self.assertEqual(sent_keys(), keys_before_travel)
                    g.fixtureOldTargetOutOfRange = True
                    set_target(True, 'Creature-old-road')
                    self.assertTrue(poll(2).decision.attack_blocked_by_range)
                    self.assertFalse(window._approaching_target)
                for _ in range(24):
                    if trip.current is None:
                        break
                    g.fixtureX, g.fixtureY = trip.current.x / 100, trip.current.y / 100
                    poll()
                self.assertIsNone(trip.current)
                if reason == 'level_change':
                    movement.reset_mock()
                    g.fixtureNavigationUnavailable = True
                    missing = poll()
                    self.assertIsNone(decode_navigation_state(image, missing.decision.frame))
                    movement.release_forward.assert_called()
                    movement.hold_forward.assert_not_called()
                    g.fixtureNavigationUnavailable = False
                    road = trip.legs[0].points
                    g.fixtureX, g.fixtureY = road[-3][0] / 100, road[-3][1] / 100
                    poll()
                    self.assertEqual((trip.current.x, trip.current.y), road[-2])
                    self.assertIn('重新接入原路段', window.ui.log_view.toPlainText())
                    for _ in range(5):
                        if trip.current is None:
                            break
                        g.fixtureX, g.fixtureY = trip.current.x / 100, trip.current.y / 100
                        poll()
                    self.assertIsNone(trip.current)
                    self.assertFalse(trip.blocked_legs)
                g.fixtureMap, g.fixtureX, g.fixtureY = 1419, 0.5216, 0.0804
                g.fixtureOldTargetOutOfRange = False
                set_target(False, 'Creature-cleared-on-crossing')
                poll()
                self.assertTrue(trip.legs)
                poll()
                self.assertFalse(trip.legs)
                self.assertIn('已确认进入诅咒之地', window.ui.log_view.toPlainText())
                for _ in range(15):
                    if trip.complete:
                        break
                    if trip.current is not None:
                        g.fixtureX, g.fixtureY = trip.current.x / 100, trip.current.y / 100
                    poll()
                self.assertTrue(trip.complete)
                g.fixtureX, g.fixtureY = trip.goal.x / 100, trip.goal.y / 100
                keys_before_arrival = sent_keys()
                for _ in range(5):
                    poll()
                    if sent_keys() != keys_before_arrival:
                        break
                self.assertEqual(sent_keys(), keys_before_arrival + ['F6'])
                game.addon.RecordAutoTargetAttempt()
                set_target(True, 'Creature-4')
                self.assertEqual(poll().selected.action, 'spell_116')

                keys_before_rejection = sent_keys()
                movement.pulse.reset_mock()
                g.fixtureTargetTrivial = True
                set_target(True, 'Creature-trivial')
                rejected = poll(2)
                self.assertEqual(rejected.decision.target_rejection, '当前怪物等级过低')
                self.assertEqual(rejected.decision.candidates, ())
                poll()
                movement.pulse.assert_called_once_with(123, 9, 35, (87, 65, 68, 9))
                self.assertEqual(sent_keys(), keys_before_rejection)
                g.fixtureTargetTrivial = False
                g.fixtureTargetClassification = 'elite'
                set_target(True, 'Creature-elite')
                rejected = poll()
                self.assertEqual(rejected.decision.target_rejection, '当前目标是精英怪或世界首领')
                self.assertEqual(rejected.decision.candidates, ())
                navigation = decode_navigation_state(image, rejected.decision.frame)
                movement.pulse.reset_mock()
                poll()
                movement.pulse.assert_called_once_with(123, navigation.discard_key, 35,
                                                       (*navigation.keys, navigation.discard_key))
                self.assertEqual(sent_keys(), keys_before_rejection)
                set_target(False, 'Creature-cleared-elite')
                poll()
                g.fixtureTargetClassification = 'normal'
                set_target(True, 'Creature-5')
                # 不再限制“比角色低 4 级”：任意等级的普通怪（含 ?? 级）都会攻击。
                for level in (g.fixtureLevel - 5, g.fixtureLevel - 3, -1, g.fixtureLevel - 4):
                    g.fixtureTargetLevel = level
                    accepted = poll(2)
                    self.assertIsNone(accepted.decision.target_rejection)
                    self.assertEqual(accepted.selected.action, 'spell_116')

                game.lua.execute('function WowBuddyDev.UpdateRecovery() return 0,0 end')
                unknown = poll(2)
                self.assertEqual(unknown.status, 'stopped')
                self.assertIn('有效的恢复读数', unknown.decision.candidates[0].reason)
                g.fixtureTargetTapped, g.fixtureTargetTrivial = True, True
                g.fixtureTargetClassification = 'elite'
                g.combat = True
                combat_tapped = poll(2)
                self.assertEqual(combat_tapped.status, 'stopped')
                self.assertIn('其他玩家占有', combat_tapped.decision.candidates[0].reason)
                # 2026-11-17 02:05：战斗中目标被判“已被其他玩家占有”，63 秒一个技能没放，被 3 只怪打死。
                # 战斗中这类拒绝只暂停 3 秒（让自动选目标换怪），之后还手。
                override = window.pipeline.combat_rejection
                started = override.since
                override.clock = lambda: started + 3.5
                fight_back = poll(2)
                self.assertIsNone(fight_back.decision.target_rejection)
                self.assertEqual(fight_back.selected.action, 'spell_116')
                override.clock = __import__('time').monotonic
                override.since = None
                g.fixtureTargetTapped = False
                keys_before_trivial = sent_keys()
                combat_trivial = poll(2)
                self.assertEqual(combat_trivial.status, 'stopped')
                self.assertEqual(combat_trivial.decision.target_rejection, '当前怪物等级过低')
                self.assertEqual(sent_keys(), keys_before_trivial)
                g.fixtureTargetAttacksPlayer = True
                self.assertEqual(poll(2).selected.action, 'spell_116')
                g.fixtureTargetPlayer = True
                set_target(True, 'Player-2')
                combat_player = poll(2)
                self.assertEqual(combat_player.status, 'stopped')
                self.assertIn('玩家控制', combat_player.decision.candidates[0].reason)

        test_dev_tray.TrayTests.run_window(self, False, exercise)

    def test_recovery_wait_does_not_transfer_to_a_new_monitor_session(self):
        def exercise(window):
            gate = window.pipeline.recovery
            clock = Mock(return_value=1000)
            window.session.monotonic_ms = clock
            window.loop.capture = SimpleNamespace(capture=lambda hwnd: CaptureResult('minimized'))
            window.session.start(123)
            self.assertEqual(window.loop.poll().status, 'minimized')
            frame = OldFrame('ok', spec_id='1482', version_code=DEV_VERSION, values={
                'player_in_combat': 'OFF', 'player_valid': 'ON', 'master_switch': 'OFF',
                'player_health_pct': '60', 'mana_pct': '100',
                'ttf': str(RECOVERY_CONFIG_BASE + 61 * 128 * 128 + 87 * 128 + 82),
                'combat_time': str(RECOVERY_CONFIG_BASE + 49 * 128 * 128 + 92 * 128 + 82),
            })
            missing = replace(frame, values=dict(frame.values, ttf='0', combat_time='0'))
            disabled = replace(missing, values=dict(missing.values,
                               ttf=str(RECOVERY_DISABLED_BASE + 61 * 128 + 49)))
            self.assertTrue(gate.evaluate(frame)[1].stop)
            self.assertTrue(gate.evaluate(missing)[1].stop)
            self.assertIsNone(gate.evaluate(disabled))
            self.assertIsNone(gate.evaluate(missing))
            self.assertTrue(gate.evaluate(frame)[1].stop)
            self.assertEqual(window.loop.poll().status, 'minimized')
            self.assertTrue(gate.evaluate(missing)[1].stop)

            window.session.stop()
            clock.return_value = 2000
            window.session.start(123)
            self.assertEqual(window.loop.poll().status, 'minimized')
            self.assertIsNone(gate.evaluate(missing))

        test_dev_tray.TrayTests.run_window(self, False, exercise)

    def test_frozen_character_frame_holds_all_input_until_a_new_sequence(self):
        def exercise(window):
            def frame(sequence=None, token=None):
                image, _ = render_old(1484, {
                    'addon_version_code': DEV_VERSION, 'action_avail': 0x800000,
                    'master_switch': 0x00ff00, 'player_valid': 0x00ff00,
                    'player_casting': 0xff0000, 'gcd': 0xff0000,
                    'player_in_combat': 0xff0000, 'druid_talents': 0x0a0000,
                })
                if sequence is None and token is None:
                    return image
                rows = [list(row) for row in image.rows]
                def paint(start, packet):
                    checksum = 0
                    for word in packet:
                        checksum = (checksum * 31 + word) % 0xfefffd
                    for row, color in enumerate([*packet, checksum], start=start):
                        for y in range(row * 4, (row + 1) * 4):
                            rows[y][6] = color
                if sequence is not None:
                    paint(34, [0x574244, sequence * 256, 0xffffff, 0xffffff, 0, 0xffffff, 0xffffff])
                if token is not None:
                    paint(94, [0x574245, token])
                return RGBImage(rows)

            state = {'dxgi': frame(254), 'printwindow': frame(255), 'time': 100000, 'desktop': None}
            windows = SimpleNamespace(is_iconic=lambda hwnd: False,
                window_rect=lambda hwnd: Rect(0, 0, 64, 1500),
                client_rect=lambda hwnd: Rect(0, 0, 64, 1500),
                client_to_screen=lambda hwnd: (0, 0))
            dxgi = SimpleNamespace(capture=lambda *args: state['dxgi'])
            printed = SimpleNamespace(capture=Mock(side_effect=lambda *args: state['printwindow']))
            window.loop.capture = WindowCapture(windows, dxgi, printed, desktop_status=lambda: state['desktop'])
            sent = []
            sender = SimpleNamespace(send=lambda key, **kw: sent.append(key) is None,
                backend=SimpleNamespace(now_ms=lambda: state['time'], Sleep=lambda ms: None),
                status='测试后端投递成功', channel='test')
            window.sender = window.dispatcher.sender = sender
            window.scheduler.clock_ms = window.session.monotonic_ms = lambda: state['time']
            window.controller.prepare(state['dxgi'])
            profile = Profile(-1, 1484, '德鲁伊', '', '卡帧测试', '', '', '', '',
                              tuple(parse_rules([{'action': 'spell_17056', 'when': ['avail', 17056]}])))
            window.controller.selection = replace(window.controller.selection, active_profile=profile)
            window.toggle_monitor()
            release = window._release_navigation_key = Mock(return_value=True)
            navigate = window._poll_navigation = Mock()

            def poll(sequence, advance, *, backend='dxgi', token=None):
                state[backend] = frame(sequence, token)
                state['time'] += advance
                return window.poll_once()

            self.assertEqual(poll(254, 0).status, 'frame_held')
            self.assertEqual(sent, [])
            self.assertIsNotNone(poll(255, 250).tick)
            self.assertEqual(sent, ['SHIFT-F2'])
            release.reset_mock()
            navigate.reset_mock()
            self.assertEqual(poll(255, 1000).status, 'frame_held')
            self.assertTrue(window.loop.capture.prefer_printwindow)
            self.assertIn('游戏画面未更新', window.ui.suggestions.toPlainText())
            self.assertEqual(poll(255, 5000, backend='printwindow').status, 'frame_held')
            self.assertEqual(poll(None, 250, backend='printwindow').status, 'frame_held')
            self.assertEqual(sent, ['SHIFT-F2'])
            self.assertEqual(release.call_count, 3)
            navigate.assert_not_called()
            self.assertEqual(window.ui.log_view.toPlainText().count('游戏画面未更新'), 1)

            result = poll(0, 250, backend='printwindow')
            self.assertEqual(result.capture.backend, 'printwindow')
            self.assertIsNotNone(result.tick)
            self.assertEqual(sent, ['SHIFT-F2', 'SHIFT-F2'])
            navigate.assert_called_once()
            self.assertIn('游戏画面已更新，恢复监控', window.ui.log_view.toPlainText())

            self.assertEqual(poll(1, 250, backend='printwindow', token=100).status, 'frame_held')
            self.assertIsNotNone(poll(2, 250, backend='printwindow', token=100).tick)
            revision = window._unattended_revision
            prior_plan = window._leveling_destination = object()
            dispatch = window.dispatcher.state
            dispatch.auras.suppression_until['old_buff'] = state['time'] + 60000
            dispatch.local_gcd_until_ms = state['time'] + 60000
            success_count = dispatch.success_count
            self.assertEqual(poll(3, 250, backend='printwindow').status, 'frame_held')
            self.assertIsNotNone(poll(4, 250, backend='printwindow', token=100).tick)
            self.assertIs(window._leveling_destination, prior_plan)
            self.assertEqual(window._unattended_revision, revision)

            self.assertEqual(poll(None, 250, backend='printwindow', token=200).status, 'frame_held')
            self.assertIsNone(window._leveling_destination)
            self.assertEqual(window._unattended_revision, revision + 1)
            self.assertEqual(dispatch.auras.suppression_until, {})
            self.assertEqual(dispatch.local_gcd_until_ms, 0)
            self.assertEqual(dispatch.success_count, success_count)
            self.assertEqual(poll(None, 100, backend='printwindow', token=200).status, 'frame_held')
            self.assertEqual(poll(1, 100, backend='printwindow', token=200).status, 'frame_held')
            self.assertIsNotNone(poll(2, 250, backend='printwindow', token=200).tick)
            self.assertEqual(dispatch.success_count, success_count + 1)

            release.reset_mock()
            navigate.reset_mock()
            printed.capture.reset_mock()
            prior_plan = window._leveling_destination = object()
            state['desktop'] = 'desktop_locked'
            self.assertEqual(poll(2, 1000, backend='printwindow', token=200).status, 'desktop_locked')
            self.assertEqual(poll(2, 1000, backend='printwindow', token=200).status, 'desktop_locked')
            state['desktop'] = 'desktop_disconnected'
            self.assertEqual(poll(2, 1000, backend='printwindow', token=200).status, 'desktop_disconnected')
            self.assertIn('会话已断开', window.ui.suggestions.toPlainText())
            self.assertEqual(window.ui.log_view.toPlainText().count('Windows 已锁屏'), 1)
            self.assertEqual(release.call_count, 3)
            self.assertEqual(dispatch.success_count, success_count + 1)
            navigate.assert_not_called()
            printed.capture.assert_not_called()

            state['desktop'] = None
            self.assertEqual(poll(2, 250, backend='printwindow', token=200).status, 'frame_held')
            self.assertEqual(poll(2, 250, backend='printwindow', token=200).status, 'frame_held')
            navigate.assert_not_called()
            self.assertEqual(poll(3, 250, backend='printwindow', token=200).status, 'sent')
            self.assertEqual(dispatch.success_count, success_count + 2)
            self.assertIs(window._leveling_destination, prior_plan)

            window.loop.capture.desktop_status = Mock(side_effect=(None, 'desktop_locked'))
            self.assertEqual(poll(4, 1750, backend='printwindow', token=200).status, 'movement_stopping')
            self.assertEqual(dispatch.success_count, success_count + 2)

        test_dev_tray.TrayTests.run_window(self, False, exercise)

    def test_capture_hold_restarts_exit_and_crossing_confirmation(self):
        from wowbuddy.engine.character_state import NavigationState
        from wowbuddy.automation.navigation import MapDestination
        from wowbuddy.engine.runtime import PollResult
        from wowbuddy.automation.walking_route import WalkingTrip, plan_walking_route

        def exercise(window):
            window.session.start(123)
            state = window.session.state
            session = state.hwnd, state.elapsed_started_ms, window._unattended_revision
            navigator = window._map_navigator = Mock()
            for hold in ('frame_held', 'desktop_locked', 'capture_failed'):
                with self.subTest(hold=hold):
                    legs = plan_walking_route(1436, 1433, 22, 'alive')
                    leg = legs[0]
                    goal = MapDestination(1433, 25.5, 59.4, 'alive', '练级区')
                    living = WalkingTrip(session, legs, goal, level=22)
                    ghost = WalkingTrip(session, legs, replace(goal, life='ghost', label='尸体'))
                    window._leveling_trip = ('alliance', 22, living)
                    window._corpse_trip = ghost

                    position = NavigationState('alive', 1, leg.source, *leg.points[-1],
                                               0, 1000, 1000, (87, 65, 68))
                    probe, _ = living.observe(position, now_ms=100)
                    waiting = replace(position, sequence=2, x=probe.x, y=probe.y)
                    self.assertIsNone(living.observe(waiting, now_ms=200)[0])
                    across = replace(position, life='ghost', map_id=leg.destination)
                    self.assertEqual(ghost.observe(across, now_ms=200), (None, None))

                    held = PollResult(hold, CaptureResult(hold, backend='printwindow'))
                    navigator.pause.reset_mock()
                    with patch.object(window.loop, 'poll', return_value=held):
                        self.assertIs(window.poll_once(), held)
                    navigator.pause.assert_called_once_with(session)

                    self.assertEqual(living.observe(replace(waiting, sequence=3), now_ms=10_000), (None, None))
                    self.assertEqual(tuple(living.legs), legs)
                    self.assertFalse(living.blocked_legs)
                    self.assertEqual(ghost.observe(replace(across, sequence=2), now_ms=10_000), (None, None))
                    self.assertEqual(ghost.observe(replace(across, sequence=2), now_ms=10_100), (None, None))
                    self.assertEqual(tuple(ghost.legs), legs)
                    self.assertIn('已确认进入', ghost.observe(replace(across, sequence=3), now_ms=10_250)[1])
                    self.assertEqual(tuple(ghost.legs), legs[1:])

        test_dev_tray.TrayTests.run_window(self, False, exercise)

    def test_capture_hold_preserves_camp_receipts_and_restarts_waits(self):
        from math import pi
        from tests.test_leveling_route import ArrivalPullTests
        from wowbuddy.engine.character_state import TargetBearing
        from wowbuddy.automation.navigation import TargetApproach
        from wowbuddy.engine.runtime import PollResult

        def exercise(window):
            window.session.start(10)
            state = window.session.state
            session = state.hwnd, state.elapsed_started_ms, window._unattended_revision
            for hold in ('frame_held', 'desktop_locked', 'capture_failed'):
                with self.subTest(hold=hold):
                    camp = ArrivalPullTests()
                    camp.setUp()
                    camp.session = session
                    camp.position = replace(camp.position, continuous=True)
                    window._arrival_pull = camp.pull
                    held = PollResult(hold, CaptureResult(hold, backend='printwindow'))

                    def pause():
                        with patch.object(window.loop, 'poll', return_value=held):
                            self.assertIs(window.poll_once(), held)

                    camp.step(1, 0, revision=10)
                    self.assertIn('已发出', camp.step(2, 250, revision=10))
                    camp.step(3, 2250, ack=1, revision=10)
                    self.assertIn('第 2 个方向', camp.step(4, 2500, ack=1, revision=10))
                    pause()
                    self.assertIsNone(camp.step(5, 10_000, ack=1, revision=10))
                    self.assertIn('第 2 个方向', camp.step(6, 10_250, ack=1, revision=10))
                    self.assertIsNone(camp.step(7, 10_500, ack=1, revision=10, heading=pi / 2))
                    self.assertIn('已发出', camp.step(8, 10_750, ack=1, revision=10, heading=pi / 2))
                    camp.foreground.pulse.assert_called()
                    self.assertEqual(camp.dispatcher.dispatch.call_count, 2)

                    fields = dict(ack=2, revision=11, target='ON', range_blocked=True, heading=pi / 2)
                    self.assertIn('确认首次选怪', camp.step(9, 11_000, **fields))
                    camp.foreground.pulse.reset_mock()
                    movement = Mock()
                    movement.keep_forward.return_value = False
                    approach = window._target_approach = TargetApproach(movement)
                    bearing = TargetBearing(11, 0.5, 37, continuous=True)
                    approach.observe(session, replace(camp.position, sequence=8), bearing)
                    approach.observe(session, replace(camp.position, sequence=9), bearing)
                    self.assertTrue(approach.pursuing)
                    pause()
                    self.assertFalse(approach.pursuing)
                    displaced = replace(camp.position, x=camp.position.x + 5, sequence=10)
                    self.assertIsNone(approach.observe(session, displaced, bearing))
                    self.assertIsNone(approach.observe(session, replace(displaced, sequence=11), bearing))
                    self.assertEqual(movement.hold_forward.call_count, 2)
                    self.assertIsNone(camp.step(10, 25_000, **fields))
                    self.assertIsNone(camp.step(11, 25_250, **fields))
                    camp.foreground.pulse.assert_not_called()
                    self.assertIsNone(camp.step(12, 33_000, **fields))
                    self.assertIn('已请求重选一次', camp.step(13, 33_250, **fields))

        test_dev_tray.TrayTests.run_window(self, False, exercise)

    def test_capture_hold_requires_fresh_revival_hover_and_corpse_wait(self):
        from wowbuddy.engine.character_state import DeathState, NavigationState
        from wowbuddy.automation.death_recovery import AutomaticRevival, CorpseAccess
        from wowbuddy.automation.navigation import MapDestination
        from wowbuddy.engine.runtime import PollResult

        def exercise(window):
            window.session.start(123)
            state = window.session.state
            session = state.hwnd, state.elapsed_started_ms, window._unattended_revision
            rect = Rect(0, 0, 800, 600)
            for hold, life in (('frame_held', 'dead'), ('desktop_locked', 'ghost'), ('capture_failed', 'ghost')):
                with self.subTest(hold=hold, life=life):
                    mouse = Mock()
                    revival = window._automatic_revival = AutomaticRevival(mouse)
                    popup = DeathState(life, 1, (5000, 6000), False, (52, 36, 36), 'ready')
                    corpse = MapDestination(52, 36, 36, 'ghost', '尸体')
                    at_corpse = NavigationState('ghost', 1, 52, 36, 36, 0, 1000, 800, (87, 65, 68))
                    access = window._corpse_access = CorpseAccess()

                    def poll(sequence, now, *, hovered=False):
                        reading = replace(popup, sequence=sequence, hovered=hovered)
                        return revival.observe(session, session[0], reading, rect, now)

                    self.assertIn('已定位', poll(1, 0))
                    self.assertIn('已点击', poll(2, 250, hovered=True))
                    poll(3, 3000)
                    self.assertEqual(mouse.move.call_count, 2)
                    self.assertEqual(access.observe(session, at_corpse, corpse, 3000), (corpse, None))
                    held = PollResult(hold, CaptureResult(hold, backend='printwindow'))
                    with patch.object(window.loop, 'poll', return_value=held):
                        self.assertIs(window.poll_once(), held)

                    self.assertIsNone(poll(4, 3250, hovered=True))
                    mouse.click.assert_called_once()
                    self.assertEqual(revival.attempts, 1)
                    self.assertEqual(access.observe(session, replace(at_corpse, sequence=2), corpse, 6000),
                                     (corpse, None))
                    poll(5, 6000, hovered=True)
                    self.assertEqual(mouse.move.call_count, 3)
                    self.assertIsNone(poll(5, 6250, hovered=True))
                    mouse.click.assert_called_once()
                    self.assertIn('已点击', poll(6, 6500, hovered=True))
                    self.assertEqual(revival.attempts, 2)
                    self.assertIn('尝试从附近接近',
                                  access.observe(session, replace(at_corpse, sequence=3), corpse, 7500)[1])

        test_dev_tray.TrayTests.run_window(self, False, exercise)

    def test_new_protocol_high_bit_to_dispatch_and_stopping(self):
        for protocol,fallback in (('old',False),('old',True),('readable',False),('readable',True)):
            with self.subTest(protocol=protocol,printwindow_fallback=fallback):
                def exercise(window):
                    if protocol == 'old':
                        field = next(field for field in window.pipeline.old.contract['commonFields']
                                     if field['id'] == 'trinket1_cd')
                        field['type'] = 'CustomCooldown'

                    def frame(bits,master=True):
                        values={'addon_version_code':DEV_VERSION,'action_avail':bits,
                            'master_switch':0x00ff00 if master else 0xff0000,
                            'player_casting':0xff0000,'gcd':0xff0000,
                            'player_in_combat':0xff0000,'druid_talents':0x0a0000,'trinket1_cd':0x000A0F}
                        return render_old(1484,values)[0] if protocol=='old' else render_readable(1484,values)
                    state={'image':frame(0x800000),'minimized':False,'time':100000}
                    windows=SimpleNamespace(is_iconic=lambda hwnd:state['minimized'],
                        window_rect=lambda hwnd:Rect(0,0,64,1500),
                        client_rect=lambda hwnd:Rect(0,0,64,1500),
                        client_to_screen=lambda hwnd:(0,0))
                    dxgi=SimpleNamespace(capture=lambda rect,width:None if fallback else state['image'])
                    prints=SimpleNamespace(capture=lambda *args:state['image'])
                    window.loop.capture=WindowCapture(windows,dxgi,prints)
                    sent=[]
                    def send(key,**kwargs):sent.append(key);return True
                    sender=SimpleNamespace(send=send,backend=SimpleNamespace(now_ms=lambda:state['time'],Sleep=lambda ms:None),
                        status='测试后端投递成功',channel='test')
                    window.sender=window.dispatcher.sender=sender
                    window.scheduler.clock_ms=lambda:state['time']
                    window.session.monotonic_ms=lambda:state['time']
                    window.controller.prepare(state['image'])
                    profile=Profile(-1,1484,'德鲁伊','','协议集成测试','','','','',
                        tuple(parse_rules([
                            {'action':'spell_1126','when':['avail',1126]},
                            {'action':'spell_17056','when':['avail',17056]}])))
                    window.controller.selection=replace(window.controller.selection,active_profile=profile)
                    window.toggle_monitor()
                    state['time']+=800
                    result=window.poll_once()
                    self.assertEqual(result.capture.backend,'printwindow' if fallback else 'dxgi')
                    self.assertIsNotNone(result.tick)
                    self.assertTrue(result.tick.decision.frame.ok)
                    if protocol == 'old':
                        self.assertEqual(window.session.state.decoded_fields['trinket1_cd'], '#000A0F')
                    self.assertEqual([c.action for c in result.tick.decision.candidates],['spell_17056'])
                    self.assertEqual(sent,['SHIFT-F2'])
                    self.assertEqual(window.dispatcher.state.success_count,1)
                    self.assertEqual(window.ui.sent_label.text(),'0')
                    self.assertEqual(window.ui.send_status_label.text(),'发键：累计 1 条')
                    self.assertEqual(window.ui.fps_label.text(),'1.3')
                    self.assertIn('1.3 fps',window.ui.frame_status_label.text())
                    self.assertEqual(window.session.state.decoded_fields['action_avail'],'16777217')
                    state['time']+=5000
                    state['image']=frame(0)
                    result=window.poll_once()
                    self.assertEqual(result.tick.decision.candidates,())
                    self.assertEqual(window.ui.sent_label.text(),'1')
                    self.assertEqual(sent,['SHIFT-F2'])
                    state['time']+=5000
                    state['image']=frame(0xffffff,False)
                    window.poll_once()
                    self.assertEqual(sent,['SHIFT-F2'])
                    state['minimized']=True
                    result=window.poll_once()
                    self.assertEqual(result.capture.status,'minimized')
                    self.assertEqual(window.ui.status_label.text(),'游戏窗口已最小化，恢复后自动继续')
                    self.assertEqual(sent,['SHIFT-F2'])
                    state['minimized']=False
                    state['time']+=5000
                    window.poll_once()
                    restored_status=window.ui.status_label.text()
                    self.assertNotIn('最小化',restored_status)
                    window.watch_once()
                    self.assertEqual(window.ui.status_label.text(),restored_status)
                    window.toggle_monitor()
                    result=window.poll_once()
                    self.assertEqual(result.status,'inactive')
                    # 原0a2070仅清内部计数；089570实际尝试主键才刷新累计文案。
                    window.toggle_monitor()
                    state['time']+=5000
                    state['minimized']=False
                    window.poll_once()
                    self.assertEqual(window.dispatcher.state.success_count,0)
                    self.assertEqual(window.ui.sent_label.text(),'0')
                    self.assertEqual(window.ui.send_status_label.text(),'发键：累计 1 条')
                    state['image']=frame(0x800000)
                    sender.send=lambda *args,**kwargs:False
                    state['time']+=5000
                    result=window.poll_once()
                    self.assertEqual(result.tick.dispatch.status,'failed')
                    self.assertEqual(window.ui.send_status_label.text(),'发键：累计 0 条')
                    failed_status=window.ui.status_label.text()
                    window.dispatcher.sender=None
                    state['time']+=5000
                    result=window.poll_once()
                    self.assertEqual(result.tick.dispatch.status,'no_sender')
                    self.assertEqual(window.ui.status_label.text(),failed_status)
                    self.assertEqual(window.ui.send_status_label.text(),'发键：累计 0 条')
                    state['image']=None
                    state['time']+=5000
                    result=window.poll_once()
                    self.assertEqual(result.status,'capture_failed')
                    self.assertEqual(window.ui.status_label.text(),'抓屏失败')
                test_dev_tray.TrayTests.run_window(self,False,exercise)
