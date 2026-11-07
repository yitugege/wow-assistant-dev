import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'desktop'))
from wowbuddy.dev_update_notice import remember_handoff,poll_notice,PENDING
from wowbuddy.dev_update_handoff import write_json

class NoticeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.current=self.root/'client';self.data=self.root/'data';self.data.mkdir()
        self.job=self.root/'job.json'
        write_json(self.job,{'product':'wowbuddy-update-job','current':str(self.current)})
        remember_handoff(self.data,self.current,{'job':str(self.job)})

    def test_pending_then_failed_result_consumed_once(self):
        self.assertFalse(poll_notice(self.data,self.current)['complete'])
        write_json(self.job.with_suffix('.result.json'),{'ok':False,'replaced':True,'restarted':False,'error':'restart denied','backup':'old-copy'})
        result=poll_notice(self.data,self.current)
        self.assertIn('已换入',result['text']);self.assertIn('restart denied',result['text']);self.assertIn('old-copy',result['text'])
        self.assertIsNone(poll_notice(self.data,self.current))
        self.assertTrue((self.data/'client-update-last-result.json').exists())

    def test_wrong_client_and_inconsistent_success_not_accepted(self):
        self.assertIn('不属于',poll_notice(self.data,self.root/'other')['text'])
        write_json(self.job.with_suffix('.result.json'),{'ok':True,'replaced':False})
        self.assertIn('未确认',poll_notice(self.data,self.current)['text'])
        self.assertTrue((self.data/PENDING).exists())

    def test_record_failure_cancels_handoff(self):
        with patch('wowbuddy.dev_update_notice.write_json',side_effect=OSError('read only')),patch('wowbuddy.dev_update_notice.cancel_handoff') as cancel:
            with self.assertRaises(OSError):remember_handoff(self.data,self.current,{'job':str(self.job)})
            cancel.assert_called_once()

    def test_gui_waits_for_report_and_stops_after_completion(self):
        from test_dev_tray import TrayTests
        def exercise(window):
            with patch('wowbuddy.dev_update_notice.poll_notice',side_effect=[{'complete':False,'text':'waiting'},{'complete':True,'text':'failed: locked'}]):
                window._restore_update_notice()
                self.assertTrue(window._update_notice_timer.isActive())
                window._restore_update_notice()
                self.assertFalse(window._update_notice_timer.isActive())
                self.assertEqual(window.ui.update_status.text(),'failed: locked')
        TrayTests.run_window(self,False,exercise)

    def test_actual_handoff_report_is_read_after_exchange(self):
        from test_dev_update_handoff import HandoffTests
        from wowbuddy.dev_update_handoff import run_handoff
        fixture=HandoffTests();fixture.setUp()
        try:
            data=fixture.current/'.local';data.mkdir()
            remember_handoff(data,fixture.current,{'job':str(fixture.job)})
            self.assertEqual(run_handoff(fixture.job,wait=lambda p,e,r:r(),launch=lambda e,a:456),0)
            result=poll_notice(data,fixture.current)
            self.assertIn('已完成目录替换',result['text'])
            self.assertIn('已发起新版重启',result['text'])
            self.assertTrue(result['result']['replaced'])
        finally:fixture.doCleanups()

if __name__=='__main__':unittest.main()
