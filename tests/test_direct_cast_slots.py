"""槽位子模块与原 addon.bin 内完整 DirectCast 对照，不执行真实游戏 API。"""
from pathlib import Path
import unittest
from lupa.lua51 import LuaRuntime
from tests import test_original_direct_cast as original

ROOT = Path(__file__).resolve().parents[1]


class DirectCastSlotsTests(unittest.TestCase):
    def setUp(self):
        reference = original.OriginalDirectCastTests()
        reference.setUp()  # 原包 SHA256 校验及完整原文执行。
        self.reference = reference.lua
        self.product = LuaRuntime(unpack_returned_tuples=True)
        self.product.execute('''
            WowBuddyDev={};SlashCmdList={}
            function wipe(t) for k in pairs(t) do t[k]=nil end end
        ''')
        self.product.execute((ROOT/'addon/WowBuddyDev/DirectCastSlots.lua').read_text('utf8'))
        for lua in (self.reference, self.product):
            lua.execute('messages={}; function print(text) table.insert(messages,text) end')

    def test_manual_commands_match_original_state_and_messages(self):
        commands = ['spell_116 61', 'class_F6 144', 'spell_116 999', 'spell_116 0',
                    'spell_116 -1', 'spell_116 1.5', ' spell_116 2', 'spell_116 2 ',
                    'spell_116\t0007', '', 'spell_116', 'spell_116 3 extra']
        for command in commands:
            with self.subTest(command=command):
                for lua in (self.reference, self.product):
                    lua.globals().SlashCmdList.DCBIND(command)
                self.assertEqual(dict(self.product.globals().WowBuddyDev.DirectCast.slots.items()),
                                 dict(self.reference.globals().P07483180.DirectCast.slots.items()))
                self.assertEqual(list(self.product.globals().messages.values()),
                                 list(self.reference.globals().messages.values()))

    def test_existing_slot_selection_and_nonempty_cache_match_original(self):
        script = '''
            queried={}
            function GetActionInfo(slot)
                table.insert(queried,slot)
                if slot==2 then error('fixture unavailable') end
                if slot==1 or slot==144 then return 'spell',116 end
                if slot==143 then return 'macro',116 end
            end
        '''
        for lua in (self.reference, self.product):
            lua.execute(script)
        self.assertEqual(self.reference.globals().P07483180.DirectCast.Cast('spell_116'),
                         (True, 'slot144'))
        self.assertEqual(self.product.globals().WowBuddyDev.DirectCast.FindSlotForSpell(116), 144)
        self.assertEqual(list(self.product.globals().queried.values()), list(range(1,145)))
        self.assertEqual(list(self.product.globals().queried.values()),
                         list(self.reference.globals().queried.values()))
        for lua in (self.reference, self.product):
            lua.execute("function GetActionInfo() error('must retain original cached index') end")
        self.assertEqual(self.reference.globals().P07483180.DirectCast.Cast('spell_116'),
                         (True, 'slot144'))
        self.assertEqual(self.product.globals().WowBuddyDev.DirectCast.FindSlotForSpell(116), 144)

    def test_empty_index_can_discover_later_action_bar_contents(self):
        self.product.execute('function GetActionInfo() return nil end')
        query = self.product.globals().WowBuddyDev.DirectCast.FindSlotForSpell
        self.assertIsNone(query(116))
        self.product.execute("function GetActionInfo(slot) if slot==33 then return 'spell',116 end end")
        self.assertEqual(query(116), 33)


if __name__ == '__main__':
    unittest.main()
