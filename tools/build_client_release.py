"""为目录版客户端生成ZIP及更新清单；排除用户数据。"""
import argparse
import json
from pathlib import Path
import sys
import zipfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
from wowbuddy.dev_client_update import digest,member_path,NAME

def build_client(source,output,version):
    source=Path(source).resolve();output=Path(output).resolve()
    if output.is_relative_to(source):raise ValueError('输出不能位于客户端内')
    members={}
    files=[]
    for path in sorted(source.rglob('*')):
        if '.local' in path.relative_to(source).parts:continue
        if path.is_symlink() or path.is_junction():raise ValueError('发布输入包含链接')
        if path.is_file():
            name=NAME+'/'+path.relative_to(source).as_posix();member_path(name)
            members[name]=digest(path);files.append((path,name))
    if not files:raise ValueError('客户端目录为空')
    output.parent.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        for path,name in files:archive.write(path,name)
    manifest={'product':'wowbuddy-client','format':1,'version':version,
              'artifact':output.name,'sha256':digest(output),'members':members}
    output.with_suffix('.manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),'utf8')
    return manifest

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--version',required=True);args=parser.parse_args()
    result=build_client(ROOT/'dist/desktop/WowBuddyDev',ROOT/'dist/release/WowBuddyDev-windows-x64.zip',args.version)
    print(json.dumps({'sha256':result['sha256'],'files':len(result['members'])}))
