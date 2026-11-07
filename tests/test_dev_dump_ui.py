"""独立CLI的真实进程诊断；不依赖正在运行的游戏或桌面。"""
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

ROOT=Path(__file__).resolve().parents[1]

class DumpUiTests(unittest.TestCase):
    def test_cli_generates_ui_and_showall_then_exits(self):
        with TemporaryDirectory() as directory:
            result=subprocess.run([sys.executable,str(ROOT/'run_dev.py'),'--dump-ui',
                '--spec=1482','--spec=1484','--talent=10/0/0','--toggle-showall',
                '--data-dir',directory],cwd=ROOT,capture_output=True,timeout=20)
            self.assertEqual(result.returncode,0,result.stderr.decode('utf8',errors='replace'))
            report=json.loads((Path(directory)/'dump-ui.json').read_text('utf8'))
            self.assertTrue(report['passed'])
            self.assertEqual(report['spec'],'1484')
            self.assertEqual(report['backend'],'NoSystemBackend')
            self.assertFalse(report['monitor_active'])
            self.assertFalse(report['watch_active'])
            self.assertIn('spec=1484',(Path(directory)/'_ui.txt').read_text('utf8'))
            showall=(Path(directory)/'_showall.txt').read_text('utf8')
            self.assertIn('--toggle-showall on',showall)
            self.assertIn('--toggle-showall off',showall)

    def test_diagnostic_parameter_conflicts_rejected_before_launch(self):
        for args in (['--dump-ui','--watch'],['--dump-ui','--desktop-selftest']):
            with self.subTest(args=args):
                result=subprocess.run([sys.executable,str(ROOT/'run_dev.py'),*args],
                    cwd=ROOT,capture_output=True,timeout=10)
                self.assertEqual(result.returncode,2)

    def test_report_write_failure_returns_nonzero(self):
        with TemporaryDirectory() as directory:
            (Path(directory)/'_ui.txt').mkdir()
            result=subprocess.run([sys.executable,str(ROOT/'run_dev.py'),'--dump-ui',
                '--data-dir',directory],cwd=ROOT,capture_output=True,timeout=20)
            self.assertEqual(result.returncode,1)
            report=json.loads((Path(directory)/'dump-ui.json').read_text('utf8'))
            self.assertFalse(report['passed'])
            self.assertFalse(report['ui_written'])
            self.assertTrue(report['errors'])
