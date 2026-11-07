import sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'desktop'))
from wowbuddy.dev_startup import run_logged,record
from wowbuddy.startup_log import ROTATE_BYTES

class StartupLogTests(unittest.TestCase):
    def test_native_handlers_restore_python_hook(self):
        with tempfile.TemporaryDirectory() as tmp:
            original=sys.excepthook
            def main():
                self.assertIsNot(sys.excepthook,original)
                return 0
            self.assertEqual(run_logged(main,application=Path(tmp),arguments=['app','--data-dir',tmp]),0)
            self.assertIs(sys.excepthook,original)

    def test_crash_selection_precedes_other_commands_without_in_process_crash(self):
        for argument,target in (('--crash-test','trigger_null_write'),('--crash-test=throw','trigger_cpp_runtime_error')):
            with tempfile.TemporaryDirectory() as tmp,patch('wowbuddy.crash_diagnostics.'+target,side_effect=RuntimeError('test sentinel')) as trigger,patch('wowbuddy.dev_startup.prepare_crash_runtime') as runtime:
                with patch('builtins.print') as main:
                    code=run_logged(main,application=Path(tmp),arguments=['app','--selftest',argument,'--data-dir',tmp])
                    self.assertEqual(code,1);trigger.assert_called_once();main.assert_not_called()
                    runtime.assert_called_once()
                    text=(Path(tmp)/'startup.log').read_text('utf8')
                    expected='--crash-test：即将制造一次空指针解引用' if target=='trigger_null_write' else '--crash-test=throw：即将抛出未捕获异常'
                    self.assertIn(expected,text)

    def test_order_normal_exit_and_append(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);args=['app','--data-dir',tmp]
            def main():record('资源阶段');record('窗口阶段');return 7
            self.assertEqual(run_logged(main,application=root,arguments=args),7)
            text=(root/'startup.log').read_text('utf8')
            self.assertLess(text.index('资源阶段'),text.index('窗口阶段'))
            self.assertIn('正常退出，返回码 7',text)
            before=(root/'startup.log').stat().st_size
            self.assertEqual(run_logged(lambda:0,application=root,arguments=args),0)
            self.assertGreater((root/'startup.log').stat().st_size,before)

    def test_exception_records_traceback_without_normal_finish(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            def fail():record('规则加载中');raise ValueError('fixture error')
            self.assertEqual(run_logged(fail,application=root,arguments=['app','--data-dir='+tmp]),1)
            text=(root/'startup.log').read_text('utf8')
            self.assertIn('规则加载中',text);self.assertIn('fixture error',text)
            self.assertNotIn('正常退出',text)
            self.assertIn('ValueError',(root/'startup-error.log').read_text('utf8'))

    def test_rotation_preserves_old_log_and_closes_handle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);old=b'x'*(ROTATE_BYTES+1)
            (root/'startup.log').write_bytes(old)
            self.assertEqual(run_logged(lambda:0,application=root,arguments=['app','--data-dir',tmp]),0)
            self.assertEqual((root/'startup.log.old').read_bytes(),old)
            (root/'startup.log').rename(root/'closed.log')

    def test_log_failure_does_not_change_command_result_and_system_exit_is_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch('wowbuddy.dev_startup.open_local_startup_log',side_effect=OSError('denied')):
                self.assertEqual(run_logged(lambda:12,application=Path(tmp),arguments=['app']),12)
            def exit_command():raise SystemExit(2)
            self.assertEqual(run_logged(exit_command,application=Path(tmp),arguments=['app','--data-dir',tmp]),2)
            self.assertIn('返回码 2',(Path(tmp)/'startup.log').read_text('utf8'))

if __name__=='__main__':unittest.main()
