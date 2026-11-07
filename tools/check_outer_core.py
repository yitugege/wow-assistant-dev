"""原外层核心真实释放当前独立客户端，再运行隔离副本离屏自检。"""
import ctypes as C
from ctypes import wintypes as W
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
from wowbuddy.launcher import (BUSINESS_EXE,LauncherContext,WindowsLauncherFiles,
                               WindowsLauncherProcess,launch_core)
from wowbuddy.packages import Member,write_bundle,read_bundle


class ObservedProcess(WindowsLauncherProcess):
    """复制观察句柄；核心仍照常关闭原始线程和进程句柄。"""
    def __init__(self):
        super().__init__()
        self.handle=None
        self.closed=[]
        self.k.GetCurrentProcess.argtypes=[];self.k.GetCurrentProcess.restype=W.HANDLE
        self.k.DuplicateHandle.argtypes=[W.HANDLE,W.HANDLE,W.HANDLE,C.POINTER(W.HANDLE),W.DWORD,W.BOOL,W.DWORD]
        self.k.DuplicateHandle.restype=W.BOOL
    def create(self,request):
        process=super().create(request)
        copy=W.HANDLE();current=self.k.GetCurrentProcess()
        if not self.k.DuplicateHandle(current,process.process,current,C.byref(copy),0,False,2):
            self.k.TerminateProcess(process.process,1)
            super().close_thread(process);super().close_process(process)
            raise C.WinError(C.get_last_error())
        self.handle=copy
        return process
    def close_thread(self,process):
        super().close_thread(process);self.closed.append('thread')
    def close_process(self,process):
        super().close_process(process);self.closed.append('process')
    def finish(self):
        if self.k.WaitForSingleObject(self.handle,30000)!=0:
            raise TimeoutError('隔离业务自检30秒内未退出')
        code=W.DWORD()
        if not self.k.GetExitCodeProcess(self.handle,C.byref(code)):raise C.WinError(C.get_last_error())
        return code.value
    def close(self):
        if self.handle:
            if self.k.WaitForSingleObject(self.handle,0)!=0:
                self.k.TerminateProcess(self.handle,1)
                self.k.WaitForSingleObject(self.handle,5000)
            self.k.CloseHandle(self.handle);self.handle=None


def check():
    source=ROOT/'dist/desktop/WowBuddyDev'
    manifest=json.loads((source/'build-manifest.json').read_text('utf8'))
    digest=lambda path:hashlib.sha256(path.read_bytes()).hexdigest()
    if not manifest['passed'] or digest(source/'WowBuddyDev.exe')!=manifest['executable_sha256']:
        raise ValueError('需要已通过构建验证的客户端')
    for name,value in manifest['source_files'].items():
        if digest(ROOT/name)!=value:raise ValueError('源码改变，须重新构建：'+name)
    members=[]
    for path in sorted(source.rglob('*')):
        relative=path.relative_to(source)
        if '.local' in relative.parts:continue
        if path.is_symlink() or path.is_junction():raise ValueError('构建输入包含链接')
        if path.is_file():members.append(Member(BUSINESS_EXE if relative.as_posix()=='WowBuddyDev.exe' else relative.as_posix(),path.read_bytes()))
    payload=write_bundle(members)
    assert read_bundle(payload)==members
    root=Path(tempfile.mkdtemp(prefix='outer-core-中文 & ',dir=ROOT/'.local')).resolve()
    context=LauncherContext(str(root/'外层测试.exe'),
        '"'+str(root/'外层测试.exe')+'" --desktop-selftest',str(root),None,
        dict(os.environ,PYINSTALLER_RESET_ENVIRONMENT='1'))
    filesystem=WindowsLauncherFiles(root)
    scenarios=[]
    cache=None
    for index,label in enumerate(('first_extract','reuse_existing','missing_ready_reextract')):
        if index==1:
            (cache/'build-manifest.json').write_bytes(b'cache sentinel')
            (cache/'.ready').write_bytes(b'not the build id')
        if index==2:
            target=(cache/'.ready').resolve()
            assert target.is_relative_to(root)
            target.unlink()
        if cache is not None:(cache/'desktop-selftest.json').unlink(missing_ok=True)
        process=ObservedProcess()
        try:
            result=launch_core(context,payload,filesystem=filesystem,process=process)
            assert result.exit_code==0,result
            alive=process.k.WaitForSingleObject(process.handle,0)==258
            assert process.closed==['thread','process']
            code=process.finish()
            cache=Path(result.release_directory)
            report=json.loads((cache/'desktop-selftest.json').read_text('utf8'))
            assert code==0 and report['passed'] and report['frozen']
            assert report['network_clients_absent'] and not report['real_system_backends_created']
            assert result.reused==(index==1)
            assert len(result.extracted_members)==(0 if index==1 else len(members))
            if index==1:
                assert (cache/'build-manifest.json').read_bytes()==b'cache sentinel'
                assert (cache/'.ready').read_bytes()==b'not the build id'
            else:
                for member in members:
                    # 自检会重新生成该报告，其他发布成员必须逐字节一致。
                    if member.name=='desktop-selftest.json':continue
                    assert digest(cache/member.name)==member.sha256,member.name
            assert result.request.cwd==str(cache)
            assert result.request.environment['WOWBUDDY_HOME']==str(root)
            assert result.request.environment['WOWBUDDY_EXE']==str(root/'外层测试.exe')
            scenarios.append({'scenario':label,'passed':True,'child_exit_code':code,
                'child_active_when_core_returned':alive,'reused':result.reused,
                'extracted_members':len(result.extracted_members),'gaps':result.gaps})
        finally:process.close()
    return {'passed':True,'business_sha256':manifest['executable_sha256'],
        'payload_sha256':hashlib.sha256(payload).hexdigest(),'member_count':len(members),
        'retained_test_root':str(root),'scenarios':scenarios,
        'frozen_outer_verified':False,'game_verified':False}


if __name__=='__main__':
    result=check()
    (ROOT/'dist/outer-core-check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(result,ensure_ascii=True))
