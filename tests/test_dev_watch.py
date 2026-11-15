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
from wowbuddy.win32.game_windows import TitleResult
import run_dev

class Windows(NoSystemBackend):
    handle=0
    def enum_windows(self,visitor):
        if self.handle:visitor(self.handle)
    def is_window(self,hwnd):return hwnd == self.handle
    def is_visible(self,hwnd):return True
    def window_pid(self,hwnd):return 123
    def window_title(self,hwnd):return TitleResult(True,'测试游戏')
    def process_path(self,pid):return r'C:\Game\Wow.exe'

class WatchTests(unittest.TestCase):
    def test_dev_monitor_waits_for_real_game_and_rejects_recycled_handle(self):
        class MultipleWindows(Windows):
            items = {
                10: (10, '战网', r'C:\Battle.net\Battle.net.exe'),
                11: (11, '桌面浮层', r'C:\Tools\Overlay.exe'),
                12: (12, '同名窗口', r'C:\Tools\MyWowTool.exe'),
            }

            def enum_windows(self, visitor):
                for hwnd in self.items:
                    visitor(hwnd)

            def is_window(self, hwnd):
                return hwnd in self.items

            def window_pid(self, hwnd):
                return self.items.get(hwnd, (0, '', ''))[0]

            def window_title(self, hwnd):
                return TitleResult(True, self.items[hwnd][1])

            def process_path(self, pid):
                return next(path for process, _, path in self.items.values() if process == pid)

        app = QApplication.instance() or QApplication([])
        backend = MultipleWindows()

        def event_loop():
            window = next(w for w in app.topLevelWidgets() if w.windowTitle().startswith('WowBuddyDev') and not w._closed)
            self.assertEqual(window.ui.window_combo.currentIndex(), -1)
            self.assertEqual(window.ui.window_combo.count(), 0)
            window.toggle_monitor()
            window.watch_once()
            self.assertFalse(window.session.is_active())
            backend.items[42] = (123, '魔兽世界', r'C:\Game\_forever_\Wow.exe')
            window.auto_start_once()
            self.assertTrue(window.session.is_active())
            self.assertEqual(window.ui.window_combo.currentData(), 42)
            backend.items[42] = (124, '窗口句柄被回收', r'C:\Tools\Overlay.exe')
            with patch.object(window.loop, 'poll') as capture:
                self.assertEqual(window.poll_once().status, 'target_lost')
                capture.assert_not_called()
            self.assertFalse(window.session.is_active())
            self.assertEqual(window.ui.window_combo.currentIndex(), -1)
            backend.items[43] = (125, '魔兽世界', r'C:\Game\_forever_\Wow.exe')
            window.watch_once()
            self.assertTrue(window.session.is_active())
            self.assertEqual(window.ui.window_combo.currentData(), 43)
            return 0

        with (TemporaryDirectory() as directory,
              patch('wowbuddy.win32.game_windows.CtypesWindowBackend', return_value=backend),
              patch('wowbuddy.win32.capture.make_win32_capture', return_value=NoSystemBackend()),
              patch('wowbuddy.win32.windows_keys.CtypesWin32Backend', return_value=NoSystemBackend()),
              patch.object(QApplication, 'exec', side_effect=event_loop)):
            self.assertEqual(run_dev.launch(directory, watch=True, hub_online=False, client_online=False,
                                            addon_online=False), 0)

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
        with TemporaryDirectory() as directory, patch('wowbuddy.win32.game_windows.CtypesWindowBackend',return_value=backend), patch('wowbuddy.win32.capture.make_win32_capture',return_value=NoSystemBackend()), patch('wowbuddy.win32.windows_keys.CtypesWin32Backend',return_value=NoSystemBackend()), patch.object(QApplication,'exec',side_effect=event_loop):
            try:
                self.assertEqual(run_dev.launch(directory,watch=True,hub_online=False,client_online=False,addon_online=False),0)
                self.assertFalse(seen[0].watch_timer.isActive())
                self.assertFalse(seen[0].poll_timer.isActive())
                self.assertTrue(seen[0]._closed)
            finally:
                for window in seen:window.close()
