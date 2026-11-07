"""冻结 EXE 插件安装链：隔离目录内验证实际安装、备份及失败退出。"""
import json
import os
from pathlib import Path
import shutil
import tempfile
import zipfile
import ctypes as C
from contextlib import contextmanager
from check_frozen_outer import ROOT, run, file_sha256
from build_addon import build
from wowbuddy.dev_addon_install import read_package


def snapshot(path):
    return {p.relative_to(path).as_posix():file_sha256(p)
            for p in path.rglob('*') if p.is_file()}


@contextmanager
def prevent_record_replacement(path):
    """允许读取安装记录，但用实际 Windows 共享模式拒绝替换/删除。"""
    from ctypes import wintypes as W
    kernel=C.WinDLL('kernel32',use_last_error=True)
    kernel.CreateFileW.argtypes=[W.LPCWSTR,W.DWORD,W.DWORD,C.c_void_p,W.DWORD,W.DWORD,W.HANDLE]
    kernel.CreateFileW.restype=W.HANDLE
    kernel.CloseHandle.argtypes=[W.HANDLE];kernel.CloseHandle.restype=W.BOOL
    # GENERIC_READ / FILE_SHARE_READ|FILE_SHARE_WRITE / OPEN_EXISTING。
    handle=kernel.CreateFileW(str(path),0x80000000,3,None,3,0x80,None)
    if handle==C.c_void_p(-1).value:raise C.WinError(C.get_last_error())
    try:yield
    finally:
        if not kernel.CloseHandle(handle):raise C.WinError(C.get_last_error())


