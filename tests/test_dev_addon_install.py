"""在临时客户端验证实际文件安装、备份和失败回滚。"""
import hashlib
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
import zipfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
from wowbuddy.dev_addon_install import install_package, client_directory
from tools.build_addon import build

class InstallTests(unittest.TestCase):
    def legacy(self):
        from wowbuddy.addon_install import SIGNATURE_FILES
        directory=self.client/'Interface/AddOns/legacy'
        directory.mkdir(parents=True,exist_ok=True)
        for name in SIGNATURE_FILES:(directory/name).write_text('-- legacy','utf8')
        return directory

    def test_success_cleans_legacy_only_after_record_is_committed(self):
        legacy=self.legacy()
        from wowbuddy.dev_addon_cleanup import cleanup_addons_directory
        def check(addons,keep):
            record=json.loads((self.client/'.wowbuddy-install.json').read_text('utf8'))
            self.assertEqual(record['addon_directory'],keep)
            self.assertTrue((self.target/'Core.lua').is_file())
            return cleanup_addons_directory(addons,keep)
        with patch('wowbuddy.dev_addon_cleanup.cleanup_addons_directory',side_effect=check):
            result=install_package(self.package,self.client)
        self.assertEqual(result['cleanup_deleted'],1)
        self.assertFalse(legacy.exists());self.assertTrue(self.target.is_dir())

    def test_install_failure_never_runs_cleanup(self):
        legacy=self.legacy()
        self.package.write_bytes(b'bad')
        with patch('wowbuddy.dev_addon_cleanup.cleanup_addons_directory') as cleanup:
            with self.assertRaises(ValueError):install_package(self.package,self.client)
            cleanup.assert_not_called()
        self.assertTrue(legacy.exists())

    def test_cleanup_failure_does_not_reclassify_successful_install(self):
        legacy=self.legacy()
        with patch('wowbuddy.addon_actions._remove_plugin_directory',side_effect=OSError('locked')):
            result=install_package(self.package,self.client)
        self.assertEqual(result['cleanup_deleted'],0)
        self.assertIn('删除失败',result['cleanup_notes'])
        self.assertTrue(legacy.exists());self.assertTrue((self.target/'Core.lua').exists())

    def setUp(self):
        self.temporary=TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)
        self.client=self.root/'client';self.client.mkdir()
        (self.client/'Wow.exe').write_bytes(b'fixture, never executed')
        self.source=self.root/'source';self.source.mkdir()
        (self.source/'WowBuddyDev.toc').write_text('Core.lua\n','utf8')
        (self.source/'Core.lua').write_text('-- new\n','utf8')
        self.package=self.root/'addon.zip'
        manifest=build(self.source,self.package)
        self.package.with_suffix('.manifest.json').write_text(json.dumps(manifest),'utf8')
        self.target=self.client/'Interface/AddOns/WowBuddyDev'

    def test_install_update_backup_and_other_addons_unchanged(self):
        result=install_package(self.package,self.client)
        self.assertIsNone(result['backup'])
        self.assertEqual((self.target/'Core.lua').read_bytes(),(self.source/'Core.lua').read_bytes())
        (self.target/'custom.lua').write_bytes(b'user change')
        other=self.target.parent/'old-random-addon';other.mkdir()
        (other/'old.lua').write_bytes(b'untouched')
        result=install_package(self.package,self.target.parent)
        self.assertEqual((Path(result['backup'])/'custom.lua').read_bytes(),b'user change')
        self.assertFalse((self.target/'custom.lua').exists())
        self.assertEqual((other/'old.lua').read_bytes(),b'untouched')

    def test_checksum_failure_leaves_existing_install_untouched(self):
        install_package(self.package,self.client)
        self.package.write_bytes(b'corrupt')
        with self.assertRaises(ValueError):install_package(self.package,self.client)
        self.assertEqual((self.target/'Core.lua').read_text('utf8'),'-- new\n')
        self.assertFalse((self.client/'WowBuddyDev-backups').exists())

    def test_swap_failure_restores_previous_directory(self):
        install_package(self.package,self.client)
        (self.target/'custom.lua').write_bytes(b'previous')
        rename=Path.rename
        def fail_stage(path,destination):
            if path.parent.name.startswith('.wowbuddy-install-'):
                raise OSError('injected swap failure')
            return rename(path,destination)
        with patch.object(Path,'rename',fail_stage),self.assertRaises(OSError):
            install_package(self.package,self.client)
        self.assertEqual((self.target/'custom.lua').read_bytes(),b'previous')

    def test_traversal_rejected_even_with_matching_manifest(self):
        name='WowBuddyDev/../../outside.lua';data=b'bad'
        with zipfile.ZipFile(self.package,'w') as archive:archive.writestr(name,data)
        manifest={'sha256':hashlib.sha256(self.package.read_bytes()).hexdigest(),
                  'members':{name:hashlib.sha256(data).hexdigest()}}
        self.package.with_suffix('.manifest.json').write_text(json.dumps(manifest),'utf8')
        with self.assertRaises(ValueError):install_package(self.package,self.client)
        self.assertFalse((self.client/'Interface').exists())

    def test_invalid_client_rejected(self):
        with self.assertRaises(ValueError):client_directory(self.root)
