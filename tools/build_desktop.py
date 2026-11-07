"""构建独立目录版桌面程序，附带本工程插件包并验证冻结入口。"""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import sys
from build_addon import build

ROOT=Path(__file__).resolve().parents[1]


def main():
    package=ROOT/'dist/WowBuddyDev-dev.zip'
    addon_manifest=build(ROOT/'addon/WowBuddyDev',package)
    package.with_suffix('.manifest.json').write_text(json.dumps(addon_manifest,ensure_ascii=False,indent=2),'utf8')
    inputs=[ROOT/'run_dev.py',*sorted((ROOT/'desktop/wowbuddy').rglob('*.py')),
            *sorted((ROOT/'assets').glob('*.json'))]
    digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    before={p.relative_to(ROOT).as_posix():digest(p) for p in inputs}
    args=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onedir','--windowed',
          '--name','WowBuddyDev','--paths',str(ROOT/'desktop'),
          '--distpath',str(ROOT/'dist/desktop'),'--workpath',str(ROOT/'build/desktop'),
          '--specpath',str(ROOT/'build'),
          '--add-data',str(ROOT/'assets')+';assets',
          '--add-data',str(ROOT/'addon')+';addon',str(ROOT/'run_dev.py')]
    # 构建工具继承的PATH可能包含其他软件的同名ICU/CRT DLL。
    # 仅在构建子进程中使用Python与Windows系统目录，避免打包错误依赖。
    build_env=os.environ.copy()
    windows=Path(build_env.get('SystemRoot', r'C:\Windows'))
    build_env['PATH']=os.pathsep.join(map(str,[Path(sys.executable).parent,
        Path(sys.base_prefix), windows/'System32',windows]))
    subprocess.run(args,cwd=ROOT,check=True,env=build_env)
    target=ROOT/'dist/desktop/WowBuddyDev'
    (target/'packages').mkdir(exist_ok=True)
    shutil.copy2(package,target/'packages'/package.name)
    shutil.copy2(package.with_suffix('.manifest.json'),target/'packages'/package.with_suffix('.manifest.json').name)
    executable=target/'WowBuddyDev.exe'
    report_path=target/'desktop-selftest.json'
    report_path.unlink(missing_ok=True)
    result=subprocess.run([str(executable),'--desktop-selftest'],cwd=target,timeout=60)
    report=json.loads(report_path.read_text('utf8'))
    backend_path=target/'backend-selftest.json'
    backend_path.unlink(missing_ok=True)
    backend_result=subprocess.run([str(executable),'--selftest-backends'],cwd=target,timeout=60)
    backend_report=json.loads(backend_path.read_text('utf8'))
    after={p.relative_to(ROOT).as_posix():digest(p) for p in inputs}
    passed=(result.returncode==0 and report['passed'] and report['frozen']
            and report['plugin_package_present'] and report['window_closed']
            and report['temporary_removed'] and before==after
            and backend_result.returncode==0 and backend_report['passed']
            and backend_report['real_system_backends_created'] and backend_report['frozen']
            and backend_report['window_closed'] and backend_report['temporary_removed']
            and digest(target/'packages'/package.name)==addon_manifest['sha256'])
    manifest={'passed':passed,'executable_sha256':digest(executable),
              'source_files':after,'source_unchanged_during_build':before==after,
              'addon_sha256':addon_manifest['sha256'],'frozen_selftest':report,
              'backend_selftest':backend_report,
              'scope':'独立源码构建及冻结入口离屏启动；不证明游戏运行或全部功能完成'}
    (target/'build-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps({'passed':passed,'executable':str(executable),'sha256':manifest['executable_sha256']}))
    return int(not passed)


if __name__=='__main__':raise SystemExit(main())
