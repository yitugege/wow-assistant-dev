"""分阶段启动适配：真实资源、Qt窗口及取消后的生命周期。"""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'desktop'))
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtCore import QCoreApplication, QEvent
from wowbuddy.assets import Assets
from wowbuddy.desktop import NoSystemBackend
from wowbuddy.dev_staged_startup import create_staged_startup
from wowbuddy.cli_dump_ui import DumpUiOptions
from test_dev_watch import Windows
import run_dev


class StagedStartupTests(unittest.TestCase):
    def setUp(self):
        self.app=QApplication.instance() or QApplication([])

    def tearDown(self):
        # 模拟的exec不消费DeferredDelete，显式完成本轮窗口销毁。
        QCoreApplication.sendPostedEvents(None,QEvent.DeferredDelete)

    def test_direct_launch_initializes_shared_qt_style_once(self):
        previous=getattr(self.app,'_wowbuddy_bootstrap_ready',False)
        self.app._wowbuddy_bootstrap_ready=False
        original=QApplication.setStyleSheet
        calls=[]
        def apply(app,style):
            calls.append(style)
            return original(app,style)
        try:
            with patch.object(QApplication,'setStyleSheet',apply):
                for _ in range(2):
                    with TemporaryDirectory() as directory:
                        result=run_dev.launch(directory,selftest=True,hub_online=False,
                                              client_online=False,addon_online=False)
                    self.assertTrue(result['passed'])
                    self.assertTrue(result['window_closed'])
                self.assertEqual(len(calls),1)
                self.assertTrue(self.app._wowbuddy_bootstrap_ready)
        finally:
            self.app._wowbuddy_bootstrap_ready=previous

    def test_success_uses_loaded_documents_and_schedules_auto(self):
        backend=Windows();backend.handle=123
        received=[];records=[]
        def construct(assets):
            received.append(assets)
            return QWidget()
        startup=create_staged_startup(self.app,ROOT/'assets',backend,construct,records.append,auto_start=True)
        try:
            startup.start();startup.timer.stop()
            for _ in range(8):startup.stages.tick()
            self.assertEqual(startup.stages.phase,'shown')
            self.assertEqual(received,[Assets.load(ROOT/'assets')])
            self.assertTrue(startup.stages.main_window.isVisible())
            self.assertEqual([timer.interval() for timer in startup.delays],[600])
        finally:
            startup.close()
            if startup.stages.main_window:startup.stages.main_window.close()

    def test_missing_resources_warn_then_construct_defaults(self):
        received=[]
        with TemporaryDirectory() as directory:
            def construct(assets):
                received.append(assets)
                assets.pipeline()
                return QWidget()
            startup=create_staged_startup(self.app,directory,Windows(),construct,lambda _:None,auto_start=True)
            try:
                startup.start();startup.timer.stop()
                for _ in range(3):startup.stages.tick()
                self.assertEqual(startup.stages.phase,'warning_delay')
                self.assertFalse(received)
                self.assertEqual(startup.delays[0].interval(),1500)
                startup.delays[0].timeout.emit()
                self.assertEqual(startup.stages.phase,'shown')
                self.assertEqual(len(received),1)
                self.assertEqual(len(startup.delays),1)
            finally:
                startup.close()
                if startup.stages.main_window:startup.stages.main_window.close()

    def test_cancel_stops_pending_warning_without_main(self):
        startup=create_staged_startup(self.app,ROOT/'assets',Windows(),lambda _:self.fail('取消后创建主窗口'),lambda _:None)
        try:
            startup.start();startup.timer.stop()
            for _ in range(5):startup.stages.tick()
            self.assertEqual(startup.stages.phase,'warning_delay')
            # 拦截quit，避免影响后续Qt测试。
            with patch.object(QApplication,'quit'):
                startup.splash.cancelled.emit()
            startup.delays[0].timeout.emit()
            self.assertEqual(startup.stages.phase,'cancelled')
            self.assertFalse(startup.timer.isActive())
            self.assertFalse(any(timer.isActive() for timer in startup.delays))
        finally:
            startup.close();startup.splash.close();startup.splash.deleteLater();self.app.processEvents()

    def test_independent_entry_constructs_real_window_then_shuts_down(self):
        hosts=[]
        def create(*args,**kwargs):
            host=create_staged_startup(*args,**kwargs);hosts.append(host);return host
        def event_loop():
            host=hosts[0];host.timer.stop()
            for _ in range(5):host.stages.tick()
            self.assertEqual(host.stages.phase,'warning_delay')
            host.delays[0].timeout.emit()
            self.assertTrue(host.stages.main_window.isVisible())
            self.assertFalse(host.stages.main_window.session.is_active())
            self.assertTrue(host.stages.main_window._native_dump_session.delay.isActive())
            self.assertEqual(host.stages.main_window._native_dump_session.delay.interval(),2600)
            return 0
        with TemporaryDirectory() as directory, patch('wowbuddy.dev_staged_startup.create_staged_startup',side_effect=create), patch('wowbuddy.game_windows.CtypesWindowBackend',return_value=Windows()), patch('wowbuddy.capture.make_win32_capture',return_value=NoSystemBackend()), patch('wowbuddy.windows_keys.CtypesWin32Backend',return_value=NoSystemBackend()), patch('PySide6.QtWidgets.QSystemTrayIcon.isSystemTrayAvailable',return_value=False), patch.object(QApplication,'exec',side_effect=event_loop):
            self.assertEqual(run_dev.launch(directory,staged=True,hub_online=False,client_online=False,addon_online=False,
                                           native_dump=(DumpUiOptions(),Path(directory))),0)
            window=hosts[0].stages.main_window
            self.assertTrue(window._closed)
            self.assertFalse(window.poll_timer.isActive())
            self.assertFalse(window.watch_timer.isActive())
            self.assertFalse(window._native_dump_session.delay.isActive())


if __name__=='__main__':unittest.main()
