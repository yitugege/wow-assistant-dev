"""向本进程专用消息窗口投递按键，不激活窗口或发送全局输入。"""
import ctypes as C
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
from wowbuddy.windows_keys import CtypesWin32Backend,KeySender


def check():
    if os.name!='nt':
        raise RuntimeError('此检查需要 Windows x64')
    user=C.WinDLL('user32',use_last_error=True)
    kernel=C.WinDLL('kernel32',use_last_error=True)
    callback_type=C.WINFUNCTYPE(C.c_ssize_t,W.HWND,W.UINT,W.WPARAM,W.LPARAM)
    class WindowClass(C.Structure):
        _fields_=[('style',W.UINT),('callback',callback_type),('class_extra',C.c_int),
                  ('window_extra',C.c_int),('instance',W.HINSTANCE),('icon',W.HICON),
                  ('cursor',W.HANDLE),('background',W.HBRUSH),('menu',W.LPCWSTR),('name',W.LPCWSTR)]
    signatures={
        'DefWindowProcW':(C.c_ssize_t,[W.HWND,W.UINT,W.WPARAM,W.LPARAM]),
        'RegisterClassW':(W.WORD,[C.POINTER(WindowClass)]),
        'CreateWindowExW':(W.HWND,[W.DWORD,W.LPCWSTR,W.LPCWSTR,W.DWORD,C.c_int,C.c_int,C.c_int,C.c_int,W.HWND,W.HMENU,W.HINSTANCE,C.c_void_p]),
        'PeekMessageW':(W.BOOL,[C.POINTER(W.MSG),W.HWND,W.UINT,W.UINT,W.UINT]),
        'DispatchMessageW':(C.c_ssize_t,[C.POINTER(W.MSG)]),
        'DestroyWindow':(W.BOOL,[W.HWND]),
        'UnregisterClassW':(W.BOOL,[W.LPCWSTR,W.HINSTANCE]),
        'IsWindowVisible':(W.BOOL,[W.HWND]),
    }
    for name,(result,args) in signatures.items():
        function=getattr(user,name);function.restype=result;function.argtypes=args
    kernel.GetModuleHandleW.restype=W.HMODULE
    kernel.GetModuleHandleW.argtypes=[W.LPCWSTR]
    received=[]
    @callback_type
    def callback(hwnd,message,wparam,lparam):
        if message in (0x100,0x101):
            received.append([message,int(wparam),int(lparam)])
            return 0
        return user.DefWindowProcW(hwnd,message,wparam,lparam)
    instance=kernel.GetModuleHandleW(None)
    name=f'WowBuddyDevPostMessageAudit{os.getpid()}'
    window_class=WindowClass(0,callback,0,0,instance,None,None,None,None,name)
    if not user.RegisterClassW(C.byref(window_class)):
        raise C.WinError(C.get_last_error())
    hwnd=None
    try:
        hwnd=user.CreateWindowExW(0,name,name,0,0,0,0,0,W.HWND(-3),None,instance,None)
        if not hwnd:raise C.WinError(C.get_last_error())
        assert not user.IsWindowVisible(hwnd)
        class Backend(CtypesWin32Backend):
            def SendInput(self,events):
                raise AssertionError('后台路径不应产生全局输入')
        backend=Backend()
        sender=KeySender(backend,hwnd=int(hwnd),force_background=True,
                         allow_activation=False,interval_ms=60000,hold_ms=30)
        cases=[('NUMPAD5',[101]),('ALT-CTRL-SHIFT-NUMPADDIVIDE',[18,17,16,111]),
               ('TAB',[9]),('SHIFT-F2',[16,113]),('CTRL-0',[17,48])]
        expected=[]
        for key,codes in cases:
            assert sender.send(key,bypass_interval=True),(key,sender.status)
            expected.extend([[0x100,code,1] for code in codes])
            expected.extend([[0x101,code,0xc0000001] for code in reversed(codes)])
        # 上次成功后限速与解析失败不能再向接收端排队消息。
        assert not sender.send('NUMPAD5')
        assert '限速跳过' in sender.status
        assert not sender.send('F99',bypass_interval=True)
        message=W.MSG()
        while user.PeekMessageW(C.byref(message),hwnd,0,0,1):
            user.DispatchMessageW(C.byref(message))
        assert received==expected,{'received':received,'expected':expected}
        assert sender.success_count==len(cases)
        assert sender.failure_count==1
        user.DestroyWindow(hwnd);hwnd=None
        assert not sender.send('TAB',bypass_interval=True)
        assert sender.failure_count==2
        return {'passed':True,'backend':'CtypesWin32Backend',
                'receiver':'本进程 HWND_MESSAGE 隐藏窗口',
                'cases':[key for key,_ in cases],'received':received,
                'success_count':sender.success_count,'failure_count':sender.failure_count,
                'channel':sender.channel,'global_input_used':False,
                'game_acceptance_verified':False}
    finally:
        if hwnd:user.DestroyWindow(hwnd)
        user.UnregisterClassW(name,instance)


if __name__=='__main__':
    result=check()
    output=ROOT/'dist/win32-post-message-check.json'
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(result,ensure_ascii=True))
