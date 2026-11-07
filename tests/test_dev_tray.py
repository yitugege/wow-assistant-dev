"""独立入口的托盘菜单和关闭行为；使用真实Qt窗口及托盘替身。"""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'desktop'))
from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtWidgets import QApplication
from wowbuddy.desktop import NoSystemBackend
from test_dev_watch import Windows
import run_dev

class Tray(QObject):
    activated=Signal(int)
    def __init__(self,icon,parent):
        super().__init__(parent)
        self.visible=False
        self.notices=[]
    def setToolTip(self,text):self.tooltip=text
    def setContextMenu(self,menu):self.menu=menu
    def show(self):self.visible=True
    def hide(self):self.visible=False
    def showMessage(self,*args):self.notices.append(args)

class TrayTests(unittest.TestCase):
    def test_project_link_and_version_use_independent_identity(self):
        from wowbuddy.dev_version import VERSION
        from wowbuddy.github_addon import REPOSITORY
        def exercise(window):
            expected='https://github.com/'+REPOSITORY
            self.assertEqual(window.ui.title_label.text(),'WowBuddyDev')
            self.assertIn(VERSION,window.ui.update_status.text())
            self.assertEqual(window.ui.website_button.text(),'GitHub 项目')
            self.assertIn(expected,window.ui.website_button.toolTip())
            with patch('PySide6.QtGui.QDesktopServices.openUrl',return_value=True) as open_url:
                window.ui.website_button.click()
                open_url.assert_called_once()
                self.assertEqual(open_url.call_args.args[0].toString(),expected)
            self.assertIn(expected,window.ui.log_view.toPlainText())
            self.assertNotIn('wowbuddy.cn',window.ui.log_view.toPlainText())
        self.run_window(False,exercise)

    def test_browse_and_install_button_use_own_package(self):
        import json
        from tools.build_addon import build
        def exercise(window):
            with TemporaryDirectory() as temporary:
                root=Path(temporary)
                client=root/'client';client.mkdir()
                (client/'Wow.exe').write_bytes(b'fixture')
                source=root/'source';source.mkdir()
                (source/'WowBuddyDev.toc').write_text('Core.lua\n','utf8')
                (source/'Core.lua').write_text('-- GUI test','utf8')
                package=root/'WowBuddyDev-dev.zip'
                manifest=build(source,package)
                package.with_suffix('.manifest.json').write_text(json.dumps(manifest),'utf8')
                with patch('PySide6.QtWidgets.QFileDialog.getExistingDirectory',return_value=str(client)),patch.object(run_dev,'PACKAGE_DIR',root):
                    window.ui.addon_browse_button.click()
                    self.assertEqual(Path(window.ui.addon_path.text()),client)
                    self.assertEqual(Path(window.settings.snapshot().addon_last_dir),client)
                    window.toggle_monitor()
                    window.ui.addon_install_button.click()
                    self.assertFalse((client/'Interface').exists())
                    self.assertIn('停止监控',window.ui.addon_status.text())
                    window.toggle_monitor()
                    window.ui.addon_install_button.click()
                    self.assertIn('已安装2个文件',window.ui.addon_status.text())
                    self.assertEqual((client/'Interface/AddOns/WowBuddyDev/Core.lua').read_text('utf8'),'-- GUI test')
        self.run_window(False,exercise)

    def run_window(self,available,exercise,*,hub_online=False):
        app=QApplication.instance() or QApplication([])
        backend=Windows();backend.handle=123
        seen=[]
        def event_loop():
            window=next(w for w in app.topLevelWidgets()
                        if w.windowTitle().startswith('WowBuddyDev') and not w._closed)
            seen.append(window)
            exercise(window)
            return 0
        with TemporaryDirectory() as directory, patch('wowbuddy.game_windows.CtypesWindowBackend',return_value=backend), patch('wowbuddy.capture.make_win32_capture',return_value=NoSystemBackend()), patch('wowbuddy.windows_keys.CtypesWin32Backend',return_value=NoSystemBackend()), patch('PySide6.QtWidgets.QSystemTrayIcon.isSystemTrayAvailable',return_value=available), patch('wowbuddy.qt_app.QSystemTrayIcon',Tray), patch.object(QApplication,'exec',side_effect=event_loop):
            try:
                self.assertEqual(run_dev.launch(directory,hub_online=hub_online,client_online=False,addon_online=False),0)
                self.assertTrue(seen[0]._closed)
                self.assertFalse(seen[0].poll_timer.isActive())
                self.assertFalse(seen[0].watch_timer.isActive())
            finally:
                for window in seen:window.close()

    def test_menu_minimize_restore_monitor_pin_and_exit(self):
        def exercise(window):
            tray=window.tray
            self.assertTrue(tray.visible)
            self.assertEqual(tray.tooltip,'WowBuddyDev（运行中）')
            actions={a.text():a for a in tray.menu.actions() if not a.isSeparator()}
            self.assertEqual(set(actions),{'显示主界面','停止/开始监控','退出','切换置顶'})
            actions['停止/开始监控'].trigger()
            self.assertTrue(window.session.is_active())
            window.ui.minimize_button.click()
            self.assertFalse(window.isVisible())
            self.assertTrue(window.session.is_active())
            actions['显示主界面'].trigger()
            self.assertTrue(window.isVisible())
            tray.activated.emit(3)
            self.assertFalse(window.isVisible())
            tray.activated.emit(3)
            self.assertTrue(window.isVisible())
            before=bool(window.windowFlags() & Qt.WindowStaysOnTopHint)
            actions['切换置顶'].trigger()
            self.assertNotEqual(before,bool(window.windowFlags() & Qt.WindowStaysOnTopHint))
            actions['停止/开始监控'].trigger()
            self.assertFalse(window.session.is_active())
            actions['停止/开始监控'].trigger()
            with patch.object(QApplication,'quit') as quit_app:
                actions['退出'].trigger()
                quit_app.assert_called_once_with()
            self.assertTrue(window._closed)
            self.assertFalse(window.poll_timer.isActive())
            self.assertFalse(tray.visible)
        self.run_window(True,exercise)

    def test_without_tray_minimizes_normally_and_close_stops(self):
        def exercise(window):
            self.assertIsNone(window.tray)
            window.toggle_monitor()
            window.ui.minimize_button.click()
            self.assertTrue(window.isVisible())
            self.assertTrue(window.isMinimized())
            self.assertTrue(window.session.is_active())
            window.showNormal()
            window.ui.close_button.click()
            self.assertTrue(window._closed)
            self.assertFalse(window.poll_timer.isActive())
        self.run_window(False,exercise)
