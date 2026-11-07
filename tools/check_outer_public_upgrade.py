"""真实旧冻结外层CLI从GitHub更新；仅运行新建隔离副本。"""
import json,os,shutil,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'desktop'))
from tools.check_frozen_outer import run
from wowbuddy.launcher import release_directory,BUSINESS_EXE
from wowbuddy.release_identity import read_release_identity,CACHE_NAMESPACE,file_sha256
from wowbuddy.github_outer import verify_outer


def check(previous,expected_manifest):
    previous=Path(previous).resolve();expected=json.loads(Path(expected_manifest).read_text('utf8'))
    old=read_release_identity(previous)
    assert old.business_sha256!=expected['business_sha256']
    root=Path(tempfile.mkdtemp(prefix='outer-public-upgrade-',dir=ROOT/'.local')).resolve()
    target=root/'独立升级 测试.exe';shutil.copy2(previous,target)
    local=root/'localappdata';local.mkdir()
    stable=root/'.local';stable.mkdir()
    sentinel=stable/'upgrade-sentinel.txt';sentinel.write_text('保留用户设置','utf8')
    old_cache=Path(release_directory(str(local/CACHE_NAMESPACE/old.cache_key),None))
    env=dict(os.environ,LOCALAPPDATA=str(local),PYINSTALLER_RESET_ENVIRONMENT='1')
    env.pop('WOWBUDDY_UPDATE_NO_RESTART',None)
    print(json.dumps({'started':str(target),'expected_version':expected['version']}),flush=True)
    outcome=run(target,root,env,arguments=['--update-now','--desktop-selftest','--no-watch','--no-update'],timeout_seconds=150)
    update=json.loads((stable/'update-now.json').read_text('utf8'))
    assert update['kind']=='outer' and update['version']==expected['version']
    assert update['installed'] and update['restart_started'] and update['exit_code']==0,update
    assert update['phase']=='restart_started'
    verify_outer(target,expected)
    new=read_release_identity(target)
    new_cache=Path(release_directory(str(local/CACHE_NAMESPACE/new.cache_key),None))
    result=json.loads((new_cache/'desktop-selftest.json').read_text('utf8'))
    assert result['passed'] and result['frozen'] and not result['monitor_active']
    assert file_sha256(new_cache/BUSINESS_EXE)==new.business_sha256
    assert file_sha256(old_cache/BUSINESS_EXE)==old.business_sha256
    assert sentinel.read_text('utf8')=='保留用户设置'
    assert not Path(str(target)+'.old').exists()
    assert outcome['processes_observed']>=6
    return {'passed':True,'test_root':str(root),'old_outer_sha256':file_sha256(previous),
        'new_outer_sha256':file_sha256(target),'update_report':update,'job':outcome,
        'new_business_sha256':new.business_sha256,'new_frozen_selftest_passed':True,
        'stable_data_preserved':True,'old_business_cache_preserved':True,
        'frozen_cli_public_upgrade_verified':True,'version_override_used':False,
        'gui_button_upgrade_verified':False,'game_verified':False}


if __name__=='__main__':
    result=check(sys.argv[1],sys.argv[2])
    (ROOT/'dist/outer-public-upgrade-check.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(result,ensure_ascii=True),flush=True)
