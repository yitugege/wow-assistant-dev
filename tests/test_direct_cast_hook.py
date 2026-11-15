"""DirectCast 按钮点击挂钩：完整登录夹具上的离线行为测试，不发送真实游戏输入。

宿主按实机记录的顺序模拟一次点击：PreClick → 默认动作 → PostClick。
战斗中宿主拒绝写安全属性，用来证明挂钩在战斗中不碰按钮属性。
"""
import unittest
from tests import test_addon_full_load as full_load

HOST = '''
directCalls={};attributeWrites={};speed=0;castTime=2000;auraPresent=false
function GetUnitSpeed() return speed end
function GetSpellInfo(name) return name,nil,nil,castTime,nil,nil,116 end
function GetActionInfo(slot) if slot==7 then return 'spell',116 end end
function UseAction(slot,unit) table.insert(directCalls,'use:'..slot) end
function CastSpellByID(id,unit) table.insert(directCalls,'cast:'..id) end
C_UnitAuras=C_UnitAuras or {}
function C_UnitAuras.GetPlayerAuraBySpellID(id) if auraPresent then return {spellId=id} end end
local methods=getmetatable(UIParent).__index
local rawSet=methods.SetAttribute
function methods:SetAttribute(key,value)
  if self.template=='SecureActionButtonTemplate' then
    assert(not combat,'fixture combat attribute denied')
    table.insert(attributeWrites,tostring(key)..'='..tostring(value))
  end
  return rawSet(self,key,value)
end
-- 一次点击的一个阶段；返回默认动作执行时按钮的 type。
function ClickPhase(button,down)
  if button.scripts.PreClick then button.scripts.PreClick(button,'LeftButton',down) end
  local seen=button:GetAttribute('type')
  if button.scripts.PostClick then button.scripts.PostClick(button,'LeftButton',down) end
  return seen
end
'''


