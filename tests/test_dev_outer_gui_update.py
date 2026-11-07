"""真实Qt控件接线，联网和安装替身不修改真实外层。"""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'desktop'))
import run_dev
from wowbuddy.update_handoff import HandoffResult


class OuterGuiUpdateTests(unittest.TestCase):
    def run_window(self,exercise):
        from test_dev_tray import TrayTests
        with patch.object(run_dev,'FROZEN',True),patch('wowbuddy.release_identity.validated_outer_target',return_value=Path('D:/fixture/Outer.exe')):
            TrayTests().run_window(False,exercise)

    def test_verified_outer_routes_check_and_download_to_outer_assets(self):
        def exercise(window):
            self.assertEqual(window._outer_update_target,Path('D:/fixture/Outer.exe'))
            info={'kind':'outer','current_version':'0.2.4','version':'0.3.0','has_update':True}
            with patch('wowbuddy.github_outer.check_latest',return_value=info) as outer,patch('wowbuddy.github_client.check_latest') as directory:
                window.ui.update_check_button.click()
                window._client_update_future.result(timeout=5);window._finish_client_update_task()
                outer.assert_called_once();directory.assert_not_called()
            staged={'kind':'outer','staged':'D:/fixture/update.exe','installed':False}
            self.assertIn('自动替换并重启',window.ui.update_apply_button.toolTip())
            with patch('wowbuddy.github_outer.download_checked',return_value=staged) as download,patch('wowbuddy.github_client.download_checked') as directory,patch('wowbuddy.dev_outer_update.install_outer',return_value=HandoffResult('restart_started','重启已安排',restart_started=True,exit_scheduled=True)) as install:
                window.ui.update_apply_button.click()
                window._client_update_future.result(timeout=5);window._finish_client_update_task()
                self.assertEqual(download.call_args.args[1],Path('D:/fixture/WowBuddyDev-updates'))
                directory.assert_not_called()
                self.assertEqual(window._client_update_staged,staged)
                self.assertFalse(window._client_auto_chain)
                from PySide6.QtWidgets import QApplication
                QApplication.processEvents()
                install.assert_called_once()
            self.assertIsNone(window._client_update_staged)
            self.assertTrue(window._outer_installing)
        self.run_window(exercise)

    def test_manual_download_failure_does_not_install_and_can_retry(self):
        def exercise(window):
            window._client_update_info={'kind':'outer','has_update':True}
            window._client_auto_chain=False
            window.ui.update_apply_button.setEnabled(True)
            with patch('wowbuddy.github_outer.download_checked',side_effect=ValueError('校验失败')),patch('wowbuddy.dev_outer_update.install_outer') as install:
                window.ui.update_apply_button.click()
                try:window._client_update_future.result(timeout=5)
                except ValueError:pass
                window._finish_client_update_task()
                from PySide6.QtWidgets import QApplication
                QApplication.processEvents()
                install.assert_not_called()
            self.assertIn('校验失败',window.ui.update_status.text())
            self.assertEqual(window.ui.update_apply_button.text(),'重试下载')
            self.assertTrue(window.ui.update_apply_button.isEnabled())
        self.run_window(exercise)

    def test_install_is_main_thread_guarded_and_restarts_outer(self):
        def exercise(window):
            window._client_update_staged={'kind':'outer','staged':'D:/fixture/update.exe'}
            window.watch_timer.start()
            def install(*args,**kwargs):
                self.assertEqual(args,( 'D:/fixture/update.exe',Path(sys.executable),window._outer_update_target))
                self.assertFalse(window.watch_timer.isActive())
                self.assertTrue(window._outer_installing)
                # 原替换器处理Qt事件期间，同步重入必须被挡住。
                window.check_update();window.download_update();window._begin_update_handoff()
                return HandoffResult('restart_started','重启已安排',restart_started=True,exit_scheduled=True)
            with patch('wowbuddy.dev_outer_update.install_outer',side_effect=install) as execute,patch('wowbuddy.dev_update_handoff.prepare_handoff') as directory:
                window._begin_update_handoff()
                execute.assert_called_once();directory.assert_not_called()
            self.assertTrue(window._outer_installing)
            self.assertFalse(window.ui.update_check_button.isEnabled())
            self.assertIsNone(window._client_update_staged)
        self.run_window(exercise)

    def test_replace_failure_allows_retry_and_restart_failure_requests_manual_open(self):
        for phase in ('replacement_failed','restart_failed'):
            def exercise(window):
                window._client_update_staged={'kind':'outer','staged':'D:/fixture/update.exe'}
                with patch('wowbuddy.dev_outer_update.install_outer',return_value=HandoffResult(phase,'失败结果')):
                    window._begin_update_handoff()
                self.assertFalse(window._outer_installing)
                self.assertTrue(window.ui.update_check_button.isEnabled())
                if phase=='replacement_failed':
                    self.assertEqual(window.ui.update_apply_button.text(),'重试安装')
                    self.assertTrue(window.ui.update_apply_button.isEnabled())
                else:self.assertIsNone(window._client_update_staged)
            with self.subTest(phase=phase):self.run_window(exercise)

    def test_directory_payload_cannot_reach_outer_installer(self):
        def exercise(window):
            window._client_update_staged={'staged':'D:/fixture/directory'}
            with patch('wowbuddy.dev_outer_update.install_outer') as install:
                window._begin_update_handoff();install.assert_not_called()
            self.assertIn('不能安装目录版',window.ui.update_status.text())
            self.assertFalse(window._outer_installing)
        self.run_window(exercise)

    def test_queued_install_is_cancelled_when_window_shuts_down(self):
        from PySide6.QtWidgets import QApplication
        def exercise(window):
            with patch('wowbuddy.dev_outer_update.install_outer') as install:
                window._start_client_update_task(lambda:{'kind':'outer','staged':'D:/fixture/update.exe'},'下载','download')
                window._client_update_future.result(timeout=5)
                window._finish_client_update_task()
                install.assert_not_called()
                window.shutdown()
                QApplication.processEvents()
                install.assert_not_called()
        self.run_window(exercise)

    def test_completed_download_is_consumed_once_even_if_polled_again(self):
        from PySide6.QtCore import QTimer
        def exercise(window):
            queued=[]
            with patch.object(QTimer,'singleShot',side_effect=lambda delay,callback:queued.append(callback)):
                window._start_client_update_task(lambda:{'kind':'outer','staged':'D:/fixture/update.exe'},'下载','download')
                window._client_update_future.result(timeout=5)
                window._finish_client_update_task()
                window._finish_client_update_task()
                self.assertEqual(len(queued),1)
        self.run_window(exercise)


if __name__=='__main__':unittest.main()
