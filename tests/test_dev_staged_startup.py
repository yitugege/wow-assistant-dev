"""分阶段启动适配：真实资源、Qt窗口及取消后的生命周期。"""
import os
os.environ['QT_QPA_PLATFORM']='offscreen'
import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'desktop'))
from PySide6.QtWidgets import QApplication, QWidget
from PySide6.QtCore import QCoreApplication, QEvent
from wowbuddy.engine.assets import Assets
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
            self.assertEqual(len(received),1)
            self.assertEqual(received[0].directory,ROOT/'assets')
            loaded=received[0].pipeline()
            bundled=Assets.load(ROOT/'assets').pipeline()
            self.assertEqual(loaded.builtin_thresholds,bundled.builtin_thresholds)
            self.assertEqual(loaded.readable_keys,bundled.readable_keys)
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

    def test_optional_readable_resources_do_not_block_old_protocol(self):
        import itertools
        sys.path.insert(0,str(ROOT/'tests/core'))
        from test_old_protocol import render_old
        from test_pipeline import render_readable
        # 原05e240丢弃两个可选加载器结果；真实资源解析后仍应使用旧协议。
        for contract_state,rules_state in itertools.product(
                ('missing','invalid','valid','mismatched'), ('missing','invalid','valid')):
            with self.subTest(contract=contract_state,rules=rules_state), TemporaryDirectory() as directory:
                root=Path(directory)
                for name in ('contract.json','rules.json'):
                    (root/name).write_bytes((ROOT/'assets'/name).read_bytes())
                for name,state in (('contract_readable.json',contract_state),('rules_readable.json',rules_state)):
                    if state=='mismatched':
                        raw=json.loads((ROOT/'assets'/name).read_bytes())
                        raw['specs']['9999']={'classicKeys':['orphan'],'classicRows':[]}
                        (root/name).write_text(json.dumps(raw), 'utf8')
                    elif state!='missing':
                        (root/name).write_bytes((ROOT/'assets'/name).read_bytes() if state=='valid' else b'{broken')
                backend=Windows();backend.handle=123
                received=[]
                def construct(assets):
                    received.append(assets)
                    return QWidget()
                startup=create_staged_startup(self.app,root,backend,construct,lambda _:None,auto_start=True)
                try:
                    startup.start();startup.timer.stop()
                    for _ in range(8):startup.stages.tick()
                    self.assertEqual(startup.stages.phase,'shown')
                    self.assertEqual(len(received),1)
                    self.assertEqual([timer.interval() for timer in startup.delays],[600])
                    pipeline=received[0].pipeline()
                    if contract_state=='mismatched':
                        self.assertIn('1482',pipeline.readable.specs)
                        self.assertNotIn('9999',pipeline.readable.specs)
                        readable=pipeline.prepare(render_readable(1482)).frame
                        self.assertTrue(readable.ok,readable.status)
                        self.assertEqual((readable.protocol,readable.spec_id),('readable','1482'))
                    frame=pipeline.prepare(render_old(1482,{})[0]).frame
                    self.assertTrue(frame.ok,frame.status)
                    self.assertEqual((frame.protocol,frame.spec_id),('old','1482'))
                finally:
                    startup.close()
                    if startup.stages.main_window:startup.stages.main_window.close()

    def test_normal_startup_decodes_normalized_field_descriptors(self):
        sys.path.insert(0,str(ROOT/'tests/core'))
        from test_old_protocol import render_old
        with TemporaryDirectory() as directory:
            root=Path(directory)
            raw=json.loads((ROOT/'assets/contract.json').read_bytes())
            mage=raw['specs']['1482']
            mage['fields'][0]=None
            mage['fields'][1]['label']=''
            presence=mage['presenceFields'][0]
            presence['type']='number'
            (root/'contract.json').write_text(json.dumps(raw),'utf8')
            (root/'rules.json').write_bytes((ROOT/'assets/rules.json').read_bytes())
            received=[]

            def construct(assets):
                received.append(assets.pipeline())
                return QWidget()

            backend=Windows();backend.handle=123
            startup=create_staged_startup(self.app,root,backend,construct,lambda _:None)
            try:
                startup.start();startup.timer.stop()
                for _ in range(8):startup.stages.tick()
                self.assertEqual(startup.stages.phase,'shown')
                image,colors=render_old(1482,{presence['id']:0x00ff00})
                frame=received[0].prepare(image).frame
                self.assertTrue(frame.ok,frame.status)
                self.assertEqual(frame.raw_colors,tuple(colors))
                start=len(raw['commonFields'])
                self.assertEqual((frame.rows[start].key,frame.rows[start].type),('','number'))
                self.assertEqual(frame.rows[start+1].label,mage['fields'][1]['id'])
                self.assertEqual(frame.rows[start+len(mage['fields'])].type,'presence')
                self.assertEqual(frame.values[presence['id']],'ON')
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
        with TemporaryDirectory() as directory, patch('wowbuddy.dev_staged_startup.create_staged_startup',side_effect=create), patch('wowbuddy.win32.game_windows.CtypesWindowBackend',return_value=Windows()), patch('wowbuddy.win32.capture.make_win32_capture',return_value=NoSystemBackend()), patch('wowbuddy.win32.windows_keys.CtypesWin32Backend',return_value=NoSystemBackend()), patch('PySide6.QtWidgets.QSystemTrayIcon.isSystemTrayAvailable',return_value=False), patch.object(QApplication,'exec',side_effect=event_loop):
            self.assertEqual(run_dev.launch(directory,staged=True,hub_online=False,client_online=False,addon_online=False,
                                           native_dump=(DumpUiOptions(),Path(directory))),0)
            window=hosts[0].stages.main_window
            self.assertTrue(window._closed)
            self.assertFalse(window.poll_timer.isActive())
            self.assertFalse(window.watch_timer.isActive())
            self.assertFalse(window._native_dump_session.delay.isActive())


if __name__=='__main__':unittest.main()
