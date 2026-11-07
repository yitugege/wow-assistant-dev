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

    def test_random_release_preserves_existing_fixed_identity_and_saved_files(self):
        install_package(self.package,self.client)
        saved=self.client/'WTF/Account/fixture/SavedVariables/WowBuddyDev.lua'
        saved.parent.mkdir(parents=True)
        saved.write_bytes(b'WowBuddyDevDB = { masterKey = "F6" }\n')
        enabled=self.client/'WTF/Account/fixture/realm/character/AddOns.txt'
        enabled.parent.mkdir(parents=True);enabled.write_bytes(b'WowBuddyDev: enabled\n')
        before={path:path.read_bytes() for path in (saved,enabled)}
        manifest=build(self.source,self.package,random_names=True)
        self.package.with_suffix('.manifest.json').write_text(json.dumps(manifest),'utf8')
        result=install_package(self.package,self.client)
        self.assertEqual(result['addon_directory'],'WowBuddyDev')
        self.assertEqual(Path(result['target']),self.target)
        self.assertTrue((self.target/'WowBuddyDev.toc').is_file())
        self.assertFalse((self.target.parent/manifest['addon_directory']).exists())
        self.assertTrue(Path(result['backup']).is_dir())
        self.assertEqual(before,{path:path.read_bytes() for path in before})
        for line in (self.target/'WowBuddyDev.toc').read_text('utf8').splitlines():
            if line and not line.startswith('#'):self.assertTrue((self.target/line).is_file())

    def test_existing_fixed_install_without_record_keeps_identity(self):
        install_package(self.package,self.client)
        (self.client/'.wowbuddy-install.json').unlink()
        manifest=build(self.source,self.package,random_names=True)
        self.package.with_suffix('.manifest.json').write_text(json.dumps(manifest),'utf8')
        result=install_package(self.package,self.client)
        self.assertEqual(result['addon_directory'],'WowBuddyDev')
        self.assertTrue((self.target/'WowBuddyDev.toc').is_file())
        record=json.loads((self.client/'.wowbuddy-install.json').read_text('utf8'))
        self.assertEqual(record['addon_directory'],'WowBuddyDev')

    def test_manual_random_install_without_record_keeps_identity(self):
        manifest=build(self.source,self.package,random_names=True)
        self.package.with_suffix('.manifest.json').write_text(json.dumps(manifest),'utf8')
        addons=self.client/'Interface/AddOns';addons.mkdir(parents=True)
        with zipfile.ZipFile(self.package) as archive:archive.extractall(addons)
        old_name=manifest['addon_directory']
        old=addons/old_name
        foreign=addons/'w000000000000';foreign.mkdir()
        (foreign/(foreign.name+'.toc')).write_text('## Title: Other addon\n','utf8')
        legacy=addons/'w111111111111';legacy.mkdir()
        legacy_toc=legacy/(legacy.name+'.toc')
        legacy_bytes='## Title: 其他插件\n'.encode('gbk')
        legacy_toc.write_bytes(legacy_bytes)
        before={p.relative_to(old):p.read_bytes() for p in old.rglob('*') if p.is_file()}
        saved=self.client/'WTF/SavedVariables'/f'{old_name}.lua'
        saved.parent.mkdir(parents=True);saved.write_bytes(b'preserve identity')
        replacement=build(self.source,self.package,random_names=True)
        self.assertNotEqual(old_name,replacement['addon_directory'])
        self.package.with_suffix('.manifest.json').write_text(json.dumps(replacement),'utf8')
        result=install_package(self.package,self.client)
        self.assertEqual(result['addon_directory'],old_name)
        self.assertTrue((old/(old_name+'.toc')).is_file())
        self.assertFalse((addons/replacement['addon_directory']).exists())
        backup=Path(result['backup'])
        self.assertEqual(before,{p.relative_to(backup):p.read_bytes() for p in backup.rglob('*') if p.is_file()})
        self.assertEqual(saved.read_bytes(),b'preserve identity')
        self.assertEqual((foreign/(foreign.name+'.toc')).read_text('utf8'),'## Title: Other addon\n')
        self.assertEqual(legacy_toc.read_bytes(),legacy_bytes)

    def test_multiple_manual_random_identities_fail_without_mutation(self):
        addons=self.client/'Interface/AddOns';addons.mkdir(parents=True)
        for _ in range(2):
            manifest=build(self.source,self.package,random_names=True)
            self.package.with_suffix('.manifest.json').write_text(json.dumps(manifest),'utf8')
            with zipfile.ZipFile(self.package) as archive:archive.extractall(addons)
        before={p.relative_to(self.client):p.read_bytes() for p in self.client.rglob('*') if p.is_file()}
        with self.assertRaisesRegex(ValueError,'多个本产品'):
            install_package(self.package,self.client)
        self.assertEqual(before,{p.relative_to(self.client):p.read_bytes() for p in self.client.rglob('*') if p.is_file()})
