"""原循环库命令：真实子进程隔离缓存与报告，不触发联网或GUI。"""
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
from wowbuddy.dev_native_hub import run_native_hub
from wowbuddy.dev_native_commands import dispatch_native_command
from wowbuddy.cli_hub import FetchWait
from wowbuddy.dev_hub_online import HUB_URL


class NativeHubTests(unittest.TestCase):
    def invoke(self,directory):
        environment=os.environ.copy()
        environment.update(WOWBUDDY_HOME=str(Path(directory)/'ignored'),WOWBUDDY_HUB_URL='http://127.0.0.1:1/unused')
        result=subprocess.run([sys.executable,str(ROOT/'run_dev.py'),'--hub-selftest','--data-dir',str(directory)],
                              cwd=ROOT,env=environment,capture_output=True,timeout=15)
        self.assertFalse((Path(directory)/'ignored').exists())
        self.assertFalse((Path(directory)/'hub-selftest.json').exists())
        return result

    def test_missing_cache_is_not_seeded_and_returns_failure(self):
        with TemporaryDirectory() as directory:
            result=self.invoke(directory)
            self.assertEqual(result.returncode,1,result.stderr)
            self.assertFalse((Path(directory)/'hub/rotations.json').exists())
            text=(Path(directory)/'_hub.txt').read_text('utf8')
            self.assertIn('缓存存在 否',text)
            self.assertIn('FAIL（没有规则可用）',text)

    def test_usable_cache_success_even_when_report_cannot_be_written(self):
        for report_blocked in (False,True):
            with self.subTest(report_blocked=report_blocked),TemporaryDirectory() as directory:
                cache=Path(directory)/'hub/rotations.json';cache.parent.mkdir()
                payload=(ROOT/'assets/rotations.json').read_bytes();cache.write_bytes(payload)
                if report_blocked:(Path(directory)/'_hub.txt').mkdir()
                result=self.invoke(directory)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual(cache.read_bytes(),payload)
                if not report_blocked:
                    self.assertIn('PASS（有可用规则）',(Path(directory)/'_hub.txt').read_text('utf8'))

    def test_default_report_directory_is_application_and_cache_is_independent(self):
        with TemporaryDirectory() as directory,patch('wowbuddy.dev_native_hub.run_native_hub',return_value=1) as command:
            app=Path(directory)
            self.assertEqual(dispatch_native_command(['app','--hub-selftest'],assets=ROOT/'assets',
                application=app,packages=app,frozen=False),1)
            self.assertEqual(command.call_args.args,(app/'.local',app))

    def test_fetch_is_explicit_uses_own_url_and_cleans_up(self):
        calls=[];cleaned=[]
        def fetch(sync,url,timeout):
            calls.append((url,timeout))
            return FetchWait(2,False,lambda:cleaned.append(True))
        with TemporaryDirectory() as directory:
            self.assertEqual(run_native_hub(directory,directory,fetch=fetch),1)
            self.assertFalse(calls)
            # 假fetch不用Qt；避免在单测宿主留下QCoreApplication干扰GUI用例。
            with patch('PySide6.QtCore.QCoreApplication.instance',return_value=object()):
                self.assertEqual(run_native_hub(directory,directory,fetch_online=True,fetch=fetch),1)
            self.assertEqual(calls,[(HUB_URL,20000)])
            self.assertEqual(cleaned,[True])


if __name__=='__main__':unittest.main()
