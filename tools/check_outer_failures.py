"""冻结外层故障注入及真实MessageBox文本/退出码验证，仅操作自建Job。"""
import ctypes as C
from ctypes import wintypes as W
import json,os,re,shutil,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'desktop'))
from tools.check_frozen_outer import run
from wowbuddy.launcher import release_directory,BUSINESS_EXE
from wowbuddy.release_identity import read_release_identity,CACHE_NAMESPACE,file_sha256
from wowbuddy.dev_outer_entry import ERROR_TITLE,PROJECT_URL


def dismiss_owned_error(job):
    user=C.WinDLL('user32',use_last_error=True);kernel=C.WinDLL('kernel32',use_last_error=True)
    callback=C.WINFUNCTYPE(W.BOOL,W.HWND,W.LPARAM)
    user.EnumWindows.argtypes=[callback,W.LPARAM];user.EnumWindows.restype=W.BOOL
    user.EnumChildWindows.argtypes=[W.HWND,callback,W.LPARAM];user.EnumChildWindows.restype=W.BOOL
    user.GetWindowThreadProcessId.argtypes=[W.HWND,C.POINTER(W.DWORD)]
    user.GetWindowTextW.argtypes=[W.HWND,W.LPWSTR,C.c_int]
    user.GetClassNameW.argtypes=[W.HWND,W.LPWSTR,C.c_int]
    user.PostMessageW.argtypes=[W.HWND,W.UINT,W.WPARAM,W.LPARAM];user.PostMessageW.restype=W.BOOL
    user.SendMessageTimeoutW.argtypes=[W.HWND,W.UINT,W.WPARAM,W.LPARAM,W.UINT,W.UINT,C.POINTER(C.c_size_t)]
    user.SendMessageTimeoutW.restype=W.LPARAM
    kernel.OpenProcess.argtypes=[W.DWORD,W.BOOL,W.DWORD];kernel.OpenProcess.restype=W.HANDLE
    kernel.IsProcessInJob.argtypes=[W.HANDLE,W.HANDLE,C.POINTER(W.BOOL)];kernel.IsProcessInJob.restype=W.BOOL
    kernel.CloseHandle.argtypes=[W.HANDLE]
    records=[]
    def text(hwnd,reader=user.GetWindowTextW):
        buffer=C.create_unicode_buffer(4096);reader(hwnd,buffer,len(buffer));return buffer.value
    @callback
    def visit(hwnd,unused):
        title=text(hwnd);kind=text(hwnd,user.GetClassNameW)
        if title!=ERROR_TITLE or kind!='#32770':return True
        pid=W.DWORD();user.GetWindowThreadProcessId(hwnd,C.byref(pid))
        process=kernel.OpenProcess(0x1000,False,pid.value)
        if not process:return True
        try:
            owned=W.BOOL()
            queried=kernel.IsProcessInJob(process,job,C.byref(owned))
            if not queried or not owned.value:return True
            children=[]
            @callback
            def child(handle,unused):
                buffer=C.create_unicode_buffer(4096);result=C.c_size_t()
                if user.SendMessageTimeoutW(handle,0xD,len(buffer),C.addressof(buffer),2,200,C.byref(result)):
                    children.append(buffer.value)
                return True
            user.EnumChildWindows(hwnd,child,0)
            body='\n'.join(children)
            if PROJECT_URL not in body:return True
            if user.PostMessageW(hwnd,0x10,0,0): # WM_CLOSE，仅指定所属Job的错误对话框
                records.append({'pid':pid.value,'hwnd':hwnd,'title':ERROR_TITLE,'text':body})
        finally:kernel.CloseHandle(process)
        return True
    user.EnumWindows(visit,0)
    return records


def check():
    source=ROOT/'dist/outer/WowBuddyDev-Outer.exe'
    build=json.loads((source.parent/'build-manifest.json').read_text('utf8'))
    assert file_sha256(source)==build['sha256']
    root=Path(tempfile.mkdtemp(prefix='outer-failures-',dir=ROOT/'.local')).resolve()
    target=root/'测试外层.exe';shutil.copy2(source,target)
    identity=read_release_identity(target);cases=[]
    for label,code,required in [('initialize',1,'启动初始化失败'),('extract',2,'解包失败'),('create_process',3,'错误码 ')]:
        local=root/label;local.mkdir()
        cache=Path(release_directory(str(local/CACHE_NAMESPACE/identity.cache_key),None))
        if label=='initialize':(local/CACHE_NAMESPACE).write_text('阻止建立目录','utf8')
        else:
            cache.mkdir(parents=True)
            if label=='extract':(cache/BUSINESS_EXE).mkdir()
            else:
                (cache/BUSINESS_EXE).write_bytes(b'not an executable')
                (cache/'.ready').write_text('fixture')
        dialogs=[]
        def observe(job):
            if not dialogs:dialogs.extend(dismiss_owned_error(job))
        env=dict(os.environ,LOCALAPPDATA=str(local),PYINSTALLER_RESET_ENVIRONMENT='1')
        outcome=run(target,root,env,arguments=['--no-watch','--no-update'],on_running=observe,expected_exit=code)
        assert len(dialogs)==1,dialogs
        body=dialogs[0]['text']
        assert required in body and PROJECT_URL in body and 'wowbuddy.cn' not in body,body
        if label=='create_process':assert re.search(r'错误码 (193|216)\b',body),body
        if label!='initialize':assert str(cache) in body
        assert outcome['processes_observed']==2,'失败路径不应启动业务子进程'
        cases.append({'scenario':label,'passed':True,'dialog':dialogs[0],**outcome})
    return {'passed':True,'outer_sha256':build['sha256'],'test_root':str(root),'cases':cases,
        'scope':'真实冻结外层、Win32对话框文本、定向关闭及退出码；未评价视觉排版或全部异常'}


if __name__=='__main__':
    report=check()
    (ROOT/'dist/outer-failures-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(report,ensure_ascii=True))
