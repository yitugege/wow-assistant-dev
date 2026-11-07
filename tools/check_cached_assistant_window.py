"""用真实旧版GUI窗口验证跨缓存排除；仅关闭本次Job窗口。"""
import json,os,shutil,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'desktop'))
from tools.check_frozen_outer import run
from tools.check_outer_gui import close_owned_main
from wowbuddy.launcher import release_directory,BUSINESS_EXE
from wowbuddy.release_identity import read_release_identity,CACHE_NAMESPACE,file_sha256
from wowbuddy.game_windows import CtypesWindowBackend,enumerate_windows
from wowbuddy.dev_game_windows import AssistantWindowFilter


def check(previous):
    from PySide6.QtCore import QSettings
    previous=Path(previous).resolve();old_identity=read_release_identity(previous)
    current=ROOT/'dist/outer/WowBuddyDev-Outer.exe';identity=read_release_identity(current)
    assert identity.business_sha256!=old_identity.business_sha256
    root=Path(tempfile.mkdtemp(prefix='cache-window-',dir=ROOT/'.local')).resolve()
    outer=root/'旧版测试.exe';shutil.copy2(previous,outer)
    local=root/'localappdata';local.mkdir()
    namespace=local/CACHE_NAMESPACE
    old_cache=Path(release_directory(str(namespace/old_identity.cache_key),None))
    new_cache=Path(release_directory(str(namespace/identity.cache_key),None));new_cache.mkdir(parents=True)
    shutil.copy2(ROOT/'dist/desktop/WowBuddyDev/WowBuddyDev.exe',new_cache/BUSINESS_EXE)
    shutil.copy2(ROOT/'dist/desktop/WowBuddyDev/build-manifest.json',new_cache/'build-manifest.json')
    assert file_sha256(new_cache/BUSINESS_EXE)==identity.business_sha256
    stable=root/'.local';stable.mkdir()
    settings=QSettings(str(stable/'settings.ini'),QSettings.IniFormat)
    settings.setValue('update/autoCheck',False);settings.sync();del settings
    backend=CtypesWindowBackend();filtered=AssistantWindowFilter(backend,current_executable=new_cache/BUSINESS_EXE)
    observed=[];closed=[]
    def observe(job):
        if closed or not (old_cache/'_ui.txt').exists():return
        before=enumerate_windows(backend).windows
        own=[w.hwnd for w in before if Path(backend.process_path(backend.window_pid(w.hwnd)))==old_cache/BUSINESS_EXE]
        if not own:return
        after={w.hwnd for w in enumerate_windows(filtered).windows}
        assert not set(own)&after,'旧缓存助手仍在候选窗口列表'
        observed.extend(own);closed.extend(close_owned_main(job))
    env=dict(os.environ,LOCALAPPDATA=str(local),PYINSTALLER_RESET_ENVIRONMENT='1')
    outcome=run(outer,root,env,arguments=['--dump-ui','--no-watch','--no-update','--no-stealth'],on_running=observe)
    assert observed and closed
    return {'passed':True,'test_root':str(root),'old_business_sha256':old_identity.business_sha256,
        'new_business_sha256':identity.business_sha256,'excluded_real_hwnds':observed,
        'closed_job_pids':closed,**outcome,'scope':'当前源码过滤器识别真实旧冻结GUI；新构建未运行，非游戏测试'}


if __name__=='__main__':
    report=check(sys.argv[1])
    (ROOT/'dist/cache-window-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(report,ensure_ascii=True))
