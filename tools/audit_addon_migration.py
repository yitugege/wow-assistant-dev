"""逐文件审计插件迁移差异；只归一明确名称及换行，不抹去功能代码。"""
import difflib
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'desktop'))
from wowbuddy.packages import read_addon


def normalize(text):
    return text.replace('\r\n','\n').replace('P07483180','WowBuddyDev').replace('SemrepDB','WowBuddyDevDB')


def check():
    package=Path('D:/reverse-analysis/wow-assistant/unpacked/addon.bin')
    payload=package.read_bytes()
    source=ROOT/'addon/WowBuddyDev'
    rows=[];mapped=set();patches=[]
    for member in read_addon(payload):
        name='WowBuddyDev.toc' if member.name=='P07483180.toc' else member.name
        mapped.add(name)
        target=source/name
        row={'original':member.name,'current':name,'original_sha256':member.sha256}
        if not target.is_file():
            row['status']='missing'
        else:
            current=target.read_bytes()
            row['current_sha256']=hashlib.sha256(current).hexdigest()
            if current==member.data:
                row['status']='byte_equal'
            elif target.suffix.lower() in ('.lua','.toc','.xml'):
                before=normalize(member.data.decode('utf-8-sig'))
                after=normalize(current.decode('utf-8-sig'))
                row['status']='identity_or_newlines_only' if before==after else 'changed'
                if before!=after:
                    patches.extend(difflib.unified_diff(before.splitlines(True),after.splitlines(True),
                                   fromfile='original/'+member.name,tofile='current/'+name))
            else:
                row['status']='changed_binary'
        rows.append(row)
    added=sorted(p.relative_to(source).as_posix() for p in source.rglob('*')
                 if p.is_file() and p.relative_to(source).as_posix() not in mapped)
    counts={status:sum(r['status']==status for r in rows) for status in sorted({r['status'] for r in rows})}
    report={'original_package_sha256':hashlib.sha256(payload).hexdigest(),'counts':counts,
            'members':rows,'added':added,'normalizations':['CRLF to LF','P07483180 to WowBuddyDev','SemrepDB to WowBuddyDevDB'],
            'scope':'逐文件静态差异；名称归一只用于审查，不代表功能等价或全部差异获授权'}
    return report,''.join(patches)


if __name__=='__main__':
    report,diff=check()
    (ROOT/'dist').mkdir(exist_ok=True)
    (ROOT/'dist/addon-migration-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
    (ROOT/'dist/addon-migration.diff').write_text(diff,'utf-8')
    print(json.dumps({'counts':report['counts'],'added':report['added'],
                      'missing':[r['original'] for r in report['members'] if r['status']=='missing']},ensure_ascii=False))
