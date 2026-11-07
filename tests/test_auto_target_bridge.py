"""执行真实Lua选怪状态机，再由桌面解析器解码；不模拟真实游戏施法。"""
import sys
import unittest
from pathlib import Path
from lupa.lua51 import LuaRuntime

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'desktop'))
from wowbuddy.auto_target import parse_auto_target, key_for_index


class AutoTargetBridgeTests(unittest.TestCase):
    def setUp(self):
        self.lua = LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute('''
        WowBuddyDev={DB={masterSwitch=true},classData={}}
        combat=false; exists=true; dead=false; focus=false; enabled=true
        button={HookScript=function(self,event,callback) self.callback=callback end}
        function CreateFrame() return {RegisterEvent=function() end,
          SetScript=function(self,event,fn) resetSession=fn end} end
        function UnitAffectingCombat() return combat end
        function InCombatLockdown() return combat end
        function UnitExists() return exists end
        function UnitIsDeadOrGhost(unit) return unit=='target' and dead or false end
        function UnitCanAttack() return true end
        function UnitCanAssist() return false end
        function GetCurrentKeyBoardFocus() if focus then return {} end end
        function GetSpecialization() return 1 end
        function GetSpecializationInfo() return 1491 end
        function WowBuddyDev.IsRangedDamageSpec() return true end
        function WowBuddyDev.IsMeleeSpec() return false end
        function WowBuddyDev.GetAutoTargetEnabled() return enabled end
        function WowBuddyDev.CreateSecureButton(name,key,text)
          boundKey=key; macro=text; return true
        end
        function WowBuddyDev.GetSecureButton() return button end
        ''')
        for name in ('ActionKeyCheck.lua', 'AutoTarget.lua'):
            self.lua.execute((ROOT/'addon/WowBuddyDev'/name).read_text('utf8'))
        self.assertTrue(self.lua.eval('WowBuddyDev.ApplyAutoTargetBinding()'))

    def packet(self):
        packet = parse_auto_target(self.lua.eval('WowBuddyDev.GetAutoTargetPacket()'))
        self.assertIsNotNone(packet)
        self.assertEqual(packet.key, self.lua.globals().boundKey)
        return packet

    def test_all_lua_key_indices_match_desktop(self):
        keys = self.lua.globals().WowBuddyDev.AUTO_TARGET_KEYS
        self.assertEqual(len(keys), 81)
        for index in range(1, 82):
            self.assertEqual(keys[index], key_for_index(index))

    def test_death_in_combat_requests_target_but_combat_exit_stops(self):
        self.assertEqual(self.packet().state, 0)
        self.lua.execute('combat=true')
        self.assertEqual(self.packet().state, 2)
        self.lua.execute('dead=true')
        self.assertEqual(self.packet().state, 1)
        self.lua.execute('combat=false; resetSession()')
        self.assertEqual(self.packet().state, 0)
        self.assertIn('[combat,nochanneling,dead]', self.lua.globals().macro)

    def test_keyboard_focus_switch_and_click_ack(self):
        self.lua.execute('combat=true')
        self.packet()
        self.lua.execute('exists=false')
        self.assertEqual(self.packet().state, 1)
        self.lua.execute('focus=true')
        self.assertEqual(self.packet().state, 0)
        self.lua.execute('focus=false; enabled=false')
        self.assertEqual(self.packet().state, 0)
        self.lua.execute('enabled=true; button.callback()')
        self.assertEqual(self.packet().ack, 1)
        self.lua.execute('WowBuddyDev.DB.masterSwitch=false')
        self.assertEqual(self.packet().state, 0)
