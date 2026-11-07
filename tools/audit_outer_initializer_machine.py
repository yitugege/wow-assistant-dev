"""保留初始化审读中关键机器码与RIP相对目标，不执行原函数。"""
import hashlib
import json
import capstone
import pefile
from audit_outer_reachable_functions import ROOT, EVIDENCE


def main():
    source = EVIDENCE / 'original-27ac1127fc/probe/outer-memory-analysis.exe'
    payload = source.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    if digest != 'fa271e62fb423302aacdbdfcac9dd19e493b2214bfe53dfb69cab4a9ed30f520':
        raise ValueError('原映像摘要不匹配')
    pe = pefile.PE(data=payload)
    base = pe.OPTIONAL_HEADER.ImageBase
    decoder = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    decoder.detail = True
    ranges = []
    for start, end in [(0x5b08, 0x5b6a), (0x5b6c, 0x5ba8),
                       (0xe37c, 0xe392), (0xb844, 0xb881), (0x12200, 0x122b2)]:
        code = pe.get_data(start, end-start)
        rows = []
        for instruction in decoder.disasm(code, base+start):
            targets = [hex(instruction.address + instruction.size + operand.mem.disp - base)
                       for operand in instruction.operands
                       if operand.type == capstone.x86.X86_OP_MEM and operand.mem.base == capstone.x86.X86_REG_RIP]
            rows.append({'rva': hex(instruction.address-base), 'bytes': instruction.bytes.hex(),
                         'mnemonic': instruction.mnemonic, 'operands': instruction.op_str,
                         'rip_targets': targets})
        if sum(len(bytes.fromhex(row['bytes'])) for row in rows) != len(code):
            raise ValueError(f'指令解码未覆盖整个请求范围: {start:#x}')
        ranges.append({'start': hex(start), 'end_exclusive': hex(end),
                       'sha256': hashlib.sha256(code).hexdigest(), 'instructions': rows})
    output = ROOT / 'dist/outer-initializer-machine.json'
    output.write_text(json.dumps({'source': str(source), 'source_sha256': digest,
                                 'ranges': ranges, 'limitations': ['仅指定机器码区间；没有执行回调或验证独立版动态等价']},
                                ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({'report': str(output), 'ranges': len(ranges)}))


if __name__ == '__main__':
    main()
