"""核对独立入口与原伪代码参数清单；静态接线不是功能完成证明。"""
import ast
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
REFERENCE=Path('D:/reverse-analysis/wow-assistant/decompiled-main/functions')
sys.path.insert(0,str(ROOT/'desktop'))
from wowbuddy.native_cli import EARLY_COMMANDS,parse_native_cli


def main():
    files=['run_dev.py','run_outer_dev.py',*[f'desktop/wowbuddy/{name}.py' for name in (
        'dev_startup','dev_native_commands','dev_staged_startup','dev_outer_entry',
        'native_cli','qt_app','threshold_widgets','window_shell')]]
    sources={name:(ROOT/name).read_text('utf-8-sig') for name in files}
    connections=[]
    for name,source in sources.items():
        for node in ast.walk(ast.parse(source)):
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='connect':
                connections.append({'file':name,'line':node.lineno,'signal':ast.unparse(node.func.value),
                                    'handlers':[ast.unparse(arg) for arg in node.args]})
    flags={};references={}
    paths=sorted(REFERENCE.glob('*.c'))
    if not paths:raise RuntimeError('未找到原伪代码，不输出空清单作为通过')
    for path in paths:
        data=path.read_bytes()
        found=set(re.findall(r'--[A-Za-z][A-Za-z0-9_-]*=?',data.decode('utf8',errors='replace')))
        if found:references[path.name]=hashlib.sha256(data).hexdigest()
        for flag in found:flags.setdefault(flag,[]).append(path.name)
    cases=[([], 'gui'),(['--crash-test'],'crash_null'),(['--crash-test=throw'],'crash_throw')]
    cases += [([flag],command) for flag,command in EARLY_COMMANDS]
    routes=[]
    for args,expected in cases:
        command=parse_native_cli(['fixture.exe',*args]).command
        assert command==expected
        file=('run_dev.py' if command=='gui' else 'desktop/wowbuddy/dev_startup.py'
              if command.startswith('crash_') else 'desktop/wowbuddy/dev_native_commands.py')
        lines=[i for i,line in enumerate(sources[file].splitlines(),1) if repr(command) in line or '"'+command+'"' in line]
        if not lines:raise AssertionError((command,file,'分派源没有显式命令引用'))
        routes.append({'arguments':args,'command':command,'dispatch_file':file,'reference_lines':lines})
    report={'scope':'独立入口静态路由、Qt信号接线与原导出参数文字；未运行业务或穷尽二进制功能',
        'source_sha256':{name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in files},
        'original_pseudocode_files_scanned':len(paths),'original_flag_source_sha256':references,
        'original_flags':flags,'routes':routes,'qt_connections':connections,
        'limitations':['命令文字引用不证明分支执行、异常处理或结果一致',
            '已导出伪代码文字搜索不覆盖动态字符串、未导出正文及全部资源',
            'Qt接线存在不证明回调语义或游戏功能通过']}
    output=ROOT/'dist/current-entry-routes.json'
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps({'report':str(output),'routes':len(routes),'qt_connections':len(connections),
                      'original_files':len(paths),'flags':sorted(flags)},ensure_ascii=False))


if __name__=='__main__':main()
