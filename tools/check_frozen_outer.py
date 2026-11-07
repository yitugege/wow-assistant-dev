"""实际冻结外层联测；自建Job约束生命周期，所有文件位于隔离目录。"""
import ctypes as C
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
from wowbuddy.launcher import ChildLaunch,WindowsLauncherProcess,release_directory,BUSINESS_EXE
from wowbuddy.release_identity import read_release_identity,CACHE_NAMESPACE,file_sha256


def run(target,root,environment,*,arguments=None,on_running=None,expected_exit=0):
    backend=WindowsLauncherProcess();k=backend.k
    class Accounting(C.Structure):
        _fields_=[('user',C.c_int64),('kernel',C.c_int64),('period_user',C.c_int64),('period_kernel',C.c_int64),
                  ('faults',W.DWORD),('total',W.DWORD),('active',W.DWORD),('terminated',W.DWORD)]
    k.QueryInformationJobObject.argtypes=[W.HANDLE,C.c_int,C.c_void_p,W.DWORD,C.POINTER(W.DWORD)]
    k.QueryInformationJobObject.restype=W.BOOL
    job=k.CreateJobObjectW(None,None)
    if not job:raise C.WinError(C.get_last_error())
    process=None
    def count():
        info=Accounting()
        if not k.QueryInformationJobObject(job,1,C.byref(info),C.sizeof(info),None):raise C.WinError(C.get_last_error())
        return info.active,info.total
    try:
        arguments=['--desktop-selftest'] if arguments is None else list(arguments)
        request=ChildLaunch(str(target),subprocess.list2cmdline([str(target),*arguments]),str(root),environment,creation_flags=4)
        process=backend.create(request)
        if not k.AssignProcessToJobObject(job,process.process):raise C.WinError(C.get_last_error())
        if k.ResumeThread(process.thread)==0xffffffff:raise C.WinError(C.get_last_error())
        deadline=time.monotonic()+45;early=False
        while True:
            active,total=count()
            if k.WaitForSingleObject(process.process,0)==0 and active:early=True
            if not active:break
            if on_running is not None:on_running(job)
            if time.monotonic()>=deadline:raise TimeoutError('冻结外层Job未按时退出')
            time.sleep(0.025)
        code=W.DWORD()
        if not k.GetExitCodeProcess(process.process,C.byref(code)):raise C.WinError(C.get_last_error())
        assert code.value==expected_exit,(code.value,expected_exit)
        return {'outer_exit':code.value,'processes_observed':total,'job_active_at_end':active,'outer_exited_before_job_empty':early}
    finally:
        k.TerminateJobObject(job,1)
        if process:
            if k.WaitForSingleObject(process.process,0)!=0:k.TerminateProcess(process.process,1)
            k.WaitForSingleObject(process.process,5000)
            backend.close_thread(process);backend.close_process(process)
        deadline=time.monotonic()+5
        while count()[0] and time.monotonic()<deadline:time.sleep(0.025)
        remaining=count()[0];k.CloseHandle(job)
        if remaining:raise RuntimeError('测试Job仍有活动进程')


def check():
    source=ROOT/'dist/outer/WowBuddyDev-Outer.exe'
    build=json.loads((source.parent/'build-manifest.json').read_text('utf8'))
    assert file_sha256(source)==build['sha256']
    root=Path(tempfile.mkdtemp(prefix='frozen-outer-中文 & ',dir=ROOT/'.local')).resolve()
    target=root/'独立 外层 & 测试.exe';shutil.copy2(source,target)
    identity=read_release_identity(target)
    local=root/'localappdata';local.mkdir()
    cache=Path(release_directory(str(local/CACHE_NAMESPACE/identity.cache_key),None))
    env=dict(os.environ,LOCALAPPDATA=str(local),WOWBUDDY_HOME='stale home',WOWBUDDY_EXE='stale exe',PYINSTALLER_RESET_ENVIRONMENT='1')
    cases=[]
    for index,label in enumerate(('first_extract','reuse','missing_ready')):
        if index==1:
            (cache/'build-manifest.json').write_bytes(b'sentinel')
            (cache/'.ready').write_bytes(b'sentinel')
        if index==2:
            ready=(cache/'.ready').resolve();assert ready.is_relative_to(root);ready.unlink()
        if index:(cache/'desktop-selftest.json').unlink(missing_ok=True)
        outcome=run(target,root,env)
        report=json.loads((cache/'desktop-selftest.json').read_text('utf8'))
        assert report['passed'] and report['frozen'] and report['network_clients_absent']
        assert not report['real_system_backends_created'] and not report['monitor_active']
        assert file_sha256(cache/BUSINESS_EXE)==identity.business_sha256
        assert (root/'.local/startup.log').is_file()
        assert not (cache/'.local/startup.log').exists()
        if index==1:
            assert (cache/'.ready').read_bytes()==b'sentinel'
            assert (cache/'build-manifest.json').read_bytes()==b'sentinel'
        else:
            for name,digest in build['members'].items():
                if name=='desktop-selftest.json':continue
                assert file_sha256(cache/name)==digest,name
        cases.append({'scenario':label,'passed':True,**outcome})
    return {'passed':True,'outer_sha256':build['sha256'],'test_root':str(root),'cache':str(cache),
            'cases':cases,'stable_startup_log_verified':True,'normal_gui_verified':False,'online_update_verified':False}


if __name__=='__main__':
    result=check()
    (ROOT/'dist/frozen-outer-check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(result,ensure_ascii=True))
