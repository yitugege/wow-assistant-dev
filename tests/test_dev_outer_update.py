"""真实PE与临时文件替换；重启替身不执行试件。"""
import hashlib
import json
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
from wowbuddy.dev_outer_update import install_outer
from wowbuddy.github_outer import EXE_NAME,MANIFEST_NAME
from wowbuddy.launcher import BUSINESS_EXE
from wowbuddy.packages import Member,write_bundle
from wowbuddy.release_identity import ReleaseIdentity,file_sha256
from wowbuddy.update_handoff import QtWin32HandoffBackend
from wowbuddy.updater import part_file_path


@unittest.skipUnless((ROOT/'dist/desktop/WowBuddyDev/WowBuddyDev.exe').is_file(),'需要自有PE资源载体')
class OuterUpdateTests(unittest.TestCase):
    def setUp(self):
        from PyInstaller.utils.win32.winresource import add_or_update_resource
        self.temporary=TemporaryDirectory();self.root=Path(self.temporary.name)
        self.inner=self.root/'cache'/BUSINESS_EXE;self.inner.parent.mkdir()
        self.inner.write_bytes(b'old business fixture')
        def artifact(path,business):
            shutil.copy2(ROOT/'dist/desktop/WowBuddyDev/WowBuddyDev.exe',path)
            payload=write_bundle([Member(BUSINESS_EXE,business)])
            identity=ReleaseIdentity(hashlib.sha256(payload).hexdigest(),hashlib.sha256(business).hexdigest())
            add_or_update_resource(str(path),payload,10,[200],[1033])
            add_or_update_resource(str(path),identity.encode(),10,[203],[1033])
            return identity
        self.target=self.root/'用户外层.exe';artifact(self.target,self.inner.read_bytes())
        self.original=file_sha256(self.target)
        stage=self.root/'stage';stage.mkdir();self.staged=stage/EXE_NAME
        identity=artifact(self.staged,b'new business fixture')
        self.manifest={'product':'wowbuddy-outer','format':1,'version':'0.3.0','artifact':EXE_NAME,
            'size':self.staged.stat().st_size,'sha256':file_sha256(self.staged),
            'payload_sha256':identity.payload_sha256,'business_sha256':identity.business_sha256}
        (stage/MANIFEST_NAME).write_text(json.dumps(self.manifest),'utf8')
        self.part=Path(part_file_path(str(self.target)))

    def tearDown(self):self.temporary.cleanup()

    def test_real_file_replace_preserves_business_cache_and_settings(self):
        setting=self.root/'settings.ini';setting.write_text('keep')
        result=install_outer(self.staged,self.inner,self.target,current_version='0.2.4',restart=False)
        self.assertEqual(result.phase,'replacement_complete')
        self.assertEqual(file_sha256(self.target),self.manifest['sha256'])
        self.assertEqual(self.inner.read_bytes(),b'old business fixture')
        self.assertEqual(setting.read_text(),'keep')
        self.assertFalse(self.part.exists());self.assertFalse(Path(str(self.target)+'.old').exists())

    def test_failed_move_rolls_back_original_outer(self):
        def factory(scope):
            return QtWin32HandoffBackend(scope,move_file_ex=lambda *args:False,
                                        sleep_ms=lambda _:None,process_events=lambda:None)
        result=install_outer(self.staged,self.inner,self.target,restart=False,backend_factory=factory)
        self.assertEqual(result.phase,'replacement_failed');self.assertTrue(result.rollback_succeeded)
        self.assertEqual(file_sha256(self.target),self.original);self.assertFalse(self.part.exists())

    def test_wrong_identity_and_existing_part_do_not_touch_target(self):
        self.inner.write_bytes(b'changed')
        with self.assertRaises(ValueError):install_outer(self.staged,self.inner,self.target,restart=False)
        self.assertFalse(self.part.exists());self.assertEqual(file_sha256(self.target),self.original)
        self.inner.write_bytes(b'old business fixture');self.part.write_bytes(b'preexisting')
        with self.assertRaises(FileExistsError):install_outer(self.staged,self.inner,self.target,restart=False)
        self.assertEqual(self.part.read_bytes(),b'preexisting');self.assertEqual(file_sha256(self.target),self.original)

    def test_no_upgrade_or_tampered_candidate_never_copies_part(self):
        with self.assertRaises(ValueError):install_outer(self.staged,self.inner,self.target,current_version='0.3.0')
        with self.staged.open('ab') as stream:stream.write(b'changed')
        with self.assertRaises(ValueError):install_outer(self.staged,self.inner,self.target)
        self.assertFalse(self.part.exists());self.assertEqual(file_sha256(self.target),self.original)

    def test_restart_uses_outer_and_preserves_original_argument_filter(self):
        launched=[];scheduled=[]
        class Process:
            @staticmethod
            def startDetached(program,args,cwd):launched.append((program,args,cwd));return True,123
        def factory(scope):return QtWin32HandoffBackend(scope,qprocess=Process,schedule_exit=lambda delay,callback:scheduled.append(delay))
        result=install_outer(self.staged,self.inner,self.target,arguments=['--no-update','--update-now','--no-watch'],backend_factory=factory)
        self.assertTrue(result.restart_started)
        self.assertEqual(launched,[(str(self.target),['--no-watch'],str(self.root))])
        self.assertEqual(scheduled,[300])


if __name__=='__main__':unittest.main()
