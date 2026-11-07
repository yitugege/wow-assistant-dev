"""真实Qt按钮到ZIP校验/暂存；只替代网络传输与进程交接，不启动下载内容。"""
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'desktop')]
import run_dev
from tools.build_client_release import build_client
from wowbuddy import github_client


class ManualUpdateTests(unittest.TestCase):
    def test_exited_or_timed_out_helper_restores_retry_even_with_bad_report(self):
        from test_dev_tray import TrayTests
        from PySide6.QtCore import QTimer
        import time
        def exercise(window):
            with TemporaryDirectory() as temporary:
                root = Path(temporary)
                staged = {'staged': str(root / 'verified-stage')}
                for index, (exit_code, content) in enumerate((
                    (1, None), (None, None), (1, '{"error":"helper failed"}'),
                    (1, '{'), (1, '[]'), (1, '{"error":42}'),
                )):
                    with self.subTest(exit_code=exit_code, report=content):
                        job = root / ('job' + str(index) + '.json')
                        if content is not None:
                            job.with_suffix('.result.json').write_text(content, 'utf8')
                        window._client_update_staged = staged
                        window._handoff = {'job': str(job), 'process': SimpleNamespace(poll=lambda: exit_code)}
                        window._handoff_timer = QTimer(window)
                        window._handoff_timer.start(100)
                        window._handoff_deadline = time.monotonic() - 1
                        window.ui.update_check_button.setEnabled(False)
                        window.ui.update_apply_button.setEnabled(False)
                        with patch.object(window, '_quit_development_app') as quit_app:
                            window._poll_update_handoff()
                            quit_app.assert_not_called()
                        self.assertTrue(job.with_suffix('.cancel.json').is_file())
                        self.assertIsNone(window._handoff)
                        self.assertFalse(window._handoff_timer.isActive())
                        self.assertIs(window._client_update_staged, staged)
                        self.assertTrue(window.ui.update_check_button.isEnabled())
                        self.assertTrue(window.ui.update_apply_button.isEnabled())
                        self.assertEqual(window.ui.update_apply_button.text(), '重试安装')
                        self.assertIn('保持运行', window.ui.update_status.text())
        TrayTests.run_window(self, False, exercise)

    def test_cancel_write_failure_recovers_only_after_helper_exit(self):
        from test_dev_tray import TrayTests
        from PySide6.QtCore import QTimer
        from unittest.mock import Mock
        def exercise(window):
            with TemporaryDirectory() as temporary:
                for initially_running in (False, True):
                    with self.subTest(running=initially_running):
                        job=Path(temporary)/('running.json' if initially_running else 'stopped.json')
                        process=Mock()
                        process.poll.return_value=None if initially_running else 1
                        process.terminate.side_effect=PermissionError('cannot terminate helper')
                        window._handoff={'job':str(job),'process':process}
                        window._client_update_staged={'staged':'verified-stage'}
                        window._handoff_timer=QTimer(window)
                        window._handoff_timer.start(100)
                        window._handoff_deadline=0
                        window.ui.update_check_button.setEnabled(False)
                        window.ui.update_apply_button.setEnabled(False)
                        with patch('wowbuddy.dev_update_handoff.write_json',side_effect=OSError('read only')), \
                             patch.object(window,'_quit_development_app') as quit_app:
                            window._poll_update_handoff()
                            if initially_running:
                                self.assertIsNotNone(window._handoff)
                                self.assertTrue(window._handoff_timer.isActive())
                                self.assertFalse(window.ui.update_apply_button.isEnabled())
                                job.with_suffix('.ready.json').write_text('{}','utf8')
                                window._poll_update_handoff()
                                quit_app.assert_not_called()
                                process.terminate.assert_called_once()
                                process.poll.return_value=1
                                window._poll_update_handoff()
                            quit_app.assert_not_called()
                        self.assertIsNone(window._handoff)
                        self.assertFalse(window._handoff_timer.isActive())
                        self.assertTrue(window.ui.update_check_button.isEnabled())
                        self.assertTrue(window.ui.update_apply_button.isEnabled())
                        self.assertEqual(window.ui.update_apply_button.text(),'重试安装')
                        self.assertIn('无法保存取消记录',window.ui.update_status.text())
        TrayTests.run_window(self,False,exercise)

    def test_buttons_download_verify_then_retry_failed_handoff(self):
        from test_dev_tray import TrayTests
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source'
            source.mkdir()
            (source / '_internal').mkdir()
            (source / '_internal/runtime.dll').write_bytes(b'fixture runtime')
            (source / 'WowBuddyDev.exe').write_bytes(b'MZ fixture never executed')
            package = root / github_client.ZIP_NAME
            manifest = build_client(source, package, '9.0.0')
            base = 'https://github.com/' + github_client.REPOSITORY + '/releases/download/v9.0.0/'
            release = {'tag_name': 'v9.0.0', 'assets': [
                {'name': n, 'browser_download_url': base + n}
                for n in (github_client.ZIP_NAME, github_client.MANIFEST_NAME)]}
            requests = []
            def fetch(url, limit, progress=None):
                requests.append(url)
                if url == base + github_client.ZIP_NAME:
                    payload = package.read_bytes()
                    if progress:
                        progress(len(payload), len(payload))
                    return payload
                if url == base + github_client.MANIFEST_NAME:
                    return json.dumps(manifest).encode()
                return json.dumps(release).encode()
            original_check = github_client.check_latest
            original_download = github_client.download_checked
            def check():
                return original_check(current_version='0.2.8', fetch=fetch)
            def download(info, workspace, **kwargs):
                return original_download(info, workspace, fetch=fetch, **kwargs)
            def exercise(window):
                with patch.object(run_dev, 'FROZEN', True), patch.object(run_dev, 'APP_ROOT', root / 'client'), \
                     patch.object(github_client, 'check_latest', check), \
                     patch.object(github_client, 'download_checked', download):
                    window.ui.update_check_button.click()
                    window._client_update_future.result(timeout=5)
                    window._finish_client_update_task()
                    self.assertEqual(window.ui.update_apply_button.text(), '下载更新包')
                    self.assertFalse(window._client_auto_chain)
                    self.assertIsNone(window._client_update_staged)
                    window.ui.update_apply_button.click()
                    window._client_update_future.result(timeout=5)
                    window._finish_client_update_task()
                    staged = window._client_update_staged
                    self.assertEqual((Path(staged['staged']) / 'WowBuddyDev.exe').read_bytes(),
                                     b'MZ fixture never executed')
                    self.assertEqual(window.ui.update_apply_button.text(), '安装并重启')
                    self.assertTrue(window.ui.update_apply_button.isEnabled())
                    job = root / 'handoff.json'
                    handoff = {'job': str(job), 'process': SimpleNamespace(poll=lambda: None)}
                    with patch('wowbuddy.dev_update_handoff.prepare_handoff', side_effect=[OSError('runtime copy failed'), handoff]) as prepare:
                        window.ui.update_apply_button.click()
                        with self.assertRaises(OSError):
                            window._client_update_future.result(timeout=5)
                        window._finish_client_update_task()
                        self.assertIs(window._client_update_staged, staged)
                        self.assertTrue(window.ui.update_apply_button.isEnabled())
                        self.assertEqual(window.ui.update_apply_button.text(), '重试安装')
                        window.ui.update_apply_button.click()
                        window._client_update_future.result(timeout=5)
                        window._finish_client_update_task()
                        self.assertEqual(prepare.call_count, 2)
                        self.assertIs(window._handoff, handoff)
                        self.assertFalse(window.ui.update_check_button.isEnabled())
                        with patch.object(window, '_quit_development_app') as quit_app:
                            window._poll_update_handoff()
                            quit_app.assert_not_called()
                            job.with_suffix('.ready.json').write_text('{"ready":true}', 'utf8')
                            window._poll_update_handoff()
                            quit_app.assert_called_once()
                    self.assertEqual(requests.count(base + github_client.ZIP_NAME), 1)
            TrayTests.run_window(self, False, exercise)


if __name__ == '__main__':
    unittest.main()
