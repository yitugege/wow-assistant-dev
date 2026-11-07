"""真实Qt计时器和会话生命周期，窗口发现替身，不抓屏或发键。"""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'desktop'))
from PySide6.QtWidgets import QApplication
from wowbuddy.desktop import NoSystemBackend
from wowbuddy.game_windows import TitleResult
import run_dev

class Windows(NoSystemBackend):
    handle=0
    def enum_windows(self,visitor):
        if self.handle:visitor(self.handle)
    def is_window(self,hwnd):return hwnd == self.handle
    def is_visible(self,hwnd):return True
    def window_pid(self,hwnd):return 123
    def window_title(self,hwnd):return TitleResult(True,'测试游戏')
    def process_path(self,pid):return 'C:/Game/Wow.exe'

class WatchTests(unittest.TestCase):
    def test_appear_close_reappear_and_shutdown(self):
        app=QApplication.instance() or QApplication([])
        backend=Windows()
        seen=[]
        def event_loop():
            window=next(w for w in app.topLevelWidgets() if w.windowTitle().startswith('WowBuddyDev') and not w._closed)
            seen.append(window)
            self.assertTrue(window.watch_timer.isActive())
            self.assertEqual(window.watch_timer.interval(),5000)
            self.assertFalse(window.session.is_active())
            backend.handle=123
            window.watch_timer.timeout.emit()
            self.assertTrue(window.session.is_active())
            self.assertEqual(window.monitor.target_hwnd,123)
            backend.handle=456
            window.watch_timer.timeout.emit()
            self.assertFalse(window.session.is_active())
            window.watch_timer.timeout.emit()
            self.assertTrue(window.session.is_active())
            self.assertEqual(window.monitor.target_hwnd,456)
            return 0
        with TemporaryDirectory() as directory, patch('wowbuddy.game_windows.CtypesWindowBackend',return_value=backend), patch('wowbuddy.capture.make_win32_capture',return_value=NoSystemBackend()), patch('wowbuddy.windows_keys.CtypesWin32Backend',return_value=NoSystemBackend()), patch.object(QApplication,'exec',side_effect=event_loop):
            try:
                self.assertEqual(run_dev.launch(directory,watch=True,hub_online=False),0)
                self.assertFalse(seen[0].watch_timer.isActive())
                self.assertFalse(seen[0].poll_timer.isActive())
                self.assertTrue(seen[0]._closed)
            finally:
                for window in seen:window.close()
