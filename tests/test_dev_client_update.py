import json,sys,tempfile,unittest,zipfile,hashlib
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'desktop'))
from tools.build_client_release import build_client
from wowbuddy.dev_client_update import stage_update,replace_stopped_client

class ClientUpdateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.source=self.root/'source';(self.source/'_internal').mkdir(parents=True)
        (self.source/'WowBuddyDev.exe').write_bytes(b'MZ new fixture, never run')
        (self.source/'_internal/runtime.dll').write_bytes(b'new runtime')
        (self.source/'.local').mkdir();(self.source/'.local/private.ini').write_text('exclude')
        self.package=self.root/'client.zip'
        self.manifest=build_client(self.source,self.package,'0.2.1')
        self.manifest_path=self.package.with_suffix('.manifest.json')
        self.current=self.root/'installed';(self.current/'_internal').mkdir(parents=True)
        (self.current/'WowBuddyDev.exe').write_bytes(b'MZ old')
        (self.current/'_internal/runtime.dll').write_bytes(b'old runtime')
        (self.current/'.local').mkdir();(self.current/'.local/settings.ini').write_text('user value')

    def stage(self):return stage_update(self.package,self.manifest_path,self.root/'stage')

    def test_full_directory_swap_preserves_settings_and_old_backup(self):
        self.assertFalse(any('/.local/' in name for name in self.manifest['members']))
        result=replace_stopped_client(self.stage(),self.current)
        self.assertEqual((self.current/'_internal/runtime.dll').read_bytes(),b'new runtime')
        self.assertEqual((self.current/'.local/settings.ini').read_text(),'user value')
        self.assertFalse((self.current/'.local/private.ini').exists())
        self.assertEqual((Path(result['backup'])/'WowBuddyDev.exe').read_bytes(),b'MZ old')
        self.assertFalse(result['restarted'])

    def test_failed_swap_rolls_back_and_can_retry(self):
        stage=self.stage();rename=Path.rename
        def fail(path,destination):
            if path==stage:raise OSError('simulated locked target')
            return rename(path,destination)
        with patch.object(Path,'rename',fail),self.assertRaises(OSError):replace_stopped_client(stage,self.current)
        self.assertEqual((self.current/'WowBuddyDev.exe').read_bytes(),b'MZ old')
        self.assertFalse((stage/'.local').exists())
        replace_stopped_client(stage,self.current)

    def test_tampering_and_nested_stage_leave_current_untouched(self):
        stage=self.stage();(stage/'_internal/runtime.dll').write_bytes(b'tampered')
        with self.assertRaises(ValueError):replace_stopped_client(stage,self.current)
        with self.assertRaises(ValueError):replace_stopped_client(self.current/'stage',self.current)
        self.assertEqual((self.current/'WowBuddyDev.exe').read_bytes(),b'MZ old')

    def test_traversal_rejected_even_with_matching_manifest(self):
        for name in ('WowBuddyDev/../escape','WowBuddyDev/.local/settings.ini','WowBuddyDev/CON.txt','WowBuddyDev/a:stream'):
            with self.subTest(name=name):
                content=b'data'
                with zipfile.ZipFile(self.package,'w') as archive:archive.writestr(name,content)
                manifest={'product':'wowbuddy-client','format':1,'sha256':hashlib.sha256(self.package.read_bytes()).hexdigest(),
                          'members':{name:hashlib.sha256(content).hexdigest()}}
                self.manifest_path.write_text(json.dumps(manifest),'utf8')
                with self.assertRaises(ValueError):self.stage()
                self.assertEqual(list((self.root/'stage').iterdir()),[])

if __name__=='__main__':unittest.main()
