"""实际冻结GUI自动更新与重启，禁扫游戏目录，关闭仅限自建Job。"""
import json,os,shutil,sys,tempfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'desktop'))
from tools.check_frozen_outer import run
from tools.check_outer_gui import close_owned_main
from wowbuddy.launcher import release_directory,BUSINESS_EXE
from wowbuddy.release_identity import read_release_identity,CACHE_NAMESPACE,file_sha256
from wowbuddy.github_outer import verify_outer
from wowbuddy.game_windows import CtypesWindowBackend


def check(previous,manifest):
    from PySide6.QtCore import QSettings
    previous=Path(previous).resolve();expected=json.loads(Path(manifest).read_text('utf8'))
    old=read_release_identity(previous)
    assert old.business_sha256!=expected['business_sha256']
    root=Path(tempfile.mkdtemp(prefix='outer-gui-upgrade-',dir=ROOT/'.local')).resolve()
    target=root/'界面升级测试.exe';shutil.copy2(previous,target)
    local=root/'localappdata';local.mkdir();stable=root/'.local';stable.mkdir()
    old_cache=Path(release_directory(str(local/CACHE_NAMESPACE/old.cache_key),None))
    new_cache=Path(release_directory(str(local/CACHE_NAMESPACE/expected['payload_sha256'][:16]),None))
    ini=stable/'settings.ini';settings=QSettings(str(ini),QSettings.IniFormat)
    settings.setValue('update/autoCheck',True);settings.setValue('update/lastCheckMs',0)
    settings.setValue('audit/sentinel','正常GUI升级保留');settings.sync();del settings
    backend=CtypesWindowBackend();old_pids=set();new_pids=set();closed=[];new_since=None
    def observe(job):
        nonlocal new_since
        if closed:return
        current_old=[];current_new=[]
        def visit(hwnd):
            if not backend.is_visible(hwnd):return
            if backend.window_title(hwnd).text!='WowBuddyDev — 独立开发版':return
            pid=backend.window_pid(hwnd);path=Path(backend.process_path(pid))
            if path==old_cache/BUSINESS_EXE:current_old.append(pid)
            elif path==new_cache/BUSINESS_EXE:current_new.append(pid)
        backend.enum_windows(visit)
        old_pids.update(current_old);new_pids.update(current_new)
        if current_new and not current_old:
            if new_since is None:new_since=time.monotonic()
            elif time.monotonic()-new_since>=1:closed.extend(close_owned_main(job))
    env=dict(os.environ,LOCALAPPDATA=str(local),PYINSTALLER_RESET_ENVIRONMENT='1',
             QT_QPA_PLATFORM='windows',WOWBUDDY_NO_GAME_SCAN='1')
    env.pop('WOWBUDDY_UPDATE_NO_RESTART',None)
    print(json.dumps({'started':str(target),'expected_version':expected['version']}),flush=True)
    outcome=run(target,root,env,arguments=['--no-watch','--no-stealth'],on_running=observe,timeout_seconds=150)
    assert old_pids and new_pids and old_pids.isdisjoint(new_pids)
    assert closed and set(closed).issubset(new_pids)
    assert outcome['processes_observed']>=6
    verify_outer(target,expected)
    assert file_sha256(new_cache/BUSINESS_EXE)==expected['business_sha256']
    assert file_sha256(old_cache/BUSINESS_EXE)==old.business_sha256
    assert not (stable/'update-now.json').exists(),'不应经过CLI更新路径'
    settings=QSettings(str(ini),QSettings.IniFormat)
    assert settings.value('audit/sentinel')=='正常GUI升级保留'
    assert settings.value('update/autoCheck',False,type=bool)
    assert int(settings.value('update/lastCheckMs',0))>0
    del settings
    log=(stable/'startup.log').read_text('utf8')
    assert log.count('正常退出，返回码 0')>=2
    assert not list(stable.glob('logs/monitor_*.log'))
    return {'passed':True,'test_root':str(root),'old_outer_sha256':file_sha256(previous),
        'new_outer_sha256':file_sha256(target),'old_gui_pids':sorted(old_pids),'new_gui_pids':sorted(new_pids),
        'closed_new_gui_pids':closed,'job':outcome,'settings_preserved':True,
        'frozen_gui_automatic_upgrade_verified':True,'manual_button_click_verified':False,
        'game_scan_disabled':True,'game_verified':False}


if __name__=='__main__':
    report=check(sys.argv[1],sys.argv[2])
    (ROOT/'dist/outer-gui-upgrade-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(report,ensure_ascii=True),flush=True)
