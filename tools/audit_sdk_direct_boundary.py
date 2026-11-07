"""枚举所选低地址区域的外部直接文本调用；区域不是已证明的模块边界。"""
import hashlib
import json
import re
import struct
from collections import Counter
from pathlib import Path
import capstone
import pefile

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = Path('D:/reverse-analysis/wow-assistant/decompiled-main/functions')
LOW, HIGH = 0x140001000, 0x14000d01e
CALL = re.compile(r'FUN_(140[0-9a-f]{6})\s*\(')


def machine_references(edges):
    target = Path('D:/reverse-analysis/wow-assistant/unpacked/WOW战斗助手.exe')
    data = target.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    assert digest == '7b3c05fdbc2369f7a8fb7bb870fb0341ba1891223212e3a02b54d5c62fb9d488'
    pe = pefile.PE(data=data)
    base = pe.OPTIONAL_HEADER.ImageBase
    relocations = Counter()
    pointers = []
    for block in pe.DIRECTORY_ENTRY_BASERELOC:
        for entry in block.entries:
            relocations[entry.type] += 1
            if entry.type == 10:
                pointer = struct.unpack('<Q', pe.get_data(entry.rva, 8))[0]
                if LOW <= pointer < HIGH:
                    pointers.append({'at': hex(base + entry.rva), 'target': hex(pointer)})
    decoder = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    decoder.detail = True
    references, partial = [], []
    ranges = 0
    for entry in pe.DIRECTORY_ENTRY_EXCEPTION:
        start, end = entry.struct.BeginAddress, entry.struct.EndAddress
        if LOW <= base + start < HIGH:
            continue
        ranges += 1
        code = pe.get_data(start, end - start)
        instructions = list(decoder.disasm(code, base + start))
        decoded = sum(i.size for i in instructions)
        if decoded != len(code):
            partial.append({'start': hex(base + start), 'end': hex(base + end),
                            'first_undecoded': hex(base + start + decoded),
                            'remaining_bytes': len(code) - decoded})
        for instruction in instructions:
            for operand in instruction.operands:
                address = None
                if operand.type == capstone.x86.X86_OP_IMM:
                    address = operand.imm
                elif (operand.type == capstone.x86.X86_OP_MEM
                      and operand.mem.base == capstone.x86.X86_REG_RIP):
                    address = instruction.address + instruction.size + operand.mem.disp
                if address is not None and LOW <= address < HIGH:
                    references.append({'caller': hex(base + start), 'callee': hex(address),
                                       'at': hex(instruction.address),
                                       'mnemonic': instruction.mnemonic,
                                       'operands': instruction.op_str})
    calls = Counter((r['caller'], r['callee']) for r in references if r['mnemonic'] == 'call')
    assert calls == Counter((r['caller'], r['callee']) for r in edges)
    return {'target_sha256': digest, 'relocation_types': dict(relocations),
            'relocated_pointers_to_region': pointers, 'external_unwind_ranges': ranges,
            'partial_decode_ranges': partial, 'references': references,
            'direct_call_multiset_matches_pseudocode': True,
            'limitations': ['只检查基址重定位64位指针及异常展开表所列区域的线性反汇编',
                            '未解码尾部、无展开记录代码、运行时生成地址和间接目标不在证明范围']}


def check():
    files = sorted(REFERENCE.glob('*.c'))
    assert len(files) == 2647
    edges = []
    hashes = {}
    for path in files:
        data = path.read_bytes()
        hashes[path.name] = hashlib.sha256(data).hexdigest()
        address = int(path.stem, 16)
        if LOW <= address < HIGH:
            continue
        body = data.decode('utf-8-sig').split('// pseudocode: provider-specific; not original source')[-1]
        for line, text in enumerate(body.splitlines(), 1):
            for found in CALL.findall(text):
                callee = int(found, 16)
                if LOW <= callee < HIGH:
                    edges.append({'caller': hex(address), 'callee': hex(callee),
                                  'body_line': line, 'text': text.strip()})
    return {'scope': '2647份导出正文中的FUN_直接调用文字',
            'range_half_open': [hex(LOW), hex(HIGH)],
            'external_callers': sorted({e['caller'] for e in edges}),
            'edges': edges, 'source_sha256': hashes,
            'machine_evidence': machine_references(edges),
            'limitations': ['选定数值地址区间不是经符号证明的SDK模块边界',
                            '不覆盖函数指针、虚调用、动态解析或反编译遗漏',
                            '此处只枚举跨区调用，不能据此证明内部所有副作用均为授权']}


if __name__ == '__main__':
    result = check()
    (ROOT / 'evidence/sdk-direct-boundary.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    print(json.dumps({'callers': result['external_callers'], 'call_sites': len(result['edges'])}))
