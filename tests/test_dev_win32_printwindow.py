"""实际 GDI 回退抓屏后逐像素比较并解码；不读取游戏窗口。"""
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform=='win32','需要 Windows')
class PrintWindowTests(unittest.TestCase):
    def test_native_capture_and_both_protocols_for_nine_specs(self):
        result=subprocess.run([sys.executable,'-c',
            'import json; from tools.check_win32_printwindow import check; print(json.dumps(check()))'],
            cwd=ROOT,env=dict(os.environ,QT_QPA_PLATFORM='windows'),
            capture_output=True,text=True,timeout=45)
        self.assertEqual(result.returncode,0,result.stderr)
        report=json.loads(result.stdout)
        self.assertTrue(report['passed'])
        self.assertEqual(len(report['cases']),18)
        self.assertFalse(report['game_capture_verified'])
        self.assertFalse(report['dxgi_verified'])


if __name__=='__main__':unittest.main()
