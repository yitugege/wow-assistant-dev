import json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'desktop'))
from tools.build_client_release import build_client
from wowbuddy.dev_client_update import digest,stage_update
from wowbuddy.dev_update_handoff import run_handoff,write_json

class HandoffTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.current=self.root/'client';self.current.mkdir()
        (self.current/'WowBuddyDev.exe').write_bytes(b'MZ old')
        source=self.root/'source';(source/'_internal').mkdir(parents=True)
        (source/'WowBuddyDev.exe').write_bytes(b'MZ new');(source/'_internal/runtime.dll').write_bytes(b'new')
        package=self.root/'client.zip';build_client(source,package,'0.2.1')
        self.stage=stage_update(package,package.with_suffix('.manifest.json'),self.root/'updates')
        self.job=self.root/'job.json'
        write_json(self.job,{'format':1,'product':'wowbuddy-update-job','current':str(self.current),'staged':str(self.stage),
                   'parent_pid':123,'original_sha256':digest(self.current/'WowBuddyDev.exe'),
                   'manifest_sha256':digest(self.stage.parent/'manifest.json'),'arguments':['--data-dir','D:/user data']})

    def test_wait_then_swap_then_launch(self):
        calls=[]
        def wait(pid,exe,ready):
            self.assertEqual((self.current/'WowBuddyDev.exe').read_bytes(),b'MZ old')
            self.assertEqual(pid,123);ready();calls.append('exited')
        def launch(exe,args):
            self.assertEqual(calls,['exited'])
            self.assertEqual(Path(exe).read_bytes(),b'MZ new')
            self.assertEqual(args,['--data-dir','D:/user data']);return 456
        self.assertEqual(run_handoff(self.job,wait=wait,launch=launch),0)
        report=json.loads(self.job.with_suffix('.result.json').read_text('utf8'))
        self.assertTrue(report['replaced'] and report['restarted']);self.assertEqual(report['restart_pid'],456)

    def test_timeout_does_not_replace_or_launch(self):
        def wait(*args):raise TimeoutError('still running')
        def launch(*args):raise AssertionError('must not launch')
        self.assertEqual(run_handoff(self.job,wait=wait,launch=launch),1)
        self.assertEqual((self.current/'WowBuddyDev.exe').read_bytes(),b'MZ old')

    def test_restart_failure_reports_replacement_separately(self):
        def launch(*args):raise OSError('launch failed')
        self.assertEqual(run_handoff(self.job,wait=lambda pid,exe,ready:ready(),launch=launch),1)
        report=json.loads(self.job.with_suffix('.result.json').read_text('utf8'))
        self.assertTrue(report['replaced']);self.assertFalse(report['restarted'])
        self.assertTrue((Path(report['backup'])/'WowBuddyDev.exe').exists())

    def test_gui_waits_for_ready_before_quitting(self):
        from test_dev_tray import TrayTests
        from unittest.mock import patch
        from PySide6.QtCore import QTimer
        import time
        class Process:
            def poll(self):return None
        def exercise(window):
            window._handoff={'job':str(self.job),'process':Process()}
            window._handoff_deadline=time.monotonic()+30
            window._handoff_timer=QTimer(window)
            with patch.object(window,'_quit_development_app') as quit_app:
                window._poll_update_handoff();quit_app.assert_not_called()
                write_json(self.job.with_suffix('.ready.json'),{'ready':True})
                window._poll_update_handoff();quit_app.assert_called_once()
        TrayTests.run_window(self,False,exercise)

    def test_prepare_failure_keeps_check_button_usable(self):
        from test_dev_tray import TrayTests
        def exercise(window):
            def fail():raise OSError('cannot copy runtime')
            window._start_client_update_task(fail,'preparing','handoff')
            with self.assertRaises(OSError):window._client_update_future.result(timeout=5)
            window._finish_client_update_task()
            self.assertTrue(window.ui.update_check_button.isEnabled())
            self.assertIn('cannot copy runtime',window.ui.update_status.text())
        TrayTests.run_window(self,False,exercise)

if __name__=='__main__':unittest.main()
