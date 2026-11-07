"""真实文件摘要与外层身份替身；不将替身结果称为冻结PE验收。"""
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'desktop'))
import run_dev
from wowbuddy.dev_paths import default_data_dir
from wowbuddy.release_identity import ReleaseIdentity,validated_outer_target,file_sha256
from wowbuddy.launcher import BUSINESS_EXE
from wowbuddy.dev_startup import run_logged


class DataPathTests(unittest.TestCase):
    @unittest.skipUnless((ROOT/'dist/desktop/WowBuddyDev/WowBuddyDev.exe').is_file(),'需要已有自有构建作为PE资源载体')
    def test_actual_pe_identity_resource_selects_stable_home(self):
        import shutil
        from PyInstaller.utils.win32.winresource import add_or_update_resource
        with TemporaryDirectory() as directory:
            root=Path(directory);cache=root/'cache';cache.mkdir()
            inner=cache/BUSINESS_EXE
            shutil.copy2(ROOT/'dist/desktop/WowBuddyDev/WowBuddyDev.exe',inner)
            outer=root/'own-outer-fixture.exe';shutil.copy2(inner,outer)
            env={'WOWBUDDY_HOME':str(root),'WOWBUDDY_EXE':str(outer)}
            self.assertEqual(default_data_dir(cache,frozen=True,executable=inner,environment=env),cache/'.local')
            identity=ReleaseIdentity('a'*64,file_sha256(inner))
            add_or_update_resource(str(outer),identity.encode(),10,[203],[1033])
            self.assertEqual(default_data_dir(cache,frozen=True,executable=inner,environment=env),root/'.local')
            with inner.open('ab') as stream:stream.write(b'changed')
            self.assertEqual(default_data_dir(cache,frozen=True,executable=inner,environment=env),cache/'.local')

    def test_verified_outer_survives_cache_change_and_rejects_stale_identity(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);outer=root/'独立外层.exe';outer.write_bytes(b'outer fixture')
            env={'WOWBUDDY_EXE':str(outer),'WOWBUDDY_HOME':str(root)}
            for folder in ('cache-a','cache-b'):
                app=root/folder;app.mkdir();inner=app/BUSINESS_EXE;inner.write_bytes(b'current client')
                identity=ReleaseIdentity('a'*64,file_sha256(inner))
                with patch('wowbuddy.dev_paths.validated_outer_target',side_effect=lambda o,i:validated_outer_target(o,i,identity_reader=lambda p:identity)):
                    self.assertEqual(default_data_dir(app,frozen=True,executable=inner,environment=env),root/'.local')
                    self.assertEqual(default_data_dir(app,frozen=False,executable=inner,environment=env),app/'.local')
                    self.assertEqual(default_data_dir(app,frozen=True,executable=inner,environment=env|{'WOWBUDDY_HOME':str(app)}),app/'.local')
                    inner.write_bytes(b'other client')
                    self.assertEqual(default_data_dir(app,frozen=True,executable=inner,environment=env),app/'.local')

    def test_unverified_environment_keeps_directory_defaults(self):
        with TemporaryDirectory() as directory:
            app=Path(directory)
            for env in ({},{'WOWBUDDY_HOME':str(app.parent)},
                        {'WOWBUDDY_HOME':str(app.parent),'WOWBUDDY_EXE':str(app/'absent.exe')}):
                self.assertEqual(default_data_dir(app,frozen=True,executable=app/'WowBuddyDev.exe',environment=env),app/'.local')

    def test_gui_startup_log_and_early_cache_share_default_and_cli_override(self):
        with TemporaryDirectory() as directory:
            root=Path(directory);stable=root/'outer/.local';cache=root/'cache';override=root/'explicit'
            for args,expected in ((['app','--no-watch'],stable),(['app','--no-watch','--data-dir',str(override)],override)):
                with patch('wowbuddy.dev_startup.default_data_dir',return_value=stable),patch.object(run_dev,'default_data_dir',return_value=stable),patch.object(run_dev,'launch',return_value=0) as launch:
                    self.assertEqual(run_logged(lambda:run_dev.main(args),application=cache,arguments=args),0)
                    self.assertEqual(launch.call_args.args[0],expected)
                    self.assertTrue((expected/'startup.log').is_file())
                from wowbuddy.dev_native_commands import dispatch_native_command
                with patch('wowbuddy.dev_native_commands.default_data_dir',return_value=stable),patch('wowbuddy.dev_native_hub.run_native_hub',return_value=0) as hub:
                    dispatch_native_command([*args,'--hub-selftest'],assets=ROOT/'assets',application=cache,packages=root,frozen=True)
                    self.assertEqual(hub.call_args.args[0],expected)
            self.assertFalse((cache/'.local').exists())


if __name__=='__main__':unittest.main()
