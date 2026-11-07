import sys,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'desktop'))
import run_dev

class AutoUpdateTests(unittest.TestCase):
    def window(self,exercise):
        from test_dev_tray import TrayTests
        TrayTests.run_window(self,False,exercise)

    def test_startup_strict_six_hour_delay_and_suppression(self):
        def exercise(window):
            window.settings.save_auto_check(True);window.settings.save_last_check_ms(100)
            window.clock_ms=lambda:21600100
            window._configure_automatic_client_update(True,False)
            self.assertFalse(window.update_timer.isActive())
            window.clock_ms=lambda:21600101
            window._configure_automatic_client_update(True,False)
            self.assertTrue(window.update_timer.isActive());self.assertEqual(window.update_timer.interval(),4000)
            window._configure_automatic_client_update(True,True)
            self.assertFalse(window.update_timer.isActive());self.assertTrue(window.ui.auto_update_check.isChecked())
            window.ui.auto_update_check.setChecked(False)
            window._configure_automatic_client_update(True,False)
            self.assertFalse(window.update_timer.isActive());self.assertFalse(window.settings.snapshot().update_auto_check)
        self.window(exercise)

    def test_manual_and_failed_checks_do_not_auto_download(self):
        def exercise(window):
            window.clock_ms=lambda:900
            window.settings.save_last_check_ms(100)
            with patch('wowbuddy.github_client.check_latest',side_effect=OSError('offline')):
                window.check_update();
                with self.assertRaises(OSError):window._client_update_future.result(timeout=5)
                window._finish_client_update_task()
            self.assertEqual(window.settings.snapshot().update_last_check_ms,100)
            info={'current_version':'0.2.1','version':'0.3.0','has_update':True}
            with patch('wowbuddy.github_client.check_latest',return_value=info),patch.object(run_dev,'FROZEN',True):
                window.check_update(manual=True);window._client_update_future.result(timeout=5);window._finish_client_update_task()
            self.assertEqual(window.settings.snapshot().update_last_check_ms,900)
            self.assertFalse(window._client_auto_chain)
        self.window(exercise)

    def test_background_check_download_then_handoff_chain(self):
        from PySide6.QtCore import QTimer
        def exercise(window):
            window._automatic_client_enabled=True;window.ui.auto_update_check.setChecked(True)
            info={'current_version':'0.2.1','version':'0.3.0','has_update':True};queued=[]
            with patch('wowbuddy.github_client.check_latest',return_value=info),patch.object(run_dev,'FROZEN',True),patch.object(QTimer,'singleShot',side_effect=lambda delay,callback:queued.append(callback)),patch.object(window,'download_update') as download,patch.object(window,'_begin_update_handoff') as handoff:
                window.check_update(manual=False);window._client_update_future.result(timeout=5);window._finish_client_update_task()
                self.assertTrue(window._client_auto_chain);self.assertEqual(len(queued),1)
                queued.pop()();download.assert_called_once()
                window._start_client_update_task(lambda:{'staged':'fixture'},'download','download')
                window._client_update_future.result(timeout=5);window._finish_client_update_task()
                self.assertEqual(len(queued),1);queued.pop()();handoff.assert_called_once()
        self.window(exercise)

if __name__=='__main__':unittest.main()
