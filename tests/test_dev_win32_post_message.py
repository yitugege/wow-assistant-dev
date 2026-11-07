"""实际后台投递到自有消息窗口；不向游戏或用户窗口发键。"""
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]


@unittest.skipUnless(sys.platform=='win32','需要 Windows')
class NativePostMessageTests(unittest.TestCase):
    def test_owned_message_window_receives_exact_key_sequence(self):
        result=subprocess.run([sys.executable,'-c',
            'import json; from tools.check_win32_post_message import check; print(json.dumps(check()))'],
            cwd=ROOT,capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)
        report=json.loads(result.stdout)
        self.assertTrue(report['passed'])
        self.assertEqual(len(report['received']),20)
        self.assertEqual(report['success_count'],5)
        self.assertEqual(report['failure_count'],2)
        self.assertFalse(report['global_input_used'])
        self.assertFalse(report['game_acceptance_verified'])


if __name__=='__main__':unittest.main()
