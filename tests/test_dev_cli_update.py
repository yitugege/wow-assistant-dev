import json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'desktop'))
from wowbuddy.dev_cli_update import run_update_now
from wowbuddy.dev_update_handoff import wait_until_ready

class UpdateCliTests(unittest.TestCase):
    def test_no_update_never_downloads_or_prepares(self):
        with tempfile.TemporaryDirectory() as tmp:
            def forbidden(*args,**kwargs):raise AssertionError('must not execute')
            code=run_update_now(tmp,tmp,[],frozen=False,
                check=lambda:{'version':'0.2.0','current_version':'0.2.1','has_update':False},download=forbidden,prepare=forbidden)
            self.assertEqual(code,0)
            report=json.loads((Path(tmp)/'update-now.json').read_text('utf8'))
            self.assertFalse(report['installed']);self.assertFalse(report['handoff_ready'])

    def test_ready_report_is_not_install_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            job=Path(tmp)/'job.json';job.write_text('{}')
            calls=[]
            def prepare(stage,current,args,**kwargs):calls.append(('prepare',stage,args,kwargs));return {'job':str(job)}
            code=run_update_now(tmp,tmp,['--update-now'],frozen=True,
                check=lambda:{'version':'0.3.0','current_version':'0.2.1','has_update':True},
                download=lambda *args:{'staged':'fixture'},prepare=prepare,wait_ready=lambda h:calls.append(('ready',)))
            self.assertEqual(code,0);self.assertEqual(calls[0][0],'prepare');self.assertEqual(calls[-1],('ready',))
            report=json.loads((Path(tmp)/'update-now.json').read_text('utf8'))
            self.assertTrue(report['handoff_ready']);self.assertFalse(report['installed'])

    def test_timeout_cancels_before_parent_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            job=Path(tmp)/'job.json';job.write_text('{}')
            class Process:
                def poll(self):return None
            handoff={'job':str(job),'process':Process()}
            code=run_update_now(tmp,tmp,[],frozen=True,
                check=lambda:{'version':'0.3.0','current_version':'0.2.1','has_update':True},
                download=lambda *args:{'staged':'fixture'},prepare=lambda *args,**kwargs:handoff,
                wait_ready=lambda h:wait_until_ready(h,timeout=0))
            self.assertEqual(code,1);self.assertTrue(job.with_suffix('.cancel.json').exists())

    def test_source_mode_does_not_download_new_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            def forbidden(*args):raise AssertionError('must not download')
            self.assertEqual(run_update_now(tmp,tmp,[],frozen=False,
                check=lambda:{'version':'0.3.0','current_version':'0.2.1','has_update':True},download=forbidden),1)

if __name__=='__main__':unittest.main()
