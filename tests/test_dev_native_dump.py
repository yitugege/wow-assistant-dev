"""原dump-ui在实际Qt事件循环中写报告后保持窗口；仅替身后端。"""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'desktop'))
from PySide6.QtCore import QEventLoop,QTimer
from PySide6.QtWidgets import QApplication
from wowbuddy.dev_dump_ui import NativeDumpSession
from wowbuddy.cli_dump_ui import DumpUiOptions
import test_dev_tray


class NativeDumpTests(unittest.TestCase):
    def test_report_written_without_exiting_and_spec_applied(self):
        def exercise(window):
            with TemporaryDirectory() as directory,patch.object(QApplication,'exit') as exit_app,patch.object(QApplication,'quit') as quit_app:
                output=Path(directory)
                session=NativeDumpSession(window,DumpUiOptions(specs=('1482','1484')),output)
                loop=QEventLoop();deadline=QTimer();deadline.setSingleShot(True)
                deadline.timeout.connect(loop.quit);deadline.start(3800)
                try:
                    self.assertEqual(session.delay.interval(),2600)
                    self.assertFalse((output/'_ui.txt').exists())
                    loop.exec()
                    self.assertTrue(session.runner.report_written)
                    self.assertEqual(session.runner.timer.interval(),600)
                    self.assertIn('spec=1484',(output/'_ui.txt').read_text('utf8'))
                    self.assertTrue(window.isVisible())
                    self.assertFalse(window._closed)
                    exit_app.assert_not_called();quit_app.assert_not_called()
                finally:session.close();deadline.stop()
        test_dev_tray.TrayTests.run_window(self,False,exercise)

    def test_close_stops_outer_and_inner_delays(self):
        def exercise(window):
            with TemporaryDirectory() as directory:
                session=NativeDumpSession(window,DumpUiOptions(),Path(directory))
                window._native_dump_session=session
                session.delay.stop();session.delay.timeout.emit()
                self.assertTrue(session.runner.timer.isActive())
                window.shutdown()
                self.assertFalse(session.delay.isActive())
                self.assertFalse(session.runner.timer.isActive())
                self.assertFalse((Path(directory)/'_ui.txt').exists())
        test_dev_tray.TrayTests.run_window(self,False,exercise)


if __name__=='__main__':unittest.main()
