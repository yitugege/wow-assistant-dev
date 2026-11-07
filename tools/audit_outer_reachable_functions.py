"""原外层内存映像的静态直接调用可达性；不执行目标，不推断间接调用目的。"""
import bisect
import argparse
import hashlib
import json
from pathlib import Path
import capstone
import pefile

ROOT=Path(__file__).resolve().parents[1]
EVIDENCE=Path('D:/reverse-analysis/wow-assistant/reconstruction/evidence/outer-observations')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--initializers', action='store_true', help='纳入已取证的初始化表目标')
    parser.add_argument('--follow-thunks', action='store_true', help='跟进无展开目标的直线跳板（最多8条指令）')
    parser.add_argument('--terminators', action='store_true', help='纳入aac4引用的两组终止回调表')
    args=parser.parse_args()
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
    initializer_evidence=None
    if args.initializers:
        evidence_path=ROOT/'dist/outer-initializer-tables.json'
        initializer_evidence=json.loads(evidence_path.read_text(encoding='utf8'))
        if initializer_evidence['sha256']!=digest:
            raise ValueError('初始化表与分析映像摘要不一致')
        for table in initializer_evidence['tables']:
            for entry in table['entries']:
                slot=int(entry['slot'],16)
                pointer=int(entry['value'],16)
                if int.from_bytes(pe.get_data(slot,8),'little')!=pointer:
                    raise ValueError('初始化指针与原映像不一致')
                if pointer:
                    roots.append(pointer-base)
        roots=list(dict.fromkeys(roots))
    terminator_tables=[]
    if args.terminators:
        for start,end in [(0x14360,0x14380),(0x14388,0x14390)]:
            entries=[]
            for slot in range(start,end,8):
                raw=pe.get_data(slot,8)
                if len(raw)!=8:raise ValueError('终止回调表读取不完整')
                pointer=int.from_bytes(raw,'little')
                if pointer:
                    if not 0<=pointer-base<pe.OPTIONAL_HEADER.SizeOfImage:
                        raise ValueError('终止回调指针超出映像')
                    roots.append(pointer-base)
                entries.append({'slot':hex(slot),'bytes':raw.hex(),'value':hex(pointer),
                                'target_rva':hex(pointer-base) if pointer else None})
            terminator_tables.append({'start':hex(start),'end_exclusive':hex(end),'entries':entries})
        roots=list(dict.fromkeys(roots))
    pending=list(roots);seen=set();functions=[];unmapped=[]
    examined_unmapped=set();thunks=[]
    while pending:
        address=pending.pop()
        span=containing(address)
        if span is None:
            unmapped.append(address)
            if args.follow_thunks and address not in examined_unmapped:
                examined_unmapped.add(address)
                # 仅跟进直线前缀后的直接jmp；条件分支、call及间接目标保持未知。
                prefix=[];target=None;reason='instruction_limit'
                for instruction in decoder.disasm(pe.get_data(address,64),base+address):
                    prefix.append({'site':hex(instruction.address-base),'bytes':instruction.bytes.hex(),
                                   'instruction':instruction.mnemonic+' '+instruction.op_str})
                    if instruction.mnemonic=='jmp':
                        operand=instruction.operands[0]
                        if operand.type==capstone.x86.X86_OP_IMM:
                            candidate=operand.imm-base
                            if 0<=candidate<pe.OPTIONAL_HEADER.SizeOfImage:
                                target=candidate;pending.append(target);reason='direct_jump'
                            else:reason='outside_image'
                        else:reason='indirect_jump'
                        break
                    if (instruction.group(capstone.CS_GRP_JUMP) or
                            instruction.mnemonic in ('call','ret','retf','int3','ud2')):
                        reason='stopped_at_'+instruction.mnemonic
                        break
                    if len(prefix)>=8:break
                thunks.append({'entry':hex(address),'prefix':prefix,'reason':reason,
                               'target':hex(target) if target is not None else None})
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
    if initializer_evidence is not None:
        report['initializer_evidence_sha256']=hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    if args.follow_thunks:
        report['unwindless_prefixes']=thunks
        report['limitations'].append('无展开目标最多读取8条直线指令，只跟进直接jmp；不是完整叶函数CFG')
    if args.terminators:
        report['terminator_tables']=terminator_tables
        report['terminator_table_source']='原aac4正文引用；指针读取自已核对SHA256的内存映像'
        report['limitations'].append('终止表仅证明捕获时刻的静态指针；未解析运行时注册的编码退出表')
    suffix='-with-initializers' if args.initializers else '-functions'
    if args.follow_thunks:suffix+='-thunks'
    if args.terminators:suffix+='-terminators'
    output=ROOT/f'dist/outer-reachable{suffix}.json'
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps({'report':str(output),'reachable':len(functions),
                      'outside_export_range':sum(f['outside_previous_export_range'] for f in functions),
                      'without_exact_export':sum(not f['has_exact_export'] for f in functions),
                      'unmapped_targets':len(set(unmapped))}))


if __name__=='__main__':main()
