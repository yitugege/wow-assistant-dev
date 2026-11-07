"""原控制台初始化/写入机器码；全部WinAPI为内存记录器，不打开控制台。"""
import ctypes as C
import hashlib
import os
from pathlib import Path
import unittest


class OuterConsoleNativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path=Path('D:/reverse-analysis/wow-assistant/reconstruction/evidence/outer-observations/original-27ac1127fc/probe/outer-memory-analysis.exe')
        if os.name!='nt' or not path.exists():raise unittest.SkipTest('需要Windows原映像')
        import pefile,capstone
        data=path.read_bytes()
        if hashlib.sha256(data).hexdigest()!='fa271e62fb423302aacdbdfcac9dd19e493b2214bfe53dfb69cab4a9ed30f520':
            raise ValueError('映像身份不符')
        pe=pefile.PE(data=data);base=pe.OPTIONAL_HEADER.ImageBase
        spans=((0x11ca0,0x11ce0),(0x11ea0,0x11ef2),(0x11f10,0x11fce))
        decoder=capstone.Cs(capstone.CS_ARCH_X86,capstone.CS_MODE_64);decoder.detail=True
        k=C.WinDLL('kernel32',use_last_error=True)
        k.VirtualAlloc.argtypes=[C.c_void_p,C.c_size_t,C.c_ulong,C.c_ulong];k.VirtualAlloc.restype=C.c_void_p
        k.VirtualProtect.argtypes=[C.c_void_p,C.c_size_t,C.c_ulong,C.POINTER(C.c_ulong)]
        k.VirtualFree.argtypes=[C.c_void_p,C.c_size_t,C.c_ulong]
        addr=k.VirtualAlloc(None,0x22000,0x3000,4)
        if not addr:raise C.WinError(C.get_last_error())
        cls.addClassCleanup(lambda:k.VirtualFree(addr,0,0x8000))
        for start,end in spans:
            code=pe.get_data(start,end-start);ins=list(decoder.disasm(code,base+start))
            if sum(i.size for i in ins)!=len(code):raise ValueError('解码不完整')
            for i in ins:
                if i.mnemonic=='call' or i.group(capstone.CS_GRP_JUMP):
                    op=i.operands[0]
                    if op.type==capstone.x86.X86_OP_IMM:
                        if not any(a<=op.imm-base<b for a,b in spans):raise ValueError('未知跳转')
                    elif (i.mnemonic!='call' or op.type!=capstone.x86.X86_OP_MEM
                          or op.mem.base!=capstone.x86.X86_REG_RIP
                          or i.address+i.size+op.mem.disp-base not in (0x14008,0x14030,0x14050,0x14058)):
                        raise ValueError('未知间接调用')
            C.memmove(addr+start,code,len(code))
        name=pe.get_data(0x1ca40,16);pe.close()
        if name!='CONOUT$\0'.encode('utf-16le'):raise ValueError('控制台路径常量不符')
        C.memmove(addr+0x1ca40,name,len(name))
        old=C.c_ulong()
        if not k.VirtualProtect(addr+0x11000,0x1000,0x20,C.byref(old)):raise C.WinError(C.get_last_error())
        cls.addr=addr;cls.handle=C.c_uint64.from_address(addr+0x21a70)
        cls.ensure=C.CFUNCTYPE(C.c_int)(addr+0x11ea0)
        cls.write=C.CFUNCTYPE(C.c_int,C.c_void_p,C.c_uint,C.POINTER(C.c_uint))(addr+0x11f10)
        cls.put=C.CFUNCTYPE(C.c_uint16,C.c_uint16)(addr+0x11ca0)

    def setUp(self):
        self.events=[];self.plan=[];self.error=6;self.new_handle=456;self.count=None
        def create(name,access,share,security,disposition,flags,template):
            self.events.append(('open',name,access,share,security,disposition,flags,template))
            return self.new_handle
        def write(handle,text,count,written,reserved):
            self.events.append(('write',handle,C.string_at(text,count*2),count,reserved))
            written[0]=count if self.count is None else self.count
            return self.plan.pop(0) if self.plan else 1
        def close(handle):self.events.append(('close',handle));return 1
        def error():self.events.append(('error',self.error));return self.error
        self.callbacks=[
            C.CFUNCTYPE(C.c_void_p,C.c_wchar_p,C.c_uint,C.c_uint,C.c_void_p,C.c_uint,C.c_uint,C.c_void_p)(create),
            C.CFUNCTYPE(C.c_int,C.c_void_p,C.c_void_p,C.c_uint,C.POINTER(C.c_uint),C.c_void_p)(write),
            C.CFUNCTYPE(C.c_int,C.c_void_p)(close),C.CFUNCTYPE(C.c_uint)(error)]
        for rva,fn in zip((0x14030,0x14008,0x14050,0x14058),self.callbacks):
            C.c_void_p.from_address(self.addr+rva).value=C.cast(fn,C.c_void_p).value

    def test_initialization_cached_success_and_failure(self):
        for initial,opened,expected in ((-2,456,1),(-2,-1,0),(-1,456,0),(123,456,1)):
            with self.subTest(initial=initial,opened=opened):
                self.events.clear();self.handle.value=initial;self.new_handle=C.c_uint64(opened).value
                self.assertEqual(self.ensure(),expected);self.assertEqual(self.ensure(),expected)
                self.assertEqual(self.events,[('open','CONOUT$',0x40000000,3,None,3,0,None)] if initial==-2 else [])

    def test_retry_only_invalid_handle_and_only_once(self):
        text=C.create_string_buffer('中😀'.encode('utf-16le'));count=C.c_uint()
        for initial in (123,-1,-2):
            for error in (6,5):
                for retry_result in (0,1):
                    with self.subTest(initial=initial,error=error,retry_result=retry_result):
                        self.events.clear();self.handle.value=initial;self.error=error
                        self.plan=[0,retry_result]
                        self.assertEqual(self.write(text,3,C.byref(count)),retry_result if error==6 else 0)
                        kinds=[e[0] for e in self.events]
                        expected=['write','error']
                        if error==6:expected+=(['close'] if initial==123 else [])+['open','write']
                        self.assertEqual(kinds,expected)
                        for event in self.events:
                            if event[0]=='write':self.assertEqual(event[2:],('中😀'.encode('utf-16le'),3,None))

    def test_character_success_does_not_require_written_count(self):
        self.handle.value=123;self.count=0
        self.assertEqual(self.put(0x4e2d),0x4e2d)
        self.assertEqual([e[0] for e in self.events],['write'])
        self.events.clear();self.plan=[0];self.error=5
        self.assertEqual(self.put(0x4e2d),0xffff)
        self.assertEqual([e[0] for e in self.events],['write','error'])


if __name__=='__main__':unittest.main()
