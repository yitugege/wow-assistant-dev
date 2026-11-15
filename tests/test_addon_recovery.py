"""实际设置控件、TOC、色条和桌面调度链；物品使用由离线宿主模拟。"""
import json
import sys
import unittest
from unittest.mock import Mock

from tests import test_addon_full_load as full_load

ROOT = full_load.ROOT
sys.path.insert(0, str(ROOT / 'desktop'))

from wowbuddy.arrival_pull import ArrivalPull
from wowbuddy.assets import Assets
from wowbuddy.auto_target import key_for_index
from wowbuddy.character_state import decode_navigation_state, decode_target_bearing
from wowbuddy.dev_protocol import RECOVERY_CONFIG_BASE, RECOVERY_DISABLED_BASE
from wowbuddy.dispatch import ActionDispatcher
from wowbuddy.navigation import MapDestination, TargetApproach
from wowbuddy.pixel_geometry import RGBImage
from wowbuddy.scheduler import Scheduler


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        prelude = (ROOT / 'tests/addon_login_host.lua').read_text('utf-8') + """
            health=100; powerValue=100; speed=0; inventory={[5349]=3,[5350]=4}
            fixtureTargetGUID='Creature-1'
            function UnitGUID() return fixtureTargetGUID end
            function UnitIsPlayer(unit) return unit=='player' end
            function UnitPlayerControlled(unit) return unit=='player' end
            function UnitIsTapDenied() return false end
            function UnitThreatSituation(unit, target)
              if unit=='player' and target=='target' and combat and targetAlive then return 1 end
            end
            local rawPower=UnitPower
            function UnitHealth(unit)
              if unit=='player' then error('protected health') end
              return 100
            end
            function UnitPower(unit, powerType)
              if unit=='player' and powerType==0 then error('protected mana') end
              return rawPower(unit, powerType)
            end
            Enum={LuaCurveType={Step=1}}
            C_CurveUtil={CreateColorCurve=function()
              return {points={},SetType=function() end,
                AddPoint=function(self,x,color) self.points[#self.points+1]={x,color} end}
            end}
            local function sampleCurve(curve, percent)
              local selected=nil
              for _,point in ipairs(curve.points) do
                if point[1]<=percent/100 then selected=point[2] end
              end
              return selected
            end
            function UnitHealthPercent(unit, useMax, curve)
              return sampleCurve(curve, unit=='player' and health or 100)
            end
            function UnitPowerPercent(unit, powerType, useMax, curve)
              return sampleCurve(curve, powerType==0 and powerValue or 0)
            end
            function GetUnitSpeed() return speed end
            function GetItemCount(id) return inventory[id] or 0 end
            function GetBindingAction(key, override)
              if override then
                if key==fixtureRecoveryClaimedKey then return 'JUMP' end
                for _,frame in ipairs(frames) do
                  local binding=frame.bindings and frame.bindings[key]
                  if binding then return 'CLICK '..binding.button..':'..binding.mouse end
                end
              end
              return key==fixtureNativeBindingKey and 'JUMP' or ''
            end
            function IsSpellKnown(id)
              return (id==837 and not fixtureStarterMage) or (id==133 and fixtureStarterMage==true)
                or (fixtureConjureKnown and fixtureConjureKnown[id])==true
            end
            function IsUsableSpell(id)
              if fixtureConjureKnown and fixtureConjureKnown[id] then return true,fixtureConjureNoMana==true end
              return IsSpellKnown(id),fixtureInsufficientMana==true
            end
            function GetSpellCooldown() return 0,0,1 end
            C_Spell={IsSpellInRange=function(id,unit)
              return unit=='target' and targetAlive and (id==837 or (id==133 and fixtureFireballInRange==true))
            end}
        """
        self.lua, _ = full_load.AddonFullLoadTests().load(full_load.SOURCE, 'WowBuddyDev', prelude)
        self.g = self.lua.globals()
        self.g.EmitFixtureEvent('ADDON_LOADED', 'WowBuddyDev')
        self.g.EmitFixtureEvent('PLAYER_LOGIN')
        self.addon = self.g.WowBuddyDev
        self.addon.DB.masterSwitch = True
        self.addon.SetAutoTargetEnabled(True)
        self.addon.RebuildPixelBars()
        self.addon.debugFrame.Hide(self.addon.debugFrame)
        self.render = self.lua.execute("""
            for _,frame in ipairs(frames) do
                local callback=frame.scripts.OnUpdate
                if callback and debug.getinfo(callback,'S').source=='@PixelBar.lua' then
                    return function(delta) now=now+delta;callback(frame,delta) end
                end
            end
            error('no PixelBar callback')
        """)
        self.click = self.lua.execute("""
            return function(parent, caption)
              for _,frame in ipairs(frames) do
                if frame.parent==parent and frame.fontString and frame.fontString:GetText()==caption then
                  return frame.scripts.OnClick(frame)
                end
              end
              error('button not found '..caption)
            end
        """)
        self.sender = Mock(status='fixture', channel='fixture')
        self.sender.send.return_value = True
        self.sender.backend.now_ms = lambda: round(self.g.now * 1000)
        self.scheduler = Scheduler(Assets.load(ROOT/'assets').pipeline(),
                                   ActionDispatcher(self.sender), self.sender.backend.now_ms)
        self.profile = next(p for p in json.loads((ROOT/'assets/rotations.json').read_bytes())['rotations']
                            if p['id'] == 1)

    def game_image(self, delta=0.25):
        self.render(delta)
        pixels = [[0x0D0D0D] * 24 for _ in range(1200)]
        for rect in self.g.visiblePixelRectangles().values():
            rgb = (round(rect.r * 255) << 16) | (round(rect.g * 255) << 8) | round(rect.b * 255)
            for y in range(int(rect.y), int(rect.y + rect.height)):
                for x in range(int(rect.x), int(rect.x + rect.width)):
                    pixels[y][x] = rgb
        return RGBImage(pixels)

    def tick(self, delta=0.25):
        self.image = self.game_image(delta)
        result = self.scheduler.tick(self.image, hwnd=10, send_interval_ms=100, selected_profile=self.profile)
        self.assertTrue(result.decision.frame.ok, result.status)
        return result

    def open_panel(self):
        self.click(self.addon.configFrame, '自动恢复设置…')
        panel = self.g.WowBuddyDevRecoverySettings
        self.assertTrue(panel.IsShown(panel))
        return panel

    def configure(self, **changes):
        panel = self.open_panel()
        inputs = dict(healthStart='61', healthResume='87', manaStart='49', manaResume='92',
                      food='5349', water='5350') | changes
        self.g.WowBuddyDevRecoveryEnabled.SetChecked(self.g.WowBuddyDevRecoveryEnabled, 1)
        for name, text in inputs.items():
            box = self.g['WowBuddyDevRecovery_' + name]
            box.SetText(box, text)
        self.click(panel, '保存')
        return panel

    def click_item(self, kind):
        button = self.addon.GetSecureButton('recovery_' + kind)
        button.scripts.OnClick(button, 'LeftButton', True)
        button.scripts.OnClick(button, 'LeftButton', False)

    def test_unattended_frost_profile_uses_fireball_until_frostbolt_is_learned(self):
        pipeline = self.scheduler.pipeline
        self.g.fixtureStarterMage = True
        self.g.EmitFixtureEvent('SPELLS_CHANGED')
        self.g.fixtureFireballInRange = True
        self.assertIsNone(self.tick().selected)
        pipeline.unattended_grinding = True
        pipeline.probe_attack_range = True
        self.g.fixtureFireballInRange = False
        self.lua.execute('function UnitDistanceSquared() return 1600,true end')
        out_of_range = self.tick()
        self.assertEqual(out_of_range.decision.fields['known_116'], 'OFF')
        self.assertEqual(out_of_range.decision.fields['known_133'], 'ON')
        self.assertEqual(out_of_range.decision.fields['range_133'], 'OFF')
        self.assertIsNone(out_of_range.selected)
        self.assertTrue(out_of_range.decision.attack_blocked_by_range)
        self.g.fixtureFireballInRange = True
        self.g.speed = 5
        self.assertIsNone(self.tick().selected)
        self.g.speed = 0
        self.g.fixtureInsufficientMana = True
        self.assertIsNone(self.tick().selected)
        self.g.fixtureInsufficientMana = False
        self.sender.send.assert_not_called()

        self.configure(manaStart='0')
        self.g.health = 60
        self.assertEqual(self.tick().selected.action, 'recovery_food')
        self.click_item('food')
        self.g.inventory[5349] = 2
        self.assertEqual(self.tick().status, 'stopped')
        self.g.health = 87
        fireball = self.tick().selected
        self.assertEqual((fireball.action, fireball.key), ('spell_133', 'NUMPAD6'))
        self.assertEqual(self.addon.GetBoundMacro('class_NUMPAD6'), '/cast [harm,nodead,nochanneling] 火球术')
        self.assertIn('尚未学会寒冰箭', fireball.reason)

        self.assertTrue(self.addon.SetPostKillAutoTargetEnabled(True))
        self.g.combat = True
        self.assertEqual(self.tick(2).selected.action, 'spell_133')
        self.g.targetAlive, self.g.combat = False, False
        self.g.EmitFixtureEvent('PLAYER_REGEN_ENABLED')
        self.assertEqual(self.tick(2).selected.action, 'auto_target')
        self.g.targetAlive, self.g.fixtureTargetGUID = True, 'Creature-2'
        self.assertEqual(self.tick(2).selected.action, 'spell_133')

        self.g.fixtureStarterMage = False
        self.g.EmitFixtureEvent('SPELLS_CHANGED')
        trained = self.tick(2)
        self.assertEqual(trained.decision.fields['known_116'], 'ON')
        self.assertEqual([candidate.action for candidate in trained.decision.candidates], ['spell_116'])
        self.assertEqual(trained.selected.action, 'spell_116')

    def test_unattended_frost_uses_fire_blast_during_low_health_melee_combat(self):
        from dataclasses import replace

        pipeline = self.scheduler.pipeline
        self.g.fixtureConjureKnown = self.lua.table_from({2137: True})
        self.g.EmitFixtureEvent('SPELLS_CHANGED')
        self.g.combat, self.g.health = True, 37
        self.lua.execute('''
            function UnitDistanceSquared() return 25,true end
            local oldRange=C_Spell.IsSpellInRange
            function C_Spell.IsSpellInRange(id,unit)
                if id==2137 then return unit=='target' and targetAlive end
                return oldRange(id,unit)
            end
        ''')
        image = self.game_image()
        ordinary = pipeline.evaluate(image, selected_profile=self.profile)
        self.assertEqual(ordinary.fields['player_health_pct'], '37')
        self.assertEqual(ordinary.fields['range_2136'], 'ON')
        self.assertEqual([item.action for item in ordinary.candidates], ['spell_116'])
        pipeline.unattended_grinding = True
        decision = pipeline.evaluate(image, selected_profile=self.profile)
        self.assertEqual([item.action for item in decision.candidates], ['spell_2136', 'spell_116'])
        self.assertIn('贴身战斗', decision.candidates[0].reason)
        finisher = next(item for item in decision.thresholds if item.action == 'spell_2136')

        def candidates(changes, *, profile=self.profile, settings=None):
            frame = replace(decision.frame, values=dict(decision.frame.values, **changes))
            return pipeline.generate(pipeline.prepare_frame(frame, selected_profile=profile, settings=settings)).candidates

        for changes in ({'player_health_pct': '45'}, {'player_health_pct': '—'}, {'distance': '8.0'},
                        {'distance': '—'}, {'range_2136': 'OFF'}, {'range_2136': 'UNKNOWN'},
                        {'known_2136': 'OFF'}, {'action_avail': '16'}, {'player_in_combat': 'OFF'},
                        {'gcd': 'ON'}, {'player_casting': '读条中'}, {'target_valid': 'OFF'}):
            with self.subTest(changes=changes):
                self.assertNotIn('spell_2136', [item.action for item in candidates(changes)])
        self.assertNotIn('spell_2136', [item.action for item in candidates({}, settings={finisher.key: 0})])
        self.assertNotIn('spell_2136', [item.action for item in candidates({}, profile=dict(self.profile, author='玩家'))])
        below_finisher = [item for item in candidates({'target_health_pct': '19'}) if item.action == 'spell_2136']
        self.assertEqual(len(below_finisher), 1)
        self.assertIn('收尾', below_finisher[0].reason)
        sent = self.tick()
        self.assertEqual((sent.selected.action, sent.selected.key), ('spell_2136', 'NUMPAD7'))
        self.assertTrue(sent.dispatch.success)

    def test_unattended_arcane_prepares_learned_armor_and_uses_single_target_finisher(self):
        from dataclasses import replace
        from types import SimpleNamespace
        from unittest.mock import patch

        profile = next(p for p in json.loads((ROOT/'assets/rotations.json').read_bytes())['rotations']
                       if p['id'] == 14)
        pipeline = self.scheduler.pipeline
        pipeline.unattended_grinding = pipeline.unattended_travel = True
        self.configure()
        self.g.fixtureConjureKnown = self.lua.table_from({168: True, 2137: True, 5144: True})
        self.g.EmitFixtureEvent('SPELLS_CHANGED')
        self.lua.execute('''
            function UnitExists(unit) return unit=='player' end
            local original=UnitHealthPercent
            function UnitHealthPercent(unit, useMax, curve)
                if unit=='target' and not targetAlive then return curve.points[1][2] end
                return original(unit,useMax,curve)
            end
        ''')
        self.g.targetAlive = False
        with patch('wowbuddy.character_state.decode_navigation_state',
                   return_value=SimpleNamespace(sight_blocked=False, idle_key_index=8)):
            frame, _ = pipeline.decode(self.game_image())
        self.assertEqual(frame.values.get('mage_prep_ready'), 'ON', {k: frame.values.get(k) for k in
                         ('target_valid', 'target_health_pct', 'player_in_combat', 'player_moving')})
        # 宿主不实现正式服光环接口，用明确的空光环帧测试恢复后的补甲。
        frame = replace(frame, values=dict(frame.values, frost_armor='OFF', ice_armor='OFF', mage_armor='OFF'))

        def actions(base, **changes):
            sample = replace(base, values=dict(base.values, **changes))
            return pipeline.generate(pipeline.prepare_frame(sample, selected_profile=profile)).candidates

        ready = actions(frame)
        self.assertEqual([(a.action, a.key) for a in ready], [('spell_168', 'NUMPAD2')],
                         {k: frame.values.get(k) for k in ('frost_armor', 'ice_armor', 'mage_armor', 'known_168',
                          'known_7302', 'known_6117', 'player_casting', 'action_avail', 'gcd', 'master_switch', 'ttf')})
        self.assertEqual(self.addon.GetBoundMacro('class_NUMPAD2'), '/cast [@player,nochanneling] 霜甲术')
        for changes in ({'mage_prep_ready': 'OFF'}, {'frost_armor': 'ON'}, {'ice_armor': 'ON'},
                        {'mage_armor': 'UNKNOWN'}, {'known_6117': 'ON'}, {'player_moving': 'ON'},
                        {'gcd': 'ON'}, {'player_casting': '读条中'}, {'player_health_pct': '30'}):
            with self.subTest(changes=changes):
                self.assertNotIn('spell_168', [a.action for a in actions(frame, **changes)])

        self.lua.execute('''
            function UnitExists(unit) return unit=='player' or unit=='target' end
            function UnitCanAttack(_,unit) return unit=='target' end
            function UnitDistanceSquared() return 25,true end
            C_Spell.IsSpellInRange=function(id,unit) return unit=='target' and (id==2137 or id==5144) end
        ''')
        self.g.targetAlive, self.g.combat, self.g.health = True, True, 37
        combat, _ = pipeline.decode(self.game_image())
        for changes in ({}, {'player_health_pct': '70', 'target_health_pct': '18'}):
            with self.subTest(changes=changes):
                self.assertNotIn('spell_2136', [a.action for a in actions(combat, **changes)])

        from wowbuddy.character_state import CastFeedback

        full_set = dict(known_400574='ON', range_400574='ON', known_5143='ON', range_5143='ON',
                        known_2136='OFF', action_avail=str((1 << 8) | (1 << 12)))
        target = (42, 1)
        pipeline._observe_arcane_sequence(target, None)

        def damage(**changes):
            fields = dict(full_set, **changes)
            return [a.action for a in actions(combat, **fields) if a.tag in ('输出', '填充', '触发', 'AOE')]

        self.assertEqual(damage(), ['spell_400574'])
        pipeline._observe_arcane_sequence(target, CastFeedback(1, 400574, ('失败',)))
        self.assertEqual(damage(), ['spell_400574'])
        for sequence, receipt, next_spell in ((2, 1239696, 5143), (3, 5144, 5143), (4, 5144, 400574)):
            feedback = CastFeedback(sequence, receipt, ('成功',))
            pipeline._observe_arcane_sequence(target, feedback)
            pipeline._observe_arcane_sequence(target, feedback)
            self.assertEqual(damage(), [f'spell_{next_spell}'])
        self.assertEqual(damage(known_2136='ON', range_2136='ON'), ['spell_400574'])
        all_ready = str(int(full_set['action_avail']) | (1 << 7))
        for out_of_range in ('OFF', 'UNKNOWN'):
            self.assertEqual(damage(known_2136='ON', range_2136=out_of_range, action_avail=all_ready),
                             ['spell_400574'])
        self.assertEqual(damage(known_2136='ON', range_2136='ON', action_avail=all_ready), ['spell_2136'])
        self.assertEqual(damage(arcane_blast_debuff='ON'), ['spell_5143'])
        pipeline._observe_arcane_sequence(target, CastFeedback(5, 2137, ('成功',)))
        self.assertEqual(damage(), ['spell_400574'])
        for sequence, receipt in ((6, 400574), (7, 5144), (8, 5144), (9, 400574)):
            pipeline._observe_arcane_sequence(target, CastFeedback(sequence, receipt, ('成功',)))
        self.assertEqual(damage(), ['spell_5143'])
        pipeline._observe_arcane_sequence((42, 2), CastFeedback(9, 400574, ('成功',)))
        self.assertEqual(damage(), ['spell_400574'])
        self.assertEqual(damage(arcane_blast_debuff='ON'), ['spell_5143'])

    def test_disabled_recovery_releases_handoff_only_when_configured_resources_are_ready(self):
        settings = self.lua.table_from(dict(enabled=False, healthStart=61, healthResume=87,
                                            manaStart=49, manaResume=92, food=5349, water=5350))
        self.assertTrue(self.addon.SaveRecoverySettings(settings))
        self.g.targetAlive = False
        self.g.health, self.g.powerValue = 60, 48
        low = self.tick().decision
        self.assertTrue(low.recovery_disabled)
        self.assertFalse(low.recovery_ready)
        self.assertEqual(int(low.frame.values['ttf']), RECOVERY_DISABLED_BASE + 61 * 128 + 49)
        self.assertEqual(low.fields['ttf'], '0')
        self.g.health = 61
        self.assertFalse(self.tick().decision.recovery_ready)
        self.g.powerValue = 49
        ready = self.tick().decision
        self.assertTrue(ready.recovery_disabled and ready.recovery_ready)
        self.sender.send.assert_not_called()
        self.addon.DB.masterSwitch = False
        stopped = self.tick().decision
        self.assertFalse(stopped.recovery_disabled or stopped.recovery_ready)

    def test_recovery_packet_loss_preserves_each_resume_threshold_before_attacking(self):
        self.configure()
        self.g.health, self.g.powerValue = 60, 48
        self.assertEqual(self.tick().selected.action, 'recovery_food')
        self.click_item('food')
        self.g.inventory[5349] = 2
        self.g.health = 75
        self.assertEqual(self.tick().selected.action, 'recovery_water')
        self.click_item('water')
        self.g.inventory[5350] = 3
        self.g.powerValue = 70
        self.assertEqual(self.tick().status, 'stopped')

        self.lua.execute('''
            savedRecovery = WowBuddyDev.UpdateRecovery
            WowBuddyDev.UpdateRecovery = function(allowed)
                local food = savedRecovery(allowed)
                return loseFood and 0 or food, 0
            end
        ''')
        for lose_food in (False, True):
            self.g.loseFood = lose_food
            missing = self.tick()
            self.assertEqual(missing.status, 'stopped')
            self.assertEqual(missing.decision.candidates[0].tag, '恢复')
            self.assertFalse(missing.decision.recovery_ready)
        self.lua.execute('WowBuddyDev.UpdateRecovery = savedRecovery')
        self.assertEqual(self.tick().status, 'stopped')
        self.g.health = 87
        still_drinking = self.tick()
        self.assertEqual(still_drinking.status, 'stopped')
        self.assertFalse(still_drinking.decision.recovery_ready)
        self.assertEqual(self.sender.send.call_count, 2)
        self.g.powerValue = 92
        resumed = self.tick()
        self.assertTrue(resumed.decision.recovery_ready)
        self.assertEqual(resumed.selected.action, 'spell_116')

    def test_panel_saves_distinct_thresholds_and_only_consumes_configured_items(self):
        panel = self.configure(food='|Hitem:5349:0|h[魔法面包]|h')
        self.assertFalse(panel.IsShown(panel))
        self.assertTrue(self.addon.DB.recovery.enabled)
        self.assertEqual((self.addon.DB.recovery.healthStart, self.addon.DB.recovery.manaResume), (61, 92))
        self.assertEqual(self.addon.DB.recovery.food, 5349)
        auto_key = next(iter(self.addon.GetSecureButton('auto_target').bindings))
        food_button = self.addon.GetSecureButton('recovery_food')
        water_button = self.addon.GetSecureButton('recovery_water')
        self.assertEqual(food_button.attributes.macrotext, '/use [nocombat,nochanneling] item:5349')
        self.assertEqual(water_button.attributes.macrotext, '/use [nocombat,nochanneling] item:5350')
        self.assertEqual(len({auto_key, next(iter(food_button.bindings)), next(iter(water_button.bindings))}), 3)

        self.g.health, self.g.powerValue = 60, 48
        self.g.speed = 5
        self.assertEqual(self.tick().status, 'stopped')
        self.g.speed = 0
        result = self.tick()
        self.assertEqual((result.status, result.selected.action), ('sent', 'recovery_food'))
        self.assertEqual(result.decision.fields['master_switch'], 'OFF')
        word = int(result.decision.frame.values['ttf'])
        self.assertGreaterEqual(word, RECOVERY_CONFIG_BASE)
        health_start, rest = divmod(word & 0x1FFFFF, 128 * 128)
        health_resume, key_index = divmod(rest, 128)
        self.assertEqual((health_start, health_resume, key_for_index(key_index)), (61, 87, result.selected.key))
        self.assertEqual(result.decision.fields['combat_time'], '0')
        self.assertEqual(len(result.decision.candidates), 1)
        self.click_item('food')
        self.g.inventory[5349] = 2
        self.g.health = 86
        self.g.typing = True
        self.assertEqual(self.tick(4).status, 'stopped')
        self.g.typing = False
        self.assertEqual(self.tick().selected.action, 'recovery_water')
        self.click_item('water')
        self.g.inventory[5350] = 3
        self.g.powerValue = 91
        self.assertEqual(self.tick(4).status, 'stopped')
        self.g.powerValue = 92
        self.assertEqual(self.tick().status, 'stopped')
        self.g.health = 87
        self.assertEqual(self.tick().selected.action, 'spell_116')
        self.assertEqual([call.args[0] for call in self.sender.send.call_args_list],
                         [next(iter(food_button.bindings)), next(iter(water_button.bindings)), 'NUMPAD5'])

    def test_low_resources_with_no_items_pauses_before_attack_but_yields_to_combat(self):
        self.configure()
        self.g.health = 35
        self.g.inventory[5349] = 0
        paused = self.tick()
        self.assertEqual(paused.status, 'stopped')
        self.assertIn('缺少已配置的食物', paused.decision.candidates[0].reason)
        self.sender.send.assert_not_called()
        self.g.combat = True
        self.assertEqual(self.tick().selected.action, 'spell_116')
        self.g.combat = False
        self.g.health = 75
        self.assertTrue(self.tick().decision.recovery_ready)

    def test_missing_food_allows_water_but_still_waits_for_health_before_attack(self):
        self.configure()
        self.g.health, self.g.powerValue = 35, 30
        self.g.inventory[5349] = 0
        result = self.tick()
        self.assertEqual(result.selected.action, 'recovery_water')
        self.click_item('water')
        self.g.inventory[5350] = 3
        self.assertEqual(self.tick().status, 'stopped')

        self.g.powerValue = 92
        waiting_for_health = self.tick(8)
        self.assertEqual(waiting_for_health.status, 'stopped')
        self.assertIn('缺少已配置的食物', waiting_for_health.decision.candidates[0].reason)
        self.assertEqual(self.sender.send.call_count, 1)
        self.g.health = 87
        self.assertEqual(self.tick().selected.action, 'spell_116')

    def test_unreadable_food_stock_does_not_block_confirmed_water(self):
        self.configure()
        self.lua.execute('''
            local count = GetItemCount
            function GetItemCount(id)
              if id == 5349 then error('food count unavailable') end
              return count(id)
            end
        ''')
        self.g.health, self.g.powerValue = 35, 30
        self.assertEqual(self.tick().selected.action, 'recovery_water')
        self.click_item('water')
        self.g.inventory[5350] = 3
        self.assertEqual(self.tick().status, 'stopped')
        self.g.powerValue = 92
        self.assertEqual(self.tick().status, 'stopped')
        self.assertEqual(self.sender.send.call_count, 1)
        self.g.health = 87
        self.assertEqual(self.tick().selected.action, 'spell_116')

    def test_replaced_food_binding_does_not_block_verified_water_or_trigger_another_macro(self):
        self.configure()
        food = self.addon.GetSecureButton('recovery_food')
        food_key = next(iter(food.bindings))
        self.g.fixtureRecoveryClaimedKey = food_key
        self.g.health, self.g.powerValue = 35, 30
        self.assertEqual(self.tick().selected.action, 'recovery_water')
        self.click_item('water')
        self.g.inventory[5350] = 3
        self.g.powerValue = 92
        self.assertEqual(self.tick().status, 'stopped')
        self.g.fixtureRecoveryClaimedKey = None
        food.SetAttribute(food, 'macrotext', '/use [nocombat] item:999')
        self.assertEqual(self.tick().status, 'stopped')
        food.SetAttribute(food, 'macrotext', self.addon.GetBoundMacro('recovery_food'))
        self.g.fixtureNativeBindingKey = food_key
        self.assertEqual(self.tick().selected.action, 'recovery_food')
        self.click_item('food')
        self.g.inventory[5349] = 2
        self.g.health = 86
        self.assertEqual(self.tick().status, 'stopped')
        self.g.health = 87
        self.assertEqual(self.tick().selected.action, 'spell_116')

    def test_missing_resource_percentage_allows_the_other_recovery_without_resuming_attack(self):
        self.configure()
        self.lua.execute('''
            local healthPercent, powerPercent = UnitHealthPercent, UnitPowerPercent
            function UnitHealthPercent(unit, ...)
              if unit=='player' and fixtureUnreadableHealth then error('health unavailable') end
              return healthPercent(unit, ...)
            end
            function UnitPowerPercent(unit, powerType, ...)
              if unit=='player' and powerType==0 and fixtureUnreadableMana then error('mana unavailable') end
              return powerPercent(unit, powerType, ...)
            end
        ''')
        self.g.health, self.g.powerValue = 35, 30
        self.g.fixtureUnreadableHealth, self.g.fixtureUnreadableMana = True, True
        unknown = self.tick()
        self.assertEqual(unknown.status, 'stopped')
        self.assertFalse(unknown.decision.recovery_ready)
        self.sender.send.assert_not_called()
        self.g.fixtureUnreadableMana = False
        water = self.tick()
        self.assertEqual(water.selected.action, 'recovery_water')
        self.click_item('water')
        self.g.inventory[5350] = 3

        self.g.fixtureUnreadableHealth, self.g.fixtureUnreadableMana = False, True
        self.assertEqual(self.tick().selected.action, 'recovery_food')
        self.click_item('food')
        self.g.inventory[5349] = 2
        self.g.health = 87
        self.assertEqual(self.tick().status, 'stopped')

        self.g.fixtureUnreadableMana = False
        self.g.powerValue = 70
        self.assertEqual(self.tick().status, 'stopped')
        self.assertEqual(self.sender.send.call_count, 2)
        self.g.powerValue = 92
        self.assertEqual(self.tick().selected.action, 'spell_116')

    def test_moving_interrupts_rest_even_if_consumption_is_confirmed_later(self):
        self.configure()
        self.g.health, self.g.powerValue = 35, 30
        self.assertEqual(self.tick().selected.action, 'recovery_food')
        self.click_item('food')
        self.g.inventory[5349] = 2
        self.assertEqual(self.tick().selected.action, 'recovery_water')
        self.click_item('water')

        self.g.speed = 5
        self.assertEqual(self.tick().status, 'stopped')
        self.g.speed = 0
        self.g.inventory[5350] = 3
        self.assertEqual(self.tick(3.1).selected.action, 'recovery_food')
        self.click_item('food')
        self.g.inventory[5349] = 1
        self.assertEqual(self.tick().selected.action, 'recovery_water')
        self.click_item('water')
        self.g.inventory[5350] = 2
        self.assertEqual(self.tick().status, 'stopped')
        self.g.health, self.g.powerValue = 87, 92
        self.assertEqual(self.tick().selected.action, 'spell_116')

    def test_combat_interrupt_preserves_the_recovery_thresholds_for_the_next_pull(self):
        self.configure()
        self.assertTrue(self.addon.SetPostKillAutoTargetEnabled(True))
        self.g.health, self.g.powerValue = 35, 30
        self.assertEqual(self.tick().selected.action, 'recovery_food')
        self.click_item('food')
        self.g.inventory[5349] = 2

        self.g.health, self.g.powerValue = 70, 65
        self.g.combat = True
        self.assertEqual(self.tick().selected.action, 'spell_116')
        self.g.targetAlive = False
        wait = self.tick()
        self.assertEqual(wait.status, 'stopped')
        self.assertIn('等待游戏确认脱战', wait.decision.candidates[0].reason)

        self.g.combat = False
        self.g.EmitFixtureEvent('PLAYER_REGEN_ENABLED')
        self.assertEqual(self.tick(3.1).selected.action, 'recovery_food')
        self.click_item('food')
        self.g.inventory[5349] = 1
        self.assertEqual(self.tick().selected.action, 'recovery_water')
        self.click_item('water')
        self.g.inventory[5350] = 3
        self.g.health, self.g.powerValue = 87, 91
        self.assertEqual(self.tick().status, 'stopped')
        self.g.powerValue = 92
        self.g.targetAlive = True
        self.g.fixtureTargetGUID = 'Creature-2'
        self.assertEqual(self.tick().selected.action, 'spell_116')

    def enable_ranked_conjuring(self):
        self.lua.execute('''
            fixtureConjureKnown={[597]=true,[990]=true,[5505]=true,[5506]=true}
            fixtureNativeBindingKey='F9'
            function C_Spell.GetSpellName(id)
              if id==990 then return '造食术' end
              if id==5506 or id==6127 then return '造水术' end
            end
            function C_Spell.GetSpellSubtext(id) return id==6127 and '等级 4' or '等级 3' end
        ''')

    def test_mage_conjures_highest_learned_food_and_water_then_overlaps_rest(self):
        self.enable_ranked_conjuring()
        self.configure(food='1113', water='2288')
        self.g.health, self.g.powerValue = 100, 30
        self.g.fixtureConjureNoMana = True
        self.assertEqual(self.tick().status, 'stopped')
        self.g.fixtureConjureNoMana = False
        water = self.tick()
        self.assertEqual(water.selected.action, 'recovery_conjure_water')
        self.assertNotEqual(water.selected.key, 'F9')
        self.assertEqual(self.addon.GetBoundMacro('recovery_conjure_water'), '/cast [nocombat,nochanneling] 造水术(等级 3)')
        self.assertEqual(self.addon.GetBoundMacro('recovery_conjured_water'), '/use [nocombat,nochanneling] item:2136')
        self.click_item('conjure_water')
        self.g.EmitFixtureEvent('UNIT_SPELLCAST_SUCCEEDED', 'pet', 'other-unit', 5506)
        self.g.EmitFixtureEvent('UNIT_SPELLCAST_SUCCEEDED', 'player', 'other-rank', 5505)
        self.assertEqual(self.tick(6.1).selected.action, 'recovery_conjure_water')
        self.click_item('conjure_water')
        waiting = self.tick(6.1)
        self.assertIn('等待冷却', waiting.decision.candidates[0].reason)
        self.g.fixtureConjureNoMana = True
        self.assertIsNone(self.tick(15.1).selected)
        self.g.fixtureConjureNoMana = False
        self.assertEqual(self.tick().selected.action, 'recovery_conjure_water')
        self.click_item('conjure_water')
        self.assertEqual(self.tick(2).status, 'stopped')
        self.g.inventory[2136] = 10
        self.g.health = 35

        self.assertEqual(self.tick(2).selected.action, 'recovery_conjure_food')
        self.assertEqual(self.addon.GetBoundMacro('recovery_conjure_food'), '/cast [nocombat,nochanneling] 造食术(等级 3)')
        self.assertEqual(self.addon.GetBoundMacro('recovery_conjured_food'), '/use [nocombat,nochanneling] item:1114')
        self.click_item('conjure_food')
        self.assertEqual(self.tick(2).status, 'stopped')
        self.g.inventory[1114] = 10

        self.assertEqual(self.tick(2).selected.action, 'recovery_food')
        self.click_item('conjured_food')
        self.g.inventory[1114] = 9
        self.assertEqual(self.tick().selected.action, 'recovery_water')
        self.click_item('conjured_water')
        self.g.inventory[2136] = 9
        self.assertEqual(self.tick().status, 'stopped')
        self.g.health, self.g.powerValue = 87, 92
        self.assertEqual(self.tick().selected.action, 'spell_116')
        self.assertEqual((self.addon.DB.recovery.food, self.addon.DB.recovery.water), (1113, 2288))

        self.g.fixtureConjureKnown[6127] = True
        self.g.EmitFixtureEvent('SPELLS_CHANGED')
        self.assertEqual(self.addon.GetBoundMacro('recovery_conjured_water'), '/use [nocombat,nochanneling] item:3772')

    def test_full_bag_blocks_empty_conjuring_but_preserves_existing_food(self):
        from wowbuddy.dev_protocol import bag_recovery_walk_safe

        self.enable_ranked_conjuring()
        self.configure(healthStart='50', food='1113', water='2288')
        self.g.health, self.g.powerValue = 60, 30
        self.lua.execute('''
            fixtureFree=0
            C_Container={GetContainerNumSlots=function(bag) return bag==0 and 16 or 0 end,
                         GetContainerNumFreeSlots=function() return fixtureFree,0 end}
        ''')
        blocked = self.tick()
        self.assertEqual(blocked.decision.candidates[0].action, 'recovery_bag_full')
        self.assertTrue(bag_recovery_walk_safe(blocked.decision.frame))
        self.sender.send.assert_not_called()
        self.g.health = 30
        self.assertFalse(bag_recovery_walk_safe(self.tick().decision.frame))
        self.g.inventory[1113] = 2
        self.assertEqual(self.tick().selected.action, 'recovery_food')
        self.click_item('food')
        self.g.inventory[1113] = 1
        self.assertNotEqual(self.tick().decision.candidates[0].action, 'recovery_bag_full')
        self.g.health = 90
        self.g.fixtureFree = 1
        self.assertEqual(self.tick().selected.action, 'recovery_conjure_water')

    def test_full_bag_defers_conjuring_after_configured_water_fails(self):
        from wowbuddy.dev_protocol import bag_recovery_walk_safe

        self.enable_ranked_conjuring()
        self.configure(healthStart='0')
        self.g.health, self.g.powerValue = 100, 30
        self.lua.execute('''
            fixtureFree=0
            C_Container={GetContainerNumSlots=function(bag) return bag==0 and 16 or 0 end,
                         GetContainerNumFreeSlots=function() return fixtureFree,0 end}
        ''')
        self.assertEqual(self.tick().selected.action, 'recovery_water')
        self.click_item('water')
        self.assertEqual(self.tick(3.1).selected.action, 'recovery_water')
        self.click_item('water')

        blocked = self.tick(3.1)
        self.assertEqual(blocked.decision.candidates[0].action, 'recovery_bag_full')
        self.assertTrue(bag_recovery_walk_safe(blocked.decision.frame))
        self.assertEqual(self.sender.send.call_count, 2)
        self.g.fixtureFree = 1
        self.assertEqual(self.tick().selected.action, 'recovery_conjure_water')
        self.click_item('conjure_water')
        self.g.inventory[2136] = 10
        self.assertEqual(self.tick(2).selected.action, 'recovery_water')
        self.click_item('conjured_water')
        self.g.inventory[2136] = 9
        self.g.powerValue = 91
        self.assertEqual(self.tick().status, 'stopped')
        self.g.powerValue = 92
        self.assertEqual(self.tick().selected.action, 'spell_116')

    def test_confirmed_conjure_waits_for_delayed_stock_before_drinking(self):
        self.enable_ranked_conjuring()
        self.configure(healthStart='0', water='2288')
        self.g.powerValue = 30
        self.assertEqual(self.tick().selected.action, 'recovery_conjure_water')
        self.click_item('conjure_water')
        self.assertEqual(self.tick(3).status, 'stopped')
        self.g.EmitFixtureEvent('UNIT_SPELLCAST_SUCCEEDED', 'player', 'conjure-water', 5506)
        self.assertEqual(self.tick(3.2).status, 'stopped')
        self.assertEqual(self.sender.send.call_count, 1)

        self.g.inventory[2136] = 10
        self.assertEqual(self.tick().selected.action, 'recovery_water')
        self.click_item('conjured_water')
        self.g.inventory[2136] = 9
        self.g.powerValue = 91
        self.assertEqual(self.tick().status, 'stopped')
        self.g.powerValue = 92
        self.assertEqual(self.tick().selected.action, 'spell_116')

    def test_duplicate_conjure_success_does_not_keep_extending_the_stock_wait(self):
        self.enable_ranked_conjuring()
        self.configure(manaStart='0', food='1113')
        self.g.health = 35
        self.assertEqual(self.tick().selected.action, 'recovery_conjure_food')
        self.click_item('conjure_food')
        self.assertEqual(self.tick(3).status, 'stopped')
        self.g.EmitFixtureEvent('UNIT_SPELLCAST_SUCCEEDED', 'player', 'conjure-food', 990)
        self.assertEqual(self.tick(3.2).status, 'stopped')
        self.g.EmitFixtureEvent('UNIT_SPELLCAST_SUCCEEDED', 'player', 'conjure-food', 990)
        self.assertEqual(self.tick(3.1).selected.action, 'recovery_conjure_food')

    def test_mage_waits_for_food_threshold_then_conjures_water_without_a_fixed_rest_delay(self):
        self.enable_ranked_conjuring()
        self.configure()
        self.g.health, self.g.powerValue = 35, 30
        self.g.inventory[5350] = 0
        self.g.fixtureConjureNoMana = True
        self.assertEqual(self.tick().selected.action, 'recovery_food')
        self.click_item('food')
        self.g.inventory[5349] = 2
        self.assertEqual(self.tick().status, 'stopped')

        self.g.fixtureConjureNoMana = False
        self.g.health, self.g.powerValue = 86, 55
        waiting = self.tick(5)
        self.assertEqual(waiting.status, 'stopped')
        self.assertFalse(waiting.decision.recovery_ready)
        self.sender.send.assert_called_once()
        self.g.health = 87
        self.assertEqual(self.tick().selected.action, 'recovery_conjure_water')
        self.click_item('conjure_water')
        self.assertEqual(self.tick(2).status, 'stopped')
        self.g.inventory[2136] = 10
        self.assertEqual(self.tick(2).selected.action, 'recovery_water')
        self.click_item('conjured_water')
        self.g.inventory[2136] = 9
        self.assertFalse(self.tick().decision.recovery_ready)
        self.g.powerValue = 92
        self.assertEqual(self.tick().selected.action, 'spell_116')

    def test_mage_uses_confirmed_ranked_water_when_configured_stock_is_unreadable(self):
        self.enable_ranked_conjuring()
        self.configure(healthStart='0')
        self.lua.execute('''
            local count = GetItemCount
            function GetItemCount(id)
              if id == 5350 then error('configured water count unavailable') end
              return count(id)
            end
        ''')
        self.g.powerValue = 30
        self.assertEqual(self.tick().status, 'stopped')
        self.assertEqual(self.sender.send.call_count, 0)

        self.g.inventory[2136] = 3
        self.assertEqual(self.tick().selected.action, 'recovery_water')
        self.click_item('conjured_water')
        self.g.inventory[2136] = 2
        self.g.powerValue = 91
        self.assertEqual(self.tick().status, 'stopped')
        self.g.powerValue = 92
        self.assertEqual(self.tick().selected.action, 'spell_116')

    def test_mage_ranked_water_binding_does_not_depend_on_conjure_spell_name(self):
        self.enable_ranked_conjuring()
        self.lua.execute('''
            fixtureConjureNameUnavailable = true
            local name, info = C_Spell.GetSpellName, GetSpellInfo
            function C_Spell.GetSpellName(id)
              if id == 5506 and fixtureConjureNameUnavailable then return nil end
              return name(id)
            end
            function GetSpellInfo(id, ...)
              if id == 5506 and fixtureConjureNameUnavailable then return nil end
              if info then return info(id, ...) end
            end
        ''')
        self.configure(healthStart='0', water='2288')
        self.g.powerValue = 30
        self.assertEqual(self.tick().status, 'stopped')
        self.g.inventory[2136] = 1
        self.assertEqual(self.tick().selected.action, 'recovery_water')
        self.click_item('conjured_water')
        self.g.inventory[2136] = 0
        self.assertEqual(self.tick().status, 'stopped')

        self.g.speed = 2
        self.assertEqual(self.tick().status, 'stopped')
        self.g.speed = 0
        self.g.fixtureConjureNameUnavailable = False
        self.g.EmitFixtureEvent('SPELLS_CHANGED')
        self.assertEqual(self.tick().selected.action, 'recovery_conjure_water')
        self.assertEqual(self.addon.GetBoundMacro('recovery_conjure_water'), '/cast [nocombat,nochanneling] 造水术(等级 3)')

    def test_mage_uses_ranked_water_when_configured_stock_has_no_consumption_receipts(self):
        self.enable_ranked_conjuring()
        self.configure(healthStart='0')
        self.g.powerValue = 30
        self.g.inventory[2136] = 3
        self.assertEqual(self.tick().selected.action, 'recovery_water')
        self.click_item('water')
        self.assertEqual(self.tick(3.1).selected.action, 'recovery_water')
        self.click_item('water')

        fallback = self.tick(3.1)
        self.assertEqual(fallback.selected.action, 'recovery_water')
        self.assertEqual(self.addon.GetBoundMacro('recovery_conjured_water'), '/use [nocombat,nochanneling] item:2136')
        self.assertNotEqual(fallback.selected.key, self.sender.send.call_args_list[0].args[0])
        self.click_item('conjured_water')
        self.g.inventory[2136] = 2
        self.g.powerValue = 91
        self.assertEqual(self.tick().status, 'stopped')
        self.g.powerValue = 92
        self.assertEqual(self.tick().selected.action, 'spell_116')
        self.assertEqual((self.addon.DB.recovery.water, self.g.inventory[5350]), (5350, 4))

    def test_mage_conjures_food_when_configured_stock_has_no_consumption_receipts(self):
        self.enable_ranked_conjuring()
        self.configure(manaStart='0')
        self.g.health = 35
        self.assertEqual(self.tick().selected.action, 'recovery_food')
        self.click_item('food')
        self.assertEqual(self.tick(3.1).selected.action, 'recovery_food')
        self.click_item('food')

        self.g.fixtureConjureNoMana = True
        self.assertIn('等待冷却', self.tick(3.1).decision.candidates[0].reason)
        self.g.fixtureConjureNoMana = False
        self.assertEqual(self.tick().selected.action, 'recovery_conjure_food')
        self.click_item('conjure_food')
        self.assertEqual(self.tick(2).status, 'stopped')
        self.g.inventory[1114] = 10
        self.assertEqual(self.tick().selected.action, 'recovery_food')
        self.assertEqual(self.addon.GetBoundMacro('recovery_conjured_food'), '/use [nocombat,nochanneling] item:1114')
        self.click_item('conjured_food')
        self.g.inventory[1114] = 9
        self.g.health = 86
        self.assertEqual(self.tick().status, 'stopped')
        self.g.health = 87
        self.assertEqual(self.tick().selected.action, 'spell_116')
        self.assertEqual((self.addon.DB.recovery.food, self.g.inventory[5349]), (5349, 3))

    def test_stocking_the_configured_food_does_not_restart_an_active_food_effect(self):
        self.enable_ranked_conjuring()
        self.configure(food='1113')
        self.g.inventory[1114] = 3
        self.g.health, self.g.powerValue = 35, 30
        self.assertEqual(self.tick().selected.action, 'recovery_food')
        self.click_item('conjured_food')
        self.g.inventory[1114] = 2
        self.g.inventory[1113] = 3
        self.assertEqual(self.tick().selected.action, 'recovery_water')
        self.click_item('water')
        self.g.inventory[5350] = 3
        self.g.health = 70
        self.assertEqual(self.tick(4).status, 'stopped')
        self.assertEqual(self.sender.send.call_count, 2)
        self.g.health, self.g.powerValue = 87, 92
        self.assertEqual(self.tick().selected.action, 'spell_116')

    def test_mage_does_not_interrupt_drinking_for_food_when_mana_reading_is_missing(self):
        self.enable_ranked_conjuring()
        self.configure()
        self.lua.execute('''
            local manaPercent = UnitPowerPercent
            function UnitPowerPercent(...)
              if fixtureUnreadableMana then error('mana unavailable') end
              return manaPercent(...)
            end
        ''')
        self.g.powerValue = 30
        self.assertEqual(self.tick().selected.action, 'recovery_water')
        self.click_item('water')
        self.g.inventory[5350] = 3
        self.g.inventory[5349] = 0
        self.g.health = 35
        self.g.fixtureUnreadableMana = True
        self.assertEqual(self.tick(3).status, 'stopped')
        self.g.fixtureUnreadableMana = False
        self.g.powerValue = 91
        self.assertEqual(self.tick().status, 'stopped')
        self.sender.send.assert_called_once()
        self.g.powerValue = 92
        self.assertEqual(self.tick().selected.action, 'recovery_conjure_food')

    def test_valid_post_kill_request_survives_rest_and_resumes_before_attacking(self):
        self.configure(manaStart='0')
        self.assertTrue(self.addon.SetPostKillAutoTargetEnabled(True))
        self.g.combat = True
        self.assertEqual(self.tick().selected.action, 'spell_116')
        self.g.targetAlive = False
        self.g.health = 45
        for delay in (0.25, 0.25, 0.35):
            waiting = self.tick(delay)
            self.assertEqual(waiting.status, 'stopped')
            self.assertIn('等待游戏确认脱战', waiting.decision.candidates[0].reason)
        self.assertEqual(self.sender.send.call_count, 1)
        self.g.combat = False
        self.g.EmitFixtureEvent('PLAYER_REGEN_ENABLED')
        result = self.tick()
        self.assertEqual(result.selected.action, 'recovery_food')
        self.click_item('food')
        self.g.inventory[5349] = 2
        self.assertEqual(self.tick().status, 'stopped')
        self.assertEqual(self.tick(8).status, 'stopped')
        self.g.health = 90
        next_target = self.tick()
        self.assertEqual(next_target.selected.action, 'auto_target')
        self.assertEqual(next_target.auto_gate, 1)
        self.g.targetAlive = True
        self.g.fixtureTargetGUID = 'Creature-2'
        self.assertEqual(self.tick().selected.action, 'spell_116')

    def test_post_kill_request_survives_a_gap_between_food_and_water(self):
        self.configure()
        self.assertTrue(self.addon.SetPostKillAutoTargetEnabled(True))
        self.g.combat = True
        self.assertEqual(self.tick().selected.action, 'spell_116')
        self.g.targetAlive = False
        self.g.health = 45
        self.assertIn('等待游戏确认脱战', self.tick().decision.candidates[0].reason)
        self.g.combat = False
        self.g.EmitFixtureEvent('PLAYER_REGEN_ENABLED')
        self.assertEqual(self.tick().selected.action, 'recovery_food')
        self.click_item('food')
        self.g.inventory[5349] = 2
        self.assertEqual(self.tick().status, 'stopped')
        self.assertEqual(self.tick(5).status, 'stopped')

        self.g.speed, self.g.health, self.g.powerValue = 2, 90, 40
        self.assertEqual(self.tick().status, 'stopped')
        self.g.speed = 0
        self.assertEqual(self.tick().selected.action, 'recovery_water')
        self.click_item('water')
        self.g.inventory[5350] = 3
        self.assertEqual(self.tick().status, 'stopped')
        self.assertEqual(self.tick(8).status, 'stopped')
        self.g.powerValue = 92
        resumed = self.tick()
        self.assertIsNotNone(resumed.selected)
        self.assertEqual(resumed.selected.action, 'auto_target')
        self.assertEqual(resumed.auto_gate, 1)

    def test_post_kill_recovery_hold_cannot_extend_indefinitely(self):
        self.configure(manaStart='0')
        self.assertTrue(self.addon.SetPostKillAutoTargetEnabled(True))
        self.g.combat = True
        self.assertEqual(self.tick().selected.action, 'spell_116')
        self.g.targetAlive = False
        self.g.health = 45
        self.tick()
        self.g.combat = False
        self.g.EmitFixtureEvent('PLAYER_REGEN_ENABLED')
        self.lua.execute('WowBuddyDev.IsRecoveryActive=function() return true end')
        self.assertIsNone(self.tick().auto_gate)
        self.assertTrue(self.addon.IsPostKillAutoTargetReady())
        self.tick(89)
        self.assertTrue(self.addon.IsPostKillAutoTargetReady())
        self.tick(6)
        self.assertFalse(self.addon.IsPostKillAutoTargetReady())

    def test_confirmed_kill_wait_is_bounded_and_skipped_with_enough_resources(self):
        self.configure()
        self.assertTrue(self.addon.SetPostKillAutoTargetEnabled(True))
        self.g.combat = True
        self.assertEqual(self.tick().selected.action, 'spell_116')
        self.g.targetAlive = False
        self.g.powerValue = 45
        wait = self.tick()
        self.assertEqual(wait.status, 'stopped')
        self.assertEqual(wait.decision.fields['ttf'], '0')
        self.assertEqual(self.tick(1).decision.fields['combat_time'], '1')
        self.assertEqual(self.tick(1.3).selected.action, 'auto_target')

        self.g.targetAlive = True
        self.g.fixtureTargetGUID = 'Creature-2'
        self.g.powerValue = 100
        self.assertEqual(self.tick().selected.action, 'spell_116')
        self.g.targetAlive = False
        self.assertEqual(self.tick().selected.action, 'auto_target')

    def test_target_disappears_before_death_can_be_confirmed(self):
        self.lua.execute("""
            fixtureTargetExists = true
            function UnitExists(unit)
              return unit == 'player' or (unit == 'target' and fixtureTargetExists)
            end
            function UnitGUID() error('unavailable GUID') end
        """)
        self.configure()
        self.assertTrue(self.addon.SetPostKillAutoTargetEnabled(True))
        self.g.combat = True
        self.assertEqual(self.tick().selected.action, 'spell_116')
        self.g.powerValue = 45
        self.g.fixtureTargetExists = False
        self.g.EmitFixtureEvent('PLAYER_TARGET_CHANGED')
        waiting = self.tick()
        self.assertEqual(waiting.status, 'stopped')
        self.assertIn('等待游戏确认脱战', waiting.decision.candidates[0].reason)
        self.g.combat = False
        self.g.EmitFixtureEvent('PLAYER_REGEN_ENABLED')
        self.assertEqual(self.tick(0.5).selected.action, 'recovery_water')
        self.assertEqual(self.sender.send.call_count, 2)

    def test_arrival_waits_for_food_and_water_then_replaces_a_non_attackable_target(self):
        self.configure()
        self.assertTrue(self.addon.SetPostKillAutoTargetEnabled(True))
        self.lua.execute('''
            fixtureTargetExists=false;fixtureBindingReplaced=false;fixtureTabOverridden=false
            fixtureDistance=42.5;fixtureInRange=false;fixtureTargetAttackable=false
            function UnitExists(unit) return unit=='player' or (unit=='target' and fixtureTargetExists) end
            function UnitCanAttack(_,unit) if unit=='target' then return fixtureTargetAttackable end end
            function UnitDistanceSquared(unit) return fixtureDistance*fixtureDistance,true end
            C_Spell.IsSpellInRange=function(id,unit) return id==837 and unit=='target' and fixtureInRange end
            C_Map={
              GetBestMapForUnit=function() return 52 end,
              GetMapInfo=function() return {name='西部荒野',mapType=3} end,
              GetMapWorldSize=function() return 1000,800 end,
              GetPlayerMapPosition=function() return {GetXY=function() return 0.3212,0.3615 end} end,
            }
            function GetPlayerFacing() return 0 end
            local actions={W='MOVEFORWARD',A='TURNLEFT',D='TURNRIGHT',TAB='TARGETNEARESTENEMY'}
            function GetBindingKey(action)
              for key,value in pairs(actions) do if value==action then return key end end
            end
            function GetBindingAction(key, override)
              assert(override==true)
              if key=='TAB' and fixtureTabOverridden then return 'JUMP' end
              if actions[key] then return actions[key] end
              if fixtureBindingReplaced then return 'JUMP' end
              for _,frame in ipairs(frames) do
                local binding=frame.bindings and frame.bindings[key]
                if binding then return 'CLICK '..binding.button..':LeftButton' end
              end
            end
            local targetButton=WowBuddyDev.GetSecureButton('auto_target')
            function targetButton:GetName() return self.name end
        ''')
        self.addon.RebuildPixelBars()
        self.scheduler.pipeline.probe_attack_range = True
        foreground = Mock()
        pull = ArrivalPull(self.scheduler.dispatcher, foreground)
        destination = MapDestination(52, 32.12, 36.15, 'alive', '练级据点')

        def observe(tick, *, position=None):
            if position is None:
                position = decode_navigation_state(self.image, tick.decision.frame)
            return pull.observe((10, 1), destination, position, tick, round(self.g.now * 1000), 100)

        self.g.health, self.g.powerValue = 60, 48
        food = self.tick()
        self.assertEqual(food.selected.action, 'recovery_food')
        self.assertFalse(food.decision.recovery_ready)
        self.assertIsNone(observe(food))
        self.click_item('food')
        self.g.inventory[5349] = 2
        self.g.health = 87
        water = self.tick()
        self.assertEqual(water.selected.action, 'recovery_water')
        self.assertIsNone(observe(water))
        self.click_item('water')
        self.g.inventory[5350] = 3
        self.g.powerValue = 90
        self.assertIsNone(observe(self.tick(3)))
        self.assertEqual(self.sender.send.call_count, 2)

        self.g.powerValue = 92
        self.g.fixtureBindingReplaced = True
        self.g.fixtureTabOverridden = True
        blocked = self.tick()
        self.assertTrue(blocked.decision.recovery_ready)
        nav = decode_navigation_state(self.image, blocked.decision.frame)
        self.assertEqual(nav.idle_key_index, 0)
        self.assertEqual(nav.retarget_key, 0)
        self.assertIsNone(observe(blocked, position=nav))
        self.g.fixtureBindingReplaced = False
        self.g.fixtureTabOverridden = False
        self.g.fixtureTargetExists = True
        self.g.fixtureTargetAttackable = None
        unknown = self.tick()
        self.assertEqual(decode_navigation_state(self.image, unknown.decision.frame).idle_key_index, 0)
        self.assertIsNone(observe(unknown))
        self.g.fixtureTargetAttackable = False
        first = self.tick()
        self.assertEqual(first.decision.frame.values['target_valid'], 'OFF')
        nav = decode_navigation_state(self.image, first.decision.frame)
        self.assertEqual(nav.idle_key_index, 1)
        self.assertEqual((nav.target_revision, nav.retarget_key), (0, 9))
        navigation_words = [0x57424D, 0x4100 + nav.sequence, 52, 3212, 3615, 0, 1000, 800, 0x574144]
        checksum = 0
        for value in navigation_words:
            checksum = (checksum * 31 + value) % 0xFEFFFD
        self.assertEqual([self.image.pixel(6, y) for y in range(174, 213, 4)], navigation_words + [checksum])
        pixels = [list(row) for row in self.image.rows]
        pixels[222][6] ^= 1
        without_pull = decode_navigation_state(RGBImage(pixels), first.decision.frame)
        self.assertEqual(without_pull.idle_key_index, 0)
        pixels[298][6] ^= 1
        without_retarget = decode_navigation_state(RGBImage(pixels), first.decision.frame)
        self.assertIsNone(without_retarget.target_revision)
        self.assertEqual(without_retarget.retarget_key, 0)
        self.assertIsNone(observe(first, position=without_pull))
        self.assertIsNone(observe(first))
        self.assertIsNone(observe(first))
        self.assertIn('首次选怪键 F6', observe(self.tick()))
        self.assertEqual(self.sender.send.call_count, 3)

        self.addon.RecordAutoTargetAttempt()
        self.g.fixtureTargetAttackable = True
        self.g.EmitFixtureEvent('PLAYER_TARGET_CHANGED')
        blocked = self.tick()
        self.assertTrue(blocked.decision.attack_blocked_by_range)
        self.assertEqual(decode_navigation_state(self.image, blocked.decision.frame).idle_key_index, 0)
        self.assertIn('确认首次选怪键生效', observe(blocked))
        waiting = self.tick(8)
        self.assertIsNone(observe(waiting))
        self.assertIsNone(observe(waiting))
        self.assertIn('已请求重选一次', observe(self.tick()))
        foreground.pulse.assert_called_once_with(10, 9, 35, (87, 65, 68, 9))
        self.g.EmitFixtureEvent('PLAYER_TARGET_CHANGED')
        self.g.fixtureInRange = True
        self.g.fixtureDistance = 20
        first_attack = self.tick()
        self.assertEqual(first_attack.selected.action, 'spell_116')
        self.assertIn('确认切换目标', observe(first_attack))
        self.g.combat = True
        self.assertIsNone(observe(self.tick()))
        self.assertEqual([item.args[0] for item in self.sender.send.call_args_list[:4]],
                         ['F7', 'F8', 'F6', 'NUMPAD5'])

    def test_range_probe_and_nameplate_approach_yield_to_real_spell(self):
        self.lua.execute('''
            fixtureDistance=36;fixtureInRange=false;fixtureTapped=false
            fixtureDistanceReadable=true;fixtureEstimate=false
            fixturePlateX=70;fixtureFacing=0;fixtureForbidden=false
            fixtureTargetAlias=true;fixtureMatchingPlate=true
            function UnitDistanceSquared(unit) return fixtureDistance*fixtureDistance,fixtureDistanceReadable end
            WowBuddyDev.LibRangeCheck={GetRange=function(self,unit)
              if fixtureEstimate then return 65,80 end
            end}
            function UnitIsPlayer(unit) return unit=='player' end
            function UnitPlayerControlled(unit) return unit=='player' end
            function UnitIsTapDenied(unit) return fixtureTapped end
            C_Spell.IsSpellInRange=function(id,unit) return id==837 and unit=='target' and fixtureInRange end
            C_Map={
              GetBestMapForUnit=function() return 52 end,
              GetMapInfo=function() return {name='西部荒野',mapType=3} end,
              GetMapWorldSize=function() return 1000,800 end,
              GetPlayerMapPosition=function() return {GetXY=function() return 0.3212,0.3615 end} end,
            }
            function GetPlayerFacing() return fixtureFacing end
            local actions={W='MOVEFORWARD',A='TURNLEFT',D='TURNRIGHT'}
            function GetBindingKey(action)
              for key,value in pairs(actions) do if value==action then return key end end
            end
            function GetBindingAction(key, override) assert(override==true);return actions[key] end
            local function plate(unit)
              return {unitToken=unit, IsForbidden=function() return fixtureForbidden end,
                IsVisible=function() return true end, GetEffectiveScale=function() return 1 end,
                GetCenter=function() return fixturePlateX,60 end}
            end
            C_NamePlate.GetNamePlateForUnit=function(unit, includeForbidden)
              assert(includeForbidden==false)
              if unit=='nameplate2' or (unit=='target' and fixtureTargetAlias) then return plate('nameplate2') end
            end
            C_NamePlate.GetNamePlates=function()
              if not fixtureEmptyPlates then return {plate('nameplate1'),plate('nameplate2')} end
              return {}
            end
            function UnitIsUnit(a,b)
              return a==b or (fixtureMatchingPlate and a=='nameplate2' and b=='target')
            end
        ''')
        self.addon.RebuildPixelBars()
        self.scheduler.pipeline.probe_attack_range = True
        movement = Mock()
        movement.keep_forward.return_value = False
        approach = TargetApproach(movement)

        def observe(tick):
            frame = tick.decision.frame
            nav = decode_navigation_state(self.image, frame, for_target=True)
            bearing = decode_target_bearing(self.image, frame, nav) if tick.decision.attack_blocked_by_range else None
            return bearing, approach.observe((10, 1), nav, bearing)

        def verify_mismatched_bearing(tick):
            frame = tick.decision.frame
            nav = decode_navigation_state(self.image, frame, for_target=True)
            self.assertIsNotNone(frame.target_revision)
            words = [self.image.pixel(6, row * 4 + 2) for row in range(59, 64)]
            self.assertEqual(words[2], frame.target_revision)
            words[2] = (words[2] - 1) % 65521
            checksum = 0
            for word in words:
                checksum = (checksum * 31 + word) % 0xFEFFFD
            pixels = [list(row) for row in self.image.rows]
            for index, word in enumerate([*words, checksum], 59):
                for y in range(index * 4, index * 4 + 4):
                    pixels[y][6] = word
            mixed = RGBImage(pixels)
            self.assertEqual(decode_navigation_state(mixed, frame, for_target=True), nav)
            bearing = decode_target_bearing(mixed, frame, nav)
            self.assertIsNone(bearing)
            return nav, bearing

        self.g.fixtureForbidden = True
        self.assertIsNone(observe(self.tick())[0])
        self.g.fixtureForbidden = False
        self.g.fixtureTapped = True
        self.assertIsNone(observe(self.tick())[0])
        self.g.fixtureTapped = False
        self.g.fixtureTargetAlias, self.g.fixtureMatchingPlate = False, False
        self.assertIsNone(observe(self.tick())[0])
        self.g.fixtureMatchingPlate = True

        far = self.tick()
        self.assertEqual(far.decision.frame.values['range_116'], 'OFF')
        self.assertTrue(far.decision.recovery_disabled and far.decision.recovery_ready)
        self.assertTrue(far.decision.attack_blocked_by_range)
        self.assertEqual(far.decision.candidates, ())
        verify_mismatched_bearing(far)
        bearing, status = observe(far)
        self.assertEqual((bearing.x, bearing.distance, status), (0.7, 36, None))
        self.assertIsNone(observe(far)[1])
        movement.pulse.assert_not_called()
        self.assertIn('开始接近', observe(self.tick())[1])
        self.assertEqual(movement.pulse.call_args.args[1], ord('D'))
        self.sender.send.assert_not_called()

        self.g.fixturePlateX, self.g.fixtureFacing = 51, 6.1
        self.g.fixtureDistance = 35
        observe(self.tick())
        movement.hold_forward.assert_called_once_with(10, (87, 65, 68))
        self.g.speed, self.g.fixtureDistance, self.g.combat = 7, 34, True
        movement.keep_forward.return_value = True
        combat = self.tick()
        self.assertIsNone(decode_navigation_state(self.image, combat.decision.frame))
        bearing, _ = observe(combat)
        self.assertTrue(bearing.continuous)
        self.assertEqual(movement.hold_forward.call_count, 2)
        mixed_position, mixed_bearing = verify_mismatched_bearing(combat)
        self.assertIsNone(approach.observe((10, 1), mixed_position, mixed_bearing))
        movement.release_forward.assert_called_once_with()
        self.assertEqual(movement.hold_forward.call_count, 2)
        self.g.fixtureDistance = 30
        self.g.fixtureInRange = True
        self.scheduler.before_dispatch = lambda fields: fields.get('player_moving') == 'OFF'
        stopping = self.tick()
        self.assertEqual(stopping.status, 'movement_stopping')
        self.assertIsNone(stopping.selected)
        self.sender.send.assert_not_called()
        self.assertIsNone(observe(stopping)[1])
        self.g.speed = 0
        attack = self.tick()
        self.assertFalse(attack.decision.attack_blocked_by_range)
        self.assertEqual(attack.selected.action, 'spell_116')
        self.assertIsNone(observe(attack)[1])
        self.assertEqual(movement.pulse.call_count, 1)
        movement.release_forward.assert_called_once_with()
        self.sender.send.assert_called_once()

        self.g.combat, self.g.fixtureInRange, self.g.fixtureDistanceReadable = False, False, False
        unknown = self.tick(2)
        unknown_frame = unknown.decision.frame
        self.assertEqual(unknown_frame.values['distance'], '—')
        self.assertTrue(unknown.decision.attack_blocked_by_range)
        unknown_bearing = decode_target_bearing(self.image, unknown_frame,
                                               decode_navigation_state(self.image, unknown_frame))
        self.assertTrue(unknown_bearing.estimated)
        self.assertIsNone(unknown_bearing.distance)
        self.g.fixtureEstimate = True
        estimated = self.tick()
        self.assertTrue(estimated.decision.attack_blocked_by_range)
        estimated_frame = estimated.decision.frame
        far_bearing = decode_target_bearing(self.image, estimated_frame,
                                           decode_navigation_state(self.image, estimated_frame))
        self.assertTrue(far_bearing.continuous and far_bearing.estimated)
        self.assertEqual(far_bearing.distance, 72.5)

        self.g.fixtureEmptyPlates = True
        self.g.EmitFixtureEvent('NAME_PLATE_UNIT_ADDED', 'nameplate1')
        self.assertIsNone(observe(self.tick())[0])
        self.g.EmitFixtureEvent('NAME_PLATE_UNIT_ADDED', 'nameplate2')
        self.assertEqual(observe(self.tick())[0].distance, 72.5)
        self.g.EmitFixtureEvent('NAME_PLATE_UNIT_REMOVED', 'nameplate2')
        self.assertIsNone(observe(self.tick())[0])

        self.lua.execute('''
            fixtureFacing=-0.2; fixtureWorld=0
            function UnitPosition(unit)
              if unit=='player' then return -100, 200, 0, 0 end
              return -100, 160, 0, fixtureWorld
            end
        ''')
        self.g.EmitFixtureEvent('PLAYER_TARGET_CHANGED')
        movement.reset_mock()
        movement.keep_forward.return_value = False
        world = self.tick()
        verify_mismatched_bearing(world)
        bearing, _ = observe(world)
        self.assertEqual((bearing.x, bearing.heading, bearing.distance), (None, 4.712, 40))
        self.assertIn('开始接近', observe(self.tick())[1])
        movement.pulse.assert_called_once_with(10, ord('D'), 100, (87, 65, 68))
        self.g.fixtureFacing = -1.57
        observe(self.tick())
        movement.hold_forward.assert_called_once_with(10, (87, 65, 68))
        self.g.fixtureWorld = 1
        self.assertIsNone(observe(self.tick())[0])
        movement.release_forward.assert_called_once_with()

        self.profile = {'specId': 1482, 'rules': [
            {'action': 'spell_116', 'tag': '输出', 'when': ['and',
             ['flag', 'player_moving', False], ['num_at_least', 'distance', 8],
             ['num_below', 'distance', 31], ['flag', 'range_116', True]]}]}
        self.g.speed, self.g.fixtureDistance, self.g.fixtureDistanceReadable = 7, 42, True
        self.assertTrue(self.tick().decision.attack_blocked_by_range)
        self.g.fixtureInRange, self.g.fixtureDistance = True, 30
        in_range = self.tick()
        self.assertEqual(in_range.decision.candidates, ())
        self.assertFalse(in_range.decision.attack_blocked_by_range)

    def test_recovery_does_not_override_either_native_interact_key(self):
        self.lua.execute('''
            function GetBindingKey(action)
                if action=='INTERACTTARGET' then return 'F7','F8' end
            end
        ''')
        self.configure()
        for kind in ('food', 'water'):
            button = self.addon.GetSecureButton('recovery_' + kind)
            self.assertIsNotNone(button)
        for key in ('F7', 'F8'):
            for frame in self.g.frames.values():
                self.assertFalse(frame.bindings and frame.bindings[key], key)

    def test_wand_fallback_requires_equipment_range_and_an_unclaimed_binding(self):
        self.lua.execute('''
            fixtureWand=true;fixtureWandRange=true;fixtureWandFiring=false;fixtureClaimedKey='F7'
            C_Map={GetBestMapForUnit=function() return nil end}
            C_Item={GetItemSubClassInfo=function(class, subclass)
              assert(class==2 and subclass==19);return '魔杖'
            end, IsEquippedItemType=function(kind) return kind=='魔杖' and fixtureWand end}
            function UnitPlayerControlled() return false end
            function UnitIsTapDenied() return false end
            function GetBindingAction(key, override)
              if key==fixtureClaimedKey then return 'JUMP' end
              if override then
                for _,frame in ipairs(frames) do
                  local binding=frame.bindings and frame.bindings[key]
                  if binding then return 'CLICK '..binding.button..':'..binding.mouse end
                end
              end
              return ''
            end
            local originalRange=C_Spell.IsSpellInRange
            function C_Spell.GetSpellName(id) if id==5019 then return '射击' end end
            function C_Spell.IsCurrentSpell(id) return id==5019 and fixtureWandFiring end
            function C_Spell.IsSpellUsable(id) return id==5019 or (id==837 and powerValue>=20) end
            function C_Spell.IsSpellInRange(id, unit)
              if id==5019 then return unit=='target' and fixtureWandRange end
              return originalRange(id, unit)
            end
            WowBuddyDev.RefreshMacroBindings()
            local button=WowBuddyDev.GetSecureButton('shoot_wand')
            function button:GetName() return 'WBD_BTN_shoot_wand' end
        ''')
        self.addon.RebuildPixelBars()
        normal = self.tick()
        self.assertEqual(normal.selected.action, 'spell_116')
        self.assertTrue(any(candidate.action == 'shoot_wand' for candidate in normal.decision.candidates))
        self.g.fixtureInsufficientMana = True
        self.g.powerValue = 0
        result = self.tick(delta=2)
        wand = next(candidate for candidate in result.decision.candidates if candidate.action == 'shoot_wand')
        self.assertEqual(result.selected, wand, result.status)
        self.assertEqual(wand.hold_ms, 1500)
        self.assertNotIn(wand.key, ('F6', 'F7'))
        button = self.addon.GetSecureButton('shoot_wand')
        self.assertEqual(button.GetAttribute(button, 'macrotext'), '/cast [harm,nodead,nochanneling] !射击')
        for state, blocked, ready in [('fixtureWand', False, True), ('fixtureWandRange', False, True),
                                      ('fixtureWandFiring', True, False), ('speed', 7, 0),
                                      ('fixtureClaimedKey', wand.key, 'F7')]:
            self.g[state] = blocked
            self.assertNotIn('shoot_wand_key', self.tick().decision.frame.values, state)
            self.g[state] = ready

    def test_invalid_threshold_does_not_overwrite_settings_and_drag_sets_item(self):
        self.configure()
        panel = self.open_panel()
        box = self.g.WowBuddyDevRecovery_food
        self.lua.execute("function GetCursorInfo() return 'item', 1113 end; function ClearCursor() cursorCleared=true end")
        box.scripts.OnReceiveDrag(box)
        self.assertEqual(box.GetText(box), '1113')
        self.assertTrue(self.g.cursorCleared)
        self.g.WowBuddyDevRecovery_healthResume.SetText(self.g.WowBuddyDevRecovery_healthResume, '60')
        self.click(panel, '保存')
        self.assertTrue(panel.IsShown(panel))
        self.assertEqual(self.addon.DB.recovery.food, 5349)

    def test_click_without_consumption_backs_off_and_recovers_after_inventory_changes(self):
        self.configure(manaStart='0')
        self.g.health = 35
        self.assertEqual(self.tick().selected.action, 'recovery_food')
        self.click_item('food')
        self.assertEqual(self.tick(3.1).selected.action, 'recovery_food')
        self.click_item('food')
        stopped = self.tick(3.1)
        self.assertEqual(stopped.status, 'stopped')
        self.assertIn('等待冷却', stopped.decision.candidates[0].reason)
        self.assertEqual(self.sender.send.call_count, 2)
        for delay in (15, 30, 60, 120, 120):
            with self.subTest(delay=delay):
                self.assertIsNone(self.tick(delay - 0.1).selected)
                self.assertEqual(self.tick(0.2).selected.action, 'recovery_food')
                self.click_item('food')
                self.assertIsNone(self.tick(3.1).selected)
        self.assertEqual(self.sender.send.call_count, 7)
        self.g.inventory[5349] = 4
        self.assertEqual(self.tick().selected.action, 'recovery_food')
        self.click_item('food')
        self.g.inventory[5349] = 3
        self.assertIsNone(self.tick().selected)
        self.g.health = 87
        self.assertEqual(self.tick().selected.action, 'spell_116')


if __name__ == '__main__':
    unittest.main()
