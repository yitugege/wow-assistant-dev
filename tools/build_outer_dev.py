"""将已验证的当前目录版装入自有外层PE；尚非公开更新附件。"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
from wowbuddy.launcher import BUSINESS_EXE
from wowbuddy.packages import Member,write_bundle,read_bundle
from wowbuddy.release_identity import ReleaseIdentity,file_sha256,read_release_identity


def main():
    source=ROOT/'dist/desktop/WowBuddyDev'
    manifest=json.loads((source/'build-manifest.json').read_text('utf8'))
    if not manifest['passed'] or file_sha256(source/'WowBuddyDev.exe')!=manifest['executable_sha256']:
        raise ValueError('业务构建未验证')
    for name,digest in manifest['source_files'].items():
        if file_sha256(ROOT/name)!=digest:raise ValueError('业务源码已变化，先重建：'+name)
    members=[]
    for path in sorted(source.rglob('*')):
        relative=path.relative_to(source)
        if '.local' in relative.parts:continue
        if path.is_symlink() or path.is_junction():raise ValueError('构建输入包含链接')
        if path.is_file():members.append(Member(BUSINESS_EXE if relative.as_posix()=='WowBuddyDev.exe' else relative.as_posix(),path.read_bytes()))
    payload=write_bundle(members)
    if read_bundle(payload)!=members:raise ValueError('WBD1往返失败')
    identity=ReleaseIdentity(hashlib.sha256(payload).hexdigest(),manifest['executable_sha256'])
    stage=ROOT/'build/outer-resources';stage.mkdir(parents=True,exist_ok=True)
    (stage/'payload.bin').write_bytes(payload);(stage/'identity.json').write_bytes(identity.encode())
    inputs=[ROOT/'run_outer_dev.py',*sorted((ROOT/'desktop/wowbuddy').glob('*.py'))]
    before={p.relative_to(ROOT).as_posix():file_sha256(p) for p in inputs}
    env=dict(os.environ);windows=Path(os.environ.get('SystemRoot',r'C:\Windows'))
    env['PATH']=os.pathsep.join(map(str,[Path(sys.executable).parent,Path(sys.base_prefix),windows/'System32',windows]))
    args=[sys.executable,'-m','PyInstaller','--noconfirm','--clean','--onefile','--windowed',
        '--name','WowBuddyDev-Outer','--paths',str(ROOT/'desktop'),
        '--distpath',str(ROOT/'dist/outer'),'--workpath',str(ROOT/'build/outer'),'--specpath',str(ROOT/'build'),
        '--resource',str(stage/'payload.bin')+',10,200,1033',
        '--resource',str(stage/'identity.json')+',10,203,1033',str(ROOT/'run_outer_dev.py')]
    subprocess.run(args,cwd=ROOT,env=env,check=True)
    outer=ROOT/'dist/outer/WowBuddyDev-Outer.exe'
    if read_release_identity(outer)!=identity:raise ValueError('PE身份资源不匹配')
    import pefile
    pe=pefile.PE(str(outer))
    try:
        resource=next(lang.data.struct for kind in pe.DIRECTORY_ENTRY_RESOURCE.entries if kind.id==10
            for name in kind.directory.entries if name.id==200 for lang in name.directory.entries if lang.id==1033)
        if pe.get_data(resource.OffsetToData,resource.Size)!=payload:raise ValueError('PE负载资源不匹配')
    finally:pe.close()
    after={p.relative_to(ROOT).as_posix():file_sha256(p) for p in inputs}
    if before!=after:raise ValueError('构建时源码发生变化')
    report={'built':True,'artifact':str(outer),'sha256':file_sha256(outer),'identity':json.loads(identity.encode()),
        'members':{m.name:m.sha256 for m in members},'source_files':after,
        'frozen_outer_execution_verified':False,'online_update_verified':False,'original_sdk_included':False}
    (ROOT/'dist/outer/build-manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps({'built':True,'artifact':str(outer),'sha256':report['sha256'],'members':len(members)}))


if __name__=='__main__':main()
