"""目录版独立交接进程：验证父进程身份、等待退出、交换并重启。"""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from .dev_addon_install import _plain_path
from .dev_client_update import EXE,digest,validate_staged,replace_stopped_client
from .update_handoff import restart_arguments

def write_json(path,value):
    path=Path(path);temporary=path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),'utf8')
    temporary.replace(path)

def wait_for_parent(pid,executable,ready,timeout_ms=120000):
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];kernel.OpenProcess.restype=wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)]
    kernel.QueryFullProcessImageNameW.restype=wintypes.BOOL
    kernel.WaitForSingleObject.argtypes=[wintypes.HANDLE,wintypes.DWORD];kernel.WaitForSingleObject.restype=wintypes.DWORD
    kernel.CloseHandle.argtypes=[wintypes.HANDLE];kernel.CloseHandle.restype=wintypes.BOOL
    handle=kernel.OpenProcess(0x100000|0x1000,False,pid)
    if not handle:raise OSError('不能取得待退出程序句柄')
    try:
        size=wintypes.DWORD(32768);buffer=ctypes.create_unicode_buffer(size.value)
        if not kernel.QueryFullProcessImageNameW(handle,0,buffer,ctypes.byref(size)):
            raise OSError('无法确认待退出程序路径')
        if os.path.normcase(os.path.abspath(buffer.value))!=os.path.normcase(os.path.abspath(executable)):
            raise ValueError('待退出进程不是本次更新的客户端')
        ready()
        if kernel.WaitForSingleObject(handle,timeout_ms)!=0:raise TimeoutError('等待旧客户端退出超时；未替换程序')
    finally:kernel.CloseHandle(handle)

def launch_program(executable,arguments):
    process=subprocess.Popen([str(executable),*arguments],cwd=Path(executable).parent,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),close_fds=True)
    return process.pid

def prepare_handoff(staged,current,arguments,*,parent_pid=None):
    current=Path(current).absolute();staged=Path(staged).absolute()
    for path in (current,staged):_plain_path(path)
    if staged.is_relative_to(current) or current.is_relative_to(staged) or staged.drive.lower()!=current.drive.lower():
        raise ValueError('更新交接目录必须在客户端之外且位于同一卷')
    manifest_path=staged.parent/'manifest.json'
    validate_staged(staged,json.loads(manifest_path.read_text('utf8')))
    workspace=staged.parent.parent
    helper=Path(tempfile.mkdtemp(prefix='handoff-',dir=workspace))
    # 交接自身位于第三个目录，不占用待移动的旧版或暂存版文件。
    for path in (current/'_internal',*(current/'_internal').rglob('*')):_plain_path(path)
    shutil.copy2(current/EXE,helper/EXE)
    shutil.copytree(current/'_internal',helper/'_internal')
    job=helper/'job.json'
    write_json(job,{'format':1,'product':'wowbuddy-update-job','current':str(current),'staged':str(staged),
                   'parent_pid':parent_pid if parent_pid is not None else os.getpid(),
                   'original_sha256':digest(current/EXE),'manifest_sha256':digest(manifest_path),
                   'arguments':list(restart_arguments(['WowBuddyDev',*arguments]))})
    process=subprocess.Popen([str(helper/EXE),'--apply-client-update',str(job)],cwd=helper,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),close_fds=True)
    return {'job':str(job),'pid':process.pid,'process':process}

def run_handoff(job_path,*,wait=wait_for_parent,launch=launch_program):
    job_path=Path(job_path).absolute();_plain_path(job_path)
    result={'ok':False,'replaced':False,'restarted':False}
    try:
        job=json.loads(job_path.read_text('utf8'))
        if job.get('format')!=1 or job.get('product')!='wowbuddy-update-job':raise ValueError('更新交接任务无效')
        current=Path(job['current']).absolute();staged=Path(job['staged']).absolute()
        for path in (current,staged):_plain_path(path)
        if not isinstance(job['arguments'],list) or any(not isinstance(arg,str) for arg in job['arguments']):
            raise ValueError('重启参数无效')
        if digest(current/EXE)!=job['original_sha256']:raise ValueError('待更新程序已改变')
        if digest(staged.parent/'manifest.json')!=job['manifest_sha256']:raise ValueError('更新清单已改变')
        validate_staged(staged,json.loads((staged.parent/'manifest.json').read_text('utf8')))
        wait(job['parent_pid'],str(current/EXE),lambda:write_json(job_path.with_suffix('.ready.json'),{'ready':True}))
        if digest(current/EXE)!=job['original_sha256']:raise ValueError('等待期间目标程序已改变')
        result.update(replace_stopped_client(staged,current));result['replaced']=True
        result['restart_pid']=launch(current/EXE,job['arguments'])
        result.update(ok=True,restarted=True)
    except Exception as error:result['error']=str(error)
    write_json(job_path.with_suffix('.result.json'),result)
    return 0 if result['ok'] else 1
