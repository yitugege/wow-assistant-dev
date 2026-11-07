"""自有外层真实替换/重启：隔离文件及Job，不访问更新服务器。"""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
from wowbuddy.release_identity import file_sha256,read_release_identity,CACHE_NAMESPACE
from wowbuddy.launcher import release_directory,BUSINESS_EXE
from check_frozen_outer import run


def driver(config_path):
    from dataclasses import asdict
    from PySide6.QtWidgets import QApplication
    from wowbuddy.dev_outer_update import install_outer
    app=QApplication([])
    config=json.loads(Path(config_path).read_text('utf8'))
    result=install_outer(config['candidate'],config['inner'],config['outer'],
        current_version='0.2.3',arguments=['--update-now','--no-update','--desktop-selftest'],
        schedule_restart_exit=False)
    Path(config['result']).write_text(json.dumps(asdict(result),ensure_ascii=False,indent=2),'utf8')
    return 0 if result.restart_started else 1


def check(previous):
    candidate=ROOT/'dist/outer/WowBuddyDev-Outer.exe'
    build=json.loads((candidate.parent/'build-manifest.json').read_text('utf8'))
    assert file_sha256(candidate)==build['sha256']
    previous=Path(previous).resolve()
    old_identity=read_release_identity(previous);new_identity=read_release_identity(candidate)
    assert old_identity.business_sha256!=new_identity.business_sha256,'需要不同的业务构建'
    root=Path(tempfile.mkdtemp(prefix='outer-restart-中文 & ',dir=ROOT/'.local')).resolve()
    target=root/'独立更新 测试.exe';shutil.copy2(previous,target)
    local=root/'localappdata';local.mkdir()
    env=dict(os.environ,LOCALAPPDATA=str(local),PYINSTALLER_RESET_ENVIRONMENT='1')
    old_cache=Path(release_directory(str(local/CACHE_NAMESPACE/old_identity.cache_key),None))
    new_cache=Path(release_directory(str(local/CACHE_NAMESPACE/new_identity.cache_key),None))
    first=run(target,root,env)
    assert json.loads((old_cache/'desktop-selftest.json').read_text('utf8'))['passed']
    stable=root/'.local';stable.mkdir(exist_ok=True)
    sentinel=stable/'update-audit.txt';sentinel.write_text('保留稳定数据','utf8')
    config={'candidate':str(candidate),'outer':str(target),'inner':str(old_cache/BUSINESS_EXE),
            'result':str(root/'handoff.json')}
    config_path=root/'config.json';config_path.write_text(json.dumps(config),'utf8')
    outcome=run(Path(sys.executable),root,env,arguments=[str(Path(__file__).resolve()),'--driver',str(config_path)])
    handoff=json.loads(Path(config['result']).read_text('utf8'))
    assert handoff['restart_started'] and not handoff['exit_scheduled']
    assert file_sha256(target)==build['sha256']
    assert file_sha256(old_cache/BUSINESS_EXE)==old_identity.business_sha256
    assert file_sha256(new_cache/BUSINESS_EXE)==new_identity.business_sha256
    report=json.loads((new_cache/'desktop-selftest.json').read_text('utf8'))
    assert report['passed'] and report['frozen'] and report['network_clients_absent']
    assert not report['monitor_active']
    assert sentinel.read_text('utf8')=='保留稳定数据'
    assert not Path(str(target)+'.old').exists()
    assert outcome['processes_observed']>=4
    return {'passed':True,'test_root':str(root),'old_outer_sha256':file_sha256(previous),
        'new_outer_sha256':file_sha256(target),'old_business_sha256':old_identity.business_sha256,
        'new_business_sha256':new_identity.business_sha256,'first_launch':first,'restart_job':outcome,
        'handoff':handoff,'new_frozen_business_selftest_passed':True,'stable_data_preserved':True,
        'scope':'实际Qt/Win32替换和QProcess重启到不同业务构建；源码驱动器，不是冻结GUI/CLI或公开下载端到端',
        'version_fixture':'两份本地产物均标0.2.4，驱动器显式使用current_version=0.2.3，仅验证替换重启',
        'public_download_verified':False,'game_verified':False}


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='--driver':raise SystemExit(driver(sys.argv[2]))
    result=check(sys.argv[1])
    (ROOT/'dist/outer-restart-check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(result,ensure_ascii=True))
