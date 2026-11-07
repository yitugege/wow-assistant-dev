import io,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'desktop'))
from wowbuddy.github_addon import read_download

class Response(io.BytesIO):
    def __init__(self,data,length=None):
        super().__init__(data);self.headers={} if length is None else {'Content-Length':str(length)}

class ProgressTests(unittest.TestCase):
    def test_chunked_known_and_unknown_totals(self):
        payload=b'x'*(600*1024)
        for header,total in ((len(payload),len(payload)),(None,0),('invalid',0)):
            with self.subTest(header=header):
                calls=[]
                self.assertEqual(read_download(Response(payload,header),len(payload),lambda r,t:calls.append((r,t))),payload)
                self.assertEqual(calls[0],(0,total));self.assertEqual(calls[-1],(len(payload),total))
                self.assertGreater(len(calls),2)
                self.assertEqual([c[0] for c in calls],sorted(c[0] for c in calls))

    def test_limits_apply_with_and_without_content_length(self):
        for header in (6,None,'invalid'):
            with self.subTest(header=header),self.assertRaises(ValueError):read_download(Response(b'123456',header),5)
        self.assertEqual(read_download(Response(b'12345'),5),b'12345')

    def test_gui_progress_and_failure_recovery(self):
        from test_dev_tray import TrayTests
        from queue import SimpleQueue
        from threading import Event
        def exercise(window):
            release=Event();window._client_download_progress=SimpleQueue()
            window._client_update_info={'has_update':True}
            def operation():
                release.wait(5);raise OSError('network interrupted')
            window._start_client_update_task(operation,'download','download')
            try:
                window._client_download_progress.put((25,100));window._finish_client_update_task()
                self.assertEqual(window.ui.update_progress.value(),25)
                self.assertEqual(window.ui.update_progress.maximum(),100)
                self.assertTrue(window.ui.update_progress.isVisible())
                window._client_download_progress.put((50,0));window._finish_client_update_task()
                self.assertEqual(window.ui.update_progress.maximum(),0)
                self.assertIn('总大小未知',window.ui.update_status.text())
            finally:release.set()
            with self.assertRaises(OSError):window._client_update_future.result(timeout=5)
            window._finish_client_update_task()
            self.assertFalse(window.ui.update_progress.isVisible())
            self.assertTrue(window.ui.update_check_button.isEnabled())
            self.assertTrue(window.ui.update_apply_button.isEnabled())
            self.assertEqual(window.ui.update_apply_button.text(),'重试下载')
            self.assertFalse(window._client_auto_chain)
        TrayTests.run_window(self,False,exercise)

if __name__=='__main__':unittest.main()
