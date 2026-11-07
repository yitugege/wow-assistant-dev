import sys,tempfile,unittest,itertools
from pathlib import Path
from contextlib import ExitStack
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'desktop'))
import run_dev
from wowbuddy.dev_native_commands import dispatch_native_command,command_data_dir

class NativeCommandTests(unittest.TestCase):
    def test_all_supported_command_combinations_use_native_priority(self):
        flags=['--selftest','--install-addon','--check-update','--update-now','--hub-selftest']
        functions=['dev_native_selftest.run_native_selftest','dev_cli_install.run_development_install',
                   'github_client.run_check_command','dev_cli_update.run_update_now','dev_native_hub.run_native_hub']
        with tempfile.TemporaryDirectory() as tmp,ExitStack() as stack:
            calls=[stack.enter_context(patch('wowbuddy.'+name,return_value=10+i)) for i,name in enumerate(functions)]
            for size in range(1,6):
                for selected in itertools.permutations(range(5),size):
                    with self.subTest(selected=selected):
                        for call in calls:call.reset_mock()
                        arguments=['app',*(flags[i] for i in selected),'--unknown-original-option','--auto','--spec','--data-dir',tmp]
                        with patch.object(sys,'argv',arguments),patch.object(run_dev,'launch') as gui:
                            self.assertEqual(run_dev.main(),10+min(selected))
                            gui.assert_not_called()
                        self.assertEqual([m.call_count for m in calls],[int(i==min(selected)) for i in range(5)])

    def test_raw_install_arguments_and_hub_fetch_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            options=dict(assets=ROOT/'assets',application=Path(tmp),packages=Path(tmp),frozen=False)
            args=['app','--install-addon','--install-addon-dir=one','--install-addon-dir=two']
            with patch('wowbuddy.dev_cli_install.run_development_install',return_value=0) as install:
                self.assertEqual(dispatch_native_command(args,**options),0)
                self.assertEqual(install.call_args.args[0],args)
            with patch('wowbuddy.dev_native_hub.run_native_hub',return_value=0) as hub:
                self.assertEqual(dispatch_native_command(['app','--hub-selftest','--hub-fetch'],**options),0)
                self.assertTrue(hub.call_args.kwargs['fetch_online'])

    def test_gui_and_unimplemented_crash_are_not_dispatched_as_install(self):
        options=dict(assets=ROOT/'assets',application=ROOT,packages=ROOT/'dist',frozen=False)
        for args in (['app','--auto'],['app','--CHECK-UPDATE'],['app','--crash-test','--install-addon']):
            self.assertIsNone(dispatch_native_command(args,**options))

    def test_data_dir_extension_last_value_and_missing_argument(self):
        self.assertEqual(command_data_dir(['app','--data-dir=first','--data-dir','second'],'default'),Path('second'))
        with self.assertRaises(ValueError):command_data_dir(['app','--data-dir'],'default')

if __name__=='__main__':unittest.main()
