"""只读解析导致线性反汇编误入数据的五组两级跳转表。"""
import hashlib
import json
import struct
from pathlib import Path
import capstone
import pefile

ROOT = Path(__file__).resolve().parents[1]


def check():
    data = Path('D:/reverse-analysis/wow-assistant/unpacked/WOW战斗助手.exe').read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    assert digest == '7b3c05fdbc2369f7a8fb7bb870fb0341ba1891223212e3a02b54d5c62fb9d488'
    pe = pefile.PE(data=data)
    base = pe.OPTIONAL_HEADER.ImageBase
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    layouts = [
        (0x51fd0, 0x524a7, 0x520dc, 'rdx', 0x524c8, 100, 0x524a8, 8),
        (0xab770, 0xabb9e, 0xab816, 'r12', 0xabba8, 79, 0xabba0, 2),
        (0xab770, 0xabb9e, 0xab8ce, 'rsi', 0xabc00, 79, 0xabbf8, 2),
        (0xab770, 0xabb9e, 0xab96a, 'r14', 0xabc58, 79, 0xabc50, 2),
        (0xab770, 0xabb9e, 0xaba1a, 'r14', 0xabcb0, 79, 0xabca8, 2),
    ]
    result = []
    for start, code_end, dispatch, register, map_rva, count, table_rva, slots in layouts:
        instructions = list(md.disasm(pe.get_data(start, code_end-start), base+start))
        assert sum(i.size for i in instructions) == code_end-start
        boundaries = {i.address-base for i in instructions}
        at = next(n for n, i in enumerate(instructions) if i.address == base+dispatch)
        actual = instructions[at:at+4]
        assert [(i.mnemonic, i.op_str) for i in actual] == [
            ('movzx', f'eax, byte ptr [{register} + rax + {hex(map_rva)}]'),
            ('mov', f'ecx, dword ptr [{register} + rax*4 + {hex(table_rva)}]'),
            ('add', f'rcx, {register}'), ('jmp', 'rcx')]
        mapping = list(pe.get_data(map_rva, count))
        assert len(mapping) == count and max(mapping) < slots
        targets = list(struct.unpack('<' + 'I'*slots, pe.get_data(table_rva, slots*4)))
        assert all(start <= target < code_end and target in boundaries for target in targets)
        result.append({'function': hex(base+start), 'dispatch': hex(base+dispatch),
                       'map_rva': hex(map_rva), 'map_indices': mapping,
                       'target_table_rva': hex(table_rva),
                       'targets': [hex(base+t) for t in targets],
                       'all_targets_local_instruction_boundaries': True})
    return {'target_sha256': digest, 'passed': True, 'tables': result,
            'index_entries': sum(len(r['map_indices']) for r in result),
            'limitations': ['五组已人工核对输入范围及映像基址寄存器的表，不枚举全程序间接跳转',
                            '静态表与指令边界检查，不执行原程序或证明分支业务语义']}


if __name__ == '__main__':
    result = check()
    (ROOT/'evidence/native-switch-tables.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf8')
    print(json.dumps({'passed': result['passed'], 'tables': len(result['tables']),
                      'index_entries': result['index_entries']}))