def check():
    directory=ROOT/'dist/desktop/WowBuddyDev'
    outer=ROOT/'dist/outer/WowBuddyDev-Outer.exe'
    directory_build=json.loads((directory/'build-manifest.json').read_text('utf8'))
    outer_build=json.loads((outer.parent/'build-manifest.json').read_text('utf8'))
    assert directory_build['passed']
    assert file_sha256(directory/'WowBuddyDev.exe')==directory_build['executable_sha256']
    assert file_sha256(outer)==outer_build['sha256']
    root=Path(tempfile.mkdtemp(prefix='frozen-addon-中文 & ',dir=ROOT/'.local')).resolve()
    cases=[]
    env=dict(os.environ,WOWBUDDY_NO_GAME_SCAN='1',PYINSTALLER_RESET_ENVIRONMENT='1',
             QT_QPA_PLATFORM='offscreen',LOCALAPPDATA=str(root/'localappdata'))
    # 业务目录版和单文件各自使用独立安装位置、数据目录及测试 Job。
    for mode in ('directory','outer'):
        home=root/mode;home.mkdir()
        if mode=='directory':
            application=home/'application'
            shutil.copytree(directory,application,ignore=shutil.ignore_patterns('.local'))
            target=application/'WowBuddyDev.exe'
            package=application/'packages/WowBuddyDev-dev.zip'
        else:
            target=home/'独立 客户端.exe';shutil.copy2(outer,target)
            package=directory/'packages/WowBuddyDev-dev.zip'
        addons=home/'模拟客户端/Interface/AddOns'
        addons.mkdir(parents=True)
        other=addons/'OtherAddon';other.mkdir()
        (other/'OtherAddon.toc').write_text('## Title: unrelated\n','utf8')
        wtf=addons.parent.parent/'WTF';wtf.mkdir()
        (wtf/'settings.lua').write_text('sentinel="保留"','utf8')
        sentinels=(snapshot(other),snapshot(wtf))
        data=home/'data';data.mkdir()
        report=data/'_install_addon_result.txt'
        backup_root=addons.parent.parent/'WowBuddyDev-backups'
        installed_name,_=read_package(package,with_metadata=True)
        installed=addons/installed_name

        def invoke(destination,expected_exit):
            report.unlink(missing_ok=True)
            outcome=run(target,home,env,arguments=['--install-addon',
                '--install-addon-dir='+str(destination),'--data-dir',str(data)],
                # 原外层启动成功即返回0，不等待或转发业务退出码。
                expected_exit=expected_exit if mode=='directory' else 0)
            result=report.read_text('utf8')
            assert result.startswith('OK\n' if expected_exit==0 else 'FAIL\n'),result
            log=(data/'startup.log').read_text('utf8')
            assert f'正常退出，返回码 {expected_exit}' in log.splitlines()[-1],log[-500:]
            outcome['business_logged_exit']=expected_exit
            assert (snapshot(other),snapshot(wtf))==sentinels
            assert not list(data.glob('logs/monitor_*.log'))
            return outcome

        def verify_payload(package):
            from hashlib import sha256
            package_name,payload=read_package(package,with_metadata=True)
            record=json.loads((addons.parent.parent/'.wowbuddy-install.json').read_text('utf8'))
            assert record=={'product':'wowbuddy-dev','addon_directory':installed_name}
            payload[Path(installed_name+'.toc')]=payload.pop(Path(package_name+'.toc'))
            expected={str(p).replace('\\','/'):sha256(content).hexdigest() for p,content in payload.items()}
            assert snapshot(installed)==expected
            return len(expected)

        outcome=invoke(addons,0)
        count=verify_payload(package)
        assert not backup_root.exists()
        before=snapshot(installed)
        cases.append({'mode':mode,'scenario':'first_install','files':count,'passed':True,**outcome})

        # 只在隔离目录版加入真实随机命名发布包，验证优先选包及已安装身份保留。
        random_directory=None
        if mode=='directory':
            package=application/'packages/WowBuddyDev-addon.zip'
            manifest=build(ROOT/'addon/WowBuddyDev',package,random_names=True)
            package.with_suffix('.manifest.json').write_text(json.dumps(manifest),'utf8')
            random_directory=manifest['addon_directory']
        outcome=invoke(addons,0)
        count=verify_payload(package)
        backups=list(backup_root.iterdir());assert len(backups)==1
        assert snapshot(backups[0])==before
        if random_directory:assert not (addons/random_directory).exists()
        cases.append({'mode':mode,'scenario':'reinstall_random' if random_directory else 'reinstall',
                      'files':count,'backup_exact':True,'identity_preserved':True,'passed':True,**outcome})

        # 在目录交换之后、身份记录提交处触发真实共享冲突。
        # 旧目录加入包中没有的文件，避免“重装成功”被误判为“旧目录已恢复”。
        (installed/'local-change.lua').write_bytes(b'-- preserve rollback sentinel')
        rollback_before=snapshot(installed)
        backup_before=snapshot(backup_root)
        record=addons.parent.parent/'.wowbuddy-install.json'
        record_before=record.read_bytes()
        with prevent_record_replacement(record):
            outcome=invoke(addons,1)
            failure=report.read_text('utf8')
            assert 'install-record.json' in failure and '.wowbuddy-install.json' in failure,failure
            assert snapshot(installed)==rollback_before
            assert record.read_bytes()==record_before
            assert snapshot(backup_root)==backup_before
            assert not list(addons.glob('.wowbuddy-install-*'))
        cases.append({'mode':mode,'scenario':'record_commit_locked','passed':True,
                      'old_directory_restored':True,'record_unchanged':True,
                      'existing_backups_unchanged':True,**outcome})

        outcome=invoke(addons,0)
        count=verify_payload(package)
        retry_backups=list(backup_root.iterdir());assert len(retry_backups)==2
        new_backups=[p for p in retry_backups if p not in backups];assert len(new_backups)==1
        assert snapshot(new_backups[0])==rollback_before
        cases.append({'mode':mode,'scenario':'retry_after_unlock','files':count,
                      'old_custom_file_backed_up':True,'passed':True,**outcome})

        installed_before=snapshot(addons)
        occupied=home/'occupied';occupied.write_bytes(b'unchanged')
        outcome=invoke(occupied,1)
        assert occupied.read_bytes()==b'unchanged'
        assert snapshot(addons)==installed_before and len(list(backup_root.iterdir()))==2
        cases.append({'mode':mode,'scenario':'occupied_target','passed':True,**outcome})

        # 没有安装记录的手动解压包，必须沿用旧随机身份。
        manual_root=home/'manual-client'
        manual_addons=manual_root/'Interface/AddOns';manual_addons.mkdir(parents=True)
        manual_package=home/'manual-original.zip'
        manual_manifest=build(ROOT/'addon/WowBuddyDev',manual_package,random_names=True)
        manual_name=manual_manifest['addon_directory']
        with zipfile.ZipFile(manual_package) as archive:archive.extractall(manual_addons)
        manual_target=manual_addons/manual_name
        foreign=manual_addons/'w111111111111';foreign.mkdir()
        foreign_toc=foreign/(foreign.name+'.toc')
        foreign_bytes='## Title: 其他插件\n'.encode('gbk')
        foreign_toc.write_bytes(foreign_bytes)
        (manual_target/'custom.lua').write_bytes(b'original manual installation')
        manual_before=snapshot(manual_target)
        saved=manual_root/'WTF/SavedVariables'/f'{manual_name}.lua'
        saved.parent.mkdir(parents=True);saved.write_bytes(b'identity must survive')
        assert not (manual_root/'.wowbuddy-install.json').exists()
        outcome=invoke(manual_addons,0)
        manual_record=json.loads((manual_root/'.wowbuddy-install.json').read_text('utf8'))
        assert manual_record=={'product':'wowbuddy-dev','addon_directory':manual_name}
        current_name,current_payload=read_package(package,with_metadata=True)
        current_payload[Path(manual_name+'.toc')]=current_payload.pop(Path(current_name+'.toc'))
        from hashlib import sha256
        assert snapshot(manual_target)=={p.as_posix():sha256(v).hexdigest() for p,v in current_payload.items()}
        assert not (manual_addons/current_name).exists()
        manual_backups=list((manual_root/'WowBuddyDev-backups').iterdir())
        assert len(manual_backups)==1 and snapshot(manual_backups[0])==manual_before
        assert saved.read_bytes()==b'identity must survive'
        assert foreign_toc.read_bytes()==foreign_bytes
        cases.append({'mode':mode,'scenario':'manual_random_without_record','passed':True,
                      'identity_preserved':True,'backup_exact':True,'saved_variables_unchanged':True,
                      'foreign_gbk_toc_unchanged':True,**outcome})
    return {'passed':True,'test_root':str(root),'cases':cases,
            'business_sha256':directory_build['executable_sha256'],'outer_sha256':outer_build['sha256'],
            'game_installation_modified':False,'game_verified':False,
            'github_download_verified':False,'gui_button_verified':False}


if __name__=='__main__':
    result=check()
    (ROOT/'dist/frozen-addon-install.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(result,ensure_ascii=True))
