"""向本进程专用消息窗口投递按键，不激活窗口或发送全局输入。"""
import ctypes as C
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import sys
import time
from dataclasses import asdict

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
from wowbuddy.windows_keys import CtypesWin32Backend,KeySender
from wowbuddy.dispatch import ActionDispatcher
from wowbuddy.candidates import Candidate
from wowbuddy.keybindings import parse_keybinding


def check(*, all_registered=False):
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
            def __init__(self):
                super().__init__()
                self.SetForegroundWindow=self.reject_activation
            def SendInput(self,events):
                raise AssertionError('后台路径不应产生全局输入')
            def reject_activation(self,handle):
                raise AssertionError('后台路径不应激活窗口')
        backend=Backend()
        sender=KeySender(backend,hwnd=int(hwnd),force_background=True,
                         allow_activation=False,interval_ms=60000,hold_ms=30)
        cases=[('NUMPAD5',[101]),('ALT-CTRL-SHIFT-NUMPADDIVIDE',[18,17,16,111]),
               ('TAB',[9]),('SHIFT-F2',[16,113]),('CTRL-0',[17,48])]
        registered=[]
        invalid=[]
        if all_registered:
            for resource in ('rules.json','rules_readable.json'):
                rules=json.loads((ROOT/'assets'/resource).read_text('utf8'))
                for spec,definition in rules['specs'].items():
                    for action in definition['actions']:
                        binding=parse_keybinding(action['key'])
                        if not binding.valid:
                            invalid.append({'resource':resource,'spec':spec,'action':action['name'],
                                            'key':action['key'],'error':binding.error})
                            continue
                        codes=[*binding.modifiers,binding.vk]
                        registered.append({'resource':resource,'spec':spec,'action':action['name'],
                                           'key':action['key'],'codes':codes})
                        cases.append((action['key'],codes))
        expected=[]
        for key,codes in cases:
            assert sender.send(key,bypass_interval=True),(key,sender.status)
            expected.extend([[0x100,code,1] for code in codes])
            expected.extend([[0x101,code,0xc0000001] for code in reversed(codes)])
        # 上次成功后限速与解析失败不能再向接收端排队消息。
        assert not sender.send('NUMPAD5')
        assert '限速跳过' in sender.status
        assert not sender.send('F99',bypass_interval=True)
        for entry in invalid:
            assert not sender.send(entry['key'],bypass_interval=True),entry
            assert sender.status==entry['error'],entry
        message=W.MSG()
        while user.PeekMessageW(C.byref(message),hwnd,0,0,1):
            user.DispatchMessageW(C.byref(message))
        assert received==expected,{'received':received,'expected':expected}
        assert sender.success_count==len(cases)
        assert sender.failure_count==1+len(invalid)
        basic_received=list(received)
        dispatch_cases=[]
        class DispatchBackend(Backend):
            def __init__(self):
                super().__init__();self.sleeps=[];self.posts=[]
                self.native_sleep=self.Sleep;self.native_post=self.PostMessageW
                self.Sleep=self.record_sleep;self.PostMessageW=self.record_post
            def record_sleep(self,milliseconds):
                self.sleeps.append(milliseconds)
                return self.native_sleep(milliseconds)
            def record_post(self,handle,message,key,value):
                self.posts.append((message,key,time.perf_counter()))
                return self.native_post(handle,message,key,value)
        for label,pre,known in [('focus_then_heal','CTRL-F2',False),
                                ('confirmed_focus','CTRL-F2',True),('invalid_pre_still_heals','INVALID-KEY',False)]:
            received.clear();dispatch_backend=DispatchBackend()
            channel=KeySender(dispatch_backend,hwnd=int(hwnd),hold_ms=100,
                              force_background=True,allow_activation=False,interval_ms=30)
            dispatcher=ActionDispatcher(channel)
            candidate=Candidate(action='heal_fixture',key='F1',pre_key=pre,pre_action='focus_party1',
                                hold_ms=30000,expect_off=('renew',))
            result=dispatcher.dispatch(candidate,hwnd=int(hwnd),fields={'player_succeeded_generation':'8'},
                                       focus_known=known,observed_focus=1 if known else -1)
            while user.PeekMessageW(C.byref(message),hwnd,0,0,1):user.DispatchMessageW(C.byref(message))
            wanted=([[0x100,17,1],[0x100,113,1],[0x101,113,0xc0000001],[0x101,17,0xc0000001]]
                    if label=='focus_then_heal' else [])+[[0x100,112,1],[0x101,112,0xc0000001]]
            assert result.success and received==wanted,(label,asdict(result),received)
            assert dispatcher.state.success_count==1
            assert dispatcher.state.auras.sent_generation['heal_fixture']==8
            assert dispatcher.state.local_gcd_until_ms==result.sent_at_ms+1500
            assert channel.force_background and not channel.allow_activation
            wait_gap=None
            if label=='focus_then_heal':
                assert result.pre_success and not result.pre_skipped
                assert dispatch_backend.sleeps==[10,40,10]
                wait_gap=(dispatch_backend.posts[4][2]-dispatch_backend.posts[3][2])*1000
                assert wait_gap>=35,wait_gap
                assert channel.success_count==2
            else:
                assert dispatch_backend.sleeps==[10]
                assert result.pre_skipped==known
                assert result.pre_success is (None if known else False)
                assert channel.success_count==1
            dispatch_cases.append({'case':label,'result':asdict(result),'received':list(received),
                'sleep_requests_ms':dispatch_backend.sleeps,'pre_up_to_main_down_ms':wait_gap})
        user.DestroyWindow(hwnd);hwnd=None
        assert not sender.send('TAB',bypass_interval=True)
        assert sender.failure_count==2+len(invalid)
        return {'passed':True,'backend':'CtypesWin32Backend',
                'receiver':'本进程 HWND_MESSAGE 隐藏窗口',
                'cases':[key for key,_ in cases],'received':basic_received,'dispatch_cases':dispatch_cases,
                'registered_actions':registered,
                'invalid_registered_actions':invalid,
                'success_count':sender.success_count,'failure_count':sender.failure_count,
                'channel':sender.channel,'global_input_used':False,
                'game_acceptance_verified':False}
    finally:
        if hwnd:user.DestroyWindow(hwnd)
        user.UnregisterClassW(name,instance)


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--all-registered',action='store_true',help='逐条投递两套资源的全部注册动作键，仅到自有隐藏窗口')
    args=parser.parse_args()
    result=check(all_registered=args.all_registered)
    output=ROOT/('dist/win32-post-message-all-registered.json' if args.all_registered
                 else 'dist/win32-post-message-check.json')
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(result,ensure_ascii=True))
