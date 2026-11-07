"""窗口身份接线：原始参数、显示回调和实际 Win32 自有窗口。"""
import os
import subprocess
import sys
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'desktop'))
import run_dev
from wowbuddy.window_identity import NativeWindowIdentity, TitleCache


class WindowIdentityTests(unittest.TestCase):
    def test_gui_dispatch_uses_raw_exact_flag(self):
        for raw,enabled in [(['app'],True),(['app','--no-stealth'],False),
                            (['app','--NO-STEALTH'],True),(['app','--no-stealth=true'],True),
                            (['app','-style','--no-stealth'],False)]:
            with self.subTest(raw=raw),patch.object(run_dev,'launch',return_value=0) as launch:
                self.assertEqual(run_dev.main(['app','--no-watch'],native_arguments=raw),0)
                self.assertEqual(launch.call_args.kwargs['native_identity_enabled'],enabled)

    def test_disabled_does_not_request_native_handle(self):
        window=Mock();api=Mock()
        NativeWindowIdentity(False,api=api).apply(window)
        window.winId.assert_not_called()
        self.assertEqual(api.mock_calls,[])

    def test_repeated_show_preserves_style_and_cached_title(self):
        window=Mock();window.winId.return_value=123
        api=Mock();api.get_extended_style.return_value=0x40008
        random=Mock(side_effect=[0,0,0])
        identity=NativeWindowIdentity(True,api=api,cache=TitleCache(),random_u32=random)
        identity.apply(window);identity.apply(window)
        self.assertEqual(random.call_count,3)
        api.set_extended_style.assert_called_with(123,0x40088)
        self.assertEqual([c.args for c in api.set_title.call_args_list],
                         [(123,'系统服务管理器 (1000)')]*2)

    def test_independent_window_show_hook_is_connected(self):
        from test_dev_tray import TrayTests
        calls=[]
        with patch('wowbuddy.window_identity.NativeWindowIdentity.apply',side_effect=lambda w:calls.append(w)):
            def exercise(window):
                self.assertIn(window,calls)
                self.assertEqual(window.ui.title_label.text(),'WowBuddyDev')
                window.hide();window.show()
                self.assertGreaterEqual(calls.count(window),2)
            TrayTests().run_window(False,exercise)

    @unittest.skipUnless(sys.platform=='win32','需要 Windows')
    def test_actual_win32_caption_and_style_on_owned_hidden_window(self):
        script='''
import ctypes
from ctypes import wintypes
from PySide6.QtWidgets import QApplication,QWidget
from wowbuddy.window_identity import NativeWindowIdentity,TitleCache,CtypesWindowIdentityAPI
app=QApplication([])
window=QWidget();window.setWindowTitle('WowBuddyDev test')
api=CtypesWindowIdentityAPI();hwnd=int(window.winId())
before=api.get_extended_style(hwnd)
NativeWindowIdentity(True,api=api,cache=TitleCache(),random_u32=lambda:0).apply(window)
api.user32.GetWindowTextW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
buffer=ctypes.create_unicode_buffer(256)
api.user32.GetWindowTextW(hwnd,buffer,256)
assert buffer.value=='系统服务管理器 (1000)',buffer.value
assert api.get_extended_style(hwnd)==before|0x80
assert not window.isVisible()
window.close()
'''
        env=dict(os.environ,QT_QPA_PLATFORM='windows',PYTHONPATH=str(ROOT/'desktop'))
        result=subprocess.run([sys.executable,'-c',script],cwd=ROOT,env=env,capture_output=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)


if __name__=='__main__':unittest.main()
