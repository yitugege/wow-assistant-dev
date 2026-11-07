"""独立外层错误提示：保留原核心结果，初始化异常单独报告。"""
from pathlib import Path
import os,sys,unittest
from unittest.mock import Mock,patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
from wowbuddy import dev_outer_entry as entry
from wowbuddy.launcher import LauncherResult


class OuterEntryTests(unittest.TestCase):
    def setUp(self):
        environment=patch.dict(os.environ,{})
        environment.start();self.addCleanup(environment.stop)

    def test_original_failure_codes_keep_reason_and_cache_but_use_own_identity(self):
        for code in (0,2,3):
            with self.subTest(code=code):
                result=LauncherResult(code,'D:/测试缓存',False,(),None,'测试原因 错误码 5')
                api=Mock()
                with patch.object(sys,'frozen',True,create=True),patch.object(entry,'SourceReleaseAPI',return_value=api),\
                     patch.object(entry,'WindowsLauncherFiles'),patch.object(entry,'WindowsLauncherProcess'),\
                     patch.object(entry,'launch_host',return_value=result) as host:
                    self.assertEqual(entry.main(),code)
                    self.assertFalse(host.call_args.kwargs['show_errors'])
                if code==0:api.message_box.assert_not_called();continue
                args=api.message_box.call_args.args
                self.assertEqual((args[0],args[2],args[3]),(None,entry.ERROR_TITLE,0x10))
                self.assertIn('测试原因 错误码 5',args[1]);self.assertIn(entry.PROJECT_URL,args[1])
                self.assertNotIn('wowbuddy.cn',args[1])
                if code==2:self.assertIn('缓存目录：\nD:/测试缓存',args[1])
                # 保留原核心格式用于对照，不修改其旧官网常量。
                self.assertIn('wowbuddy.cn',result.dialog_text)

    def test_identity_and_cache_errors_have_visible_report_and_never_launch(self):
        for phase in ('identity','cache'):
            with self.subTest(phase=phase):
                api=Mock();fallback=Mock()
                if phase=='cache':api.cache_root.mkdir.side_effect=PermissionError('缓存不可写')
                with patch.object(sys,'frozen',True,create=True),\
                     patch.object(entry,'SourceReleaseAPI',side_effect=ValueError('资源203损坏') if phase=='identity' else None,return_value=api),\
                     patch.object(entry,'WindowsHostAPI',return_value=fallback),patch.object(entry,'launch_host') as host:
                    self.assertEqual(entry.main(),1);host.assert_not_called()
                dialog=fallback if phase=='identity' else api
                self.assertIn('启动初始化失败',dialog.message_box.call_args.args[1])
                self.assertIn(entry.PROJECT_URL,dialog.message_box.call_args.args[1])

    def test_source_entry_does_not_create_windows_backends(self):
        with patch.object(sys,'frozen',False,create=True),patch.object(entry,'SourceReleaseAPI') as api:
            with self.assertRaises(RuntimeError):entry.main()
            api.assert_not_called()


if __name__=='__main__':unittest.main()
