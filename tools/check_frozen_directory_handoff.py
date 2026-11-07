"""两个实际构建间的冻结交接测试；隔离目录、自有Job，不替换用户客户端。"""
import ctypes as C
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'desktop'))
from tools.build_client_release import build_client
from tools.check_frozen_outer import run
from tools.check_outer_gui import close_owned_main
from wowbuddy.github_outer import read_payload
from wowbuddy.packages import read_bundle
from wowbuddy.launcher import BUSINESS_EXE
from wowbuddy.release_identity import file_sha256,read_release_identity
from wowbuddy.dev_client_update import stage_update,EXE
from wowbuddy.dev_update_handoff import prepare_handoff
from wowbuddy.game_windows import CtypesWindowBackend


def check():
    from PySide6.QtCore import QSettings
    previous=ROOT/'dist/local-6bb86ed/WowBuddyDev-Outer.exe'
    source=ROOT/'dist/desktop/WowBuddyDev'
    old=read_release_identity(previous)
    build=json.loads((source/'build-manifest.json').read_text('utf8'))
    assert build['passed'] and file_sha256(source/EXE)==build['executable_sha256']
    assert old.business_sha256!=build['executable_sha256']
    root=Path(tempfile.mkdtemp(prefix='frozen-directory-handoff-',dir=ROOT/'.local')).resolve()
    current=root/'client';current.mkdir()
    for member in read_bundle(read_payload(previous)):
        path=current/(EXE if member.name==BUSINESS_EXE else member.name)
        assert path.resolve().is_relative_to(root)
        path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(member.data)
    assert file_sha256(current/EXE)==old.business_sha256
    stable=current/'.local';stable.mkdir(exist_ok=True)
    (stable/'sentinel.txt').write_text('目录更新保留此数据','utf8')
    settings=QSettings(str(stable/'settings.ini'),QSettings.IniFormat)
    settings.setValue('audit/sentinel','frozen-handoff-preserved')
    settings.setValue('update/autoCheck',False);settings.sync();del settings
    package=root/'client.zip';manifest=build_client(source,package,'0.2.8')
    staged=stage_update(package,package.with_suffix('.manifest.json'),root/'updates')
    backend=CtypesWindowBackend();handoff=None;closed=[];parent_pid=None
    k=C.WinDLL('kernel32',use_last_error=True)
    k.OpenProcess.argtypes=[W.DWORD,W.BOOL,W.DWORD];k.OpenProcess.restype=W.HANDLE
    k.AssignProcessToJobObject.argtypes=[W.HANDLE,W.HANDLE];k.AssignProcessToJobObject.restype=W.BOOL
    k.IsProcessInJob.argtypes=[W.HANDLE,W.HANDLE,C.POINTER(W.BOOL)];k.IsProcessInJob.restype=W.BOOL
    k.CloseHandle.argtypes=[W.HANDLE]
    def observe(job):
        nonlocal handoff,parent_pid
        if closed:return
        if handoff is None:
            candidates=[]
            def visit(hwnd):
                if backend.window_title(hwnd).text!='WowBuddyDev — 独立开发版':return
                pid=backend.window_pid(hwnd)
                if Path(backend.process_path(pid))==current/EXE:candidates.append(pid)
            backend.enum_windows(visit)
            if not candidates:return
            assert len(set(candidates))==1
            parent_pid=candidates[0]
            handle=k.OpenProcess(0x1000,False,parent_pid)
            if not handle:raise C.WinError(C.get_last_error())
            try:
                admitted=W.BOOL()
                assert k.IsProcessInJob(handle,job,C.byref(admitted)) and admitted.value
            finally:k.CloseHandle(handle)
            handoff=prepare_handoff(staged,current,['--desktop-selftest','--no-watch','--no-update'],parent_pid=parent_pid)
            handle=k.OpenProcess(0x100|0x1|0x1000,False,handoff['pid'])
            if not handle:raise C.WinError(C.get_last_error())
            try:
                if not k.AssignProcessToJobObject(job,handle):
                    handoff['process'].terminate();handoff['process'].wait(timeout=5)
                    raise C.WinError(C.get_last_error())
            finally:k.CloseHandle(handle)
        if Path(handoff['job']).with_suffix('.ready.json').is_file():
            closed.extend(close_owned_main(job))
            assert closed==[parent_pid]
    env=dict(os.environ,WOWBUDDY_NO_GAME_SCAN='1',PYINSTALLER_RESET_ENVIRONMENT='1',
             HTTP_PROXY='http://127.0.0.1:1',HTTPS_PROXY='http://127.0.0.1:1',ALL_PROXY='http://127.0.0.1:1',NO_PROXY='')
    env.pop('WOWBUDDY_EXE',None);env.pop('WOWBUDDY_HOME',None)
    with patch.dict(os.environ,env,clear=True):
        outcome=run(current/EXE,current,env,arguments=['--no-watch','--no-update','--no-stealth'],
                    on_running=observe,timeout_seconds=180)
    assert handoff and closed
    result=json.loads(Path(handoff['job']).with_suffix('.result.json').read_text('utf8'))
    assert result['ok'] and result['replaced'] and result['restarted'],result
    assert handoff['process'].wait(timeout=5)==0
    assert file_sha256(current/EXE)==build['executable_sha256']
    backup=Path(result['backup']);assert backup.is_relative_to(root)
    assert file_sha256(backup/EXE)==old.business_sha256
    assert (current/'.local/sentinel.txt').read_text('utf8')=='目录更新保留此数据'
    settings=QSettings(str(current/'.local/settings.ini'),QSettings.IniFormat)
    assert settings.value('audit/sentinel')=='frozen-handoff-preserved'
    assert settings.value('update/autoCheck',True,type=bool) is False
    del settings
    report=json.loads((current/'desktop-selftest.json').read_text('utf8'))
    assert report['passed'] and report['frozen'] and report['window_closed']
    assert Path(report['assets'])==current/'_internal/assets'
    assert (current/'desktop-selftest.json').stat().st_mtime_ns>Path(handoff['job']).with_suffix('.ready.json').stat().st_mtime_ns
    for name,digest in manifest['members'].items():
        relative=Path(name).relative_to('WowBuddyDev')
        if relative.as_posix()=='desktop-selftest.json':continue
        assert file_sha256(current/relative)==digest,name
    assert outcome['processes_observed']>=3 and outcome['job_active_at_end']==0
    return {'passed':True,'root':str(root),'previous_business_sha256':old.business_sha256,
            'new_business_sha256':build['executable_sha256'],'parent_pid':parent_pid,
            'handoff_result':result,'handoff_job':handoff['job'],'job':outcome,'settings_data_preserved':True,
            'new_report_origin_verified':True,'installed_members_verified':len(manifest['members'])-1,
            'scope':'真实冻结父进程、交接进程、目录替换和新EXE自检；本地包，宿主触发prepare_handoff',
            'manual_button_verified':False,'github_download_verified':False,'game_verified':False}


if __name__=='__main__':
    result=check()
    (ROOT/'dist/frozen-directory-handoff.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(result,ensure_ascii=True))
