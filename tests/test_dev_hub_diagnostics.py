"""真实CLI进程检查缓存成功、损坏、空库及环境隔离。"""
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest

ROOT=Path(__file__).resolve().parents[1]

class HubDiagnosticTests(unittest.TestCase):
    def invoke(self,directory):
        environment=os.environ.copy()
        environment['WOWBUDDY_HOME']=str(Path(directory)/'must-not-use')
        environment['WOWBUDDY_HUB_URL']='http://127.0.0.1:1/not-used'
        result=subprocess.run([sys.executable,str(ROOT/'run_dev.py'),'--hub-selftest',
            '--data-dir',str(directory)],cwd=ROOT,capture_output=True,env=environment,timeout=15)
        self.assertFalse((Path(directory)/'must-not-use').exists())
        return result,json.loads((Path(directory)/'hub-selftest.json').read_text('utf8'))

    def test_builtin_cache_and_missing_actions_reported_separately(self):
        with TemporaryDirectory() as directory:
            result,report=self.invoke(directory)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertTrue(report['cache_check_passed'])
            self.assertEqual(report['profiles'],41)
            self.assertEqual(report['profiles_with_missing_actions'],18)
            self.assertTrue(report['initial_library_seeded'])
            self.assertFalse(report['network_used'])
            self.assertNotIn('正在联网',report['status'])
            self.assertIn('PASS',(Path(directory)/'_hub.txt').read_text('utf8'))

    def test_invalid_and_empty_existing_caches_are_preserved_and_fail(self):
        empty=json.loads((ROOT/'assets/rotations.json').read_text('utf8'))
        empty['rotations']=[]
        for payload in (b'{broken',json.dumps(empty).encode('utf8')):
            with self.subTest(payload=payload[:20]),TemporaryDirectory() as directory:
                cache=Path(directory)/'hub/rotations.json'
                cache.parent.mkdir();cache.write_bytes(payload)
                result,report=self.invoke(directory)
                self.assertEqual(result.returncode,1,result.stderr)
                self.assertFalse(report['cache_check_passed'])
                self.assertFalse(report['initial_library_seeded'])
                self.assertEqual(cache.read_bytes(),payload)
                self.assertEqual(report['profiles'],0)

    def test_report_failure_does_not_pass(self):
        with TemporaryDirectory() as directory:
            (Path(directory)/'_hub.txt').mkdir()
            result,report=self.invoke(directory)
            self.assertEqual(result.returncode,1)
            self.assertFalse(report['report_written'])
            self.assertTrue(report['report_error'])

    def test_network_flag_and_conflicting_modes_rejected(self):
        for extra in ('--watch','--dump-ui'):
            result=subprocess.run([sys.executable,str(ROOT/'run_dev.py'),'--hub-selftest',extra],
                cwd=ROOT,capture_output=True,timeout=10)
            self.assertEqual(result.returncode,2)
