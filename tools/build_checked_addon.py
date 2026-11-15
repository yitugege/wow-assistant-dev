"""生成并验证随机名测试插件包；只编译Lua，不执行插件或安装到游戏。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile
from lupa.lua51 import LuaRuntime

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'desktop'))
from tools.build_addon import build, check_archive, collect_files
from wowbuddy.core.dev_protocol import DEV_VERSION


def check(output):
    source=ROOT/'addon/WowBuddyDev'
    snapshot=lambda:{p.relative_to(source).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in source.rglob('*') if p.is_file()}
    before=snapshot()
    manifest=build(source,output,random_names=True)
    manifest['protocol_version']=DEV_VERSION
    lua=LuaRuntime(unpack_returned_tuples=True)
    compile_lua=lua.eval('function(s,n) local f,e=loadstring(s,n);return f~=nil,e end')
    with zipfile.ZipFile(output) as archive:
        compiled,packed_lua,references=check_archive(archive,compile_lua)
    # 打包以 TOC 为白名单，对照源也取同一份清单，不在 TOC 中的 Lua 不进包。
    if sorted(packed_lua)!=sorted(p.read_bytes() for p in collect_files(source) if p.suffix=='.lua'):
        raise ValueError('Lua源码与包内内容不一致')
    if before!=snapshot():raise ValueError('检查期间源码已变化')
    output.with_suffix('.manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),'utf8')
    report={'passed':True,'artifact':str(output),'sha256':manifest['sha256'],
            'addon_directory':manifest['addon_directory'],'members':len(manifest['members']),
            'compiled_lua':compiled,'references':references,'source_files':before,
            'lua_bytes_preserved':True,'source_unchanged':True,'installed':False,'game_verified':False}
    output.with_suffix('.check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=ROOT/'dist/WowBuddyDev-addon-local.zip')
    args=parser.parse_args()
    report=check(args.output.resolve())
    print(json.dumps({k:report[k] for k in ('passed','artifact','sha256','addon_directory','members')},ensure_ascii=False))
    print('compiled_lua='+str(len(report['compiled_lua']))+' references='+str(len(report['references'])))
