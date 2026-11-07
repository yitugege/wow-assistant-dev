"""执行源码/发布包完整 TOC 顶层；不模拟登录、定时器或受保护执行。"""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import zipfile

from lupa.lua51 import LuaRuntime
from tools.build_addon import build

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'addon/WowBuddyDev'


class AddonFullLoadTests(unittest.TestCase):
    def load(self, directory, addon_name):
        lua = LuaRuntime(unpack_returned_tuples=True,
                         register_eval=False, register_builtins=False)
        for host in ('pixelbar_host.lua', 'addon_load_host.lua'):
            lua.execute((ROOT / 'tests' / host).read_text('utf8'))
        shared = lua.table()
        loaded = []
        for line in (directory / f'{addon_name}.toc').read_text('utf-8-sig').splitlines():
            entry = line.strip()
            if not entry or entry.startswith('#'):
                continue
            self.assertEqual(Path(entry).suffix, '.lua')
            path = (directory / entry.replace('\\', '/')).resolve()
            self.assertTrue(path.is_relative_to(directory.resolve()))
            # 不捕获后继续：任意模块加载失败即使本测试失败。
            lua.execute(path.read_text('utf-8-sig'), addon_name, shared, name='@'+entry)
            loaded.append(entry)
        addon = lua.globals().WowBuddyDev
        self.assertEqual(set(addon.classes.keys()), set(range(1482, 1492)) - {1483})
        for name in ('mainFrame', 'configFrame', 'macroEditorFrame', 'DecisionBridge'):
            self.assertIsNotNone(addon[name], name)
        for name in ('GetAutoTargetPacket', 'GetRaidFocusPacket', 'RebuildPixelBars'):
            self.assertEqual(lua.eval('type')(addon[name]), 'function', name)
        self.assertIsNotNone(lua.globals().LibStub(addon_name+'-RangeCheck-3.0'))
        self.assertIsNone(lua.globals().WowBuddyDevDiagnostics)
        return lua, loaded

    def test_source_complete_toc_loads(self):
        self.load(SOURCE, 'WowBuddyDev')

    def test_randomized_package_loads_and_records_actual_addon_identity(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = build(SOURCE, root/'addon.zip', random_names=True)
            name = manifest['addon_directory']
            with zipfile.ZipFile(root/'addon.zip') as archive:
                archive.extractall(root/'unpacked')
            lua, loaded = self.load(root/'unpacked'/name, name)
            self.assertTrue(all(Path(entry).name.startswith('f') for entry in loaded))
            lua.globals().actualAddonName = name
            lua.execute('''
                local count=0
                for _,frame in ipairs(frames) do
                    if frame.events and frame.events.ADDON_ACTION_BLOCKED then
                        count=count+1
                        frame.scripts.OnEvent(frame,'ADDON_ACTION_BLOCKED','unrelated','Other')
                        assert(WowBuddyDevDiagnostics == nil)
                        for i=1,51 do
                            frame.scripts.OnEvent(frame,'ADDON_ACTION_BLOCKED',actualAddonName,'Operation'..i)
                        end
                        frame.scripts.OnEvent(frame,'ADDON_ACTION_FORBIDDEN',actualAddonName,'Final')
                    end
                end
                assert(count==1)
                assert(#WowBuddyDevDiagnostics==50)
                assert(WowBuddyDevDiagnostics[1].operation=='Operation3')
                assert(WowBuddyDevDiagnostics[50].addon==actualAddonName)
                assert(WowBuddyDevDiagnostics[50].event=='ADDON_ACTION_FORBIDDEN')
                assert(WowBuddyDevDiagnostics[50].operation=='Final')
            ''')


if __name__ == '__main__':
    unittest.main()
