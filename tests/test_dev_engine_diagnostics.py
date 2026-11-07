"""自检命令的实际报告、追加语义与错误传播。"""
import json
from pathlib import Path
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
from wowbuddy.dev_engine_diagnostics import run_engine_diagnostics

class EngineDiagnosticTests(unittest.TestCase):
    def invoke(self,directory):
        return subprocess.run([sys.executable,str(ROOT/'run_dev.py'),'--engine-selftest',
            '--data-dir',str(directory)],cwd=ROOT,capture_output=True,timeout=20)

    def test_report_counts_skips_and_append_semantics(self):
        with TemporaryDirectory() as directory:
            first=self.invoke(directory)
            self.assertEqual(first.returncode,0,first.stderr)
            path=Path(directory)/'_selftest.txt'
            content=path.read_bytes()
            report=json.loads((Path(directory)/'engine-selftest.json').read_text('utf8'))
            self.assertTrue(report['checks_passed'])
            self.assertEqual(len(report['groups']),9)
            self.assertEqual(report['skipped'],41)
            self.assertEqual(report['groups']['hub']['profile_count'],41)
            self.assertEqual(self.invoke(directory).returncode,0)
            self.assertEqual(path.read_bytes(),content+content)

    def test_invalid_cache_preserved_and_nonzero(self):
        with TemporaryDirectory() as directory:
            cache=Path(directory)/'hub/rotations.json';cache.parent.mkdir()
            cache.write_bytes(b'{broken')
            self.assertEqual(self.invoke(directory).returncode,1)
            report=json.loads((Path(directory)/'engine-selftest.json').read_text('utf8'))
            self.assertFalse(report['command_succeeded'])
            self.assertTrue(report['errors'])
            self.assertEqual(cache.read_bytes(),b'{broken')

    def test_invalid_binding_is_a_failed_check_not_report_success(self):
        with TemporaryDirectory() as directory:
            assets=Path(directory)/'assets'
            shutil.copytree(ROOT/'assets',assets)
            rules=json.loads((assets/'rules.json').read_text('utf8'))
            rules['specs']['1482']['actions'][0]['key']='INVALID_KEY'
            (assets/'rules.json').write_text(json.dumps(rules,ensure_ascii=False),'utf8')
            output=Path(directory)/'output'
            self.assertEqual(run_engine_diagnostics(assets,output),1)
            report=json.loads((output/'engine-selftest.json').read_text('utf8'))
            self.assertTrue(report['report_written'])
            self.assertFalse(report['checks_passed'])
            self.assertIn('bindings',report['failed_groups'])

    def test_report_open_failure_is_nonzero(self):
        with TemporaryDirectory() as directory:
            (Path(directory)/'_selftest.txt').mkdir()
            self.assertEqual(self.invoke(directory).returncode,1)
            report=json.loads((Path(directory)/'engine-selftest.json').read_text('utf8'))
            self.assertFalse(report['report_written'])
            self.assertTrue(report['report_error'])
