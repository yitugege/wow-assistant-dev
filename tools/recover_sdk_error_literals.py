"""解释009400的常量分支，到001000前停止；不执行目标机器码/系统调用。"""
import hashlib
import json
from pathlib import Path
import capstone as cs
import pefile

ROOT = Path(__file__).resolve().parents[1]
BASE = 0x140000000
MASK = (1 << 64) - 1


def rc4(data, key):
    state = list(range(256))
    j = 0
    for i in range(256):
        j = (j + state[i] + key[i % len(key)]) & 255
        state[i], state[j] = state[j], state[i]
    i = j = 0
    result = []
    for value in data:
        i = (i + 1) & 255
        j = (j + state[i]) & 255
        state[i], state[j] = state[j], state[i]
        result.append(value ^ state[(state[i] + state[j]) & 255])
    return bytes(result)


def recover(pe, instructions, code):
    registers = {'rsp': 0x20010000, 'rcx': code & 0xffffffff, 'rdx': 0x30000000}
    memory = {}
    pc, comparison = BASE + 0x9400, 0
    aliases = {'eax': ('rax', 32), 'ecx': ('rcx', 32), 'edx': ('rdx', 32),
               'ebp': ('rbp', 32), 'ebx': ('rbx', 32), 'esi': ('rsi', 32),
               'edi': ('rdi', 32), 'al': ('rax', 8)}

    def reg(name):
        parent, bits = aliases.get(name, (name, 64))
        return registers.get(parent, 0) & ((1 << bits) - 1)

    def putreg(name, value):
        parent, bits = aliases.get(name, (name, 64))
        value &= (1 << bits) - 1
        registers[parent] = ((reg(parent) & ~255) | value) if bits == 8 else value

    def address(op, ins):
        m = op.mem
        first = ins.address + ins.size if m.base == cs.x86.X86_REG_RIP else reg(ins.reg_name(m.base)) if m.base else 0
        return (first + (reg(ins.reg_name(m.index)) * m.scale if m.index else 0) + m.disp) & MASK

    def read(addr, size):
        if all(addr + n in memory for n in range(size)):
            return bytes(memory[addr+n] for n in range(size))
        if BASE <= addr and addr + size <= BASE + pe.OPTIONAL_HEADER.SizeOfImage:
            return pe.get_data(addr-BASE, size)
        raise AssertionError(f'未初始化读 {addr:x}/{size}')

    def write(addr, data):
        assert 0x20000000 <= addr < 0x20020000 or 0x30000000 <= addr < 0x30001000
        memory.update((addr+n, v) for n, v in enumerate(data))

    def value(op, ins):
        if op.type == cs.x86.X86_OP_REG: return reg(ins.reg_name(op.reg))
        if op.type == cs.x86.X86_OP_IMM: return op.imm
        return int.from_bytes(read(address(op, ins), op.size), 'little')

    def assign(op, val, ins):
        if op.type == cs.x86.X86_OP_REG: putreg(ins.reg_name(op.reg), val)
        else: write(address(op, ins), (val & ((1 << (op.size*8))-1)).to_bytes(op.size, 'little'))

    def signed(val, bits):
        val &= (1 << bits)-1
        return val-(1 << bits) if val & (1 << (bits-1)) else val

    for step in range(2000):
        ins = instructions[pc]
        op, args = ins.mnemonic, ins.operands
        next_pc = pc + ins.size
        if op == 'call':
            assert args[0].type == cs.x86.X86_OP_IMM
            target = args[0].imm
            if target == BASE + 0x1000:
                return {'decode_call': hex(pc), 'encrypted_hex': read(reg('rcx'), reg('edx')).hex(), 'steps': step+1}
            assert target == BASE + 0x3cf0  # 动态CRT初始化不执行，常量构造不依赖其返回值。
        elif op == 'push':
            registers['rsp'] -= 8
            write(reg('rsp'), value(args[0], ins).to_bytes(8, 'little'))
        elif op in ('mov', 'movabs'): assign(args[0], value(args[1], ins), ins)
        elif op == 'lea': assign(args[0], address(args[1], ins), ins)
        elif op in ('add', 'sub', 'xor'):
            left, right = value(args[0], ins), value(args[1], ins)
            assign(args[0], left+right if op == 'add' else left-right if op == 'sub' else left^right, ins)
        elif op == 'cmp':
            bits = args[0].size*8
            comparison = signed(value(args[0], ins), bits)-signed(value(args[1], ins), bits)
        elif op == 'test': comparison = value(args[0], ins) & value(args[1], ins)
        elif op in ('jmp', 'je', 'jne', 'jg'):
            if op == 'jmp' or op == 'je' and comparison == 0 or op == 'jne' and comparison != 0 or op == 'jg' and comparison > 0:
                next_pc = args[0].imm
        elif op == 'rep movsq':
            count = reg('rcx')
            assert count < 128
            for _ in range(count):
                write(reg('rdi'), read(reg('rsi'), 8))
                registers['rdi'] += 8
                registers['rsi'] += 8
            registers['rcx'] = 0
        elif op != 'nop': raise AssertionError(f'未支持指令 {pc:x} {op}')
        pc = next_pc
    raise AssertionError('超出步骤限制')


def check():
    data = Path('D:/reverse-analysis/wow-assistant/unpacked/WOW战斗助手.exe').read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    assert digest == '7b3c05fdbc2369f7a8fb7bb870fb0341ba1891223212e3a02b54d5c62fb9d488'
    pe = pefile.PE(data=data)
    md = cs.Cs(cs.CS_ARCH_X86, cs.CS_MODE_64); md.detail = True
    instructions = {i.address: i for i in md.disasm(pe.get_data(0x9400, 0xf18), BASE+0x9400)}
    key = pe.get_data(0xe39c0, 16)
    assert rc4(bytes.fromhex('38cef51701d14338299d'), key) == b'msvcrt.dll'
    thresholds = set()
    for ins in instructions.values():
        if ins.mnemonic == 'cmp' and ins.op_str.startswith('ebp, '):
            thresholds.add(ins.operands[1].imm)
    samples = sorted({-(1 << 31), (1 << 31)-1} | {t+d for t in thresholds for d in (-1, 0, 1)})
    rows = []
    for code in samples:
        row = recover(pe, instructions, code)
        plain = rc4(bytes.fromhex(row['encrypted_hex']), key)
        row.update(code=code, decoded_hex=plain.hex(), text_gbk=plain.decode('gbk'),
                   fallback_format=row['decode_call'] == '0x14000a2d8')
        rows.append(row)
    return {'target_sha256': digest, 'passed': True, 'comparison_thresholds': sorted(thresholds),
            'samples': rows, 'limitations': ['受限解释器不是CPU模拟器，只支持本函数解码前已核对指令',
                'CRT初始化被跳过，停在解码调用前；不验证分配失败、格式化、拷贝或错误返回码',
                '每个比较阈值及其两侧加int32极值；文案保留GBK解码，不执行目标代码']}


if __name__ == '__main__':
    result = check()
    (ROOT/'evidence/sdk-error-literals.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf8')
    print(json.dumps({'passed': result['passed'], 'samples': len(result['samples']),
                      'unique_literals': len({r['decoded_hex'] for r in result['samples']})}))
