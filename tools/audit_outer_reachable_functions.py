"""原外层内存映像的静态直接调用可达性；不执行目标，不推断间接调用目的。"""
import bisect
import hashlib
import json
from pathlib import Path
import capstone
import pefile

ROOT=Path(__file__).resolve().parents[1]
EVIDENCE=Path('D:/reverse-analysis/wow-assistant/reconstruction/evidence/outer-observations')


def main():
    path=EVIDENCE/'original-27ac1127fc/probe/outer-memory-analysis.exe'
    payload=path.read_bytes()
    digest=hashlib.sha256(payload).hexdigest()
    assert digest=='fa271e62fb423302aacdbdfcac9dd19e493b2214bfe53dfb69cab4a9ed30f520'
    pe=pefile.PE(data=payload)
    base=pe.OPTIONAL_HEADER.ImageBase
    ranges=sorted({(entry.struct.BeginAddress,entry.struct.EndAddress)
                   for entry in pe.DIRECTORY_ENTRY_EXCEPTION})
    starts=[a for a,b in ranges]
    def containing(address):
        index=bisect.bisect_right(starts,address)-1
        return ranges[index] if index>=0 and address<ranges[index][1] else None
    exported={int(p.stem,16)-base for p in (EVIDENCE/'decompiled-memory/functions').glob('0x*.c')}
    decoder=capstone.Cs(capstone.CS_ARCH_X86,capstone.CS_MODE_64)
    decoder.detail=True
    roots=[0x5154,0x4fe0,0x31d0,0x2fd0]
    pending=list(roots);seen=set();functions=[];unmapped=[]
    while pending:
        address=pending.pop()
        span=containing(address)
        if span is None:
            unmapped.append(address)
            continue
        start,end=span
        if start in seen:continue
        seen.add(start)
        direct=[];indirect=[]
        instructions=list(decoder.disasm(pe.get_data(start,end-start),base+start))
        for instruction in instructions:
            if instruction.mnemonic!='call' and not instruction.group(capstone.CS_GRP_JUMP):continue
            operand=instruction.operands[0]
            if operand.type==capstone.x86.X86_OP_IMM:
                target=operand.imm-base
                if not 0<=target<pe.OPTIONAL_HEADER.SizeOfImage:continue
                if instruction.mnemonic!='call' and start<=target<end:continue
                direct.append({'site':hex(instruction.address-base),'kind':instruction.mnemonic,'target':hex(target)})
                pending.append(target)
            else:
                indirect.append({'site':hex(instruction.address-base),'kind':instruction.mnemonic,'operand':instruction.op_str})
        if instructions:
            last=instructions[-1]
            if last.address+last.size==base+end and last.mnemonic not in ('ret','retf','jmp','int3','ud2'):
                direct.append({'site':hex(end),'kind':'fallthrough','target':hex(end)})
                pending.append(end)
        functions.append({'begin':hex(start),'end':hex(end),'has_exact_export':start in exported,
                          'outside_previous_export_range':not 0x1000<=start<0x6000,
                          'direct_edges':direct,'indirect_edges':indirect})
    functions.sort(key=lambda item:int(item['begin'],16))
    report={'source':str(path),'sha256':digest,'image_base':hex(base),'unwind_ranges':len(ranges),
            'exported_functions':len(exported),'roots':[hex(v) for v in roots],
            'reachable_functions':functions,'unmapped_targets':[hex(v) for v in sorted(set(unmapped))],
            'limitations':['仅直接call、跨范围跳转及顺序落入后继；未解析间接函数指针、回调、异常处理器或动态加载',
                           'pdata记录可能是展开分块，并非源代码函数边界',
                           '有正文不代表已实现或验证；无匹配正文不自动等于缺失业务功能']}
    output=ROOT/'dist/outer-reachable-functions.json'
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps({'report':str(output),'reachable':len(functions),
                      'outside_export_range':sum(f['outside_previous_export_range'] for f in functions),
                      'without_exact_export':sum(not f['has_exact_export'] for f in functions),
                      'unmapped_targets':len(set(unmapped))}))


if __name__=='__main__':main()
