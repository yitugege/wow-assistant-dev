"""插件登出快照（docs/design/20261115-diagnostic-export.md A7、A8）：隔离 Lua 执行，不模拟 WoW 安全环境。"""
from pathlib import Path
import unittest

from lupa.lua51 import LuaRuntime

ADDON = Path(__file__).resolve().parents[1] / 'addon/WowBuddyDev'

HOST = '''
frames = {}
printed = {}
function CreateFrame()
  local frame = { events = {} }
  function frame:RegisterEvent(name) self.events[name] = true end
  function frame:SetScript(kind, fn) self[kind] = fn end
  table.insert(frames, frame)
  return frame
end
function print(text) table.insert(printed, tostring(text)) end
function time() return 1763200000 end
SlashCmdList = {}
function fire(event)
  for _, frame in ipairs(frames) do
    if frame.events[event] and frame.OnEvent then frame.OnEvent(frame, event) end
  end
end
'''


class RuntimeDiagnosticsTests(unittest.TestCase):
    def load(self, prelude=''):
        lua = LuaRuntime(unpack_returned_tuples=True)
        lua.execute(HOST)
        lua.execute((ADDON / 'Modules.lua').read_text('utf-8-sig'))
        lua.execute(prelude)
        lua.execute((ADDON / 'RuntimeDiagnostics.lua').read_text('utf-8-sig'), 'WowBuddyDev')
        return lua

    def lua_list(self, table):
        return [table[i] for i in range(1, len(table) + 1)] if table is not None else None

    def test_a7_logout_snapshot_copies_three_runtime_sources_with_caps(self):
        lua = self.load('''
            for i = 1, 120 do table.insert(WowBuddyDev.moduleErrors, "越界 " .. i) end
            local captured = {}
            for i = 1, 12 do captured[i] = { text = "err " .. i, count = i, firstAt = "10:00:00", lastAt = "10:00:01" } end
            WowBuddyDev.GetCapturedLuaErrors = function() return captured end
            WowBuddyDev.errorLogs = {}
            for i = 1, 60 do WowBuddyDev.errorLogs[i] = { time = "10:00:0" .. (i % 10), type = "cast", message = "m" .. i } end
            WowBuddyDev.addonVersionCode = 0x574201
        ''')
        lua.globals().fire('PLAYER_LOGOUT')
        log = lua.globals().WowBuddyDevRuntimeLog
        self.assertIsNotNone(log)
        self.assertEqual(log.savedAt, 1763200000)
        self.assertEqual(log.addonVersionCode, 0x574201)
        module_errors = self.lua_list(log.moduleErrors)
        self.assertEqual(len(module_errors), 100)
        self.assertEqual(module_errors[-1], '越界 120')   # 保留最新的
        lua_errors = self.lua_list(log.luaErrors)
        self.assertEqual(len(lua_errors), 10)
        self.assertEqual((lua_errors[0].text, lua_errors[0].count), ('err 1', 1))
        error_logs = self.lua_list(log.errorLogs)
        self.assertEqual(len(error_logs), 50)
        self.assertEqual(error_logs[0].message, 'm1')
        # 是副本：之后修改运行时表不影响快照
        lua.execute('WowBuddyDev.moduleErrors[120] = "changed"; WowBuddyDev.GetCapturedLuaErrors()[1].text = "changed"; '
                    'WowBuddyDev.errorLogs[1].message = "changed"')
        self.assertEqual(self.lua_list(log.moduleErrors)[-1], '越界 120')
        self.assertEqual(log.luaErrors[1].text, 'err 1')
        self.assertEqual(log.errorLogs[1].message, 'm1')

    def test_a7_missing_sources_give_empty_lists(self):
        lua = self.load()
        lua.globals().fire('PLAYER_LOGOUT')
        log = lua.globals().WowBuddyDevRuntimeLog
        self.assertEqual((len(log.moduleErrors), len(log.luaErrors), len(log.errorLogs)), (0, 0, 0))

    def test_a7_snapshot_failure_never_breaks_logout(self):
        lua = self.load('WowBuddyDev.GetCapturedLuaErrors = function() error("boom") end')
        lua.globals().fire('PLAYER_LOGOUT')   # 不抛出
        log = lua.globals().WowBuddyDevRuntimeLog
        self.assertTrue(log is None or 'boom' in str(log.snapshotError))

    def test_a7_slash_command_refreshes_and_explains_reload(self):
        lua = self.load('table.insert(WowBuddyDev.moduleErrors, "越界 1")')
        g = lua.globals()
        self.assertEqual(g.SLASH_WBDDIAG1, '/wbddiag')
        g.SlashCmdList.WBDDIAG('')
        self.assertEqual(self.lua_list(g.WowBuddyDevRuntimeLog.moduleErrors), ['越界 1'])
        self.assertTrue(any('/reload' in line for line in self.lua_list(g.printed)))

    # A8
    def test_a8_toc_declares_file_and_saved_variable(self):
        toc = (ADDON / 'WowBuddyDev.toc').read_text('utf-8-sig').splitlines()
        files = [line.strip() for line in toc if line.strip() and not line.startswith('#')]
        self.assertEqual(files.index('RuntimeDiagnostics.lua'), files.index('SecurityDiagnostics.lua') + 1)
        saved = next(line for line in toc if line.startswith('## SavedVariables:'))
        self.assertIn('WowBuddyDevRuntimeLog', [name.strip() for name in saved.split(':', 1)[1].split(',')])


if __name__ == '__main__':
    unittest.main()
