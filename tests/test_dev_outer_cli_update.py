"""外层CLI分流与原05b7f0返回码；下载、重启使用替身。"""
import json,os,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch,Mock
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'desktop'))
from wowbuddy.dev_cli_update import run_outer_update_now,current_outer_target
from wowbuddy.dev_native_commands import dispatch_native_command
from wowbuddy.update_handoff import HandoffResult


class OuterCliTests(unittest.TestCase):
    def test_phase_exit_codes_and_no_delayed_gui_exit(self):
        for phase,expected in [('replacement_complete',0),('restart_started',0),('restart_failed',0),('replacement_failed',1)]:
            with self.subTest(phase=phase),tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'WOWBUDDY_UPDATE_NO_RESTART':''}):
                root=Path(tmp);outer=root/'Outer.exe';inner=root/'inner.exe'
                install=Mock(return_value=HandoffResult(phase,'测试结果',restart_started=phase=='restart_started'))
                download=Mock(return_value={'kind':'outer','staged':'candidate.exe'})
                code=run_outer_update_now(root,inner,outer,['--update-now','--no-watch'],
                    check=lambda:{'version':'0.3.0','current_version':'0.2.4','has_update':True},
                    download=download,install=install)
                self.assertEqual(code,expected)
                self.assertEqual(download.call_args.args[1],root/'WowBuddyDev-updates')
                self.assertEqual(install.call_args.args,('candidate.exe',inner,outer))
                self.assertFalse(install.call_args.kwargs['restart'])
                self.assertFalse(install.call_args.kwargs['schedule_restart_exit'])
                self.assertEqual(install.call_args.kwargs['arguments'],['--update-now','--no-watch'])
                report=json.loads((root/'update-now.json').read_text('utf8'))
                self.assertEqual(report['installed'],expected==0)
                self.assertFalse(report['handoff_ready'])

    def test_no_update_and_wrong_payload_do_not_install(self):
        for has_update in (False,True):
            with tempfile.TemporaryDirectory() as tmp:
                install=Mock();download=Mock(return_value={'staged':'directory'})
                code=run_outer_update_now(tmp,'inner.exe',Path(tmp)/'outer.exe',[],
                    check=lambda:{'version':'0.3.0','current_version':'0.2.4','has_update':has_update},
                    download=download,install=install)
                self.assertEqual(code,1 if has_update else 0)
                self.assertEqual(download.call_count,int(has_update));install.assert_not_called()

    def test_dispatch_uses_outer_transport_only_for_valid_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            options=dict(assets=ROOT/'assets',application=Path(tmp),packages=Path(tmp),frozen=True)
            for outer in (None,Path(tmp)/'outer.exe'):
                with patch('wowbuddy.dev_cli_update.current_outer_target',return_value=outer),\
                     patch('wowbuddy.github_client.run_check_command',return_value=10) as check,\
                     patch('wowbuddy.dev_cli_update.run_outer_update_now',return_value=0) as install,\
                     patch('wowbuddy.dev_cli_update.run_update_now',return_value=0) as directory:
                    self.assertEqual(dispatch_native_command(['app','--check-update'],**options),10)
                    self.assertEqual('check' in check.call_args.kwargs,outer is not None)
                    self.assertEqual(dispatch_native_command(['app','--update-now'],**options),0)
                    self.assertEqual(install.call_count,int(outer is not None))
                    self.assertEqual(directory.call_count,int(outer is None))

    def test_source_never_validates_environment_outer(self):
        with patch('wowbuddy.release_identity.validated_outer_target') as validate:
            self.assertIsNone(current_outer_target(False));validate.assert_not_called()

    def test_default_restart_and_install_exception_report(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{},clear=True):
            install=Mock(side_effect=ValueError('候选校验失败'))
            code=run_outer_update_now(tmp,'inner.exe',Path(tmp)/'outer.exe',[],
                check=lambda:{'version':'0.3.0','current_version':'0.2.4','has_update':True},
                download=lambda *args:{'kind':'outer','staged':'candidate.exe'},install=install)
            self.assertEqual(code,1)
            self.assertTrue(install.call_args.kwargs['restart'])
            report=json.loads((Path(tmp)/'update-now.json').read_text('utf8'))
            self.assertFalse(report['installed']);self.assertIn('候选校验失败',report['error'])


if __name__=='__main__':unittest.main()
