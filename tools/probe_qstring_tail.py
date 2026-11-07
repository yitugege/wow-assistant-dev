"""隔离执行原Qt字符串复制指令，检验不同尾部内存模式；不加载或运行DLL。"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--dll',type=Path,required=True)
    parser.add_argument('--runtime',type=Path)
    args=parser.parse_args()
    if args.runtime:sys.path.insert(0,str(args.runtime))
    import pefile
    from unicorn import Uc, UcError, UC_ARCH_X86, UC_MODE_64, UC_HOOK_MEM_INVALID
    from unicorn.x86_const import UC_X86_REG_RCX,UC_X86_REG_RDX,UC_X86_REG_RSP,UC_X86_REG_RIP
    payload=args.dll.read_bytes()
    digest=hashlib.sha256(payload).hexdigest()
    if digest!='b712b4754588e89f855dc0aa087d6304b2fd21b0e0639d1cdeb9cb969bd5fb72':
        raise ValueError('DLL摘要不匹配；不能对未知版本使用固定RVA')
    pe=pefile.PE(data=payload)
    base=pe.OPTIONAL_HEADER.ImageBase
    code=pe.get_memory_mapped_image()
    cases=[]
    for name,allocation in [('zero_allocation_header',0),('valid_owned_header',0x50004000),('observed_bad_pointer',5)]:
        machine=Uc(UC_ARCH_X86,UC_MODE_64)
        machine.mem_map(base,(len(code)+4095)&~4095)
        machine.mem_write(base,code)
        machine.mem_map(0x50000000,0x100000)
        source,dest,stack,stop=0x50001000,0x50002000,0x50090000,0x500ff000
        header=struct.pack('<QQQ',allocation,0x50005000,3)
        machine.mem_write(source,header)
        machine.mem_write(0x50004000,struct.pack('<i',1))
        machine.mem_write(0x50005000,'ABC'.encode('utf-16le'))
        machine.mem_write(stack,struct.pack('<Q',stop))
        machine.reg_write(UC_X86_REG_RCX,dest)
        machine.reg_write(UC_X86_REG_RDX,source)
        machine.reg_write(UC_X86_REG_RSP,stack)
        invalid=[]
        def fault(uc,access,address,size,value,user):
            invalid.append({'access':access,'address':hex(address),'size':size})
            return False
        machine.hook_add(UC_HOOK_MEM_INVALID,fault)
        error=None
        try:machine.emu_start(base+0x16f0,stop,count=100)
        except UcError as exc:error=str(exc)
        cases.append({'case':name,'allocation_pointer':hex(allocation),'error':error,
          'returned':machine.reg_read(UC_X86_REG_RIP)==stop,
          'fault_rva':hex(machine.reg_read(UC_X86_REG_RIP)-base) if error else None,
          'invalid_access':invalid,'copied_header':bytes(machine.mem_read(dest,24)).hex(),
          'owned_reference_count':struct.unpack('<i',machine.mem_read(0x50004000,4))[0]})
    passed=(cases[0]['returned'] and cases[1]['returned']
            and cases[1]['owned_reference_count']==2
            and not cases[2]['returned'] and cases[2]['fault_rva']=='0x170e'
            and any(x['address']=='0x5' for x in cases[2]['invalid_access']))
    report={'passed':passed,'dll':str(args.dll),'sha256':digest,'cases':cases,
      'scope':'Unicorn隔离执行原DLL的QString复制构造指令；尾部模式由实验提供，不代表真实堆分布或完整GUI协议切换。'}
    (ROOT/'dist').mkdir(exist_ok=True)
    (ROOT/'dist/qstring-tail-probe.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8')
    print(json.dumps(report,ensure_ascii=False))
    return int(not passed)


if __name__=='__main__':raise SystemExit(main())
