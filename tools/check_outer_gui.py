"""冻结外层正常GUI、稳定INI和清理联测；不监控游戏，退出限于自建Job。"""
import ctypes as C
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'desktop'))
from tools.check_frozen_outer import run
from wowbuddy.launcher import release_directory,BUSINESS_EXE
from wowbuddy.release_identity import read_release_identity,CACHE_NAMESPACE,file_sha256


def close_owned_main(job):
    """仅关闭所属Job且标题匹配的主窗，不按全局标题误关用户现有助手。"""
    user=C.WinDLL('user32',use_last_error=True);kernel=C.WinDLL('kernel32',use_last_error=True)
    callback_type=C.WINFUNCTYPE(W.BOOL,W.HWND,W.LPARAM)
    user.EnumWindows.argtypes=[callback_type,W.LPARAM];user.EnumWindows.restype=W.BOOL
    user.GetWindowThreadProcessId.argtypes=[W.HWND,C.POINTER(W.DWORD)]
    user.GetWindowThreadProcessId.restype=W.DWORD
    user.GetWindowTextW.argtypes=[W.HWND,W.LPWSTR,C.c_int];user.GetWindowTextW.restype=C.c_int
    user.PostMessageW.argtypes=[W.HWND,W.UINT,W.WPARAM,W.LPARAM];user.PostMessageW.restype=W.BOOL
    kernel.OpenProcess.argtypes=[W.DWORD,W.BOOL,W.DWORD];kernel.OpenProcess.restype=W.HANDLE
    kernel.IsProcessInJob.argtypes=[W.HANDLE,W.HANDLE,C.POINTER(W.BOOL)];kernel.IsProcessInJob.restype=W.BOOL
    kernel.CloseHandle.argtypes=[W.HANDLE];kernel.CloseHandle.restype=W.BOOL
    closed=[]
    @callback_type
    def visit(hwnd,unused):
        pid=W.DWORD();user.GetWindowThreadProcessId(hwnd,C.byref(pid))
        handle=kernel.OpenProcess(0x1000,False,pid.value)
        if not handle:return True
        try:
            admitted=W.BOOL()
            if not kernel.IsProcessInJob(handle,job,C.byref(admitted)) or not admitted.value:return True
            title=C.create_unicode_buffer(256);user.GetWindowTextW(hwnd,title,256)
            if title.value=='WowBuddyDev — 独立开发版':
                if user.PostMessageW(hwnd,0x10,0,0):closed.append(pid.value)
        finally:kernel.CloseHandle(handle)
        return True
    user.EnumWindows(visit,0)
    return closed


def check():
    from PySide6.QtCore import QSettings
    source=ROOT/'dist/outer/WowBuddyDev-Outer.exe'
    build=json.loads((source.parent/'build-manifest.json').read_text('utf8'))
    assert file_sha256(source)==build['sha256']
    root=Path(tempfile.mkdtemp(prefix='outer-gui-',dir=ROOT/'.local')).resolve()
    outer=root/'测试外层.exe';shutil.copy2(source,outer)
    identity=read_release_identity(outer)
    local=root/'localappdata';local.mkdir()
    cache=Path(release_directory(str(local/CACHE_NAMESPACE/identity.cache_key),None))
    stable=root/'.local';stable.mkdir()
    ini=stable/'settings.ini'
    settings=QSettings(str(ini),QSettings.IniFormat)
    settings.setValue('update/autoCheck',False)
    settings.setValue('audit/sentinel','两次启动保留');settings.sync();del settings
    env=dict(os.environ,LOCALAPPDATA=str(local),PYINSTALLER_RESET_ENVIRONMENT='1',QT_QPA_PLATFORM='windows')
    # 正常GUI仍有循环库/插件联网路径；为支持代理变量的传输设置不可用本地代理。
    # Qt/系统代理策略另有来源，不能据此宣称测试完全没有网络访问。
    env.update(HTTP_PROXY='http://127.0.0.1:1',HTTPS_PROXY='http://127.0.0.1:1',ALL_PROXY='http://127.0.0.1:1',NO_PROXY='')
    cases=[]
    for index in range(2):
        old=cache.parent/f'app-audit-old-{index}';old.mkdir(parents=True)
        (old/'fixture.txt').write_text('old')
        unrelated=cache.parent/'keep';unrelated.mkdir(exist_ok=True)
        report_path=cache/'_ui.txt';report_path.unlink(missing_ok=True)
        closed=[]
        def observe(job):
            if closed or not report_path.exists():return
            text=report_path.read_text('utf8')
            if 'WowBuddyDev' not in text or '开始监控' not in text:return
            closed.extend(close_owned_main(job))
        outcome=run(outer,root,env,arguments=['--dump-ui','--no-watch','--no-update','--no-stealth'],on_running=observe)
        assert closed,'未通过自有窗口WM_CLOSE结束'
        assert not old.exists() and unrelated.is_dir() and (cache/BUSINESS_EXE).is_file()
        settings=QSettings(str(ini),QSettings.IniFormat)
        assert settings.value('audit/sentinel')=='两次启动保留'
        assert settings.value('update/autoCheck',True,type=bool) is False
        del settings
        log=(stable/'startup.log').read_text('utf8')
        assert '已清理旧解包目录 1 个' in log
        assert '正常退出，返回码 0' in log
        assert not (cache/'.local/settings.ini').exists()
        assert not list(stable.glob('logs/monitor_*.log'))
        cases.append({'run':index+1,'passed':True,'closed_job_pids':closed,'old_cache_removed':True,'stable_ini_preserved':True,**outcome})
    return {'passed':True,'outer_sha256':build['sha256'],'test_root':str(root),'cases':cases,
            'monitoring_requested':False,'online_update_verified':False,'game_verified':False}


if __name__=='__main__':
    report=check()
    (ROOT/'dist/outer-gui-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(report,ensure_ascii=True))
