"""开发版客户端识别：官方经典服执行文件与子目录（docs/design/20261115-diagnostic-export.md A10、A11）。"""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'desktop'))

from wowbuddy.addons import dev_addon_install, dev_game_paths  # noqa: E402
from wowbuddy.addons.addon_install import GAME_VARIANTS  # noqa: E402
from wowbuddy.win32.game_windows import GAME_EXECUTABLES  # noqa: E402


class EmptySettings:
    def snapshot(self):
        return type('Snapshot', (), {'addon_last_dir': '', 'addon_history': ()})()

    def _read(self, key, default, kind):
        return []


class ClientRecognitionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / 'World of Warcraft'
        self.root.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def client(self, variant, executable):
        path = self.root / variant
        (path / 'Interface' / 'AddOns').mkdir(parents=True)
        (path / executable).write_bytes(b'MZ')
        return path

    # A10
    def test_a10_classic_executables_are_accepted(self):
        for index, executable in enumerate(('WowClassic.exe', 'WowClassicB.exe', 'wowclassic.EXE')):
            with self.subTest(executable=executable):
                path = self.client(f'variant{index}', executable)
                self.assertEqual(dev_addon_install.client_directory(path), path.resolve())
                self.assertEqual(dev_addon_install.client_directory(path / 'Interface' / 'AddOns'), path.resolve())

    def test_a10_directory_without_game_executable_is_rejected_with_full_list(self):
        path = self.root / '_classic_'
        path.mkdir()
        (path / 'Launcher.exe').write_bytes(b'MZ')
        with self.assertRaises(ValueError) as raised:
            dev_addon_install.client_directory(path)
        for name in ('Wow.exe', 'WowB.exe', 'WowClassic.exe', 'WowClassicB.exe'):
            self.assertIn(name, str(raised.exception))

    def test_a10_client_executables_match_window_layer(self):
        self.assertEqual({name.casefold() for name in dev_addon_install.CLIENT_EXECUTABLES}, set(GAME_EXECUTABLES))

    # A11
    def test_a11_discovers_classic_variants_from_install_root(self):
        classic = self.client('_classic_', 'WowClassic.exe')
        era = self.client('_classic_era_', 'WowClassic.exe')
        found = dev_game_paths.discover_clients(EmptySettings(), search_roots=(self.root,))
        self.assertEqual(set(found), {classic.resolve(), era.resolve()})

    def test_a11_existing_variants_still_discovered(self):
        expected = {self.client('_classic_beta_', 'WowB.exe').resolve(),
                    self.client('_cn_beta_', 'Wow.exe').resolve(),
                    self.client('_forever_', 'Wow.exe').resolve()}
        found = dev_game_paths.discover_clients(EmptySettings(), search_roots=(self.root,))
        self.assertEqual(set(found), expected)

    def test_a11_original_parity_variants_unchanged(self):
        self.assertEqual(GAME_VARIANTS, (("_classic_beta_", "WowB.exe"), ("_cn_beta_", "Wow.exe")))


if __name__ == '__main__':
    unittest.main()
