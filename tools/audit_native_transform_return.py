"""只读核对006e50返回值和调用方消费；不运行EXE或其保护SDK。"""
import hashlib
import json
from pathlib import Path
import capstone
import pefile

ROOT = Path(__file__).resolve().parents[1]
TARGET = Path('D:/reverse-analysis/wow-assistant/unpacked/WOW战斗助手.exe')
EXPECTED = '7b3c05fdbc2369f7a8fb7bb870fb0341ba1891223212e3a02b54d5c62fb9d488'


def check():
    payload = TARGET.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    assert digest == EXPECTED
    pe = pefile.PE(data=payload)
    base = pe.OPTIONAL_HEADER.ImageBase
    decoder = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)

    def decode(rva, size):
        return list(decoder.disasm(pe.get_data(rva, size), base + rva))

    def rows(instructions):
        return [{'address': hex(i.address), 'bytes': bytes(i.bytes).hex(),
                 'mnemonic': i.mnemonic, 'operands': i.op_str} for i in instructions]

    thunk = decode(0x6e50, 15)
    assert [(i.mnemonic, i.op_str) for i in thunk] == [
        ('sub', 'rsp, 0x28'), ('call', hex(base + 0xae50)), ('nop', ''),
        ('add', 'rsp, 0x28'), ('ret', '')]
    transform = decode(0xae50, 0xd01e - 0xae50)
    assert transform[-1].address == base + 0xd01d
    assert [(i.mnemonic, i.op_str) for i in transform[-3:]] == [
        ('mov', 'eax, dword ptr [rsp + 0x28]'), ('add', 'rsp, 0x38'), ('ret', '')]
    callers = []
    for rva, end in ((0x5ef0, 0x6b00), (0x6e80, 0x79e0)):
        instructions = decode(rva, end - rva)
        for index, instruction in enumerate(instructions):
            if instruction.mnemonic == 'call' and instruction.op_str == hex(base + 0x6e50):
                following = instructions[index + 1:index + 5]
                consumer = following[0]
                assert (consumer.mnemonic, consumer.op_str) in (
                    ('mov', 'dword ptr [r12 + 0xcc], eax'),
                    ('add', 'eax, dword ptr [rsp + 0x60]'),
                    ('mov', 'dword ptr [r14 + 0xcc], eax'))
                callers.append({'function': hex(base + rva),
                                'call_and_following': rows(instructions[index:index + 5])})
    assert len(callers) == 3
    return {'target_sha256': digest, 'passed': True,
            'thunk': rows(thunk), 'transform_return': rows(transform[-3:]),
            'callers': callers,
            'conclusion': '006e50不改写被调用方EAX返回值；三个调用点随后读取EAX，伪代码void签名不可采用。',
            'limitations': ['静态机器码核对，不执行原程序、不调用SDK、不请求远端',
                            '不证明128分支所有算术行为或响应字段业务含义',
                            '线性反汇编仅用于所列函数内的直接调用点，不排除间接调用']}


if __name__ == '__main__':
    result = check()
    (ROOT / 'evidence/native-transform-return.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    print(json.dumps({'passed': result['passed'], 'call_sites': len(result['callers'])}))
