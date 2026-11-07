"""逐项核对原0a0cf0静态圣印表；不执行原程序或游戏。"""
from pathlib import Path
import hashlib,json,re,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'desktop'))
from wowbuddy.scheduler import SEAL_IDS

def check():
    source=Path('D:/reverse-analysis/wow-assistant/decompiled-main/functions/0x1400a0cf0.c')
    text=source.read_text('utf8')
    # 每个名字构造QString后紧跟一个技能ID赋值，再拷贝该QString至表项。
    pattern=r'L"(seal_[a-z]+)";\s*local_[a-f0-9]+ = [^;]+;\s*pQVar2 = \(QString \*\)QString::QString\([^;]+;\s*local_[a-f0-9]+ = (0x[a-f0-9]+);\s*QString::QString\([^;]+pQVar2\);'
    pairs=re.findall(pattern,text)
    literals=re.findall(r'L"(seal_[a-z]+)"',text)
    assert len(pairs)==len(literals)==21,('unexpected native table layout',len(pairs),len(literals))
    native={int(number,16):name for name,number in pairs}
    assert len(native)==21 and native==SEAL_IDS
    return {'function':'0x1400a0cf0','pseudocode_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
            'implementation':'desktop/wowbuddy/scheduler.py:SEAL_IDS',
            'entries':[{'spell_id':int(number,16),'field':name} for name,number in pairs],
            'equal':True,'native_execution':False,'scope':'已导出静态表常量逐项对照，不证明游戏回执或有效持续时间'}

if __name__=='__main__':
    result=check()
    (ROOT/'evidence/native-seal-table.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps({'equal':result['equal'],'entries':len(result['entries'])}))
