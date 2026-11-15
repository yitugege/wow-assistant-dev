"""九职业冻结字段页诊断与显示全部切换；仅NoSystemBackend离屏窗口。"""
from pathlib import Path
import json,os,tempfile,shutil
from PySide6.QtCore import QSettings
from check_frozen_outer import ROOT,run,file_sha256

def check():
    directory=ROOT/'dist/desktop/WowBuddyDev'
    outer=ROOT/'dist/outer/WowBuddyDev-Outer.exe'
    business_manifest=json.loads((directory/'build-manifest.json').read_text('utf8'))
    outer_manifest=json.loads((outer.parent/'build-manifest.json').read_text('utf8'))
    assert business_manifest['passed']
    assert file_sha256(directory/'WowBuddyDev.exe')==business_manifest['executable_sha256']
    assert file_sha256(outer)==outer_manifest['sha256']
    root=Path(tempfile.mkdtemp(prefix='field-ui-',dir=ROOT/'.local'))
    cases=[]
    for mode in ('directory','outer'):
        home=root/mode;home.mkdir()
        if mode=='directory':
            application=home/'application'
            shutil.copytree(directory,application,ignore=shutil.ignore_patterns('.local'))
            target=application/'WowBuddyDev.exe'
        else:
            target=home/'client.exe';shutil.copy2(outer,target)
        env=dict(os.environ,LOCALAPPDATA=str(home/'localappdata'),PYINSTALLER_RESET_ENVIRONMENT='1',QT_QPA_PLATFORM='offscreen')
        for spec in (1482,1484,1485,1486,1487,1488,1489,1490,1491):
            data=home/str(spec)
            outcome=run(target,home,env,arguments=['--desktop-dump-ui',f'--spec={spec}',
                '--toggle-showall','--data-dir',str(data)])
            report=json.loads((data/'dump-ui.json').read_text('utf8'))
            assert report['passed'] and report['spec']==str(spec),(mode,spec,report)
            assert report['backend']=='NoSystemBackend'
            assert not report['monitor_active'] and not report['watch_active']
            assert f'spec={spec}' in (data/'_ui.txt').read_text('utf8')
            showall=(data/'_showall.txt').read_text('utf8')
            assert '--toggle-showall on' in showall and '--toggle-showall off' in showall
            cases.append({'mode':mode,'spec':spec,'passed':True,'report':str(data/'dump-ui.json'),**outcome})
        # 原04a530的数字arg会再次解释动作名中的占位符；冻结程序也必须保留此语义。
        data=home/'threshold-placeholder';data.mkdir()
        fixture=data/'rotations.json'
        fixture.write_text(json.dumps({'rotations':[{'specId':1482,'specName':'诊断',
            'subKey':'test','profileName':'占位符阈值','rules':[
                {'action':'cast%1','when':['num_below','player_health_pct',30]}]}]},
            ensure_ascii=False),'utf8')
        settings=QSettings(str(data/'settings.ini'),QSettings.IniFormat)
        settings.setValue('switch/sw_player_health_pct_b30',19)
        settings.sync()
        expected='sw_cast30~player_health_pct_b%4'
        for phase in ('migrate','reopen'):
            outcome=run(target,home,env,arguments=['--desktop-dump-ui',
                f'--rotations={fixture}','--rotation=1482|test|占位符阈值',
                '--spec=1482','--data-dir',str(data)])
            report=json.loads((data/'dump-ui.json').read_text('utf8'))
            assert report['passed'] and report['backend']=='NoSystemBackend',report
            assert not report['monitor_active'] and not report['watch_active']
            settings.sync()
            assert int(settings.value('switch/'+expected,-1))==19
            assert not settings.contains('switch/sw_player_health_pct_b30')
            assert not settings.contains('switch/sw_cast%1~player_health_pct_b30')
            ui=(data/'_ui.txt').read_text('utf8')
            assert '19%' in ui,ui
            cases.append({'mode':mode,'scenario':'threshold-'+phase,'passed':True,
                'key':expected,'value':19,'report':str(data/'dump-ui.json'),**outcome})
    return {'passed':True,'cases':cases,'outer_sha256':outer_manifest['sha256'],
            'business_sha256':business_manifest['executable_sha256'],'test_root':str(root),
            'game_verified':False,'scope':'冻结字段页加载及显示全部切换，不是像素布局或实机施法验收'}

if __name__=='__main__':
    report=check()
    (ROOT/'dist/frozen-field-ui.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps({'passed':report['passed'],'cases':len(report['cases'])}))
