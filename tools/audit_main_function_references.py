"""索引全部主程序伪代码与仓库中的显式地址引用；引用不等于行为覆盖。"""
from pathlib import Path
from collections import defaultdict,Counter
import hashlib,json,re
ROOT=Path(__file__).resolve().parents[1]
REFERENCE=Path('D:/reverse-analysis/wow-assistant/decompiled-main/functions')
ADDRESS=re.compile(r'(?i)(?<![0-9a-z])(?:FUN_|0x)?(140[0-9a-f]{6})(?![0-9a-z])')
SHORT_ADDRESS=re.compile(r'(?i)(?<![0-9a-z])(?:0x)?(0[0-9a-f]{5})(?![0-9a-z])')

def check():
    files=sorted(REFERENCE.glob('*.c'))
    if not files:raise RuntimeError('缺少原主程序伪代码')
    refs=defaultdict(list)
    sources=[*ROOT.glob('*.md'),*ROOT.glob('run*.py')]
    for directory in ('desktop','addon','tests','tools'):
        sources.extend(p for p in (ROOT/directory).rglob('*') if p.suffix in ('.py','.lua','.md'))
    digests={}
    for path in sorted(set(sources)):
        relative=path.relative_to(ROOT).as_posix()
        text=path.read_text('utf-8-sig')
        kind='source' if relative.startswith(('desktop/','addon/','run')) else 'test' if relative.startswith('tests/') else 'tool' if relative.startswith('tools/') else 'document'
        for number,line in enumerate(text.splitlines(),1):
            mentions={(int(a,16),'full') for a in ADDRESS.findall(line)}
            mentions.update((0x140000000+int(a,16),'short_alias_unverified') for a in SHORT_ADDRESS.findall(line))
            for address,form in mentions:
                refs[address].append({'file':relative,'line':number,'kind':kind,'form':form})
                digests[relative]=hashlib.sha256(path.read_bytes()).hexdigest()
    rows=[]
    for path in files:
        data=path.read_bytes();text=data.decode('utf-8-sig')
        address=int(path.stem,16)
        header=re.search(r'^// address: (0x[0-9a-f]+)$',text,re.M)
        assert header and int(header[1],16)==address,path.name
        body=text.split('// pseudocode: provider-specific; not original source',1)[-1]
        rows.append({'address':hex(address),'file':path.name,'sha256':hashlib.sha256(data).hexdigest(),
                     'body_available':'// body: available' in text,'body_lines':len(body.splitlines()),
                     'explicit_references':refs.get(address,[]),
                     'body_address_mentions':sorted({hex(int(a,16)) for a in ADDRESS.findall(body) if int(a,16)!=address})})
    counts=Counter()
    for row in rows:
        counts['total']+=1
        counts['body_available']+=row['body_available']
        kinds={r['kind'] for r in row['explicit_references']}
        counts['without_address_reference_or_alias']+=not kinds
        for kind in kinds:counts[kind+'_reference']+=1
    return {'scope':'主程序导出文件与显式完整地址文字引用索引；不是语义覆盖或完成率',
            'limitations':['六位短地址仅记作待确认别名，可能与普通常量混淆；范围覆盖、间接共享实现未自动归并',
                            '文本地址引用可能属于外层或文档背景，不能据此确认实现',
                            '无引用不证明功能缺失；必须逐函数确认职责与可达性'],
            'counts':dict(counts),'referencing_file_sha256':digests,'functions':rows,
            'largest_without_reference':sorted((r for r in rows if not r['explicit_references']),
                                               key=lambda r:r['body_lines'],reverse=True)[:20],
            # 文档提及待审地址不能把函数从源码未对应队列移除。
            'largest_without_source_reference':sorted((r for r in rows
                if not any(x['kind']=='source' for x in r['explicit_references'])),
                key=lambda r:r['body_lines'],reverse=True)[:20]}

if __name__=='__main__':
    result=check();output=ROOT/'dist/main-function-reference-index.json'
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps({'counts':result['counts'],'largest':[(r['address'],r['body_lines'])
          for r in result['largest_without_reference'][:8]]},ensure_ascii=False))
