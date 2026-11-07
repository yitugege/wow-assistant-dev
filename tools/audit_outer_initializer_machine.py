"""保留初始化审读中关键机器码与RIP相对目标，不执行原函数。"""
import hashlib
import argparse
import json
import capstone
import pefile
from audit_outer_reachable_functions import ROOT, EVIDENCE


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--termination', action='store_true', help='导出终止路径三处ABI存疑函数的完整展开范围')
    parser.add_argument('--string-search', action='store_true', help='导出字符集合搜索四个函数的完整展开范围')
    parser.add_argument('--stream-flush', action='store_true', help='导出流刷新及文件提交四个函数的完整展开范围')
    parser.add_argument('--console-output', action='store_true', help='导出控制台恢复和UTF8文件写入的完整展开范围')
    args = parser.parse_args()
    if sum((args.termination, args.string_search, args.stream_flush, args.console_output)) > 1:
        parser.error('导出模式不能同时指定')
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
    spans = [(0x5b08, 0x5b6a), (0x5b6c, 0x5ba8),
             (0xe37c, 0xe392), (0xb844, 0xb881), (0x12200, 0x122b2)]
    if args.termination:
        ends = {e.struct.BeginAddress:e.struct.EndAddress for e in pe.DIRECTORY_ENTRY_EXCEPTION}
        spans = [(start, ends[start]) for start in (0xfc50, 0x11e04, 0x1210c)]
    if args.string_search:
        ends = {e.struct.BeginAddress:e.struct.EndAddress for e in pe.DIRECTORY_ENTRY_EXCEPTION}
        spans = [(start, ends[start]) for start in (0x4430, 0x4610, 0x4830, 0x4970)]
    if args.stream_flush:
        ends = {e.struct.BeginAddress:e.struct.EndAddress for e in pe.DIRECTORY_ENTRY_EXCEPTION}
        spans = [(start, ends[start]) for start in (0xf9c8, 0xfa54, 0x10c9c, 0x10d28)]
    if args.console_output:
        ends = {e.struct.BeginAddress:e.struct.EndAddress for e in pe.DIRECTORY_ENTRY_EXCEPTION}
        spans = [(start, ends[start]) for start in (0x11474, 0x11ca0, 0x11ea0, 0x11f10)]
    for start, end in spans:
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
    if args.string_search:
        by_address = {int(row['rva'],16): row for item in ranges for row in item['instructions']}
        for compare, branch, opcode in [(0x4690,0x4696,'jb'), (0x46df,0x46e5,'jae'),
                                         (0x474c,0x4752,'jae'), (0x476f,0x4775,'jae'),
                                         (0x47ce,0x47d4,'jae'), (0x47ef,0x47f5,'jae')]:
            if by_address[compare]['mnemonic'] != 'pcmpestri' or by_address[branch]['mnemonic'] != opcode:
                raise ValueError('字符集合比较的条件跳转与已审读机器码不符')
        if by_address[0x485e]['operands'] != 'ymm2, ymm0':
            raise ValueError('集合位图返回寄存器与原机器码不符')
    output = ROOT / ('dist/outer-termination-machine.json' if args.termination else 'dist/outer-initializer-machine.json')
    if args.string_search:
        output = ROOT / 'dist/outer-string-search-machine.json'
    if args.stream_flush:
        output = ROOT / 'dist/outer-stream-flush-machine.json'
    if args.console_output:
        output = ROOT / 'dist/outer-console-output-machine.json'
    output.write_text(json.dumps({'source': str(source), 'source_sha256': digest,
                                 'ranges': ranges, 'limitations': ['仅指定机器码区间；没有执行回调或验证独立版动态等价']},
                                ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({'report': str(output), 'ranges': len(ranges)}))


if __name__ == '__main__':
    main()
