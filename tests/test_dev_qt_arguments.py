"""独立子进程使用真实Qt消费参数，避免复用单测宿主QApplication。"""
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))


class QtArgumentTests(unittest.TestCase):
    def test_actual_qt_consumes_platform_and_style_before_callback(self):
        script="""
import sys,json
from pathlib import Path
sys.path.insert(0,'desktop')
from wowbuddy.dev_startup import run_logged
from PySide6.QtWidgets import QApplication
selected=[]
original=QApplication.setStyleSheet
def apply_style(self,value):
    selected.append(self.style().objectName())
    original(self,value)
QApplication.setStyleSheet=apply_style
def command(arguments):
    app=QApplication.instance()
    print(json.dumps({'arguments':arguments,'platform':app.platformName(),'style':selected[0]}))
    return 0
raise SystemExit(run_logged(command,application=Path(sys.argv[1]),arguments=['probe','-platform','offscreen','-style','Fusion','--unknown','--data-dir',sys.argv[1]],qt_runtime=True))
"""
        with TemporaryDirectory() as directory:
            run=subprocess.run([sys.executable,'-c',script,directory],cwd=ROOT,capture_output=True,text=True,timeout=15)
            self.assertEqual(run.returncode,0,run.stderr)
            report=json.loads(run.stdout)
            self.assertEqual(report['arguments'],['probe','--unknown','--data-dir',directory])
            self.assertEqual(report['platform'],'offscreen')
            self.assertEqual(report['style'].lower(),'fusion')

    def test_qt_option_value_does_not_become_early_business_command(self):
        with TemporaryDirectory() as directory:
            # --selftest在这里是Qt -style的值；原始列表提前分派会错选selftest。
            run=subprocess.run([sys.executable,str(ROOT/'run_dev.py'),'-platform','offscreen',
                '-style','--selftest','--hub-selftest','--data-dir',directory],cwd=ROOT,capture_output=True,timeout=15)
            self.assertEqual(run.returncode,1,run.stderr)
            self.assertTrue((Path(directory)/'_hub.txt').is_file())
            self.assertFalse((Path(directory)/'_selftest.txt').exists())
            log=(Path(directory)/'startup.log').read_text('utf8')
            self.assertIn('QApplication',log)
            self.assertIn('offscreen',log)

    def test_independent_headless_diagnostic_reuses_bootstrap_application(self):
        with TemporaryDirectory() as directory:
            run=subprocess.run([sys.executable,str(ROOT/'run_dev.py'),'--desktop-dump-ui',
                '--data-dir',directory],cwd=ROOT,capture_output=True,timeout=20)
            self.assertEqual(run.returncode,0,run.stderr)
            report=json.loads((Path(directory)/'dump-ui.json').read_text('utf8'))
            self.assertTrue(report['passed'])
            self.assertEqual(report['backend'],'NoSystemBackend')
            from wowbuddy.startup_log import QT_READY,STYLE_READY
            log=(Path(directory)/'startup.log').read_text('utf8')
            self.assertEqual(log.count(QT_READY),1)
            self.assertEqual(log.count(STYLE_READY),1)


if __name__=='__main__':unittest.main()
