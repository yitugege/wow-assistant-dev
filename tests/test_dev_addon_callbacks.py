"""插件下载完成回调的生命周期；不联网、不扫描或写入游戏目录。"""
import unittest
from concurrent.futures import Future
from unittest.mock import Mock, patch
import test_dev_tray
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from wowbuddy.addon_update import AddonUpdateState


class AddonCallbackTests(unittest.TestCase):
    def run_case(self, mode, exercise):
        def run(window):
            window._addon_online = True
            window.ui.addon_path.setText('fixture-client')
            start = window._refresh_addon_release if mode == 'auto' else window._download_github_addon
            finish = window._finish_addon_refresh if mode == 'auto' else window._finish_github_download
            future = Future()
            executor = Mock()
            executor.submit.return_value = future
            result = {'package': 'fixture.zip', 'tag': 'fixture'}
            with patch('concurrent.futures.ThreadPoolExecutor', return_value=executor) as pool, \
                 patch('wowbuddy.dev_addon_update.apply_release', return_value=AddonUpdateState(pending=())) as auto, \
                 patch('wowbuddy.dev_addon_install.install_package', return_value={
                     'target': 'fixture', 'cleanup_deleted': 0, 'cleanup_notes': ''}) as manual, \
                 patch.object(window, '_addon_game_snapshot', side_effect=AssertionError('禁止游戏扫描')):
                exercise(window, start, finish, future, result, pool, auto if mode == 'auto' else manual)
        test_dev_tray.TrayTests.run_window(self, False, run)

    def test_completed_result_consumed_once_and_next_request_works(self):
        for mode in ('auto', 'manual'):
            with self.subTest(mode=mode):
                def exercise(window, start, finish, future, result, pool, install):
                    start()
                    finish()
                    install.assert_not_called()
                    future.set_result(result)
                    finish()
                    finish()
                    self.assertEqual(install.call_count, 1)
                    start()
                    finish()
                    self.assertEqual(install.call_count, 2)
                self.run_case(mode, exercise)

    def test_queued_completion_after_shutdown_cannot_install_or_restart(self):
        for mode in ('auto', 'manual'):
            with self.subTest(mode=mode):
                def exercise(window, start, finish, future, result, pool, install):
                    start()
                    future.set_result(result)
                    QTimer.singleShot(0, finish)
                    window.shutdown()
                    QApplication.processEvents()
                    install.assert_not_called()
                    start()
                    self.assertEqual(pool.call_count, 1)
                self.run_case(mode, exercise)

    def test_manual_and_automatic_requests_are_mutually_exclusive(self):
        for mode in ('auto', 'manual'):
            with self.subTest(mode=mode):
                def exercise(window, start, finish, future, result, pool, install):
                    start()
                    window._refresh_addon_release()
                    window._download_github_addon()
                    self.assertEqual(pool.call_count, 1)
                    future.set_result(result)
                    finish()
                    install.assert_called_once()
                self.run_case(mode, exercise)


if __name__ == '__main__':
    unittest.main()
