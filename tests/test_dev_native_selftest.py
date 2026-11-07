import json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'desktop'))
import run_dev
from wowbuddy.dev_native_selftest import run_native_selftest

class NativeSelftestTests(unittest.TestCase):
    def test_non_object_specs_reports_empty_rules_instead_of_raising(self):
        from PySide6.QtCore import QJsonValue
        for specs in (None,42,'1482',['1482'],True):
            with self.subTest(specs=specs),tempfile.TemporaryDirectory() as tmp:
                self.assertEqual(QJsonValue.fromVariant(specs).toObject(),{})
                root=Path(tmp);assets=root/'assets';assets.mkdir()
                (assets/'rules.json').write_text(json.dumps({'specs':specs}),'utf8')
                (assets/'contract.json').write_bytes((ROOT/'assets/contract.json').read_bytes())
                self.assertEqual(run_native_selftest(assets,root,['app','--selftest']),0)
                report=(root/'_selftest.txt').read_text('utf8')
                self.assertIn('rules 加载失败: 规则内容为空',report)
                self.assertIn('C++ 引擎自检',report)

    def test_engine_report_appends_and_does_not_create_gui_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)
            argv=['WowBuddyDev','--selftest','--rotations='+str(ROOT/'assets/rotations.json')]
            self.assertEqual(run_native_selftest(ROOT/'assets',output,argv),0)
            first=(output/'_selftest.txt').read_bytes()
            self.assertIn('C++ 引擎自检',first.decode('utf8'))
            self.assertEqual(run_native_selftest(ROOT/'assets',output,argv),0)
            self.assertEqual((output/'_selftest.txt').read_bytes(),first+first)
            self.assertFalse((output/'desktop-selftest.json').exists())

    def test_native_write_failure_keeps_native_zero_exit_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp);(output/'_selftest.txt').mkdir()
            self.assertEqual(run_native_selftest(ROOT/'assets',output,['app','--selftest']),0)

    def test_cli_prioritizes_selftest_without_launching_gui_or_updater(self):
        with tempfile.TemporaryDirectory() as tmp:
            argv=['app','--selftest','--auto','--update-now','--data-dir',tmp]
            with patch.object(sys,'argv',argv),patch('wowbuddy.dev_native_selftest.run_native_selftest',return_value=0) as engine,patch.object(run_dev,'launch') as gui:
                self.assertEqual(run_dev.main(),0)
                self.assertEqual(engine.call_args.args[1],Path(tmp))
                self.assertEqual(engine.call_args.args[2],argv)
                gui.assert_not_called()

    def test_default_report_location_is_application_directory(self):
        with patch.object(sys,'argv',['app','--selftest']),patch('wowbuddy.dev_native_selftest.run_native_selftest',return_value=0) as engine:
            self.assertEqual(run_dev.main(),0)
            self.assertEqual(engine.call_args.args[1],run_dev.APP_ROOT)

if __name__=='__main__':unittest.main()