class DirectCastHookTests(unittest.TestCase):
    ACTION = 'class_NUMPAD5'

    def fixture(self, combat=False):
        lua = full_load.AddonFullLoadTests().login_fixture('MAGE', 8, 1482)
        lua.execute(HOST)
        g = lua.globals()
        g.combat = combat
        addon = g.WowBuddyDev
        button = addon.GetSecureButton(self.ACTION)
        self.assertIsNotNone(button)
        return lua, g, addon, addon.DirectCast, button

    def click(self, g, button):
        return g.ClickPhase(button, True), g.ClickPhase(button, False)

    def test_login_attaches_hook_to_every_class_button(self):
        _, _, addon, dc, _ = self.fixture()
        keys = list(addon.GetClassMacroKeys().values())
        self.assertGreaterEqual(dc.HookStatus().installed, len(keys))
        for key in keys:
            scripts = addon.GetSecureButton('class_' + key).scripts
            self.assertIsNotNone(scripts.PreClick, key)
            self.assertIsNotNone(scripts.PostClick, key)
        self.assertEqual(dc.HookStatus().errors, 0)
        self.assertEqual(len(addon.errorLogs), 0)

    def test_moving_cast_is_swallowed_for_down_and_up_then_restored(self):
        _, g, _, dc, button = self.fixture()
        g.speed = 7
        self.assertEqual(self.click(g, button), ('emptybutton', 'emptybutton'))
        self.assertEqual(button.attributes['type'], 'macro')
        status = dc.HookStatus()
        self.assertEqual((status.swallowed, status.lastReason, status.lastAction),
                         (1, 'moving-cast', self.ACTION))
        self.assertEqual(list(g.directCalls.values()), [])
        # 停步后的下一次点击照常走宏。
        g.speed = 0
        self.assertEqual(self.click(g, button), ('macro', 'macro'))
        self.assertEqual(dc.HookStatus().swallowed, 1)

    def test_swallow_does_not_register_resend_intent(self):
        lua, g, _, dc, button = self.fixture()
        g.speed = 7
        self.click(g, button)
        g.speed = 0
        tickers = [t for _, t in g.loadTickers.items()
                   if lua.eval('debug.getinfo')(t.callback).source == '@DirectCastMovement.lua']
        self.assertEqual(len(tickers), 1)
        for _ in range(4):
            tickers[0].callback()
        self.assertEqual(list(g.directCalls.values()), [])

    def test_standing_instant_and_disabled_leave_macro_untouched(self):
        for scenario in ('standing', 'instant', 'dc-off', 'hook-off'):
            with self.subTest(scenario=scenario):
                _, g, _, dc, button = self.fixture()
                g.speed = 0 if scenario == 'standing' else 7
                if scenario == 'instant':
                    g.castTime = 0
                elif scenario == 'dc-off':
                    g.SlashCmdList.DIRECTCAST('off')
                elif scenario == 'hook-off':
                    g.SlashCmdList.DIRECTCAST('hook off')
                before = len(g.attributeWrites)
                self.assertEqual(self.click(g, button), ('macro', 'macro'))
                self.assertEqual(len(g.attributeWrites), before)
                self.assertEqual(dc.HookStatus().swallowed, 0)

    def test_combat_never_writes_secure_attributes(self):
        _, g, _, dc, button = self.fixture()
        g.combat = True
        g.speed = 7
        before = len(g.attributeWrites)
        self.assertEqual(self.click(g, button), ('macro', 'macro'))
        self.assertEqual(len(g.attributeWrites), before)
        status = dc.HookStatus()
        self.assertEqual((status.swallowed, status.combatSkipped, status.errors,
                          status.lastSkipped), (0, 1, 0, 'moving-cast'))

    def test_combat_starting_between_down_and_up_releases_the_up_phase(self):
        _, g, _, dc, button = self.fixture()
        g.speed = 7
        self.assertEqual(g.ClickPhase(button, True), 'emptybutton')
        self.assertEqual(button.attributes['type'], 'macro')
        g.combat = True
        before = len(g.attributeWrites)
        self.assertEqual(g.ClickPhase(button, False), 'macro')
        self.assertEqual(len(g.attributeWrites), before)
        self.assertEqual(dc.HookStatus().errors, 0)

    def test_stale_down_does_not_swallow_a_late_up(self):
        _, g, _, _, button = self.fixture()
        g.speed = 7
        self.assertEqual(g.ClickPhase(button, True), 'emptybutton')
        g.fixtureTime = (g.fixtureTime or g.GetTime()) + 5
        g.GetTime = lambda: g.fixtureTime
        self.assertEqual(g.ClickPhase(button, False), 'macro')

    def test_self_buff_with_aura_present_is_swallowed_out_of_combat(self):
        _, g, addon, dc, button = self.fixture()
        g.castTime = 0
        addon._pixelStripV2BySpec = g.loadstring(
            "return {[1482]={{kind='presence',unit='player',filter='HELPFUL',spellIDs={116},name='x'}}}")()
        g.auraPresent = True
        self.assertEqual(self.click(g, button), ('emptybutton', 'emptybutton'))
        self.assertEqual(dc.HookStatus().lastReason, 'blocked-aura-present')
        g.auraPresent = False
        self.assertEqual(self.click(g, button), ('macro', 'macro'))
        self.assertEqual(list(g.directCalls.values()), [])

    def test_rebinding_reuses_hook_and_observer_failure_keeps_binding(self):
        _, g, addon, dc, button = self.fixture()
        installed = dc.HookStatus().installed
        macro = addon.GetBoundMacro(self.ACTION)
        self.assertTrue(addon.CreateSecureButton(self.ACTION, 'NUMPAD5', macro))
        self.assertEqual(dc.HookStatus().installed, installed)
        self.assertFalse(dc.AttachButton(True, self.ACTION))
        self.assertFalse(dc.AttachButton(button, ''))
        addon.OnSecureButtonBound = g.loadstring("return function() error('fixture observer failure') end")()
        self.assertTrue(addon.CreateSecureButton(self.ACTION, 'NUMPAD5', macro))
        self.assertEqual(addon.GetBoundMacro(self.ACTION), macro)

    def entries(self, g):
        return list(g.WowBuddyDevHookLog.presses.values())

    def test_log_is_created_lazily_and_records_each_decision(self):
        _, g, _, dc, button = self.fixture()
        self.assertIsNone(g.WowBuddyDevHookLog)
        g.ClickPhase(button, True); g.ClickPhase(button, False)
        g.speed = 7
        g.ClickPhase(button, True); g.ClickPhase(button, False)
        g.combat = True
        g.ClickPhase(button, True); g.ClickPhase(button, False)
        g.combat = False
        g.SlashCmdList.DIRECTCAST('hook off')
        g.ClickPhase(button, True)
        log = g.WowBuddyDevHookLog
        self.assertEqual((log.version, log.build, log.interface), ('1.60.1', '60000', '16001'))
        rows = [(e.decision, e.reason, e.action, e.combat) for e in self.entries(g)]
        self.assertEqual(rows, [('pass', None, self.ACTION, False),
                                ('swallow', 'moving-cast', self.ACTION, False),
                                ('combat-pass', 'moving-cast', self.ACTION, True),
                                ('disabled', None, self.ACTION, False)])
        swallow = self.entries(g)[1]
        self.assertEqual((swallow.speed, swallow.typeAtClick, swallow.typeAfterPost),
                         ('7', 'emptybutton', 'macro'))
        self.assertEqual(dc.HookStatus().logged, 4)

    def test_spell_events_attach_to_latest_press_within_window(self):
        _, g, _, _, button = self.fixture()
        g.ClickPhase(button, True)
        g.EmitFixtureEvent('UNIT_SPELLCAST_SENT', 'player', 'target', 'guid', 116)
        g.EmitFixtureEvent('UNIT_SPELLCAST_START', 'party1', 'guid', 116)
        g.EmitFixtureEvent('UI_ERROR_MESSAGE', 50, '移动中无法施法')
        events = list(self.entries(g)[0].events.values())
        self.assertEqual([(e.event, e.spell, e.message) for e in events],
                         [('UNIT_SPELLCAST_SENT', '116', None),
                          ('UI_ERROR_MESSAGE', None, '移动中无法施法')])
        g.now = g.now + 2
        g.EmitFixtureEvent('UNIT_SPELLCAST_SUCCEEDED', 'player', 'guid', 116)
        self.assertEqual(len(self.entries(g)[0].events), 2)

    def test_log_is_capped_and_can_be_cleared(self):
        _, g, _, dc, button = self.fixture()
        for _ in range(205):
            g.ClickPhase(button, True)
        self.assertEqual(len(g.WowBuddyDevHookLog.presses), 200)
        g.SlashCmdList.DIRECTCAST('log clear')
        self.assertIsNone(g.WowBuddyDevHookLog)
        self.assertEqual(dc.HookStatus().logged, 0)
        g.EmitFixtureEvent('UNIT_SPELLCAST_SENT', 'player', 'target', 'guid', 116)
        self.assertIsNone(g.WowBuddyDevHookLog)

    def test_leftover_swallow_is_restored_when_combat_ends(self):
        _, g, _, _, button = self.fixture()
        g.speed = 7
        button.scripts.PreClick(button, 'LeftButton', True)
        self.assertEqual(button.attributes['type'], 'emptybutton')
        g.EmitFixtureEvent('PLAYER_REGEN_ENABLED')
        self.assertEqual(button.attributes['type'], 'macro')


if __name__ == '__main__':
    unittest.main()
