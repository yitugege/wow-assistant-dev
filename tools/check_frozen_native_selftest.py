"""隔离副本验证冻结自检和启动环境；仅修改临时副本的规则文件。"""
import json
import os
from pathlib import Path
import shutil
import tempfile
from check_frozen_outer import ROOT, run, file_sha256


def check():
    source=ROOT/'dist/desktop/WowBuddyDev'
    build=json.loads((source/'build-manifest.json').read_text('utf8'))
    assert build['passed']
    assert file_sha256(source/'WowBuddyDev.exe')==build['executable_sha256']
    root=Path(tempfile.mkdtemp(prefix='frozen-selftest-',dir=ROOT/'.local')).resolve()
    copy=root/'client'
    shutil.copytree(source,copy,ignore=shutil.ignore_patterns('.local'))
    rules=copy/'_internal/assets/rules.json'
    original=rules.read_bytes()
    original_digest=file_sha256(source/'_internal/assets/rules.json')
    env=dict(os.environ,QT_QPA_PLATFORM='offscreen',WOWBUDDY_NO_GAME_SCAN='1',
             PYINSTALLER_RESET_ENVIRONMENT='1')
    keys=('进程ID','程序路径','工作目录','WOWBUDDY_HOME','Windows 版本','管理员权限',
          '内存','CPU','位数','主屏','区域设置','界面语言ID')
    cases=[]
    for index,(name,value) in enumerate((('valid',None),('null',None),('number',42),
                                        ('string','1482'),('array',['1482']),('boolean',True))):
        rules.write_bytes(original if index==0 else json.dumps({'specs':value}).encode())
        data=root/name
        outcome=run(copy/'WowBuddyDev.exe',root,env,
                    arguments=['--selftest','--no-update','--data-dir',str(data)])
        report=(data/'_selftest.txt').read_text('utf8')
        assert 'C++ 引擎自检' in report
        expected='rules OK' if index==0 else 'rules 加载失败: 规则内容为空'
        assert expected in report
        log=(data/'startup.log').read_text('utf8')
        positions=[log.index('环境 '+key+' = ') for key in keys]
        assert positions==sorted(positions)
        assert positions[-1]<log.index('QApplication 构造完成')
        assert '正常退出，返回码 0' in log
        assert '独立主窗口已显示' not in log
        assert not list(data.glob('logs/monitor_*.log'))
        cases.append({'name':name,'passed':True,'environment_fields':len(keys),**outcome})
    assert file_sha256(source/'_internal/assets/rules.json')==original_digest
    return {'passed':True,'executable_sha256':build['executable_sha256'],
            'test_root':str(root),'cases':cases,'build_assets_unchanged':True,
            'game_verified':False,'addon_callbacks_runtime_verified':False}


if __name__=='__main__':
    report=check()
    (ROOT/'dist/frozen-native-selftest-current.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(report,ensure_ascii=True))
