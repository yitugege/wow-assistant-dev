"""开发版插件不被较旧发布包覆盖（docs/design/20261115-addon-overwritten-by-github.md D1–D4）。"""
from concurrent.futures import Future
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'desktop'), str(ROOT), str(ROOT / 'tests')]

from tools.build_addon import build  # noqa: E402
from wowbuddy.addons import dev_addon_install  # noqa: E402
from wowbuddy.core.dev_protocol import DEV_VERSION  # noqa: E402
from wowbuddy.dev_version import VERSION  # noqa: E402
from wowbuddy.update.addon_update import AddonGame  # noqa: E402
from wowbuddy.update.dev_addon_update import apply_release  # noqa: E402


class Pending:
    def __init__(self):
        self.paths = ()

    def read(self):
        return self.paths

    def write(self, paths):
        self.paths = paths


def make_package(root, *, version=None, random_names=False):
    source = root / 'source'
    if not source.exists():
        source.mkdir()
        (source / 'WowBuddyDev.toc').write_text('## Title: WowBuddyDev\n## Version: 0.0.1-dev\nCore.lua\n', 'utf8')
        (source / 'Core.lua').write_text('-- own addon', 'utf8')
    package = root / f'pkg-{version or "current"}-{int(random_names)}.zip'
    manifest = build(source, package, random_names=random_names)
    manifest['protocol_version'] = DEV_VERSION
    if version is not None:
        manifest['version'] = version
    package.with_suffix('.manifest.json').write_text(json.dumps(manifest), 'utf8')
    return package, manifest


def make_client(root, name='client', record_version=None):
    client = root / name
    (client / 'Interface' / 'AddOns').mkdir(parents=True)
    (client / 'Wow.exe').write_bytes(b'MZ')
    if record_version is not False:
        addon = client / 'Interface' / 'AddOns' / 'WowBuddyDev'
        addon.mkdir()
        (addon / 'WowBuddyDev.toc').write_text('## Title: old\n', 'utf8')
        record = {'product': 'wowbuddy-dev', 'addon_directory': 'WowBuddyDev'}
        if record_version:
            record['version'] = record_version
        (client / '.wowbuddy-install.json').write_text(json.dumps(record), 'utf8')
    return client


class VersionStampTests(unittest.TestCase):
    """D1：打包写入版本号，安装记录保存版本号。"""

    def test_d1_package_toc_and_manifest_carry_current_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            for random_names in (False, True):
                with self.subTest(random_names=random_names):
                    package, manifest = make_package(Path(tmp), random_names=random_names)
                    self.assertEqual(manifest['version'], VERSION)
                    import zipfile
                    with zipfile.ZipFile(package) as archive:
                        toc = next(n for n in archive.namelist() if n.endswith('.toc'))
                        lines = archive.read(toc).decode('utf-8-sig').splitlines()
                    self.assertIn(f'## Version: {VERSION}-dev', lines)
                    self.assertEqual(sum(line.startswith('## Version:') for line in lines), 1)

    def test_d1_source_toc_matches_desktop_version(self):
        toc = (ROOT / 'addon/WowBuddyDev/WowBuddyDev.toc').read_text('utf-8-sig').splitlines()
        self.assertIn(f'## Version: {VERSION}-dev', toc)

    def test_d1_install_record_stores_package_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package, _ = make_package(root, version='0.3.0')
            client = make_client(root, record_version=False)
            result = dev_addon_install.install_package(package, client)
            record = json.loads((client / '.wowbuddy-install.json').read_text('utf8'))
            self.assertEqual(record['version'], '0.3.0')
            self.assertEqual(result['version'], '0.3.0')
            self.assertEqual(dev_addon_install.installed_version(client / 'Interface' / 'AddOns'), '0.3.0')
            self.assertEqual(dev_addon_install.package_version(package), '0.3.0')

    def test_d1_version_comparison(self):
        self.assertTrue(dev_addon_install.is_newer('0.2.21', '0.2.8'))
        self.assertFalse(dev_addon_install.is_newer('0.2.8', '0.2.21'))
        self.assertFalse(dev_addon_install.is_newer('0.2.21', '0.2.21'))


