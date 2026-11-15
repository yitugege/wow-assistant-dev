"""一键导出诊断的离线验收（docs/design/20261115-diagnostic-export.md 第 3 节 A1–A6）。"""
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'desktop'))

from wowbuddy import diagnostic_export as export  # noqa: E402

ACCOUNTS = ('ALPHAACCT', '123456789#1')
USER = 'secretuser'
RANDOM_NAME = 'w0123456789ab'


def tree_digest(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(Path(root).rglob('*')) if p.is_file()}


class Fixture:
    """临时数据目录与一个随机插件目录名的伪客户端（两个账号）。"""

    def __init__(self, root):
        self.root = Path(root)
        self.data = self.root / 'data'
        self.client = self.root / 'game' / '_classic_'
        self.data.mkdir(parents=True)
        (self.data / 'startup.log').write_text(f'启动 C:\\Users\\{USER}\\wow\\run_dev.py\n', 'utf-8')
        (self.data / 'settings.ini').write_text(f'[addon]\nlastDir=C:/Users/{USER}/Games/WoW\n', 'utf-8')
        (self.data / 'engine-selftest.json').write_text('{"ok": true}', 'utf-8')
        logs = self.data / 'logs'
        logs.mkdir()
        for index in range(7):
            path = logs / f'monitor_20261115_10000{index}.log'
            path.write_text(f'监控日志 {index}\n', 'utf-8')
            os.utime(path, (1_000_000 + index, 1_000_000 + index))
        (self.data / 'hub').mkdir()
        (self.data / 'hub' / 'rotations.json').write_text('{}', 'utf-8')
        (self.client / 'Interface' / 'AddOns' / RANDOM_NAME).mkdir(parents=True)
        (self.client / 'Interface' / 'AddOns' / RANDOM_NAME / f'{RANDOM_NAME}.toc').write_text('## Title: x\n', 'utf-8')
        (self.client / 'Wow.exe').write_bytes(b'MZ')
        (self.client / '.wowbuddy-install.json').write_text(
            json.dumps({'product': 'wowbuddy-dev', 'addon_directory': RANDOM_NAME}), 'utf-8')
        for account in ACCOUNTS:
            saved = self.client / 'WTF' / 'Account' / account / 'SavedVariables'
            saved.mkdir(parents=True)
            (saved / f'{RANDOM_NAME}.lua').write_text(
                f'WowBuddyDevRuntimeLog = {{ owner = "{account}", path = "C:\\\\Users\\\\{USER}" }}\n', 'utf-8')
            (saved / 'OtherAddon.lua').write_text('Other = {}\n', 'utf-8')

    def run(self, **options):
        options.setdefault('user_names', (USER,))
        return export.export_diagnostics(self.data, [self.client], **options)


class DiagnosticExportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.fixture = Fixture(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def members(self, result):
        with zipfile.ZipFile(result.path) as archive:
            return {name: archive.read(name) for name in archive.namelist()}

    # A1：导出内容与结构
    def test_a1_zip_contains_manifest_desktop_files_and_saved_variables(self):
        result = self.fixture.run()
        self.assertTrue(result.path.is_file())
        self.assertEqual(result.path.parent, self.fixture.data / 'diagnostics')
        self.assertRegex(result.path.name, r'^wowbuddy-diagnostics-\d{8}-\d{6}\.zip$')
        members = self.members(result)
        manifest = json.loads(members['manifest.json'])
        for name in ('desktop/startup.log', 'desktop/settings.ini', 'desktop/engine-selftest.json'):
            self.assertIn(name, members)
        self.assertNotIn('desktop/hub/rotations.json', members)
        saved = sorted(n for n in members if n.startswith('clients/1/savedvariables/'))
        self.assertEqual(saved, ['clients/1/savedvariables/<ACCOUNT-1>/WowBuddyDev.lua',
                                 'clients/1/savedvariables/<ACCOUNT-2>/WowBuddyDev.lua'])
        self.assertIn('clients/1/install.json', members)
        self.assertEqual(manifest['clients'][0]['addon_directory'], RANDOM_NAME)
        self.assertFalse(manifest['game_verified'])
        self.assertIn('startup-error.log', manifest['missing'])
        self.assertEqual(set(manifest['members']), set(members) - {'manifest.json'})

    def test_a1_only_latest_five_monitor_logs(self):
        members = self.members(self.fixture.run())
        logs = sorted(n for n in members if n.startswith('desktop/logs/'))
        self.assertEqual(logs, [f'desktop/logs/monitor_20261115_10000{i}.log' for i in range(2, 7)])

    def test_a1_client_without_this_addon_exports_no_saved_variables(self):
        (self.fixture.client / '.wowbuddy-install.json').unlink()
        members = self.members(self.fixture.run())
        self.assertFalse([n for n in members if n.startswith('clients/')])
        manifest = json.loads(members['manifest.json'])
        self.assertEqual(manifest['clients'][0]['addon_directory'], '')

    # A2：脱敏
    def test_a2_account_and_user_names_never_appear(self):
        members = self.members(self.fixture.run())
        secrets = [s.encode('utf-8') for s in (*ACCOUNTS, USER)] + [USER.upper().encode('utf-8')]
        for name, data in members.items():
            for secret in secrets:
                with self.subTest(member=name, secret=secret):
                    self.assertNotIn(secret.lower(), name.encode('utf-8').lower())
                    self.assertNotIn(secret.lower(), data.lower())
        manifest = json.loads(members['manifest.json'])
        self.assertTrue(manifest['redactions'])
        self.assertIn(b'<ACCOUNT-1>', members['clients/1/savedvariables/<ACCOUNT-1>/WowBuddyDev.lua'])
        self.assertIn(b'<USER>', members['desktop/startup.log'])

    def test_a2_redaction_respects_word_boundaries(self):
        text = export.redact('xALPHAACCTy ALPHAACCT secretuserz', {'ALPHAACCT': '<ACCOUNT-1>'}, ('secretuser',))
        self.assertEqual(text, 'xALPHAACCTy <ACCOUNT-1> secretuserz')

    # A3：限量与只读
    def test_a3_large_file_keeps_tail_and_total_limit_skips(self):
        big = self.fixture.data / 'startup.log'
        big.write_bytes(b'HEAD' + b'x' * 5000 + b'TAIL')
        members = self.members(self.fixture.run(max_file_bytes=1000))
        manifest = json.loads(members['manifest.json'])
        self.assertIn('desktop/startup.log', manifest['truncated'])
        self.assertTrue(members['desktop/startup.log'].endswith(b'TAIL'))
        self.assertNotIn(b'HEAD', members['desktop/startup.log'])
        self.assertLessEqual(len(members['desktop/startup.log']), 1000)
        self.assertEqual(manifest['skipped'], [])
        total = sum(len(v) for k, v in members.items() if k != 'manifest.json')
        limited = self.members(self.fixture.run(max_file_bytes=1000, max_total_bytes=total - 1))
        manifest = json.loads(limited['manifest.json'])
        self.assertTrue(manifest['skipped'])
        self.assertLessEqual(sum(len(v) for k, v in limited.items() if k != 'manifest.json'), total - 1)
        # 监控日志排在最后，超限时先跳过它们，SavedVariables 与启动日志保留。
        self.assertTrue(all(name.startswith('desktop/logs/') for name in manifest['skipped']))
        self.assertIn('clients/1/savedvariables/<ACCOUNT-1>/WowBuddyDev.lua', limited)

    def test_a3_sources_unchanged_and_nothing_written_outside_data_dir(self):
        root = Path(self.temporary.name)
        game_before = tree_digest(self.fixture.client)
        data_before = tree_digest(self.fixture.data)
        outside_before = {p for p in root.iterdir()}
        result = self.fixture.run()
        self.assertEqual(tree_digest(self.fixture.client), game_before)
        after = tree_digest(self.fixture.data)
        new = set(after) - set(data_before)
        self.assertEqual(new, {f'diagnostics/{result.path.name}'})
        self.assertEqual({k: after[k] for k in data_before}, data_before)
        self.assertEqual({p for p in root.iterdir()}, outside_before)

    # A4：客户端发现不受窗口环境影响
    def test_a4_find_clients_ignores_no_game_scan_environment(self):
        class Snapshot:
            addon_last_dir = str(self.fixture.client)
            addon_history = ()

        class Settings:
            def snapshot(self):
                return Snapshot()

            def _read(self, key, default, kind):
                return []

        with patch.dict(os.environ, {'WOWBUDDY_NO_GAME_SCAN': '1'}):
            clients = export.find_clients(Settings(), search_roots=())
        self.assertEqual([Path(c) for c in clients], [self.fixture.client.absolute()])

    def test_a4_find_clients_scans_common_roots_by_default(self):
        class Settings:
            def snapshot(self):
                return type('Snapshot', (), {'addon_last_dir': '', 'addon_history': ()})()

            def _read(self, key, default, kind):
                return []

        with patch('wowbuddy.addons.dev_game_paths.common_roots', return_value=(self.fixture.client.parent,)), \
                patch('wowbuddy.addons.dev_game_paths.VARIANTS', ('_classic_',)):
            clients = export.find_clients(Settings())
        self.assertEqual([Path(c) for c in clients], [self.fixture.client.absolute()])


class DiagnosticExportCommandTests(unittest.TestCase):
    """A5：run_dev.py --export-diagnostics。"""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.fixture = Fixture(self.temporary.name)
        sys.path.insert(0, str(ROOT))
        import run_dev
        self.run_dev = run_dev

    def tearDown(self):
        self.temporary.cleanup()

    def test_a5_command_exports_and_reports(self):
        with patch('wowbuddy.diagnostic_export.find_clients', return_value=(self.fixture.client,)), \
                patch('wowbuddy.diagnostic_export.default_user_names', return_value=(USER,)):
            code = self.run_dev.main(['run_dev.py', '--export-diagnostics', f'--data-dir={self.fixture.data}'])
        self.assertEqual(code, 0)
        report = json.loads((self.fixture.data / 'diagnostics-export.json').read_text('utf-8'))
        self.assertTrue(report['ok'])
        self.assertTrue(Path(report['path']).is_file())
        self.assertIn('clients/1/savedvariables/<ACCOUNT-1>/WowBuddyDev.lua', report['members'])
        self.assertIn('startup-error.log', report['missing'])
        text = json.dumps(report, ensure_ascii=False).lower()
        self.assertNotIn(USER, text)
        self.assertNotIn(ACCOUNTS[0].lower(), text)

    def test_a5_command_failure_returns_1_and_records_error(self):
        def broken(*args, **kwargs):
            raise OSError('来源不可读')
        with patch('wowbuddy.diagnostic_export.export_diagnostics', side_effect=broken), \
                patch('wowbuddy.diagnostic_export.find_clients', return_value=()):
            code = self.run_dev.main(['run_dev.py', '--export-diagnostics', f'--data-dir={self.fixture.data}'])
        self.assertEqual(code, 1)
        report = json.loads((self.fixture.data / 'diagnostics-export.json').read_text('utf-8'))
        self.assertFalse(report['ok'])
        self.assertIn('来源不可读', report['error'])

    def test_a5_command_rejects_unrelated_options(self):
        with self.assertRaises(SystemExit):
            self.run_dev.main(['run_dev.py', '--export-diagnostics', '--engine-selftest',
                               f'--data-dir={self.fixture.data}'])


class DiagnosticExportWindowTests(unittest.TestCase):
    """A6：开发版窗口的“导出诊断”按钮（离屏 Qt，经 run_dev.launch 启动真实窗口）。"""

    def run_window(self, exercise):
        sys.path.insert(0, str(ROOT / 'tests'))
        import test_dev_tray
        test_dev_tray.TrayTests.run_window(self, False, exercise)

    def test_a6_button_exports_logs_and_opens_folder(self):
        opened = []

        def exercise(window):
            button = window.ui.export_diagnostics_button
            self.assertEqual(button.objectName(), 'ExportDiagnostics')
            self.assertTrue(button.isEnabled())
            self.assertIn('/reload', button.toolTip())
            target = Path(window.launch_options.data_dir) / 'diagnostics' / 'x.zip'
            result = export.ExportResult(target, members={'manifest.json': {}, 'desktop/startup.log': {}},
                                         missing=['startup-error.log'])
            with patch('wowbuddy.diagnostic_export.find_clients', return_value=()) as find, \
                    patch('wowbuddy.diagnostic_export.export_diagnostics', return_value=result) as run, \
                    patch('PySide6.QtGui.QDesktopServices.openUrl', side_effect=lambda url: opened.append(url)):
                button.click()
            find.assert_called_once()
            self.assertEqual(Path(run.call_args.args[0]), Path(window.launch_options.data_dir))
            log = window.ui.log_view.toPlainText()
            self.assertIn('已导出诊断：', log)
            self.assertIn(str(target), log)
            self.assertIn('缺少 1 项', log)
            self.assertTrue(button.isEnabled())
            self.assertEqual(Path(opened[0].toLocalFile()), target.parent)

        self.run_window(exercise)

    def test_a6_failure_is_logged_without_crashing(self):
        def exercise(window):
            button = window.ui.export_diagnostics_button
            with patch('wowbuddy.diagnostic_export.find_clients', return_value=()), \
                    patch('wowbuddy.diagnostic_export.export_diagnostics', side_effect=OSError('磁盘已满')), \
                    patch('PySide6.QtGui.QDesktopServices.openUrl') as open_url:
                button.click()
            self.assertIn('诊断导出失败：', window.ui.log_view.toPlainText())
            self.assertIn('磁盘已满', window.ui.log_view.toPlainText())
            open_url.assert_not_called()
            self.assertTrue(button.isEnabled())

        self.run_window(exercise)


if __name__ == '__main__':
    unittest.main()
