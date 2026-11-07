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