class AutomaticRefreshTests(unittest.TestCase):
    """D2：自动热更不降级。"""

    def run_apply(self, record_version):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            package, _ = make_package(root, version='0.2.8')
            client = make_client(root, record_version=record_version)
            addons = client / 'Interface' / 'AddOns'
            logs = []
            install = Mock(return_value=dev_addon_install_result())
            games = lambda: (AddonGame('forever', str(addons), False, 'WowBuddyDev'),)
            state = apply_release({'package': str(package), 'changed': True, 'tag': 'v0.2.8'}, Pending(),
                                  games=games, installed_name=lambda path: 'WowBuddyDev', on_log=logs.append,
                                  install=install)
            return install, state, logs

    def test_d2_skips_client_with_newer_or_equal_version(self):
        for installed in ('0.2.21', '0.2.8'):
            with self.subTest(installed=installed):
                install, state, logs = self.run_apply(installed)
                install.assert_not_called()
                self.assertTrue(any('跳过' in line and installed in line and '0.2.8' in line for line in logs), logs)

    def test_d2_reinstalls_older_or_unknown_versions(self):
        for installed in ('0.2.1', None):
            with self.subTest(installed=installed):
                install, state, logs = self.run_apply(installed)
                install.assert_called_once()


def dev_addon_install_result():
    from wowbuddy.update.addon_update import ReinstallResult
    return ReinstallResult(True, 'WowBuddyDev')


class WindowTests(unittest.TestCase):
    """D3、D4：GitHub 安装降级确认、按钮文字与安装日志（离屏真实窗口）。"""

    def run_window(self, exercise):
        import test_dev_tray
        test_dev_tray.TrayTests.run_window(self, False, exercise)

    def finish_github_download(self, window, client, package):
        from PySide6.QtCore import QTimer
        future = Future()
        future.set_result({'package': str(package), 'tag': 'v0.2.8', 'changed': True})
        window._download_future = future
        window._download_consumed = False
        window._download_client = str(client)
        window._download_timer = QTimer(window)
        window._download_executor = Mock()
        window._finish_github_download()

    def test_d3_older_github_release_needs_confirmation(self):
        def exercise(window):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                package, _ = make_package(root, version='0.2.8')
                client = make_client(root, record_version=VERSION)
                from PySide6.QtWidgets import QMessageBox
                with patch('wowbuddy.addons.dev_addon_install.install_package') as install, \
                        patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.No) as ask:
                    self.finish_github_download(window, client, package)
                ask.assert_called_once()
                prompt = ' '.join(str(arg) for arg in ask.call_args.args)
                self.assertIn('0.2.8', prompt)
                self.assertIn(VERSION, prompt)
                install.assert_not_called()
                self.assertIn('已取消', window.ui.addon_status.text())
                with patch('wowbuddy.addons.dev_addon_install.install_package',
                           return_value={'target': str(client), 'files': 1, 'backup': None, 'cleanup_deleted': 0,
                                         'cleanup_notes': '', 'version': '0.2.8'}) as install, \
                        patch('PySide6.QtWidgets.QMessageBox.question', return_value=QMessageBox.StandardButton.Yes):
                    self.finish_github_download(window, client, package)
                install.assert_called_once()

        self.run_window(exercise)

    def test_d3_newer_github_release_installs_without_prompt(self):
        def exercise(window):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                package, _ = make_package(root, version='9.9.9')
                client = make_client(root, record_version=VERSION)
                with patch('wowbuddy.addons.dev_addon_install.install_package',
                           return_value={'target': str(client), 'files': 1, 'backup': None, 'cleanup_deleted': 0,
                                         'cleanup_notes': '', 'version': '9.9.9'}) as install, \
                        patch('PySide6.QtWidgets.QMessageBox.question') as ask:
                    self.finish_github_download(window, client, package)
                ask.assert_not_called()
                install.assert_called_once()

        self.run_window(exercise)

    def test_d4_buttons_name_source_and_version(self):
        def exercise(window):
            self.assertEqual(window.ui.addon_install_button.text(), f'安装本地构建（v{VERSION}）')
            self.assertIn('WowBuddyDev-dev.zip', window.ui.addon_install_button.toolTip())
            self.assertEqual(window.ui.addon_detect_button.text(), '安装 GitHub 发布版')
            self.assertIn('GitHub', window.ui.addon_detect_button.toolTip())

        self.run_window(exercise)

    def test_d4_install_result_names_source_version_target_and_is_written_to_file(self):
        def exercise(window):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                package, _ = make_package(root, version='0.2.8')
                client = make_client(root, record_version='0.2.1')
                with patch('wowbuddy.addons.dev_addon_install.install_package',
                           return_value={'target': str(client / 'Interface/AddOns/WowBuddyDev'), 'files': 3,
                                         'backup': None, 'cleanup_deleted': 0, 'cleanup_notes': '',
                                         'version': '0.2.8'}):
                    self.finish_github_download(window, client, package)
                status = window.ui.addon_status.text()
                for text in ('GitHub', '0.2.8', str(client)):
                    self.assertIn(text, status)
                log = Path(window.launch_options.data_dir) / 'addon-install.log'
                self.assertTrue(log.is_file())
                self.assertIn('0.2.8', log.read_text('utf-8'))

        self.run_window(exercise)


if __name__ == '__main__':
    unittest.main()
