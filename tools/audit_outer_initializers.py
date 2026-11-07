"""读取原内存映像中由4fe0引用的初始化指针表；不执行回调。"""
import csv
import hashlib
import json
import struct
import capstone
import pefile
from audit_outer_reachable_functions import ROOT,EVIDENCE


def main():
    path=EVIDENCE/'original-27ac1127fc/probe/outer-memory-analysis.exe'
    payload=path.read_bytes()
    digest=hashlib.sha256(payload).hexdigest()
    assert digest=='fa271e62fb423302aacdbdfcac9dd19e493b2214bfe53dfb69cab4a9ed30f520'
    pe=pefile.PE(data=payload);base=pe.OPTIONAL_HEADER.ImageBase
    inventory=ROOT/'dist/outer-ghidra-remaining/functions.tsv'
    names={int(row['rva'],16):row['name'] for row in csv.DictReader(inventory.open(encoding='utf8'),delimiter='\t')}
    decoder=capstone.Cs(capstone.CS_ARCH_X86,capstone.CS_MODE_64)
    tables=[]
    for label,start,end in [('int_initializers',0x14320,0x14358),
                            ('void_initializers',0x14308,0x14318),
                            ('tls_callback_slot',0x22d50,0x22d58),
                            ('tls_destructor_slot',0x22d48,0x22d50)]:
        entries=[]
        for slot in range(start,end,8):
            pointer=struct.unpack('<Q',pe.get_data(slot,8))[0]
            item={'slot':hex(slot),'value':hex(pointer)}
            if pointer:
                rva=pointer-base
                assert 0<=rva<pe.OPTIONAL_HEADER.SizeOfImage
                instructions=[]
                for instruction in decoder.disasm(pe.get_data(rva,80),pointer):
                    instructions.append({'rva':hex(instruction.address-base),
                                         'instruction':instruction.mnemonic+' '+instruction.op_str})
                    if instruction.mnemonic=='ret':break
                item.update(target_rva=hex(rva),provider_name=names.get(rva),prefix_instructions=instructions)
            entries.append(item)
        tables.append({'name':label,'start':hex(start),'end_exclusive':hex(end),'entries':entries})
    report={'source':str(path),'sha256':digest,'caller_rva':'0x4fe0',
            'table_addresses_source':'原4fe0伪代码；58f8/5900机器码lea结果',
            'inventory_sha256':hashlib.sha256(inventory.read_bytes()).hexdigest(),'tables':tables,
            'limitations':['值来自捕获时刻的内存映像；不证明所有历史时刻相同',
                           '未运行回调，未证明间接调用图完整；80字节仅为前缀']}
    output=ROOT/'dist/outer-initializer-tables.json'
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps({'report':str(output),'non_null_targets':sum(bool(int(e['value'],16)) for t in tables for e in t['entries'])}))


if __name__=='__main__':main()
