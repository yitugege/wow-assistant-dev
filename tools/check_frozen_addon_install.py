"""冻结 EXE 插件安装链：隔离目录内验证实际安装、备份及失败退出。"""
import json
import os
from pathlib import Path
import shutil
import tempfile
from check_frozen_outer import ROOT, run, file_sha256
from build_addon import build
from wowbuddy.dev_addon_install import read_package


def snapshot(path):
    return {p.relative_to(path).as_posix():file_sha256(p)
            for p in path.rglob('*') if p.is_file()}


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
            assert record=={'product':'wowbuddy-dev','addon_directory':'WowBuddyDev'}
            payload[Path('WowBuddyDev.toc')]=payload.pop(Path(package_name+'.toc'))
            expected={str(p).replace('\\','/'):sha256(content).hexdigest() for p,content in payload.items()}
            assert snapshot(addons/'WowBuddyDev')==expected
            return len(expected)

        outcome=invoke(addons,0)
        count=verify_payload(package)
        assert not backup_root.exists()
        before=snapshot(addons/'WowBuddyDev')
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

        installed_before=snapshot(addons)
        occupied=home/'occupied';occupied.write_bytes(b'unchanged')
        outcome=invoke(occupied,1)
        assert occupied.read_bytes()==b'unchanged'
        assert snapshot(addons)==installed_before and len(list(backup_root.iterdir()))==1
        cases.append({'mode':mode,'scenario':'occupied_target','passed':True,**outcome})
    return {'passed':True,'test_root':str(root),'cases':cases,
            'business_sha256':directory_build['executable_sha256'],'outer_sha256':outer_build['sha256'],
            'game_installation_modified':False,'game_verified':False,
            'github_download_verified':False,'gui_button_verified':False}


if __name__=='__main__':
    result=check()
    (ROOT/'dist/frozen-addon-install.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(result,ensure_ascii=True))
